"""tasks 路由冒烟：用 TestClient 打 POST/GET/batches/import 全链路。"""
import asyncio
import os
import sys
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db


def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    asyncio.run(db.init_db())
    asyncio.run(_seed())

    # 关闭鉴权中间件对 /api/tasks 的拦截：让中间件认为该路径公开
    import app as appmod
    appmod.PUBLIC_PATHS = list(appmod.PUBLIC_PATHS) + ["/api/tasks"]

    # 绕过 require_admin 依赖（中间件已绕过，route-level 也需要）
    from routers.auth import require_admin
    async def _noop_admin():
        return {"username": "admin", "role": "admin"}
    appmod.app.dependency_overrides[require_admin] = _noop_admin

    from fastapi.testclient import TestClient
    client = TestClient(appmod.app)

    r = client.post("/api/tasks", json={"name": "T", "categories": ["品牌词"]})
    assert r.status_code == 200, r.text
    task_id = r.json()["data"]["id"]

    r = client.get("/api/tasks")
    assert r.status_code == 200 and len(r.json()["data"]) == 1, r.text

    r = client.post(f"/api/tasks/{task_id}/batches", json={
        "model_keys": ["kimi"], "per_model_question_ids": {"kimi": ["Q1", "Q2"]}, "delay": 8})
    assert r.status_code == 200, r.text
    cfg = r.json()["data"]
    assert cfg["version"] == 2 and cfg["task_id"] == task_id, cfg

    payload = {"meta": {"task_id": task_id, "batch_id": cfg["batch_id"], "run_id": cfg["run_id"]},
               "questions": [], "analysis_results": {"kimi": [_mk("Q1", "kimi")]}}
    r = client.post(f"/api/tasks/{task_id}/import-results",
                    files={"file": ("r.json", json.dumps(payload).encode(), "application/json")})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["results_inserted"] == 1, r.text

    r = client.get(f"/api/tasks/{task_id}")
    assert r.json()["data"]["coverage"]["kimi"]["Q1"] == "done", r.text

    r = client.get(f"/api/tasks/{task_id}/scores")
    assert r.status_code == 200 and len(r.json()["data"]) >= 1, r.text
    r = client.get(f"/api/tasks/{task_id}/details")
    assert r.status_code == 200 and len(r.json()["data"]) >= 1, r.text

    print("✅ PASS: /api/tasks 全链路冒烟")


async def _seed():
    conn = await db.get_db()
    try:
        for i in range(1, 5):
            await conn.execute(
                "INSERT INTO questions (id, category, question_type, question, difficulty, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (f"Q{i}", "品牌词" if i <= 2 else "对比词",
                 "品牌词" if i <= 2 else "对比词", f"问题{i}", "medium"))
        await conn.commit()
    finally:
        await conn.close()


def _mk(qid, mk):
    return {"question_id": qid, "model_key": mk, "model_name": mk.upper(),
            "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
            "has_citation": False, "citation_count": 0, "ucloud_recommended": False,
            "recommendation_strength": "none", "sentiment_score": 0.6, "sentiment_label": "positive",
            "position_weight": 0.5, "response_length": 5, "raw_content": "UCloud",
            "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": []}


if __name__ == "__main__":
    main()
