"""豆包 v_list 内部深挖 + 搜索题正文定位 — 第二轮证据

第一轮(doubao_bubble_dom.json)发现:
  1. RESPONSE_SELECTOR 6 个子选择器全 count=0 → _extract_response 主路径必死,
     全靠 TreeWalker fallback 抓整个 message-list(混抓 user+assistant+首页流)。
  2. message-list 直接子级只有 1-2 个大 div(v_list-D34x3M = 整轮对话容器)。
  3. q002 直答侥幸抓对4670字; q003 搜索题只抓到9字"找到 18 篇资料" →
     搜索题 assistant 正文没抓到,需定位它在哪个 DOM 节点、为何 TreeWalker 漏掉。

本轮:递归 dump v_list-D34x3M 内部子树(找 user vs assistant 区分性子节点),
q003 等更久 + dump 完成态全结构, 看 assistant 正文到底在哪、是否需要滚动/展开。
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

Q_SEARCH = "UCloud海外有哪些节点？"

# 递归 dump v_list 内部子树: 列出每个有实质文本(>=8字)的元素及其 class/role/层级
DEEP_TREE_JS = """
() => {
  const ml = document.querySelector('[class*="message-list"]');
  if (!ml) return { found: false };
  const out = [];
  const visit = (el, depth, pathIdx) => {
    if (depth > 6) return;
    const cls = (typeof el.className === 'string') ? el.className : '';
    const role = el.getAttribute('role') || '';
    const ownText = Array.from(el.childNodes).filter(n => n.nodeType === 3)
                       .map(n => n.textContent.trim()).join('');
    const innerLen = (el.innerText || '').length;
    // 只记录有实质文本或含搜索元数据的节点
    const hasMeta = /搜索\\s*\\d+\\s*个?关键词|参考(?:了)?\\s*\\d+\\s*篇|找到\\s*\\d+\\s*篇/.test(el.textContent || '');
    if (innerLen >= 8 || hasMeta || depth <= 2) {
      out.push({
        depth, path: pathIdx,
        tag: el.tagName.toLowerCase(),
        cls: cls.slice(0, 100),
        role,
        own_text: ownText.slice(0, 50),
        inner_len: innerLen,
        has_meta: hasMeta,
        link_count: el.querySelectorAll(':scope > a[href], :scope > * > a[href]').length,
        child_count: el.children.length,
      });
    }
    for (let i = 0; i < el.children.length && i < 12; i++) {
      visit(el.children[i], depth + 1, pathIdx + '.' + i);
    }
  };
  for (let i = 0; i < ml.children.length; i++) {
    visit(ml.children[i], 0, String(i));
  }
  return { found: true, nodes: out };
}
"""

# 全页所有有实质文本的顶层块(不限 message-list), 看 assistant 正文是否在 list 外
TOP_BLOCKS_JS = """
() => {
  const out = [];
  // 扫 body 下前几层 div, 找 innerText 最大的几个
  const all = document.querySelectorAll('div, section, article, main');
  const scored = [];
  for (const el of all) {
    const innerLen = (el.innerText || '').length;
    if (innerLen >= 50) {
      const cls = (typeof el.className === 'string') ? el.className : '';
      scored.push({ tag: el.tagName.toLowerCase(), cls: cls.slice(0, 80),
                    inner_len: innerLen,
                    text_head: (el.innerText || '').trim().slice(0, 60),
                    in_message_list: !!el.closest('[class*="message-list"]') });
    }
  }
  scored.sort((a, b) => b.inner_len - a.inner_len);
  return scored.slice(0, 15);
}
"""


async def main():
    os.environ["DISPLAY"] = ":0"
    os.makedirs("output", exist_ok=True)

    print("启动豆包客户端（沿用登录态）...")
    client = create_web_chat_client("doubao")
    if not await client.initialize():
        print("浏览器启动失败"); return
    page = client._page

    # 发搜索题(最容易复现9字问题), 但 wait 后不急着 extract, 先等久一点
    print(f"\n发搜索题(手动控制等待): {Q_SEARCH}")
    await client._start_new_chat(page)
    await client._type_question(page, Q_SEARCH)
    await client._send_question(page)

    # 阶段A: wait_for_response 判稳定时立刻 dump
    print("[A] 调 _wait_for_response ...")
    await client._wait_for_response(page, timeout=120)
    body_early = await client._extract_response(page)
    print(f"[A] wait 完即 extract: {len(body_early)}字 head={body_early[:60]!r}")
    snap_early = {
        "tag": "early_after_wait",
        "url": page.url,
        "extracted_len": len(body_early),
        "extracted_head": body_early[:200],
        "deep_tree": await page.evaluate(DEEP_TREE_JS),
        "top_blocks": await page.evaluate(TOP_BLOCKS_JS),
    }
    await page.screenshot(path="output/doubao_bubble2_early.png", full_page=True)

    # 阶段B: 再多等 25 秒(让搜索题正文充分渲染), 重新 dump
    print("[B] 额外等 25 秒后重采 ...")
    await asyncio.sleep(25)
    body_late = await client._extract_response(page)
    print(f"[B] 加等后 extract: {len(body_late)}字 head={body_late[:60]!r}")
    snap_late = {
        "tag": "late_after_extra_wait",
        "url": page.url,
        "extracted_len": len(body_late),
        "extracted_head": body_late[:200],
        "deep_tree": await page.evaluate(DEEP_TREE_JS),
        "top_blocks": await page.evaluate(TOP_BLOCKS_JS),
    }
    await page.screenshot(path="output/doubao_bubble2_late.png", full_page=True)

    result = {"question": Q_SEARCH, "stages": {"early": snap_early, "late": snap_late}}
    with open("output/doubao_bubble2_dom.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\n证据: output/doubao_bubble2_dom.json + 2 张截图")

    # 速览
    for tag, s in (("early", snap_early), ("late", snap_late)):
        print(f"\n=== {tag} extract={s['extracted_len']}字 ===")
        dt = s.get("deep_tree", {})
        print(f"  deep_tree found={dt.get('found')} nodes={len(dt.get('nodes', []))}")
        for n in dt.get("nodes", [])[:18]:
            print(f"    d{n['depth']} {n['path']:6} <{n['tag']}> cls={n['cls'][:40]!r} "
                  f"role={n['role']!r} len={n['inner_len']:5} meta={n['has_meta']} "
                  f"own={n['own_text'][:25]!r}")
        print(f"  top_blocks(前5):")
        for b in s.get("top_blocks", [])[:5]:
            print(f"    <{b['tag']}> cls={b['cls'][:35]!r} len={b['inner_len']:5} "
                  f"in_ml={b['in_message_list']} head={b['text_head'][:30]!r}")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(main())
