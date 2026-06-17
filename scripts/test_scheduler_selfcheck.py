"""三级任务调度引擎自检（不真打平台，用 mock 客户端）

验证：
  1. 交错正确性 + 限流退避：3 模型 × 4 题，全部 done；单模型最长连续请求 ≤ max_consecutive。
  2. 单题重试：瞬态错误前 2 次失败、第 3 次成功 → done 且 attempts==3。
  3. 封号退避：返回"请求频率过快"1 次 → 进冷却 → 退回 pending → 重试成功。
  4. 断点续跑：手动标记部分单元 done 后运行，仅补跑 pending，done 不重复。
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from scheduler import EvalScheduler
from task_units import SqliteUnitStore
from webchat_policy import classify_signal


class MockClient:
    """可编程 mock 客户端：按 (model, qid) 给出预设响应序列。"""
    def __init__(self, model_key, script, call_log):
        self.model_key = model_key
        self.script = script
        self.call_log = call_log
        self.name = model_key.upper()
        self.is_configured = True

    async def initialize(self):
        return True

    async def chat(self, question):
        qid = question  # 测试里 question 文本即 qid
        seq = self.script.get((self.model_key, qid), [])
        resp = seq.pop(0) if seq else {"content": f"默认:{qid}", "error": None}
        self.call_log.append((self.model_key, qid))
        return resp

    async def close(self):
        pass


def make_questions(n):
    return [{"id": f"Q{i+1}", "question": f"Q{i+1}", "category": "test",
             "question_type": "direct", "tags": [], "difficulty": "medium"} for i in range(n)]


def make_factory(registry):
    async def fac(mk):
        return registry[mk]
    return fac


def fast_policy(models, **kw):
    base = {"inter_unit_delay": 0.0, "max_consecutive": 99, "burst_cooldown": 0,
            "rate_max": 999, "ban_cooldown_sec": 1, "max_attempts": 3}
    base.update(kw)
    return {m: dict(base) for m in models}


def main():
    tmp = tempfile.mkdtemp()

    # ── 1. 交错 + 限流退避 ──
    store = SqliteUnitStore(os.path.join(tmp, "interleave.db"))
    models = ["a", "b", "c"]
    qs = make_questions(4)
    log = []
    registry = {m: MockClient(m, {}, log) for m in models}
    extra = fast_policy(models, max_consecutive=2, burst_cooldown=0.05)

    async def m1():
        await EvalScheduler("runI", models, qs, store, make_factory(registry),
                            extra_policy=extra).run()
    asyncio.run(m1())
    counts = store.counts("runI")
    assert counts["done"] == 12, counts
    for m in models:
        assert len([u for u in store.list_units("runI", "done") if u.model_key == m]) == 4
    # 单模型最长连续请求 ≤ 2
    max_run = 0; cur = None; run = 0
    for mk, _ in log:
        run = run + 1 if mk == cur else 1
        cur = mk
        max_run = max(max_run, run)
    print(f"   单模型最长连续请求 = {max_run} (上限 2)")
    assert max_run <= 2, f"burst 上限被突破: {max_run}"
    print("✅ PASS: 交错正确性 + 限流退避")

    # ── 2. 单题重试 ──
    s = SqliteUnitStore(os.path.join(tmp, "retry.db"))
    reg = {"a": MockClient("a", {("a", "Q1"): [
        {"content": "", "error": "timeout"},
        {"content": "", "error": "timeout"},
        {"content": "成功回答", "error": None},
    ]}, [])}
    async def m2():
        await EvalScheduler("runR", ["a"], make_questions(1), s, make_factory(reg),
                            extra_policy=fast_policy(["a"], max_attempts=3)).run()
    asyncio.run(m2())
    u = s.get("runR", "a", "Q1")
    assert u.status == "done" and u.attempts == 3 and u.content == "成功回答", (u.status, u.attempts, u.content)
    print("✅ PASS: 单题重试（2 失败 → 第 3 次成功，attempts==3）")

    # ── 3. 封号退避 ──
    s = SqliteUnitStore(os.path.join(tmp, "throttle.db"))
    reg = {"a": MockClient("a", {("a", "Q1"): [
        {"content": "", "error": "请求频率过快，触发限流"},
        {"content": "恢复后回答", "error": None},
    ]}, [])}
    async def m3():
        await EvalScheduler("runT", ["a"], make_questions(1), s, make_factory(reg),
                            extra_policy=fast_policy(["a"], ban_cooldown_sec=0.1, max_attempts=5)).run()
    asyncio.run(m3())
    u = s.get("runT", "a", "Q1")
    assert u.status == "done" and u.content == "恢复后回答", (u.status, u.last_error)
    assert classify_signal("请求频率过快，触发限流") == "throttle"
    print("✅ PASS: 封号退避（throttle → 冷却 → 重试成功）")

    # ── 4. 断点续跑 ──
    s = SqliteUnitStore(os.path.join(tmp, "resume.db"))
    models2 = ["a", "b"]; qs2 = make_questions(3)
    s.expand_units("runRes", models2, [q["id"] for q in qs2], {m: m for m in models2})
    for qid in ("Q1", "Q2"):
        u = s.get("runRes", "a", qid); u.status = "done"; u.content = "旧结果"; u.attempts = 1
        s.upsert(u)
    reg = {m: MockClient(m, {}, []) for m in models2}
    async def m4():
        await EvalScheduler("runRes", models2, qs2, s, make_factory(reg),
                            extra_policy=fast_policy(models2)).run()
    asyncio.run(m4())
    assert s.counts("runRes")["done"] == 6, s.counts("runRes")
    assert s.get("runRes", "a", "Q1").content == "旧结果"
    print("✅ PASS: 断点续跑（done 不重跑，仅补 pending）")

    # ── 5. 每模型独立题区间 ──
    s = SqliteUnitStore(os.path.join(tmp, "permodel.db"))
    models5 = ["a", "b"]
    qs5 = make_questions(4)
    reg = {m: MockClient(m, {}, []) for m in models5}
    pmq = {"a": [qs5[0], qs5[1], qs5[3]],  # a 跑 Q1,Q2,Q4
           "b": [qs5[1], qs5[2]]}           # b 跑 Q2,Q3
    async def m5():
        await EvalScheduler("runP", models5, qs5, s, make_factory(reg),
                            extra_policy=fast_policy(models5),
                            per_model_questions=pmq).run()
    asyncio.run(m5())
    # a 应 done Q1,Q2,Q4；b 应 done Q2,Q3
    a_done = {u.question_id for u in s.list_units("runP", "done") if u.model_key == "a"}
    b_done = {u.question_id for u in s.list_units("runP", "done") if u.model_key == "b"}
    assert a_done == {"Q1", "Q2", "Q4"}, a_done
    assert b_done == {"Q2", "Q3"}, b_done
    assert s.counts("runP")["done"] == 5, s.counts("runP")
    print("✅ PASS: 每模型独立题区间（per_model_questions）")

    print("\n🎉 全部自检通过")


if __name__ == "__main__":
    main()
