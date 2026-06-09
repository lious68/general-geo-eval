"""设置管理路由 - 含 ModelVerse 中转平台一键配置"""
from fastapi import APIRouter, HTTPException
import json
import os
import sys
import database as db
import models

router = APIRouter(prefix="/api/settings", tags=["settings"])

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
async def update_model(model_key: str, req: models.ModelConfigUpdate):
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
async def enable_modelverse():
    """一键启用 ModelVerse 中转平台 - 所有模型使用统一API"""
    mv = MODELVERSE_CONFIG
    for model_key, model_name in mv["models"].items():
        await db.set_setting(f"api_key_{model_key}", mv["api_key"])
        await db.set_setting(f"base_url_{model_key}", mv["base_url"])
        await db.set_setting(f"model_{model_key}", model_name)
    await db.set_setting("use_modelverse", "true")
    return {"success": True, "message": f"已启用 ModelVerse 中转，配置了 {len(mv['models'])} 个模型"}


@router.post("/modelverse/disable")
async def disable_modelverse():
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
        client = ModelClient(model_key)
        response = client.chat("请用一句话介绍UCloud优刻得", None, enable_search=enable_search)
        if response.get("error"):
            return {"success": False, "message": response["error"]}
        content = response.get("content", "")
        mentioned = any(kw in content for kw in ["UCloud", "ucloud", "优刻得"])
        return {"success": True, "data": {"response": content[:500], "ucloud_mentioned": mentioned, "search_enabled": enable_search}}
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
async def update_keywords(req: models.KeywordsUpdate):
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
async def update_weights(req: models.WeightsUpdate):
    """更新评分权重"""
    await db.set_setting("geo_weights", req.json())
    return {"success": True}
