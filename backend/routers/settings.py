"""设置管理路由"""
from fastapi import APIRouter
import json
import database as db
import models

router = APIRouter(prefix="/api/settings", tags=["settings"])

MODELS_CONFIG = {
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    "ernie": {"name": "文心一言", "base_url": "https://qianfan.baidubce.com/v2", "model": "ernie-4.0-8k"},
    "doubao": {"name": "豆包", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-pro-32k"},
    "kimi": {"name": "Kimi", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "qwen": {"name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
}


@router.get("/models")
async def get_models():
    """获取模型配置"""
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
        })
    return {"success": True, "data": result}


@router.put("/models/{model_key}")
async def update_model(model_key: str, req: models.ModelConfigUpdate):
    """更新模型配置"""
    if model_key not in MODELS_CONFIG:
        from fastapi import HTTPException
        raise HTTPException(400, f"未知模型: {model_key}")
    if req.api_key is not None:
        await db.set_setting(f"api_key_{model_key}", req.api_key)
    if req.model is not None:
        await db.set_setting(f"model_{model_key}", req.model)
    if req.base_url is not None:
        await db.set_setting(f"base_url_{model_key}", req.base_url)
    return {"success": True}


@router.post("/models/{model_key}/test")
async def test_model(model_key: str):
    """测试模型连通性"""
    if model_key not in MODELS_CONFIG:
        from fastapi import HTTPException
        raise HTTPException(400, f"未知模型: {model_key}")

    api_key = await db.get_setting(f"api_key_{model_key}", "")
    if not api_key:
        return {"success": False, "message": "API Key 未配置"}

    try:
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
        os.environ[MODELS_CONFIG[model_key].get("api_key_env", "")] = api_key
        from model_clients import ModelClient
        client = ModelClient(model_key)
        response = client.chat("请用一句话介绍UCloud优刻得", None)
        if response.get("error"):
            return {"success": False, "message": response["error"]}
        content = response.get("content", "")
        mentioned = any(kw in content for kw in ["UCloud", "ucloud", "优刻得"])
        return {"success": True, "data": {"response": content[:200], "ucloud_mentioned": mentioned}}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/keywords")
async def get_keywords():
    """获取品牌关键词"""
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
    import config
    saved = await db.get_setting("brand_keywords", "")
    if saved:
        return {"success": True, "data": json.loads(saved)}
    return {"success": True, "data": {k: v for k, v in config.BRAND_KEYWORDS.items()}}


@router.put("/keywords")
async def update_keywords(req: models.KeywordsUpdate):
    """更新品牌关键词"""
    await db.set_setting("brand_keywords", req.json(ensure_ascii=False))
    return {"success": True}


@router.get("/weights")
async def get_weights():
    """获取评分权重"""
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
    import config
    saved = await db.get_setting("geo_weights", "")
    if saved:
        return {"success": True, "data": json.loads(saved)}
    return {"success": True, "data": config.SCORE_CONFIG["geo_weights"]}


@router.put("/weights")
async def update_weights(req: models.WeightsUpdate):
    """更新评分权重"""
    await db.set_setting("geo_weights", req.json())
    return {"success": True}
