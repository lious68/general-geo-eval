"""验证 Kimi 搜索面板截断修复 — 不再只抓到搜索面板

0630 坏题代表:
  q020: 旧52字(只搜索面板); 新应含正文 markdown >200字
  q028: 旧85字(只搜索面板); 新应含正文 markdown >200字
  q036: 旧108字(搜索面板+正文首句); 新应含完整正文 >200字
防回归: q002 非搜索直答(旧2338字OK), 新应仍正常。
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
    ("q020", "国内云厂商出海能力哪家强？", 52, "search_panel_truncated"),
    ("q028", "7B/14B/32B/67B 参数模型分别需要什么 GPU 配置？", 85, "search_panel_truncated"),
    ("q036", "适合中小企业的大模型平台有哪些？", 108, "search_panel_truncated"),
    ("q002", "优刻得轻量云主机怎么样？", 2338, "nonsearch_regression"),
]


async def run_one(client, qid, question, old_len, kind):
    r = await client.chat(question)
    text = r.get("content", "") or ""
    n = len(text)
    head = text[:60].replace("\n", " ")
    print(f"\n{'='*60}\n[{qid}] {kind} (旧长度={old_len})")
    print(f"  新长度={n}  err={r.get('error')}")
    print(f"  head: {head!r}")
    return {"qid": qid, "kind": kind, "n": n, "old_len": old_len, "text": text, "error": r.get("error")}


async def main():
    os.environ["DISPLAY"] = ":0"
    print("启动 Kimi 客户端（headed）...")
    client = create_web_chat_client("kimi")
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
        if kind == "search_panel_truncated":
            # 不再只抓到搜索面板: 长度 > 200 且 head 不止是搜索面板
            is_pure_panel = n < 150 and ("搜索网页" in text or "个结果" in text)
            passed = n > 200 and not is_pure_panel
            tag = "搜索面板截断已修复(>200字正文)"
        else:
            # q002 非搜索直答防回归: 仍 >200 字
            passed = n > 200
            tag = "非搜索直答防回归"
        flag = "✅" if passed else "❌"
        print(f"  {flag} [{qid}] {tag}: 新={n} 旧={old_len}")
        if not passed:
            ok = False
            print(f"     head: {text[:100]!r}")

    print(f"\n{'✅ 全部通过' if ok else '❌ 存在未通过项'}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
