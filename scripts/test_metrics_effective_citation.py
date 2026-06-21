"""_has_effective_citation 口径自检（TDD RED→GREEN）。

bug：core/metrics.py _has_effective_citation 判定"官方引用"时只扫 result.citations，
但 analyzer 把【子域名】UCloud 官方 URL（astraflow.ucloud.cn / docs.ucloud.cn /
www-waf.ucloud.cn 等）放进 all_cited_urls（is_ucloud=True），因 url_patterns 只匹配
ucloud.cn / ucloud.com / ucloudstack.com 根域，子域名 URL 进不了 citations。
→ 这类响应官方 URL 明明在回答里，却被判无引用 → 引用率被压低。

口径（与定义一致）：
  有效引用 = UCloud 官方引用 OR (提及UCloud时的第三方来源引用)
  官方引用：citations 或 all_cited_urls 中任一 is_ucloud=True 即计入
"""
import os
import sys
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from analyzer import AnalysisResult, CitationInfo
from metrics import _has_effective_citation


def _url(content, is_ucloud=False, channel=""):
    return CitationInfo(citation_type="url", content=content, position=0,
                        source_channel=channel, is_ucloud=is_ucloud)


def _mk(mentioned=False, citations=None, all_cited_urls=None):
    return AnalysisResult(
        question_id="q", model_key="m", model_name="M",
        ucloud_mentioned=mentioned, citations=citations or [],
        all_cited_urls=all_cited_urls or [], raw_content="",
    )


def main():
    # A（RED 目标）：官方 URL 仅出现在 all_cited_urls（子域名情形）→ 应有效
    r = _mk(mentioned=True, citations=[],
            all_cited_urls=[_url("https://astraflow.ucloud.cn/v1/chat/completions", is_ucloud=True)])
    assert _has_effective_citation(r) is True, "子域名官方 URL（仅在 all_cited_urls）应计入有效引用"

    # B：官方 URL 在 citations → 有效（回归）
    r = _mk(mentioned=True,
            citations=[_url("https://www.ucloud.cn/site/product/gpu.html", is_ucloud=True)])
    assert _has_effective_citation(r) is True, "citations 中官方 URL 应有效"

    # C：提及 UCloud + 知乎第三方来源（在 citations）→ 有效（回归）
    r = _mk(mentioned=True,
            citations=[_url("https://zhuanlan.zhihu.com/p/123", is_ucloud=False)])
    assert _has_effective_citation(r) is True, "提及+第三方来源应有效"

    # D：无官方、无第三方 → 无效（回归）
    r = _mk(mentioned=False, citations=[],
            all_cited_urls=[_url("https://example.com/x", is_ucloud=False)])
    assert _has_effective_citation(r) is False, "无官方无第三方应无效"

    # E：官方 URL 在 all_cited_urls，未提及 UCloud → 仍有效（官方不要求提及）
    r = _mk(mentioned=False, citations=[],
            all_cited_urls=[_url("https://docs.ucloud.cn/api.html", is_ucloud=True)])
    assert _has_effective_citation(r) is True, "官方引用不要求提及 UCloud"

    # F：提及 + 官方仅在 all_cited_urls + citations 里只有非第三方 URL → 有效
    r = _mk(mentioned=True,
            citations=[_url("https://example.com/x", is_ucloud=False)],
            all_cited_urls=[_url("https://www-waf.ucloud.cn/site/product/ulhost.html", is_ucloud=True)])
    assert _has_effective_citation(r) is True, "子域名官方 URL 应让响应有效"

    print("✅ PASS: _has_effective_citation 官方引用扫 citations ∪ all_cited_urls（子域名官方 URL 不再漏判）")


if __name__ == "__main__":
    main()
