"""WebChat 结果质量检查器 — 跑完 webchat 后检查抓取质量

用法:
    python scripts/check_webchat_results.py output/run_XXX.json
    python scripts/check_webchat_results.py output/run_XXX.json --verbose
    python scripts/check_webchat_results.py output/run_XXX.json --report output/check_XXX.json

推荐用法: runner 跑完 [5/5] 导出结果 后, 紧接着跑本检查器, 坏题立刻可见,
再决定是否导入/重跑——不用等人工扫 raw_content。

检查 6 类质量问题(基于已修 bug 的真实形态), 每题命中其一即标坏:
  ERROR              error_message 非空 或 raw 为空 (runner 异常/未抓到)
  EMPTY_ECHO 空回声  raw ≈ 题干本身 (抓到 user 题干回显, 豆包 77d0544)
  CROSS_QUESTION 串题 raw 首行 == 另一道题的题干 (抓到上一题残留气泡, 豆包 77d0544)
  NOISE 首页噪声     raw 前200字含首页推荐流标记且<400字 (豆包抓首页流, 77d0544)
  SEARCH_PANEL_TRUNC  kimi 专属: raw 含"搜索网页"+"个结果"且<150字 (kimi 34ecfca)
  TOO_SHORT 过短     <120字且不含UCloud词+不含搜索元数据 (慢启动截断/答非所问兜底)

退出码: 有坏题→1 (便于 CI/脚本串联); 无坏题→0。
报告默认落 output/check_{run_id}.json。
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter

# Windows 控制台默认 GBK, 中文/emoji 会崩, 切 UTF-8
if sys.platform == "win32" and sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass

# 判定逻辑与后端接口共用同一份, 避免双份漂移
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
from webchat_quality import classify, type_label_cn  # noqa: E402


def load_run(path):
    """读 run json, 返回 (meta, questions_map, analysis_results)。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    meta = data.get("meta", {})
    questions = data.get("questions", [])
    qmap = {q.get("id", ""): (q.get("question", "") or "").strip() for q in questions}
    ar = data.get("analysis_results", {})
    return meta, qmap, ar


def check_run(path, verbose=False, report_path=None):
    """检查一个 run json, 打印报告 + 落盘, 返回坏题数。"""
    meta, qmap, ar = load_run(path)
    run_id = meta.get("run_id", os.path.basename(path))

    all_bad = []  # [{model, qid, type, len, head, detail}]
    by_model = {}  # {mk: {"total":, "bad":, "types": Counter}}

    for mk, results in ar.items():
        total = len(results)
        bad = []
        types = Counter()
        for r in sorted(results, key=lambda x: x.get("question_id", "")):
            qid = r.get("question_id", "")
            raw = r.get("raw_content", "") or ""
            err = r.get("error_message", "") or ""
            qtext = qmap.get(qid, "")
            label, detail = classify(qid, raw, err, qtext, qmap, mk)
            n = len(raw.strip())
            head = raw[:34].replace("\n", " ")
            if label != "OK":
                bad.append({"qid": qid, "type": label, "len": n, "head": head, "detail": detail})
                types[label] += 1
            elif verbose:
                print(f"  {mk:8} {qid:5} len={n:6} OK              {qtext[:24]:26} | {head}")
        by_model[mk] = {"total": total, "bad": len(bad), "types": dict(types)}
        all_bad.extend({"model": mk, **b} for b in bad)

    # 打印坏题明细
    SEP = "=" * 100
    print(f"\n{SEP}")
    print(f"  WebChat 结果质量检查 — {run_id}")
    print(f"  源文件: {path}")
    print(SEP)

    if not all_bad:
        print("  ✅ 未发现坏题")
    else:
        print(f"  ⚠️ 发现 {len(all_bad)} 个坏题:\n")
        print(f"  {'模型':8} {'qid':5} {'len':>6}  {'类型':20} {'题干':24} | head")
        print("  " + "-" * 96)
        # 按模型分组打印
        for mk in ar:
            mk_bad = [b for b in all_bad if b["model"] == mk]
            if not mk_bad:
                continue
            for b in mk_bad:
                qtext = qmap.get(b["qid"], "")[:24]
                print(f"  {mk:8} {b['qid']:5} {b['len']:>6}  {b['type']:20} {qtext:24} | {b['head']}")
        print()

    # 总览
    print(f"  {'模型':8} {'总数':>4} {'坏题':>4}  类型分布")
    print("  " + "-" * 50)
    grand_total = 0
    grand_bad = 0
    for mk, info in by_model.items():
        grand_total += info["total"]
        grand_bad += info["bad"]
        t = info["types"]
        print(f"  {mk:8} {info['total']:>4} {info['bad']:>4}  {t if t else '—'}")
    print("  " + "-" * 50)
    print(f"  {'合计':8} {grand_total:>4} {grand_bad:>4}")
    print(SEP)

    # 落盘报告
    if report_path is None:
        report_path = os.path.join(
            os.path.dirname(os.path.abspath(path)),
            f"check_{run_id}.json",
        )
    report = {
        "run_id": run_id,
        "source": path,
        "total": grand_total,
        "bad_count": grand_bad,
        "by_model": {mk: {"total": v["total"], "bad": v["bad"], "types": v["types"]}
                     for mk, v in by_model.items()},
        "bad": all_bad,
    }
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"  报告已保存: {report_path}")
    except OSError as e:
        print(f"  ⚠️ 报告保存失败: {e}")

    return grand_bad


