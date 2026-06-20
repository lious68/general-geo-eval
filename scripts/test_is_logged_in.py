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

    # ── kimi 子类覆盖：查 localStorage access_token/msh_user_id，不看输入框 ──
    # 证据：diag_kimi_login_state.py 登录后 localStorage 有 access_token+msh_user_id；
    # 登录前只有 anonymous_access_token。kimi-auth cookie 与输入框可见都是弱信号。
    from web_chat_clients import KimiWebChatClient

    class _KimiFakePage:
        def __init__(self, url, has_real_token):
            self.url = url
            self._has = has_real_token

        async def evaluate(self, js):
            return self._has

    class _KimiFakePageExc:
        url = "https://www.kimi.com/"

        async def evaluate(self, js):
            raise RuntimeError("page gone")

    kc = KimiWebChatClient("kimi")

    # 6. kimi：localStorage 有 access_token → True（即使输入框探测不存在）
    assert await kc._is_logged_in(_KimiFakePage("https://www.kimi.com/", True), timeout=1) is True, \
        "kimi 有 access_token 应判已登录"

    # 7. kimi：只有 anonymous token（has_real=False）→ False（核心：堵住落地页误判）
    assert await kc._is_logged_in(_KimiFakePage("https://www.kimi.com/", False), timeout=1) is False, \
        "kimi 无 access_token 应判未登录"

    # 8. kimi：URL 在登录页即使有 token → False
    assert await kc._is_logged_in(_KimiFakePage("https://www.kimi.com/passport/login", True), timeout=1) is False, \
        "kimi 登录页 URL 应判未登录"

    # 9. kimi：evaluate 抛错 → False（不向上抛）
    assert await kc._is_logged_in(_KimiFakePageExc(), timeout=1) is False, \
        "kimi evaluate 异常应判未登录"

    print("✅ PASS: _is_logged_in 基类(登录页/正常页/不可见/异常/不导航) + kimi(localStorage access_token) 均正确")


# ── ernie 子类：查 cookie BDUSS（httpOnly），不看输入框 ──
# 证据：diag_ernie_login_state.py 登录翻转 [2]→[5]：登录前只有匿名态 cookie
# （BAIDUID/RT/ab_sr…，无 BDUSS）；登录后 BDUSS+STOKEN+PTOKEN+UBI 写入。
# 文心首页输入框匿名态就可见 → 基类"输入框可见"是弱信号，会把匿名态误判已登录。
# BDUSS 是百度通行证 httpOnly 登录凭证，仅完整登录后出现，是强信号。
async def test_ernie():
    from web_chat_clients import ErnieWebChatClient

    class _ErnieFakePage:
        """fake：context.cookies() 返回给定 cookie 名集合（context 是属性，仿 Playwright）。"""
        def __init__(self, url, cookie_names):
            self.url = url
            names = cookie_names

            class _Ctx:
                async def cookies(_self):
                    return [{"name": n, "value": "v_" + n, "domain": ".baidu.com"} for n in names]
            self.context = _Ctx()

    class _ErnieFakePageNoCtx:
        url = "https://yiyan.baidu.com/"
        # 无 context() → 触发兜底 try/except → False（不向上抛）

    ec = ErnieWebChatClient("ernie")

    # 10. ernie：有 BDUSS → True
    page = _ErnieFakePage("https://yiyan.baidu.com/", ["BAIDUID", "BDUSS", "STOKEN"])
    assert await ec._is_logged_in(page, timeout=1) is True, \
        "ernie 有 BDUSS 应判已登录"

    # 11. ernie：只有匿名态 cookie（无 BDUSS）→ False（核心：堵住落地页误判）
    page = _ErnieFakePage("https://yiyan.baidu.com/", ["BAIDUID", "RT", "ab_sr"])
    assert await ec._is_logged_in(page, timeout=1) is False, \
        "ernie 无 BDUSS（匿名态）应判未登录"

    # 12. ernie：URL 在登录页即使有 BDUSS → False
    page = _ErnieFakePage("https://passport.baidu.com/v2/?login", ["BDUSS"])
    assert await ec._is_logged_in(page, timeout=1) is False, \
        "ernie 登录页 URL 应判未登录"

    # 13. ernie：context.cookies() 抛错 / 无 context → False（不向上抛）
    assert await ec._is_logged_in(_ErnieFakePageNoCtx(), timeout=1) is False, \
        "ernie cookies 异常应判未登录"

    print("✅ PASS: ernie _is_logged_in(cookie BDUSS 强信号 / 匿名态 False / 登录页 False / 异常 False)")


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(test_ernie())
