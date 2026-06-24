"""
本地 Playwright WebChat runner — 用于在本地运行无法通过 API 调用的模型评测

用法:
    python scripts/local_webchat_runner.py --models kimi ernie --questions all --output results.json

说明:
    - 使用 core/web_chat_clients.py 中的 Playwright 客户端
    - 使用 core/analyzer.py 中的 ResponseAnalyzer 分析响应
    - 输出格式与服务端 analysis_results + geo_scores 完全一致
    - 生成的 JSON 文件可通过前端「上传本地结果」功能导入服务器
"""
import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

# Windows 控制台默认 GBK 编码，切换为 UTF-8 避免 emoji 报错
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ── 常量 ──
SEP = "=" * 72
MODEL_NAMES = {
    "deepseek": "DeepSeek",
    "ernie": "文心一言",
    "doubao": "豆包",
    "kimi": "Kimi",
    "qwen": "千问",
}

# 本地任务单元库 + 清单目录（断点续跑用）
LOCAL_RUNS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "local_runs")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")


def _setup_headed_mode(headed: bool):
    """控制浏览器是否显示窗口。

    WebChatClientBase.initialize() 检查 DISPLAY 环境变量：
    - 有 DISPLAY → headed（显示窗口）
    - 无 DISPLAY → headless（后台运行）
    Windows 默认无 DISPLAY，所以需要手动设置。
    """
    if headed:
        os.environ["DISPLAY"] = ":0"
        print("  🖥️  浏览器窗口模式已启用（能看到浏览器窗口）")
    else:
        print("  🌑 后台模式（不显示浏览器窗口）")


# 添加项目路径（必须在设置环境变量之后，因为 import 时会初始化客户端）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from web_chat_clients import create_web_chat_client
from analyzer import ResponseAnalyzer
from metrics import MetricsCalculator
from analyzer import AnalysisResult
from brand_profile import BrandProfile, default_brand_profile
from database import get_questions as db_get_questions
from scheduler import EvalScheduler
from task_units import SqliteUnitStore
from webchat_policy import get_model_policy
from web_chat_auth import has_auth_state, save_auth_state


def _analysis_to_dict(a) -> Dict:
    """AnalysisResult → dict (与 eval_runner._analysis_to_dict 一致)"""
    return {
        "question_id": a.question_id,
        "model_key": a.model_key,
        "model_name": a.model_name,
        "ucloud_mentioned": a.ucloud_mentioned,
        "ucloud_mention_count": a.ucloud_mention_count,
        "ucloud_rank": a.ucloud_rank,
        "has_citation": a.has_citation,
        "citation_count": a.citation_count,
        "ucloud_recommended": a.ucloud_recommended,
        "recommendation_strength": a.ucloud_recommendation_strength,
        "sentiment_score": a.sentiment_score,
        "sentiment_label": a.sentiment_label,
        "position_weight": a.position_weight,
        "response_length": a.response_length,
        "raw_content": a.raw_content,
        "competitor_mentions": {k: [{"keyword": m.keyword, "position": m.position} for m in v]
                                for k, v in a.competitor_mentions.items()},
        "citations": [{"citation_type": c.citation_type, "content": c.content,
                        "position": c.position, "source_channel": c.source_channel,
                        "is_ucloud": c.is_ucloud}
                       for c in a.citations],
        "all_cited_urls": [{"citation_type": c.citation_type, "content": c.content,
                            "position": c.position, "source_channel": c.source_channel,
                            "is_ucloud": c.is_ucloud}
                           for c in a.all_cited_urls],
        "error_message": a.error_message,
    }


def _empty_result(question_id: str, model_key: str, error: str) -> Dict:
    """空结果 (与 eval_runner._empty_result 一致)"""
    return {
        "question_id": question_id,
        "model_key": model_key,
        "model_name": MODEL_NAMES.get(model_key, model_key),
        "ucloud_mentioned": False,
        "ucloud_mention_count": 0,
        "ucloud_rank": None,
        "has_citation": False,
        "citation_count": 0,
        "ucloud_recommended": False,
        "recommendation_strength": "none",
        "sentiment_score": 0.5,
        "sentiment_label": "neutral",
        "position_weight": 0.0,
        "response_length": 0,
        "raw_content": "",
        "competitor_mentions": {},
        "citations": [],
        "all_cited_urls": [],
        "error_message": error,
    }


