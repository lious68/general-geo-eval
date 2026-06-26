"""验证文心一言 (chat.baidu.com) 响应提取选择器（不发新问题，复用 diag 已发送的回答）。

跑完 diag_ernie_response2.py 后页面已有一轮问答，本脚本重新打开、发一道简短问题、
用新 RESPONSE_SELECTOR(.answer-box.last-answer-box) 走完整 _wait_for_response +
_extract_response，确认能拿到非空正文，再 print 出来。

用法（Win RDP）：
    cd C:\\general-geo-eval
    python scripts\\verify_ernie_extract.py
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

QUESTION = "UCloud优刻得是做什么的？用一句话回答。"


async def main():
    c = create_web_chat_client("ernie")
    if not c.is_configured:
        print("❌ 无 ernie 登录态"); return
    if not await c.initialize():
        print("❌ 浏览器启动失败"); return
    page = c._page
    await c._goto_site(page)
    await asyncio.sleep(5)

    # 发问题
    print(f"发送问题: {QUESTION}")
    ta = page.locator("#chat-textarea")
    await ta.wait_for(state="visible", timeout=10000)
    await ta.click()
    await asyncio.sleep(0.3)
    await page.keyboard.type(QUESTION, delay=20)
    await asyncio.sleep(0.4)
    await page.keyboard.press("Enter")

    # 走完整等待+提取（与生产路径一致）
    print("等待响应完成（_wait_for_response）...")
    await c._wait_for_response(page, timeout=180)
    print("提取响应文本（_extract_response）...")
    text = await c._extract_response(page)

    print("\n=== 提取结果 ===")
    print(f"文本长度: {len(text)}")
    print(f"正文:\n{text}")

    if len(text) < 20:
        print("\n⚠️ 提取失败或过短——选择器可能仍未命中")
    else:
        print("\n✅ 提取成功，选择器 .answer-box.last-answer-box 可用")

    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
