"""重算指定 task 的 analysis_results.rank + geo_scores, 修复竞品关键词对称化后的历史 rank。

只重算 ucloud_rank / ucloud_mentioned / ucloud_mention_count / ucloud_first_position /
position_weight / competitor_mentions 这几个受关键词影响的字段；
不动 raw_content / citations / sentiment 等抓取与分析产物。

用法:
    python scripts/recalc_task_ranks.py <task_id>
    python scripts/recalc_task_ranks.py task_20260630_175114_afcd48 --dry-run

dry-run 只打印 rank 变化, 不写库。
"""
import argparse
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
if sys.platform == "win32" and sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass

import database as db
from analyzer import ResponseAnalyzer
from brand_profile import default_brand_profile


async def recalc(task_id: str, dry_run: bool):
    task = await db.get_task(task_id)
    if not task:
        print(f"❌ task 不存在: {task_id}")
        return
    brand_id = task.get("brand_id") or "ucloud"
    profile = db.get_brand_profile_by_id(brand_id) or default_brand_profile()
    analyzer = ResponseAnalyzer(brand_profile=profile)

    rows = await db.get_task_results(task_id)
    print(f"task {task_id} 共 {len(rows)} 条 analysis_results, brand={brand_id}")

    changed = []
    for r in rows:
        raw = r.get("raw_content") or ""
        err = r.get("error_message") or ""
        if err or not raw:
            continue  # 错误/空行不重算 rank
        res = analyzer.analyze(r["question_id"], r["model_key"],
                               r.get("model_name") or r["model_key"], raw, error=None)
        old_rank = r.get("ucloud_rank")
        new_rank = res.ucloud_rank
        old_mentioned = bool(r.get("ucloud_mentioned"))
        new_mentioned = res.ucloud_mentioned
        if old_rank != new_rank or old_mentioned != new_mentioned:
            changed.append({
                "model": r["model_key"], "qid": r["question_id"],
                "old_rank": old_rank, "new_rank": new_rank,
                "old_mentioned": old_mentioned, "new_mentioned": new_mentioned,
            })

    print(f"\nrank/mentioned 变化: {len(changed)} 条")
    for c in changed:
        flag = ""
        if c["old_rank"] and c["old_rank"] <= 3 and not (c["new_rank"] and c["new_rank"] <= 3):
            flag = "  <<<退出top3"
        elif (not c["old_rank"] or c["old_rank"] > 3) and c["new_rank"] and c["new_rank"] <= 3:
            flag = "  <<<新进top3"
        print(f"  {c['model']:8} {c['qid']:5}  rank {c['old_rank']}→{c['new_rank']}  mentioned {c['old_mentioned']}→{c['new_mentioned']}{flag}")

    if dry_run:
        print("\n[dry-run] 未写库")
        return

    if not changed:
        print("\n无变化, 跳过写库 + 评分重算")
        return

    # 写回 rank 相关字段
    for r in rows:
        raw = r.get("raw_content") or ""
        err = r.get("error_message") or ""
        if err or not raw:
            continue
        res = analyzer.analyze(r["question_id"], r["model_key"],
                               r.get("model_name") or r["model_key"], raw, error=None)
        if (res.ucloud_rank == r.get("ucloud_rank") and
                bool(res.ucloud_mentioned) == bool(r.get("ucloud_mentioned"))):
            continue
        # 直接 UPDATE 这几列
        conn = await db.get_db()
        try:
            import json as _json
            comp_ser = _json.dumps(
                {k: [dict(m.__dict__) for m in v] for k, v in res.competitor_mentions.items()},
                ensure_ascii=False)
            await conn.execute(
                """UPDATE analysis_results
                   SET ucloud_mentioned=?, ucloud_mention_count=?, ucloud_rank=?,
                       position_weight=?, competitor_mentions=?
                   WHERE id=?""",
                (int(res.ucloud_mentioned), res.ucloud_mention_count, res.ucloud_rank,
                 res.position_weight, comp_ser, r["id"])
            )
            await conn.commit()
        finally:
            await conn.close()

    # 重算 geo_scores
    from services import task_service
    await task_service.recalculate_task_scores(task_id)
    print(f"\n✅ 已写回 {len(changed)} 条 rank, 并重算 geo_scores")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task_id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(recalc(args.task_id, args.dry_run))
