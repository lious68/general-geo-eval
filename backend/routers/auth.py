"""认证路由"""
import hashlib
import secrets
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import database as db

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)

# 需要鉴权的路由前缀
PROTECTED_PREFIXES = ["/api/settings", "/api/evaluations", "/api/questions", "/api/auth/users"]


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        if stored.startswith("scrypt$"):
            _, salt, expected = stored.split("$")
            actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        else:
            actual, expected = hashlib.sha256(password.encode()).hexdigest(), stored
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """验证当前用户，返回用户信息 dict"""
    if not credentials:
        raise HTTPException(401, "未登录")
    user_info = await db.verify_session(credentials.credentials)
    if not user_info:
        raise HTTPException(401, "登录已过期，请重新登录")
    return user_info


async def require_admin(request: Request):
    """依赖：仅管理员可操作"""
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


@router.post("/login")
async def login(body: dict):
    """登录（支持用户名+密码，兼容旧密码自动迁移）"""
    username = body.get("username", "admin").strip()
    password = body.get("password", "")

    if not username:
        raise HTTPException(400, "用户名不能为空")

    # 查找用户
    user = await db.get_user_by_username(username)

    if not user:
        # 旧密码兼容：如果 username=admin 且 users 表为空，检查旧的 admin_password_hash
        if username == "admin":
            stored_hash = await db.get_admin_password_hash()
            if not stored_hash:
                raise HTTPException(403, "管理员尚未初始化，请联系服务器管理员")
            # 验证旧密码
            if not verify_password(password, stored_hash):
                raise HTTPException(401, "用户名或密码错误")
            # 迁移旧密码到 users 表
            await db.create_user("admin", hash_password(password), "admin")
            token = secrets.token_hex(32)
            await db.create_session(token, "admin", "admin")
            return {"success": True, "data": {"token": token, "role": "admin", "username": "admin", "is_first_login": False}}
        raise HTTPException(401, "用户名或密码错误")

    # 正常验证
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")

    if not user["password_hash"].startswith("scrypt$"):
        await db.update_user_password(user["username"], hash_password(password))
    token = secrets.token_hex(32)
    await db.create_session(token, user["username"], user["role"])
    return {"success": True, "data": {"token": token, "role": user["role"], "username": user["username"], "is_first_login": False}}


@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """登出"""
    if credentials:
        await db.delete_session(credentials.credentials)
    return {"success": True}


@router.get("/check")
async def check_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """检查登录状态"""
    has_password = bool(await db.get_admin_password_hash()) or bool(await db.list_users())
    if not credentials:
        return {"success": True, "data": {"authenticated": False, "has_password": has_password}}
    user_info = await db.verify_session(credentials.credentials)
    if not user_info:
        return {"success": True, "data": {"authenticated": False, "has_password": has_password}}
    return {"success": True, "data": {"authenticated": True, "has_password": has_password, "role": user_info["role"], "username": user_info["username"]}}


@router.post("/change-password")
async def change_password(body: dict, user_info: dict = Depends(get_current_user)):
    """修改当前用户密码"""
    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")

    user = await db.get_user_by_username(user_info["username"])
    if not user or not verify_password(old_password, user["password_hash"]):
        raise HTTPException(401, "原密码错误")
    if len(new_password) < 12:
        raise HTTPException(400, "新密码至少12位")

    await db.update_user_password(user_info["username"], hash_password(new_password))
    # 清除该用户所有旧会话
    db_conn = await db.get_db()
    try:
        await db_conn.execute("DELETE FROM admin_sessions WHERE username=?", (user_info["username"],))
        await db_conn.commit()
    finally:
        await db_conn.close()

    token = secrets.token_hex(32)
    await db.create_session(token, user_info["username"], user_info["role"])
    return {"success": True, "data": {"token": token}}


# ============ 用户管理（仅管理员） ============

@router.get("/users")
async def list_users_endpoint(user_info: dict = Depends(get_current_user)):
    """列出所有用户"""
    if user_info.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    users = await db.list_users()
    return {"success": True, "data": users}


@router.post("/users")
async def create_user_endpoint(body: dict, user_info: dict = Depends(get_current_user)):
    """创建用户"""
    if user_info.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    username = body.get("username", "").strip()
    password = body.get("password", "")
    role = body.get("role", "viewer")
    if not username:
        raise HTTPException(400, "用户名不能为空")
    if len(password) < 12:
        raise HTTPException(400, "密码至少12位")
    if role not in ("admin", "viewer"):
        raise HTTPException(400, "角色必须是 admin 或 viewer")
    try:
        await db.create_user(username, hash_password(password), role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True}


@router.delete("/users/{user_id}")
async def delete_user_endpoint(user_id: int, user_info: dict = Depends(get_current_user)):
    """删除用户"""
    if user_info.get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    # 不能删自己
    target = await db.get_db()
    try:
        cursor = await target.execute("SELECT username FROM users WHERE id=?", (user_id,))
        row = await cursor.fetchone()
        if row and row["username"] == user_info["username"]:
            raise HTTPException(400, "不能删除自己")
        if not row:
            raise HTTPException(404, "用户不存在")
    finally:
        await target.close()
    await db.delete_user(user_id)
    return {"success": True}