def main():
    parser = argparse.ArgumentParser(
        description="检查 WebChat run json 的抓取质量(空回声/串题/首页噪声/搜索面板截断/过短)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 检查单个 run
  python scripts/check_webchat_results.py output/run_XXX.json

  # 连 OK 题也打印明细
  python scripts/check_webchat_results.py output/run_XXX.json --verbose

  # 列出所有 run 并选择(不传文件路径即进选择菜单)
  python scripts/check_webchat_results.py

  # 检查最近一个 run(快速)
  python scripts/check_webchat_results.py --latest
        """,
    )
    parser.add_argument("run_json", nargs="?", help="runner 产物 output/run_*.json 路径(不传则进选择菜单)")
    parser.add_argument("--verbose", action="store_true", help="连 OK 题也打印明细")
    parser.add_argument("--report", help="报告另存路径(默认 output/check_{run_id}.json)")
    parser.add_argument("--latest", action="store_true", help="直接检查最近一个 run(按修改时间)")
    args = parser.parse_args()

    run_path = args.run_json

    # 无路径: 进选择菜单(列出 output/run_*.json, 按修改时间倒序)
    if not run_path:
        run_path = _pick_run_interactive(args.latest)
        if not run_path:
            sys.exit(2)

    if not os.path.isfile(run_path):
        print(f"❌ 文件不存在: {run_path}")
        sys.exit(2)

    bad_count = check_run(run_path, verbose=args.verbose, report_path=args.report)
    sys.exit(1 if bad_count > 0 else 0)


def _pick_run_interactive(latest: bool) -> str:
    """列出 output/run_*.json(按修改时间倒序), 交互选择或 --latest 直选第一个。"""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    runs = sorted(
        glob.glob(os.path.join(output_dir, "run_*.json")),
        key=os.path.getmtime,
        reverse=True,
    )
    # 过滤掉 check_*.json 报告(已排除, 因 glob 是 run_*)和极小文件
    runs = [r for r in runs if os.path.getsize(r) > 200]

    if not runs:
        print("❌ output/ 下没有 run_*.json 文件")
        return ""

    if latest:
        return runs[0]

    print("\n📂 output/ 下的 run 文件(按修改时间倒序, 最近在上):\n")
    for i, r in enumerate(runs[:20], 1):  # 只列最近 20 个
        mtime = os.path.getmtime(r)
        from datetime import datetime
        ts = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
        size_kb = os.path.getsize(r) / 1024
        name = os.path.basename(r)
        # 读 meta 取模型/题数概览
        try:
            with open(r, encoding="utf-8") as f:
                d = json.load(f)
            meta = d.get("meta", {})
            mks = ",".join(meta.get("model_keys", [])) or "?"
            nq = meta.get("total_questions", "?")
            print(f"  {i:2}. {name}  ({ts}, {size_kb:.1f}KB, {mks}, {nq}题)")
        except Exception:
            print(f"  {i:2}. {name}  ({ts}, {size_kb:.1f}KB, <读取出错>)")
    if len(runs) > 20:
        print(f"  ... 还有 {len(runs) - 20} 个更早的 run")

    print()
    choice = input(f"  选择编号 [1=最近, 直接回车=1, q=退出]: ").strip().lower()
    if choice in ("q", "quit", "exit"):
        return ""
    if not choice:
        return runs[0]
    try:
        idx = int(choice) - 1
        if 0 <= idx < min(len(runs), 20):
            return runs[idx]
    except ValueError:
        pass
    print("  无效选择")
    return ""


if __name__ == "__main__":
    main()
