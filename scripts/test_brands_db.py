"""brands 表 CRUD + current 自检。"""
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

    # list 含预置 ucloud
    brands = await db.list_brands()
    assert any(b["id"] == "ucloud" for b in brands), "应预置 ucloud"

    # create acme
    acme = derive_from_input("Acme云", "阿克米科技", "https://www.acme-cloud.cn", "云计算")
    created = await db.create_brand("acme", acme)
    assert created["id"] == "acme" and created["brand_name"] == "Acme云"

    # id 冲突
    try:
        await db.create_brand("acme", acme)
        assert False, "重复 id 应抛 ValueError"
    except ValueError:
        pass

    # get
    b = await db.get_brand("acme")
    assert b and b["brand_profile"]["brand_name"] == "Acme云"

    # update
    acme2 = derive_from_input("Acme云2", "阿克米", "https://acme-cloud.cn", "云计算")
    await db.update_brand("acme", acme2)
    b2 = await db.get_brand("acme")
    assert b2["brand_name"] == "Acme云2"

    # current 切换
    await db.set_current_brand_id("acme")
    assert await db.get_current_brand_id() == "acme"

    # delete：无活跃数据可软删
    await db.delete_brand("acme")
    b3 = await db.get_brand("acme")
    assert b3 is None or b3["is_active"] == 0, "删除后应不可见或 is_active=0"

    # 切回 ucloud
    await db.set_current_brand_id("ucloud")
    print("✅ PASS: brands CRUD + current")


if __name__ == "__main__":
    asyncio.run(main())
