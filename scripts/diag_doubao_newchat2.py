"""豆包「新建对话」二轮采证 — 试3种交互，判定哪种真能开新会话

用法:
    python scripts/diag_doubao_newchat2.py

上一轮证据：侧栏顶部没有独立「新建对话」文本按钮。候选入口：
  (1) 顶部豆包 logo <a>（y~58, class group/sidebar_nav_item）—— 多半回首页
  (2) hover 侧栏顶部，找悬停才出现的「新建对话」按钮
  (3) 右上角 y~15 的 svg <button>（main 区，疑似侧栏折叠/新对话）
本轮：发一题后，依次试3种动作，每种动作后判定是否真开新会话
  判据：URL 变成新 session id（/chat/<新数字>） OR message-list 清空
落 output/doubao_newchat2_dom.json。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client

QUESTION = "UCloud海外有哪些节点？"


async def _dismiss_overlays(page):
    for sel in [
        "[role='dialog'] [class*='close']",
        "[role='dialog'] button[aria-label*='关闭']",
        "div[class*='mask'], div[class*='overlay'], div[class*='backdrop']",
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1000):
                await loc.click(timeout=1500)
                await asyncio.sleep(0.3)
        except Exception:
            pass
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.2)
    except Exception:
        pass


async def _state(page):
    """返回当前 url + message-list 消息条数，用于判定是否开了新会话。"""
    try:
        return await page.evaluate("""() => {
          const ml = document.querySelector('[class*="message-list"]');
          const cnt = ml ? ml.querySelectorAll('[class*="message-row"], [class*="v_list_row"], [class*="chat-message"]').length : 0;
          return { url: location.href, msg_count: cnt };
        }""")
    except Exception:
        return {"url": page.url, "msg_count": -1}


async def _try_action(page, name, fn):
    """执行一种交互动作，返回前后状态对比。"""
    before = await _state(page)
    ok, err = True, None
    try:
        await fn()
    except Exception as e:
        ok, err = str(e)
    await asyncio.sleep(2.5)
    after = await _state(page)
    new_session = (before["url"] != after["url"]) and ("/chat/" in after["url"])
    msg_cleared = (before["msg_count"] > 0) and (after["msg_count"] < before["msg_count"])
    result = {
        "action": name, "before": before, "after": after,
        "clicked_ok": ok, "error": err,
        "url_changed_to_new_session": new_session,
        "msg_cleared": msg_cleared,
        "opened_new": new_session or msg_cleared,
    }
    print(f"  [{name}] before={before} after={after} opened_new={result['opened_new']}")
    if err:
        print(f"    error: {err}")
    return result


async def debug():
    os.environ["DISPLAY"] = ":0"
    os.makedirs("output", exist_ok=True)

    print("启动豆包客户端（沿用登录态）...")
    client = create_web_chat_client("doubao")
    ok = await client.initialize()
    if not ok:
        print("浏览器启动失败"); return

    await client._navigate_to_chat(client._page)
    page = client._page
    await _dismiss_overlays(page)

    print(f"发题: {QUESTION}")
    await client._type_question(page, QUESTION)
    await client._send_question(page)
    print("等响应...")
    await client._wait_for_response(page, timeout=120)

    base = await _state(page)
    print(f"\n[基线] 发完一题后: {base}")
    result = {"question": QUESTION, "baseline": base, "actions": []}

    # 动作1：点顶部豆包 logo <a>（y~58, group/sidebar_nav_item）
    async def a1():
        loc = page.locator("a.group\\/sidebar_nav_item, [class*='sidebar_nav_item']").first
        await loc.click(timeout=4000)
    result["actions"].append(await _try_action(page, "点豆包logo(a.sidebar_nav_item)", a1))

    # 动作2：hover 侧栏顶部，找悬停出现的「新建对话」按钮并点
    async def a2():
        # 先 hover 侧栏顶部区域
        try:
            await page.locator("#flow_chat_sidebar, [class*='sidebar']").first.hover(timeout=2000)
            await asyncio.sleep(1.0)
        except Exception:
            pass
        # 找悬停后出现的、文本含「新建/新对话」的可点元素
        cand = await page.evaluate("""() => {
          const out = [];
          const all = Array.from(document.querySelectorAll('button, a, [role="button"], [class*="new"]'));
          for (const el of all) {
            const t = (el.textContent || '').trim();
            const aria = el.getAttribute('aria-label') || '';
            if (/新建|新对话|新聊天|New chat/i.test(t + aria)) {
              const r = el.getBoundingClientRect();
              if (r.width && r.height) out.push({ tag: el.tagName.toLowerCase(), text: t.slice(0,20), aria, x: Math.round(r.x), y: Math.round(r.y) });
            }
          }
          return out;
        }""")
        print(f"    hover后候选: {cand}")
        if cand:
            # 点第一个
            try:
                loc = page.get_by_text(cand[0]["text"], exact=False).first
                await loc.click(timeout=3000)
            except Exception:
                # 回退：按坐标点
                await page.mouse.click(cand[0]["x"] + 10, cand[0]["y"] + 10)
        else:
            raise RuntimeError("hover后未找到新建对话按钮")
    result["actions"].append(await _try_action(page, "hover侧栏找新建对话按钮", a2))

    # 动作3：点右上角 y~15 的 svg <button>（main 区，疑似新对话/折叠）
    async def a3():
        # main 区顶部带 svg 的 button
        btns = page.locator("main button:has(svg)")
        cnt = await btns.count()
        clicked = False
        for i in range(min(cnt, 5)):
            b = btns.nth(i)
            box = await b.bounding_box()
            if box and box["y"] < 80 and box["x"] > 400:  # 右上角
                await b.click(timeout=3000)
                clicked = True
                break
        if not clicked:
            raise RuntimeError("未找到右上角 svg 按钮")
    result["actions"].append(await _try_action(page, "点右上角svg按钮", a3))

    # 汇总：哪种动作真开了新会话
    winners = [a["action"] for a in result["actions"] if a["opened_new"]]
    print(f"\n=== 成功开新会话的动作: {winners if winners else '无'} ===")

    with open("output/doubao_newchat2_dom.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("证据: output/doubao_newchat2_dom.json")

    await page.screenshot(path="output/doubao_newchat2_debug.png", full_page=True)
    print("截图: output/doubao_newchat2_debug.png")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(debug())
