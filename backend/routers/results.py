"""结果查询路由"""
import json
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import database as db
from services.chart_builder import (
    build_radar_option, build_bar_option, build_coverage_option,
    build_sentiment_option, build_heatmap_option,
)

router = APIRouter(prefix="/api/results", tags=["results"])

# ── 第三方内容平台域名（知乎/CSDN/GitHub 等有具体内容的站点）──
THIRD_PARTY_CONTENT_DOMAINS = [
    "zhihu.com", "zhuanlan.zhihu.com",
    "csdn.net", "blog.csdn.net",
    "juejin.cn", "segmentfault.com", "jianshu.com",
    "cnblogs.com", "infoq.cn", "oschina.net", "oscimg.com",
    "github.com", "gitee.com",
    "bilibili.com",
    "stackoverflow.com", "readthedocs.io",
    "mp.weixin.qq.com",
    "51cto.com",
]

# ── URL 引用类型分类 ──
def _classify_url_type(url: str) -> str:
    """判断一条 URL 是「可能的信息来源」还是「AI生成的引用」。

    规则：
    - 第三方内容平台（知乎/CSDN/GitHub等）上有具体路径的页面 → "可能的信息来源"
    - 首页级、产品页、API endpoint、云厂商官网 → "AI生成的引用"
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.rstrip("/")

        # 第三方内容平台 + 有具体路径 → 可能的信息来源
        is_third = any(d in domain for d in THIRD_PARTY_CONTENT_DOMAINS)
        if is_third and len(path) > 5 and path not in ("", "/"):
            return "可能的信息来源"

        # API endpoint / 代码示例中的 endpoint → AI生成的引用
        if domain.startswith("api.") or "/v1/" in path or "/api/" in path:
            return "AI生成的引用"

        # 首页级（空路径或极短路径）→ AI生成的引用
        if path in ("", "/") or len(path) <= 5:
            return "AI生成的引用"

        # 其余：产品页、定价页、文档首页等，都属于AI生成的引用
        return "AI生成的引用"
    except Exception:
        return "AI生成的引用"


def _resolve_citation_channel(url_info: dict) -> str:
    """判定引用构成通道——基于引用自身属性（不依赖评测模式）：
    - UCloud 官方链接 (citation_type=url, is_ucloud=true) → pretraining（模型预训练知识）
    - 文本引用 (citation_type=reference，如"据UCloud官网…") → pretraining（模型预训练知识）
    - 第三方 URL (citation_type=url, is_ucloud=false) → web_search（联网搜索获取）
    - API 搜索引用 (position < 0) → web_search
    - 无 citation_type 的 → undetected"""
    channel = url_info.get("citation_channel")
    if channel and channel in ("pretraining", "user_provided", "web_search", "undetected"):
        return channel

    ct = url_info.get("citation_type", "")

    # API 搜索引用（position < 0）→ web_search
    pos = url_info.get("position")
    if pos is not None:
        try:
            if int(pos) < 0:
                return "web_search"
        except (TypeError, ValueError):
            pass

    # 文本引用（如"据UCloud官网…"）→ pretraining
    if ct == "reference":
        return "pretraining"

    # URL 引用 → 按 is_ucloud 区分
    if ct == "url":
        if url_info.get("is_ucloud"):
            return "pretraining"   # UCloud 官方链接
        else:
            return "web_search"    # 第三方来源链接

    return "undetected"


def _extract_cited_urls(r: dict, cache_map: dict = None) -> list:
    """从一条 analysis_result 解析出供前端渲染的引用链接清单。

    同时读 all_cited_urls（URL引用）和 citations（含文本引用如"据UCloud官网…"），
    按 content 去重，返回 [{content, is_ucloud, source_channel, mentions_uc, citation_channel}]。
    文本引用无 URL，citation_type 为 "reference"，citation_channel 为 "pretraining"。

    mentions_uc = 该 URL 网页正文是否出现 UCloud/优刻得（来自 url_uc_cache 缓存）：
      True/False/None(未检测)。cache_map 为预取的 {url: mentions_uc}，避免逐条查库。
    """
    def _parse_json(raw):
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    seen = set()
    out = []

    # 1. all_cited_urls — URL 引用
    for u in _parse_json(r.get("all_cited_urls", "[]")):
        if not isinstance(u, dict):
            continue
        if u.get("citation_type") and u.get("citation_type") != "url":
            continue
        c = u.get("content") or u.get("url") or ""
        if not c or not str(c).startswith("http"):
            continue
        if c in seen:
            continue
        seen.add(c)
        mu = u.get("mentions_uc")
        if mu is None and cache_map is not None:
            mu = cache_map.get(c)
        out.append({
            "content": c,
            "is_ucloud": bool(u.get("is_ucloud")),
            "source_channel": u.get("source_channel") or _resolve_domain_label(c),
            "mentions_uc": mu,
            "position": u.get("position"),
            "citation_channel": _resolve_citation_channel(u),
        })

    # 2. citations — 文本引用（citation_type="reference"，如"据UCloud官网…"）
    for cit in _parse_json(r.get("citations", "[]")):
        if not isinstance(cit, dict):
            continue
        ct = cit.get("citation_type", "")
        if ct == "url":
            # URL 引用已在 all_cited_urls 中处理，这里只补文本引用
            c = cit.get("content") or cit.get("url") or ""
            if c and c not in seen:
                seen.add(c)
                mu = cit.get("mentions_uc")
                if mu is None and cache_map is not None:
                    mu = cache_map.get(c)
                out.append({
                    "content": c,
                    "is_ucloud": bool(cit.get("is_ucloud")),
                    "source_channel": cit.get("source_channel") or _resolve_domain_label(c),
                    "mentions_uc": mu,
                    "position": cit.get("position"),
                    "citation_channel": _resolve_citation_channel(cit),
                })
        elif ct == "reference":
            # 文本引用：用 content（文本短语）去重
            c = cit.get("content", "").strip()
            if not c or c in seen:
                continue
            seen.add(c)
            out.append({
                "content": c,
                "is_ucloud": bool(cit.get("is_ucloud", True)),
                "source_channel": "文本引用",
                "mentions_uc": None,
                "position": cit.get("position"),
                "citation_channel": _resolve_citation_channel(cit),
            })

    return out


def _resolve_domain_label(url: str) -> str:
    """从 URL 提取域名，作为'其他'类的细化标签。"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if ":" in domain:
            domain = domain.split(":")[0]
        if domain.startswith("www."):
            domain = domain[4:]
        if not domain:
            return "其他"
        # 尝试用 core/config 的映射
        try:
            from config import URL_CHANNEL_MAPPING
        except ImportError:
            import os, sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
            from config import URL_CHANNEL_MAPPING

        if domain in URL_CHANNEL_MAPPING:
            return URL_CHANNEL_MAPPING[domain]
        # 父域名匹配
        parts = domain.split(".")
        for i in range(len(parts) - 1):
            parent = ".".join(parts[i:])
            if parent in URL_CHANNEL_MAPPING:
                return URL_CHANNEL_MAPPING[parent]
        # 没匹配上就用域名本身作为标签
        return domain
    except Exception:
        return "其他"


