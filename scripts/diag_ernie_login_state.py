"""
诊断文心一言 (yiyan.baidu.com) 登录态信号：cookie + localStorage + sessionStorage + DOM，登录前→后对比。

目的：找出"只在完整登录后才出现"的强信号，用于 _login_flow 的 _is_logged_in 探测。
百度通行证 cookie（BAIDUID/BDUSS 等）有些在登录前/匿名态就有，是弱信号——会导致
_login_flow 抢救半成品 state（误判已登录、过早保存，评测时发不出请求或被踢回登录页）。
本脚本每 3s 打印 cookie/localStorage/sessionStorage/URL/登录按钮可见性，让用户看着
登录前→后的翻转，定位强信号。

用法:
    python scripts/diag_ernie_login_state.py
    # 浏览器打开后手动登录；登录完成后回终端按 Enter 打印完整快照
"""
import asyncio
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

URL = "https://yiyan.baidu.com"


# 探测 DOM 上"登录入口"是否可见（登录前应可见，登录后应消失）
# 百度登录入口常见文案：登录 / 扫码登录 / 登录百度账号 / 立即登录
LOGIN_PROBE_JS = """() => {
    const out = {loginBtnVisible: false, loginBtnText: '', avatarVisible: false, bodyTextSample: ''};
    const nodes = Array.from(document.querySelectorAll('a, button, [role="button"], div, span'));
    for (const n of nodes) {
        const t = ((n.textContent || '') + ' ' + (n.getAttribute('aria-label') || '')).trim().toLowerCase();
        const rect = n.getBoundingClientRect();
        if (rect.width < 20 || rect.height < 10) continue;
        if ((t.includes('登录') || t.includes('扫码登录') || t.includes('log in') || t.includes('sign in') || t === 'login')
            && rect.top < 500) {
            out.loginBtnVisible = true;
            out.loginBtnText = (n.textContent || '').trim().slice(0, 24);
            break;
        }
    }
    // 头像/账号区（百度常见 class 含 avatar/user/info/account 或 img[alt] 含头像）
    const av = document.querySelector('img[class*="avatar"], [class*="avatar"] img, [class*="user"], [class*="account"], [class*="info-head"]');
    if (av) {
        const r = av.getBoundingClientRect();
        out.avatarVisible = r.width > 10 && r.height > 10;
    }
    out.bodyTextSample = (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 120);
    return out;
}"""


async def _storage_snapshot(page, store):
    """读取 page 的 localStorage(0)/sessionStorage(1)。返回 {key: 截断值}。"""
    js = f"""() => {{
        const out = {{}};
        const s = {store};
        try {{
            for (let i=0;i<s.length;i++){{
                const k = s.key(i);
                let v = s.getItem(k) || '';
                out[k] = v.length > 40 ? v.slice(0,40)+'...('+v.length+')' : v;
            }}
        }} catch(e) {{}}
        return out;
    }}"""
    return await page.evaluate(js)


async def main():
    from playwright.async_api import async_playwright

    print(f"=== 诊断文心一言登录态信号 ({URL}) ===")
    print("浏览器即将打开（全新 context，无登录态）。请在窗口里完整登录。")
    print("我会每 3s 打印 cookie/localStorage/sessionStorage/URL/登录按钮，观察登录前→后的翻转。")
    print("重点关注：BDUSS 是否登录后才出现；localStorage/sessionStorage 是否有登录后才写的 key。\n")

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(channel="chrome", headless=False, args=[
            "--disable-blink-features=AutomationControlled", "--no-sandbox",
        ])
    except Exception:
        browser = await pw.chromium.launch(headless=False, args=["--no-sandbox"])

    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    try:
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass

    async def poll():
        i = 0
        while True:
            await asyncio.sleep(3)
            i += 1
            try:
                ck = await context.cookies()
                cnames = sorted({c["name"] for c in ck})
                ls = await _storage_snapshot(page, "localStorage")
                ss = await _storage_snapshot(page, "sessionStorage")
                dom = await page.evaluate(LOGIN_PROBE_JS)
                print(f"  [{i}] url={page.url}")
                print(f"      cookies({len(ck)}): {cnames}")
                bduss = [c["name"] for c in ck if c["name"] == "BDUSS"]
                print(f"      BDUSS present: {bool(bduss)}  STOKEN present: {'STOKEN' in cnames}")
                print(f"      localStorage keys: {list(ls.keys())}")
                print(f"      sessionStorage keys: {list(ss.keys())}")
                print(f"      loginBtn={dom.get('loginBtnVisible')} ({dom.get('loginBtnText')!r}) avatar={dom.get('avatarVisible')}")
            except Exception as e:
                print(f"  [{i}] poll err: {e}")

    poll_task = asyncio.create_task(poll())
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "  >>> 登录完成后按 Enter 打印完整快照...\n")
    poll_task.cancel()

    # 完整快照
    ck = await context.cookies()
    ls = await _storage_snapshot(page, "localStorage")
    ss = await _storage_snapshot(page, "sessionStorage")
    dom = await page.evaluate(LOGIN_PROBE_JS)
    state = await context.storage_state()

    print(f"\n=== 完整快照 ===")
    print(f"URL: {page.url}")
    print(f"cookies ({len(ck)}): {sorted(c['name'] for c in ck)}")
    print(f"\nlocalStorage ({len(ls)} keys):")
    for k in sorted(ls):
        print(f"  {k} = {ls[k]}")
    print(f"\nsessionStorage ({len(ss)} keys):")
    for k in sorted(ss):
        print(f"  {k} = {ss[k]}")
    print(f"\nDOM: loginBtn={dom.get('loginBtnVisible')} ({dom.get('loginBtnText')!r}) avatar={dom.get('avatarVisible')}")
    print(f"     body sample: {dom.get('bodyTextSample')!r}")
    print(f"\nstorage_state origins ({len(state.get('origins', []))}):")
    for o in state.get("origins", []):
        ls = o.get("localStorage") or []
        # Playwright storage_state 的 localStorage 既可能是 list[{name,value}] 也可能是 dict
        if isinstance(ls, list):
            ls_keys = [item.get("name") for item in ls]
        else:
            ls_keys = list(ls.keys())
        print(f"  origin={o.get('origin')} localStorage_keys={ls_keys}")

    print("\n=== 结论提示 ===")
    bduss = [c for c in ck if c["name"] == "BDUSS"]
    if bduss:
        print(f"  ✅ BDUSS 登录后出现（强信号候选）：domain={bduss[0].get('domain')} httpOnly={bduss[0].get('httpOnly')}")
    else:
        print(f"  ⚠️ 登录后仍无 BDUSS（弱 cookie 信号）——强信号可能在 localStorage/sessionStorage")
    if ls:
        print(f"  localStorage 登录后 keys: {list(ls.keys())}（对比登录前，新增/值变的即强信号候选）")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
