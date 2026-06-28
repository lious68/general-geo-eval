"""多品牌并行隔离端到端：两品牌题集/任务/评分互不污染 + 切品牌不串口径。"""
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
from brand_profile import derive_from_input


def _mk(qid, mk, content):
    return {"question_id": qid, "model_key": mk, "model_name": mk.upper(),
            "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
            "has_citation": False, "citation_count": 0, "ucloud_recommended": False,
            "recommendation_strength": "none", "sentiment_score": 0.6, "sentiment_label": "positive",
            "position_weight": 0.5, "response_length": len(content), "raw_content": content,
            "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": []}


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # 建 acme 品牌
    acme = derive_from_input("Acme云", "阿克米", "https://acme-cloud.cn", "云计算")
    await db.create_brand("acme", acme)

    # ucloud 题集 + 任务 + 导入
    await db.upsert_question({"id": "u_q1", "category": "品类词", "question_type": "品类词",
        "question": "便宜的云主机推荐？", "tags": [], "difficulty": "medium"}, brand_id="ucloud")
    u_task = await task_service.create_task_with_questions("UT", ["u_q1"], brand_id="ucloud")
    await task_service.import_batch_results(u_task["id"], {
        "meta": {"task_id": u_task["id"], "batch_id": "ub", "run_id": "ur"},
        "questions": [], "analysis_results": {"deepseek": [_mk("u_q1", "deepseek", "UCloud 不错")]}
    })

    # acme 题集 + 任务 + 导入（题干不含 Acme，回答含 Acme云）
    await db.upsert_question({"id": "a_q1", "category": "品类词", "question_type": "品类词",
        "question": "便宜的云主机推荐？", "tags": [], "difficulty": "medium"}, brand_id="acme")
    a_task = await task_service.create_task_with_questions("AT", ["a_q1"], brand_id="acme")
    await task_service.import_batch_results(a_task["id"], {
        "meta": {"task_id": a_task["id"], "batch_id": "ab", "run_id": "ar"},
        "questions": [], "analysis_results": {"deepseek": [
            {**_mk("a_q1", "deepseek", "Acme云 不错"), "ucloud_mentioned": True}
        ]}
    })

    # 切到 acme（current=acme），重算 ucloud 任务：应用 ucloud 口径
    await db.set_current_brand_id("acme")
    await task_service.recalculate_task_scores(u_task["id"])
    u_scores = await db.get_task_scores(u_task["id"])
    us = next(x for x in u_scores if x.get("category") is None)
    assert us["coverage_rate"] == 1.0, f"ucloud 任务应按 ucloud 口径 coverage=1.0，实得 {us['coverage_rate']}"

    # acme 任务：按 acme 口径（题干不含 Acme，回答含 Acme云 → coverage=1.0）
    await task_service.recalculate_task_scores(a_task["id"])
    a_scores = await db.get_task_scores(a_task["id"])
    asr = next(x for x in a_scores if x.get("category") is None)
    assert asr["coverage_rate"] == 1.0, f"acme 任务应按 acme 口径 coverage=1.0，实得 {asr['coverage_rate']}"

    # 隔离：ucloud 任务列表不含 acme 任务
    await db.set_current_brand_id("ucloud")
    u_tasks = await db.list_tasks()
    assert all(t["id"] != a_task["id"] for t in u_tasks), "ucloud 任务列表不应含 acme 任务"
    await db.set_current_brand_id("acme")
    a_tasks = await db.list_tasks()
    assert all(t["id"] != u_task["id"] for t in a_tasks), "acme 任务列表不应含 ucloud 任务"

    print("✅ PASS: 多品牌并行隔离 + 口径不串")


if __name__ == "__main__":
    asyncio.run(main())
