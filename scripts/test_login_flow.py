"""_login_flow 自检：只在 _is_logged_in 确认后才 save_auth_state（fake client）。

验证三路：
  A. 探测始终 False（用小 max_wait）→ 超时 → save_auth_state 未被调用、返回 False。
  B. 探测第 2 次起 True → save_auth_state 被调用恰好 1 次、返回 True。
  C. _page 为 None 时应 initialize(fresh=True) 后再探测。
不依赖真实浏览器（fake client + monkeypatch save_auth_state 到计数器）。
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


class _FakeCtx:
    async def storage_state(self):
        return {"cookies": [{"name": "c1"}, {"name": "c2"}, {"name": "c3"}], "origins": []}


class _FakePage:
    def __init__(self):
        self.url = "https://www.kimi.com/chat"


class _FakeClient:
    """最小 fake：仅暴露 _login_flow 用到的接口。"""

    name = "Kimi"
    url = "https://www.kimi.com"

    def __init__(self, is_logged_in_seq):
        # is_logged_in_seq: 每次调用返回的 bool 序列（True=已登录）
        self._seq = list(is_logged_in_seq)
        self._page = _FakePage()
        self._context = _FakeCtx()
        self.goto_calls = 0
        self.init_calls = 0

    async def initialize(self, fresh=False):
        self.init_calls += 1
        return True

    async def _goto_site(self, page):
        self.goto_calls += 1

    async def _is_logged_in(self, page, timeout=15):
        if self._seq:
            return self._seq.pop(0)
        return False  # 序列耗尽后保持 False（模拟始终未登录）

    async def close(self):
        pass


def _patch_save_auth_state(mod, counter):
    """把 runner 模块里的 save_auth_state 替换为计数器。"""
    counter["calls"] = 0
    counter["args"] = []

    def _fake(mk, state):
        counter["calls"] += 1
        counter["args"].append((mk, state))
        return f"/tmp/fake_{mk}_state.json"

    mod.save_auth_state = _fake


async def main():
    # 用 importlib 导入 runner（它顶层有副作用：path 设置、import，但 main() 不自动跑）
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "local_webchat_runner",
        os.path.join(os.path.dirname(__file__), "local_webchat_runner.py"),
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    # ── A. 始终未登录 → 超时不保存 ──
    counter_a = {}
    _patch_save_auth_state(runner, counter_a)
    client_a = _FakeClient(is_logged_in_seq=[False, False, False, False, False])
    # max_wait 设小（3s 一次，max_wait=6 → 最多 2 轮），加速测试
    ok = await runner._login_flow(client_a, "kimi", max_wait=6)
    assert ok is False, "始终未登录应返回 False"
    assert counter_a["calls"] == 0, "未确认登录不应调用 save_auth_state"
    assert client_a.goto_calls == 1, "应只 _goto_site 一次"
    assert client_a.init_calls == 0, "_page 已存在时不应再 initialize"

    # ── B. 第 2 次探测 True → 保存一次、返回 True ──
    counter_b = {}
    _patch_save_auth_state(runner, counter_b)
    client_b = _FakeClient(is_logged_in_seq=[False, True])
    ok = await runner._login_flow(client_b, "kimi", max_wait=60)
    assert ok is True, "确认登录应返回 True"
    assert counter_b["calls"] == 1, "确认登录应恰好保存一次"
    mk, state = counter_b["args"][0]
    assert mk == "kimi", "save_auth_state 应收到正确 model_key"
    assert len(state.get("cookies", [])) == 3, "应保存 fake context 的 cookies"

    # ── C. _page 为 None 时应 initialize(fresh=True) ──
    counter_c = {}
    _patch_save_auth_state(runner, counter_c)
    client_c = _FakeClient(is_logged_in_seq=[True])
    client_c._page = None  # 强制走 initialize 分支
    ok = await runner._login_flow(client_c, "kimi", max_wait=60)
    assert ok is True, "无 page 时 initialize 后探测成功应返回 True"
    assert client_c.init_calls == 1, "_page=None 应调 initialize(fresh=True)"
    assert counter_c["calls"] == 1

    print("✅ PASS: _login_flow 只在确认登录后保存一次，未登录超时不保存，无 page 时自动 initialize")


if __name__ == "__main__":
    asyncio.run(main())
