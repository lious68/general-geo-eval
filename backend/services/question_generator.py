"""AI 问题生成服务

根据用户输入的品牌/公司/官网/行业，调用已配置的模型生成 GEO 评估题集：
- AI 按行业特性生成若干「场景」（category），每个场景恰好 5 个示例问题
- 问题覆盖品牌词/品类词/对比词/场景词四种类型
- 可含品牌词/公司名/产品型号，简洁模拟真实搜索意图
"""
import os
import sys
import json
import re
import logging
from typing import List, Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import config as cfg
import database as db
from model_clients import ModelClient
from brand_profile import derive_from_input

logger = logging.getLogger(__name__)

VALID_TYPES = ["品牌词", "品类词", "对比词", "场景词"]

SYSTEM_PROMPT = "你是 GEO（生成式引擎优化）评估题集设计专家，擅长根据品牌与行业设计贴近真实用户搜索意图的评测问题。"

USER_PROMPT_TEMPLATE = """请为以下被测品牌设计 GEO 评估问题集。

【被测品牌】品牌名：{brand_name}；公司名：{company_name}；官网：{website}；行业：{industry}

要求：
1. 结合「{industry}」行业特性，生成 {scenario_hint}个评估场景（每个场景是一个产品/需求类别，如"海外云主机""GPU""AI大模型"等，场景名要贴合该行业真实用户关注点）。
2. 每个场景【恰好 5 个】示例问题，不多不少，共 {scenario_hint}×5 个问题。
3. 5 个问题需覆盖以下 4 种问题类型（question_type 字段取值之一）：品牌词、品类词、对比词、场景词。
   - 品牌词：题干直接包含「{brand_name}」或公司名/产品型号（如"{brand_name}海外云主机怎么样？"）
   - 品类词：围绕品类做泛需求搜索（如"便宜的海外VPS推荐哪家？"）
   - 对比词：排名/价格/区别/对比/怎么选等比较型问题（如"{brand_name}和阿里云哪个更好？"）
   - 场景词：具体业务场景问题（如"游戏公司上云推荐什么云服务？"）
4. 问题要简洁、口语化，模拟真实用户在 AI 搜索框里的搜索意图，不要长篇大论。
5. 部分问题可包含「{brand_name}」品牌词、公司名或具体产品型号，但不要每题都带品牌词（保证有足够"自然问题"用于提及率统计）。
6. 严格只输出一个 JSON 数组，不要任何解释、不要 markdown 代码块标记。每个元素格式：
   {{"category": "场景名", "question_type": "品牌词|品类词|对比词|场景词", "question": "问题文本", "tags": ["标签1","标签2"]}}

现在请输出 JSON 数组：
"""


def _build_prompt(brand_name: str, company_name: str, website: str, industry: str,
                  scenario_count: Optional[int]) -> str:
    if scenario_count and scenario_count > 0:
        hint = f"{scenario_count} "
    else:
        hint = "8~12 "
    return USER_PROMPT_TEMPLATE.format(
        brand_name=brand_name, company_name=company_name or "（未提供）",
        website=website or "（未提供）", industry=industry or "通用", scenario_hint=hint,
    )


