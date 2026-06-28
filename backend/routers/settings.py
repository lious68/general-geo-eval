"""设置管理路由 - 含 ModelVerse 中转平台一键配置"""
from fastapi import APIRouter, HTTPException, Depends
from routers.auth import require_admin
import json
import os
import sys
import database as db
import models

router = APIRouter(prefix="/api/settings", tags=["settings"])

# core 模块路径（品牌档案）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from brand_profile import derive_from_input, default_brand_profile

# 原厂模型配置
MODELS_CONFIG = {
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat", "api_key_env": "DEEPSEEK_API_KEY", "has_search": False, "search_note": "官方API无内置联网"},
    "ernie": {"name": "文心一言", "base_url": "https://qianfan.baidubce.com/v2", "model": "ernie-4.0-8k", "api_key_env": "ERNIE_API_KEY", "has_search": True, "search_note": "通过Qianfan AppBuilder"},
    "doubao": {"name": "豆包", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-pro-32k", "api_key_env": "DOUBAO_API_KEY", "has_search": True, "search_note": "extra_body.enable_search"},
    "kimi": {"name": "Kimi", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k", "api_key_env": "KIMI_API_KEY", "has_search": True, "search_note": "builtin_function:$web_search"},
    "qwen": {"name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "api_key_env": "QWEN_API_KEY", "has_search": True, "search_note": "enable_search+forced_search"},
}

# ModelVerse 中转平台配置
MODELVERSE_CONFIG = {
    "base_url": "https://api.modelverse.cn/v1",
    "api_key": os.getenv("MODELVERSE_API_KEY", "jzSvXwLaaE9g03Pc0fC043Fe-0Fb7-4665-bC2A-10EdA49d"),
    "models": {
        "deepseek": "deepseek-chat",
        "ernie": "ernie-4.0-8k",
        "doubao": "doubao-pro-32k",
        "kimi": "moonshot-v1-8k",
        "qwen": "qwen-plus",
    }
}


@router.get("/models")
async def get_models():
    """获取模型配置"""
    use_modelverse = await db.get_setting("use_modelverse", "false")
    result = []
    for key, cfg in MODELS_CONFIG.items():
        api_key = await db.get_setting(f"api_key_{key}", "")
        custom_model = await db.get_setting(f"model_{key}", cfg["model"])
        custom_url = await db.get_setting(f"base_url_{key}", cfg["base_url"])
        result.append({
            "key": key,
            "name": cfg["name"],
            "base_url": custom_url,
            "model": custom_model,
            "has_api_key": bool(api_key),
            "api_key_preview": f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "",
            "has_search": cfg.get("has_search", False),
            "search_note": cfg.get("search_note", ""),
        })
    return {
        "success": True,
        "data": {
            "models": result,
            "use_modelverse": use_modelverse == "true",
            "modelverse_base_url": MODELVERSE_CONFIG["base_url"],
            "modelverse_api_key_preview": "*** (via MODELVERSE_API_KEY)" if os.getenv("MODELVERSE_API_KEY") else f"{MODELVERSE_CONFIG['api_key'][:8]}...{MODELVERSE_CONFIG['api_key'][-6:]}",
        }
    }


@router.put("/models/{model_key}")
async def update_model(model_key: str, req: models.ModelConfigUpdate, user=Depends(require_admin)):
    """更新单个模型配置"""
    if model_key not in MODELS_CONFIG:
        raise HTTPException(400, f"未知模型: {model_key}")
    if req.api_key is not None:
        await db.set_setting(f"api_key_{model_key}", req.api_key)
    if req.model is not None:
        await db.set_setting(f"model_{model_key}", req.model)
    if req.base_url is not None:
        await db.set_setting(f"base_url_{model_key}", req.base_url)
    return {"success": True}


@router.post("/modelverse/enable")
async def enable_modelverse(user=Depends(require_admin)):
    """一键启用 ModelVerse 中转平台 - 所有模型使用统一API"""
    mv = MODELVERSE_CONFIG
    for model_key, model_name in mv["models"].items():
        await db.set_setting(f"api_key_{model_key}", mv["api_key"])
        await db.set_setting(f"base_url_{model_key}", mv["base_url"])
        await db.set_setting(f"model_{model_key}", model_name)
    await db.set_setting("use_modelverse", "true")
    return {"success": True, "message": f"已启用 ModelVerse 中转，配置了 {len(mv['models'])} 个模型"}


@router.post("/modelverse/disable")
async def disable_modelverse(user=Depends(require_admin)):
    """关闭 ModelVerse，恢复原厂配置"""
    for model_key, cfg in MODELS_CONFIG.items():
        await db.set_setting(f"base_url_{model_key}", cfg["base_url"])
        await db.set_setting(f"model_{model_key}", cfg["model"])
        # 不清除 API Key，保留用户之前配的
    await db.set_setting("use_modelverse", "false")
    return {"success": True, "message": "已恢复原厂配置"}


@router.post("/models/{model_key}/test")
async def test_model(model_key: str, enable_search: bool = False):
    """测试模型连通性（可选测试联网搜索）"""
    if model_key not in MODELS_CONFIG:
        raise HTTPException(400, f"未知模型: {model_key}")

    api_key = await db.get_setting(f"api_key_{model_key}", "")
    if not api_key:
        return {"success": False, "message": "API Key 未配置"}

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
        os.environ[MODELS_CONFIG[model_key]["api_key_env"]] = api_key
        from model_clients import ModelClient
        from brand_profile import default_brand_profile
        client = ModelClient(model_key)
        # 用当前被测品牌名做连通性测试
        profile = db.get_brand_profile()
        test_name = profile.brand_name or default_brand_profile().brand_name
        response = client.chat(f"请用一句话介绍{test_name}", None, enable_search=enable_search)
        if response.get("error"):
            return {"success": False, "message": response["error"]}
        content = response.get("content", "")
        mentioned = any(name and name in content for name in profile.display_names) or (test_name in content)
        return {"success": True, "data": {"response": content[:500], "brand_mentioned": mentioned, "search_enabled": enable_search}}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/keywords")
async def get_keywords():
    """获取品牌关键词"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
    import config
    saved = await db.get_setting("brand_keywords", "")
    if saved:
        return {"success": True, "data": json.loads(saved)}
    return {"success": True, "data": {k: v for k, v in config.BRAND_KEYWORDS.items()}}


@router.put("/keywords")
async def update_keywords(req: models.KeywordsUpdate, user=Depends(require_admin)):
    """更新品牌关键词"""
    await db.set_setting("brand_keywords", req.json(ensure_ascii=False))
    return {"success": True}


@router.get("/weights")
async def get_weights():
    """获取评分权重"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
    import config
    saved = await db.get_setting("geo_weights", "")
    if saved:
        return {"success": True, "data": json.loads(saved)}
    return {"success": True, "data": config.SCORE_CONFIG["geo_weights"]}


@router.put("/weights")
async def update_weights(req: models.WeightsUpdate, user=Depends(require_admin)):
    """更新评分权重"""
    await db.set_setting("geo_weights", req.json())
    return {"success": True}


# ============ 品牌档案 ============

@router.get("/brand-profile")
async def get_brand_profile():
    """兜底：返回当前品牌档案（兼容旧前端）。新前端用 /api/brands/current。"""
    bid = await db.get_current_brand_id()
    b = await db.get_brand(bid)
    if not b:
        return {"success": True, "data": {"configured": False, **default_brand_profile().to_dict()}}
    return {"success": True, "data": {"configured": True, **b["brand_profile"]}}


@router.put("/brand-profile")
async def update_brand_profile(req: models.BrandProfileUpdate, user=Depends(require_admin)):
    """兜底：更新当前品牌档案。新前端用 PUT /api/brands/{id}。"""
    if not req.brand_name.strip():
        raise HTTPException(400, "品牌名不能为空")
    profile = derive_from_input(req.brand_name, req.company_name, req.website, req.industry)
    bid = await db.get_current_brand_id()
    if not await db.get_brand(bid):
        await db.create_brand(bid, profile)  # 兜底新建
    else:
        await db.update_brand(bid, profile)
    return {"success": True, "data": profile.to_dict(),
            "message": f"已更新当前品牌档案：{profile.brand_name}（{profile.industry or '未填行业'}）"}
