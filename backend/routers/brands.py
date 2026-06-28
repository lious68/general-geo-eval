"""品牌库路由：多品牌 CRUD + 当前品牌切换。"""
import sys
import os
from fastapi import APIRouter, HTTPException, Depends
from routers.auth import require_admin
import models
import database as db

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from brand_profile import derive_from_input, default_brand_profile

router = APIRouter(prefix="/api/brands", tags=["brands"])


def _slugify(s: str) -> str:
    """品牌名 → slug：小写、非字母数字下划线转下划线。"""
    import re
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w]+", "_", s, flags=re.UNICODE)
    return s.strip("_") or "brand"


@router.get("")
async def list_brands():
    items = await db.list_brands()
    return {"success": True, "data": items}


@router.post("")
async def create_brand(req: models.BrandCreate, user=Depends(require_admin)):
    brand_id = req.brand_id or _slugify(req.brand_name)
    if not req.brand_name.strip():
        raise HTTPException(400, "品牌名不能为空")
    profile = derive_from_input(req.brand_name, req.company_name, req.website, req.industry)
    try:
        created = await db.create_brand(brand_id, profile)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "data": created,
            "message": f"已创建品牌「{profile.brand_name}」({brand_id})"}


@router.get("/current")
async def get_current_brand():
    bid = await db.get_current_brand_id()
    b = await db.get_brand(bid)
    if not b:
        # current 指向已删品牌时回退 ucloud
        await db.set_current_brand_id("ucloud")
        b = await db.get_brand("ucloud")
    return {"success": True, "data": b}


@router.put("/current")
async def set_current_brand(req: models.CurrentBrandUpdate, user=Depends(require_admin)):
    b = await db.get_brand(req.brand_id)
    if not b:
        raise HTTPException(404, f"品牌 {req.brand_id} 不存在")
    await db.set_current_brand_id(req.brand_id)
    return {"success": True, "data": b, "message": f"已切换到品牌「{b['brand_name']}」"}


@router.get("/{brand_id}")
async def get_brand(brand_id: str):
    b = await db.get_brand(brand_id)
    if not b:
        raise HTTPException(404, "品牌不存在")
    return {"success": True, "data": b}


@router.put("/{brand_id}")
async def update_brand(brand_id: str, req: models.BrandUpdate, user=Depends(require_admin)):
    if not req.brand_name.strip():
        raise HTTPException(400, "品牌名不能为空")
    profile = derive_from_input(req.brand_name, req.company_name, req.website, req.industry)
    if not await db.get_brand(brand_id):
        raise HTTPException(404, "品牌不存在")
    await db.update_brand(brand_id, profile)
    return {"success": True, "data": {"id": brand_id, **profile.to_dict()},
            "message": f"已更新品牌「{profile.brand_name}」"}


@router.delete("/{brand_id}")
async def delete_brand(brand_id: str, user=Depends(require_admin)):
    try:
        await db.delete_brand(brand_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "message": f"已删除品牌 {brand_id}"}
