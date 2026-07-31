"""生成 doubao 人工采集模板 JSON。

用法: python scripts/make_manual_doubao_template.py <task_id>
输出: output/manual_doubao_<task_id>.json

人工流程：在 doubao.com 每题新开对话 → 粘贴 question → 等 doubao 答完
→ 点答案「复制」按钮（含底部引用来源）→ 粘进对应 question 的 "answer" 字段。
填完跑 scripts/import_manual_doubao.py 导入。
"""
import asyncio, os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import database as db


async def main():
    if len(sys.argv) < 2:
        print("用法: python make_manual_doubao_template.py <task_id>")
        sys.exit(2)
    task_id = sys.argv[1]
    await db.init_db()
    task = await db.get_task(task_id)
    if not task:
        print(f"任务 {task_id} 不存在"); sys.exit(1)
    qids = task["question_ids"]
    conn = await db.get_db()
    qmap = {}
    try:
        cur = await conn.execute("SELECT id, question, category, question_type FROM questions")
        for r in await cur.fetchall():
            qmap[r["id"]] = {"question": r["question"], "category": r["category"], "type": r["question_type"]}
    finally:
        await conn.close()

    questions = []
    for qid in qids:
        q = qmap.get(qid, {})
        questions.append({
            "question_id": qid,
            "question": q.get("question", ""),
            "category": q.get("category", ""),
            "answer": "",  # ← 人工填写：doubao 复制按钮的完整答案（含引用来源）
            "new_window_confirmed": False,  # ← 人工确认：该题已新开对话（防串题）
        })

    out = {
        "task_id": task_id,
        "task_name": task.get("name", ""),
        "model_key": "doubao",
        "_说明": "每题在 doubao.com 新开对话粘贴 question，答完点答案「复制」(含底部引用来源)粘进 answer。new_window_confirmed 设 true 确认新开过窗口。填完跑 import_manual_doubao.py。",
        "questions": questions,
    }
    out_path = os.path.join(os.path.dirname(__file__), "..", "output", f"manual_doubao_{task_id}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"✅ 模板已生成: {out_path}")
    print(f"   {len(questions)} 题，逐题填 answer 字段（doubao 复制按钮含引用来源）")


if __name__ == "__main__":
    asyncio.run(main())