def _strip_code_fence(text: str) -> str:
    """去掉模型可能包裹的 ```json ... ``` 代码块标记。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉首行 ```xxx
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # 兜底：截取第一个 [ 到最后一个 ]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return text


def _parse_questions(content: str) -> List[Dict]:
    """解析模型输出为问题列表，校验并规整字段。"""
    raw = _strip_code_fence(content or "")
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"模型输出不是合法 JSON：{e}；原文前200字：{raw[:200]}")
    if not isinstance(items, list):
        raise ValueError("模型输出不是 JSON 数组")

    cleaned = []
    for it in items:
        if not isinstance(it, dict):
            continue
        qtext = (it.get("question") or "").strip()
        category = (it.get("category") or "").strip() or "未分类"
        qtype = (it.get("question_type") or "").strip()
        if qtype not in VALID_TYPES:
            # 兜底归类
            qtype = "品类词"
        tags = it.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        if not qtext:
            continue
        cleaned.append({
            "category": category,
            "question_type": qtype,
            "question": qtext,
            "tags": tags,
        })
    return cleaned


def _enforce_five_per_scenario(items: List[Dict]) -> tuple[List[Dict], Dict[str, int]]:
    """每个场景恰好 5 题：超过则截断到 5，不足则记录告警。返回 (规整后列表, 每场景原始计数)。"""
    by_cat: Dict[str, List[Dict]] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    raw_counts = {c: len(v) for c, v in by_cat.items()}
    out: List[Dict] = []
    for cat, qs in by_cat.items():
        if len(qs) > 5:
            logger.warning(f"场景「{cat}」生成 {len(qs)} 题，截断为 5 题")
            qs = qs[:5]
        elif len(qs) < 5:
            logger.warning(f"场景「{cat}」仅生成 {len(qs)} 题（不足 5）")
        out.extend(qs)
    return out, raw_counts


async def generate_questions(brand_name: str, company_name: str = "", website: str = "",
                             industry: str = "", model_key: str = "deepseek",
                             scenario_count: Optional[int] = None) -> Dict:
    """调用已配置模型生成题集。返回 {questions, scenarios, raw_counts, model_key}。"""
    brand_name = (brand_name or "").strip()
    if not brand_name:
        raise ValueError("品牌名不能为空")
    if model_key not in cfg.MODELS:
        raise ValueError(f"未知模型: {model_key}")

    # 从 DB 读取该模型的 API Key / base_url / model 并应用到 config + env
    saved_key = await db.get_setting(f"api_key_{model_key}", "")
    if not saved_key:
        raise ValueError(f"模型 {cfg.MODELS[model_key]['name']} 未配置 API Key，请先在「系统设置」配置")
    saved_url = await db.get_setting(f"base_url_{model_key}", "")
    saved_model = await db.get_setting(f"model_{model_key}", "")
    if saved_key:
        os.environ[cfg.MODELS[model_key]["api_key_env"]] = saved_key
    if saved_url:
        cfg.MODELS[model_key]["base_url"] = saved_url
    if saved_model:
        cfg.MODELS[model_key]["model"] = saved_model

    client = ModelClient(model_key)
    if not client.is_configured:
        raise ValueError(f"模型 {cfg.MODELS[model_key]['name']} 初始化失败，请检查 API Key 配置")

    prompt = _build_prompt(brand_name, company_name, website, industry, scenario_count)
    resp = client.chat(prompt, system_prompt=SYSTEM_PROMPT, enable_search=False)
    if resp.get("error"):
        raise ValueError(f"模型调用失败: {resp['error']}")
    content = resp.get("content", "")

    items = _parse_questions(content)
    if not items:
        raise ValueError("模型未生成任何有效问题，请重试或换一个模型")

    items, raw_counts = _enforce_five_per_scenario(items)
    scenarios = list(dict.fromkeys(it["category"] for it in items))

    return {
        "questions": items,
        "scenarios": scenarios,
        "raw_counts": raw_counts,
        "model_key": model_key,
        "model_name": cfg.MODELS[model_key]["name"],
    }


async def generate_and_replace(brand_name: str, company_name: str = "", website: str = "",
                               industry: str = "", model_key: str = "deepseek",
                               scenario_count: Optional[int] = None) -> Dict:
    """生成题集 → 替换当前激活题集 → 同步品牌档案。返回汇总信息。"""
    result = await generate_questions(brand_name, company_name, website, industry, model_key, scenario_count)

    # 1. 同步品牌档案（分析口径必须与题集品牌一致）
    profile = derive_from_input(brand_name, company_name, website, industry)
    await db.save_brand_profile(profile)

    # 2. 清场 + 写入新题（按场景顺序分配 gen_001..）
    await db.deactivate_all_questions()
    idx = 0
    for it in result["questions"]:
        idx += 1
        qid = f"gen_{idx:03d}"
        await db.upsert_question({
            "id": qid,
            "category": it["category"],
            "question_type": it["question_type"],
            "question": it["question"],
            "tags": it["tags"],
            "difficulty": "medium",
        })

    return {
        "generated": len(result["questions"]),
        "scenarios": len(result["scenarios"]),
        "scenario_names": result["scenarios"],
        "raw_counts": result["raw_counts"],
        "model_key": result["model_key"],
        "model_name": result["model_name"],
        "brand_profile": profile.to_dict(),
    }
