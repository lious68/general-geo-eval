"""生成 doubao 人工采集模板（分隔符文本格式，直接粘贴原文无需 JSON 转义）。

用法: python scripts/make_manual_doubao_template.py <task_id>
输出: output/manual_doubao_<task_id>.txt

格式：每题一块，以 `# qNNN | 题干` 行开头，下方粘贴 doubao 答案原文（含引用来源），
直到下一个 `# qNNN` 行。new_window 标记：在题头行加 ! 表示已新开窗口。

人工流程：doubao.com 新开对话 → 粘贴题干 → 答完点答案「复制」(含底部引用) →
粘到该题 # 行下方。填完跑 scripts/import_manual_doubao.py。
"""
import asyncio, os, sys
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
        cur = await conn.execute("SELECT id, question, category FROM questions")
        for r in await cur.fetchall():
            qmap[r["id"]] = (r["question"], r["category"])
    finally:
        await conn.close()

    lines = []
    lines.append(f"# doubao 人工采集模板 | task={task_id} | {task.get('name','')}")
    lines.append("# 格式：每题以 `# qNNN | 题干` 行开头（新开过窗口在行首加 ! 即 `#! qNNN | ...`），")
    lines.append("# 下方粘贴 doubao 答案原文（点答案「复制」按钮，含底部引用来源），到下一题 # 行为止。")
    lines.append("# 填完跑: python scripts/import_manual_doubao.py <本文件>")
    lines.append("")
    for qid in qids:
        q, cat = qmap.get(qid, ("", ""))
        lines.append(f"# {qid} | {q}")
        lines.append(f"# 品类: {cat}")
        lines.append("")  # answer 粘这里
    out_path = os.path.join(os.path.dirname(__file__), "..", "output", f"manual_doubao_{task_id}.txt")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 模板已生成: {out_path}")
    print(f"   {len(qids)} 题，每题 # 行下方粘 doubao 答案（含引用来源）")


if __name__ == "__main__":
    asyncio.run(main())
