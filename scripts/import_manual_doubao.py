"""导入 doubao 人工采集（分隔符文本格式），覆盖 task 的 doubao 数据 + 重算。

用法: python scripts/import_manual_doubao.py <manual_doubao_xxx.txt>

格式：每题 `# qNNN | 题干` 行开头（新开过窗口行首加 !），下方是 doubao 答案原文
（含引用来源），到下一题 # 行为止。空答案跳过。
"""
import asyncio, os, sys, re, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
import database as db
from analyzer import ResponseAnalyzer
from brand_profile import default_brand_profile
from services import task_service
from services.eval_runner import _analysis_to_dict


def parse_manual(path):
    """解析分隔符文本：返回 [(qid, question, new_window_confirmed, answer), ...]"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 找所有题头行：`# qNNN | 题干` 或 `#! qNNN | 题干`
    heads = []
    for m in re.finditer(r"(?m)^(#!?)\s+(q\d+)\s*\|(.*)$", text):
        heads.append((m.start(), m.end(), m.group(1), m.group(2), m.group(3).strip()))
    items = []
    for i, (hstart, hend, mark, qid, qtext) in enumerate(heads):
        # body = 题头行结束 到 下一题头开始（或文件末）
        body_start = hend
        body_end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        body = text[body_start:body_end]
        # 去掉本题块内的注释行（# 开头）+ 首尾空白
        body_lines = [ln for ln in body.split("\n") if not ln.strip().startswith("#")]
        answer = "\n".join(body_lines).strip()
        new_win = "!" in mark
        items.append((qid, qtext, new_win, answer))
    return items


async def main():
    if len(sys.argv) < 2:
        print("用法: python import_manual_doubao.py <manual_doubao_xxx.txt>")
        sys.exit(2)
    path = sys.argv[1]
    # task_id 从文件名或内容推断：先尝试问 DB 第一个题
    items = parse_manual(path)
    if not items:
        print("未解析到任何题（检查格式：每题 `# qNNN | 题干` 行）"); sys.exit(1)
    await db.init_db()
    # 找 task_id：取第一个 qid 所属 task
    qid0 = items[0][0]
    conn = await db.get_db()
    task_id = None
    try:
        cur = await conn.execute("SELECT task_id FROM analysis_results WHERE question_id=? LIMIT 1", (qid0,))
        row = await cur.fetchone()
        if row:
            task_id = row["task_id"]
    finally:
        await conn.close()
    if not task_id:
        print(f"无法确定 task_id（题 {qid0} 不在任何任务里）"); sys.exit(1)
    task = await db.get_task(task_id)
    brand_profile = db.get_brand_profile_by_id(task.get("brand_id") or "ucloud")
    analyzer = ResponseAnalyzer(brand_profile=brand_profile)

    batch_id = f"batch_manual_doubao_{int(time.time())}"
    run_id = f"run_manual_doubao_{int(time.time())}"
    ok = 0; skipped = 0; not_confirmed = 0
    for i, (qid, qtext, new_win, answer) in enumerate(items, 1):
        if not answer:
            print(f"  [{i}/{len(items)}] {qid}: 空，跳过"); skipped += 1; continue
        if not new_win:
            print(f"  [{i}/{len(items)}] {qid}: ⚠️ 未标 !（未确认新开窗口）")
            not_confirmed += 1
        ar = analyzer.analyze(qid, "doubao", "豆包", answer, error=None, search_results=None)
        rd = _analysis_to_dict(ar)
        rd["task_id"] = task_id
        rd["batch_id"] = batch_id
        rd["run_id"] = run_id
        await db.save_task_analysis_result(task_id, batch_id, run_id, rd)
        print(f"  [{i}/{len(items)}] {qid}: {len(answer)}字 mention={ar.ucloud_mentioned} cite={ar.has_citation} rank={ar.ucloud_rank} urls={len(ar.all_cited_urls)}")
        ok += 1

    print(f"\n导入 {ok}/{len(items)} 题（跳过空 {skipped}，未确认新窗口 {not_confirmed}），重算评分…")
    await task_service.recalculate_task_scores(task_id)
    print(f"✅ doubao 人工数据已导入 task {task_id} 并重算评分")


if __name__ == "__main__":
    asyncio.run(main())
