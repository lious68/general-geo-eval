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

# 真正的输入元素（去掉 [class*='chat' i] 等宽泛匹配，避免容器淹没真输入框）
INPUT_CANDIDATES = (
    "textarea, "
    "[contenteditable='true'], [contenteditable=''], [contenteditable], "
    "[role='textbox'], "
    "input[type='text'], input[type='search'], input:not([type])"
)


async def dump_inputs(page, label):
    print(f"\n--- {label} 输入元素 ---")
    try:
        els = await page.locator(INPUT_CANDIDATES).all()
    except Exception as e:
        els = []
        print("  定位异常:", e)
    print(f"  候选数: {len(els)}")
    for i, el in enumerate(els[:40]):
        try:
            vis = await el.is_visible()
            tag = await el.evaluate("e=>e.tagName")
            cls = (await el.get_attribute("class") or "").strip()
            ph = await el.get_attribute("placeholder") or ""
            ce = await el.get_attribute("contenteditable") or ""
            role = await el.get_attribute("role") or ""
            dt = await el.get_attribute("data-testid") or ""
            outer = await el.evaluate("e=>e.outerHTML.slice(0,300)")
            print(f"  [{i}] vis={vis} tag={tag} ce={ce} role={role} dt={dt}")
            print(f"      class={cls[:90]}")
            print(f"      ph={ph[:30]} html={outer[:260]}")
        except Exception as e:
            print(f"  [{i}] 读取异常: {e}")


async def dump_buttons(page, label):
    print(f"\n--- {label} 按钮(button / role=button) ---")
    try:
        btns = await page.locator("button, [role='button']").all()
    except Exception:
        btns = []
    print(f"  总数: {len(btns)}")
    cnt = 0
    for b in btns:
        try:
            vis = await b.is_visible()
            txt = (await b.inner_text()).strip()
            al = await b.get_attribute("aria-label") or ""
            cls = (await b.get_attribute("class") or "").strip()
            dt = await b.get_attribute("data-testid") or ""
            ti = await b.get_attribute("title") or ""
            # 打印可见的，或带发送/提交语义的
            key = (txt + al + ti + cls).lower()
            if vis or any(k in key for k in ("发送", "send", "提交", "submit")):
                print(f"  [vis={vis}] text={txt[:24]} aria={al[:30]} title={ti[:20]} dt={dt} class={cls[:60]}")
                cnt += 1
                if cnt >= 30:
                    break
        except Exception:
            pass


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
    await asyncio.sleep(10)  # SPA 渲染留足时间

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

    # 主 frame 输入/按钮
    await dump_inputs(page, "主frame")
    await dump_buttons(page, "主frame")

    # iframe 检查
    frames = page.frames
    print(f"\n--- iframe 数: {len(frames)} ---")
    for f in frames[1:]:  # 跳过主 frame
        print(f"  frame: url={f.url[:80]} name={f.name}")
        try:
            n = await f.locator(INPUT_CANDIDATES).count()
            print(f"    输入元素数: {n}")
            if n > 0:
                await dump_inputs(f, f"frame {f.url[:50]}")
                await dump_buttons(f, f"frame {f.url[:50]}")
        except Exception as e:
            print(f"    frame 访问异常: {e}")

    # 底部输入区 HTML（输入框常在页面底部固定区）
    print("\n--- 底部输入区(footer / 底部固定 div) outerHTML ---")
    try:
        for sel in ("footer", "[class*='footer' i]", "[class*='input-area' i]",
                    "[class*='inputArea' i]", "[class*='dialogueInput' i]",
                    "[class*='chatInput' i]", "[class*='chat-input' i]"):
            cnt = await page.locator(sel).count()
            if cnt:
                print(f"  {sel}: {cnt} 个")
                outer = await page.locator(sel).last.evaluate("e=>e.outerHTML.slice(0,600)")
                print(f"    {outer[:600]}")
    except Exception as e:
        print("  异常:", e)

    await c.close()
    print("\n=== 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
