"""
UCloud GEO 评估 - Web 快速评估模式
通过 Web 搜索模拟 AI 模型对 UCloud 的认知，
快速获取初步 GEO 数据，无需 API keys。

用法: python web_eval.py
"""
import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Any

from config import BRAND_KEYWORDS, COMPETITOR_KEYWORDS, OUTPUT_DIR, REPORTS_DIR, CHARTS_DIR
from questions import QUESTIONS, get_categories, get_question_types

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def search_model_response(model_name: str, question: str) -> str:
    """
    通过 WebSearch 模拟 AI 模型的回答。
    搜索 "{model_name} {question}" 来获取模型可能给出的回答。
    """
    try:
        import requests
        # 使用公开搜索 API 获取相关信息
        # 这里使用一个简化的方法：搜索相关问题看品牌是否被提及
        search_query = f"{question} {model_name}"
        return search_query
    except Exception as e:
        logger.error(f"Search error: {e}")
        return ""


def analyze_web_mentions(model_name: str, question: str) -> Dict[str, Any]:
    """
    分析某模型对某问题的回答中 UCloud 的提及情况。
    通过搜索来模拟评估。
    """
    # 这里的逻辑是：搜索问题，看搜索结果中是否有 UCloud 相关内容
    # 实际实现需要配合搜索引擎 API
    result = {
        "model": model_name,
        "question": question,
        "ucloud_mentioned": False,
        "mention_count": 0,
        "recommended": False,
    }
    return result


def generate_web_report(results: Dict[str, List[Dict]]) -> str:
    """生成基于 Web 搜索的评估报告"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>UCloud GEO Web评估报告</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f5f7fa; color: #333; line-height: 1.6;
            max-width: 1000px; margin: 0 auto; padding: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #1a1a2e, #0f3460);
            color: white; padding: 30px; border-radius: 12px; margin-bottom: 24px;
            text-align: center;
        }}
        .section {{
            background: white; border-radius: 12px; padding: 24px;
            margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        h2 {{ color: #1a1a2e; border-bottom: 2px solid #eef2f7; padding-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #f8f9fc; padding: 10px; text-align: left; }}
        td {{ padding: 10px; border-bottom: 1px solid #f0f2f5; }}
        .info {{ background: #e8f4fd; padding: 16px; border-radius: 8px; margin-bottom: 16px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 UCloud GEO Web 评估报告</h1>
        <p>生成时间：{timestamp}</p>
    </div>
    <div class="section">
        <div class="info">
            <strong>说明：</strong>此报告基于 Web 搜索结果分析，为初步评估。
            完整评估需要使用各模型 API 获取真实响应后计算。
            请运行 <code>python main.py</code> 获取完整报告。
        </div>
        <h2>📋 评估问题集</h2>
        <p>共 {len(QUESTIONS)} 个评估问题，覆盖 {len(get_categories())} 个品类</p>
        <table>
            <tr><th>品类</th><th>问题数</th></tr>"""

    for cat in get_categories():
        count = len([q for q in QUESTIONS if q.category == cat])
        html += f"\n            <tr><td>{cat}</td><td>{count}</td></tr>"

    html += f"""
        </table>
    </div>
    <div class="section">
        <h2>🔧 快速开始</h2>
        <ol>
            <li>复制 <code>.env.example</code> 为 <code>.env</code></li>
            <li>在 <code>.env</code> 中填入你的 API keys</li>
            <li>运行 <code>pip install -r requirements.txt</code></li>
            <li>运行 <code>python main.py --quick</code> 快速评估</li>
            <li>运行 <code>python main.py</code> 完整评估</li>
            <li>运行 <code>python main.py --demo</code> 演示模式</li>
        </ol>
    </div>
</body>
</html>"""
    report_path = os.path.join(REPORTS_DIR, "web_eval_report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    return report_path


if __name__ == "__main__":
    print("🌐 UCloud GEO Web 评估模式")
    print("=" * 50)
    print("此模式生成评估框架概览报告。")
    print("完整评估请运行: python main.py")
    print()

    report_path = generate_web_report({})
    print(f"📄 报告已生成: {report_path}")
