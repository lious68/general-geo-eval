"""诊断文心一言 (chat.baidu.com) 登录态 DOM，用于适配 ErnieWebChatClient 选择器。

迁域名后旧选择器（[contenteditable='true'], [class*='editable'], [class*='input-area'], textarea）
匹配不到输入框 → Locator Timeout。本脚本用已存的登录态 headed 打开页面，dump
输入框/发送按钮候选元素的 tag/class/placeholder/data-*，据此重调选择器。

用法（Win RDP，前台管理员 PowerShell）：
    cd C:\\general-geo-eval
    python scripts\\diag_ernie_dom.py
"""
import asyncio
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# headed（DISPLAY=:0 → WebChatClientBase.initialize 走 headless=False）
os.environ["DISPLAY"] = ":0"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from web_chat_clients import create_web_chat_client  # noqa: E402

# 输入框候选选择器（尽量宽，dump 出来再看真实结构）
INPUT_CANDIDATES = (
    "textarea, "
    "[contenteditable='true'], [contenteditable=''], "
    "[role='textbox'], "
    "input[type='text'], input[type='search'], "
    "[class*='input' i], [class*='editor' i], [class*='textarea' i], "
    "[class*='chat' i], [class*='prompt' i]"
)


async def main():
    c = create_web_chat_client("ernie")
    print("ernie is_configured(有登录态):", c.is_configured)
    if not c.is_configured:
        print("❌ 无 ernie 登录态，先跑 setup_webchat_auth.py ernie 登录")
        return
    if not await c.initialize():
        print("❌ 浏览器启动失败")
        return
    page = c._page
    await c._goto_site(page)
    await asyncio.sleep(6)

    print("\n=== 页面信息 ===")
    print("URL:", page.url)
    try:
        print("Title:", await page.title())
    except Exception:
        pass
    try:
        logged = await c._is_logged_in(page, timeout=5)
        print("_is_logged_in(BDUSS 判定):", logged)
    except Exception as e:
        print("_is_logged_in 异常:", e)

    print("\n=== 输入框候选元素 ===")
    try:
        els = await page.locator(INPUT_CANDIDATES).all()
    except Exception as e:
        els = []
        print("定位异常:", e)
    print(f"候选数: {len(els)}")
    for i, el in enumerate(els[:25]):
        try:
            vis = await el.is_visible()
            tag = await el.evaluate("e=>e.tagName")
            cls = await el.get_attribute("class") or ""
            ph = await el.get_attribute("placeholder") or ""
            ce = await el.get_attribute("contenteditable") or ""
            role = await el.get_attribute("role") or ""
            dt = await el.get_attribute("data-testid") or ""
            outer = await el.evaluate("e=>e.outerHTML.slice(0,240)")
            print(f"[{i}] vis={vis} tag={tag} ce={ce} role={role} dt={dt}")
            print(f"    class={cls[:80]} ph={ph[:30]}")
            print(f"    html={outer}")
        except Exception as e:
            print(f"[{i}] 读取异常: {e}")

    print("\n=== 可见按钮（发送按钮候选）===")
    try:
        btns = await page.locator("button").all()
    except Exception:
        btns = []
    shown = 0
    for b in btns:
        try:
            if not await b.is_visible():
                continue
            txt = (await b.inner_text()).strip()
            al = await b.get_attribute("aria-label") or ""
            cls = await b.get_attribute("class") or ""
            dt = await b.get_attribute("data-testid") or ""
            # 只打印疑似发送/提交的，或带图标描述的
            key = (txt + al).lower()
            if any(k in key for k in ("发送", "send", "提交", "submit")) or "send" in (cls + dt).lower():
                print(f"  [疑似发送] text={txt[:20]} aria={al[:30]} dt={dt} class={cls[:60]}")
                shown += 1
        except Exception:
            pass
    if shown == 0:
        print("  未找到带'发送/send'字样的可见按钮，下面列全部可见按钮(前15)：")
        cnt = 0
        for b in btns:
            try:
                if not await b.is_visible():
                    continue
                txt = (await b.inner_text()).strip()
                al = await b.get_attribute("aria-label") or ""
                cls = await b.get_attribute("class") or ""
                print(f"  btn text={txt[:20]} aria={al[:30]} class={cls[:60]}")
                cnt += 1
                if cnt >= 15:
                    break
            except Exception:
                pass

    await c.close()
    print("\n=== 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
