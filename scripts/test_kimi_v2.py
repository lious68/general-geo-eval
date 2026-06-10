"""
用实际 web_chat_clients.py 代码测试 Kimi 完整链路
"""
import asyncio
import os
import sys

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from web_chat_clients import create_web_chat_client


async def test():
    os.environ["DISPLAY"] = ":0"
    print("创建 Kimi 客户端...")
    client = create_web_chat_client("kimi")

    print("初始化浏览器...")
    ok = await client.initialize()
    if not ok:
        print("浏览器启动失败")
        return

    os.makedirs("output", exist_ok=True)

    # Step 1: Navigate
    print("\n=== Step 1: 导航 ===")
    try:
        await client._navigate_to_chat(client._page)
        print(f"  URL: {client._page.url}")
        print(f"  Title: {await client._page.title()}")
        await client._page.screenshot(path="output/kimi_v2_step1.png")
        print("  OK")
    except Exception as e:
        print(f"  FAIL: {e}")
        await client.close()
        return

    # Step 2: Type
    print("\n=== Step 2: 输入 ===")
    question = "UCloud海外云主机怎么样？"
    try:
        await client._type_question(client._page, question)
        # Verify
        typed = await client._page.evaluate("""() => {
            var el = document.querySelector('[contenteditable="true"]');
            return el ? el.textContent : 'NOT FOUND';
        }""")
        print(f"  输入框内容: '{typed}'")
        if typed and len(typed) > len(question) * 0.5:
            print("  OK - 输入成功")
        else:
            print(f"  WARN - 输入可能失败 (期望{len(question)}字，得到{len(typed)}字)")
        await client._page.screenshot(path="output/kimi_v2_step2.png")
    except Exception as e:
        print(f"  FAIL: {e}")
        await client.close()
        return

    # Step 3: Send
    print("\n=== Step 3: 发送 ===")
    try:
        await client._send_question(client._page)
        print("  OK - 已发送")
        await client._page.screenshot(path="output/kimi_v2_step3.png")
    except Exception as e:
        print(f"  FAIL: {e}")
        await client.close()
        return

    # Step 4: Wait
    print("\n=== Step 4: 等待响应 (60秒) ===")
    try:
        await client._wait_for_response(client._page, timeout=60)
        text_len = await client._page.evaluate("""() => document.body.innerText.length""")
        print(f"  OK - 页面文本 {text_len} 字")
        await client._page.screenshot(path="output/kimi_v2_step4.png", full_page=True)
    except Exception as e:
        print(f"  WARN: {e}")
        await client._page.screenshot(path="output/kimi_v2_step4_warn.png", full_page=True)

    # Step 5: Extract
    print("\n=== Step 5: 提取响应 ===")
    try:
        response = await client._extract_response(client._page)
        print(f"  提取到 {len(response)} 字")
        print(f"  预览: {response[:500]}")
        print("  OK")
    except Exception as e:
        print(f"  FAIL: {e}")

    await client.close()
    print("\n完成。")


if __name__ == "__main__":
    asyncio.run(test())
