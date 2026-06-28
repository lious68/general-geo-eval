"""文心一言 (chat.baidu.com) 引用源 URL 定位诊断

问题：_extract_response 抓到的回答里有"共参考27篇资料"+序号+标题列表，
但列表项里没有 <a href>，导致 URL 抓不到、citation_rate 偏低。
本脚本采集：参考资料列表项的真实 DOM 结构，找 URL 藏在哪（a[href] /
data-* 属性 / 点击展开 / 角标 popover）。

用法（Win RDP，前台 PowerShell）：
    cd C:\\general-geo-eval
    python scripts\\diag_ernie_refs.py
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

# 参考资料列表项 DOM 结构
REF_LIST_PROBE = """
() => {
  const out = { items: [], hrefs: [], data_attrs: [] };
  // 找含"参考"文本的容器
  const KW = ['共参考', '参考', '资料', '来源', '搜索'];
  const cand = [];
  document.querySelectorAll('div, section, ul, ol, li').forEach(el => {
    const t = (el.textContent || '').trim();
    if (t.length > 0 && t.length < 30 && KW.some(k => t.includes(k))) {
      cand.push(el);
    }
  });
  // 对每个候选，dump 它及其后续兄弟的结构
  for (const root of cand.slice(0, 3)) {
    // 收集 root 之后的所有 li / 列表项
    const scope = root.parentElement || root;
    const lis = scope.querySelectorAll('li, [class*="item"], [class*="source"], [class*="ref"]');
    lis.forEach((li, i) => {
      if (i >= 10) return;
      const a = li.querySelector('a[href]');
      out.items.push({
        text: (li.textContent || '').trim().slice(0, 80),
        has_a: !!a,
        a_href: a ? a.href : null,
        a_text: a ? (a.textContent||'').trim().slice(0,40) : null,
        html: li.outerHTML.slice(0, 400),
        cls: (typeof li.className==='string') ? li.className.slice(0,80) : '',
      });
    });
  }
  // 全页所有 a[href]（看有没有外部链接藏在别处）
  document.querySelectorAll('a[href]').forEach(a => {
    const h = a.href;
    if (h.startsWith('http') && !h.includes('baidu.com')) {
      out.hrefs.push({ href: h, text: (a.textContent||'').trim().slice(0,40),
        visible: !!(a.offsetWidth||a.offsetHeight) });
    }
  });
  // 带 data-url / data-href / data-link 的元素
  document.querySelectorAll('[data-url], [data-href], [data-link], [data-src]').forEach(el => {
    out.data_attrs.push({ tag: el.tagName.toLowerCase(),
      url: el.getAttribute('data-url')||el.getAttribute('data-href')||el.getAttribute('data-link')||el.getAttribute('data-src'),
      text: (el.textContent||'').trim().slice(0,60) });
  });
  return out;
}
"""


async def main():
    c = create_web_chat_client("ernie")
    if not c.is_configured:
        print("❌ 无 ernie 登录态"); return
    if not await c.initialize():
        print("❌ 浏览器启动失败"); return
    page = c._page
    await c._navigate_to_chat(page)
    print(f"发送问题: {QUESTION}")
    await c._type_question(page, QUESTION)
    await c._send_question(page)
    print("等待响应...")
    await c._wait_for_response(page, timeout=180)

    await page.screenshot(path="output/ernie_refs_debug.png", full_page=True)
    res = await page.evaluate(REF_LIST_PROBE)
    print(f"\n[参考资料列表项] {len(res['items'])} 个")
    for it in res['items'][:10]:
        print(f"  has_a={it['has_a']} a_href={it['a_href']}")
        print(f"    text: {it['text']!r}")
        print(f"    cls: {it['cls']}")
        print(f"    html: {it['html'][:300]}")
    print(f"\n[全页外部 a[href]] {len(res['hrefs'])} 个")
    for h in res['hrefs'][:20]:
        print(f"  vis={h['visible']} {h['text']!r} -> {h['href']}")
    print(f"\n[data-url/href/link 元素] {len(res['data_attrs'])} 个")
    for d in res['data_attrs'][:20]:
        print(f"  <{d['tag']}> url={d['url']} text={d['text']!r}")

    # 试试点开"共参考N篇资料"看是否展开带链接
    print("\n=== 点击展开参考资料 ===")
    try:
        loc = page.get_by_text('共参考', exact=False).first
        if await loc.is_visible(timeout=3000):
            await loc.click(timeout=3000)
            await asyncio.sleep(1.5)
            res2 = await page.evaluate(REF_LIST_PROBE)
            print(f"[展开后] 外部 a[href] {len(res2['hrefs'])} 个, 列表项 {len(res2['items'])} 个")
            for it in res2['items'][:6]:
                print(f"  has_a={it['has_a']} a_href={it['a_href']} text={it['text']!r}")
            for h in res2['hrefs'][:15]:
                print(f"  {h['href']}")
    except Exception as e:
        print(f"  展开异常: {e}")

    await c.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(main())
