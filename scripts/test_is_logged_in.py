"""_is_logged_in 判定逻辑自检（fake page，不依赖真实浏览器）。

验证：URL 在登录页 → False；URL 正常 + 输入框可见 → True；
URL 正常 + 输入框不可见 → False；is_visible 抛错 → False。
不导航（_is_logged_in 只看当前页 url，不调 goto）。
"""
import sys
import os
import io
import asyncio

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


class _FakeLocator:
    def __init__(self, visible_value=True, exc=None):
        self._visible = visible_value
        self._exc = exc

    @property
    def first(self):
        return self

    async def is_visible(self, timeout=0):
        if self._exc:
            raise self._exc
        return self._visible


class _FakePage:
    def __init__(self, url="", visible=True, exc=None):
        self.url = url
        self._locator = _FakeLocator(visible, exc)
        self.goto_calls = 0

    def locator(self, selector):
        return self._locator


def _make_client():
    # 用基类即可（INPUT_SELECTOR 是基类级占位，这里覆盖一个确定值）
    from web_chat_clients import WebChatClientBase

    class _Probe(WebChatClientBase):
        INPUT_SELECTOR = "textarea.fake"

    c = _Probe("kimi")  # kimi 站点 url=www.kimi.com，is_configured 可能 False 不影响探测
    return c


async def main():
    c = _make_client()

    # 1. URL 含 passport → False（即使输入框可见）
    page = _FakePage(url="https://passport.kimi.com/login", visible=True)
    assert await c._is_logged_in(page, timeout=1) is False, "登录页 URL 应判未登录"

    # 2. URL 无关键字 + 输入框可见 → True
    page = _FakePage(url="https://www.kimi.com/chat", visible=True)
    assert await c._is_logged_in(page, timeout=1) is True, "正常页+输入框可见应判已登录"

    # 3. URL 无关键字 + 输入框不可见 → False
    page = _FakePage(url="https://www.kimi.com/chat", visible=False)
    assert await c._is_logged_in(page, timeout=1) is False, "输入框不可见应判未登录"

    # 4. is_visible 抛错 → False（不向上抛）
    page = _FakePage(url="https://www.kimi.com/chat", exc=RuntimeError("boom"))
    assert await c._is_logged_in(page, timeout=1) is False, "is_visible 异常应判未登录"

    # 5. 不导航：_is_logged_in 不应调 page.goto
    page = _FakePage(url="https://www.kimi.com/chat", visible=True)
    await c._is_logged_in(page, timeout=1)
    assert page.goto_calls == 0, "_is_logged_in 不应导航"

    print("✅ PASS: _is_logged_in 登录页/正常页/不可见/异常均判定正确，且不导航")


if __name__ == "__main__":
    asyncio.run(main())
