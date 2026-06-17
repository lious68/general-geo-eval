"""v2 配置解析冒烟：构造 v2 配置，验证 main 解析出 per_model_questions + task_meta。
不跑浏览器，只验解析路径（monkeypatch run_local_eval）。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import local_webchat_runner as R


def main():
    cfg = {
        "version": 2, "task_id": "task_x", "task_name": "T", "batch_id": "batch_y",
        "run_id": "run_z", "delay": 8,
        "units": [{"model_key": "kimi", "question_ids": ["Q1", "Q2"]},
                  {"model_key": "deepseek", "question_ids": ["Q1"]}],
        "questions": [{"id": "Q1", "question": "q1", "category": "c", "question_type": "t",
                       "tags": [], "difficulty": "medium"},
                      {"id": "Q2", "question": "q2", "category": "c", "question_type": "t",
                       "tags": [], "difficulty": "medium"}],
    }
    cfg_path = os.path.join(tempfile.mkdtemp(), "task.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    captured = {}
    async def fake_run(**kw):
        captured.update(kw)
    R.run_local_eval = fake_run
    sys.argv = ["runner", "--config", cfg_path, "--headed"]
    R.main()

    assert captured.get("per_model_questions") is not None, "v2 未解析出 per_model_questions"
    assert set(captured["per_model_questions"].keys()) == {"kimi", "deepseek"}
    assert captured["per_model_questions"]["kimi"][0]["id"] == "Q1"
    assert captured["task_meta"] == {"task_id": "task_x", "batch_id": "batch_y"}
    print("✅ PASS: v2 配置解析（per_model_questions + task_meta 透传）")


if __name__ == "__main__":
    main()
