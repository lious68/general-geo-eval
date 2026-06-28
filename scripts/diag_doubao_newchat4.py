"""豆包粘性会话定位 — 只读证据采集

为什么有这轮：newchat3 证实「新对话」点击能导航到干净 /chat（msg_count 0），
但一发送就回到 q003 的同一个会话 id 38432792893519106。怀疑登录态把该会话
钉成"当前活动会话"，存在 localStorage/sessionStorage 里，/chat 发送时被恢复。

本脚本（只读，不清理不登出）：
  1) 发 q003 → 等响应
  2) 点「新对话」→ 到 /chat（msg_count 0）
  3) dump 全部 localStorage + sessionStorage 键值（截断），找含 conversation/
     chat/session/38432792893519106 的键 —— 定位"粘性会话指针"
  4) dump message-list 每一行的结构（tag/class/role/文本头/user-or-assistant），
     为"只取最后一条 assistant 回答"的 extractor 兜底备好选择器
  5) 发 q011 → 确认又回到 38432792893519106（复现粘性）

落 output/doubao_newchat4_dom.json。
"""
import asyncio
import io
import json
import os
import sys

# Windows 控制台 GBK，emoji/特殊字符会崩。包 utf-8。
if sys.platform == "win32" and sys.stdout is not None:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, io.UnsupportedOperation, ValueError):
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client

Q003 = "UCloud海外有哪些节点？"
Q011 = "UCloud和阿里云有什么区别？"
STICKY_ID = "38432792893519106"


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
    try:
        return await page.evaluate("""() => {
          const ml = document.querySelector('[class*="message-list"]');
          const cnt = ml ? ml.querySelectorAll('[class*="message-row"], [class*="v_list_row"], [class*="chat-message"]').length : 0;
          return { url: location.href, msg_count: cnt };
        }""")
    except Exception:
        return {"url": page.url, "msg_count": -1}


