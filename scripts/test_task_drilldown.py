"""task 级问题下钻自检：/results/0/question-drilldown?task_id=&model_key=
大任务+模型 → 每题一行（跨批次去重），run 模式行为保持。

用 TestClient：建 task → 导入两个批次（同模型同题，验证只留一行；不同题验证聚合）→
GET 下钻断言 total_questions/题目文本/自然问题过滤。
"""
import asyncio
import os
import sys
import io
import tempfile
import json

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db


def main():
    tmp = tempfile.mkdtemp()
    db.DB_PATH = os.path.join(tmp, "geo.db")
    asyncio.run(db.init_db())
    asyncio.run(_seed())

    import app as appmod
    appmod.PUBLIC_PATHS = list(appmod.PUBLIC_PATHS) + ["/api/tasks", "/api/results"]
    from routers.auth import require_admin

    async def _noop_admin():
        return {"username": "admin", "role": "admin"}
    appmod.app.dependency_overrides[require_admin] = _noop_admin

    from fastapi.testclient import TestClient
    client = TestClient(appmod.app)

    # 建 task，题集 Q1..Q4（引导型+对比词）
    r = client.post("/api/tasks", json={"name": "T", "categories": ["引导型", "对比词"]})
    assert r.status_code == 200, r.text
    task_id = r.json()["data"]["id"]

    # 批次 A：kimi 答 Q1（提及）
    r = client.post(f"/api/tasks/{task_id}/batches", json={
        "model_keys": ["kimi"], "per_model_question_ids": {"kimi": ["Q1"]}, "delay": 8})
    assert r.status_code == 200, r.text
    cfgA = r.json()["data"]
    payloadA = {"meta": {"task_id": task_id, "batch_id": cfgA["batch_id"], "run_id": cfgA["run_id"]},
                "questions": [], "analysis_results": {"kimi": [_mk("Q1", "kimi", mentioned=True)]}}
    r = client.post(f"/api/tasks/{task_id}/batches/{cfgA['batch_id']}/import-results",
                    files={"file": ("a.json", json.dumps(payloadA).encode(), "application/json")})
    assert r.status_code == 200 and r.json()["data"]["results_inserted"] == 1, r.text

    # 批次 B：kimi 答 Q1（再次导入，应覆盖只留一行）+ Q2
    r = client.post(f"/api/tasks/{task_id}/batches", json={
        "model_keys": ["kimi"], "per_model_question_ids": {"kimi": ["Q1", "Q2"]}, "delay": 8})
    assert r.status_code == 200, r.text
    cfgB = r.json()["data"]
    payloadB = {"meta": {"task_id": task_id, "batch_id": cfgB["batch_id"], "run_id": cfgB["run_id"]},
                "questions": [],
                "analysis_results": {"kimi": [_mk("Q1", "kimi", mentioned=True),
                                              _mk("Q2", "kimi", mentioned=True)]}}
    r = client.post(f"/api/tasks/{task_id}/batches/{cfgB['batch_id']}/import-results",
                    files={"file": ("b.json", json.dumps(payloadB).encode(), "application/json")})
    assert r.status_code == 200 and r.json()["data"]["results_inserted"] == 2, r.text

    # 下钻：kimi，大任务聚合 → 应 2 题（Q1 去重后单行 + Q2），不是 3
    r = client.get(f"/api/results/0/question-drilldown?model_key=kimi&task_id={task_id}")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["total_questions"] == 2, f"跨批次应去重为 2 题，实际 {data['total_questions']}: {data}"
    qids = sorted(q["question_id"] for q in data["questions"])
    assert qids == ["Q1", "Q2"], qids
    # 题目原文来自 questions 表 JOIN
    q1 = next(q for q in data["questions"] if q["question_id"] == "Q1")
    assert q1["question_text"] == "问题1", q1["question_text"]
    # Q1 是品牌词引导型 → 非自然 → 提及率显示 "-"
    assert q1["is_natural"] is False, "品牌词题应为非自然"
    assert q1["metrics"]["coverage"]["value"] == "-", q1["metrics"]["coverage"]["value"]
    # raw_content 透传
    assert "UCloud" in q1["response_content"], q1["response_content"]
    # 原始标志字段（供前端标签展示，与批次视图一致）：
    # Q1 是引导型 → metrics.coverage.numerator 被强制 0，但 ucloud_mentioned 仍为 True，
    # 标签得用原始字段才能在引导型题上正确显示"提及"。
    assert q1["ucloud_mentioned"] is True, "Q1 原始 ucloud_mentioned 应为 True"
    assert q1["ucloud_recommended"] is True, "Q1 原始 ucloud_recommended 应为 True"
    assert q1["citation_count"] == 0, "Q1 citation_count 应为 0"
    assert q1["has_citation"] is False, "Q1 has_citation 应为 False"
    # 关键：引导型题 metrics.coverage.numerator=0（强制），但原始 ucloud_mentioned=True
    assert q1["metrics"]["coverage"]["numerator"] == 0, "引导型题 coverage.numerator 应被强制 0"
    assert q1["ucloud_mentioned"] is True, "引导型题原始 ucloud_mentioned 仍应为 True（标签用此）"

    # task 模式不校验 run 存在性：run_id=0 不报 404
    assert r.status_code == 200

    # 不存在的模型 → 空数组，不报错
    r = client.get(f"/api/results/0/question-drilldown?model_key=ghost&task_id={task_id}")
    assert r.status_code == 200 and r.json()["data"]["total_questions"] == 0, r.text

    print("✅ PASS: task 级问题下钻（跨批次去重=2题、题目原文JOIN、自然问题过滤、run_id占位不校验、空模型=0）")


async def _seed():
    conn = await db.get_db()
    try:
        # Q1=引导型（非自然，coverage 应显示 "-"）；Q2=对比词自然题；Q3/Q4 备用
        cats = {"Q1": "引导型", "Q2": "对比词", "Q3": "对比词", "Q4": "对比词"}
        for i in range(1, 5):
            qid = f"Q{i}"
            await conn.execute(
                "INSERT INTO questions (id, category, question_type, question, difficulty, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (qid, cats[qid], cats[qid], f"问题{i}", "medium"))
        await conn.commit()
    finally:
        await conn.close()


def _mk(qid, mk, mentioned=True):
    return {"question_id": qid, "model_key": mk, "model_name": mk.upper(),
            "ucloud_mentioned": mentioned, "ucloud_mention_count": 1 if mentioned else 0,
            "ucloud_rank": 1 if mentioned else None,
            "has_citation": False, "citation_count": 0,
            "ucloud_recommended": mentioned, "recommendation_strength": "strong" if mentioned else "none",
            "sentiment_score": 0.6, "sentiment_label": "positive",
            "position_weight": 0.5, "response_length": 5, "raw_content": "UCloud 是云服务商",
            "competitor_mentions": {}, "error_message": None, "citations": [], "all_cited_urls": []}


if __name__ == "__main__":
    main()
