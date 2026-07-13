"""一键验证：把 output/run_20260630_175142_b5d763.json (40题×5模型) 导入主库为一个任务，
供「行动计划」页验证用。可重复运行（按 task_id 覆盖）。"""
import asyncio, os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import database as db
from services import task_service

RUN_JSON = os.path.join(os.path.dirname(__file__), "..", "output", "run_20260630_175142_b5d763.json")
TASK_NAME = "验证-40题5模型(0730)"

async def main():
    d = json.load(open(RUN_JSON, encoding="utf-8"))
    qids = sorted({q["id"] for q in d["questions"]}, key=lambda x: (len(x), x))
    print(f"题数: {len(qids)}  模型: {list(d['analysis_results'].keys())}")

    # 找是否已有同名任务（重复运行覆盖）
    existing = None
    for t in await task_service.build_task_list_summary():
        if t.get("name") == TASK_NAME:
            existing = t; break
    if existing:
        task_id = existing["id"]
        print(f"复用已有任务: {task_id}")
    else:
        task = await task_service.create_task_with_questions(TASK_NAME, qids, None, "ucloud")
        task_id = task["id"]
        print(f"新建任务: {task_id}")

    # 建批次配置 + 导入
    cfg = await task_service.create_batch_config(
        task_id, list(d["analysis_results"].keys()),
        {mk: qids for mk in d["analysis_results"]}, 0)
    print(f"批次: {cfg['batch_id']}")

    payload = {"meta": {"task_id": task_id, "batch_id": cfg["batch_id"], "run_id": cfg["run_id"]},
               "questions": [], "analysis_results": d["analysis_results"]}
    res = await task_service.import_batch_results(task_id, payload, cfg["batch_id"])
    print(f"导入结果条数: {res['results_inserted']}")
    print()
    print("=" * 60)
    print(f"任务ID: {task_id}")
    print(f"行动计划页 URL: /action-plan?task_id={task_id}")
    print(f"行动计划 API:   curl 'http://localhost:8000/api/results/0/action-plan?task_id={task_id}'")
    print("=" * 60)

asyncio.run(main())