@router.get("/{run_id}/scores")
async def get_scores(run_id: str, category: str = None, task_id: Optional[str] = None):
    """获取GEO评分"""
    if task_id:
        rows = await db.get_task_scores(task_id, category)
        return {"success": True, "data": rows}
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")
    scores = await db.get_scores(run_id, category)
    return {"success": True, "data": scores}


@router.get("/{run_id}/details")
async def get_details(run_id: str, model_key: str = None, category: str = None,
                      page: int = 1, page_size: int = 50, task_id: Optional[str] = None):
    """获取详细结果"""
    if task_id:
        rows = await db.get_task_results(task_id, model_key)
        return {"success": True, "data": rows}
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    results = await db.get_results(run_id, model_key, category)
    total = len(results)
    start = (page - 1) * page_size
    items = results[start:start + page_size]
    return {"success": True, "data": {"items": items, "total": total, "page": page, "page_size": page_size}}


@router.get("/{run_id}/charts")
async def get_charts(run_id: str, task_id: Optional[str] = None):
    """获取图表配置JSON"""
    if task_id:
        scores = await db.get_task_scores(task_id)
        import database as _db
        db_conn = await _db.get_db()
        try:
            cursor = await db_conn.execute(
                "SELECT * FROM geo_scores WHERE task_id=? AND category IS NOT NULL", (task_id,)
            )
            all_cat_scores = [dict(r) for r in await cursor.fetchall()]
        finally:
            await db_conn.close()
        all_results = await db.get_task_results(task_id)
        results_by_model = {}
        for r in all_results:
            mk = r["model_key"]
            if mk not in results_by_model:
                results_by_model[mk] = []
            results_by_model[mk].append(r)
        charts = {
            "radar": build_radar_option(scores) if scores else {},
            "bar": build_bar_option(scores) if scores else {},
            "coverage": build_coverage_option(scores) if scores else {},
            "sentiment": build_sentiment_option(results_by_model) if results_by_model else {},
            "heatmap": build_heatmap_option(all_cat_scores) if all_cat_scores else {},
        }
        return {"success": True, "data": charts}

    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    # 获取全局评分
    scores = await db.get_scores(run_id)
    # 获取品类评分
    cat_scores_raw = await db.get_scores(run_id, category="__all__")
    # 获取所有品类评分
    import database as _db
    db_conn = await _db.get_db()
    try:
        cursor = await db_conn.execute(
            "SELECT * FROM geo_scores WHERE run_id=? AND category IS NOT NULL", (run_id,)
        )
        all_cat_scores = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db_conn.close()

    # 获取详细结果用于情感图
    all_results = await db.get_results(run_id)
    results_by_model = {}
    for r in all_results:
        mk = r["model_key"]
        if mk not in results_by_model:
            results_by_model[mk] = []
        results_by_model[mk].append(r)

    charts = {
        "radar": build_radar_option(scores) if scores else {},
        "bar": build_bar_option(scores) if scores else {},
        "coverage": build_coverage_option(scores) if scores else {},
        "sentiment": build_sentiment_option(results_by_model) if results_by_model else {},
        "heatmap": build_heatmap_option(all_cat_scores) if all_cat_scores else {},
    }
    return {"success": True, "data": charts}


@router.get("/{run_id}/citations")
async def get_citation_details(run_id: str, model_key: str = None):
    """获取引用详情：哪些问题产生了UCloud引用，及具体引用内容

    仅返回 has_citation=1 的记录（贡献了GEO引用率的）
    """
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    all_results = await db.get_results(run_id, model_key)

    # 关联 questions 表补充问题文本
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question, category, question_type FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = {
                "text": row["question"], "category": row["category"], "type": row["question_type"]
            }
    finally:
        await db_conn.close()

    # 按模型分组
    by_model = {}
    for r in all_results:
        q_info = question_map.get(r["question_id"], {})
        question_text = q_info.get("text", "")
        citations_list = db.get_effective_citations(r)
        if not citations_list:
            continue

        mk = r["model_key"]
        if mk not in by_model:
            by_model[mk] = {"model_name": r.get("model_name", mk), "citation_questions": []}

        by_model[mk]["citation_questions"].append({
            "question_id": r["question_id"],
            "question_text": question_text,
            "citations": citations_list,
        })

    return {"success": True, "data": by_model}


