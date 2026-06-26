"""诊断文心一言 (chat.baidu.com) 回答区 DOM，用于适配响应提取选择器。

发一个问题后等待回答，dump 消息/回答区候选元素的 class/innerText/outerHTML，
据此重调 _wait_for_response / _extract_response 的选择器（旧 [class*='answerBox'] 失效）。

用法（Win RDP，前台管理员 PowerShell）：
    cd C:\\general-geo-eval
    python scripts\\diag_ernie_response.py
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

# 回答/消息区候选选择器
ANSWER_CANDIDATES = (
    "[class*='message' i], [class*='msg' i], [class*='answer' i], "
    "[class*='bubble' i], [class*='markdown' i], [class*='agent' i], "
    "[class*='reply' i], [class*='response' i], [class*='content' i], "
    "[class*='chat-item' i], [class*='receive' i], [class*='assistant' i]"
)


async def main():
    c = create_web_chat_client("ernie")
    if not c.is_configured:
        print("❌ 无 ernie 登录态"); return
    if not await c.initialize():
        print("❌ 浏览器启动失败"); return
    page = c._page
    await c._goto_site(page)
    await asyncio.sleep(6)

    # 发送问题
    print(f"发送问题: {QUESTION}")
    ta = page.locator("#chat-textarea")
    await ta.wait_for(state="visible", timeout=10000)
    await ta.click()
    await asyncio.sleep(0.3)
    await page.keyboard.type(QUESTION, delay=20)
    await asyncio.sleep(0.5)
    await page.keyboard.press("Enter")
    print("已按 Enter 发送，等 25 秒让回答完成...")
    await asyncio.sleep(25)

    print("\n=== 回答区候选元素 ===")
    try:
        els = await page.locator(ANSWER_CANDIDATES).all()
    except Exception as e:
        els = []
        print("定位异常:", e)
    print(f"候选数: {len(els)}")
    # 只打印 innerText 较长的（疑似答案正文）+ 可见
    printed = 0
    for i, el in enumerate(els):
        try:
            vis = await el.is_visible()
            if not vis:
                continue
            text = (await el.inner_text() or "").strip()
            if len(text) < 15:
                continue
            cls = (await el.get_attribute("class") or "").strip()
            tag = await el.evaluate("e=>e.tagName")
            outer = await el.evaluate("e=>e.outerHTML.slice(0,400)")
            print(f"\n[{i}] vis={vis} tag={tag} textLen={len(text)}")
            print(f"    class={cls[:100]}")
            print(f"    text前120: {text[:120]}")
            print(f"    html前400: {outer}")
            printed += 1
            if printed >= 15:
                break
        except Exception as e:
            print(f"[{i}] 异常: {e}")
    if printed == 0:
        print("  ⚠️ 没找到含较长文本的可见回答候选，dump 全部可见候选(前20)的 class：")
        cnt = 0
        for i, el in enumerate(els):
            try:
                if not await el.is_visible():
                    continue
                cls = (await el.get_attribute("class") or "").strip()
                tag = await el.evaluate("e=>e.tagName")
                print(f"  [{i}] tag={tag} class={cls[:80]}")
                cnt += 1
                if cnt >= 20:
                    break
            except Exception:
                pass

    # 进度标记检测：看页面里"思考中/搜索中/生成中"在哪个元素
    print("\n=== 进度标记所在元素（思考中/搜索中/生成中）===")
    try:
        info = await page.evaluate("""() => {
            const markers = ['思考中','搜索中','生成中','正在思考','正在搜索','正在生成','思考完成','准备输出结果'];
            const out = [];
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const t = (el.innerText || '').slice(0, 50);
                for (const m of markers) {
                    if (t.includes(m) && el.children.length < 3) {
                        out.push({marker: m, tag: el.tagName, cls: (el.className||'').toString().slice(0,80), text: t});
                        break;
                    }
                }
                if (out.length > 10) break;
            }
            return out;
        }""")
        for x in info:
            print(f"  {x['marker']}: tag={x['tag']} class={x['cls']} text={x['text'][:40]}")
        if not info:
            print("  未检测到进度标记（回答可能已完成）")
    except Exception as e:
        print("  异常:", e)

    await c.close()
    print("\n=== 完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
