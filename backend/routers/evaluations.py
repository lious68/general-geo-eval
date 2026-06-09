"""评测管理路由"""
import json
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from typing import Optional
import database as db
import models
from services.eval_runner import start_evaluation, cancel_evaluation
from database import verify_session

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
            mode=req.mode,
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


@router.post("/{run_id}/cancel")
async def cancel_evaluation_endpoint(run_id: str):
    """强制取消运行中的评测任务"""
    ok = await cancel_evaluation(run_id)
    if not ok:
        raise HTTPException(404, f"评测任务 {run_id} 不存在或已结束")
    return {"success": True}


@router.post("/import/results")
async def import_results(req: models.ResultsBatchImport):
    """批量导入本地 WebChat 评测结果

    本地跑完 WebChat 后，将分析结果通过此接口写入服务器数据库。
    自动创建 evaluation_run 记录、保存分析结果、计算 GEO 评分。
    """
    from datetime import datetime
    import uuid

    model_key = req.model_key
    results = req.results

    if not results:
        raise HTTPException(400, "没有可导入的结果")

    # 1. 创建 evaluation_run
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    question_ids = [r.question_id for r in results]
    await db.create_run(
        run_id, req.name, [model_key], question_ids,
        {"mode": req.mode, "source": "local_webchat"}, mode=req.mode
    )
    await db.update_run_status(run_id, "running")

    # 2. 保存分析结果
    completed = 0
    for r in results:
        result_dict = {
            "question_id": r.question_id,
            "model_key": r.model_key,
            "model_name": r.model_name,
            "ucloud_mentioned": r.ucloud_mentioned,
            "ucloud_mention_count": r.ucloud_mention_count,
            "ucloud_rank": r.ucloud_rank,
            "has_citation": r.has_citation,
            "citation_count": r.citation_count,
            "ucloud_recommended": r.ucloud_recommended,
            "recommendation_strength": r.recommendation_strength,
            "sentiment_score": r.sentiment_score,
            "sentiment_label": r.sentiment_label,
            "position_weight": r.position_weight,
            "response_length": r.response_length,
            "raw_content": r.raw_content,
            "competitor_mentions": r.competitor_mentions,
            "error_message": r.error_message,
            "citations": r.citations,
            "all_cited_urls": r.all_cited_urls,
        }
        await db.save_analysis_result(run_id, result_dict)
        completed += 1

    # 3. 计算 GEO 评分（使用共享函数）
    from services.eval_runner import calculate_and_save_geo_scores
    model_name = results[0].model_name if results else model_key
    formatted_results = [r.dict() for r in results]
    questions_list = await _get_all_questions()
    await calculate_and_save_geo_scores(run_id, model_key, model_name, formatted_results, questions_list)

    # 4. 更新状态为完成
    await db.update_run_status(run_id, "completed", completed)

    return {"success": True, "data": {"run_id": run_id, "completed": completed}}


async def _get_all_questions():
    """获取所有活跃问题"""
    db_conn = await db.get_db()
    try:
        cursor = await db_conn.execute("SELECT * FROM questions WHERE is_active=1")
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db_conn.close()


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