@router.get("/{run_id}/citation-channels")
async def get_citation_channel_clustering(run_id: str, model_key: str = None,
                                          task_id: Optional[str] = None):
    """引用来源渠道聚类统计

    仅统计 ucloud_mentioned=1 的响应中的URL（对GEO评分有贡献），
    按 URL 域名的来源渠道聚类汇总，附带每条引用的问题和完整URL

    task_id 模式：按大任务聚合该模型的全部 analysis_results（跨批次，
    (task_id,model,question) 唯一去重），run_id 传 "0" 占位、不做 run 存在性校验。
    """
    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    # 关联 questions 表获取题目文本
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question, category, question_type FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = {
                "text": row["question"], "category": row["category"], "type": row["question_type"]
            }
    finally:
        await db_conn.close()

    by_model = {}
    # 预取这批结果所有引用 URL 的 mentions_uc 缓存（一次查库）
    _chan_all_urls = set()
    for r in all_results:
        for field in ("all_cited_urls", "citations"):
            v = r.get(field)
            try:
                lst = json.loads(v) if isinstance(v, str) else v
            except (ValueError, TypeError):
                continue
            if isinstance(lst, list):
                for item in lst:
                    if isinstance(item, dict):
                        _u = item.get("content") or item.get("url") or ""
                        if _u and str(_u).startswith("http"):
                            _chan_all_urls.add(_u)
    _uc_chan_map = await db.get_url_uc_cached_map(list(_chan_all_urls)) if _chan_all_urls else {}

    for r in all_results:
        has_error = r.get("error_message") and r["error_message"] != ""
        if has_error:
            continue

        mk = r["model_key"]
        qid = r["question_id"]
        q_info = question_map.get(qid, {})

        if mk not in by_model:
            by_model[mk] = {
                "model_name": r.get("model_name", mk),
                "channels": {},  # channel_name -> {count, question_details}
            }

        # 解析 all_cited_urls JSON — 统计所有URL引用来源
        urls_raw = r.get("all_cited_urls", "[]")
        if isinstance(urls_raw, str):
            try:
                urls_list = json.loads(urls_raw)
            except (json.JSONDecodeError, TypeError):
                urls_list = []
        elif isinstance(urls_raw, list):
            urls_list = urls_raw
        else:
                urls_list = []

        seen_urls_this_question = set()

        for url_info in urls_list:
            if url_info.get("citation_type") != "url":
                continue
            channel = url_info.get("source_channel", "其他") or "其他"
            url_content = url_info.get("content", "")

            # 细化"其他"类
            if channel == "其他":
                channel = _resolve_domain_label(url_content)

            if url_content in seen_urls_this_question:
                continue
            seen_urls_this_question.add(url_content)

            if channel not in by_model[mk]["channels"]:
                by_model[mk]["channels"][channel] = {"count": 0, "question_details": []}
            by_model[mk]["channels"][channel]["count"] += 1
            by_model[mk]["channels"][channel]["question_details"].append({
                "question_id": qid,
                "question_text": q_info.get("text", qid),
                "question_category": q_info.get("category", ""),
                "url": url_content,
                "url_type": _classify_url_type(url_content),
                "mentions_uc": _uc_chan_map.get(url_content),
            })

        # 也统计 citations 中 UCloud 的引用
        cits_raw = r.get("citations", "[]")
        if isinstance(cits_raw, str):
            try:
                cits_list = json.loads(cits_raw)
            except (json.JSONDecodeError, TypeError):
                cits_list = []
        elif isinstance(cits_raw, list):
            cits_list = cits_raw
        else:
            cits_list = []

        for cit in cits_list:
            if cit.get("citation_type") != "url":
                continue
            channel = cit.get("source_channel", "其他") or "其他"
            url_content = cit.get("content", "")

            if channel == "其他":
                channel = _resolve_domain_label(url_content)

            if url_content in seen_urls_this_question:
                continue
            seen_urls_this_question.add(url_content)

            if channel not in by_model[mk]["channels"]:
                by_model[mk]["channels"][channel] = {"count": 0, "question_details": []}
            by_model[mk]["channels"][channel]["count"] += 1
            by_model[mk]["channels"][channel]["question_details"].append({
                "question_id": qid,
                "question_text": q_info.get("text", qid),
                "question_category": q_info.get("category", ""),
                "url": url_content,
                "url_type": _classify_url_type(url_content),
                "mentions_uc": _uc_chan_map.get(url_content),
            })

    # 转换 channels dict 为列表并排序，同时提取 sample_urls
    for mk_data in by_model.values():
        channels_list = []
        for ch, info in mk_data["channels"].items():
            # 从 question_details 提取不重复的示例 URL（最多 6 个）
            seen = set()
            sample_urls = []
            for detail in info["question_details"]:
                url = detail.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    sample_urls.append(url)
                    if len(sample_urls) >= 6:
                        break
            channels_list.append({
                "channel": ch,
                "count": info["count"],
                "question_details": info["question_details"],
                "sample_urls": sample_urls,
            })
        channels_list.sort(key=lambda x: x["count"], reverse=True)
        mk_data["channels"] = channels_list

    return {"success": True, "data": by_model}


