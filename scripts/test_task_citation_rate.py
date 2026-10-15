"""task 引用率（citation_rate）自检（TDD RED→GREEN）。

bug：recalculate_task_scores 经 _result_to_analysis 重建 AnalysisResult 时
未解析 DB 行的 citations/all_cited_urls JSON → result.citations 恒为 [] →
MetricsCalculator._has_effective_citation 恒 False → task citation_rate 恒 0。

口径（与 metrics.py / 定义一致）：
  引用率 = 含有效引用的响应数 / 有效响应总数
  有效 = UCloud 官方引用 OR (提及UCloud时的第三方来源引用)

本测：4 道有效题，2 条带有效引用（Q1 官方、Q2 第三方+提及）、2 条无效引用
（Q3 非第三方域名、Q4 无引用）→ citation_rate 应 = 2/4 = 0.5，而非 0。
"""
from batch_fixture import seed_batch
import asyncio
import os
import sys
import tempfile
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from services import task_service


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # 4 道对比词自然题（citation 分母 = 全部有效响应）
    conn = await db.get_db()
    try:
        for i in range(1, 5):
            await conn.execute(
                "INSERT INTO questions (id, category, question_type, question, difficulty, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (f"Q{i}", "对比词", "对比词", f"问题{i}", "medium"))
        await conn.commit()
    finally:
        await conn.close()

    task = await task_service.create_task_with_questions("CiteRate", ["Q1", "Q2", "Q3", "Q4"])
    task_id = task["id"]

    cfg = await seed_batch(
        task_id, ["kimi"], {"kimi": ["Q1", "Q2", "Q3", "Q4"]}, delay=8
    )

    await task_service.import_batch_results(task_id, {
        "meta": {"task_id": task_id, "batch_id": cfg["batch_id"], "run_id": cfg["run_id"]},
        "questions": [],
        "analysis_results": {"kimi": [
            # Q1：UCloud 官方引用 → 有效
            _mk("Q1", citations=[_url("https://www.ucloud.cn/product/uaio.html", is_ucloud=True)]),
            # Q2：提及UCloud + 知乎第三方来源 → 有效
            _mk("Q2", citations=[_url("https://zhuanlan.zhihu.com/p/123456", is_ucloud=False)]),
            # Q3：提及UCloud + 非第三方域名(example.com) → 无效
            _mk("Q3", citations=[_url("https://example.com/some/path", is_ucloud=False)]),
            # Q4：无任何引用 → 无效
            _mk("Q4", citations=[]),
        ]},
    })

    scores = await db.get_task_scores(task_id)
    assert scores, "应有全局评分"
    kimi = next(s for s in scores if s["model_key"] == "kimi")
    print(f"  citation_rate = {kimi['citation_rate']}  (期望 0.5)")
    assert kimi["citation_rate"] == 0.5, f"引用率应为 2/4=0.5，实得 {kimi['citation_rate']}"
    assert kimi["valid_responses"] == 4, f"有效响应应为 4，实得 {kimi['valid_responses']}"

    # 对照：metrics 口径下 Q1(官方)/Q2(提及+第三方) 有效，Q3(非第三方)/Q4(无) 无效 → 2/4。
    # 用 MetricsCalculator 直接复核 _result_to_analysis 重建后的判定。
    from metrics import MetricsCalculator, _has_effective_citation
    rows = await db.get_task_results(task_id, "kimi")
    rebuilt = [task_service._result_to_analysis(r) for r in rows]
    eff = {r.question_id: _has_effective_citation(r) for r in rebuilt}
    assert eff == {"Q1": True, "Q2": True, "Q3": False, "Q4": False}, eff

    print("✅ PASS: task 引用率 = 有效引用数/有效响应数（2/4=0.5，非 0；_result_to_analysis 正确重建 citations）")


def _url(content, is_ucloud=False, channel=""):
    return {"citation_type": "url", "content": content, "position": -1,
            "source_channel": channel, "is_ucloud": is_ucloud}


def _mk(qid, citations):
    return {
        "question_id": qid, "model_key": "kimi", "model_name": "KIMI",
        "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
        "has_citation": bool(citations), "citation_count": len(citations),
        "ucloud_recommended": True, "recommendation_strength": "strong",
        "sentiment_score": 0.6, "sentiment_label": "positive",
        "position_weight": 0.5, "response_length": 5,
        "raw_content": "UCloud 是云服务商，参考 " + " / ".join(c["content"] for c in citations) if citations else "UCloud",
        "competitor_mentions": {}, "error_message": None,
        "citations": citations, "all_cited_urls": citations,
    }


if __name__ == "__main__":
    asyncio.run(main())
