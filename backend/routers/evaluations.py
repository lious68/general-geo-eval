"""评测管理路由"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query, UploadFile, File, Form
from typing import Optional
import json
import uuid
from datetime import datetime
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
async def delete_evaluation(run_id: str):
    """删除评测"""
    await db.delete_run(run_id)
    return {"success": True}


@router.post("/{run_id}/cancel")
async def cancel_evaluation(run_id: str):
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


@router.post("/import-results")
async def import_local_results(
    file: UploadFile = File(..., description="本地 Playwright runner 导出的 JSON 文件"),
    run_name: str = Form("本地WebChat导入"),
):
    """导入本地 Playwright WebChat 评测结果

    接收 local_webchat_runner.py 导出的 JSON 文件，
    创建 evaluation_run 记录，写入 analysis_results 和 geo_scores。
    """
    try:
        content = await file.read()
        data = json.loads(content)
    except Exception as e:
        raise HTTPException(400, f"JSON 解析失败: {e}")

    # 验证数据格式
    if "analysis_results" not in data or "questions" not in data:
        raise HTTPException(400, "JSON 格式不正确: 缺少 analysis_results 或 questions 字段")

    analysis_results = data.get("analysis_results", {})
    questions = data.get("questions", [])
    geo_scores_data = data.get("geo_scores", {})
    model_keys = list(analysis_results.keys())

    if not model_keys:
        raise HTTPException(400, "没有可用的模型数据")

    # 生成 run_id
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_local_" + uuid.uuid4().hex[:6]

    # 收集所有问题ID
    question_ids = [q["id"] for q in questions]

    # 创建评测运行记录
    total = sum(len(v) for v in analysis_results.values())
    try:
        await db.create_run(run_id, run_name, model_keys, question_ids, {
            "mode": "webchat_local",
            "source": "local_playwright",
            "total_results": total,
        }, mode="webchat")
    except Exception as e:
        raise HTTPException(500, f"创建评测记录失败: {e}")

    # 写入 analysis_results
    inserted = 0
    try:
        for mk, results in analysis_results.items():
            for r in results:
                await db.save_analysis_result(run_id, r)
                inserted += 1
    except Exception as e:
        await db.delete_run(run_id)
        raise HTTPException(500, f"写入分析结果失败: {e}")

    # 写入 geo_scores
    if geo_scores_data:
        try:
            for mk, scores_by_cat in geo_scores_data.items():
                model_name = analysis_results[mk][0].get("model_name", mk) if analysis_results.get(mk) else mk
                for cat, scores in scores_by_cat.items():
                    # cat 为 None 表示全局评分
                    await db.save_geo_scores(run_id, mk, model_name, cat, scores)
        except Exception as e:
            # geo_scores 写入失败不阻塞，可以后续重新计算
            import logging
            logging.getLogger(__name__).warning(f"写入 geo_scores 失败 (可手动重新计算): {e}")

    # 标记为已完成
    await db.update_run_status(run_id, "completed", total)

    return {
        "success": True,
        "data": {
            "run_id": run_id,
            "models": model_keys,
            "questions": len(question_ids),
            "results_inserted": inserted,
        },
        "message": f"成功导入 {inserted} 条结果，{len(model_keys)} 个模型，{len(question_ids)} 个问题",
    }


@router.post("/export-webchat-config")
async def export_webchat_config(req: models.EvaluationCreate):
    """导出 WebChat 本地评测任务配置

    前端选择 WebChat 模型后调用此接口，返回一个 task_config.json，
    用户将此文件下载到本地电脑，运行 local_webchat_runner.py 即可自动按配置执行。

    配置包含：模型列表、品类筛选、问题范围、延迟等参数。
    """
    # 验证必须是 webchat 模式
    if req.mode != "webchat":
        raise HTTPException(400, "mode 必须是 'webchat'")

    # 获取问题列表
    try:
        questions = await db.get_questions(
            category=req.categories[0] if req.categories and len(req.categories) == 1 else None,
            active_only=True,
        )
        if req.categories:
            questions = [q for q in questions if q["category"] in req.categories]
    except Exception:
        questions = []

    # 如果指定了 question_ids，进一步筛选
    if req.question_ids:
        questions = [q for q in questions if q["id"] in req.question_ids]

    if not questions:
        raise HTTPException(400, "没有可评估的问题")

    # 生成任务配置
    config = {
        "version": 1,
        "generated_at": datetime.utcnow().isoformat(),
        "task": {
            "name": req.name,
            "model_keys": req.model_keys,
            "delay": req.delay,
        },
        "questions": questions,
        "question_ids": [q["id"] for q in questions],
        "categories": req.categories or [],
    }

    return {
        "success": True,
        "data": config,
        "message": f"已生成 {len(questions)} 个问题、{len(req.model_keys)} 个模型的 WebChat 任务配置",
    }