@router.get("/{run_id}/question-drilldown")
async def get_question_drilldown(run_id: str, model_key: str, task_id: Optional[str] = None):
    """问题级下钻：获取某渠道每道题的指标计数（分子/分母）和回答摘要。

    task_id 模式：按大任务聚合该模型的全部 analysis_results（跨批次，
    (task_id,model,question) 唯一去重），run_id 传 "0" 占位、不做 run 存在性校验。
    """
    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    if not all_results:
        return {"success": True, "data": {"model_name": model_key, "total_questions": 0, "questions": []}}

    model_name = all_results[0].get("model_name", model_key)

    # 预取这批结果所有引用 URL 的 mentions_uc 缓存（一次查库，避免逐条查）
    _all_urls = []
    for r in all_results:
        for field in ("all_cited_urls", "citations"):
            v = r.get(field)
            try:
                lst = json.loads(v) if isinstance(v, str) else v
            except (ValueError, TypeError):
                continue
            if isinstance(lst, list):
                for item in lst:
                    if isinstance(item, dict):
                        u = item.get("content") or item.get("url") or ""
                        if u and str(u).startswith("http"):
                            _all_urls.append(u)
    _uc_cache_map = await db.get_url_uc_cached_map(_all_urls) if _all_urls else {}

    # 关联 questions 表获取题目文本、品类、类型
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question, category, question_type FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = {"text": row["question"], "category": row["category"], "type": row["question_type"]}
    finally:
        await db_conn.close()

    questions = []
    for r in all_results:
        qid = r["question_id"]
        q_info = question_map.get(qid, {})
        has_error = r.get("error_message") and r["error_message"] != ""

        # 判断是否为自然问题（引导型和题干含UCloud/优刻得的排除提及率/TOP3推荐率）
        q_text = q_info.get("text", "")
        q_category = q_info.get("category", "")
        is_natural = db.is_natural_question(q_text, q_category)

        # 构建指标计数（分子/分母）
        denom = 1
        coverage_num = 1 if r.get("ucloud_mentioned") and not has_error else 0
        citation_num = 1 if db.has_effective_citation(r) and not has_error else 0
        # TOP3 推荐率分子必须与顶层 metrics.py 一致：rank<=3 才算进 top3，
        # 而非 "回答里出现了推荐词"(ucloud_recommended 布尔)——否则排名#4 的题
        # 会因回答含"强烈推荐"而在抽屉显示 1/1，与顶层聚合(0.4839=15/31)对不上。
        # （0630 doubao q011: rank=4 + ucloud_recommended=1，正是此类边角。）
        rank = r.get("ucloud_rank")
        recommend_num = 1 if (rank is not None and rank <= 3) and not has_error else 0
        strength = r.get("recommendation_strength", "none") or "none"

        # 引导型/非自然问题：提及率和TOP3推荐率显示"-"
        if not is_natural:
            coverage_display = "-"
            recommend_display = "-"
        else:
            coverage_display = f"{coverage_num}/{denom}" if not has_error else "-"
            recommend_display = f"{recommend_num}/{denom}" if not has_error else "-"

        # 回答摘要（表格列用）和完整回答内容（展开区用）
        raw = r.get("raw_content", "") or ""
        summary = raw[:200] + ("..." if len(raw) > 200 else "") if raw else ""
        response_content = raw  # 完整内容，供前端折叠展示

        questions.append({
            "question_id": qid,
            "question_text": q_info.get("text", qid),
            "category": q_category,
            "question_type": q_info.get("type", ""),
            "is_natural": is_natural,
            "metrics": {
                "coverage": {"numerator": coverage_num if is_natural else 0,
                             "denominator": denom if is_natural and not has_error else 0,
                             "value": coverage_display},
                "citation": {"numerator": citation_num, "denominator": denom if not has_error else 0,
                             "value": f"{citation_num}/{denom}" if not has_error else "-"},
                "recommendation": {"numerator": recommend_num if is_natural else 0,
                                   "denominator": denom if is_natural and not has_error else 0,
                                   "value": recommend_display,
                                   "strength": strength if is_natural else "-"},
                "sentiment": {"score": round(r.get("sentiment_score", 0.5), 4),
                              "label": r.get("sentiment_label", "neutral")},
            },
            "mention_count": r.get("ucloud_mention_count", 0),
            "position_weight": r.get("position_weight", 0),
            "ucloud_rank": r.get("ucloud_rank"),
            # 原始标志字段：供前端标签展示（提及/推荐/引用N），与批次结果视图一致。
            # 引导型/非自然题的 metrics.*.numerator 被强制为 0，标签必须用原始字段
            # 才能在引导型题上正确显示"提及"等。
            "ucloud_mentioned": bool(r.get("ucloud_mentioned")),
            "ucloud_recommended": bool(r.get("ucloud_recommended")),
            "citation_count": r.get("citation_count", 0) or 0,
            "has_citation": bool(db.has_effective_citation(r)),
            "response_summary": summary,
            "response_content": response_content,
            "cited_urls": _extract_cited_urls(r, cache_map=_uc_cache_map),
            "has_error": has_error,
            "error_message": r.get("error_message") if has_error else None,
        })

    return {"success": True, "data": {"model_name": model_name, "total_questions": len(questions), "questions": questions}}


@router.get("/{run_id}/citation-drilldown")
async def get_citation_drilldown(run_id: str, source_channel: str = Query(...),
                                 task_id: Optional[str] = None,
                                 model_key: Optional[str] = None):
    """引用源下钻：按来源渠道名称筛选，返回该来源下的所有问题及引用链接

    source_channel 为渠道名（如"UCloud官网"、"知乎"、"阿里云"等）

    task_id 模式：按大任务聚合该模型（或全部模型）的 analysis_results（跨批次去重），
    run_id 传 "0" 占位、不做 run 存在性校验；可选 model_key 过滤单一模型。
    """
    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    # 关联 questions 表获取题目文本
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question, category, question_type FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = {
                "text": row["question"], "category": row["category"], "type": row["question_type"]
            }
    finally:
        await db_conn.close()

    by_model = {}
    # 预取这批结果所有引用 URL 的 mentions_uc 缓存（一次查库）
    _chan_all_urls = set()
    for r in all_results:
        for field in ("all_cited_urls", "citations"):
            v = r.get(field)
            try:
                lst = json.loads(v) if isinstance(v, str) else v
            except (ValueError, TypeError):
                continue
            if isinstance(lst, list):
                for item in lst:
                    if isinstance(item, dict):
                        _u = item.get("content") or item.get("url") or ""
                        if _u and str(_u).startswith("http"):
                            _chan_all_urls.add(_u)
    _uc_chan_map = await db.get_url_uc_cached_map(list(_chan_all_urls)) if _chan_all_urls else {}

    for r in all_results:
        has_error = r.get("error_message") and r["error_message"] != ""
        if has_error:
            continue

        mk = r["model_key"]
        qid = r["question_id"]
        q_info = question_map.get(qid, {})

        # 收集该条结果中匹配 source_channel 的所有 URL
        matching_urls = []

        # 从 all_cited_urls 中查找
        urls_raw = r.get("all_cited_urls", "[]")
        if isinstance(urls_raw, str):
            try:
                urls_list = json.loads(urls_raw)
            except (json.JSONDecodeError, TypeError):
                urls_list = []
        else:
            urls_list = urls_raw or []

        for url_info in urls_list:
            if url_info.get("citation_type") != "url":
                continue
            channel = url_info.get("source_channel", "其他") or "其他"
            url_content = url_info.get("content", "")
            if channel == "其他":
                channel = _resolve_domain_label(url_content)
            if channel == source_channel:
                matching_urls.append({
                    "content": url_content,
                    "is_ucloud": url_info.get("is_ucloud", False),
                    "url_type": _classify_url_type(url_content),
                    "mentions_uc": _uc_chan_map.get(url_content),
                })

        # 从 citations 中查找
        cits_raw = r.get("citations", "[]")
        if isinstance(cits_raw, str):
            try:
                cits_list = json.loads(cits_raw)
            except (json.JSONDecodeError, TypeError):
                cits_list = []
        else:
            cits_list = cits_raw or []

        for cit in cits_list:
            if cit.get("citation_type") != "url":
                continue
            channel = cit.get("source_channel", "其他") or "其他"
            url_content = cit.get("content", "")
            if channel == "其他":
                channel = _resolve_domain_label(url_content)
            if channel == source_channel:
                # 去重
                if not any(u["content"] == url_content for u in matching_urls):
                    matching_urls.append({
                        "content": url_content,
                        "is_ucloud": cit.get("is_ucloud", False),
                        "url_type": _classify_url_type(url_content),
                        "mentions_uc": _uc_chan_map.get(url_content),
                    })

        if not matching_urls:
            continue

        if mk not in by_model:
            by_model[mk] = {
                "model_name": r.get("model_name", mk),
                "questions": [],
            }

        by_model[mk]["questions"].append({
            "question_id": qid,
            "question_text": q_info.get("text", qid),
            "question_category": q_info.get("category", ""),
            "ucloud_mentioned": bool(r.get("ucloud_mentioned")),
            "urls": matching_urls,
        })

    return {"success": True, "data": by_model}


