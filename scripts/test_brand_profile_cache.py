"""品牌档案缓存层自检：按 brand_id 缓存 + current 切换 + 显式取。"""
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
from brand_profile import BrandProfile, derive_from_input


async def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    await db.init_db()

    # current 默认 ucloud
    cur_id = await db.get_current_brand_id()
    assert cur_id == "ucloud", f"current 应为 ucloud，实得 {cur_id}"

    # get_brand_profile() 返回 current(ucloud) 档案
    p = db.get_brand_profile()
    assert p.brand_name == "UCloud", f"默认档案应为 UCloud，实得 {p.brand_name}"

    # 新建第二个品牌 acme 并设为 current
    acme = derive_from_input("Acme云", "阿克米科技", "https://www.acme-cloud.cn", "云计算")
    # Task 2 只改缓存层；create_brand 属 Task 3，这里用直接 SQL 插入第二个品牌让测试自洽
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO brands (id, brand_name, company_name, website, industry, brand_profile_json, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ("acme", acme.brand_name, acme.company_name, acme.website, acme.industry, acme.to_json()))
        await conn.commit()
    finally:
        await conn.close()
    await db.refresh_brand_cache()  # 让缓存感知新插入的 acme
    await db.set_current_brand_id("acme")
    assert await db.get_current_brand_id() == "acme"

    # current 切换后 get_brand_profile() 返回 acme
    p2 = db.get_brand_profile()
    assert p2.brand_name == "Acme云", f"切后应为 Acme云，实得 {p2.brand_name}"

    # 显式按 id 取 ucloud（不依赖 current）
    p3 = db.get_brand_profile_by_id("ucloud")
    assert p3.brand_name == "UCloud", f"显式取 ucloud 应为 UCloud，实得 {p3.brand_name}"

    # 不存在的 id fallback default
    p4 = db.get_brand_profile_by_id("not_exist")
    assert p4.brand_name == "UCloud", "不存在的 brand_id 应 fallback UCloud 默认"

    print("✅ PASS: 品牌档案缓存按 brand_id 取 + current 切换")


if __name__ == "__main__":
    asyncio.run(main())
