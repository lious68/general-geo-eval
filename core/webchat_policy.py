"""
UCloud GEO 评估框架 - WebChat 逐模型策略与封号信号检测

为「任务 → 模型 → 问题」三级任务架构提供：
  1. 每个模型的限流/重试策略（DeepSeek 等敏感平台收紧）
  2. 页面/错误文本的封号信号分类（throttle / login_expired）
  3. 退避参数

这些配置同时被 server（eval_runner.py）与本地 runner（local_webchat_runner.py）使用，
是 core/scheduler.py 调度决策的唯一输入。
"""
import re
from typing import Dict


# ============================================================
# 逐模型策略
# ============================================================
# 字段含义（core/scheduler.py 消费）：
#   max_attempts       单题最大尝试次数（瞬态错误才重试；封号/登录不在此内）
#   inter_unit_delay   同一模型相邻两次请求之间的最小间隔（秒）
#   max_consecutive    突发上限：同模型连续请求达到该值后强制 burst_cooldown 冷却
#   burst_cooldown     突发后冷却（秒）
#   rate_max          滑动窗口内最大请求数
#   rate_window_sec   滑动窗口长度（秒）
#   ban_cooldown_sec  检测到 throttle（频率过快）信号后的长冷却（秒）
#
# 设计依据：DeepSeek 等平台「连续问询超过约 25 次即触发封号」。
# 标准基准 40 题 × 5 模型 = 200 次，单平台必须把短时连发压到阈值以下。

_DEFAULT_POLICY = {
    "max_attempts": 3,
    "inter_unit_delay": 8.0,
    "max_consecutive": 20,      # 用户要求：每模型满20题休息
    "burst_cooldown": 3600,     # 休息1小时
    "rate_max": 20,             # 每小时上限同步收紧
    "rate_window_sec": 3600,
    "ban_cooldown_sec": 900,
}

# DeepSeek 更敏感：满15题即触发（比20更早、更保守），但休息时长统一1小时。
_MODEL_OVERRIDES: Dict[str, dict] = {
    "deepseek": {
        "max_attempts": 4,
        "inter_unit_delay": 15.0,
        "max_consecutive": 15,   # 远低于 25 阈值
        "burst_cooldown": 3600,  # 统一休息1小时
        "rate_max": 20,          # 每小时上限
        "rate_window_sec": 3600,
        "ban_cooldown_sec": 1800,
    },
}

MODEL_POLICY: Dict[str, dict] = {}
for _mk in ("deepseek", "ernie", "doubao", "kimi", "qwen"):
    _p = dict(_DEFAULT_POLICY)
    _p.update(_MODEL_OVERRIDES.get(_mk, {}))
    MODEL_POLICY[_mk] = _p
del _mk, _p


def get_model_policy(model_key: str) -> dict:
    """获取某模型的策略，未知模型回退到默认。"""
    base = dict(_DEFAULT_POLICY)
    base.update(_MODEL_OVERRIDES.get(model_key, {}))
    return base


# ============================================================
# 退避参数（指数退避 + 抖动）
# ============================================================
BACKOFF = {
    "base": 5.0,     # 首次重试前等待
    "factor": 2.0,   # 每次翻倍
    "cap": 120.0,    # 单次退避上限（秒）
    "jitter": 0.25,  # ±25% 抖动
}


# ============================================================
# 封号信号检测
# ============================================================
# throttle：触发限流/风控（需长冷却后重试）
_LOGIN_PATTERNS = [
    r"登[录陆]已(?:过期|失效)",
    r"请(?:先|重新)?登[录陆]",
    r"未登[录陆]",
    r"login\s*(?:required|expired|failed)",
    r"token\s*(?:invalid|expired)",
    r"会话已(?:过期|失效)",
]

_THROTTLE_PATTERNS = [
    r"频率过快",
    r"过于频繁",
    r"操作太频繁",
    r"请求(?:过于)?频繁",
    r"请求(?:过)?多",
    r"访问(?:过于)?频繁",
    r"稍后(?:再)?(?:试|重试)",
    r"系统繁忙",
    r"服务(?:暂不可用|繁忙)",
    r"限流",
    r"rate\s*limit",
    r"too\s*many\s*requests",
    r"429",
    r"安全验证",
    r"captcha",
    r"验证码",
]
# 注：移除过宽的「异常」「verify」「验证」等（会在正常回答里误伤）；
# 触发验证码时平台通常也伴随「验证码/captcha」字样，已覆盖。

_LOGIN_RE = re.compile("|".join(_LOGIN_PATTERNS), re.IGNORECASE)
_THROTTLE_RE = re.compile("|".join(_THROTTLE_PATTERNS), re.IGNORECASE)


def classify_signal(text: str) -> str:
    """对响应文本/错误信息做封号信号分类。

    Returns:
        "ok" | "throttle" | "login_expired"
        login_expired 优先于 throttle（登录失效比限流更严重，需人工介入）。
    """
    if not text:
        return "ok"
    if _LOGIN_RE.search(text):
        return "login_expired"
    if _THROTTLE_RE.search(text):
        return "throttle"
    return "ok"


# 对「模型回答正文」分类时，正文最长不计入的阈值。
# 真实限流/登录失效提示是短句（通常 <50 字）；正常回答数百字以上。
_CONTENT_SIGNAL_MAX_LEN = 100


def classify_content_signal(text: str, max_len: int = _CONTENT_SIGNAL_MAX_LEN) -> str:
    """对「模型回答正文」做封号信号分类（只对短文本生效）。

    与 classify_signal 的区别：长度 >= max_len 的正文直接判 ok。

    原因：throttle 模式里有「限流」「429」「安全验证」「验证码」「系统繁忙」等
    宽词，而评估对象 UCloud 是云厂商，其真实回答里常出现这些技术词（讨论限流、
    429 重试、安全验证、验证码等）。对长正文用 classify_signal 会把正确回答误判
    为 throttle，触发 900s 冷却把整模型卡死。真实限流/登录提示是短句，所以只对
    短文本分类即可既捕获真提示、又不误伤长回答。

    错误信息（err）仍用 classify_signal，错误串天然短，不受此限。
    """
    if not text:
        return "ok"
    if len(text) >= max_len:
        return "ok"
    return classify_signal(text)
