"""
UCloud GEO Web - ECharts 图表 JSON 构建器
替代 matplotlib，生成 ECharts option JSON 供前端渲染
"""
from typing import Dict, List, Any


def build_radar_option(scores_list: List[Dict]) -> Dict:
    """雷达图：5维指标对比"""
    categories = ["覆盖率", "提及率", "引用率", "推荐率", "情感值"]
    colors = ["#0f3460", "#e94560", "#533483", "#f5a623", "#7ed321"]

    series_data = []
    for i, s in enumerate(scores_list):
        values = [
            round(s["coverage_rate"], 3),
            round(min(s["mention_rate"] / 3.0, 1.0), 3),
            round(s["citation_rate"], 3),
            round(s["recommendation_rate"], 3),
            round(s["sentiment_score"], 3),
        ]
        series_data.append({
            "value": values,
            "name": s["model_name"],
            "itemStyle": {"color": colors[i % len(colors)]},
            "areaStyle": {"opacity": 0.1},
        })

    return {
        "title": {"text": "UCloud GEO 多维度雷达图", "left": "center", "top": 10},
        "tooltip": {"trigger": "item"},
        "legend": {"bottom": 10, "data": [s["model_name"] for s in scores_list]},
        "radar": {
            "indicator": [{"name": c, "max": 1} for c in categories],
            "radius": "60%",
        },
        "series": [{
            "type": "radar",
            "data": series_data,
        }],
    }


def build_bar_option(scores_list: List[Dict]) -> Dict:
    """柱状图：GEO综合得分"""
    colors = ["#0f3460", "#16213e", "#1a1a2e", "#533483", "#e94560"]
    names = [s["model_name"] for s in scores_list]
    values = [round(s["geo_score"], 1) for s in scores_list]

    return {
        "title": {"text": "GEO 综合得分对比", "left": "center"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "category", "data": names, "axisLabel": {"fontSize": 14}},
        "yAxis": {"type": "value", "name": "GEO Score", "max": lambda: max(values) * 1.3 + 5},
        "series": [{
            "type": "bar",
            "data": [{"value": v, "itemStyle": {"color": colors[i % len(colors)]}}
                     for i, v in enumerate(values)],
            "barWidth": "50%",
            "label": {"show": True, "position": "top", "fontSize": 14, "fontWeight": "bold"},
        }],
    }


def build_coverage_option(scores_list: List[Dict]) -> Dict:
    """分组柱状图：覆盖率/引用率/推荐率"""
    colors = ["#0f3460", "#e94560", "#533483"]
    names = [s["model_name"] for s in scores_list]

    return {
        "title": {"text": "核心指标对比", "left": "center"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"bottom": 0, "data": ["覆盖率", "引用率", "推荐率"]},
        "xAxis": {"type": "category", "data": names},
        "yAxis": {"type": "value", "name": "%", "axisLabel": {"formatter": "{value}%"}},
        "series": [
            {
                "name": "覆盖率",
                "type": "bar",
                "data": [round(s["coverage_rate"] * 100, 1) for s in scores_list],
                "itemStyle": {"color": colors[0]},
                "label": {"show": True, "position": "top", "formatter": "{c}%"},
            },
            {
                "name": "引用率",
                "type": "bar",
                "data": [round(s["citation_rate"] * 100, 1) for s in scores_list],
                "itemStyle": {"color": colors[1]},
                "label": {"show": True, "position": "top", "formatter": "{c}%"},
            },
            {
                "name": "推荐率",
                "type": "bar",
                "data": [round(s["recommendation_rate"] * 100, 1) for s in scores_list],
                "itemStyle": {"color": colors[2]},
                "label": {"show": True, "position": "top", "formatter": "{c}%"},
            },
        ],
    }


def build_sentiment_option(results_by_model: Dict[str, List[Dict]]) -> Dict:
    """堆叠柱状图：情感分布"""
    colors = {"positive": "#7ed321", "neutral": "#f5a623", "negative": "#e94560"}
    model_names = []
    pos_data, neu_data, neg_data = [], [], []

    for mk, results in results_by_model.items():
        if not results:
            continue
        name = results[0].get("model_name", mk)
        model_names.append(name)
        mentioned = [r for r in results if r.get("ucloud_mentioned") and not r.get("error_message")]
        total = len(mentioned) or 1
        pos_data.append(round(sum(1 for r in mentioned if r.get("sentiment_label") == "positive") / total * 100, 1))
        neu_data.append(round(sum(1 for r in mentioned if r.get("sentiment_label") == "neutral") / total * 100, 1))
        neg_data.append(round(sum(1 for r in mentioned if r.get("sentiment_label") == "negative") / total * 100, 1))

    return {
        "title": {"text": "UCloud 情感分布", "left": "center"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "formatter": "{b}<br/>{a0}: {c0}%<br/>{a1}: {c1}%<br/>{a2}: {c2}%"},
        "legend": {"bottom": 0, "data": ["正面", "中性", "负面"]},
        "xAxis": {"type": "category", "data": model_names},
        "yAxis": {"type": "value", "name": "%", "max": 100},
        "series": [
            {"name": "正面", "type": "bar", "stack": "total", "data": pos_data, "itemStyle": {"color": colors["positive"]}},
            {"name": "中性", "type": "bar", "stack": "total", "data": neu_data, "itemStyle": {"color": colors["neutral"]}},
            {"name": "负面", "type": "bar", "stack": "total", "data": neg_data, "itemStyle": {"color": colors["negative"]}},
        ],
    }


def build_heatmap_option(category_scores: List[Dict]) -> Dict:
    """热力图：品类×模型 GEO得分"""
    if not category_scores:
        return {"title": {"text": "品类分析（暂无数据）"}}

    # 提取唯一的品类和模型
    categories = list(dict.fromkeys(s["category"] for s in category_scores if s.get("category")))
    models = list(dict.fromkeys(s["model_name"] for s in category_scores))

    # 构建数据矩阵
    data = []
    for i, cat in enumerate(categories):
        for j, model in enumerate(models):
            for s in category_scores:
                if s.get("category") == cat and s.get("model_name") == model:
                    data.append([j, i, round(s["geo_score"], 1)])
                    break

    return {
        "title": {"text": "品类 × 模型 GEO得分热力图", "left": "center"},
        "tooltip": {"position": "top", "formatter": lambda p: f"{models[p.data[0]]} × {categories[p.data[1]]}: {p.data[2]}"},
        "xAxis": {"type": "category", "data": models, "splitArea": {"show": True}},
        "yAxis": {"type": "category", "data": categories, "splitArea": {"show": True}},
        "visualMap": {"min": 0, "max": 100, "calculable": True, "orient": "horizontal", "left": "center", "bottom": 0},
        "series": [{
            "type": "heatmap",
            "data": data,
            "label": {"show": True},
        }],
    }
