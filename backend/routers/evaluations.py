"""评测管理路由"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from typing import Optional
import database as db
import models
from services.eval_runner import start_evaluation

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


class ConnectionManager:
    def __init__(self):
        self.active: dict = {}

    async def connect(self, run_id: str, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(run_id, []).append(ws)

    def disconnect(self, run_id: str, ws: WebSocket):
        if run_id in self.active:
            self.active[run_id].remove(ws)

    async def broadcast(self, run_id: str, data: dict):
        for ws in self.active.get(run_id, []):
            try:
                await ws.send_json(data)
            except Exception:
                pass


ws_manager = ConnectionManager()


@router.post("")
async def create_evaluation(req: models.EvaluationCreate):
    """创建评测任务"""
    try:
        run_id = await start_evaluation(
            name=req.name,
            model_keys=req.model_keys,
            question_ids=req.question_ids,
            categories=req.categories,
            temperature=req.temperature,
            delay=req.delay,
            ws_manager=ws_manager,
        )
        return {"success": True, "data": {"run_id": run_id}}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("")
async def list_evaluations(limit: int = 50, offset: int = 0):
    """列出评测"""
    runs = await db.get_runs(limit, offset)
    for r in runs:
        try:
            r["model_keys"] = __import__("json").loads(r["model_keys"]) if isinstance(r["model_keys"], str) else r["model_keys"]
            r["question_ids"] = __import__("json").loads(r["question_ids"]) if isinstance(r["question_ids"], str) else r["question_ids"]
            r["config"] = __import__("json").loads(r["config"]) if isinstance(r["config"], str) else r["config"]
        except Exception:
            pass
    return {"success": True, "data": runs}


@router.get("/{run_id}")
async def get_evaluation(run_id: str):
    """获取评测详情"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")
    try:
        run["model_keys"] = __import__("json").loads(run["model_keys"]) if isinstance(run["model_keys"], str) else run["model_keys"]
        run["question_ids"] = __import__("json").loads(run["question_ids"]) if isinstance(run["question_ids"], str) else run["question_ids"]
        run["config"] = __import__("json").loads(run["config"]) if isinstance(run["config"], str) else run["config"]
    except Exception:
        pass
    return {"success": True, "data": run}


@router.delete("/{run_id}")
async def delete_evaluation(run_id: str):
    """删除评测"""
    await db.delete_run(run_id)
    return {"success": True}


@router.websocket("/ws/{run_id}")
async def evaluation_ws(ws: WebSocket, run_id: str):
    """WebSocket 实时进度"""
    await ws_manager.connect(run_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(run_id, ws)
