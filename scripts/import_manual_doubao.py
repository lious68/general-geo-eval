"""导入 doubao 人工采集的答案，覆盖 task 的 doubao 数据 + 重算评分。

用法: python scripts/import_manual_doubao.py <manual_doubao_xxx.json>

每题用 ResponseAnalyzer.analyze() 分析 answer（从答案文本扫 URL/引用）→
save_task_analysis_result 覆盖旧 doubao 行 → recalculate_task_scores。
"""
import asyncio, os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import database as db
from analyzer import ResponseAnalyzer
from brand_profile import default_brand_profile
from services import task_service
from services.eval_runner import _analysis_to_dict


async def main():
    if len(sys.argv) < 2:
        print("用法: python import_manual_doubao.py <manual_doubao_xxx.json>")
        sys.exit(2)
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    task_id = data["task_id"]
    questions = data["questions"]
    await db.init_db()
    task = await db.get_task(task_id)
    if not task:
        print(f"任务 {task_id} 不存在"); sys.exit(1)
    brand_profile = db.get_brand_profile_by_id(task.get("brand_id") or "ucloud")
    analyzer = ResponseAnalyzer(brand_profile=brand_profile)

    batch_id = f"batch_manual_doubao_{int(time.time())}"
    run_id = f"run_manual_doubao_{int(time.time())}"
    ok = 0; skipped = 0; not_confirmed = 0
    for i, q in enumerate(questions, 1):
        qid = q["question_id"]
        answer = (q.get("answer") or "").strip()
        if not answer:
            print(f"  [{i}/{len(questions)}] {qid}: answer 空，跳过"); skipped += 1; continue
        if not q.get("new_window_confirmed"):
            print(f"  [{i}/{len(questions)}] {qid}: ⚠️ 未确认新开窗口（new_window_confirmed=false）")
            not_confirmed += 1
        ar = analyzer.analyze(qid, "doubao", "豆包", answer, error=None, search_results=None)
        rd = _analysis_to_dict(ar)
        rd["task_id"] = task_id
        rd["batch_id"] = batch_id
        rd["run_id"] = run_id
        await db.save_task_analysis_result(task_id, batch_id, run_id, rd)
        print(f"  [{i}/{len(questions)}] {qid}: {len(answer)}字 mention={ar.ucloud_mentioned} cite={ar.has_citation} rank={ar.ucloud_rank} urls={len(ar.all_cited_urls)}")
        ok += 1

    print(f"\n导入 {ok}/{len(questions)} 题（跳过空 {skipped}，未确认新窗口 {not_confirmed}），重算评分…")
    await task_service.recalculate_task_scores(task_id)
    print("✅ doubao 人工数据已导入并重算评分")


if __name__ == "__main__":
    asyncio.run(main())
