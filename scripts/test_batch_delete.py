"""批次删除端点冒烟：建 task+batch+结果，DELETE 删一个批次，确认只删该批次、
其他批次与 task 本身保留，scores 已重算。"""
import asyncio, os, sys, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import database as db


def _mk(qid, mk):
    return {"question_id": qid, "model_key": mk, "model_name": mk,
            "ucloud_mentioned": True, "ucloud_mention_count": 1, "ucloud_rank": 1,
            "has_citation": False, "citation_count": 0, "ucloud_recommended": False,
            "recommendation_strength": "none", "sentiment_score": 0.6, "sentiment_label": "positive",
            "position_weight": 0.5, "response_length": 5, "raw_content": "UCloud",
            "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": []}


def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    asyncio.run(db.init_db())
    asyncio.run(_seed())

    import app as appmod
    appmod.PUBLIC_PATHS = list(appmod.PUBLIC_PATHS) + ["/api/tasks"]
    from routers.auth import require_admin
    async def _noop(): return {"username": "admin", "role": "admin"}
    appmod.app.dependency_overrides[require_admin] = _noop
    from fastapi.testclient import TestClient
    client = TestClient(appmod.app)

    # 建 task + 2 个批次（kimi 跑 Q1/Q2，qwen 跑 Q1/Q2）
    r = client.post("/api/tasks", json={"name": "T", "question_ids": ["Q1", "Q2"]})
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["id"]
    r = client.post(f"/api/tasks/{tid}/batches", json={
        "model_keys": ["kimi"], "per_model_question_ids": {"kimi": ["Q1", "Q2"]}, "delay": 0})
    b1 = r.json()["data"]["batch_id"]
    r = client.post(f"/api/tasks/{tid}/batches", json={
        "model_keys": ["qwen"], "per_model_question_ids": {"qwen": ["Q1", "Q2"]}, "delay": 0})
    b2 = r.json()["data"]["batch_id"]

    # 各导入 2 条结果
    for bid, mk in [(b1, "kimi"), (b2, "qwen")]:
        payload = {"meta": {"task_id": tid, "batch_id": bid, "run_id": f"run_{bid}"},
                   "questions": [], "analysis_results": {mk: [_mk("Q1", mk), _mk("Q2", mk)]}}
        r = client.post(f"/api/tasks/{tid}/batches/{bid}/import-results",
                        files={"file": ("r.json", json.dumps(payload).encode(), "application/json")})
        assert r.status_code == 200, r.text

    # 删前：4 条结果
    assert _count_results(tid) == 4, _count_results(tid)
    assert _count_batches(tid) == 2, _count_batches(tid)

    # 删 b1
    r = client.delete(f"/api/tasks/{tid}/batches/{b1}")
    assert r.status_code == 200, r.text
    # 删后：只剩 b2 的 2 条；b1 行没了；task 还在
    assert _count_results(tid) == 2, f"应剩2条, 实{_count_results(tid)}"
    assert _count_batches(tid) == 1, f"应剩1个批次, 实{_count_batches(tid)}"
    # b2 的 run_id 还在
    conn = sqlite3_conn()
    assert conn.execute("SELECT batch_id FROM analysis_results WHERE task_id=?", (tid,)).fetchall()[0] == (b2,)
    conn.close()
    # 删不存在的批次 → 404
    r = client.delete(f"/api/tasks/{tid}/batches/nope")
    assert r.status_code == 404, r.text
    # scores 仍在（task 级，重算过）
    r = client.get(f"/api/tasks/{tid}/scores")
    assert r.status_code == 200 and len(r.json()["data"]) >= 1, r.text

    print("✅ PASS: 批次删除（只删目标批次，保留 task 与其他批次，scores 重算）")


def _count_results(tid):
    conn = sqlite3_conn()
    n = conn.execute("SELECT count(*) FROM analysis_results WHERE task_id=?", (tid,)).fetchone()[0]
    conn.close(); return n

def _count_batches(tid):
    conn = sqlite3_conn()
    n = conn.execute("SELECT count(*) FROM evaluation_runs WHERE task_id=?", (tid,)).fetchone()[0]
    conn.close(); return n

def sqlite3_conn():
    import sqlite3
    return sqlite3.connect(db.DB_PATH)

async def _seed():
    conn = await db.get_db()
    try:
        for i in (1, 2):
            await conn.execute(
                "INSERT INTO questions (id, category, question_type, question, difficulty, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)", (f"Q{i}", "品牌词", "品牌词", f"问题{i}", "medium"))
        await conn.commit()
    finally:
        await conn.close()


if __name__ == "__main__":
    main()