def _scores_to_dict(s) -> Dict:
    """GEOScores → dict (与 eval_runner._scores_to_dict 一致)"""
    return {
        "geo_score": s.geo_score,
        "coverage_rate": s.coverage_rate,
        "mention_rate": s.mention_rate,
        "citation_rate": s.citation_rate,
        "recommendation_rate": s.recommendation_rate,
        "sentiment_score": s.sentiment_score,
        "avg_rank": s.avg_rank,
        "total_questions": s.total_questions,
        "valid_responses": s.valid_responses,
    }


def _dict_to_analysis(d: Dict):
    """dict → AnalysisResult (与 eval_runner._dict_to_analysis 一致)"""
    return AnalysisResult(
        question_id=d["question_id"],
        model_key=d["model_key"],
        model_name=d["model_name"],
        ucloud_mentioned=bool(d["ucloud_mentioned"]),
        ucloud_mention_count=d["ucloud_mention_count"],
        ucloud_rank=d.get("ucloud_rank"),
        has_citation=bool(d["has_citation"]),
        citation_count=d["citation_count"],
        ucloud_recommended=bool(d["ucloud_recommended"]),
        ucloud_recommendation_strength=d["recommendation_strength"],
        sentiment_score=d["sentiment_score"],
        sentiment_label=d["sentiment_label"],
        position_weight=d["position_weight"],
        response_length=d["response_length"],
        raw_content=d.get("raw_content", ""),
    )


# ── 主逻辑 ──

