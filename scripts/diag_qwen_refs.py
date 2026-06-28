"""千问引用源 DOM 证据采集 v2 — 彻底定位引用源在哪 / 是否需开搜索模式

v1 发现：常规提问后千问 DOM 里 0 个外部 <a href>、0 个"参考X篇"文本，
回答含"截至2026年6月"幻觉时间 → 怀疑根本没联网搜索。
v2 针对：
  - 采集页面上所有"搜索/研究/深度/联网"开关按钮，记录其状态并尝试点开
  - 发送前确保搜索模式打开
  - 响应后 dump 回答容器 outerHTML（找 [1][2] 上标结构）
  - 专门找 qwen 的"来源/参考资料/搜索"面板（可能在回答下方独立组件）
  - 滚动到底 + 等 12s 异步加载后重采 <a href>
  - 探测回答正文里所有 sup / 上标 / [n] 标记及其 onclick/aria 属性
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client

QUESTION = "UCloud海外有哪些节点？"

# 1) 页面上所有疑似"搜索/研究/深度/联网"开关
MODE_TOGGLES_PROBE = """
() => {
  const out = [];
  const KW = ['搜索','联网','研究','深度','deep','search','research','think','思考','联网搜索','深度搜索'];
  const cand = document.querySelectorAll('button, [role="switch"], [role="button"], [class*="mode"], [class*="search"], [class*="research"], label, div[tabindex]');
  for (const el of cand) {
    const t = (el.textContent || '').trim();
    const aria = el.getAttribute('aria-label') || '';
    const cls = (typeof el.className === 'string') ? el.className : '';
    if (t.length > 0 && t.length < 20 && KW.some(k => t.includes(k) || aria.toLowerCase().includes(k.toLowerCase()))) {
      out.push({
        tag: el.tagName.toLowerCase(),
        text: t, aria, cls: cls.slice(0,80),
        checked: el.getAttribute('aria-checked') || el.getAttribute('aria-selected') || '',
        visible: !!(el.offsetWidth || el.offsetHeight),
        rect: (() => { const r = el.getBoundingClientRect(); return {x:Math.round(r.x), y:Math.round(r.y)}; })(),
      });
    }
  }
  return out;
}
"""

# 2) 回答容器 outerHTML（找 [n] 上标 / 引用结构）
ANSWER_HTML_PROBE = """
() => {
  // qwen 回答气泡常见容器
  const sels = [
    '[class*="message-content"]','[class*="markdown"]','[class*="assistant"]',
    '[class*="response"]','[class*="answer"]','[role="article"]',
    '[class*="bubble"]','[class*="content"][class*="item"]'
  ];
  for (const sel of sels) {
    const els = document.querySelectorAll(sel);
    if (els.length) {
      const last = els[els.length-1];
      return { sel, html: last.outerHTML.slice(0, 3000), text: (last.innerText||'').slice(0,200) };
    }
  }
  return null;
}
"""

# 3) 全页找 [n] 上标 / footnote / cite 标记
CITATION_MARK_PROBE = """
() => {
  const out = { sups: [], bracket_els: [], ref_panels: [] };
  // 上标
  document.querySelectorAll('sup, [class*="footnote"], [class*="cite"], [class*="ref-num"], [class*="citation"]').forEach((el,i) => {
    if (i>=15) return;
    out.sups.push({
      tag: el.tagName.toLowerCase(),
      cls: (typeof el.className==='string')?el.className.slice(0,80):'',
      text: (el.textContent||'').trim().slice(0,20),
      html: el.outerHTML.slice(0,200),
      visible: !!(el.offsetWidth||el.offsetHeight),
    });
  });
  // 含"来源/参考/搜索"的容器（可能在回答下方）
  const KW = ['来源','参考','搜索','资料','引用','source','reference'];
  document.querySelectorAll('div, section, [class*="source"], [class*="reference"], [class*="search-result"]').forEach((el,i) => {
    if (i>400) return;
    const t = (el.textContent||'').trim();
    if (t.length>0 && t.length<80 && KW.some(k=>t.includes(k))) {
      const a = el.querySelectorAll('a[href]').length;
      if (a>0 || t.includes('篇') || t.includes('来源') || t.includes('参考')) {
        out.ref_panels.push({
          tag: el.tagName.toLowerCase(),
          cls: (typeof el.className==='string')?el.className.slice(0,100):'',
          text: t.slice(0,80),
          a_count: a,
          html: el.outerHTML.slice(0, 500),
        });
      }
    }
  });
  return out;
}
"""

ALL_LINKS_PROBE = """
() => {
  const out = [];
  const all = document.querySelectorAll('a[href]');
  for (const a of all) {
    out.push({ href: a.href, text: (a.textContent||'').trim().slice(0,60),
      visible: !!(a.offsetWidth||a.offsetHeight) });
  }
  return out;
}
"""


async def _dismiss_overlays(page):
    for sel in ["[role='dialog'] [class*='close']","div[class*='mask'], div[class*='overlay']"]:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1200):
                await loc.click(timeout=1500); await asyncio.sleep(0.3)
        except Exception: pass
    try: await page.keyboard.press("Escape"); await asyncio.sleep(0.3)
    except Exception: pass


async def probe_modes(page):
    """采集并尝试点开搜索/研究模式开关。"""
    modes = await page.evaluate(MODE_TOGGLES_PROBE)
    print(f"\n[模式开关候选] {len(modes)} 个:")
    for m in modes:
        print(f"  <{m['tag']}> text={m['text']!r} aria={m['aria']!r} checked={m['checked']} vis={m['visible']} cls={m['cls'][:40]}")
    # 尝试点开含"搜索/联网/深度"且未选中的
    clicked = []
    for m in modes:
        if not m['visible']: continue
        t = m['text']
        if any(k in t for k in ['联网','深度','搜索']) and m['checked'] != 'true':
            try:
                loc = page.get_by_text(t, exact=False).first
                if await loc.is_visible(timeout=1500):
                    await loc.click(timeout=2000)
                    clicked.append(t)
                    await asyncio.sleep(0.8)
            except Exception: pass
    if clicked:
        print(f"  已尝试点开: {clicked}")
    return modes


async def debug():
    os.environ["DISPLAY"] = ":0"
    os.makedirs("output", exist_ok=True)
    result = {"question": QUESTION, "stages": {}}

    print("启动千问客户端...")
    client = create_web_chat_client("qwen")
    ok = await client.initialize()
    if not ok:
        print("启动失败"); return
    await client._navigate_to_chat(client._page)
    page = client._page
    await _dismiss_overlays(page)

    # 发送前探测模式开关
    print("=== 发送前 ===")
    modes_before = await probe_modes(page)
    result["stages"]["modes_before"] = modes_before

    print(f"\n发送问题: {QUESTION}")
    await client._type_question(page, QUESTION)
    # 发送前再探测一次（输入框聚焦后可能弹出搜索开关）
    modes_pre_send = await probe_modes(page)
    result["stages"]["modes_pre_send"] = modes_pre_send
    await client._send_question(page)
    print("等待响应...")
    await client._wait_for_response(page, timeout=180)

    # 立即采集
    await page.screenshot(path="output/qwen_refs_debug.png", full_page=True)
    answer = await page.evaluate(ANSWER_HTML_PROBE)
    result["stages"]["answer_html"] = answer
    print(f"\n[回答容器] sel={answer.get('sel') if answer else None}")
    if answer:
        print(f"  text head: {answer.get('text','')!r}")
        print(f"  html head 600: {answer.get('html','')[:600]}")

    cites = await page.evaluate(CITATION_MARK_PROBE)
    result["stages"]["citation_marks_immediate"] = cites
    print(f"\n[立即] sups={len(cites['sups'])} ref_panels={len(cites['ref_panels'])}")
    for s in cites['sups'][:8]:
        print(f"  sup: {s['tag']}.{s['cls'][:40]} text={s['text']!r} html={s['html'][:120]}")
    for p in cites['ref_panels'][:6]:
        print(f"  panel: {p['tag']}.{p['cls'][:40]} a_count={p['a_count']} text={p['text']!r}")

    links0 = await page.evaluate(ALL_LINKS_PROBE)
    ext0 = [l for l in links0 if l['href'].startswith('http') and 'qianwen.com' not in l['href']]
    print(f"[立即] <a href>={len(links0)} 外部={len(ext0)}")

    # 滚动到底，等异步加载
    print("\n=== 滚动到底 + 等 12s ===")
    try:
        await page.mouse.wheel(0, 4000); await asyncio.sleep(1)
        await page.mouse.wheel(0, 4000); await asyncio.sleep(1)
    except Exception: pass
    await asyncio.sleep(12)

    cites2 = await page.evaluate(CITATION_MARK_PROBE)
    result["stages"]["citation_marks_after_wait"] = cites2
    links2 = await page.evaluate(ALL_LINKS_PROBE)
    ext2 = [l for l in links2 if l['href'].startswith('http') and 'qianwen.com' not in l['href']]
    print(f"[等后] sups={len(cites2['sups'])} ref_panels={len(cites2['ref_panels'])} <a href>={len(links2)} 外部={len(ext2)}")
    for p in cites2['ref_panels'][:8]:
        print(f"  panel: {p['tag']}.{p['cls'][:50]} a_count={p['a_count']} text={p['text']!r}")
        print(f"    html: {p['html'][:300]}")
    for l in ext2[:20]:
        print(f"  ext: {l['text'][:30]} -> {l['href']}")

    await page.screenshot(path="output/qwen_refs_debug2.png", full_page=True)

    # 跑现有 extractor
    try:
        resp = await client._extract_response(page)
        with open("output/qwen_extracted_response.txt","w",encoding="utf-8") as f: f.write(resp)
        print(f"\n[extractor] {len(resp)} 字, 含引用来源: {'引用来源' in resp}")
    except Exception as e:
        print(f"  extractor 异常: {e}")

    # ★ 关键：从 img src 的 zimgs 代理 key 参数 base64 解码出真实来源 URL
    # 先尝试点开"X篇来源"折叠面板，展开后采全部来源项
    try:
        exp = page.get_by_text('篇来源', exact=False).first
        if await exp.is_visible(timeout=2000):
            await exp.click(timeout=2500)
            await asyncio.sleep(1.5)
            print("[已点击展开'X篇来源']")
    except Exception as e:
        print(f"  展开异常(可忽略): {e}")

    refs = await page.evaluate("""
