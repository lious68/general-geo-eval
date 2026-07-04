"""WebChat 抓取质量判定核心 — 后端接口与 CLI 脚本共用，避免双份漂移。

判定 6 类质量问题(基于已修 bug 的真实形态), 每题命中其一即标坏:
  ERROR              error_message 非空 或 raw 为空 (runner 异常/未抓到)
  EMPTY_ECHO 空回声  raw ≈ 题干本身 (抓到 user 题干回显, 豆包 77d0544)
  CROSS_QUESTION 串题 raw 首行 == 另一道题的题干 (抓到上一题残留气泡, 豆包 77d0544)
  NOISE 首页噪声     raw 前200字含首页推荐流标记且<400字 (豆包抓首页流, 77d0544)
  SEARCH_PANEL_TRUNC  kimi 专属: raw 含"搜索网页"+"个结果"且<150字 (kimi 34ecfca)
  TOO_SHORT 过短     <120字且不含UCloud词+不含搜索元数据 (慢启动截断/答非所问兜底)

纯函数无副作用, 不依赖 Playwright/DB, 供 backend/routers/results.py 与
scripts/check_webchat_results.py 共用。
"""

HOMEPAGE_MARKERS = ["新对话", "有什么我能帮你的吗", "资讯：", "AI 生成可能有误", "请核实"]
UCLOUD_MARKERS = ["UCloud", "优刻得", "U云", "UCLOUD"]
# 搜索元数据标记(各模型搜索题正文前会出现, 用于 TOO_SHORT 排除搜索题)
SEARCH_META_MARKERS = ["搜索网页", "个结果", "搜索关键词", "参考资料", "参考", "篇资料"]


def classify(qid, raw, error, qtext, all_qtext, model_key):
    """判定单题质量。返回 (label, detail) 或 ('OK', None)。

    判定顺序: ERROR → EMPTY_ECHO → CROSS_QUESTION → NOISE →
              SEARCH_PANEL_TRUNC → TOO_SHORT, 命中即停(一题一主问题)。

    Args:
        qid: 题号
        raw: raw_content 文本
        error: error_message
        qtext: 本题题干
        all_qtext: {qid: 题干} 全题映射, 供串题比对
        model_key: 模型键(SEARCH_PANEL_TRUNC 仅对 kimi 判)
    """
    raw = (raw or "").strip()
    err = (error or "").strip()
    n = len(raw)
    q = (qtext or "").strip()

    # 1 ERROR: 有错误 或 空
    if err:
        return "ERROR", err[:80]
    if n == 0:
        return "ERROR", "raw_content 为空"

    # 2 EMPTY_ECHO 空回声: raw ≈ 题干本身
    if q and n <= len(q) + 8 and (raw == q or raw.startswith(q)):
        return "EMPTY_ECHO", f"raw≈题干({n}字)"

    # 3 CROSS_QUESTION 串题: 首行 == 他题题干
    # 真串题特征(0630 q006): 首行就是另一题的完整题干(短、常带问号)。
    # 误报排除:
    #   a) 首行以【本题】题干开头 → 是回答回显题干(豆包正常格式"题干+搜索元数据+正文"),
    #      不是串题。
    #   b) 首行虽以他题题干前缀开头, 但首行比他题题干长很多 → 是正常展开的长答案
    #      (如 deepseek q037 首行"API中转站…的核心区别在于…"撞了题库里另一题前缀),
    #      非串题。只有首行≈他题题干本身(≤他题干+4字)才算串题。
    first_line = raw.split("\n", 1)[0].strip()[:40]
    if q and not first_line.startswith(q):  # 排除 a) 本题题干回显
        for other, oq in all_qtext.items():
            if other == qid or len(oq) < 8:
                continue
            if first_line.startswith(oq[:12]) and len(first_line) <= len(oq) + 4:
                return "CROSS_QUESTION", f"首行={other}题干"

    # 4 NOISE 首页噪声: 前200字含首页标记且<400字
    if n < 400 and any(m in raw[:200] for m in HOMEPAGE_MARKERS):
        return "NOISE", "含首页推荐流标记"

    # 5 SEARCH_PANEL_TRUNC: kimi 专属, 搜索面板截断
    if model_key == "kimi":
        head60 = raw[:60]
        if "搜索网页" in head60 and "个结果" in raw[:80] and n < 150:
            return "SEARCH_PANEL_TRUNC", f"只抓到搜索面板({n}字)"

    # 6 TOO_SHORT 过短: <120字且不含UCloud词+不含搜索元数据
    if n < 120:
        has_ucloud = any(m in raw for m in UCLOUD_MARKERS)
        has_meta = any(m in raw for m in SEARCH_META_MARKERS)
        if not has_ucloud and not has_meta:
            return "TOO_SHORT", f"过短且无实质内容({n}字)"

    return "OK", None


def type_tag_type(label):
    """el-tag / 标签着色映射: 返回 Element Plus tag type 字符串。"""
    return {
        "ERROR": "danger",
        "EMPTY_ECHO": "danger",
        "TOO_SHORT": "danger",
        "CROSS_QUESTION": "warning",
        "NOISE": "warning",
        "SEARCH_PANEL_TRUNC": "info",
    }.get(label, "")


def type_label_cn(label):
    """问题类型中文标签。"""
    return {
        "ERROR": "错误/空",
        "EMPTY_ECHO": "空回声",
        "CROSS_QUESTION": "串题",
        "NOISE": "首页噪声",
        "SEARCH_PANEL_TRUNC": "搜索面板截断",
        "TOO_SHORT": "过短",
    }.get(label, label)
