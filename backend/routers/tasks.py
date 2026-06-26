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
    """建任务，固定总题集。仅传 name 时默认全部题（任务=GEO计算总集）。"""
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


@router.post("/{task_id}/recalculate")
async def recalculate_task(task_id: str, user=Depends(require_admin)):
    """重算单个 task 的 GEO 评分（按当前 analysis_results 覆盖 geo_scores）。

    用于修复历史数据：citation_rate 等指标随 _result_to_analysis/分析口径更新后，
    无需重新导入即可刷新评分。
    """
    if not await db.get_task(task_id):
        raise HTTPException(404, "任务不存在")
    await task_service.recalculate_task_scores(task_id)
    return {"success": True, "message": f"任务 {task_id} 评分已重算"}


@router.post("/recalculate-all")
async def recalculate_all_tasks(user=Depends(require_admin)):
    """重算全部 task 的 GEO 评分（批量刷新历史数据）。"""
    tasks = await db.list_tasks()
    recalc = 0
    for t in tasks:
        await task_service.recalculate_task_scores(t["id"])
        recalc += 1
    return {"success": True, "data": {"recalculated": recalc},
            "message": f"已重算 {recalc} 个任务的评分"}


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


@router.post("/{task_id}/batches/{batch_id}/repush")
async def repush_batch(task_id: str, batch_id: str, user=Depends(require_admin)):
    """重新触发 webhook 推送（Win 离线/丢失时手动重推）。"""
    try:
        ok = await task_service.repush_batch(task_id, batch_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"success": True, "data": {"pushed": ok},
            "message": "已重推" if ok else "推送失败（Win 未达），批次保留可再重推"}


@router.post("/{task_id}/batches/{batch_id}/import-results")
async def import_batch_results(task_id: str, batch_id: str,
                               file: UploadFile = File(...), user=Depends(require_admin)):
    """导入本地 runner 结果 JSON 到指定批次（pin batch_id），按 (task,model,question) 合并去重 + 重算。"""
    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"JSON 解析失败: {e}")
    try:
        result = await task_service.import_batch_results(
            task_id, data, batch_id=batch_id,
            file_name=file.filename, file_size=len(content)
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "data": result,
            "message": f"批次 {batch_id} 已导入 {result['results_inserted']} 条结果并重算评分"}


@router.get("/{task_id}/batches/{batch_id}/results")
async def get_batch_results(task_id: str, batch_id: str):
    """取某批次已导入的分析结果（带题目原文），供前端展开查看问题+答案。"""
    rows = await task_service.get_batch_results(task_id, batch_id)
    return {"success": True, "data": rows}


@router.get("/{task_id}/batches/{batch_id}/import-logs")
async def get_batch_import_logs(task_id: str, batch_id: str):
    """取某批次的导入审计日志（时间倒序）。"""
    rows = await task_service.get_batch_import_logs(task_id, batch_id)
    return {"success": True, "data": rows}


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
        result = await task_service.import_batch_results(
            task_id, data, file_name=file.filename, file_size=len(content)
        )
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
