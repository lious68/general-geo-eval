"""豆包「新建对话」按钮 DOM 证据采集 — 定位真实选择器 + 验证是否真开新会话

用法:
    python scripts/diag_doubao_newchat.py

复用 create_web_chat_client("doubao") + 已存 storage_state。
流程：导航 → 发一题 → 等响应 → 探测新建对话按钮候选 → 点最佳候选 →
验证是否真开了新会话（消息列表清空 / URL 变化）。同时测 goto /chat 会不会
恢复旧会话。据此定 _start_new_chat 的真实选择器。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client

QUESTION = "UCloud海外有哪些节点？"


# 探测左侧栏所有可点元素（不限关键词），找出「新建对话」按钮真实结构
SIDEBAR_PROBE = """
() => {
  const out = [];
  // 左侧栏区域：x < 320 或 class 含 sidebar/aside/nav
  const all = Array.from(document.querySelectorAll('button, a, [role="button"], [role="menuitem"], li, div[onclick]'));
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    // 只取左侧栏（x < 320）或带 sidebar/aside/nav class 的
    const cls = (typeof el.className === 'string') ? el.className : '';
    const inLeft = r.x < 320 || /sidebar|aside|nav-|side-|left-side/i.test(cls);
    if (!inLeft) continue;
    const t = (el.textContent || '').trim();
    const aria = el.getAttribute('aria-label') || '';
    const title = el.getAttribute('title') || '';
    const tag = el.tagName.toLowerCase();
    const href = el.getAttribute('href') || '';
    // 跳过纯长文本容器（消息项），只看短的可点控件
    if (t.length > 30 && !aria && !title) continue;
    // 容器路径
    const chain = [];
    let p = el; let g = 0;
    while (p && p !== document.body && g < 6) {
      const c = (typeof p.className === 'string') ? p.className.split(/\\s+/).filter(Boolean).slice(0,2).join('.') : '';
      const id = p.id ? '#' + p.id : '';
      chain.unshift(p.tagName.toLowerCase() + (c ? '.' + c : '') + id);
      p = p.parentElement; g++;
    }
    out.push({
      tag, text: t.slice(0, 25), aria, title, cls: cls.slice(0, 80), href,
      container: chain.join(' > '),
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      hasSvg: !!el.querySelector('svg'),
    });
  }
  return out;
}
"""


async def _dismiss_overlays(page):
    for sel in [
        "[role='dialog'] [class*='close']",
        "[role='dialog'] button[aria-label*='关闭']",
        "[role='dialog'] button[aria-label*='Close']",
        "div[class*='mask'], div[class*='overlay'], div[class*='backdrop']",
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1500):
                await loc.click(timeout=2000)
                await asyncio.sleep(0.4)
        except Exception:
            pass
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
    except Exception:
        pass


# 探测所有疑似「新建对话」按钮：文本/aria-label/类名/容器路径
NEWCHAT_PROBE = """
() => {
  const out = [];
  // 文本关键词候选
  const KW = ['新建对话', '新对话', '新聊天', 'New chat', 'New Chat', '开启新对话'];
  const all = Array.from(document.querySelectorAll('button, a, [role="button"], div[onclick], [class*="new"]'));
  for (const el of all) {
    const t = (el.textContent || '').trim();
    const aria = el.getAttribute('aria-label') || '';
    const title = el.getAttribute('title') || '';
    const cls = (typeof el.className === 'string') ? el.className : '';
    const href = el.getAttribute('href') || '';
    const isKw = KW.some(k => t.includes(k) || aria.includes(k) || title.includes(k));
    const isClassNew = /new[-_ ]?(chat|conversation|dialog|session)/i.test(cls);
    const isPlus = /\+/.test(t) && /chat|conv|session|对话/i.test(cls + aria);
    if (!(isKw || isClassNew || isPlus)) continue;
    // 容器路径
    const chain = [];
    let p = el;
    let g = 0;
    while (p && p !== document.body && g < 8) {
      const tag = p.tagName.toLowerCase();
      const c = (typeof p.className === 'string') ? p.className.split(/\\s+/).filter(Boolean).slice(0,3).join('.') : '';
      const id = p.id ? '#' + p.id : '';
      chain.unshift(tag + (c ? '.' + c : '') + id);
      p = p.parentElement; g++;
    }
    const rect = el.getBoundingClientRect();
    out.push({
      tag: el.tagName.toLowerCase(), text: t.slice(0, 30), aria, title,
      cls: cls.slice(0, 120), href,
      container: chain.join(' > '),
      visible: !!(rect.width && rect.height),
      x: rect.x, y: rect.y, w: rect.width, h: rect.height,
    });
  }
  return out;
}
"""


async def _msg_count(page):
    """当前会话消息条数（assistant 回答数）。"""
    try:
        return await page.evaluate("""() => {
          // 豆包回答区在 message-list 内，count message rows
          const ml = document.querySelector('[class*="message-list"]');
          if (!ml) return 0;
          return ml.querySelectorAll('[class*="message-row"], [class*="v_list_row"], [class*="chat-message"]').length;
        }""")
    except Exception:
        return -1


async def debug():
    os.environ["DISPLAY"] = ":0"
    os.makedirs("output", exist_ok=True)

    print("启动豆包客户端（沿用登录态）...")
    client = create_web_chat_client("doubao")
    ok = await client.initialize()
    if not ok:
        print("浏览器启动失败")
        return

    await client._navigate_to_chat(client._page)
    page = client._page
    await _dismiss_overlays(page)

    print(f"发题: {QUESTION}")
    await client._type_question(page, QUESTION)
    await client._send_question(page)
    print("等响应...")
    await client._wait_for_response(page, timeout=120)

    result = {"question": QUESTION, "stages": {}}

    # A) 探测新建对话按钮候选
    cand = await page.evaluate(NEWCHAT_PROBE)
    result["stages"]["newchat_candidates"] = cand
    print(f"\n[新建对话按钮候选(关键词)] {len(cand)} 个:")
    for c in cand:
        print(f"  <{c['tag']}> text={c['text']!r} aria={c['aria']!r} cls={c['cls'][:50]!r} vis={c['visible']} pos=({int(c['x'])},{int(c['y'])})")
        print(f"      容器: {c['container'][:140]}")

    # A2) 左侧栏全部可点控件（不限关键词，定位真实结构）
    side = await page.evaluate(SIDEBAR_PROBE)
    result["stages"]["sidebar_controls"] = side
    print(f"\n[左侧栏可点控件] {len(side)} 个:")
    for c in side[:20]:
        print(f"  <{c['tag']}> text={c['text']!r} aria={c['aria']!r} title={c['title']!r} svg={c['hasSvg']} pos=({c['x']},{c['y']}) size=({c['w']}x{c['h']})")
        print(f"      cls={c['cls'][:60]!r} 容器: {c['container'][:120]}")

    msgs_before = await _msg_count(page)
    url_before = page.url
    result["stages"]["before_newchat"] = {"url": url_before, "msg_count": msgs_before}
    print(f"\n[点之前] url={url_before}  msg_count={msgs_before}")

    # B) 点最佳候选（优先可见 + 文本最像「新建」）
    target = None
    for c in cand:
        if c["visible"] and any(k in (c["text"] + c["aria"]) for k in ["新建对话", "新对话", "New chat", "新聊天"]):
            target = c; break
    if not target:
        for c in cand:
            if c["visible"]:
                target = c; break

    clicked = None
    if target:
        try:
            # 用文本/aria 定位
            key = target["text"] or target["aria"]
            if key:
                loc = page.get_by_text(key, exact=False).first
            else:
                loc = page.locator(target["container"].split(" > ")[-1]).first
            await loc.click(timeout=4000)
            await asyncio.sleep(2.0)
            clicked = target
            print(f"\n[已点] <{target['tag']}> {key!r}")
        except Exception as e:
            print(f"\n[点击失败] {e}")
            clicked = {"error": str(e), "target": target}

    msgs_after = await _msg_count(page)
    url_after = page.url
    result["stages"]["after_newchat_click"] = {
        "clicked": clicked, "url": url_after, "msg_count": msgs_after,
        "url_changed": url_before != url_after,
        "msg_count_changed": msgs_before != msgs_after,
    }
    print(f"[点之后] url={url_after}  msg_count={msgs_after}  url_changed={url_before != url_after}  msg_changed={msgs_before != msgs_after}")

    # C) 对照：goto /chat 会不会恢复旧会话？
    #    先回到有对话的状态（若上面已开新会话，再发一题制造一条消息）
    try:
        await _dismiss_overlays(page)
        await client._type_question(page, "AWS海外节点有哪些？")
        await client._send_question(page)
        await client._wait_for_response(page, timeout=120)
        msgs_pre_goto = await _msg_count(page)
        url_pre_goto = page.url
        print(f"\n[goto 对照] 发第二题后 url={url_pre_goto} msg_count={msgs_pre_goto}")
        # 现在直接 goto /chat
        await page.goto("https://www.doubao.com/chat", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        await _dismiss_overlays(page)
        msgs_post_goto = await _msg_count(page)
        url_post_goto = page.url
        result["stages"]["goto_chat_test"] = {
            "pre_url": url_pre_goto, "pre_msg_count": msgs_pre_goto,
            "post_url": url_post_goto, "post_msg_count": msgs_post_goto,
            "restored_old_session": msgs_post_goto >= msgs_pre_goto and msgs_pre_goto > 0,
        }
        print(f"[goto /chat 后] url={url_post_goto} msg_count={msgs_post_goto}  恢复旧会话={msgs_post_goto >= msgs_pre_goto and msgs_pre_goto > 0}")
    except Exception as e:
        print(f"[goto 对照失败] {e}")
        result["stages"]["goto_chat_test"] = {"error": str(e)}

    with open("output/doubao_newchat_dom.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\nDOM 证据: output/doubao_newchat_dom.json")

    await page.screenshot(path="output/doubao_newchat_debug.png", full_page=True)
    print("截图: output/doubao_newchat_debug.png")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(debug())
