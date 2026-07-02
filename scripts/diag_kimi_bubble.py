"""Kimi 搜索面板→正文 DOM 证据采集 — 定位为何只抓到搜索面板

0630 kimi 3 坏题(q020/q028/q036)只抓到「搜索网页\\n<关键词>\\nN个结果」搜索面板,
正文全丢。根因怀疑:_wait_for_kimi_text_stability 用 chatArea.innerText 长度判稳定,
搜索面板渲染完(52字)后、正文起笔前有停顿,停顿期误判稳定→抓到搜索面板就返回。

本轮:跑 q020,在 _wait_for_response 判稳定时立刻 dump + 多等 25s 后再 dump,
看 segment-assistant 是否含搜索面板、正文在哪个节点、为何 TreeWalker 漏掉。
"""
import asyncio
import io
import json
import os
import sys

if sys.platform == "win32" and sys.stdout is not None:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, io.UnsupportedOperation, ValueError):
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client

Q = "国内云厂商出海能力哪家强？"  # q020, 0630 只抓到52字搜索面板

DUMP_JS = """
() => {
  const out = { url: location.href };
  // segment-assistant 元素清单
  const segs = Array.from(document.querySelectorAll('segment.segment-assistant, .segment-assistant'));
  out.segments = segs.map((s, i) => ({
    idx: i, cls: (typeof s.className === 'string') ? s.className.slice(0, 80) : '',
    inner_len: (s.innerText || '').length,
    text_head: (s.innerText || '').trim().slice(0, 80),
    has_search_panel: /搜索网页|个结果/.test(s.innerText || ''),
  }));
  // chatArea innerText (与 _wait_for_kimi_text_stability 同源)
  const chatArea = document.querySelector('.chat-content, [class*="chat-content"], [class*="conversation"], main') || document.body;
  out.chat_area_len = (chatArea.innerText || '').length;
  out.chat_area_head = (chatArea.innerText || '').trim().slice(0, 100);
  out.has_search_panel = /搜索网页|个结果/.test(chatArea.innerText || '');
  // 找含「搜索网页」的元素及其后兄弟(正文可能在其后)
  const all = Array.from(document.querySelectorAll('div, section, segment'));
  const searchPanels = [];
  for (const el of all) {
    const t = (el.innerText || '').trim();
    if (/搜索网页/.test(t) && /个结果/.test(t) && t.length < 200) {
      const next = el.nextElementSibling;
      searchPanels.push({
        cls: (typeof el.className === 'string') ? el.className.slice(0, 60) : '',
        text: t.slice(0, 80),
        next_tag: next ? next.tagName.toLowerCase() : null,
        next_cls: next ? ((typeof next.className === 'string') ? next.className.slice(0, 60) : '') : null,
        next_len: next ? (next.innerText || '').length : 0,
        next_head: next ? (next.innerText || '').trim().slice(0, 80) : '',
      });
    }
  }
  out.search_panels = searchPanels.slice(0, 4);
  return out;
}
"""


async def main():
    os.environ["DISPLAY"] = ":0"
    os.makedirs("output", exist_ok=True)

    print("启动 Kimi 客户端（沿用登录态）...")
    client = create_web_chat_client("kimi")
    if not await client.initialize():
        print("浏览器启动失败"); return
    page = client._page

    print(f"\n发题(手动控制等待): {Q}")
    await client._start_new_chat(page)
    await client._type_question(page, Q)
    await client._send_question(page)

    # A: wait_for_response 判稳定时立刻 dump
    print("[A] 调 _wait_for_response ...")
    await client._wait_for_response(page, timeout=120)
    body_early = await client._extract_response(page)
    print(f"[A] wait完即extract: {len(body_early)}字 head={body_early[:60]!r}")
    snap_early = {"tag": "early", "extracted_len": len(body_early),
                  "extracted_head": body_early[:200],
                  "dom": await page.evaluate(DUMP_JS)}
    await page.screenshot(path="output/kimi_bubble_early.png", full_page=True)

    # B: 多等 25s 后重采
    print("[B] 额外等 25 秒后重采 ...")
    await asyncio.sleep(25)
    body_late = await client._extract_response(page)
    print(f"[B] 加等后extract: {len(body_late)}字 head={body_late[:60]!r}")
    snap_late = {"tag": "late", "extracted_len": len(body_late),
                 "extracted_head": body_late[:200],
                 "dom": await page.evaluate(DUMP_JS)}
    await page.screenshot(path="output/kimi_bubble_late.png", full_page=True)

    result = {"question": Q, "stages": {"early": snap_early, "late": snap_late}}
    with open("output/kimi_bubble_dom.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\n证据: output/kimi_bubble_dom.json + 2 张截图")

    for tag, s in (("early", snap_early), ("late", snap_late)):
        print(f"\n=== {tag} extract={s['extracted_len']}字 ===")
        dom = s["dom"]
        print(f"  url={dom.get('url')}")
        print(f"  chat_area_len={dom.get('chat_area_len')} has_search_panel={dom.get('has_search_panel')}")
        print(f"  chat_area_head={dom.get('chat_area_head')!r}")
        print(f"  segments({len(dom.get('segments', []))}):")
        for sg in dom.get("segments", []):
            print(f"    [{sg['idx']}] cls={sg['cls']!r} len={sg['inner_len']} search_panel={sg['has_search_panel']} head={sg['text_head'][:50]!r}")
        print(f"  search_panels({len(dom.get('search_panels', []))}):")
        for sp in dom.get("search_panels", []):
            print(f"    cls={sp['cls']!r} txt={sp['text'][:40]!r}")
            print(f"      next=<{sp['next_tag']}> cls={sp['next_cls']!r} len={sp['next_len']} head={sp['next_head'][:50]!r}")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(main())