@router.post("/{run_id}/backfill-citations")
async def backfill_citations(run_id: str):
    """从 raw_content 重新提取引用详情并回填 citations/all_cited_urls 列"""
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "评测不存在")

    count = await db.backfill_citations(run_id)
    return {"success": True, "data": {"backfilled": count}}


@router.post("/{run_id}/backfill-url-uc")
async def backfill_url_uc(run_id: str, task_id: Optional[str] = None,
                          concurrency: int = 8):
    """对指定 run/task 范围内的引用 URL 抓取并回填「出现 UCloud」缓存。

    抓取每个 URL 网页正文是否含 UCloud/优刻得，结果存 url_uc_cache 表（跨 task 复用）。
    官方域名短路判 True；抓取失败标 NULL（前端显示"未检测"）。
    task_id 模式：run_id 传 "0" 占位。
    """
    if task_id:
        scope, rid, tid = "task", None, task_id
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        scope, rid, tid = "run", run_id, None

    stats = await db.backfill_url_uc(scope=scope, run_id=rid, task_id=tid,
                                     concurrency=concurrency)
    return {"success": True, "data": stats}


@router.get("/compare")
async def compare_runs(run_id_1: str = Query(...), run_id_2: str = Query(...)):
    """对比两次评测"""
    scores1 = await db.get_scores(run_id_1)
    scores2 = await db.get_scores(run_id_2)
    return {"success": True, "data": {"run_1": scores1, "run_2": scores2}}


@router.get("/{run_id}/citation-breakdown")
async def get_citation_breakdown(run_id: str, model_key: Optional[str] = None,
                                 task_id: Optional[str] = None):
    """引用构成统计：按引用自身属性四类（预训练/用户提供/网络搜索/未检测）计数。

    只读端点，返回 {pretraining: N, user_provided: N, web_search: N, undetected: N, total: N}。
    task_id 模式：按大任务聚合该模型（或全部模型）的 analysis_results（跨批次去重），
    run_id 传 "0" 占位、不做 run 存在性校验。

    分类规则（_resolve_citation_channel）：
    - UCloud 官方链接/文本引用 → pretraining（预训练知识）
    - 第三方来源 URL → web_search（联网搜索）
    - 用户提供的 URL → user_provided（暂无数据）
    """
    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    # 四类计数器
    counts = {"pretraining": 0, "user_provided": 0, "web_search": 0, "undetected": 0}

    for r in all_results:
        has_error = r.get("error_message") and r["error_message"] != ""
        if has_error:
            continue

        # 从 all_cited_urls 解析引用，统计每条的 citation_channel
        urls_raw = r.get("all_cited_urls", "[]")
        if isinstance(urls_raw, str):
            try:
                urls_list = json.loads(urls_raw)
            except (json.JSONDecodeError, TypeError):
                urls_list = []
        elif isinstance(urls_raw, list):
            urls_list = urls_raw
        else:
            urls_list = []

        seen_urls = set()
        for url_info in urls_list:
            if not isinstance(url_info, dict):
                continue
            if url_info.get("citation_type") != "url":
                continue
            url_content = url_info.get("content", "")
            if not url_content or url_content in seen_urls:
                continue
            seen_urls.add(url_content)

            channel = _resolve_citation_channel(url_info)
            counts[channel] += 1

        # 也统计 citations 字段中的引用
        cits_raw = r.get("citations", "[]")
        if isinstance(cits_raw, str):
            try:
                cits_list = json.loads(cits_raw)
            except (json.JSONDecodeError, TypeError):
                cits_list = []
        elif isinstance(cits_raw, list):
            cits_list = cits_raw
        else:
            cits_list = []

        for cit in cits_list:
            if not isinstance(cit, dict):
                continue
            # URL 引用：去重后统计
            if cit.get("citation_type") == "url":
                url_content = cit.get("content", "")
                if not url_content or url_content in seen_urls:
                    continue
                seen_urls.add(url_content)
            # 文本引用（如"据UCloud官网…"）：无 URL，直接统计（pretraining）
            channel = _resolve_citation_channel(cit)
            counts[channel] += 1

    total = sum(counts.values())
    return {
        "success": True,
        "data": {
            "pretraining": counts["pretraining"],
            "user_provided": counts["user_provided"],
            "web_search": counts["web_search"],
            "undetected": counts["undetected"],
            "total": total,
        },
    }


@router.get("/{run_id}/quality-check")
async def get_quality_check(run_id: str, model_key: Optional[str] = None,
                            task_id: Optional[str] = None):
    """抓取质量检查：逐题判定空回声/串题/首页噪声/搜索面板截断/过短/错误。

    只读, 不改 DB/评分。复用 core/webchat_quality.classify（与 CLI 脚本
    check_webchat_results.py 同源, 避免双份漂移）。
    task_id 模式: 按大任务聚合该模型(或全部模型)的 analysis_results,
        run_id 传 "0" 占位、不做 run 存在性校验（与 question-drilldown 同形）。
    model_key 不传: 查该 task/run 全部模型。
    """
    from webchat_quality import classify

    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    if not all_results:
        return {"success": True, "data": {"total": 0, "bad_count": 0, "by_model": {}, "bad": []}}

    # 关联 questions 表获取全题题干（串题判定需全题比对）
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = (row["question"] or "").strip()
    finally:
        await db_conn.close()

    # 按模型分组
    by_model_dict = {}
    for r in all_results:
        by_model_dict.setdefault(r.get("model_key", ""), []).append(r)

    by_model = {}
    bad_list = []
    for mk, results in by_model_dict.items():
        total = len(results)
        bad = 0
        types = {}
        for r in sorted(results, key=lambda x: x.get("question_id", "")):
            qid = r.get("question_id", "")
            raw = r.get("raw_content", "") or ""
            err = r.get("error_message", "") or ""
            qtext = question_map.get(qid, "")
            label, detail = classify(qid, raw, err, qtext, question_map, mk)
            if label != "OK":
                bad += 1
                types[label] = types.get(label, 0) + 1
                bad_list.append({
                    "model": mk,
                    "qid": qid,
                    "question_text": qtext,
                    "type": label,
                    "len": len(raw.strip()),
                    "head": raw[:60].replace("\n", " "),
                    "detail": detail,
                })
        by_model[mk] = {"total": total, "bad": bad, "types": types}

    return {
        "success": True,
        "data": {
            "total": sum(v["total"] for v in by_model.values()),
            "bad_count": len(bad_list),
            "by_model": by_model,
            "bad": bad_list,
        },
    }


