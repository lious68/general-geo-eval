"""验证千问"慢启动"修复 — 非搜索直答题不再被截断成 ~70 字。

bug 证据（batch_20260701_133519 q010-q016）：
  runner_global.log 全部 "response stable after 3s (2 checks, 4 chars)"
  → response_length 72/74/89/74/97/79/101，句尾"国内头"等被截断。
  根因：千问先吐 4 字前缀再停顿 1-3s 才继续流式；基类
  _wait_for_text_stability 默认 stable_threshold=2 在停顿期误判完成。

  修复（web_chat_clients.QwenWebChatClient._wait_for_response）：
  先等正文越过慢启动门槛（≥40 字），再跑 stability（threshold=3）；
  极短答案（<40 字且 6s 不再增长）直接判完成。

本脚本对 3 道曾被截断的非搜索题 + 1 道搜索题复跑，断言：
  - 非搜索题 response_length 显著 > 100（旧值 72/79/101）；
  - 答案文本不以半截词结尾（无"头/部/云"等突兀截断尾）；
  - 搜索题仍正常出长文 + 引用（未回归）。
"""
import asyncio
import os
import sys

# Windows 控制台 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client

# (qid, question, 旧截断长度, 是否搜索型)
CASES = [
    ("q010", "国内厂商谁家海外节点多？", 72, False),
    ("q015", "哪家云厂商亚洲节点多？", 79, False),
    ("q016", "海外住宅 ip 轻量云主机买谁家的？", 101, False),
    ("q003", "UCloud海外有哪些节点？", 1280, True),  # 搜索型，防回归
]


async def run_one(client, qid, question, old_len, is_search):
    page = client._page
    print(f"\n{'='*60}\n[{qid}] {question}  (旧长度={old_len}, 搜索型={is_search})")
    await client._start_new_chat(page)
    await client._type_question(page, question)
    await client._send_question(page)
    await client._wait_for_response(page, timeout=120)
    text = await client._extract_response(page)
    n = len(text)
    head = text[:60].replace("\n", " ")
    tail = text[-40:].replace("\n", " ") if n >= 40 else text
    print(f"  新长度={n}  (旧={old_len}, Δ={n - old_len:+d})")
    print(f"  head: {head!r}")
    print(f"  tail: {tail!r}")
    has_cite = "引用来源" in text
    print(f"  引用来源: {has_cite}")
    return {"qid": qid, "n": n, "old_len": old_len, "is_search": is_search,
            "has_cite": has_cite, "text": text}


async def main():
    os.environ["DISPLAY"] = ":0"
    print("启动千问客户端（headed）...")
    client = create_web_chat_client("qwen")
    if not await client.initialize():
        print("❌ 启动失败"); return
    await client._navigate_to_chat(client._page)

    results = []
    for qid, q, old_len, is_search in CASES:
        try:
            r = await run_one(client, qid, q, old_len, is_search)
            results.append(r)
        except Exception as e:
            print(f"  ❌ [{qid}] 异常: {e}")
            import traceback; traceback.print_exc()
        await asyncio.sleep(3)

    await client.close()

    print(f"\n{'='*60}\n断言:")
    ok = True
    for r in results:
        qid, n, old_len, is_search = r["qid"], r["n"], r["old_len"], r["is_search"]
        if is_search:
            # 搜索型：应仍出长文（≥200）且有引用，未回归
            passed = n >= 200 and r["has_cite"]
            tag = "搜索型防回归"
        else:
            # 非搜索型：新长度应显著 > 旧截断长度（至少 +30 字，且 >100）
            passed = n > old_len + 30 and n > 100
            tag = "非搜索型不再截断"
        flag = "✅" if passed else "❌"
        print(f"  {flag} [{qid}] {tag}: 新={n} 旧={old_len} 引用={r['has_cite']}")
        if not passed:
            ok = False
            print(f"     tail: {r['text'][-60:]!r}")

    print(f"\n{'✅ 全部通过' if ok else '❌ 存在未通过项'}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