def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _save_manifest(run_id: str, name: str, model_keys: List[str],
                   questions: List[Dict], delay: float, output_path: str,
                   task_meta: Optional[Dict] = None,
                   brand_profile: Optional[BrandProfile] = None) -> str:
    """保存任务清单（断点续跑所需：问题集 + 模型 + 参数 + 品牌档案）。"""
    os.makedirs(LOCAL_RUNS_DIR, exist_ok=True)
    path = os.path.join(LOCAL_RUNS_DIR, f"{run_id}.manifest.json")
    manifest = {
        "run_id": run_id, "name": name, "model_keys": model_keys,
        "delay": delay, "output_path": output_path, "questions": questions,
        "task_meta": task_meta or {},
        "brand_profile": brand_profile.to_dict() if brand_profile else None,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path


def _load_manifest(run_id: str) -> Optional[Dict]:
    path = os.path.join(LOCAL_RUNS_DIR, f"{run_id}.manifest.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_output(run_id, model_keys, questions, all_results, geo_scores,
                  task_meta=None) -> Dict:
    fixed_geo_scores = {}
    for mk, scores_by_cat in geo_scores.items():
        fixed_geo_scores[mk] = {}
        for cat, scores in scores_by_cat.items():
            cat_key = cat if cat is not None else "__GLOBAL__"
            fixed_geo_scores[mk][cat_key] = scores
    meta = {
        "generated_at": datetime.now().isoformat(),
        "mode": "webchat_local",
        "run_id": run_id,
        "model_keys": model_keys,
        "total_questions": len(questions),
        "total_results": sum(len(v) for v in all_results.values()),
    }
    if task_meta:
        meta.update(task_meta)  # 透传 task_id / batch_id
    return {
        "meta": meta,
        "questions": questions,
        "analysis_results": {mk: all_results[mk] for mk in model_keys},
        "geo_scores": fixed_geo_scores,
    }


def _write_json(path: str, data: Dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def _login_flow(client, mk: str, max_wait: int = 300) -> bool:
    """--headed 下引导登录：确保浏览器开着 → 导航一次 → 轮询 _is_logged_in → 确认后才保存。

    只在 _is_logged_in 确认登录后调 save_auth_state，杜绝提前保存不完整 state。
    导航只做一次（_goto_site），轮询时不重复 goto（否则会打断用户正在进行的登录）。
    返回是否最终登录成功。
    """
    # 确保浏览器开着（无存档时 initialize(fresh=True) 开全新 context）
    if client._page is None:
        if not await client.initialize(fresh=True):
            print(f"  ❌ {client.name} 无法启动浏览器，跳过登录")
            return False
    # 导航到站点一次；之后只探测、不重新 goto
    await client._goto_site(client._page)
    name = client.name
    print(f"\n  → 请在浏览器窗口登录 {name}（{client.url}）")
    print(f"    登录完成后会自动检测并保存，无需手动按 Enter。")
    elapsed = 0
    while elapsed < max_wait:
        await asyncio.sleep(3)
        elapsed += 3
        try:
            if await client._is_logged_in(client._page, timeout=5):
                # 等 3s 让登录跳转回流把 token/cookie 写全，再复确认一次，
                # 避免抢救"刚出现弱信号但还没写完"的中途态。
                await asyncio.sleep(3)
                if not await client._is_logged_in(client._page, timeout=5):
                    print(f"    ⚠️ {name} 登录态未稳定，继续等待...")
                else:
                    try:
                        state = await client._context.storage_state()
                        save_auth_state(mk, state)
                        print(f"  ✅ {name} 登录已检测并保存（{len(state.get('cookies', []))} cookies）")
                        return True
                    except Exception as e:
                        print(f"  ❌ {name} 保存登录态失败: {e}")
                        return False
        except Exception as e:
            print(f"    ⚠️ {name} 探测异常（继续等待）: {e}")
        print(f"    ... 等待 {name} 登录（{max_wait - elapsed}s）")
    print(f"  ⚠️ {max_wait}s 未检测到 {name} 登录，不保存、跳过该模型")
    return False


async def run_local_eval(
    model_keys: List[str],
    question_ids: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    delay: float = 8.0,
    output_path: str = "local_results.json",
    questions: Optional[List[Dict]] = None,
    run_id: Optional[str] = None,
    resume: bool = False,
    name: str = "GEO评估",
    per_model_questions: Optional[Dict[str, List[Dict]]] = None,
    task_meta: Optional[Dict] = None,
    headed: bool = False,
    brand_profile: Optional[BrandProfile] = None,
):
    """执行本地 WebChat 评测（三级任务调度：任务 → 模型 → 问题）

    - 单元级持久化（data/local_runs/<run_id>.db）+ 断点续跑
    - 每单元 done 即增量写 output/<run_id>.partial.json，崩溃不丢已完成题
    - resume=True 时从已存在的 run_id 恢复，跳过 done，仅补跑 pending/failed
    """
    # ── 恢复模式：从清单重建问题集与参数 ──
    if resume and run_id:
        manifest = _load_manifest(run_id)
        if not manifest:
            print(f"  错误: 找不到 run_id={run_id} 的清单，无法恢复")
            return
        model_keys = manifest["model_keys"]
        questions = manifest["questions"]
        delay = manifest.get("delay", delay)
        output_path = manifest.get("output_path", output_path)
        name = manifest.get("name", name)
        task_meta = manifest.get("task_meta") or None
        # 恢复品牌档案（保证续跑时分析口径与首次一致）
        if brand_profile is None and manifest.get("brand_profile"):
            brand_profile = BrandProfile.from_dict(manifest["brand_profile"])
        print(f"  ♻️  恢复模式: run_id={run_id}")

    print(SEP)
    print("  GEO 评估 — 本地 Playwright WebChat Runner")
    print(SEP)
    print(f"  模型: {', '.join(model_keys)}")
    print(f"  输出: {output_path}")
    print(f"  延迟: {delay}s（与平台保护间隔取较大者）")
    print()

    # 1. 获取问题列表
    print("[1/5] 加载问题列表...")
    if not questions:
        questions = await _load_questions(question_ids, categories)
        if question_ids:
            questions = [q for q in questions if q["id"] in question_ids]
        if categories:
            questions = [q for q in questions if q["category"] in categories]
    if not questions:
        print("  错误: 没有可评估的问题")
        return
    print(f"  加载 {len(questions)} 个问题")

    # ── 登录预检：对每个模型真实探测"能不能聊天"；没登录则 --headed 引导登录后保存 ──
    # 用真实 DOM 探测（输入框可见 + 非登录页 URL），取代旧的 has_auth_state（文件存在）
    # 和手动按 Enter；杜绝"提前保存不完整 state"和"跑到一半才挂"。
    print("\n[登录预检] 逐模型探测登录态...")
    not_logged_in: List[str] = []
    for mk in model_keys:
        client = create_web_chat_client(mk)
        logged_in = False
        try:
            if client.is_configured and await client.initialize():
                await client._goto_site(client._page)
                logged_in = await client._is_logged_in(client._page)
            if not logged_in:
                print(f"  {mk}: 未登录" + ("" if client.is_configured else "（无存档）"))
                if headed:
                    logged_in = await _login_flow(client, mk)
            if not logged_in:
                not_logged_in.append(mk)
            else:
                print(f"  {mk}: 已登录 ✓")
        except Exception as e:
            print(f"  {mk}: 探测异常 {e}，按未登录处理")
            not_logged_in.append(mk)
        finally:
            await client.close()

    if not_logged_in:
        if headed:
            print(f"\n  ⚠️ 以下模型未登录成功，将被跳过: {', '.join(not_logged_in)}")
        else:
            print(f"\n  ⚠️ 以下模型未登录，且非 --headed 无法弹浏览器登录，将被跳过: {', '.join(not_logged_in)}")
            print(f"  （加 --headed 可弹浏览器登录）")

    # 全部模型未登录 → 中止，不产出空结果
    if all(mk in not_logged_in for mk in model_keys):
        print("\n❌ 所有模型均未登录，已中止，未生成结果文件。")
        print("   请用 --headed 模式运行以弹出浏览器登录，或先运行 setup_webchat_auth.py。")
        return

    # 2. 生成/复用 run_id + 单元库 + 清单
    if not run_id:
        run_id = _new_run_id()
    print(f"[2/5] 任务 run_id = {run_id}")
    store = SqliteUnitStore(os.path.join(LOCAL_RUNS_DIR, f"{run_id}.db"))
    if not resume:
        _save_manifest(run_id, name, model_keys, questions, delay, output_path, task_meta, brand_profile)

    partial_path = os.path.join(OUTPUT_DIR, f"{run_id}.partial.json")

    analyzer = ResponseAnalyzer(brand_profile=brand_profile)
    calculator = MetricsCalculator()
    all_results: Dict[str, List] = {mk: [] for mk in model_keys}
    _q_map = {q["id"]: q for q in questions}
    total = len(questions) * len(model_keys)

    # 若恢复，先把已 done 的单元回填进 all_results（用 store 里的 content 重算）
    if resume:
        for u in store.list_units(run_id, "done"):
            analysis = analyzer.analyze(
                question_id=u.question_id, model_key=u.model_key,
                model_name=u.model_name or MODEL_NAMES.get(u.model_key, u.model_key),
                content=u.content or "", error=None,
            )
            all_results[u.model_key].append(_analysis_to_dict(analysis))
        print(f"  恢复: 已完成 {sum(len(v) for v in all_results.values())} 个单元，仅补跑剩余")

    # 3. 回调
    def _dump_partial():
        out = _build_output(run_id, model_keys, questions, all_results, {}, task_meta=task_meta)
        _write_json(partial_path, out)

    async def on_unit_done(unit, response):
        content = response.get("content", "")
        error = response.get("error")
        model_name = unit.model_name or MODEL_NAMES.get(unit.model_key, unit.model_key)
        analysis = analyzer.analyze(
            question_id=unit.question_id, model_key=unit.model_key,
            model_name=model_name, content=content, error=error,
        )
        result = _analysis_to_dict(analysis)
        # 去重：同一 (model,question) 保留最新（重试成功时覆盖旧的失败记录）
        arr = all_results[unit.model_key]
        arr = [r for r in arr if r["question_id"] != unit.question_id]
        arr.append(result)
        all_results[unit.model_key] = arr
        _dump_partial()  # 增量写盘：崩溃也不丢
        c = sum(len(v) for v in all_results.values())
        ucloud = "✅" if analysis.ucloud_mentioned else "—"
        cit = f"📎{analysis.citation_count}" if analysis.has_citation else ""
        rec = f"⭐{analysis.ucloud_recommendation_strength}" if analysis.ucloud_recommended else ""
        mark = "❌" if error else ""
        print(f"    [{c}/{total}] {unit.model_key}:{unit.question_id} {ucloud} {cit} {rec} {mark}"
              f"{(' '+error[:60]) if error else ''}")

    async def on_progress(event):
        if event.get("type") == "throttled":
            print(f"    ⚠️ {event['model_key']} 触发限流，进入长冷却后重试")
        elif event.get("type") == "model_skipped":
            print(f"    ⛔ {event.get('model_key')} 跳过（{event.get('reason')}）")

    # 客户端工厂：浏览器由 scheduler worker 内部初始化/关闭
    async def client_factory(mk):
        return create_web_chat_client(mk)

    # 逐模型策略：用户 delay 与平台保护 delay 取较大者
    extra_policy = {}
    for mk in model_keys:
        pol = get_model_policy(mk)
        if delay and delay > 0:
            extra_policy[mk] = {"inter_unit_delay": max(pol.get("inter_unit_delay", 0), float(delay))}

    # 4. 执行调度
    print("[3/5] 开始评测（跨模型交错 + 逐模型限流 + 单题重试 + 封号退避）...")
    scheduler = EvalScheduler(
        run_id=run_id, models=model_keys, questions=questions, store=store,
        client_factory=client_factory, on_unit_done=on_unit_done, on_progress=on_progress,
        extra_policy=extra_policy,
        per_model_questions=per_model_questions,
    )
    await scheduler.run()

    # 补齐被跳过/失败的模型单元为空结果，保证评测覆盖完整
    # per_model_questions 模式下每模型只补自己的题区间，避免产生幻影 failed 行
    for mk in model_keys:
        seen = {r["question_id"] for r in all_results[mk]}
        if per_model_questions:
            model_qs = per_model_questions.get(mk, questions)
        else:
            model_qs = questions
        for q in model_qs:
            if q["id"] not in seen:
                all_results[mk].append(_empty_result(q["id"], mk, "WebChat 未配置登录状态 / 跳过"))

    # 5. 计算评分
    print("\n[4/5] 计算 GEO 评分...")
    geo_scores: Dict[str, Dict[str, Any]] = {}
    for mk in model_keys:
        if not all_results[mk]:
            continue
        model_name = MODEL_NAMES.get(mk, mk)
        results = [_dict_to_analysis(r) for r in all_results[mk]]
        scores = calculator.calculate_scores(results, questions=questions, brand_profile=brand_profile)
        geo_scores[mk] = {None: _scores_to_dict(scores)}
        print(f"  {model_name}: GEO={scores.geo_score:.1f} "
              f"覆盖={scores.coverage_rate:.2f} "
              f"引用={scores.citation_rate:.2f} "
              f"推荐={scores.recommendation_rate:.2f}")
        categories_map = {}
        for r in all_results[mk]:
            q = _q_map.get(r["question_id"])
            if q:
                categories_map.setdefault(q["category"], []).append(r)
        for cat, cat_results in categories_map.items():
            cat_questions = [q for q in questions if q.get("category") == cat]
            cat_scores = calculator.calculate_scores([_dict_to_analysis(r) for r in cat_results],
                                                    questions=cat_questions, brand_profile=brand_profile)
            geo_scores[mk][cat] = _scores_to_dict(cat_scores)

    print("\n[5/5] 导出结果...")
    output = _build_output(run_id, model_keys, questions, all_results, geo_scores, task_meta=task_meta)
    _write_json(output_path, output)
    print(f"  ✅ 结果已保存: {output_path}")
    print(f"  文件大小: {os.path.getsize(output_path) / 1024:.1f} KB")
    # 清理 partial
    try:
        if os.path.exists(partial_path):
            os.remove(partial_path)
    except OSError:
        pass
    print("完成。")


async def _load_questions(
    question_ids: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
) -> List[Dict]:
    """加载问题列表（从数据库或本地文件）"""
    try:
        # 尝试从数据库加载
        questions = await db_get_questions(
            category=categories[0] if categories and len(categories) == 1 else None,
            active_only=True,
        )
        if question_ids:
            questions = [q for q in questions if q["id"] in question_ids]
        if categories:
            questions = [q for q in questions if q["category"] in categories]
        return questions
    except Exception:
        pass

    # 数据库不可用时，从 core/questions.py 加载
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
        from questions import QUESTIONS
        questions = [
            {
                "id": q.id,
                "category": q.category,
                "question_type": q.question_type,
                "question": q.question,
                "tags": q.tags,
                "difficulty": q.difficulty,
            }
            for q in QUESTIONS
        ]
        if question_ids:
            questions = [q for q in questions if q["id"] in question_ids]
        if categories:
            questions = [q for q in questions if q["category"] in categories]
        return questions
    except ImportError:
        print("  错误: 无法加载问题列表")
        return []


def main():
    parser = argparse.ArgumentParser(
        description="本地 Playwright WebChat Runner",
        epilog="""
用例:
  # 方式1：直接指定参数（手动模式）
  python scripts/local_webchat_runner.py --models kimi ernie --delay 10

  # 方式2：从服务器下载的任务配置运行（云联动模式）
  python scripts/local_webchat_runner.py --config task_config.json

  # 带浏览器窗口（可手动处理验证码/登录）
  python scripts/local_webchat_runner.py --config task_config.json --headed
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        help="任务配置文件路径（由服务器 /api/evaluations/export-webchat-config 生成）",
    )
    parser.add_argument(
        "--models", nargs="+",
        help="要评测的模型 (默认: kimi)",
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="显示浏览器窗口（默认后台运行，--headed 可处理验证码/登录）",
    )
    parser.add_argument(
        "--questions", default="all",
        help="问题范围: all / 逗号分隔的问题ID / 品类名（--config 模式下被忽略）",
    )
    parser.add_argument(
        "--delay", type=float,
        help="每题之间的延迟秒数（--config 模式下优先使用配置中的值）",
    )
    parser.add_argument(
        "--output",
        help="输出文件路径（默认: output/webchat_results_YYYYMMDD_HHMMSS.json）",
    )
    parser.add_argument(
        "--inline-questions", "-Q",
        help='直接传入问题文本，用 || 分隔（不需要数据库），如 --inline-questions "什么是云计算？||推荐什么云服务？"',
    )
    parser.add_argument(
        "--resume",
        help="断点续跑：传入之前的 run_id，跳过已完成单元，仅补跑 pending/failed",
    )

    args = parser.parse_args()

    # 断点续跑：直接从清单恢复，忽略其它参数
    if args.resume:
        _setup_headed_mode(args.headed)
        asyncio.run(run_local_eval(
            model_keys=[], output_path="", delay=0.0,
            run_id=args.resume, resume=True, headed=args.headed,
        ))
        return

    # 设置浏览器显示模式（必须在 import web_chat_clients 之前）
    _setup_headed_mode(args.headed)

    # 加载任务配置
    question_ids = None
    categories = None
    preloaded_questions = None
    model_keys = args.models or ["kimi"]
    delay = args.delay if args.delay is not None else 8.0
    output_path = args.output
    task_name = "GEO评估"

    per_model_questions = None
    task_meta = None
    brand_profile = None
    if args.config:
        print(f"  📥 从配置文件加载: {args.config}")
        with open(args.config, "r", encoding="utf-8") as f:
            config = json.load(f)

        delay = config.get("delay", config.get("task", {}).get("delay", delay))
        preloaded_questions = config.get("questions")
        question_ids = config.get("question_ids")
        categories = config.get("categories")
        task_name = config.get("task_name") or config.get("task", {}).get("name", "GEO评估")

        # 读取品牌档案（服务端建批次时写入），用于本地分析口径
        brand_profile = None
        if config.get("brand_profile"):
            brand_profile = BrandProfile.from_dict(config["brand_profile"])

        if config.get("version") == 2 or "units" in config:
            # v2：每模型独立题区间
            units = config.get("units", [])
            model_keys = [u["model_key"] for u in units]
            q_map_cfg = {q["id"]: q for q in (preloaded_questions or [])}
            per_model_questions = {
                u["model_key"]: [q_map_cfg[qid] for qid in u["question_ids"] if qid in q_map_cfg]
                for u in units
            }
            # 缺题对象时退化为最小 dict（仅 id）
            for mk, qs in per_model_questions.items():
                if not qs:
                    per_model_questions[mk] = [{"id": qid, "question": qid, "category": "",
                                                "question_type": "", "tags": [], "difficulty": "medium"}
                                               for qid in next(u["question_ids"] for u in units if u["model_key"] == mk)]
            task_meta = {"task_id": config.get("task_id"), "batch_id": config.get("batch_id")}
            print(f"  任务(v2): {task_name} | task_id={task_meta['task_id']} | batch_id={task_meta['batch_id']}")
            print(f"  模型: {', '.join(model_keys)} | 单元: {sum(len(v) for v in per_model_questions.values())}")
        else:
            # v1 兼容
            model_keys = config["task"]["model_keys"]
            task_name = config["task"].get("name", "GEO评估")

        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in task_name)
            output_path = f"output/webchat_{safe_name}_{timestamp}.json"
        print()
    else:
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"output/webchat_results_{timestamp}.json"
        if args.inline_questions:
            texts = args.inline_questions.split("||")
            preloaded_questions = [
                {"id": f"test_{i+1}", "category": "test", "question_type": "direct",
                 "question": t.strip(), "tags": [], "difficulty": "medium"}
                for i, t in enumerate(texts) if t.strip()
            ]
            print(f"  📝 使用内联问题: {len(preloaded_questions)} 个")
        elif args.questions != "all":
            if "," in args.questions:
                question_ids = args.questions.split(",")
            else:
                categories = [args.questions]

    asyncio.run(run_local_eval(
        model_keys=model_keys,
        question_ids=question_ids,
        categories=categories,
        delay=delay,
        output_path=output_path,
        questions=preloaded_questions,
        name=task_name,
        per_model_questions=per_model_questions,
        task_meta=task_meta,
        headed=args.headed,
        brand_profile=brand_profile,
    ))


if __name__ == "__main__":
    main()
