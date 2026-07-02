"""豆包 user/assistant 气泡 DOM 证据采集 — 定位区分性 class/role

为什么有这轮：GEO评估0630 豆包 21/40 坏题（12 空回声抓到 user 题干回显 +
7 串题抓到上一题残留 assistant 气泡 + 2 首页噪声）。根因是 _extract_response
的 RESPONSE_SELECTOR.last / TreeWalker 不区分 user/assistant 气泡。
本脚本广谱 dump message-list 每行结构 + 各子选择器命中数，找出 user vs
assistant 的区分性 class/role/data-*，据此重写 extractor 锚定本次 assistant 气泡。

用法:
    python scripts/diag_doubao_bubble.py

复用 create_web_chat_client("doubao") + 已存 storage_state。
跑两题：直答题 q002 + 搜索题 q003，每题 wait_for_response 后、extract 前 dump。
产物落 output/doubao_bubble_dom.json + 截图。
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

Q_DIRECT = "优刻得轻量云主机怎么样？"        # 直答题，0630 空回声代表(q002)
Q_SEARCH = "UCloud海外有哪些节点？"          # 搜索题，0630 首页噪声代表(q003)

# RESPONSE_SELECTOR 各子选择器（web_chat_clients.py:1313）
SUB_SELECTORS = [
    "[class*='message-content']",
    "[class*='markdown']",
    "[class*='response']",
    "[class*='assistant']",
    "[role='article']",
    "[class*='chat-message']",
]

HOMEPAGE_MARKERS = ["新对话", "有什么我能帮你的吗", "资讯：", "AI 生成可能有误", "请核实"]


# dump message-list 每一行结构，标注 user/assistant 启发
DUMP_ROWS_JS = """
() => {
  const ml = document.querySelector('[class*="message-list"]');
  if (!ml) return { found: false, rows: [] };
  const rows = ml.children;
  const out = [];
  for (let i = 0; i < rows.length; i++) {
    const el = rows[i];
    const cls = (typeof el.className === 'string') ? el.className : '';
    const role = el.getAttribute('role') || '';
    // data-* 属性收集
    const dataAttrs = {};
    for (const a of el.attributes) {
      if (a.name.startsWith('data-')) dataAttrs[a.name] = a.value.slice(0, 60);
    }
    const txt = (el.textContent || '').trim();
    // 是否含搜索元数据
    const hasSearchMeta = /搜索\\s*\\d+\\s*个?关键词/.test(txt) || /参考(?:了)?\\s*\\d+\\s*篇/.test(txt);
    // 是否含 markdown 容器
    const hasMarkdown = !!el.querySelector('[class*="markdown"], [class*="content"]');
    // a[href] 数量
    const linkCount = el.querySelectorAll('a[href]').length;
    // 启发：assistant 行通常有 markdown/长文/链接；user 行通常短、是问题原文、无 markdown
    const innerLen = (el.innerText || '').length;
    out.push({
      idx: i,
      tag: el.tagName.toLowerCase(),
      cls: cls.slice(0, 140),
      role,
      dataAttrs,
      text_head: txt.slice(0, 80),
      inner_text_len: innerLen,
      has_markdown: hasMarkdown,
      has_search_meta: hasSearchMeta,
      link_count: linkCount,
      child_count: el.children.length,
    });
  }
  return { found: true, row_count: rows.length, rows: out };
}
"""

# 各子选择器命中数 + .last 文本头
PROBE_SUBSELECTORS_JS = """
(subSelectors) => {
  const out = [];
  for (const sel of subSelectors) {
    let els;
    try { els = Array.from(document.querySelectorAll(sel)); } catch(e) { els = []; }
    const last = els[els.length - 1];
    out.push({
      selector: sel,
      match_count: els.length,
      last_text_head: last ? (last.textContent || '').trim().slice(0, 60) : null,
      last_cls: last ? ((typeof last.className === 'string') ? last.className.slice(0, 80) : '') : null,
    });
  }
  return out;
}
"""

# 全页 <a href> 清单 + 容器链（复用 diag_doubao_refs 的 ALL_LINKS_PROBE 精简版）
ALL_LINKS_JS = """
() => {
  const out = [];
  const all = document.querySelectorAll('a[href]');
  for (const a of all) {
    const chain = [];
    let el = a;
    let guard = 0;
    while (el && el !== document.body && guard < 8) {
      const tag = el.tagName.toLowerCase();
      const cls = (el.className && typeof el.className === 'string') ? el.className.split(/\\s+/).filter(Boolean).slice(0,2).join('.') : '';
      chain.unshift(tag + (cls ? '.' + cls : ''));
      el = el.parentElement;
      guard++;
    }
    out.push({
      href: a.href,
      text: (a.textContent || '').trim().slice(0, 60),
      container: chain.join(' > '),
      visible: !!(a.offsetWidth || a.offsetHeight || a.getClientRects().length),
    });
  }
  return out.slice(0, 40);
}
"""


async def dump_all(page, tag):
    """采一次完整快照：message-list 行 + 子选择器命中 + 链接 + URL/state"""
    snap = {"tag": tag, "url": page.url}
    try:
        snap["message_rows"] = await page.evaluate(DUMP_ROWS_JS)
    except Exception as e:
        snap["message_rows_err"] = str(e)
    try:
        snap["sub_selectors"] = await page.evaluate(PROBE_SUBSELECTORS_JS, SUB_SELECTORS)
    except Exception as e:
        snap["sub_selectors_err"] = str(e)
    try:
        snap["all_links"] = await page.evaluate(ALL_LINKS_JS)
    except Exception as e:
        snap["all_links_err"] = str(e)
    return snap


async def main():
    os.environ["DISPLAY"] = ":0"
    os.makedirs("output", exist_ok=True)

    print("启动豆包客户端（沿用登录态）...")
    client = create_web_chat_client("doubao")
    if not await client.initialize():
        print("浏览器启动失败"); return
    page = client._page
    result = {"stages": {}}

    # ── 题1：直答题 q002 ──
    print(f"\n发直答题: {Q_DIRECT}")
    r1 = await client.chat(Q_DIRECT)
    body1 = r1.get("content", "")
    print(f"[直答完成] 正文{len(body1)}字 err={r1.get('error')}")
    print(f"  head: {body1[:80]!r}")
    snap1 = await dump_all(page, "after_direct")
    snap1["extracted_body_head"] = body1[:300]
    snap1["extracted_body_len"] = len(body1)
    snap1["is_empty_echo"] = body1.strip() == Q_DIRECT.strip() or body1.strip().startswith(Q_DIRECT.strip())
    result["stages"]["direct_q002"] = snap1
    await page.screenshot(path="output/doubao_bubble_direct.png", full_page=True)

    # ── 题2：搜索题 q003（chat() 会先 _start_new_chat 硬重载）──
    print(f"\n发搜索题: {Q_SEARCH}")
    r2 = await client.chat(Q_SEARCH)
    body2 = r2.get("content", "")
    print(f"[搜索题完成] 正文{len(body2)}字 err={r2.get('error')}")
    print(f"  head: {body2[:80]!r}")
    snap2 = await dump_all(page, "after_search")
    snap2["extracted_body_head"] = body2[:300]
    snap2["extracted_body_len"] = len(body2)
    snap2["has_homepage_noise"] = any(m in body2[:200] for m in HOMEPAGE_MARKERS)
    result["stages"]["search_q003"] = snap2
    await page.screenshot(path="output/doubao_bubble_search.png", full_page=True)

    with open("output/doubao_bubble_dom.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\n证据: output/doubao_bubble_dom.json + 2 张截图")

    # 控制台速览 message-list 行
    for stage in ("direct_q002", "search_q003"):
        s = result["stages"][stage]
        mr = s.get("message_rows", {})
        print(f"\n=== {stage} message-list (found={mr.get('found')}, rows={mr.get('row_count')}) ===")
        for r in mr.get("rows", []):
            print(f"  [{r['idx']}] <{r['tag']}> cls={r['cls'][:50]!r} role={r['role']!r} "
                  f"md={r['has_markdown']} search={r['has_search_meta']} links={r['link_count']} "
                  f"len={r['inner_text_len']} txt={r['text_head'][:40]!r}")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(main())
