"""
通用品牌档案（BrandProfile）

把"当前被测品牌"的全部信息集中到一个对象里，替代散落在 analyzer / metrics /
database / eval_runner 各处的 UCloud 硬编码。

- 单品牌部署：档案存于后端 app_settings（key=brand_profile），首页输入后派生。
- 向后兼容：未设置档案时 fallback 到 default_brand_profile()（UCloud），旧数据与 CLI 不受影响。
- 本地 runner：档案由 task_config.json 透传，不依赖后端 DB。
"""
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse


@dataclass
class BrandProfile:
    """被测品牌档案。字段名 is_ucloud 在调用方仍沿用旧名，语义=「是否被测品牌官方引用」。"""

    brand_name: str = ""
    company_name: str = ""
    website: str = ""
    industry: str = ""
    keywords: Dict[str, List[str]] = field(
        default_factory=lambda: {"primary": [], "products": [], "flagship": [], "aliases": []}
    )
    official_domains: List[str] = field(default_factory=list)      # 小写根域名，如 ucloud.cn
    url_patterns: List[str] = field(default_factory=list)          # 正则字符串，用于官方 URL 匹配
    reference_keywords: List[str] = field(default_factory=list)    # 如 "据UCloud"、"UCloud官网"
    display_names: List[str] = field(default_factory=list)         # 推荐检测用的品牌文本名

    # ---------- 序列化 ----------
    def to_dict(self) -> Dict:
        return {
            "brand_name": self.brand_name,
            "company_name": self.company_name,
            "website": self.website,
            "industry": self.industry,
            "keywords": self.keywords,
            "official_domains": self.official_domains,
            "url_patterns": self.url_patterns,
            "reference_keywords": self.reference_keywords,
            "display_names": self.display_names,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "BrandProfile":
        d = d or {}
        kw = d.get("keywords") or {}
        return cls(
            brand_name=d.get("brand_name", ""),
            company_name=d.get("company_name", ""),
            website=d.get("website", ""),
            industry=d.get("industry", ""),
            keywords={
                "primary": list(kw.get("primary", [])),
                "products": list(kw.get("products", [])),
                "flagship": list(kw.get("flagship", [])),
                "aliases": list(kw.get("aliases", [])),
            },
            official_domains=list(d.get("official_domains", [])),
            url_patterns=list(d.get("url_patterns", [])),
            reference_keywords=list(d.get("reference_keywords", [])),
            display_names=list(d.get("display_names", [])),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    # ---------- 派生查询 ----------
    def is_official_url(self, url: str) -> bool:
        """URL 是否命中被测品牌官方域名（替代写死的 'ucloud' in url）。"""
        u = (url or "").lower()
        return any(d and d in u for d in self.official_domains)

    def question_keywords(self) -> List[str]:
        """自然问题过滤用的关键词：primary + aliases（题干含这些词视为引导型/非自然问题）。"""
        kws = list(self.keywords.get("primary", [])) + list(self.keywords.get("aliases", []))
        return list(dict.fromkeys(k for k in kws if k))

    def context_keywords(self) -> List[str]:
        """引用上下文匹配用的关键词：primary + products + aliases。"""
        kws = (
            list(self.keywords.get("primary", []))
            + list(self.keywords.get("products", []))
            + list(self.keywords.get("aliases", []))
        )
        return list(dict.fromkeys(k for k in kws if k))


# ============================================================
# 派生 / 默认档案
# ============================================================

def _extract_domain(url: str) -> str:
    """从网址提取小写根域名（去 www、去端口）。"""
    if not url:
        return ""
    u = url.strip()
    if "://" not in u:
        u = "http://" + u
    netloc = urlparse(u).netloc.lower()
    if ":" in netloc:
        netloc = netloc.split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def derive_from_input(brand_name: str, company_name: str = "",
                      website: str = "", industry: str = "") -> BrandProfile:
    """根据用户输入的品牌/公司/官网/行业，自动派生关键词、官方域名、引用规则。

    products / flagship 默认留空，用户可在系统设置里补充具体产品型号。
    """
    brand_name = (brand_name or "").strip()
    company_name = (company_name or "").strip()
    website = (website or "").strip()
    industry = (industry or "").strip()

    # ---- primary / aliases ----
    primary: List[str] = []
    if brand_name:
        primary.append(brand_name)
        if brand_name.isascii():
            primary.append(brand_name.lower())
    if company_name and company_name not in primary:
        primary.append(company_name)

    aliases: List[str] = []
    if brand_name and company_name:
        aliases.append(f"{brand_name}{company_name}")
        aliases.append(f"{company_name}{brand_name}")

    # ---- 官方域名 / URL 正则 ----
    official_domains: List[str] = []
    domain = _extract_domain(website)
    if domain:
        official_domains.append(domain)
    url_patterns = [f"https?://(www\\.)?{re.escape(d)}" for d in official_domains]

    # ---- 参考引用关键词 ----
    name = brand_name or company_name
    reference_keywords: List[str] = []
    if name:
        reference_keywords = [
            f"据{name}", f"{name}官网", f"{name}数据显示",
            f"根据{name}", f"{name}报告", f"{name}官方",
        ]

    # ---- 推荐检测用品牌名 ----
    display_names = list(dict.fromkeys(
        [n for n in [brand_name, company_name] + aliases if n]
    ))

    return BrandProfile(
        brand_name=brand_name,
        company_name=company_name,
        website=website,
        industry=industry,
        keywords={
            "primary": list(dict.fromkeys(primary)),
            "products": [],
            "flagship": [],
            "aliases": list(dict.fromkeys(aliases)),
        },
        official_domains=official_domains,
        url_patterns=url_patterns,
        reference_keywords=reference_keywords,
        display_names=display_names,
    )


def default_brand_profile() -> BrandProfile:
    """UCloud 默认档案（向后兼容：未设置品牌时使用，旧数据/CLI 不受影响）。"""
    import config  # core/config.py
    citation = config.SCORE_CONFIG.get("citation", {})
    # 从现有 url_patterns 反推官方域名（patterns 里点是转义的 \\.，先还原）
    official_domains: List[str] = []
    for pat in citation.get("url_patterns", []):
        pat_clean = pat.replace(r"\.", ".")
        m = re.search(r"([a-z0-9][a-z0-9.-]*\.[a-z]{2,})", pat_clean, re.IGNORECASE)
        if m:
            d = m.group(1).lower()
            if d.startswith("www."):
                d = d[4:]
            if d not in official_domains:
                official_domains.append(d)
    primary = list(config.BRAND_KEYWORDS.get("primary", []))
    aliases = list(config.BRAND_KEYWORDS.get("aliases", []))
    display_names = list(dict.fromkeys(
        [n for n in primary + aliases if n]
    ))
    return BrandProfile(
        brand_name="UCloud",
        company_name="优刻得",
        website="https://www.ucloud.cn",
        industry="云计算",
        keywords={
            "primary": primary,
            "products": list(config.BRAND_KEYWORDS.get("products", [])),
            "flagship": list(config.BRAND_KEYWORDS.get("flagship", [])),
            "aliases": aliases,
        },
        official_domains=official_domains,
        url_patterns=list(citation.get("url_patterns", [])),
        reference_keywords=list(citation.get("reference_keywords", [])),
        display_names=display_names,
    )


# ============================================================
# 自然问题判定（替代散落各处的 ucloud|优刻得 正则）
# ============================================================

def build_keyword_pattern(keywords: List[str]) -> re.Pattern:
    """编译关键词 alternation 正则（空列表→永不匹配）。"""
    parts = [re.escape(k) for k in keywords if k]
    if not parts:
        return re.compile(r"(?!x)x")  # 永不匹配
    return re.compile("|".join(parts), re.IGNORECASE)


def is_natural_question(question: str, category: str = "",
                        profile: Optional[BrandProfile] = None) -> bool:
    """非引导型、且题干不含被测品牌词时，视为自然问题。

    profile 为 None 时使用 UCloud 默认档案（向后兼容）。
    """
    if category == "引导型":
        return False
    if profile is None:
        profile = default_brand_profile()
    pattern = build_keyword_pattern(profile.question_keywords())
    return not pattern.search(question or "")


if __name__ == "__main__":
    # 自检
    p = derive_from_input("Acme云", "阿克米科技", "https://www.acme-cloud.cn", "云计算")
    print("brand:", p.brand_name, "| domains:", p.official_domains)
    print("url_patterns:", p.url_patterns)
    print("reference_keywords:", p.reference_keywords)
    print("display_names:", p.display_names)
    print("is_official_url(https://www.acme-cloud.cn/pricing):", p.is_official_url("https://www.acme-cloud.cn/pricing"))
    print("natural('Acme云怎么样？', ''):", is_natural_question("Acme云怎么样？", "", p))
    print("natural('国内云服务器推荐哪家？', ''):", is_natural_question("国内云服务器推荐哪家？", "", p))
    d = default_brand_profile()
    print("default brand:", d.brand_name, "| domains:", d.official_domains[:3])
    print("default natural('UCloud海外云主机怎么样？'):", is_natural_question("UCloud海外云主机怎么样？", "", d))
