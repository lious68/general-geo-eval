import pytest
import database as db


@pytest.mark.asyncio
async def test_get_run_by_batch_id_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    await db.init_db()
    run_id = "run_test1"
    batch_id = "batch_test1"
    await db.add_task_batch(run_id=run_id, task_id="task_test1", batch_id=batch_id,
                            name="t", model_keys=["kimi"], question_ids=["q1"],
                            per_model={"kimi": ["q1"]}, config={})
    row = await db.get_run_by_batch_id(batch_id)
    assert row is not None
    assert row["id"] == run_id
    assert await db.get_run_by_batch_id("nope") is None


@pytest.mark.asyncio
async def test_list_pending_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    await db.init_db()
    await db.add_task_batch(run_id="r1", task_id="t1", batch_id="b1",
                            name="t", model_keys=["kimi"], question_ids=["q1"],
                            per_model={"kimi": ["q1"]}, config={})
    # b1 状态默认 config_downloaded
    pending = await db.list_pending_batches()
    ids = [p["batch_id"] for p in pending]
    assert "b1" in ids
