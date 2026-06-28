"""questions brand_id 隔离自检：题集按品牌过滤 + 软删按品牌。"""
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
from brand_profile import derive_from_input


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # 清除 init_db 导入的默认题（保证隔离测试从空题集开始）
    conn = await db.get_db()
    try:
        await conn.execute("DELETE FROM questions")
        await conn.commit()
    finally:
        await conn.close()

    # 建 acme 品牌
    acme = derive_from_input("Acme云", "阿克米", "https://acme-cloud.cn", "云计算")
    await db.create_brand("acme", acme)

    # ucloud 插 2 题，acme 插 1 题
    await db.upsert_question({"id": "u_q1", "category": "c", "question_type": "品类词",
                              "question": "q", "tags": [], "difficulty": "medium"}, brand_id="ucloud")
    await db.upsert_question({"id": "u_q2", "category": "c", "question_type": "品类词",
                              "question": "q", "tags": [], "difficulty": "medium"}, brand_id="ucloud")
    await db.upsert_question({"id": "a_q1", "category": "c", "question_type": "品类词",
                              "question": "q", "tags": [], "difficulty": "medium"}, brand_id="acme")

    # 按 ucloud 过滤：只见 2 题
    u_qs = await db.get_questions(brand_id="ucloud")
    u_ids = {q["id"] for q in u_qs}
    assert u_ids == {"u_q1", "u_q2"}, f"ucloud 应见 2 题，实得 {u_ids}"

    # 按 acme 过滤：只见 1 题
    a_qs = await db.get_questions(brand_id="acme")
    assert {q["id"] for q in a_qs} == {"a_q1"}, "acme 应见 1 题"

    # deactivate_all_questions 按 brand_id 软删（只软删 ucloud）
    await db.deactivate_all_questions(brand_id="ucloud")
    u_active = await db.get_questions(brand_id="ucloud")
    assert u_active == [], "ucloud 软删后应无 active 题"
    a_active = await db.get_questions(brand_id="acme")
    assert len(a_active) == 1, "acme 题不应被 ucloud 软删影响"

    print("✅ PASS: questions brand_id 隔离")


if __name__ == "__main__":
    asyncio.run(main())
