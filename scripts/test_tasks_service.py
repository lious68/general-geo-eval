"""task_service 自检：建任务 → 建批次 → 两次导入合并去重 → 矩阵 + 重算。"""
import asyncio
import os
import sys
import tempfile
import io

# Windows console may default to GBK; force UTF-8 for the emoji print
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

    # 插入 4 道测试题
    conn = await db.get_db()
    try:
        for i in range(1, 5):
            await conn.execute(
                "INSERT INTO questions (id, category, question_type, question, difficulty, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (f"Q{i}", "品牌词" if i <= 2 else "对比词", "品牌词" if i <= 2 else "对比词",
                 f"问题{i}", "medium")
            )
        await conn.commit()
    finally:
        await conn.close()

    # 1. 建任务（固定总题集 Q1..Q4）
    task = await task_service.create_task_with_questions("T1", ["Q1", "Q2", "Q3", "Q4"])
    task_id = task["id"]

    # 2. 建批次：deepseek 跑 Q1,Q2；kimi 跑 Q1,Q2,Q3
    cfg = await task_service.create_batch_config(
        task_id, ["deepseek", "kimi"],
        {"deepseek": ["Q1", "Q2"], "kimi": ["Q1", "Q2", "Q3"]}, delay=8
    )
    assert cfg["version"] == 2 and cfg["task_id"] == task_id
    assert len(cfg["units"]) == 2
    assert cfg["units"][0]["question_ids"] == ["Q1", "Q2"]

    # 3. 第一次导入：deepseek Q1,Q2 done
    await task_service.import_batch_results(task_id, {
        "meta": {"task_id": task_id, "batch_id": cfg["batch_id"], "run_id": cfg["run_id"]},
        "questions": [],
        "analysis_results": {
            "deepseek": [
                _mk("Q1", "deepseek", "UCloud 很好"), _mk("Q2", "deepseek", "UCloud 不错"),
            ]
        }
    })
    detail = await task_service.build_task_detail(task_id)
    assert detail["coverage"]["deepseek"]["Q1"] == "done"
    assert detail["coverage"]["deepseek"].get("Q3") == "missing"
    assert detail["coverage"]["deepseek"].get("Q4") == "missing"

    # 4. 第二次导入：deepseek 重导 Q1（覆盖）+ kimi Q1,Q2,Q3
    await task_service.import_batch_results(task_id, {
        "meta": {"task_id": task_id, "batch_id": "batch_2", "run_id": "run_2"},
        "questions": [],
        "analysis_results": {
            "deepseek": [_mk("Q1", "deepseek", "UCloud 覆盖更新")],
            "kimi": [_mk("Q1", "kimi", "UCloud"), _mk("Q2", "kimi", "UCloud"), _mk("Q3", "kimi", "UCloud")],
        }
    })
    # 去重覆盖：deepseek Q1 仍只有一条（不累积）
    results = await db.get_task_results(task_id, "deepseek")
    q1_rows = [r for r in results if r["question_id"] == "Q1"]
    assert len(q1_rows) == 1, f"deepseek Q1 应去重为 1 条，实得 {len(q1_rows)}"
    assert q1_rows[0]["raw_content"] == "UCloud 覆盖更新"

    detail = await task_service.build_task_detail(task_id)
    assert detail["coverage"]["kimi"]["Q3"] == "done"
    assert detail["summary"]["done_cells"] == 5  # deepseek Q1,Q2 + kimi Q1,Q2,Q3

    # 5. 评分重算存在
    scores = await db.get_task_scores(task_id)
    assert len(scores) >= 2, f"应有 2 个模型全局评分，实得 {len(scores)}"

    print("✅ PASS: task_service 合并去重 + 矩阵 + 重算")


def _mk(qid, mk, content):
    return {
        "question_id": qid, "model_key": mk, "model_name": mk.upper(),
        "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
        "has_citation": False, "citation_count": 0, "ucloud_recommended": False,
        "recommendation_strength": "none", "sentiment_score": 0.6, "sentiment_label": "positive",
        "position_weight": 0.5, "response_length": len(content), "raw_content": content,
        "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": [],
    }


if __name__ == "__main__":
    asyncio.run(main())