# ============================================================
# 行动计划诊断端点（纯只读，不改任何分数）
# ============================================================
# 来源渠道权威性分层（纯展示用，不进分数判定）。
# 官方层走 brand_profile.is_official_url（当前品牌档案，不硬编码 UCloud）；
# 其余按域名关键词归层。
_AUTHORITY_REFERENCE_DOMAINS = [
    "github.com", "gitee.com", "wikipedia.org", "baike.baidu.com",
    "stackoverflow.com", "readthedocs.io", "pypi.org", "npmjs.com", "docs.rs",
]
_AUTHORITY_COMMUNITY_DOMAINS = [
    "zhihu.com", "csdn.net", "juejin.cn", "segmentfault.com", "cnblogs.com",
    "infoq.cn", "oschina.net", "oscimg.com", "mp.weixin.qq.com", "51cto.com",
    "jianshu.com",
]
_UGC_DOMAINS = [
    "toutiao.com", "baijiahao.baidu.com", "sohu.com", "163.com",
    "weibo.com", "xiaohongshu.com", "36kr.com", "iesdouyin.com", "douyin.com",
]


def _domain_of(url: str) -> str:
    try:
        d = urlparse(url).netloc.lower()
        if ":" in d:
            d = d.split(":")[0]
        if d.startswith("www."):
            d = d[4:]
        return d
    except Exception:
        return ""


def _authority_tier(url: str, profile) -> str:
    """把一条 URL 归入五类权威性分层（纯展示）。profile 为 brand_profile。"""
    if profile and profile.is_official_url(url):
        return "官方"
    d = _domain_of(url)
    if not d:
        return "未映射"
    if any(x in d for x in _AUTHORITY_REFERENCE_DOMAINS):
        return "权威参考"
    if any(x in d for x in _AUTHORITY_COMMUNITY_DOMAINS):
        return "权威社区"
    if any(x in d for x in _UGC_DOMAINS):
        return "一般UGC"
    # resolve_channel 命中"其他"的也算未映射
    try:
        from config import resolve_channel, DEFAULT_CHANNEL
        ch = resolve_channel(url)
        return "未映射" if ch == DEFAULT_CHANNEL else "其他已映射"
    except Exception:
        return "未映射"


def _guess_template_type(content: str) -> str:
    """根据回答正文启发式判断它用的是哪种'赢的结构'。"""
    if not content:
        return "常规"
    if len(content) > 6000 and ("一、" in content or "二、" in content or "三、" in content):
        return "选型指南型"
    # 表格分隔或对比
    if content.count("|") >= 6 or "对比" in content[:400] or "表格" in content[:400]:
        return "对比表格型"
    return "常规"


