"""豆包「新对话」按钮隔离 — 端到端验证（证据采集 + 修复测试用例）

用法:
    python scripts/diag_doubao_newchat3.py

为什么有这轮：上一轮点的是侧栏 .first（=豆包 logo），它回的是首页
/恢复会话，不是真开新对话。用户指认正解是点 logo 下面那个独立的
「新对话」nav 项（结构见下，快捷键 Ctrl Shift K）：
    <div class="truncate ... s-font-small flex items-center">
      <span class="font-medium">新对话</span>
      <div ...>Ctrl Shift K</div>
    </div>

本脚本验证「点新对话按钮」能否真清空会话：
  1) 发 q003「UCloud海外有哪些节点？」→ 等响应
  2) 点「新对话」按钮（JS 精确定位 span 文本==新对话 的可点击祖先；失败兜底 Ctrl+Shift+K）
  3) 校验：URL 变 /chat（无 session id）且 message-list 清空
  4) 发 q011「UCloud和阿里云有什么区别？」→ 等响应 → 提取正文
  5) 判定隔离成功：q011 正文里不应出现 q003 的问题文本「UCloud海外有哪些节点」
     （v3 失败的标志正是 q011 正文第 1 行 = q003 的问题文本）

落 output/doubao_newchat3_dom.json + 截图。
这里的 click_new_chat_button() 即后续要移植进 _start_new_chat 的逻辑。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client

Q003 = "UCloud海外有哪些节点？"
Q011 = "UCloud和阿里云有什么区别？"

# q003 问题文本特征 —— q011 正文若含它，说明会话没隔离（q003 问答残留在 message-list）
Q003_MARK = "UCloud海外有哪些节点"


async def _dismiss_overlays(page):
    for sel in [
        "[role='dialog'] [class*='close']",
        "[role='dialog'] button[aria-label*='关闭']",
        "[role='dialog'] button[aria-label*='Close']",
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
    """url + message-list 消息条数。"""
    try:
        return await page.evaluate("""() => {
          const ml = document.querySelector('[class*="message-list"]');
          const cnt = ml ? ml.querySelectorAll('[class*="message-row"], [class*="v_list_row"], [class*="chat-message"]').length : 0;
          return { url: location.href, msg_count: cnt };
        }""")
    except Exception:
        return {"url": page.url, "msg_count": -1}


async def _dump_newchat_btn(page):
    """dump「新对话」按钮真实 DOM（tag/class/容器路径/坐标），供移植选择器用。"""
    return await page.evaluate("""() => {
      const out = [];
      // 找文本含「新对话」的可点元素及其可点击祖先
      const all = Array.from(document.querySelectorAll('span, div, button, a, [role="button"]'));
      for (const el of all) {
        const ownText = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
        const t = (el.textContent || '').trim();
        if (!(ownText === '新对话' || t === '新对话' || (t.includes('新对话') && t.length < 12))) continue;
        // 向上找可点击祖先
        let click = el;
        for (let i = 0; i < 5 && click; i++) {
          const tag = click.tagName.toLowerCase();
          const cls = (typeof click.className === 'string') ? click.className : '';
          const role = click.getAttribute('role') || '';
          if (tag === 'button' || tag === 'a' || role === 'button' || /sidebar_nav_item|nav[-_]item/i.test(cls)) break;
          click = click.parentElement;
        }
        const chain = [];
        let p = click; let g = 0;
        while (p && p !== document.body && g < 7) {
          const c = (typeof p.className === 'string') ? p.className.split(/\\s+/).filter(Boolean).slice(0,2).join('.') : '';
          const id = p.id ? '#' + p.id : '';
          chain.unshift(p.tagName.toLowerCase() + (c ? '.' + c : '') + id);
          p = p.parentElement; g++;
        }
        const r = (click || el).getBoundingClientRect();
        out.push({
          hit_text: t.slice(0, 20),
          click_tag: (click || el).tagName.toLowerCase(),
          click_cls: ((click || el).className || '').toString().slice(0, 120),
          container: chain.join(' > '),
          x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
          visible: !!(r.width && r.height),
        });
      }
      return out;
    }""")


async def click_new_chat_button(page):
    """点「新对话」按钮 —— 后续移植进 _start_new_chat 的逻辑。

    策略：JS 精确定位 span/div 文本==「新对话」的可点击祖先并 .click()；
    失败兜底 Ctrl+Shift+K（侧栏提示的快捷键）。
    返回 (opened: bool, method: str, detail: str)。
    """
    await _dismiss_overlays(page)
    # 1) JS 定位 + DOM click
    try:
        clicked = await page.evaluate("""() => {
          const all = Array.from(document.querySelectorAll('span, div, button, a, [role="button"]'));
          for (const el of all) {
            const ownText = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
            const t = (el.textContent || '').trim();
            if (!(ownText === '新对话' || t === '新对话' || (t.includes('新对话') && t.length < 12))) continue;
            let click = el;
            for (let i = 0; i < 5 && click; i++) {
              const tag = click.tagName.toLowerCase();
              const cls = (typeof click.className === 'string') ? click.className : '';
              const role = click.getAttribute('role') || '';
              if (tag === 'button' || tag === 'a' || role === 'button' || /sidebar_nav_item|nav[-_]item/i.test(cls)) break;
              click = click.parentElement;
            }
            const target = click || el;
            const r = target.getBoundingClientRect();
            if (!r.width || !r.height) continue;
            target.click();
            return { ok: true, tag: target.tagName.toLowerCase(), cls: (target.className||'').toString().slice(0,80) };
          }
          return { ok: false };
        }""")
        if clicked and clicked.get("ok"):
            await asyncio.sleep(2.0)
            st = await _state(page)
            # /chat 无 session id 视为开新会话（豆包新对话落地页就是 /chat）
            is_new = ("/chat/" not in st["url"]) or (st["msg_count"] == 0)
            if is_new:
                return True, "js-click新对话", f"after={st}"
            # 点到了但没清空 → 可能点到 logo，继续走快捷键
    except Exception as e:
        print(f"  [js-click] 异常: {e}")

    # 2) 兜底：Ctrl+Shift+K
    try:
        await page.keyboard.press("Control+Shift+KeyK")
        await asyncio.sleep(2.0)
        st = await _state(page)
        is_new = ("/chat/" not in st["url"]) or (st["msg_count"] == 0)
        if is_new:
            return True, "Ctrl+Shift+K", f"after={st}"
    except Exception as e:
        print(f"  [Ctrl+Shift+K] 异常: {e}")

    st = await _state(page)
    return False, "none", f"after={st}"


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

    result = {"q003": Q003, "q011": Q011, "stages": {}}

    # ── A) 先 dump「新对话」按钮 DOM（在干净的新对话页就能看到）──
    btn_dom = await _dump_newchat_btn(page)
    result["stages"]["newchat_btn_dom"] = btn_dom
    print(f"\n[新对话按钮 DOM] {len(btn_dom)} 个命中:")
    for b in btn_dom:
        print(f"  <{b['click_tag']}> cls={b['click_cls'][:50]!r} vis={b['visible']} pos=({b['x']},{b['y']}) size={b['w']}x{b['h']}")
        print(f"      容器: {b['container'][:140]}")

    # ── B) 发 q003 ──
    print(f"\n发题 q003: {Q003}")
    await client._type_question(page, Q003)
    await client._send_question(page)
    print("等响应(q003)...")
    await client._wait_for_response(page, timeout=120)
    st_after_q003 = await _state(page)
    q003_text = await client._extract_response(page)
    result["stages"]["after_q003"] = {
        "state": st_after_q003,
        "body_head": q003_text[:200],
        "body_len": len(q003_text),
        "contains_q003_mark": Q003_MARK in q003_text,
    }
    print(f"[q003 完成] {st_after_q003}  正文{len(q003_text)}字  含q003mark={Q003_MARK in q003_text}")

    # ── C) 点「新对话」按钮 ──
    print("\n点「新对话」按钮...")
    opened, method, detail = await click_new_chat_button(page)
    st_after_new = await _state(page)
    result["stages"]["click_new_chat"] = {
        "opened": opened, "method": method, "detail": detail,
        "state_after": st_after_new,
    }
    print(f"[点新对话] opened={opened} method={method} {detail}")
    print(f"[点新对话后] {st_after_new}")
    await _dismiss_overlays(page)

    # ── D) 发 q011 ──
    print(f"\n发题 q011: {Q011}")
    await client._type_question(page, Q011)
    await client._send_question(page)
    print("等响应(q011)...")
    await client._wait_for_response(page, timeout=120)
    st_after_q011 = await _state(page)
    q011_text = await client._extract_response(page)
    contaminated = Q003_MARK in q011_text
    result["stages"]["after_q011"] = {
        "state": st_after_q011,
        "body_head": q011_text[:300],
        "body_len": len(q011_text),
        "contains_q003_mark": contaminated,  # True = 隔离失败（q003 残留）
    }
    result["isolation_ok"] = not contaminated
    print(f"\n[q011 完成] {st_after_q011}  正文{len(q011_text)}字")
    print(f"[隔离判定] q011正文含q003问题文本(Q003_MARK)={contaminated}")
    print(f"  → {'❌ 隔离失败：q011 仍串入 q003' if contaminated else '✅ 隔离成功：q011 无 q003 残留'}")
    print(f"  q011 正文开头:\n{q011_text[:300]}")

    with open("output/doubao_newchat3_dom.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\nDOM 证据: output/doubao_newchat3_dom.json")
    with open("output/_v4_q011_body.txt", "w", encoding="utf-8") as f:
        f.write(q011_text)
    print("q011 正文: output/_v4_q011_body.txt")

    await page.screenshot(path="output/doubao_newchat3_debug.png", full_page=True)
    print("截图: output/doubao_newchat3_debug.png")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(debug())
