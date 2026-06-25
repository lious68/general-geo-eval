"""
UCloud GEO 评估框架 - WebChat 认证状态管理
管理各 AI 模型官网的登录状态（Playwright storageState JSON 文件）
支持对关键认证 cookie 的精确检测，区分各平台的登录验证状态。
"""
import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 认证状态文件目录
AUTH_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "webchat_auth")

# 各模型对应的官网地址及关键认证 cookie 名称
# auth_cookies: 该平台登录状态的关键 cookie 名称（匹配任意一个即视为有效）
# auth_domains: cookie 所属域名的匹配模式（只要域名包含这些字符串即可）
WEBCHAT_SITES = {
    "deepseek": {
        "name": "DeepSeek",
        "url": "https://chat.deepseek.com",
        "auth_cookies": ["ds_session_id", "user_token", "token", "auth_token", "chat_token", "HWWAFSESID"],
        "auth_domains": ["deepseek.com"],
    },
    "ernie": {
        "name": "文心一言",
        "url": "https://chat.baidu.com",
        "auth_cookies": ["BDUSS", "STOKEN", "BAIDUID", "BDTOKEN", "BIDUPSID", "BAIDUID_BFESS", "BDUSS_BFESS", "XFT", "__bid_n"],
        "auth_domains": ["baidu.com", "chat.baidu.com", "yiyan.baidu.com", "xlab.baidu.com"],
    },
    "doubao": {
        "name": "豆包",
        "url": "https://www.doubao.com/chat",
        "auth_cookies": ["sessionid", "sid_tt", "csrf_token", "passport_auth", "is_login", "passport_csrf_token"],
        "auth_domains": ["doubao.com", "volces.com", "bytedance.com"],
    },
    "kimi": {
        "name": "Kimi",
        "url": "https://www.kimi.com",
        "auth_cookies": ["kimi-auth", "token", "access_token", "user_id", "refresh_token", "kimi_token", "auth_token"],
        "auth_domains": ["kimi.com", "moonshot.cn"],
    },
    "qwen": {
        "name": "千问",
        "url": "https://www.qianwen.com",
        # 实测（diag_webchat_cookies.py）：qwen 登录完成后写入通义 SSO 票据
        # tongyi_sso_ticket（httpOnly、1年、.qianwen.com）及其 hash。注意 b-user-id
        # 在登录完成前就写入（浏览器指纹，非登录态），不能作为登录判据，故不列入。
        # 旧列 login_sid/token/.../login_aliyunid qwen 根本不写，已废弃。
        "auth_cookies": ["tongyi_sso_ticket", "tongyi_sso_ticket_hash"],
        "auth_domains": ["qianwen.com", "aliyun.com", "tongyi"],
    },
}


def ensure_auth_dir():
    """确保认证文件目录存在"""
    os.makedirs(AUTH_DIR, exist_ok=True)


def get_auth_path(model_key: str) -> str:
    """获取某模型的认证状态文件路径"""
    ensure_auth_dir()
    return os.path.join(AUTH_DIR, f"{model_key}_state.json")


def has_auth_state(model_key: str) -> bool:
    """检查某模型是否有认证状态文件"""
    path = get_auth_path(model_key)
    if not os.path.exists(path):
        return False
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        # storageState 至少要有 cookies 或 origins
        return bool(data.get("cookies") or data.get("origins"))
    except (json.JSONDecodeError, ValueError):
        return False


def save_auth_state(model_key: str, state_data: Dict) -> str:
    """保存认证状态到文件

    Args:
        model_key: 模型标识 (如 "kimi")
        state_data: Playwright storageState dict (包含 cookies 和 origins)

    Returns:
        保存的文件路径
    """
    path = get_auth_path(model_key)
    Path(path).write_text(json.dumps(state_data, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Saved auth state for {model_key} to {path}")
    return path


def load_auth_state(model_key: str) -> Optional[Dict]:
    """加载认证状态

    Returns:
        storageState dict，或 None（文件不存在/无效）
    """
    path = get_auth_path(model_key)
    if not os.path.exists(path):
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not (data.get("cookies") or data.get("origins")):
            return None
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def delete_auth_state(model_key: str) -> bool:
    """删除认证状态文件"""
    path = get_auth_path(model_key)
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Deleted auth state for {model_key}")
        return True
    return False


def validate_auth_cookies(model_key: str) -> Dict:
    """验证认证状态中的关键 cookie 是否存在且未过期

    检查 Playwright storageState 中是否包含该平台的关键认证 cookie，
    并且 cookie 的域名匹配、未过期。匹配任意一个关键 cookie 即视为有效。

    Returns:
        {
            "has_auth": bool,         # 是否有认证文件
            "is_valid": bool,         # 认证是否有效（至少一个关键 cookie 匹配）
            "matched_cookies": list,  # 匹配到的关键 cookie 名称列表
            "cookie_count": int,      # 认证文件中的总 cookie 数量
            "details": str,           # 可读的状态描述
        }
    """
    state = load_auth_state(model_key)
    if not state:
        return {
            "has_auth": False,
            "is_valid": False,
            "matched_cookies": [],
            "cookie_count": 0,
            "details": "未上传认证文件",
        }

    site = WEBCHAT_SITES.get(model_key, {})
    required_cookies = site.get("auth_cookies", [])
    auth_domains = site.get("auth_domains", [])

    cookies = state.get("cookies", [])
    matched: List[str] = []
    for cookie in cookies:
        name = cookie.get("name", "")
        domain = cookie.get("domain", "")
        # 检查是否是关键认证 cookie 且域名匹配
        if name in required_cookies:
            domain_match = any(d in domain for d in auth_domains) if auth_domains else True
            if domain_match:
                # 检查是否过期（-1 表示 session cookie，不过期）
                expires = cookie.get("expires", -1)
                if expires == -1 or expires > time.time():
                    matched.append(name)

    is_valid = len(matched) > 0
    if is_valid:
        details = f"认证有效（关键 cookie: {', '.join(matched)}）"
    else:
        details = f"认证无效（共 {len(cookies)} 个 cookie，无关键认证 cookie 匹配）"

    return {
        "has_auth": True,
        "is_valid": is_valid,
        "matched_cookies": matched,
        "cookie_count": len(cookies),
        "details": details,
    }


def get_all_auth_status() -> Dict[str, Dict]:
    """获取所有模型的认证状态概览（包含精确验证）"""
    result = {}
    for model_key, site_info in WEBCHAT_SITES.items():
        validation = validate_auth_cookies(model_key)
        result[model_key] = {
            "model_key": model_key,
            "name": site_info["name"],
            "url": site_info["url"],
            "has_auth": validation["has_auth"],
            "is_valid": validation["is_valid"],
            "matched_cookies": validation["matched_cookies"],
            "cookie_count": validation["cookie_count"],
            "details": validation["details"],
            "auth_path": get_auth_path(model_key) if validation["has_auth"] else None,
        }
    return result