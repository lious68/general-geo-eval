"""回填品牌提及口径：对 task 的每条 analysis_result，用修复后的 analyzer 重算
提及相关字段（ucloud_mentioned/mention_count/rank/position_weight/recommendation/
sentiment/has_citation），保留存储的 citations/all_cited_urls 不变（API 搜索引用
无法从 raw_content 重派生），然后重算 geo_scores。

用法: python scripts/backfill_mentions.py <task_id | ALL>
"""
import asyncio, os, sys, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from analyzer import ResponseAnalyzer, has_effective_citation
from brand_profile import default_brand_profile
from services import task_service


async def backfill_task(task_id: str):
    profile = db.get_brand_profile_by_id(
        (await db.get_task(task_id) or {}).get("brand_id") or "ucloud")
    analyzer = ResponseAnalyzer(brand_profile=profile)

    rows = await db.get_task_results(task_id)
    print(f"[{task_id}] {len(rows)} 条结果待回填")
    flipped_mentioned = 0
    flipped_citation = 0
    conn = await db.get_db()
    try:
        for r in rows:
            content = r.get("raw_content") or ""
            if r.get("error_message") or not content:
                continue
            # 复用存储的 citations / all_cited_urls（API 搜索引用不可重派生）
            from services.task_service import _result_to_analysis, _parse_citation_infos
            ar = _result_to_analysis(r)
            # 重算提及相关（顺序：mentions → competitor → position → rank → rec → sentiment）
            analyzer._detect_brand_mentions(content, ar)
            analyzer._detect_competitor_mentions(content, ar)
            analyzer._calculate_position_weight(content, ar)
            analyzer._calculate_rank(content, ar)
            analyzer._detect_recommendations(content, ar)
            analyzer._analyze_sentiment(content, ar)
            # has_citation 走 GEO 口径重判（依赖 corrected ucloud_mentioned + 存储 citations）
            new_has_cite = has_effective_citation(ar)

            old_mentioned = bool(r.get("ucloud_mentioned"))
            old_has_cite = bool(r.get("has_citation"))
            if old_mentioned != ar.ucloud_mentioned:
                flipped_mentioned += 1
            if old_has_cite != new_has_cite:
                flipped_citation += 1

            await conn.execute(
                "UPDATE analysis_results SET "
                "ucloud_mentioned=?, ucloud_mention_count=?, ucloud_rank=?, "
                "position_weight=?, ucloud_recommended=?, recommendation_strength=?, "
                "sentiment_score=?, sentiment_label=?, has_citation=?, citation_count=? "
                "WHERE id=?",
                (int(ar.ucloud_mentioned), ar.ucloud_mention_count, ar.ucloud_rank,
                 ar.position_weight, int(ar.ucloud_recommended),
                 ar.ucloud_recommendation_strength, ar.sentiment_score,
                 ar.sentiment_label, int(new_has_cite), ar.citation_count, r["id"]))
        await conn.commit()
    finally:
        await conn.close()

    print(f"[{task_id}] 提及翻转 {flipped_mentioned} 条, 引用翻转 {flipped_citation} 条")
    # 重算评分
    await task_service.recalculate_task_scores(task_id)
    print(f"[{task_id}] geo_scores 已重算")


async def main():
    if len(sys.argv) < 2:
        print("用法: python backfill_mentions.py <task_id | ALL>")
        sys.exit(1)
    target = sys.argv[1]
    await db.init_db()
    if target.upper() == "ALL":
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        tids = [r[0] for r in conn.execute("SELECT id FROM tasks")]
        conn.close()
        print(f"ALL: {len(tids)} 个任务")
    else:
        tids = [target]
    for tid in tids:
        await backfill_task(tid)
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
