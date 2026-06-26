"""批次状态机路由：Win 守护进程回报状态 + 拉待处理批次。"""
from fastapi import APIRouter, HTTPException, Depends
from routers.auth import require_admin
import models
import database as db

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.get("/pending")
async def list_pending(user=Depends(require_admin)):
    rows = await db.list_pending_batches()
    return {"success": True, "data": rows}


@router.post("/{batch_id}/status")
async def update_batch_status(batch_id: str, body: models.BatchStatusUpdate,
                              user=Depends(require_admin)):
    run = await db.get_run_by_batch_id(batch_id)
    if not run:
        raise HTTPException(404, "批次不存在")
    await db.update_run_status(run["id"], body.status, body.completed)
    return {"success": True, "data": {"batch_id": batch_id, "status": body.status}}