async def click_new_chat_button(page):
    await _dismiss_overlays(page)
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
            return { ok: true };
          }
          return { ok: false };
        }""")
        if clicked and clicked.get("ok"):
            await asyncio.sleep(2.0)
            return True
    except Exception as e:
        print(f"  [click] 异常: {e}")
    return False


async def dump_storage(page):
    """dump localStorage + sessionStorage，标注含粘性 id / conversation 的键。"""
    return await page.evaluate("""(stickyId) => {
      const dump = (store, name) => {
        const out = [];
        for (let i = 0; i < store.length; i++) {
          const k = store.key(i);
          let v = '';
          try { v = store.getItem(k) || ''; } catch(e) { v = '<err>'; }
          const vs = v.toString();
          const hot = (vs.includes(stickyId) || /conv|chat|session|dialog|active|current|last/i.test(k + vs.slice(0,200)));
          out.push({ store: name, key: k, len: vs.length,
                     val_head: vs.slice(0, 200), hot });
        }
        return out.sort((a,b) => (b.hot - a.hot));
      };
      return [...dump(localStorage, 'local'), ...dump(sessionStorage, 'session')];
    }""", STICKY_ID)


async def dump_message_rows(page):
    """dump message-list 每一行结构，区分 user/assistant。"""
    return await page.evaluate("""() => {
      const ml = document.querySelector('[class*="message-list"]');
      if (!ml) return [];
      const rows = ml.children;
      const out = [];
      for (let i = 0; i < rows.length; i++) {
        const el = rows[i];
        const cls = (typeof el.className === 'string') ? el.className : '';
        const txt = (el.textContent || '').trim().slice(0, 80);
        // user/assistant 启发：assistant 通常含 markdown/长文；user 通常短且是问题原文
        const hasMarkdown = !!el.querySelector('[class*="markdown"], [class*="content"]');
        out.push({
          idx: i, tag: el.tagName.toLowerCase(),
          cls: cls.slice(0, 120),
          text_head: txt,
          has_markdown: hasMarkdown,
          child_count: el.children.length,
        });
      }
      return out;
    }""")


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

    result = {"stages": {}}

    # A) 发 q003
    print(f"发 q003: {Q003}")
    await client._type_question(page, Q003)
    await client._send_question(page)
    await client._wait_for_response(page, timeout=120)
    st0 = await _state(page)
    print(f"[q003 完成] {st0}")
    result["stages"]["after_q003"] = st0

    # B) 点新对话 → /chat
    print("点「新对话」...")
    opened = await click_new_chat_button(page)
    st1 = await _state(page)
    print(f"[点新对话后] opened={opened} {st1}")
    result["stages"]["after_newchat_click"] = {"opened": opened, "state": st1}

    # C) dump storage —— 定位粘性会话指针
    storage = await dump_storage(page)
    hot = [s for s in storage if s["hot"]]
    result["stages"]["storage_dump"] = storage
    result["stages"]["storage_hot"] = hot
    print(f"\n[storage] 共 {len(storage)} 键，含粘性id/会话相关 {len(hot)} 键:")
    for s in hot:
        print(f"  [{s['store']}] {s['key']} (len={s['len']})  hot={s['hot']}")
        print(f"      val_head: {s['val_head'][:160]}")

    # D) dump message-list 行结构（此时 /chat 应为空，先发 q011 再 dump 更有料）
    rows_pre = await dump_message_rows(page)
    result["stages"]["rows_after_newchat_pre_send"] = rows_pre
    print(f"\n[/chat 发送前 message-list 行数] {len(rows_pre)}")

    # E) 发 q011 → 复现粘性
    print(f"\n发 q011: {Q011}")
    await client._type_question(page, Q011)
    await client._send_question(page)
    await client._wait_for_response(page, timeout=120)
    st2 = await _state(page)
    q011_text = await client._extract_response(page)
    resumed_sticky = STICKY_ID in st2["url"]
    contaminated = "UCloud海外有哪些节点" in q011_text
    result["stages"]["after_q011"] = {
        "state": st2, "resumed_sticky_id": resumed_sticky,
        "contaminated": contaminated, "body_len": len(q011_text),
    }
    print(f"[q011 完成] {st2}  resumed_sticky={resumed_sticky}  contaminated={contaminated}")

    # ── 关键：定位 Q003_MARK 在 q011_text 的位置，判 contamination 真假 ──
    mark = "UCloud海外有哪些节点"
    mark_pos = q011_text.find(mark)
    if mark_pos >= 0:
        ctx_start = max(0, mark_pos - 80)
        ctx_end = min(len(q011_text), mark_pos + 120)
        is_in_citation_zone = mark_pos > len(q011_text) * 0.6  # 出现在后 40% 多半是引用区
        result["stages"]["q003_mark_loc"] = {
            "pos": mark_pos, "total_len": len(q011_text),
            "ratio": round(mark_pos / max(1, len(q011_text)), 3),
            "in_citation_zone_guess": is_in_citation_zone,
            "context": q011_text[ctx_start:ctx_end],
        }
        print(f"\n[Q003_MARK 定位] pos={mark_pos}/{len(q011_text)} ratio={mark_pos/len(q011_text):.2f}")
        print(f"  上下文: ...{q011_text[ctx_start:ctx_end]}...")
        print(f"  → {'疑似引用区误命中(假阳性)' if is_in_citation_zone else '疑似正文残留(真污染)'}")
    else:
        result["stages"]["q003_mark_loc"] = {"pos": -1}
        print(f"\n[Q003_MARK 定位] 未出现 → 无污染")

    # F) dump q011 后的 message-list 行结构 —— 看 q003 和 q011 是否都在同一 list
    rows_post = await dump_message_rows(page)
    result["stages"]["rows_after_q011"] = rows_post
    print(f"\n[q011 后 message-list 行数] {len(rows_post)}:")
    for r in rows_post:
        print(f"  [{r['idx']}] <{r['tag']}> cls={r['cls'][:50]!r} md={r['has_markdown']} kids={r['child_count']}  text={r['text_head'][:50]!r}")

    with open("output/doubao_newchat4_dom.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\n证据: output/doubao_newchat4_dom.json")

    await page.screenshot(path="output/doubao_newchat4_debug.png", full_page=True)
    await client.close()
    print("完成。")


if __name__ == "__main__":
    asyncio.run(debug())
