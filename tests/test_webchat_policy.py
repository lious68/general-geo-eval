import asyncio
import pytest
from webchat_policy import get_model_policy, MODEL_POLICY
import scheduler


def test_all_models_20_per_hour_one_hour_rest():
    for mk in ("deepseek", "ernie", "doubao", "kimi", "qwen"):
        p = get_model_policy(mk)
        assert p["max_consecutive"] <= 20, f"{mk} max_consecutive {p['max_consecutive']} > 20"
        assert p["burst_cooldown"] == 3600, f"{mk} burst_cooldown {p['burst_cooldown']} != 3600"


def test_deepseek_triggers_earlier_but_rests_one_hour():
    p = get_model_policy("deepseek")
    assert p["max_consecutive"] == 15
    assert p["burst_cooldown"] == 3600


@pytest.mark.asyncio
async def test_rate_limiter_burst_after_max_consecutive(monkeypatch):
    sleeps = []
    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)

    pol = {"max_consecutive": 2, "burst_cooldown": 100,
           "rate_max": 9999, "rate_window_sec": 3600, "inter_unit_delay": 0}
    limiter = scheduler.RateLimiter("t", pol)
    await limiter.acquire()   # 1
    await limiter.acquire()   # 2 — consecutive 达上限
    await limiter.acquire()   # 3 — 应触发 burst_cooldown=100 的 sleep
    assert 100 in sleeps, f"burst_cooldown 100 未触发, sleeps={sleeps}"
