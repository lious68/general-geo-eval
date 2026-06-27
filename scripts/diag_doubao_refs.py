"""豆包引用源 DOM 证据采集 — 定位"参考资料/来源"折叠面板的真实结构与抓取路径

用法:
    python scripts/diag_doubao_refs.py

复用 create_web_chat_client("doubao") + 已存 storage_state（data/webchat_auth/doubao_state.json）。
对 q003「UCloud海外有哪些节点？」跑一次（触发联网搜索），在响应稳定后采集：

  1. full_page 截图 → output/doubao_refs_debug.png
  2. 全文 → output/doubao_full_text.txt
  3. 全 DOM <a href> 清单 + 每个链接从自身到 body 的 class/id 容器链
  4. 含"参考/资料/来源/引用"的文本节点 → 最近祖先元素 outerHTML(前800字)
  5. iframe 列表 + 疑似容器 shadowRoot 探测
  6. 交互试探：点击"参考N篇资料/参考资料/来源/展开"按钮 + 角标[1]，
     点击前后各采一次 <a href>，看 URL 是否点击后才出现

产物落 output/doubao_search_dom.json + output/doubao_extracted_response.txt，
据此决定 DoubaoWebChatClient._extract_response() 的精确抓取选择器。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client

QUESTION = "UCloud海外有哪些节点？"

# 容器路径：从 <a> 向上取 class/id，直到 body，拼成紧凑字符串便于人工看归属
ANCESTOR_PROBE = """
(anchorSel) => {
  const a = document.querySelector(anchorSel);
  if (!a) return null;
  const chain = [];
  let el = a;
  while (el && el !== document.body) {
    const tag = el.tagName.toLowerCase();
    const cls = (el.className && typeof el.className === 'string') ? el.className.split(/\\s+/).filter(Boolean).slice(0,3).join('.') : '';
    const id = el.id ? '#' + el.id : '';
    chain.unshift(tag + (cls ? '.' + cls : '') + id);
    el = el.parentElement;
  }
  return chain.join(' > ');
}
"""

# 3) 全 <a href> 清单 + 容器链
ALL_LINKS_PROBE = """
() => {
  const out = [];
  const all = document.querySelectorAll('a[href]');
  for (const a of all) {
    const chain = [];
    let el = a;
    while (el && el !== document.body) {
      const tag = el.tagName.toLowerCase();
      const cls = (el.className && typeof el.className === 'string') ? el.className.split(/\\s+/).filter(Boolean).slice(0,3).join('.') : '';
      const id = el.id ? '#' + el.id : '';
      chain.unshift(tag + (cls ? '.' + cls : '') + id);
      el = el.parentElement;
    }
    out.push({
      href: a.href,
      text: (a.textContent || '').trim().slice(0, 80),
      container: chain.join(' > '),
      visible: !!(a.offsetWidth || a.offsetHeight || a.getClientRects().length),
    });
  }
  return out;
}
"""

# 4) 含关键词的文本节点 → 最近祖先 outerHTML
REF_TEXT_PROBE = """
() => {
  const KW = ['参考', '资料', '来源', '引用', '篇'];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => {
      const t = node.textContent || '';
      // 命中"参考X篇资料/来源/引用"这类搜索元数据
      if (KW.some(k => t.includes(k)) && t.trim().length < 40) return NodeFilter.FILTER_ACCEPT;
      return NodeFilter.FILTER_REJECT;
    }
  });
  const hits = [];
  let n;
  let i = 0;
  while ((n = walker.nextNode()) && i < 20) {
    let p = n.parentElement;
    // 向上找一个看起来像容器（含多个子/有class）的祖先
    let guard = 0;
    while (p && guard < 6) {
      if (p.className && p.children.length > 0) break;
      p = p.parentElement;
      guard++;
    }
    if (!p) continue;
    hits.push({
      text: n.textContent.trim(),
      tag: p.tagName.toLowerCase(),
      cls: (typeof p.className === 'string') ? p.className.slice(0, 120) : '',
      id: p.id || '',
      outerHTML: p.outerHTML.slice(0, 800),
    });
    i++;
  }
  return hits;
}
"""

# 5) iframe + shadow 探测
FRAME_SHADOW_PROBE = """
() => {
  const out = { iframes: [], shadowRoots: [] };
  document.querySelectorAll('iframe').forEach((f, i) => {
    out.iframes.push({ idx: i, src: f.src || '', name: f.name || '', title: f.title || '' });
  });
  // 探测疑似参考/来源容器的 shadowRoot
  const cand = document.querySelectorAll('[class*="reference"],[class*="source"],[class*="citation"],[class*="参考"],details');
  cand.forEach((el, i) => {
    if (el.shadowRoot) {
      out.shadowRoots.push({
        idx: i, tag: el.tagName.toLowerCase(),
        cls: (typeof el.className === 'string') ? el.className.slice(0, 120) : '',
        hasShadowLinks: !!el.shadowRoot.querySelector('a[href]'),
      });
    }
  });
  return out;
}
"""

# 6) 点击候选（best-effort，吞异常）
CLICK_CANDIDATES = [
    # 折叠/展开按钮类（aria-expanded=false 或含关键词文本）
    "[aria-expanded='false']",
    "details:not([open])",
    "summary",
    # 文本匹配的按钮
    "button",
]


async def _dismiss_overlays(page):
    """关掉遮罩/弹窗 dialog，避免拦截输入框点击。best-effort。"""
    for sel in [
        "[role='dialog'] [class*='close']",
        "[role='dialog'] button[aria-label*='关闭']",
        "[role='dialog'] button[aria-label*='Close']",
        "[data-slot='dialog-content'] [class*='close']",
        "div[class*='mask'], div[class*='overlay'], div[class*='backdrop']",
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1500):
                await loc.click(timeout=2000)
                await asyncio.sleep(0.4)
        except Exception:
            pass
    # 直接按 Esc 关 radix dialog（兜底，最可靠）
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.4)
    except Exception:
        pass


async def collect(page, tag):
    """采一次全 <a href> 清单，附 tag 便于点击前后对比。"""
    try:
        return await page.evaluate(ALL_LINKS_PROBE)
    except Exception as e:
        print(f"  [{tag}] 采集 links 失败: {e}")
        return []


def external_links(links):
    """挑出外部链接（非 doubao/bytedance 内部），用于判断是否有引用源。"""
    out = []
    for l in links or []:
        href = (l.get("href") or "")
        if not href.startswith("http"):
            continue
        if "doubao.com" in href and "/chat" in href:
            continue
        if "bytedance.com" in href:
            continue
        out.append(l)
    return out


async def debug():
    os.environ["DISPLAY"] = ":0"
    os.makedirs("output", exist_ok=True)

    print("启动豆包客户端（沿用已存登录态）...")
    client = create_web_chat_client("doubao")
    ok = await client.initialize()
    if not ok:
        print("浏览器启动失败（登录态可能失效，先跑 setup_webchat_auth.py）")
        return

    print("导航到聊天页面...")
    await client._navigate_to_chat(client._page)
    page = client._page

    # 关掉登录后/首屏可能弹出的遮罩 dialog（role=dialog / radix dialog），
    # 否则它 intercept pointer events，输入框点不动（30s 超时）。
    await _dismiss_overlays(page)

    print(f"发送问题: {QUESTION}")
    await client._type_question(page, QUESTION)
    await client._send_question(page)
    print("等待响应...")
    await client._wait_for_response(page, timeout=120)

    result = {"question": QUESTION, "stages": {}}

    # 1+2 截图 + 全文
    await page.screenshot(path="output/doubao_refs_debug.png", full_page=True)
    print("截图: output/doubao_refs_debug.png")
    all_text = await page.evaluate("() => document.body.innerText || ''")
    with open("output/doubao_full_text.txt", "w", encoding="utf-8") as f:
        f.write(all_text)
    print(f"全文: output/doubao_full_text.txt ({len(all_text)} 字)")

    # 3) 点击前 <a href> 清单
    links_before = await collect(page, "before")
    ext_before = external_links(links_before)
    result["stages"]["before_click"] = {
        "total_a_href": len(links_before),
        "external_count": len(ext_before),
        "external_links": ext_before,
    }
    print(f"[点击前] <a href> 共 {len(links_before)}，外部 {len(ext_before)}")
    for l in ext_before[:15]:
        print(f"    {l.get('text','')[:30]:30s} -> {l.get('href','')}")
        print(f"        容器: {l.get('container','')[:120]}")

    # 4) 参考/来源文本节点祖先
    ref_hits = await page.evaluate(REF_TEXT_PROBE)
    result["stages"]["ref_text_ancestors"] = ref_hits
    print(f"\n[参考/来源文本节点] 命中 {len(ref_hits)} 个祖先:")
    for h in ref_hits[:6]:
        print(f"    <{h.get('tag')} class=\"{h.get('cls','')[:60]}\"> text={h.get('text','')!r}")
        print(f"        outerHTML(前200): {h.get('outerHTML','')[:200]}")

    # 5) iframe / shadow
    frames_shadow = await page.evaluate(FRAME_SHADOW_PROBE)
    result["stages"]["frames_and_shadow"] = frames_shadow
    print(f"\n[iframe] {len(frames_shadow.get('iframes',[]))} 个; [shadowRoot] {len(frames_shadow.get('shadowRoots',[]))} 个疑似容器带 shadow")
    for f in frames_shadow.get("iframes", [])[:5]:
        print(f"    iframe src={f.get('src','')[:80]} title={f.get('title','')}")

    # 6) 交互试探：点候选按钮，看外部链接是否增多
    clicked = []
    for sel in CLICK_CANDIDATES:
        try:
            locs = page.locator(sel)
            cnt = await locs.count()
            if cnt == 0:
                continue
            # 最多点前 3 个，best-effort
            for i in range(min(cnt, 3)):
                try:
                    btn = locs.nth(i)
                    if await btn.is_visible(timeout=1500):
                        await btn.click(timeout=3000)
                        clicked.append({"selector": sel, "index": i, "ok": True})
                except Exception:
                    pass
        except Exception:
            pass
    await asyncio.sleep(1.5)
    links_after_expand = await collect(page, "after_expand")
    ext_after_expand = external_links(links_after_expand)
    result["stages"]["after_expand_clicks"] = {
        "clicked": clicked,
        "external_count": len(ext_after_expand),
        "external_links": ext_after_expand,
    }
    print(f"\n[点展开按钮后] 外部链接 {len(ext_after_expand)}（点击前 {len(ext_before)}）")
    for l in ext_after_expand[:15]:
        print(f"    {l.get('text','')[:30]:30s} -> {l.get('href','')}")

    # 6b) 角标 [1] 弹 popover 试探
    popover_gained = []
    try:
        sup_count = await page.locator("sup, [class*='footnote'], [class*='cite'], [class*='ref']").count()
        print(f"\n[角标候选] sup/cite/ref 元素 {sup_count} 个")
        for i in range(min(sup_count, 5)):
            try:
                el = page.locator("sup, [class*='footnote'], [class*='cite'], [class*='ref']").nth(i)
                if await el.is_visible(timeout=1000):
                    await el.click(timeout=3000)
                    await asyncio.sleep(0.8)
                    ext_now = external_links(await collect(page, f"sup{i}"))
                    if len(ext_now) > len(ext_after_expand):
                        popover_gained.append({"sup_index": i, "new_external": ext_now[len(ext_after_expand):]})
            except Exception:
                pass
    except Exception as e:
        print(f"  角标试探异常: {e}")
    result["stages"]["after_sup_clicks"] = {
        "popover_gained_links": popover_gained,
    }
    if popover_gained:
        print(f"[点角标后] 新增外部链接 {sum(len(p['new_external']) for p in popover_gained)} 个")
        for p in popover_gained[:3]:
            for l in p["new_external"][:5]:
                print(f"    {l.get('text','')[:30]:30s} -> {l.get('href','')}")

    # 落盘
    with open("output/doubao_search_dom.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nDOM 证据: output/doubao_search_dom.json")

    # 跑一次现有 extractor，看它抓到了什么
    try:
        resp = await client._extract_response(page)
        with open("output/doubao_extracted_response.txt", "w", encoding="utf-8") as f:
            f.write(resp)
        print(f"现有 extractor 结果: output/doubao_extracted_response.txt ({len(resp)} 字)")
        print(f"  含 '引用来源' 段: {'引用来源' in resp}")
    except Exception as e:
        print(f"  extractor 异常: {e}")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(debug())
