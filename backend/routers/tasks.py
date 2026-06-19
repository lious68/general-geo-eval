"""三级任务路由：任务 → 模型 → 问题（仅 WebChat 模式范围）。"""
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from routers.auth import require_admin
import models
import database as db
from services import task_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("")
async def create_task(req: models.TaskCreate, user=Depends(require_admin)):
    """建任务，固定总题集。"""
    if not req.question_ids and not req.categories:
        raise HTTPException(400, "需提供 question_ids 或 categories 之一")
    qids = await task_service.resolve_question_ids(req.question_ids, req.categories)
    if not qids:
        raise HTTPException(400, "没有可评估的问题")
    task = await task_service.create_task_with_questions(req.name, qids, req.categories)
    return {"success": True, "data": task, "message": f"已创建任务，固定题集 {len(qids)} 题"}


@router.get("")
async def list_tasks():
    """任务列表（含覆盖率摘要）。"""
    items = await task_service.build_task_list_summary()
    return {"success": True, "data": items}


@router.get("/{task_id}")
async def get_task(task_id: str):
    detail = await task_service.build_task_detail(task_id)
    if not detail:
        raise HTTPException(404, "任务不存在")
    return {"success": True, "data": detail}


@router.delete("/{task_id}")
async def delete_task(task_id: str, user=Depends(require_admin)):
    if not await db.get_task(task_id):
        raise HTTPException(404, "任务不存在")
    await db.delete_task(task_id)
    return {"success": True}


@router.post("/{task_id}/batches")
async def create_batch(task_id: str, req: models.BatchCreate, user=Depends(require_admin)):
    """建下载批次，返回 v2 配置 JSON（前端下载，本地 runner 消费）。"""
    try:
        config = await task_service.create_batch_config(
            task_id, req.model_keys, req.per_model_question_ids, req.delay
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "data": config,
            "message": f"已生成批次配置（{len(req.model_keys)} 模型）"}


@router.get("/{task_id}/batches/{batch_id}/config")
async def get_batch_config(task_id: str, batch_id: str):
    """取某批次已持久化的 v2 配置，供前端重新下载（重下/重跑）。"""
    try:
        config = await task_service.get_batch_config(task_id, batch_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"success": True, "data": config}


@router.post("/{task_id}/import-results")
async def import_results(task_id: str, file: UploadFile = File(...),
                         user=Depends(require_admin)):
    """导入本地 runner 结果 JSON，按 (task,model,question) 合并去重 + 重算。"""
    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON 解析失败: {e}")
    try:
        result = await task_service.import_batch_results(task_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "data": result,
            "message": f"已导入 {result['results_inserted']} 条结果并重算评分"}


@router.get("/{task_id}/scores")
async def get_scores(task_id: str, category: Optional[str] = None):
    rows = await db.get_task_scores(task_id, category)
    return {"success": True, "data": rows}


@router.get("/{task_id}/details")
async def get_details(task_id: str, model_key: Optional[str] = None, limit: int = 200, offset: int = 0):
    rows = await db.get_task_results(task_id, model_key)
    total = len(rows)
    items = rows[offset: offset + limit]
    page = (offset // limit) + 1 if limit else 1
    return {"success": True, "data": {"items": items, "total": total, "page": page, "page_size": limit}}
