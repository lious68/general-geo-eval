"""验证豆包「串题/空回声」修复 — 锚定本次 assistant 气泡

0630 坏题代表：
  - q002 直答题(空回声): 旧 raw==题干 12字；新应 >100 字实质回答
  - q006 引导题(串题→q003): 旧首行="UCloud海外有哪些节点？"；新首行应=本题/本题答案
  - q003 搜索题(首页噪声+引用): 旧含"新对话/资讯："；新应出长文+引用源(防回归)

断言:
  - q002 raw 不再 == 题干，长度 > 100
  - q006 raw 不含 q003 题干"UCloud海外有哪些节点"（除非在引用区后段）
  - q003 raw 含实质正文(>200字) + 引用来源段
"""
import asyncio
import io
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client

CASES = [
    ("q002", "优刻得轻量云主机怎么样？", 12, "empty_echo"),
    ("q006", "优刻得 GPU 云支持哪些显卡型号？", 2266, "cross_question"),
    ("q003", "UCloud海外有哪些节点？", 205, "search_regression"),
]
Q003_MARK = "UCloud海外有哪些节点"


async def run_one(client, qid, question, old_len, kind):
    r = await client.chat(question)
    text = r.get("content", "") or ""
    n = len(text)
    head = text[:60].replace("\n", " ")
    tail = text[-40:].replace("\n", " ") if n >= 40 else text
    has_cite = "引用来源" in text
    print(f"\n{'='*60}\n[{qid}] {kind} (旧长度={old_len})")
    print(f"  新长度={n}  err={r.get('error')}")
    print(f"  head: {head!r}")
    print(f"  tail: {tail!r}")
    print(f"  引用来源段: {has_cite}")
    return {"qid": qid, "kind": kind, "n": n, "old_len": old_len,
            "text": text, "has_cite": has_cite, "error": r.get("error")}


async def main():
    os.environ["DISPLAY"] = ":0"
    print("启动豆包客户端（headed）...")
    client = create_web_chat_client("doubao")
    if not await client.initialize():
        print("❌ 启动失败"); return
    await client._navigate_to_chat(client._page)

    results = []
    for qid, q, old_len, kind in CASES:
        try:
            r = await run_one(client, qid, q, old_len, kind)
            results.append(r)
        except Exception as e:
            print(f"  ❌ [{qid}] 异常: {e}")
            import traceback; traceback.print_exc()
        await asyncio.sleep(3)

    await client.close()

    print(f"\n{'='*60}\n断言:")
    ok = True
    for r in results:
        qid, n, old_len, kind, text = r["qid"], r["n"], r["old_len"], r["kind"], r["text"]
        if kind == "empty_echo":
            # q002: 不再==题干, >100字
            passed = n > 100 and not text.strip().startswith("优刻得轻量云主机怎么样？") is False
            # 实际断言: 长度>100 且 不只是题干
            passed = n > 100 and text.strip() != "优刻得轻量云主机怎么样？"
            tag = "空回声已修复(>100字实质回答)"
        elif kind == "cross_question":
            # q006: 正文前 60% 不含 q003 题干标记(避免串入 q003 答案)
            mark_pos = text.find(Q003_MARK)
            in_cite_zone = mark_pos > len(text) * 0.6 if mark_pos >= 0 else False
            passed = (mark_pos < 0) or in_cite_zone
            tag = "串题已修复(前段不含q003答案)"
        else:
            # q003 搜索题: >200字 + 有引用来源段(防引用回归)
            passed = n > 200 and r["has_cite"]
            tag = "搜索题防回归(长文+引用)"
        flag = "✅" if passed else "❌"
        print(f"  {flag} [{qid}] {tag}: 新={n} 旧={old_len} 引用={r['has_cite']}")
        if not passed:
            ok = False
            print(f"     head: {text[:80]!r}")

    print(f"\n{'✅ 全部通过' if ok else '❌ 存在未通过项'}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