() => {
  const out = [];
  // 全局找所有带 key= 的代理 img（每条来源一个 favicon）
  const imgs = document.querySelectorAll('img[src*="ims"], img[src*="zimgs"], img[src*="key="]');
  imgs.forEach(img => {
    const m = img.src.match(/key=([A-Za-z0-9+/=_-]+)/);
    if (!m) return;
    // 向上找最近的来源卡片，取其可见标题文本
    let card = img.closest('[class*="reference-wrap"], [class*="link-title"], [class*="search-content"], [class*="source-item"], li, [class*="item"]');
    let title = '';
    if (card) {
      // 取卡片里非图标文本
      title = (card.textContent || '').trim().replace(/\\s+/g,' ').slice(0, 120);
    }
    out.push({ img_src: img.src.slice(0,80), key: m[1], title });
  });
  const seen = new Set(); const uniq = [];
  for (const r of out) { if (!seen.has(r.key)) { seen.add(r.key); uniq.push(r); } }
  return uniq;
}
""")
    result["stages"]["decoded_refs"] = refs
    print(f"\n★ 解码出来源 {len(refs)} 条:")
    import base64
    for r in refs:
        try:
            k = r['key']; k += '=' * (-len(k) % 4)
            url = base64.b64decode(k).decode('utf-8', errors='replace')
        except Exception as e:
            url = f'(decode err: {e})'
        print(f"  {url}")
        print(f"    title: {r['title']!r}")

    with open("output/qwen_search_dom.json","w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\nDOM 证据: output/qwen_search_dom.json")
    await client.close()
    print("完成。")


if __name__ == "__main__":
    asyncio.run(debug())
