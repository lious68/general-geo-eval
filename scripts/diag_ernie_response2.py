"""诊断文心一言 (chat.baidu.com) 回答区 DOM v2。

v1 的问题：候选选择器窄 + 打印前 15 个就被侧边栏 history-item 占满，
真正的答案容器在更后面的 index 被 break 截断，没 dump 出来。

v2 策略：
  - 排除侧边栏（class 含 aside/sidebar/history 的祖先）
  - 收集主区所有可见且 innerText≥30 的元素，按文本长度倒序
  - 打印 tag/class + 父链(4 层) + 文本前 120
  - 另 dump 主对话容器候选（class 含 main/body/conversation/dialog/turn/bubble）
  - 检查停止/重新生成按钮（判断是否仍在生成）

用法（Win RDP，前台管理员 PowerShell）：
    cd C:\\general-geo-eval
    python scripts\\diag_ernie_response2.py
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

QUESTION = "UCloud海外云主机怎么样？"


async def main():
    c = create_web_chat_client("ernie")
    if not c.is_configured:
        print("❌ 无 ernie 登录态"); return
    if not await c.initialize():
        print("❌ 浏览器启动失败"); return
    page = c._page
    await c._goto_site(page)
    await asyncio.sleep(6)

    print(f"发送问题: {QUESTION}")
    ta = page.locator("#chat-textarea")
    await ta.wait_for(state="visible", timeout=10000)
    await ta.click()
    await asyncio.sleep(0.3)
    await page.keyboard.type(QUESTION, delay=20)
    await asyncio.sleep(0.5)
    await page.keyboard.press("Enter")
    print("已按 Enter 发送，等 30 秒让回答完成...")
    await asyncio.sleep(30)

    # 1. 主区可见元素（排除侧边栏，按文本长度倒序）
    print("\n=== 主区可见元素（排除 aside/sidebar/history，按文本长度倒序 top30）===")
    info = await page.evaluate(r"""() => {
        const out = [];
        const inAside = (el) => {
            let p = el;
            while (p) {
                const cls = (p.className || '').toString();
                if (/(aside|sidebar|history)/i.test(cls)) return true;
                p = p.parentElement;
            }
            return false;
        };
        for (const el of document.querySelectorAll('*')) {
            if (inAside(el)) continue;
            const text = (el.innerText || '').trim();
            if (text.length < 30) continue;
            const chain = [];
            let p = el.parentElement, depth = 0;
            while (p && depth < 4) {
                chain.push((p.className || '').toString().slice(0, 45));
                p = p.parentElement; depth++;
            }
            out.push({
                tag: el.tagName,
                cls: (el.className || '').toString().slice(0, 90),
                textLen: text.length,
                text: text.slice(0, 120),
                chain: chain
            });
        }
        out.sort((a, b) => b.textLen - a.textLen);
        return out.slice(0, 30);
    }""")
    print(f"命中数: {len(info)}")
    for i, x in enumerate(info):
        print(f"\n[{i}] tag={x['tag']} textLen={x['textLen']} class={x['cls']}")
        print(f"    父链: {' > '.join(x['chain'])}")
        print(f"    text前120: {x['text']}")

    # 2. 主对话容器候选
    print("\n=== 主对话容器候选（class 含 main/body/conversation/dialog/turn/bubble/list）===")
    conts = await page.evaluate(r"""() => {
        const out = [];
        const inAside = (el) => {
            let p = el;
            while (p) {
                const cls = (p.className || '').toString();
                if (/(aside|sidebar)/i.test(cls)) return true;
                p = p.parentElement;
            }
            return false;
        };
        for (const el of document.querySelectorAll('*')) {
            if (inAside(el)) continue;
            const cls = (el.className || '').toString();
            if (/(chat-main|chat-body|chat-content|conversation|dialog|turn|bubble|chat-item|message-list|msg-list|chat-list|answer|reply)/i.test(cls)) {
                out.push({tag: el.tagName, cls: cls.slice(0, 110), childCount: el.children.length, text: (el.innerText||'').slice(0, 90)});
            }
        }
        return out.slice(0, 25);
    }""")
    for x in conts:
        print(f"  tag={x['tag']} children={x['childCount']} class={x['cls']}")
        print(f"    text前90: {x['text']}")

    # 3. 生成状态按钮
    print("\n=== 生成状态按钮（停止/重新生成）===")
    btns = await page.evaluate(r"""() => {
        const out = [];
        for (const b of document.querySelectorAll('button, [role=button]')) {
            const t = (b.innerText || '').trim();
            const al = b.getAttribute('aria-label') || '';
            const ti = b.getAttribute('title') || '';
            if (/停止|生成中|重新生成|regenerate|stop|暂停|继续/i.test(t + al + ti)) {
                out.push({text: t.slice(0,20), aria: al.slice(0,20), title: ti.slice(0,20), cls: (b.className||'').toString().slice(0,60)});
            }
        }
        return out;
    }""")
    for b in btns:
        print(f"  text={b['text']} aria={b['aria']} title={b['title']} class={b['cls']}")
    if not btns:
        print("  （无停止/重新生成按钮，可能已生成完成）")

    # 4. 全页最长文本（含侧边栏，对照判断答案是否真的出现）
    print("\n=== 全页最长文本 top5（含侧边栏，对照）===")
    top = await page.evaluate(r"""() => {
        const out = [];
        for (const el of document.querySelectorAll('*')) {
            const text = (el.innerText || '').trim();
            if (text.length < 30) continue;
            out.push({len: text.length, cls: (el.className||'').toString().slice(0,60), text: text.slice(0,80)});
        }
        out.sort((a,b)=>b.len-a.len);
        return out.slice(0,5);
    }""")
    for x in top:
        print(f"  len={x['len']} class={x['cls']} text前80: {x['text']}")

    await c.close()
    print("\n=== 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
