"""用 doubao API 模式（无状态）重跑 task 的所有题，覆盖 WebChat 污染数据。

每题独立 API 调用 → 无会话隔离问题（彻底治串题）。复用 _create_model_client
（读 DB 的 api_key_doubao/base_url_doubao/model_doubao）+ ResponseAnalyzer。

前置：doubao 的 DB 设置已配成 ModelVerse 中转（api_key_doubao=<ModelVerse key>,
base_url_doubao=https://api.modelverse.cn/v1, model_doubao=ByteDance/doubao-1-5-pro-32k-250115）。

用法: python scripts/run_doubao_api_task.py <task_id>
"""
import asyncio, os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import database as db
from model_clients import ModelClient
from analyzer import ResponseAnalyzer
from brand_profile import default_brand_profile
from services import task_service
from services.eval_runner import _create_model_client, _analysis_to_dict


async def main():
    if len(sys.argv) < 2:
        print("用法: python run_doubao_api_task.py <task_id>")
        sys.exit(2)
    task_id = sys.argv[1]
    await db.init_db()
    task = await db.get_task(task_id)
    if not task:
        print(f"任务 {task_id} 不存在"); sys.exit(1)
    qids = task["question_ids"]
    print(f"任务 {task_id}（{task['name']}）：{len(qids)} 题")

    # 取题目原文 + 品类
    conn = await db.get_db()
    qmap = {}
    try:
        cur = await conn.execute("SELECT id, question, category, question_type FROM questions")
        for r in await cur.fetchall():
            qmap[r["id"]] = {"question": r["question"], "category": r["category"], "type": r["question_type"]}
    finally:
        await conn.close()

    # doubao API 客户端（走 DB 配置，应为 ModelVerse 中转）
    client = await _create_model_client("doubao", 0.7)
    if not client or not getattr(client, "is_configured", False):
        print("❌ doubao API 未配置：先在 DB 设 api_key_doubao/base_url_doubao/model_doubao（ModelVerse）")
        sys.exit(1)
    print(f"doubao 客户端就绪: base_url={client.config.get('base_url')} model={client.config.get('model')}")

    brand_profile = db.get_brand_profile_by_id(task.get("brand_id") or "ucloud")
    analyzer = ResponseAnalyzer(brand_profile=brand_profile)

    # 新批次承载本次 API 结果（导入时按 (task,model,question) 覆盖旧 doubao 行）
    batch_id = f"batch_api_doubao_{int(time.time())}"
    run_id = f"run_api_doubao_{int(time.time())}"

    ok = 0
    for i, qid in enumerate(qids, 1):
        q = qmap.get(qid, {})
        question_text = q.get("question", "")
        if not question_text:
            print(f"  [{i}/{len(qids)}] {qid}: 无题目原文，跳过"); continue
        # API 调用（enable_search；ModelVerse 不透传则无 citations，但无串题）
        try:
            resp = client.chat(question_text, enable_search=True)
        except Exception as e:
            print(f"  [{i}/{len(qids)}] {qid}: API 异常 {e}")
            resp = {"content": "", "error": str(e), "search_results": None}
        content = resp.get("content", "") or ""
        error = resp.get("error")
        search_results = resp.get("search_results")
        # 分析（复用 analyzer，API 搜索引用走 _incorporate_search_results）
        ar = analyzer.analyze(qid, "doubao", "豆包", content, error, search_results=search_results)
        rd = _analysis_to_dict(ar)
        rd["task_id"] = task_id
        rd["batch_id"] = batch_id
        rd["run_id"] = run_id
        await db.save_task_analysis_result(task_id, batch_id, run_id, rd)
        mlen = len(content)
        print(f"  [{i}/{len(qids)}] {qid}: {mlen}字 mention={ar.ucloud_mentioned} cite={ar.has_citation} rank={ar.ucloud_rank}")
        ok += 1
        await asyncio.sleep(1)  # 轻度限流

    print(f"\n完成 {ok}/{len(qids)} 题，重算评分…")
    await task_service.recalculate_task_scores(task_id)
    print("✅ doubao API 结果已导入并重算评分")


if __name__ == "__main__":
    asyncio.run(main())