def _build_action_items(diag: dict, profile) -> list:
    """规则引擎：从聚合诊断数据生成 P0/P1/P2/P3 行动项。
    每条行动项 evidence 必须是真实算出来的数/题号。"""
    items = []
    by_cat = diag["by_category"]
    gap_qs = diag["gap_questions"]
    strength_qs = diag["strength_questions"]
    by_model = diag["by_model"]
    channels = diag["channels"]
    templates = diag["templates"]
    brand_name = (profile.brand_name if profile else "品牌") or "品牌"

    # P0-1: 洼地品类（引用率 0 或 自然题提及率 <20%）
    for c in by_cat:
        if c["n"] == 0:
            continue
        is_gap = (c["cited_pct"] == 0) or (c["mentioned_pct"] < 0.20)
        if not is_gap:
            continue
        cat = c["category"]
        cat_gaps = [g["qid"] for g in gap_qs if g["category"] == cat]
        evidence = (f"{cat}：自然题 {c['n']} 道，提及率 {c['mentioned_pct']*100:.0f}%、"
                    f"引用率 {c['cited_pct']*100:.0f}%、TOP3 {c['top3_pct']*100:.0f}%")
        actions = [f"用「选型指南型」模板做一篇 {cat} 完整排名长文，{brand_name} 排第一并给最强标签"]
        if cat_gaps:
            actions.append(f"先补这些全空白题：{', '.join(cat_gaps[:6])}")
        items.append({
            "priority": "P0",
            "title": f"补 {cat} 品类内容（洼地）",
            "evidence": evidence,
            "actions": actions,
        })

    # P0-2: 标杆复制（强项品类的模板往洼地搬）
    strong_cats = {}
    for s in strength_qs:
        strong_cats.setdefault(s["category"], []).append(s)
    for cat, sqs in strong_cats.items():
        # 找该品类用的模板类型
        cat_tpls = [t for t in templates if any(s["qid"] == t["qid"] for s in sqs)]
        tpl_type = cat_tpls[0]["template_type"] if cat_tpls else "选型指南型"
        # 找一个洼地品类作为目标
        target = next((c for c in by_cat
                       if c["category"] != cat and c["n"] > 0
                       and (c["cited_pct"] == 0 or c["mentioned_pct"] < 0.20)), None)
        if not target:
            continue
        evidence = (f"{cat} 已是强项（{len(sqs)} 道题 ≥3 模型提及），标杆模板：{tpl_type}；"
                    f"目标洼地：{target['category']}（引用率 {target['cited_pct']*100:.0f}%）")
        items.append({
            "priority": "P0",
            "title": f"把 {cat} 的「{tpl_type}」模板复制到 {target['category']}",
            "evidence": evidence,
            "actions": [
                f"参考标杆：{', '.join(s['qid'] for s in sqs[:3])}（{tpl_type}）",
                f"对 {target['category']} 的每道题套用同结构，{brand_name} 进对比表同列",
            ],
        })

    # P1-1: 每道强项题做对比表格内容
    for s in strength_qs[:5]:
        items.append({
            "priority": "P1",
            "title": f"扩大强项题 {s['qid']} 的内容覆盖",
            "evidence": f"{s['qid']}（{s['category']}）：{s['mention_models']}/5 模型已提及",
            "actions": [
                "做对比表格型内容，品牌进同列 + 价格硬数据",
                "首发 CSDN/知乎/官网 docs 三处（高质三方社区已被验证会引）",
            ],
        })

    # P1-2: 官网内容（官方占比低且仍有提及的模型）
    for m in by_model:
        if m["n"] == 0:
            continue
        if m["official_url_ratio"] < 0.10 and m["mentioned"] > 0:
            items.append({
                "priority": "P1",
                "title": f"官网 docs 补差异化段（针对 {m['model_key']}）",
                "evidence": (f"{m['model_key']}：官方URL占比仅 {m['official_url_ratio']*100:.0f}%，"
                             f"但提及率 {m['mentioned']/m['n']*100:.0f}%（仍有抓取能力）"),
                "actions": [
                    "每个产品 docs 页补「对比竞品差异化 + 独家卖点」段",
                    "H1 含品牌词 + 官网域名，便于该模型抓到带品牌词的页面",
                ],
            })

    # P1-3: 渠道映射补录（未映射 TOP5 域名）
    unmapped = [c for c in channels if c["tier"] in ("未映射", "其他已映射")]
    # 用域名级聚合（channels 已是 tier+channel 聚合，这里直接取未映射渠道 TOP5）
    top_unmapped = sorted(unmapped, key=lambda x: x["count"], reverse=True)[:5]
    if top_unmapped:
        names = [f"{c['channel']}({c['count']})" for c in top_unmapped]
        items.append({
            "priority": "P1",
            "title": "给高频未映射域名建渠道映射",
            "evidence": f"未映射/其他类占比较大，TOP5：{', '.join(names)}",
            "actions": [
                "在 core/config.py 的 URL_CHANNEL_MAPPING 补录这些域名（纯展示，不改分数）",
                "若其中有官方域名（如 ucloud-global.com），登记进 official_domains 需单独评估（会微调引用率）",
            ],
        })

    # P2: 弱模型（提及率 <20%）
    for m in by_model:
        if m["n"] == 0:
            continue
        if m["mentioned"] / m["n"] < 0.20:
            items.append({
                "priority": "P2",
                "title": f"针对弱模型 {m['model_key']} 铺内容",
                "evidence": f"{m['model_key']}：自然题提及率仅 {m['mentioned']/m['n']*100:.0f}%（{m['mentioned']}/{m['n']}）",
                "actions": [
                    f"{m['model_key']} 官方引用占比 {m['official_url_ratio']*100:.0f}%，主要靠正文知识而非官网",
                    "在知乎/CSDN 正文植入品牌词（不依赖官网被抓）",
                ],
            })

    # P3: 低质 UGC 只分发
    ugc = [c for c in channels if c["tier"] == "一般UGC"]
    top_ugc = sorted(ugc, key=lambda x: x["count"], reverse=True)[:3]
    if top_ugc:
        items.append({
            "priority": "P3",
            "title": "低质 UGC 渠道降优先级",
            "evidence": f"一般UGC被引TOP3：{', '.join(c['channel'] for c in top_ugc)}",
            "actions": ["只做分发不做原创，把力气挪到权威社区/官网 docs"],
        })

    # 排序：P0 → P1 → P2 → P3
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    items.sort(key=lambda x: order.get(x["priority"], 9))
    return items


