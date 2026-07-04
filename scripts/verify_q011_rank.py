"""验证竞品关键词对称化后 q011 rank 是否修正为 4。

直接用 ResponseAnalyzer 重跑分析(raw_content 从 run json 读), 不碰 DB。
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
sys.stdout.reconfigure(encoding="utf-8") if sys.platform == "win32" else None

from analyzer import ResponseAnalyzer

# 从最新含 q011 的 run 读 doubao q011 raw
run_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "output", "run_20260702_160342_085d6c.json")
d = json.load(open(run_path, encoding="utf-8"))
raw = None
for r in d["analysis_results"]["doubao"]:
    if r.get("question_id") == "q011":
        raw = r.get("raw_content", "")
        break

an = ResponseAnalyzer()
res = an.analyze("q011", "doubao", "豆包", raw, error=None)
print(f"q011 doubao  new rank = {res.ucloud_rank}  (期望 4)")
print(f"  ucloud_first_pos = {res.ucloud_first_position}")
print("  competitor first_pos:")
for c, ms in res.competitor_mentions.items():
    if ms:
        print(f"    {c}: {ms[0].position}  ({ms[0].keyword!r})")
# 完整品牌顺序
allb = [("UCloud", res.ucloud_first_position)] + [(c, ms[0].position) for c, ms in res.competitor_mentions.items() if ms]
allb = [b for b in allb if b[1] is not None]
allb.sort(key=lambda x: x[1])
print("  完整顺序:", " < ".join(f"{b}@{p}" for b, p in allb))
print("  => UCloud 实际第", [b for b,_ in allb].index("UCloud")+1, "名")
assert res.ucloud_rank == 4, f"❌ 期望 rank=4, 实际 {res.ucloud_rank}"
print("✅ q011 rank 修正为 4, 退出 top3")
