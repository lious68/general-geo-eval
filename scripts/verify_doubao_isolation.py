"""验证豆包会话隔离修复：连问 2 题，确认第 2 题不携带第 1 题上下文。

用法（本地 Windows，headed，需已 setup 豆包登录态）：
  python scripts/verify_doubao_isolation.py

通过条件：q011 回答里不含 q003 的标志文本"UCloud海外有哪些节点"，
且 q011 回答不以"结合你的场景/背景/需求"等引用前题上下文开头。
"""
import asyncio, os, sys, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import DoubaoWebChatClient

Q003 = "UCloud 海外有哪些节点？"          # 引导型
Q011 = "国内企业出海用什么云？"          # 自然题
Q003_MARK = "UCloud海外有哪些节点"       # q003 题干标志，串题时会出现
BLEED_MARKS = ["结合你的场景", "结合你的背景", "结合你的需求", "前面提到", "上文", "如前所述"]


async def main():
    c = DoubaoWebChatClient("doubao")
    if not await c.initialize():
        print("❌ 豆包未登录，先跑: python scripts/setup_webchat_auth.py doubao")
        return 2
    print("✓ 已登录，开始验证")

    await c._navigate_to_chat(c._page)
    # 第一题 q003
    print("\n[1/2] 提问 q003 ...")
    r1 = await c.chat(Q003)
    a1 = r1.get("content", "") or ""
    print(f"  q003 回答 {len(a1)} 字")

    # 第二题 q011（chat() 内部会调修复后的 _start_new_chat）
    print("\n[2/2] 提问 q011（chat 内部已调 _start_new_chat 重置）...")
    r2 = await c.chat(Q011)
    a2 = r2.get("content", "") or ""
    print(f"  q011 回答 {len(a2)} 字")

    await c.close()

    # 判 contamination
    mark_hit = Q003_MARK in a2
    bleed_hit = [m for m in BLEED_MARKS if m in a2[:200]]
    print("\n" + "=" * 60)
    print(f"q011 含 q003 标志文本({Q003_MARK}): {mark_hit}")
    print(f"q011 开头串题信号: {bleed_hit or '无'}")
    if mark_hit or bleed_hit:
        print("❌ FAIL: 串题！_start_new_chat 未隔离，别跑全量")
        print(f"\nq011 开头 200 字:\n{a2[:200]}")
        return 1
    print("✅ PASS: 隔离生效，q011 未携 q003 上下文，可跑全量 40 题")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
