"""评测管理路由"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query, Depends
from routers.auth import require_admin
from typing import Optional
import database as db
import models
from services.eval_runner import start_evaluation, _active_tasks, _dict_to_analysis, _scores_to_dict
from database import verify_session
from metrics import MetricsCalculator

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
async def create_evaluation(req: models.EvaluationCreate, user=Depends(require_admin)):
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
            mode=req.mode,
            enable_search=req.enable_search,
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
async def delete_evaluation(run_id: str, user=Depends(require_admin)):
    """删除评测"""
    await db.delete_run(run_id)
    return {"success": True}


@router.post("/{run_id}/cancel")
async def cancel_evaluation(run_id: str, user=Depends(require_admin)):
    """取消正在运行的评测"""
    # 取消后台 asyncio task
    task = _active_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        _active_tasks.pop(run_id, None)
    # 更新状态为 cancelled
    await db.update_run_status(run_id, "cancelled")
    return {"success": True, "message": "评测已取消"}


@router.websocket("/ws/{run_id}")
async def evaluation_ws(ws: WebSocket, run_id: str, token: str = None):
    """WebSocket 实时进度

    鉴权方式：浏览器 WebSocket 无法设置自定义 header，
    因此 token 通过 query param ?token=xxx 传递。
    如果 token 无效则关闭连接。
    """
    # 验证 token（WebSocket 不走中间件，需手动鉴权）
    if not token or not await verify_session(token):
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws_manager.connect(run_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(run_id, ws)



@router.post("/{run_id}/recalculate-scores")
async def recalculate_scores(run_id: str):
    """从 analysis_results 重新计算 geo_scores

    用于本地导入后 geo_scores 缺失的情况。
    """
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    # 获取所有 analysis_results
    results_by_model = {}
    db_conn = await db.get_db()
    try:
        cursor = await db_conn.execute(
            "SELECT * FROM analysis_results WHERE run_id=?", (run_id,)
        )
        for row in await cursor.fetchall():
            r = dict(row)
            mk = r["model_key"]
            results_by_model.setdefault(mk, []).append(r)
    finally:
        await db_conn.close()

    if not results_by_model:
        raise HTTPException(400, "没有 analysis_results 数据")

    # 重新计算
    calculator = MetricsCalculator()
    brand_profile = db.get_brand_profile()
    total = 0
    for mk, results in results_by_model.items():
        model_name = results[0].get("model_name", mk)
        analysis_objects = [_dict_to_analysis(r) for r in results]
        scores = calculator.calculate_scores(analysis_objects, brand_profile=brand_profile)
        await db.save_geo_scores(run_id, mk, model_name, None, _scores_to_dict(scores))
        total += len(results)

    return {
        "success": True,
        "data": {"run_id": run_id, "models": list(results_by_model.keys()), "total_results": total},
        "message": f"已重新计算 {len(results_by_model)} 个模型的 GEO 评分",
    }


