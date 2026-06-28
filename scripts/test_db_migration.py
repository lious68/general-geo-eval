"""数据库迁移幂等自检：建 tasks 表 + task_id 列 + 唯一索引，重复运行无副作用。"""
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


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")

    await db.init_db()
    # 验证 tasks 表存在
    conn = await db.get_db()
    try:
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        assert (await cur.fetchone()) is not None, "tasks 表未创建"
        for table, col in [("evaluation_runs", "task_id"), ("evaluation_runs", "batch_id"),
                           ("analysis_results", "task_id"), ("analysis_results", "batch_id"),
                           ("geo_scores", "task_id")]:
            cur = await conn.execute(f"PRAGMA table_info({table})")
            cols = [r["name"] for r in await cur.fetchall()]
            assert col in cols, f"{table}.{col} 未添加"
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_ar_task_model_q'")
        assert (await cur.fetchone()) is not None, "唯一索引未创建"
        # brands 表 + brand_id 列 + 预置 ucloud
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='brands'")
        assert (await cur.fetchone()) is not None, "brands 表未创建"
        for table in ["questions", "tasks", "evaluation_runs", "analysis_results", "geo_scores"]:
            cur = await conn.execute(f"PRAGMA table_info({table})")
            cols = [r["name"] for r in await cur.fetchall()]
            assert "brand_id" in cols, f"{table}.brand_id 未添加"
        cur = await conn.execute("SELECT COUNT(*) FROM brands")
        assert (await cur.fetchone())[0] >= 1, "brands 表应预置至少 1 行"
        cur = await conn.execute("SELECT id FROM brands WHERE id='ucloud'")
        assert (await cur.fetchone()) is not None, "未预置 ucloud 品牌"
        cur = await conn.execute("SELECT value FROM app_settings WHERE key='current_brand_id'")
        row = await cur.fetchone()
        assert row and row["value"] == "ucloud", f"current_brand_id 应为 ucloud，实得 {row['value'] if row else None}"
        # 现有 questions 行的 brand_id 默认补为 ucloud（init_db 导入默认题后）
        cur = await conn.execute("SELECT DISTINCT brand_id FROM questions")
        bids = [r["brand_id"] for r in await cur.fetchall()]
        assert bids == ["ucloud"] or bids == [], f"questions.brand_id 应默认 ucloud，实得 {bids}"
    finally:
        await conn.close()

    # 幂等：再跑一次 init_db 不报错
    await db.init_db()
    print("✅ PASS: 迁移幂等（tasks 表 + task_id/batch_id 列 + 唯一索引）")


if __name__ == "__main__":
    asyncio.run(main())
