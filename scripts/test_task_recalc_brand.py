"""评分口径自检：task 重算用 task.brand_id 的 profile，不串 current 品牌。"""
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


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # 建第二个品牌 acme 并设为 current（制造串口径条件）
    acme = derive_from_input("Acme云", "阿克米", "https://acme-cloud.cn", "云计算")
    await db.create_brand("acme", acme)
    await db.set_current_brand_id("acme")  # current=acme

    # 给 ucloud 品牌建题集 + 任务 + 导入结果（brand_id=ucloud）
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO questions (id, category, question_type, question, difficulty, is_active, brand_id) "
            "VALUES ('Q1','品类词','品类词','便宜的云主机推荐？','medium',1,'ucloud')")
        await conn.commit()
    finally:
        await conn.close()

    # 建任务（brand_id 默认 ucloud）
    task = await task_service.create_task_with_questions("T", ["Q1"])
    task_id = task["id"]
    # 确认 task.brand_id == ucloud
    t = await db.get_task(task_id)
    assert t["brand_id"] == "ucloud", f"task.brand_id 应为 ucloud，实得 {t.get('brand_id')}"

    # 导入 ucloud 题的结果（含 UCloud 提及）
    await task_service.import_batch_results(task_id, {
        "meta": {"task_id": task_id, "batch_id": "b1", "run_id": "r1"},
        "questions": [],
        "analysis_results": {"deepseek": [{
            "question_id": "Q1", "model_key": "deepseek", "model_name": "DeepSeek",
            "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
            "has_citation": False, "citation_count": 0, "ucloud_recommended": False,
            "recommendation_strength": "none", "sentiment_score": 0.6, "sentiment_label": "positive",
            "position_weight": 0.5, "response_length": 10, "raw_content": "UCloud 海外云主机不错",
            "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": [],
        }]},
    })

    # 此时 current=acme，但 task 属 ucloud。重算应按 ucloud 口径算（提及率=1.0）。
    scores = await db.get_task_scores(task_id)
    assert scores, "应有评分"
    s = next(x for x in scores if x.get("category") is None)
    # ucloud 口径下 Q1 是自然问题（题干不含 UCloud），UCloud 被提及 → coverage_rate=1.0
    assert s["coverage_rate"] == 1.0, f"ucloud 口径下 coverage_rate 应为 1.0，实得 {s['coverage_rate']}"

    print("✅ PASS: task 重算按 task.brand_id 口径（不串 current）")


if __name__ == "__main__":
    asyncio.run(main())
