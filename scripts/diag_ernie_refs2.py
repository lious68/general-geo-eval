"""文心一言引用源 URL 定位 v2 — 抓参考资料面板完整 outerHTML + 序号项结构

v1 发现：响应里有"共参考N篇资料"+序号标题列表，但找不到列表项(li)。
说明参考资料面板用的是别的结构。v2 dump：
  - answer-box 完整 outerHTML（截断）找序号项真实结构
  - 全页找带数字序号+标题的文本节点结构
  - 找"共参考"文本节点的祖先与兄弟完整 HTML
  - 检查 a[href] 是否在更深层（cs-answer 内）
"""
import asyncio
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["DISPLAY"] = ":0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from web_chat_clients import create_web_chat_client  # noqa: E402

QUESTION = "UCloud海外有哪些节点？"

PROBE = """
() => {
  const out = { ref_block_html: '', numbered_items: [], all_a_in_answer: [], ref_ancestor_html: '' };
  // 1) 找"共参考"文本节点，dump 其最近含 class 的祖先 outerHTML
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (n.textContent||'').includes('共参考') ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT
  });
  let n = walker.nextNode();
  if (n) {
    let p = n.parentElement;
    // 向上找一个像容器的祖先
    let guard = 0;
    while (p && guard < 8) {
      if (p.className && p.children.length > 1) break;
      p = p.parentElement; guard++;
    }
    if (p) out.ref_ancestor_html = p.outerHTML.slice(0, 2000);
  }
  // 2) answer-box 内所有 a[href]（含 baidu 内部跳转）
  const ab = document.querySelector('.answer-box.last-answer-box, .answer-box, .conversation-flow-answer-container');
  if (ab) {
    ab.querySelectorAll('a[href]').forEach(a => {
      out.all_a_in_answer.push({ href: a.href, text: (a.textContent||'').trim().slice(0,50),
        visible: !!(a.offsetWidth||a.offsetHeight),
        cls: (typeof a.className==='string')?a.className.slice(0,60):'' });
    });
    // answer-box 内所有 li
    ab.querySelectorAll('li').forEach((li,i) => {
      if (i>=12) return;
      const a = li.querySelector('a[href]');
      out.numbered_items.push({ text:(li.textContent||'').trim().slice(0,80),
        href: a?a.href:null, html: li.outerHTML.slice(0,300) });
    });
  }
  return out;
}
"""


async def main():
    c = create_web_chat_client("ernie")
    if not await c.initialize():
        print("❌ 启动失败"); return
    page = c._page
    await c._navigate_to_chat(page)
    print(f"发送: {QUESTION}")
    await c._type_question(page, QUESTION)
    await c._send_question(page)
    print("等待响应...")
    await c._wait_for_response(page, timeout=180)

    res = await page.evaluate(PROBE)
    print(f"\n[answer-box 内 a[href]] {len(res['all_a_in_answer'])} 个")
    for a in res['all_a_in_answer'][:20]:
        print(f"  vis={a['visible']} cls={a['cls'][:30]} {a['text']!r} -> {a['href']}")
    print(f"\n[answer-box 内 li] {len(res['numbered_items'])} 个")
    for it in res['numbered_items'][:6]:
        print(f"  href={it['href']} text={it['text']!r}")
        print(f"    html: {it['html'][:250]}")
    print(f"\n[共参考祖先 HTML(前1500)]:")
    print(res['ref_ancestor_html'][:1500])

    await page.screenshot(path="output/ernie_refs_debug.png", full_page=True)
    await c.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(main())
