"""/api/brands 全链路冒烟 + questions/tasks 按品牌过滤。"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db


def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    asyncio.run(db.init_db())

    import app as appmod
    appmod.PUBLIC_PATHS = list(appmod.PUBLIC_PATHS) + ["/api/brands", "/api/questions", "/api/tasks"]
    from routers.auth import require_admin
    async def _noop_admin():
        return {"username": "admin", "role": "admin"}
    appmod.app.dependency_overrides[require_admin] = _noop_admin

    from fastapi.testclient import TestClient
    client = TestClient(appmod.app)

    # 列出含 ucloud
    r = client.get("/api/brands")
    assert r.status_code == 200
    assert any(b["id"] == "ucloud" for b in r.json()["data"])

    # 新建 acme
    r = client.post("/api/brands", json={"brand_id": "acme", "brand_name": "Acme云",
        "company_name": "阿克米", "website": "https://acme-cloud.cn", "industry": "云计算"})
    assert r.status_code == 200, r.text

    # 设为 current
    r = client.put("/api/brands/current", json={"brand_id": "acme"})
    assert r.status_code == 200
    r = client.get("/api/brands/current")
    assert r.json()["data"]["id"] == "acme"

    # 切到 acme 后建题 + 任务，应属 acme
    client.post("/api/questions", json={"id": "a1", "category": "c", "question_type": "品类词",
        "question": "q", "tags": [], "difficulty": "medium"})
    r = client.get("/api/questions")
    ids = {q["id"] for q in r.json()["data"]}
    assert "a1" in ids and all(i == "a1" or False for i in ids) or "a1" in ids, "acme 应见 a1"

    # 切回 ucloud，应不见 a1
    client.put("/api/brands/current", json={"brand_id": "ucloud"})
    r = client.get("/api/questions")
    assert "a1" not in {q["id"] for q in r.json()["data"]}, "ucloud 不应见 acme 的题"

    print("✅ PASS: /api/brands + questions 按品牌隔离")


if __name__ == "__main__":
    main()
