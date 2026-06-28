"""豆包硬重载隔离验证 — 直接用改后的 DoubaoWebChatClient.chat() 跑两题

用法:
    python scripts/diag_doubao_iso_v5.py

验证 _start_new_chat 改成「硬 goto /chat 整页重载」后，q011 是否还串入 q003。
判定：q011 raw 正文里不应出现 q003 的问题文本 "UCloud海外有哪些节点"。
"""
import asyncio
import io
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

Q003 = "UCloud海外有哪些节点？"
Q011 = "UCloud和阿里云有什么区别？"
Q003_MARK = "UCloud海外有哪些节点"


async def _state(page):
    try:
        return await page.evaluate("""() => {
          const ml = document.querySelector('[class*="message-list"]');
          const cnt = ml ? ml.querySelectorAll('[class*="message-row"], [class*="v_list_row"], [class*="chat-message"]').length : 0;
          return { url: location.href, msg_count: cnt };
        }""")
    except Exception:
        return {"url": page.url, "msg_count": -1}


async def main():
    os.environ["DISPLAY"] = ":0"
    os.makedirs("output", exist_ok=True)

    print("启动豆包客户端（沿用登录态）...")
    client = create_web_chat_client("doubao")
    if not await client.initialize():
        print("浏览器启动失败"); return
    await client._navigate_to_chat(client._page)
    page = client._page

    result = {"stages": {}}

    # ── q003 ──
    print(f"\n发 q003: {Q003}")
    r003 = await client.chat(Q003)
    body003 = r003.get("content", "")
    st003 = await _state(page)
    print(f"[q003 完成] {st003}  正文{len(body003)}字  err={r003.get('error')}")
    result["stages"]["q003"] = {"state": st003, "body_len": len(body003),
                                "body_head": body003[:200], "error": r003.get("error")}

    # ── q011（chat() 内部会先调 _start_new_chat 硬重载）──
    print(f"\n发 q011: {Q011}")
    r011 = await client.chat(Q011)
    body011 = r011.get("content", "")
    st011 = await _state(page)
    mark_pos = body011.find(Q003_MARK)
    contaminated = mark_pos >= 0
    print(f"[q011 完成] {st011}  正文{len(body011)}字  err={r011.get('error')}")
    print(f"\n=== 隔离判定 ===")
    print(f"q011 正文含 q003 问题文本(Q003_MARK) = {contaminated}")
    if contaminated:
        print(f"  位置: pos={mark_pos}/{len(body011)}")
        print(f"  上下文: ...{body011[max(0,mark_pos-60):mark_pos+100]}...")
        print("  → 隔离失败")
    else:
        print("  → 隔离成功")
    print(f"\nq011 正文开头:\n{body011[:300]}")

    result["stages"]["q011"] = {
        "state": st011, "body_len": len(body011),
        "body_head": body011[:300], "error": r011.get("error"),
        "contaminated": contaminated, "mark_pos": mark_pos,
    }
    result["isolation_ok"] = not contaminated

    with open("output/doubao_iso_v5_dom.json", "w", encoding="utf-8") as f:
        import json
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open("output/_v5_q011_body.txt", "w", encoding="utf-8") as f:
        f.write(body011)
    print("\n证据: output/doubao_iso_v5_dom.json + output/_v5_q011_body.txt")

    await client.close()
    print("完成。")


if __name__ == "__main__":
    asyncio.run(main())