@router.get("/{run_id}/action-plan")
async def get_action_plan(run_id: str, model_key: Optional[str] = None,
                          task_id: Optional[str] = None):
    """行动计划诊断（纯只读）：聚合自然题表现 + 渠道分布 + 标杆模板 + 数据驱动的行动项。

    不改 analysis_results / geo_scores / 任何分数。所有口径复用：
    - 自然题：db.is_natural_question
    - 有效引用：db.has_effective_citation
    - 渠道：config.resolve_channel + brand_profile.is_official_url

    task_id 模式：按大任务聚合（跨批次去重），run_id 传 "0" 占位、不做存在性校验
    （与 citation-breakdown / question-drilldown 同形）。
    """
    if task_id:
        all_results = await db.get_task_results(task_id, model_key)
    else:
        run = await db.get_run(run_id)
        if not run:
            raise HTTPException(404, "评测不存在")
        all_results = await db.get_results(run_id, model_key)

    if not all_results:
        return {"success": True, "data": {
            "task_id": task_id, "summary": {}, "by_model": [], "by_category": [],
            "gap_questions": [], "strength_questions": [], "channels": [],
            "templates": [], "action_items": [],
        }}

    # 关联 questions 表
    db_conn = await db.get_db()
    question_map = {}
    try:
        cursor = await db_conn.execute("SELECT id, question, category, question_type FROM questions")
        for row in await cursor.fetchall():
            question_map[row["id"]] = {
                "text": row["question"], "category": row["category"], "type": row["question_type"]
            }
    finally:
        await db_conn.close()

    profile = db.get_brand_profile()

    # 按 (qid) 收集每题各模型结果，用于判定"全空白/强项"
    by_qid = {}  # qid -> list of result rows (valid only)
    natural_qids = set()
    leading_qids = set()
    for r in all_results:
        qid = r.get("question_id", "")
        q_info = question_map.get(qid, {})
        q_text = q_info.get("text", "")
        q_cat = q_info.get("category", "")
        has_error = bool(r.get("error_message"))
        if has_error:
            continue
        is_nat = db.is_natural_question(q_text, q_cat)
        (natural_qids if is_nat else leading_qids).add(qid)
        by_qid.setdefault(qid, {"info": q_info, "results": [], "natural": is_nat})
        by_qid[qid]["results"].append(r)

    # ---- summary（自然题 vs 引导题）----
    nat_total = 0
    nat_mentioned = 0
    nat_cited = 0
    nat_top3 = 0
    for qid in natural_qids:
        for r in by_qid[qid]["results"]:
            nat_total += 1
            if r.get("ucloud_mentioned"):
                nat_mentioned += 1
            if db.has_effective_citation(r):
                nat_cited += 1
            rank = r.get("ucloud_rank")
            if rank is not None and rank <= 3:
                nat_top3 += 1
    summary = {
        "natural_total": nat_total,
        "natural_mentioned": nat_mentioned,
        "natural_cited": nat_cited,
        "natural_top3": nat_top3,
        "natural_mention_rate": round(nat_mentioned / nat_total, 4) if nat_total else 0,
        "natural_cite_rate": round(nat_cited / nat_total, 4) if nat_total else 0,
        "natural_top3_rate": round(nat_top3 / nat_total, 4) if nat_total else 0,
        "leading_total": sum(len(by_qid[q]["results"]) for q in leading_qids),
    }

    # ---- by_model ----
    model_agg = {}
    for qid, bucket in by_qid.items():
        if not bucket["natural"]:
            continue
        for r in bucket["results"]:
            mk = r.get("model_key", "")
            a = model_agg.setdefault(mk, {"model_key": mk, "n": 0, "mentioned": 0,
                                          "cited": 0, "top3": 0, "official_urls": 0, "total_urls": 0})
            a["n"] += 1
            if r.get("ucloud_mentioned"):
                a["mentioned"] += 1
            if db.has_effective_citation(r):
                a["cited"] += 1
            rank = r.get("ucloud_rank")
            if rank is not None and rank <= 3:
                a["top3"] += 1
            for u in _parse_json_field(r.get("all_cited_urls")):
                if not isinstance(u, dict) or u.get("citation_type") != "url":
                    continue
                url = u.get("content", "")
                if not url:
                    continue
                a["total_urls"] += 1
                if profile and profile.is_official_url(url):
                    a["official_urls"] += 1
    by_model = []
    for mk in ["deepseek", "ernie", "doubao", "kimi", "qwen"]:
        if mk not in model_agg:
            continue
        a = model_agg[mk]
        a["official_url_ratio"] = round(a["official_urls"] / a["total_urls"], 4) if a["total_urls"] else 0
        by_model.append(a)

    # ---- by_category（仅自然题）----
    cat_agg = {}
    cat_gap_qids = {}
    for qid, bucket in by_qid.items():
        if not bucket["natural"]:
            continue
        cat = bucket["info"].get("category", "") or "未分类"
        a = cat_agg.setdefault(cat, {"category": cat, "n": 0, "mentioned": 0,
                                     "cited": 0, "top3": 0, "qids": []})
        a["qids"].append(qid)
        for r in bucket["results"]:
            a["n"] += 1
            if r.get("ucloud_mentioned"):
                a["mentioned"] += 1
            if db.has_effective_citation(r):
                a["cited"] += 1
            rank = r.get("ucloud_rank")
            if rank is not None and rank <= 3:
                a["top3"] += 1
    by_category = []
    for cat, a in cat_agg.items():
        # 该品类下全空白题（5模型都未提及 —— 这里按"该题所有结果都未提及"）
        gap_in_cat = []
        for qid in a["qids"]:
            if all(not r.get("ucloud_mentioned") for r in by_qid[qid]["results"]):
                gap_in_cat.append(qid)
        by_category.append({
            "category": cat,
            "n": a["n"],
            "mentioned_pct": round(a["mentioned"] / a["n"], 4) if a["n"] else 0,
            "cited_pct": round(a["cited"] / a["n"], 4) if a["n"] else 0,
            "top3_pct": round(a["top3"] / a["n"], 4) if a["n"] else 0,
            "gap_qids": gap_in_cat,
        })
    by_category.sort(key=lambda x: x["cited_pct"])  # 洼地排前

    # ---- gap_questions / strength_questions ----
    gap_questions = []
    strength_questions = []
    for qid, bucket in by_qid.items():
        if not bucket["natural"]:
            continue
        mention_models = sum(1 for r in bucket["results"] if r.get("ucloud_mentioned"))
        total_models = len(bucket["results"])
        q_obj = {"qid": qid, "question": bucket["info"].get("text", ""),
                 "category": bucket["info"].get("category", ""), "mention_models": mention_models,
                 "total_models": total_models}
        if total_models > 0 and mention_models == 0:
            gap_questions.append(q_obj)
        elif mention_models >= 3:
            strength_questions.append(q_obj)

    # ---- channels（五 tier + 渠道名聚合）----
    chan_counter = {}  # (tier, channel) -> count
    for r in all_results:
        if r.get("error_message"):
            continue
        for u in _parse_json_field(r.get("all_cited_urls")):
            if not isinstance(u, dict) or u.get("citation_type") != "url":
                continue
            url = u.get("content", "")
            if not url:
                continue
            tier = _authority_tier(url, profile)
            try:
                from config import resolve_channel
                ch = resolve_channel(url)
            except Exception:
                ch = "其他"
            key = (tier, ch)
            chan_counter[key] = chan_counter.get(key, 0) + 1
    channels = [{"tier": t, "channel": c, "count": n}
                for (t, c), n in sorted(chan_counter.items(), key=lambda x: -x[1])]

    # ---- templates（自然题里 TOP3 最长胜出答案）----
    template_cands = []
    for qid, bucket in by_qid.items():
        if not bucket["natural"]:
            continue
        for r in bucket["results"]:
            if not r.get("ucloud_mentioned"):
                continue
            rank = r.get("ucloud_rank")
            if rank is None or rank > 3:
                continue
            content = r.get("raw_content", "") or ""
            template_cands.append({
                "qid": qid,
                "model": r.get("model_key", ""),
                "question": bucket["info"].get("text", ""),
                "category": bucket["info"].get("category", ""),
                "rank": rank,
                "strength": r.get("recommendation_strength", "none"),
                "len": len(content),
                "head": content[:400],
                "template_type": _guess_template_type(content),
            })
    template_cands.sort(key=lambda x: -x["len"])
    templates = template_cands[:3]

    diag = {
        "summary": summary,
        "by_model": by_model,
        "by_category": by_category,
        "gap_questions": gap_questions,
        "strength_questions": strength_questions,
        "channels": channels,
        "templates": templates,
    }
    action_items = _build_action_items(diag, profile)

    return {
        "success": True,
        "data": {
            "task_id": task_id,
            **diag,
            "action_items": action_items,
        },
    }


def _parse_json_field(raw):
    """把 DB 里 TEXT 存的 JSON 字段安全解析成 list。"""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return []