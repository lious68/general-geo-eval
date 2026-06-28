"""
通用 GEO 评估 Web 应用 - FastAPI 入口
含鉴权中间件：设置/评测/问题管理接口需登录
"""
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 添加 core 模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from database import init_db, verify_session
from routers import evaluations, results, questions, settings, auth, webchat, tasks, batches, brands


# 需要鉴权的路径前缀
PROTECTED_PREFIXES = [
    "/api/settings",
    "/api/evaluations",
    "/api/questions",
    "/api/webchat/auth",
    "/api/tasks",
    "/api/batches",
    "/api/brands",
]
# 不需要鉴权的路径
PUBLIC_PATHS = [
    "/api/auth/login",
    "/api/auth/check",
    "/api/health",
    "/api/results",
    "/api/questions/categories",
    "/api/questions/types",
    "/api/webchat/auth/status",
    "/api/evaluations/ws/",     # WebSocket 连接：token 通过 query param 或初始消息验证
    "/docs",
    "/openapi.json",
    "/redoc",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库 + 配置日志"""
    import logging
    logging.basicConfig(level=logging.INFO)
    await init_db()
    yield


app = FastAPI(
    title="通用 GEO 评估系统",
    description="评估任意品牌在 AI 模型中的品牌可见度（GEO）",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 鉴权中间件
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """鉴权中间件：保护管理类接口"""
    path = request.url.path

    # 静态文件和根路径放行
    if not path.startswith("/api/"):
        return await call_next(request)

    # 公开接口放行
    for pub in PUBLIC_PATHS:
        if path.startswith(pub):
            return await call_next(request)

    # 检查是否需要鉴权
    needs_auth = any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)
    if not needs_auth:
        return await call_next(request)

    # 验证 token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        user_info = await verify_session(token)
        if user_info:
            request.state.user = user_info
            return await call_next(request)

    return JSONResponse(
        status_code=401,
        content={"detail": "未登录或登录已过期，请重新登录"}
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "GEO Eval", "version": "2.0.0"}

# 注册路由
app.include_router(auth.router)
app.include_router(evaluations.router)
app.include_router(results.router)
app.include_router(questions.router)
app.include_router(settings.router)
app.include_router(webchat.router)
app.include_router(tasks.router)
app.include_router(batches.router)
app.include_router(brands.router)

# 静态文件（Vue 构建产物）— 必须最后挂载
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
