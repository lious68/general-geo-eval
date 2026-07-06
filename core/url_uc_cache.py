"""引用 URL「是否出现 UCloud/优刻得」缓存 + 抓取判定。

判定语义：抓取该 URL 的网页正文（纯文本），是否包含被测品牌本体关键词
（UCloud / ucloud / 优刻得 / 优刻得科技 / 688158）。不含产品歧义词（星图/快杰/中立云），
避免「星图、阿里云通义」这类同名词误判（见 0630 q040）。

设计要点：
- 缓存表 url_uc_cache 以 URL 为主键，跨 task/run/模型 复用，同一 URL 只抓一次。
- UCloud 官方域名（ucloud.cn/ucloud.com/ucloudstack.com/compshare.com）短路判 True，不抓。
- 抓取失败（超时/反爬/非HTML）写 status='fetch_failed'，mentions_uc=NULL，前端显示「未检测」。
- 抓取在调用方进程内同步进行（Linux 后端进程或 Windows 回填脚本都可调用同一函数）。
"""
import asyncio
import re
from typing import Optional
from urllib.parse import urlparse

try:
    import httpx
except ImportError:  # 仅在无 httpx 环境下回退（不应发生在 venv 里）
    httpx = None

# 被测品牌本体关键词（不含产品歧义词）
UC_KEYWORDS = re.compile(
    r"UCloud|ucloud|优刻得|优刻得科技|688158",
    re.IGNORECASE,
)

# UCloud 官方域名 —— 直接判 True，无需抓取
UC_OFFICIAL_DOMAINS = re.compile(
    r"(^|\.)(ucloud\.cn|ucloud\.com|ucloudstack\.com|compshare\.com)$",
    re.IGNORECASE,
)

# 真实浏览器 UA，降低被反爬拦截概率
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 抓取参数：超时 12s，最多重试 1 次，整体并发限 8
_FETCH_TIMEOUT = 12.0
_MAX_RETRIES = 1
_MAX_CONCURRENCY = 8


def is_uc_official_url(url: str) -> bool:
    """URL 是否 UCloud 官方域名 → 无需抓取，直接判 True。"""
    try:
        netloc = urlparse(url).netloc.lower().split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return bool(UC_OFFICIAL_DOMAINS.search(netloc))
    except Exception:
        return False


def _text_from_html(html: str) -> str:
    """粗暴去标签：把 <script>/<style> 整块删掉再 strip 标签。

    只判关键词是否出现，不需要精确正文，所以用快速正则而非 BeautifulSoup，
    避免 venv 引入额外依赖。"""
    if not html:
        return ""
    # 删 script/style/noscript 块
    html = re.sub(r"<(script|style|noscript)\b[^>]*>.*?</\1>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    # 删所有标签
    text = re.sub(r"<[^>]+>", " ", html)
    # HTML 实体简单还原（够用即可）
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return text


async def fetch_url_mentions_uc(url: str) -> Optional[bool]:
    """抓取单个 URL，判定正文是否含 UCloud 关键词。

    返回：
        True  = 文章出现 UCloud/优刻得
        False = 抓到了但没出现
        None  = 抓取失败（超时/反爬/非HTML/网络错）
    """
    if httpx is None:
        return None
    # 官方域名短路
    if is_uc_official_url(url):
        return True

    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT,
                follow_redirects=True,
                headers=_HEADERS,
                verify=False,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    last_err = f"http {resp.status_code}"
                    continue
                ctype = resp.headers.get("content-type", "")
                if "html" not in ctype.lower():
                    # 非 HTML（PDF/图片/json 等）—— 不抓正文，判 None
                    return None
                # 编码：优先 resp.encoding，回退 utf-8（中文站常见）
                try:
                    text = resp.content.decode(resp.encoding or "utf-8", errors="replace")
                except (LookupError, TypeError):
                    text = resp.content.decode("utf-8", errors="replace")
                body = _text_from_html(text)
                return bool(UC_KEYWORDS.search(body))
        except (httpx.TimeoutException, httpx.HTTPError, Exception) as e:
            last_err = type(e).__name__
            continue
    # 全部重试失败
    return None


# ── DB 缓存读写（延迟 import database，避免 core 依赖 backend） ──

async def _get_cache_conn():
    import database as db
    return await db.get_db()


async def get_cached_mentions_uc(url: str):
    """读缓存。返回 (mentions_uc: Optional[bool], status: str) 或 (None, 'not_cached')。"""
    db = await _get_cache_conn()
    try:
        cur = await db.execute(
            "SELECT mentions_uc, status FROM url_uc_cache WHERE url=?", (url,))
        row = await cur.fetchone()
        if row:
            return row["mentions_uc"], row["status"]
        return None, "not_cached"
    finally:
        await db.close()


async def save_cached_mentions_uc(url: str, mentions_uc, status: str):
    """写/更新缓存。"""
    db = await _get_cache_conn()
    try:
        # aiosqlite 不支持 INSERT ... ON CONLECT 直接对 None，用显式 SQL
        await db.execute(
            """INSERT INTO url_uc_cache (url, mentions_uc, status, fetched_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(url) DO UPDATE SET
                 mentions_uc=excluded.mentions_uc,
                 status=excluded.status,
                 fetched_at=CURRENT_TIMESTAMP""",
            (url, mentions_uc, status))
        await db.commit()
    finally:
        await db.close()


async def fetch_and_cache(url: str) -> Optional[bool]:
    """抓取单个 URL 并写缓存，返回 mentions_uc。已缓存且非 fetch_failed 的直接复用。"""
    cached, status = await get_cached_mentions_uc(url)
    if cached is not None:
        return cached
    if status == "fetch_failed":
        # 失败过的，再试一次（可能临时反爬）
        pass
    mentions = await fetch_url_mentions_uc(url)
    new_status = "ok" if mentions is not None else "fetch_failed"
    await save_cached_mentions_uc(url, mentions, new_status)
    return mentions


async def backfill_urls(urls, concurrency: int = _MAX_CONCURRENCY,
                        on_progress=None) -> dict:
    """批量抓取回填一组 URL。

    - 官方域名短路（不抓，缓存记 True/official）。
    - 已缓存且成功的复用。
    - 并发上限可调。
    on_progress(done, total) 回调用于报告进度。
    返回 {total, ok, mentions_true, mentions_false, failed, cached_reused}。
    """
    # 去重
    uniq = list(dict.fromkeys(urls))
    sem = asyncio.Semaphore(concurrency)
    stats = {"total": len(uniq), "ok": 0, "true": 0, "false": 0,
             "failed": 0, "reused": 0}
    done = 0

    async def _one(u):
        nonlocal done
        async with sem:
            # 先查缓存
            cached, status = await get_cached_mentions_uc(u)
            if cached is not None:
                stats["reused"] += 1
                stats["ok"] += 1
                if cached:
                    stats["true"] += 1
                else:
                    stats["false"] += 1
            else:
                mentions = await fetch_and_cache(u)
                if mentions is True:
                    stats["true"] += 1
                    stats["ok"] += 1
                elif mentions is False:
                    stats["false"] += 1
                    stats["ok"] += 1
                else:
                    stats["failed"] += 1
            done += 1
            if on_progress:
                try:
                    on_progress(done, stats["total"])
                except Exception:
                    pass

    await asyncio.gather(*[_one(u) for u in uniq], return_exceptions=True)
    return stats
