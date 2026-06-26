"""
UCloud GEO 评估框架 - WebChat 浏览器自动化客户端
使用 Playwright 模拟真实用户在各 AI 模型官网的 Web Chat 交互，
获取带联网搜索引用的完整响应。

当前已实现：Kimi（联网搜索最强）
其他模型暂为 stub，后续逐个调试适配。
"""
import asyncio
import logging
import os
import re
from typing import Dict, Any, Optional

from playwright.async_api import async_playwright, Page, BrowserContext

from web_chat_auth import load_auth_state, WEBCHAT_SITES

logger = logging.getLogger(__name__)


class WebChatClientBase:
    """WebChat 客户端基类

    子类需要实现:
    - _navigate_to_chat()    打开新对话页面
    - _type_question()       输入问题
    - _send_question()       发送问题
    - _wait_for_response()   等待响应完成
    - _extract_response()    提取完整响应文本（含引用URL）
    - _start_new_chat()      重置为新对话
    """

    model_key: str = ""
    name: str = ""
    url: str = ""
    is_configured: bool = False

    # 登录页 URL 片段（命中任一即视为未登录/登录页，_is_logged_in 反向信号）
    LOGIN_URL_HINTS = ("login", "passport", "signin", "sso")

    def __init__(self, model_key: str):
        self.model_key = model_key
        site = WEBCHAT_SITES.get(model_key, {})
        self.name = site.get("name", model_key)
        self.url = site.get("url", "")

        # 检查是否有认证状态
        auth_state = load_auth_state(model_key)
        self._auth_state = auth_state
        self.is_configured = auth_state is not None

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def initialize(self, fresh: bool = False) -> bool:
        """启动浏览器（在评测开始时调用一次）

        fresh=False（默认，评测用）：无认证状态返回 False；用已存 storage_state 开浏览器。
        fresh=True（登录流程用）：不要求认证状态，开全新 context（不传 storage_state），
            供 _login_flow 引导用户登录后探测保存。

        豆包等网站检测 Playwright 自动化浏览器，需要在有 X 显示的环境下
        使用 headless=False（配合 xvfb-run）才能绕过反爬检测。
        服务器上 systemd 服务需用 xvfb-run 启动 uvicorn。
        """
        if not fresh and not self.is_configured:
            logger.warning(f"WebChat {self.model_key}: 无认证状态，无法评测")
            return False

        self._playwright = await async_playwright().start()

        # 检测是否有 DISPLAY 环境变量（xvfb 提供），有则用 headed 模式绕过反爬
        has_display = os.environ.get("DISPLAY") is not None
        headless_mode = not has_display
        logger.info(f"WebChat {self.model_key}: headless={headless_mode}, DISPLAY={os.environ.get('DISPLAY', 'none')}")

        self._browser = await self._playwright.chromium.launch(
            headless=headless_mode,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        # 反自动化检测：JS 层抹掉 webdriver 指纹
        stealth_js = """
        // 删除 navigator.webdriver 属性
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // 伪装 chrome 对象（headless 缺少 chrome runtime）
        window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
        // 伪装 permissions API（headless 返回 'prompt' 而正常浏览器返回 'denied'）
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );
        // 伪装 plugins（headless 无 plugins）
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        // 伪装 languages
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
        """

        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            **({"storage_state": self._auth_state} if (not fresh and self._auth_state) else {}),
        )
        # 在每个页面创建前注入反检测脚本
        await self._context.add_init_script(stealth_js)
        self._page = await self._context.new_page()
        logger.info(f"WebChat {self.model_key}: 浏览器已启动 (headless={headless_mode})")
        return True

    async def chat(self, question: str) -> Dict[str, Any]:
        """发送问题并获取响应（与 ModelClient.chat() 返回格式一致）

        Returns:
            {"model": str, "model_name": str, "content": str, "error": str|None, "timestamp": str}
        """
        if not self._page:
            return {
                "model": self.model_key,
                "model_name": self.name,
                "content": "",
                "raw_response": None,
                "error": "Browser not initialized",
                "timestamp": "",
            }

        q_preview = question[:40] + ("..." if len(question) > 40 else "")
        try:
            # 每道题前重置对话
            logger.info(f"WebChat {self.model_key}: 重置对话 → 准备提问: {q_preview}")
            await self._start_new_chat(self._page)

            # 输入问题
            logger.info(f"WebChat {self.model_key}: 输入问题: {q_preview}")
            await self._type_question(self._page, question)

            # 发送
            logger.info(f"WebChat {self.model_key}: 发送问题，等待响应...")
            await self._send_question(self._page)

            # 等待响应完成
            await self._wait_for_response(self._page, timeout=120)

            # 提取响应文本
            logger.info(f"WebChat {self.model_key}: 提取响应文本...")
            text = await self._extract_response(self._page)
            logger.info(f"WebChat {self.model_key}: 响应完成，长度={len(text)}字")

            # 封号信号检测：把分类结果编码进 error 文本，
            # 交给 scheduler 统一处理（重试/冷却/跳过）。
            # 用稳定的触发短语，确保 scheduler 端 classify_signal 能确定性分类。
            # 注意：只对「短文本」分类（classify_content_signal）。真实限流/登录
            # 提示是短句；正常回答数百字且可能含「限流/429/验证码」等技术词
            # （评估对象 UCloud 是云厂商），对长正文扫描会误判限流、触发 900s
            # 冷却把整模型卡死。
            from webchat_policy import classify_content_signal
            sig = classify_content_signal(text)
            if sig == "login_expired":
                return {"model": self.model_key, "model_name": self.name, "content": "",
                        "raw_response": None,
                        "error": f"登录已过期（页面出现登录/验证信号）: {text[:160]}",
                        "timestamp": ""}
            if sig == "throttle":
                return {"model": self.model_key, "model_name": self.name, "content": "",
                        "raw_response": None,
                        "error": f"请求频率过快，触发限流: {text[:160]}",
                        "timestamp": ""}

            return {
                "model": self.model_key,
                "model_name": self.name,
                "content": text,
                "raw_response": None,
                "error": None,
                "timestamp": "",
            }

        except Exception as e:
            logger.error(f"WebChat {self.model_key} error: {e}")
            return {
                "model": self.model_key,
                "model_name": self.name,
                "content": "",
                "raw_response": None,
                "error": str(e),
                "timestamp": "",
            }

    async def close(self):
        """关闭浏览器（在评测结束时调用）"""
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"WebChat {self.model_key} close error: {e}")
        finally:
            self._browser = None
            self._playwright = None
            self._page = None
            self._context = None

    async def _goto_site(self, page: Page) -> None:
        """导航到站点首页一次（探测/登录前由调用方调用）。

        失败静默：导航失败时由 _is_logged_in 的输入框可见性兜底判 False。
        只导航一次，不在 _is_logged_in 内重复 goto（否则会打断用户正在进行的登录）。
        """
        try:
            await page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            try:
                await page.goto(self.url, wait_until="commit", timeout=30000)
            except Exception:
                pass

    async def _is_logged_in(self, page: Page, timeout: int = 15) -> bool:
        """真实登录态探测（只看当前页，不导航）。

        URL 含登录页片段 → False；否则看聊天输入框是否可见。
        不导航：登录轮询时每 3s 调用，重复 goto 会打断用户登录。
        子类可覆盖以提供更精确信号（默认用 INPUT_SELECTOR 可见性 + URL 反向信号）。
        """
        url = page.url or ""
        if any(h in url for h in self.LOGIN_URL_HINTS):
            return False
        try:
            loc = page.locator(self.INPUT_SELECTOR).first
            return await loc.is_visible(timeout=timeout * 1000)
        except Exception:
            return False

    # ── 子类需要实现的方法 ──

    async def _navigate_to_chat(self, page: Page):
        """打开新对话页面"""
        raise NotImplementedError

    async def _type_question(self, page: Page, question: str):
        """输入问题到输入框"""
        raise NotImplementedError

    async def _send_question(self, page: Page):
        """点击发送按钮"""
        raise NotImplementedError

    async def _wait_for_response(self, page: Page, timeout: int = 120):
        """等待响应完成"""
        raise NotImplementedError

    async def _extract_response(self, page: Page) -> str:
        """提取完整响应文本（含引用URL）"""
        raise NotImplementedError

    async def _start_new_chat(self, page: Page):
        """重置为新对话"""
        raise NotImplementedError

    # ── 通用等待策略 ──

    async def _wait_for_text_stability(self, page: Page, selector: str,
                                         timeout: int = 120, interval: int = 1,
                                         stable_threshold: int = 2):
        """通用文本稳定性等待：当文本长度连续 N 次不变时视为完成

        Args:
            selector: 响应文本区域的 CSS 选择器
            timeout: 最大等待秒数
            interval: 每次轮询间隔秒数
            stable_threshold: 连续稳定次数阈值
        """
        last_length = 0
        stable_count = 0
        elapsed = 0

        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            try:
                # 使用 querySelectorAll 取最后一个元素，与 page.locator(selector).last 一致
                # selector 作为 evaluate 参数传入，避免含单引号的选择器（如
                # [class*='message-content']）破坏 JS 字符串字面量导致 SyntaxError。
                current_length = await page.evaluate(
                    "(sel) => {"
                    "  const els = document.querySelectorAll(sel);"
                    "  if (!els.length) return 0;"
                    "  return (els[els.length - 1]?.innerText || '').length;"
                    "}",
                    selector,
                )
            except Exception:
                current_length = 0

            if current_length > 0 and current_length == last_length:
                stable_count += 1
                if stable_count >= stable_threshold:
                    logger.info(f"WebChat {self.model_key}: response stable after {elapsed}s ({stable_count} checks, {current_length} chars)")
                    # 等额外 2 秒，让可能的后续引用卡片加载
                    await asyncio.sleep(2)
                    return True
            else:
                stable_count = 0
                last_length = current_length

        logger.warning(f"WebChat {self.model_key}: response timeout after {timeout}s, last_length={last_length}")
        return False


class KimiWebChatClient(WebChatClientBase):
    """Kimi (www.kimi.com) WebChat 客户端

    Kimi 自动联网搜索，无需手动开启搜索模式。
    响应特点：搜索时会显示"搜索中..."提示，完成后有引用卡片。
    注意：Kimi 已从 kimi.moonshot.cn 迁移到 www.kimi.com
    """

    # ── Kimi 页面选择器 ──
    # Kimi 使用 contenteditable div 而不是 textarea
    INPUT_SELECTOR = "[contenteditable='true'].chat-input-editor, [contenteditable='true']"
    SEND_SELECTOR = "button[class*='send'], img[class*='send'], button[data-testid='send-button']"
    RESPONSE_SELECTOR = "[class*='markdown'], [class*='message-content'], [class*='assistant']"
    NEW_CHAT_SELECTOR = "a[href='/'], button[class*='new-chat'], [class*='create-conversation'], [data-testid='new-chat']"
    SEARCH_INDICATOR = "[class*='searching'], [class*='search-indicator'], [class*='web-search']"

    async def _is_logged_in(self, page: Page, timeout: int = 15) -> bool:
        """kimi 真实登录态探测（覆盖基类的"输入框可见"弱信号）。

        kimi-auth cookie 登录中途就出现、聊天输入框落地页就可见，都是弱信号——
        会导致 _login_flow 抢救半成品 state（实测：误存 6 cookie + 只有 anonymous
        token 的 localStorage，评测时发不出请求）。kimi 是 SPA，真正会话凭证在
        localStorage：access_token(JWT)/msh_user_id 仅完整登录后写入；
        anonymous_access_token 是匿名态，不算登录。
        证据：diag_kimi_login_state.py 登录后 localStorage 有 access_token+
        refresh_token+msh_user_id、loginBtn=False avatar=True；登录前只有 anonymous_*。
        """
        url = page.url or ""
        if any(h in url for h in self.LOGIN_URL_HINTS):
            return False
        try:
            has_real = await page.evaluate(
                "() => !!(localStorage.getItem('access_token') || localStorage.getItem('msh_user_id'))"
            )
            return bool(has_real)
        except Exception:
            return False

    async def _navigate_to_chat(self, page: Page):
        """导航到 Kimi 新对话页面"""
        try:
            await page.goto("https://www.kimi.com", wait_until="networkidle", timeout=30000)
        except Exception:
            # networkidle 可能超时，回退到 domcontentloaded
            await page.goto("https://www.kimi.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

    async def _type_question(self, page: Page, question: str):
        """在输入框中输入问题（Kimi 用 contenteditable div）

        使用 Playwright 物理键盘输入，比 JS 设置 textContent 更可靠。
        Kimi 的编辑器是 React-based，不响应直接 DOM 修改。
        """
        # 先关闭可能遮挡输入框的侧边栏遮罩
        try:
            mask = page.locator("div.mask").first
            if await mask.is_visible(timeout=3000):
                await mask.click(timeout=3000)
                await asyncio.sleep(0.5)
                logger.info("WebChat kimi: closed sidebar mask")
        except Exception:
            pass

        # 等待输入框出现（页面可能还在加载）
        input_box = None
        for selector in [
            "div.chat-input-editor",
            "[contenteditable='true']",
            "[role='textbox']",
        ]:
            try:
                box = page.locator(selector).first
                if await box.is_visible(timeout=15000):
                    input_box = box
                    break
            except Exception:
                continue

        if not input_box:
            await page.screenshot(path="output/kimi_input_debug.png", full_page=True)
            logger.warning("WebChat kimi: 找不到输入框，已截图到 output/kimi_input_debug.png")
            raise RuntimeError("Kimi 输入框未找到")

        # 点击输入框聚焦（force=True 绕过遮罩层拦截）
        await input_box.click(force=True)
        await asyncio.sleep(0.3)

        # 物理键盘输入（Kimi React 编辑器只响应真实键盘事件）
        # 15ms/char 是经验值：50 字约 0.75s，不会超时
        await page.keyboard.type(question, delay=15)
        await asyncio.sleep(0.3)

        # 验证输入是否成功
        typed = await page.evaluate("""() => {
            const el = document.querySelector('[contenteditable="true"]');
            return el ? el.textContent : '';
        }""")
        if typed and len(typed) > len(question) * 0.5:
            logger.info(f"WebChat kimi: question typed via keyboard ({len(typed)} chars)")
        else:
            logger.warning(f"WebChat kimi: typing may have failed (expected {len(question)}, got {len(typed)})")

    async def _send_question(self, page: Page):
        """发送问题"""
        await asyncio.sleep(0.5)

        # 方式1：JS 查找输入框附近的箭头/发送按钮并点击
        try:
            clicked = await page.evaluate("""() => {
                const inputEl = document.querySelector('[contenteditable="true"]');
                if (!inputEl) return false;
                const parent = inputEl.closest('form') || inputEl.parentElement || document.body;
                // 查找所有可点击元素
                const candidates = parent.querySelectorAll('button, [role="button"], div[role="button"], svg, img');
                for (const el of candidates) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 10 || rect.height < 10) continue;
                    const cls = (el.className || '').toLowerCase();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    // 发送按钮特征：箭头、发送、submit、up
                    if (cls.includes('arrow') || cls.includes('send') || cls.includes('submit') ||
                        cls.includes('up') || aria.includes('send') || aria.includes('发送') ||
                        aria.includes('提交') || aria.includes('arrow')) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }""")
            if clicked:
                logger.info("WebChat kimi: sent via JS button click")
                return
        except Exception as e:
            logger.debug(f"WebChat kimi: JS click failed: {e}")

        # 方式2：在输入框内按 Enter（如果 JS 点击失败）
        try:
            await page.evaluate("""() => {
                const el = document.querySelector('[contenteditable="true"]');
                if (el) {
                    el.focus();
                    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }));
                }
            }""")
            logger.info("WebChat kimi: sent via JS Enter")
            return
        except Exception:
            pass

        # 方式3：物理 Enter 键
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.3)
        logger.info("WebChat kimi: sent via physical Enter")

    async def _wait_for_response(self, page: Page, timeout: int = 120):
        """等待 Kimi 响应完成

        Kimi 搜索流程：先搜索（显示"搜索中..."）→ 再生成回答 → 流式输出
        等待策略：先等搜索指示器消失 → 用可见文本稳定性判断完成
        """
        # 先等搜索指示器出现然后消失
        try:
            search_indicator = page.locator(self.SEARCH_INDICATOR).first
            if await search_indicator.is_visible(timeout=10000):
                await search_indicator.wait_for(state="hidden", timeout=60000)
                logger.info(f"WebChat kimi: search completed")
        except Exception:
            pass

        # 等响应区域出现
        try:
            await page.wait_for_selector("segment.segment-assistant, .segment-assistant", timeout=30000)
        except Exception:
            pass

        # 用可见文本稳定性判断完成（不依赖单一 CSS 选择器）
        await self._wait_for_kimi_text_stability(page, timeout=timeout)

    async def _wait_for_kimi_text_stability(self, page: Page, timeout: int = 120):
        """Kimi 专用文本稳定性检查 — 不依赖单一 CSS 选择器"""
        start_text_len = await page.evaluate("""() => {
            // 优先取聊天内容区域
            const chatArea = document.querySelector(
                '.chat-content, [class*="chat-content"], [class*="conversation"], main'
            ) || document.body;
            const text = chatArea.innerText || '';
            return text.length;
        }""")
        logger.info(f"WebChat kimi: waiting for response (initial text: {start_text_len} chars)")

        stable_count = 0
        prev_len = start_text_len
        elapsed = 0
        interval = 3

        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            current_len = await page.evaluate("""() => {
                const chatArea = document.querySelector(
                    '.chat-content, [class*="chat-content"], [class*="conversation"], main'
                ) || document.body;
                return (chatArea.innerText || '').length;
            }""")
            logger.info(f"WebChat kimi: text len after {elapsed}s: {current_len} chars")

            # 流式输出：每次增长至少 30 字才算在生成
            if current_len > prev_len + 30:
                stable_count = 0
                prev_len = current_len
            else:
                stable_count += 1
                if stable_count >= 3:
                    # 额外等 2 秒让引用卡片加载
                    await asyncio.sleep(2)
                    logger.info(f"WebChat kimi: response complete ({current_len} chars)")
                    return

    async def _extract_response(self, page: Page) -> str:
        """提取 Kimi 响应文本，包括引用链接

        策略：
        1. 尝试用 segment-assistant 选择器提取
        2. 回退：TreeWalker 提取整个页面，排除侧边栏/footer/输入区
        """
        # 先尝试用 CSS 选择器提取
        try:
            response_area = page.locator("segment.segment-assistant, .segment-assistant").last
            await response_area.wait_for(state="visible", timeout=5000)
            text = await response_area.inner_text()

            if len(text) > 50:
                citations = await self._extract_links_from_area(response_area)
                if citations:
                    text += "\n\n---\n引用来源:\n" + "\n".join(citations)

                logger.info("WebChat kimi: extracted %d chars via segment-assistant", len(text))
                return text
        except Exception:
            pass

        # 回退：用 TreeWalker 提取全页面文本，排除侧边栏/footer/输入区
        result = await page.evaluate("""() => {
            var bodyW = document.body.scrollWidth;
            var sidebarRight = bodyW * 0.3;
            var exclude = 'input,textarea,button,[role="navigation"],[role="menubar"],header,footer,script,style,noscript,link,meta';
            var sidebarCls = 'sidebar,left-side,leftpanel,logo,brand,nav';

            var texts = [];
            var links = [];
            var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
                acceptNode: function(node) {
                    var tag = node.tagName.toLowerCase();
                    if (tag === 'script' || tag === 'style' || tag === 'noscript' ||
                        tag === 'link' || tag === 'meta' || tag === 'header' || tag === 'footer')
                        return NodeFilter.FILTER_REJECT;
                    return NodeFilter.FILTER_ACCEPT;
                }
            });

            var node;
            while (node = walker.nextNode()) {
                // 只取文本节点
                var children = node.childNodes;
                for (var i = 0; i < children.length; i++) {
                    if (children[i].nodeType === Node.TEXT_NODE) {
                        var t = children[i].textContent.trim();
                        if (t.length >= 3) {
                            texts.push(t);
                        }
                    }
                }
                // 收集链接
                if (node.tagName === 'A' && node.href) {
                    var hr = node.href;
                    if (!hr.startsWith('javascript:') && !hr.startsWith('#') &&
                        !hr.includes('kimi.com')) {
                        links.push({text: (node.textContent || '').trim(), href: hr});
                    }
                }
            }

            // 进一步过滤：排除左屏内容（侧边栏）
            var rightTexts = [];
            walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
                acceptNode: function(n) {
                    var p = n.parentElement;
                    if (!p) return NodeFilter.FILTER_REJECT;
                    if (p.closest(exclude)) return NodeFilter.FILTER_REJECT;
                    var r = n.parentElement.getBoundingClientRect();
                    if (r.x < sidebarRight) return NodeFilter.FILTER_REJECT;
                    var t = n.textContent.trim();
                    if (t.length < 3) return NodeFilter.FILTER_REJECT;
                    return NodeFilter.FILTER_ACCEPT;
                }
            });
            while (node = walker.nextNode()) {
                rightTexts.push(node.textContent.trim());
            }

            return {text: rightTexts.join('\\n').trim(), linkCount: links.length};
        }""")

        text = result.get("text", "")

        # 提取外部链接（从主内容区域）
        links = await page.evaluate("""() => {
            var links = [];
            var allA = document.querySelectorAll('a[href]');
            for (var i = 0; i < allA.length; i++) {
                var a = allA[i];
                var hr = a.href || '';
                if (!hr || hr.startsWith('javascript:') || hr.startsWith('#')) continue;
                if (hr.includes('kimi.com')) continue;
                links.push({text: (a.textContent || '').trim() || ('[' + (links.length+1) + ']'), href: hr});
            }
            return links;
        }""")

        if links:
            citation_lines = []
            for i, link in enumerate(links):
                link_text = link.get("text", "") or "[" + str(i+1) + "]"
                citation_lines.append("[" + str(i+1) + "] " + link_text + ": " + link["href"])
            text += "\n\n---\n引用来源:\n" + "\n".join(citation_lines)

        logger.info("WebChat kimi: extracted %d chars via TreeWalker fallback", len(text))
        return text or ""

    async def _extract_links_from_area(self, response_area) -> list:
        """从响应区域提取外部引用链接"""
        links = await response_area.evaluate("""
            el => {
                const links = el.querySelectorAll('a[href]');
                return Array.from(links).map(a => ({
                    text: a.textContent.trim(),
                    href: a.href
                }));
            }
        """)
        citation_lines = []
        idx = 1
        for link in links:
            href = link["href"]
            if href.startswith("javascript:") or href.startswith("#"):
                continue
            if "kimi.com" in href and "/search" not in href:
                continue
            link_text = link["text"] or f"[{idx}]"
            citation_lines.append(f"[{idx}] {link_text}: {href}")
            idx += 1
        return citation_lines

    async def _start_new_chat(self, page: Page):
        """开始新对话"""
        try:
            # 方式1：用 JS 查找新对话按钮并点击
            clicked = await page.evaluate("""() => {
                const buttons = Array.from(document.querySelectorAll('button, a'));
                for (const btn of buttons) {
                    const text = (btn.textContent || '').trim();
                    const cls = (btn.className || '').toLowerCase();
                    const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                    if ((text === '新建对话' || text === '新对话' || text.includes('新建') && text.includes('对话'))
                        || cls.includes('new-chat') || aria.includes('new') || aria.includes('新建')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""")
            if clicked:
                await asyncio.sleep(2)
                return
        except Exception:
            pass

        # 方式2：回退到首页
        await page.goto("https://www.kimi.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)


class DeepSeekWebChatClient(WebChatClientBase):
    """DeepSeek (chat.deepseek.com) WebChat 客户端

    DeepSeek 不内置联网搜索，纯推理模型。
    页面为 React SPA，需要登录后才能看到聊天界面。
    选择器基于 DeepSeek 2025 年页面结构，使用多重 fallback。
    """

    # ── DeepSeek 页面选择器 ──
    INPUT_SELECTOR = (
        "textarea[data-testid='chat-input'], "
        "textarea[id*='chat'], textarea[class*='input'], textarea[class*='chat-input'], "
        "textarea.ds-scroll-area, "
        "[contenteditable='true'][class*='input'], "
        "#chat-input, .chat-input textarea, "
        "textarea"
    )
    SEND_SELECTOR = (
        "button[data-testid='send-button'], "
        "button[aria-label*='Send'], button[aria-label*='send'], "
        "button[class*='send'], img[class*='send'], "
        "button[type='submit'][class*='chat']"
    )
    RESPONSE_SELECTOR = (
        "[class*='assistant-message'], "
        "div.ds-markdown.ds-assistant-message-main-content, "
        "div.ds-markdown, "
        "[data-testid='assistant-message'], "
        "[class*='message-assistant'], "
        "[class*='markdown-body'], [class*='markdown'], "
        ".chat-message-assistant, .message-content"
    )
    NEW_CHAT_SELECTOR = (
        "a[href='/'][class*='sidebar'], "
        "button[aria-label*='new chat'], button[aria-label*='New Chat'], "
        "a[href='/chat'], "
        "[class*='new-chat'], [class*='new-conversation'], "
        "[data-testid='new-chat']"
    )

    async def _navigate_to_chat(self, page: Page):
        """导航到 DeepSeek 新对话页面"""
        await page.goto("https://chat.deepseek.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

    async def _type_question(self, page: Page, question: str):
        """在输入框中输入问题"""
        # 先关闭可能遮挡的侧边栏遮罩
        try:
            mask = page.locator("div[class*='mask'], div[class*='overlay'], div[class*='backdrop']").first
            if await mask.is_visible(timeout=2000):
                await mask.click(timeout=2000)
                await asyncio.sleep(0.5)
        except Exception:
            pass

        input_el = page.locator(self.INPUT_SELECTOR).first
        await input_el.wait_for(state="visible", timeout=15000)
        await input_el.click(force=True)
        await asyncio.sleep(0.3)

        # 区分 textarea 和 contenteditable
        tag = await input_el.evaluate("el => el.tagName")
        if tag == "TEXTAREA":
            await input_el.fill(question)
        else:
            await page.keyboard.type(question, delay=30)

    async def _send_question(self, page: Page):
        """发送问题"""
        try:
            send_btn = page.locator(self.SEND_SELECTOR).first
            if await send_btn.is_visible(timeout=5000):
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")
        except Exception:
            await page.keyboard.press("Enter")

    async def _wait_for_response(self, page: Page, timeout: int = 120):
        """等待 DeepSeek 响应完成

        DeepSeek 无联网搜索，直接等待文本稳定。
        流式输出完成后文本长度不再变化。
        """
        # 等响应区域出现（尝试多个选择器）
        response_found = False
        for selector in [
            "div.ds-markdown.ds-assistant-message-main-content",
            "[class*='assistant-message']",
            "[class*='markdown']",
        ]:
            try:
                resp_area = page.locator(selector).last
                await resp_area.wait_for(state="visible", timeout=15000)
                response_found = True
                logger.info(f"WebChat deepseek: response area found via {selector}")
                break
            except Exception:
                continue

        if not response_found:
            logger.warning("WebChat deepseek: no response area found, waiting extra time")
            await asyncio.sleep(15)

        # 等文本稳定（用页面整体文本长度判断，更可靠）
        await self._wait_for_deepseek_text_stability(page, timeout=timeout)

    async def _wait_for_deepseek_text_stability(self, page: Page, timeout: int = 120):
        """DeepSeek 文本稳定性检查"""
        prev_len = 0
        stable_count = 0
        elapsed = 0
        interval = 3

        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            current_len = await page.evaluate("""() => {
                const el = document.querySelector(
                    "div.ds-markdown.ds-assistant-message-main-content, " +
                    "[class*='assistant-message'], [class*='markdown']"
                );
                return el ? (el.innerText || '').length : 0;
            }""")

            if current_len > prev_len + 30:
                stable_count = 0
                prev_len = current_len
            else:
                stable_count += 1
                if stable_count >= 3:
                    logger.info(f"WebChat deepseek: response complete ({current_len} chars)")
                    return

    async def _extract_response(self, page: Page) -> str:
        """提取 DeepSeek 响应文本，包括引用链接"""
        # 优先用精确的 DeepSeek 选择器（避免匹配到 markdown 子元素）
        response_area = None
        for selector in [
            "div.ds-markdown.ds-assistant-message-main-content",
            "[class*='assistant-message']",
        ]:
            try:
                area = page.locator(selector).last
                if await area.is_visible(timeout=5000):
                    response_area = area
                    logger.info(f"WebChat deepseek: extract via {selector}")
                    break
            except Exception:
                continue

        if not response_area:
            try:
                response_area = page.locator("[class*='markdown']").first
                await response_area.wait_for(state="visible", timeout=10000)
            except Exception:
                return ""

        text = await response_area.inner_text()

        # 提取所有 <a href> 链接
        links = await response_area.evaluate("""
            el => {
                const links = el.querySelectorAll('a[href]');
                return Array.from(links).map(a => ({
                    text: a.textContent.trim(),
                    href: a.href
                }));
            }
        """)

        if links:
            citation_lines = []
            for i, link in enumerate(links):
                href = link["href"]
                if href.startswith("javascript:") or href.startswith("#"):
                    continue
                link_text = link["text"] or f"[{i+1}]"
                citation_lines.append(f"[{i+1}] {link_text}: {href}")
            if citation_lines:
                text += "\n\n---\n引用来源:\n" + "\n".join(citation_lines)

        return text

    async def _start_new_chat(self, page: Page):
        """开始新对话"""
        try:
            new_btn = page.locator(self.NEW_CHAT_SELECTOR).first
            if await new_btn.is_visible(timeout=3):
                await new_btn.click()
                await asyncio.sleep(2)
            else:
                await page.goto("https://chat.deepseek.com", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
        except Exception:
            await page.goto("https://chat.deepseek.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)


class ErnieWebChatClient(WebChatClientBase):
    """文心一言 (chat.baidu.com) WebChat 客户端

    百度的 AI 聊天平台，支持联网搜索和深度思考。
    原域名 yiyan.baidu.com 已迁移到 chat.baidu.com（2026）。
    Baidu 使用哈希化的 CSS 类名（如 editable__T7WAW4uW），
    因此选择器以结构/语义属性为主，辅以类名模式匹配。
    """

    # ── 文心一言选择器 ──
    # chat.baidu.com 新版输入框 id 固定为 chat-textarea（最稳），ci-textarea 为其 class
    INPUT_SELECTOR = (
        "#chat-textarea, "
        "textarea.ci-textarea, "
        "[contenteditable='true'], "
        "[class*='editable'], "
        "[class*='input-area'], textarea"
    )
    SEND_SELECTOR = (
        "button[aria-label*='发送'], button[aria-label*='Send'], "
        "button[class*='send']"
    )
    # 回答容器：chat.baidu.com 的回答回合。
    # 实测 DOM（diag_ernie_response2）：回答区结构为
    #   conversation-flow-answer-container > answer-box.last-answer-box
    #     > chat-search-answer-generate > ... > cs-answer-container
    # 旧选择器 [class*='answerBox'](驼峰) 匹配不到——实际类名是 answer-box(短横线)；
    # [class*='answer'](小写) 过宽，.last 会命中底部空的 answer-tips-wrapper(innerText="")
    # → _wait_until_no_progress_markers 取空文本恒不满足 → 死循环到 180s 超时；
    #   _extract_response 的 .last 同样命中空 wrapper → 返回 ""。
    # 改用精确类名 .answer-box，.last 取最新回答回合（多轮时取最后一个）。
    RESPONSE_SELECTOR = (
        ".answer-box.last-answer-box, "
        ".answer-box, "
        ".conversation-flow-answer-container"
    )
    NEW_CHAT_SELECTOR = (
        "button[aria-label*='新建'], "
        "a[href*='new'], "
        "[class*='new-chat'], [class*='create'], "
        "button[class*='new']"
    )
    SEARCH_TOGGLE_SELECTOR = (
        "button[aria-label*='搜索'], "
        "[class*='search-toggle'], "
        "[class*='联网']"
    )

    async def _is_logged_in(self, page: Page, timeout: int = 15) -> bool:
        """文心一言真实登录态探测（覆盖基类"输入框可见"弱信号）。

        文心首页 (chat.baidu.com) 的输入框匿名态就可见——基类判据会把匿名/登录中途
        误判成已登录 → _login_flow 抢救保存只有匿名 cookie 的半成品 state → 下次评测
        一加载就被踢回登录页（"每次要重新登录"根因）。

        强信号 = BDUSS cookie：百度通行证 httpOnly 登录凭证，仅完整登录后下发。
        证据：diag_ernie_login_state.py 登录翻转 [2]→[5]：登录前只有匿名态 cookie
        （BAIDUID/RT/ab_sr…，无 BDUSS）；登录后 BDUSS+STOKEN+PTOKEN+UBI 写入。
        BDUSS 是 httpOnly → document.cookie 读不到，必须用 context.cookies()。
        """
        url = page.url or ""
        if any(h in url for h in self.LOGIN_URL_HINTS):
            return False
        try:
            cookies = await page.context.cookies()
            return any(c.get("name") == "BDUSS" and c.get("value") for c in cookies)
        except Exception:
            return False

    async def _navigate_to_chat(self, page: Page):
        """导航到文心一言"""
        await page.goto("https://chat.baidu.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

    async def _type_question(self, page: Page, question: str):
        """在输入框中输入问题（chat.baidu.com 优先 #chat-textarea，避免命中隐藏 textarea）"""
        input_el = page.locator("#chat-textarea")
        try:
            await input_el.wait_for(state="visible", timeout=8000)
        except Exception:
            input_el = page.locator(self.INPUT_SELECTOR).first
            await input_el.wait_for(state="visible", timeout=5000)
        await input_el.click()
        await asyncio.sleep(0.3)
        await page.keyboard.type(question, delay=30)

    async def _send_question(self, page: Page):
        """发送问题（优先按 Enter，更可靠）"""
        try:
            send_btn = page.locator(self.SEND_SELECTOR).first
            if await send_btn.is_visible(timeout=3000):
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")
        except Exception:
            await page.keyboard.press("Enter")

    async def _wait_for_response(self, page: Page, timeout: int = 180):
        """等待文心一言响应完成

        文心一言有"深度思考"模式：先流式输出"正在思考中"+思维链（可见但非最终答案），
        再出最终答案。完成判定按 answerBox 正文内容——不再依赖 CSS 选择器（文心类名
        哈希化如 editable__T7WAW4uW，[class*='thinking'] 匹配不到 → is_visible 直接
        False → 旧逻辑跳过等待思考结束）。

        证据：output/webchat_task3_20260620_222419.json 的 q17/q18 在思考停顿期
        被 _wait_for_text_stability 误判稳定、提前返回半截"正在思考中...买到高"。
        策略：先轮询直到正文不再含进行中标记 → 再做文本稳定性确认（最终答案稳定）。
        """
        # 等待回答区域出现
        try:
            resp_area = page.locator(self.RESPONSE_SELECTOR).last
            await resp_area.wait_for(state="visible", timeout=30000)
        except Exception:
            await asyncio.sleep(10)

        # ── 阶段1：等深度思考结束（内容判定，不靠 CSS 选择器）──
        # 进行中标记：思考中/搜索中/生成中等。正文含任一即继续等。
        # 这些是 UI 渲染在 answerBox 里的可见提示，不是最终答案的一部分。
        await self._wait_until_no_progress_markers(page, timeout=timeout)

        # ── 阶段2：最终答案文本稳定（思考结束后答案仍在流式增长，需等其稳定）──
        await self._wait_for_text_stability(
            page, self.RESPONSE_SELECTOR, timeout=timeout
        )

    async def _wait_until_no_progress_markers(self, page: Page, timeout: int = 180,
                                               interval: int = 2) -> bool:
        """轮询 answerBox 正文，直到不含"进行中"标记（正在思考中/搜索中/生成中...）。

        思考阶段正文会反复出现这些标记；标记全部消失后才进入最终答案阶段。
        单独成阶段：思考停顿期文本长度可能暂时不变（_wait_for_text_stability 会误判），
        但标记仍在 → 此处继续等，堵住"思考停顿误判稳定"。
        返回 True=已进入无标记阶段，False=超时。
        """
        marker_js = (
            "(sel) => {"
            "  const els = document.querySelectorAll(sel);"
            "  if (!els.length) return '';"
            "  return (els[els.length - 1]?.innerText || '');"
            "}"
        )
        selector = self.RESPONSE_SELECTOR
        markers = ("正在思考", "思考中", "搜索中", "生成中", "正在搜索", "正在生成")
        elapsed = 0
        while elapsed < timeout:
            try:
                text = await page.evaluate(marker_js, selector) or ""
            except Exception:
                text = ""
            if text and not any(m in text for m in markers):
                logger.info(f"WebChat {self.model_key}: thinking ended (no progress markers, {len(text)} chars)")
                return True
            await asyncio.sleep(interval)
            elapsed += interval
        logger.warning(f"WebChat {self.model_key}: still has progress markers after {timeout}s")
        return False

    async def _extract_response(self, page: Page) -> str:
        """提取文心一言响应文本

        文心一言的回答区域包含"深度思考"过程和最终答案。
        需要过滤掉思考过程的文本，只保留最终答案。
        """
        try:
            answer_box = page.locator(self.RESPONSE_SELECTOR).last
            await answer_box.wait_for(state="visible", timeout=10000)
        except Exception:
            return ""

        # 提取最终答案：获取最后一个 agent-markdown 的内容
        # 文心一言的 answerBox 结构：
        #   - 思考过程（第一个 agent-markdown）
        #   - "准备输出结果" 分隔线
        #   - 最终答案文本
        text = await answer_box.evaluate("""el => {
            // chat.baidu.com：answer-box 的 innerText 混入了兄弟 UI chrome——
            //   cs-answer-hover-menu-container（"深度思考/对话支持收藏啦/👌好的继续吧"）
            //   answer-ask-container（"UCloud优刻得的创始人是谁"等追问建议）
            // 这些不是答案正文。优先取内容子区 .chat-search-answer-generate /
            // .cs-answer-container（diag 实测其文本仅比 answer-box 少这 ~73 字 chrome），
            // 取不到再回退 answer-box 全文。
            const content = el.querySelector(
                '.chat-search-answer-generate, .cs-answer-container, .answer-container'
            );
            let allText = (content || el).innerText || '';

            // 防御：若仍含悬停菜单（回退路径），裁掉"深度思考"起的尾部 chrome。
            // 加位置守卫（>40%）避免误裁答案正文里合法提及的"深度思考"。
            const chromeIdx = allText.indexOf('深度思考');
            if (chromeIdx !== -1 && chromeIdx > allText.length * 0.4) {
                allText = allText.substring(0, chromeIdx).trim();
            }

            // 旧结构兼容：按"准备输出结果/思考完成"分隔线取后半
            const marker = '准备输出结果';
            const idx = allText.lastIndexOf(marker);
            if (idx !== -1) {
                return allText.substring(idx + marker.length).trim();
            }
            const thinkMarker = '思考完成';
            const thinkIdx = allText.lastIndexOf(thinkMarker);
            if (thinkIdx !== -1) {
                return allText.substring(thinkIdx + thinkMarker.length).trim();
            }

            return allText;
        }""")

        # 提取链接（从整个 answerBox 中获取）
        links = await answer_box.evaluate("""
            el => {
                const links = el.querySelectorAll('a[href]');
                return Array.from(links).map(a => ({
                    text: a.textContent.trim(),
                    href: a.href
                }));
            }
        """)

        if links:
            citation_lines = []
            for i, link in enumerate(links):
                href = link["href"]
                if href.startswith("javascript:") or href.startswith("#"):
                    continue
                if "baidu.com" in href and "/chat" in href:
                    continue
                link_text = link["text"] or f"[{i+1}]"
                citation_lines.append(f"[{i+1}] {link_text}: {href}")
            if citation_lines:
                text += "\n\n---\n引用来源:\n" + "\n".join(citation_lines)

        return text

    async def _start_new_chat(self, page: Page):
        """开始新对话"""
        try:
            new_btn = page.locator(self.NEW_CHAT_SELECTOR).first
            if await new_btn.is_visible(timeout=3):
                await new_btn.click()
                await asyncio.sleep(2)
            else:
                await page.goto("https://chat.baidu.com", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
        except Exception:
            await page.goto("https://chat.baidu.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)


class DoubaoWebChatClient(WebChatClientBase):
    """豆包 (doubao.com/chat) WebChat 客户端

    字节跳动旗下 AI 聊天平台，强联网搜索集成。
    使用 Semi Design UI 框架（class 前缀 semi-* / samantha-*）。
    页面在未登录状态下也能看到聊天 UI 结构。
    """

    # ── 豆包选择器 ──
    # 豆包的响应在消息气泡中，可能使用多种 class 模式
    INPUT_SELECTOR = (
        "textarea[class*='chat-input'], textarea[class*='input'], textarea[class*='samantha'], "
        "[contenteditable='true'], "
        "[data-testid='chat-input'], textarea"
    )
    SEND_SELECTOR = (
        "button[aria-label*='发送'], button[aria-label*='Send'], "
        "button[class*='send'], button[class*='semi-button-primary'], "
        "[data-testid='send-button']"
    )
    RESPONSE_SELECTOR = (
        "[class*='message-content'], [class*='markdown'], "
        "[class*='response'], [class*='assistant'], "
        "[role='article'], [class*='chat-message']"
    )
    # 扩展：豆包可能用的响应区域选择器
    RESPONSE_FALLBACKS = [
        # 通用聊天消息容器
        "[class*='message']",
        "[class*='msg']",
        "[class*='assistant']",
        "[class*='bot']",
        # 豆包 Semi Design / samantha 系列
        "[class*='samantha']",
        "[class*='semi']",
        # 内容区域
        "[class*='content']",
        "[class*='chat-content']",
        # 最后一个非空的文本容器（兜底）
        "main",
        "article",
    ]
    NEW_CHAT_SELECTOR = (
        "button[class*='new-chat'], "
        "button[aria-label*='新建对话'], "
        "[class*='samantha'][class*='new'], "
        "a[class*='sidebar'][href*='chat']"
    )
    SEARCH_INDICATOR = (
        "[class*='searching'], "
        "[class*='联网'], [class*='search-result']"
    )

    async def _navigate_to_chat(self, page: Page):
        """导航到豆包聊天页面"""
        await page.goto("https://www.doubao.com/chat", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

    async def _type_question(self, page: Page, question: str):
        """在输入框中输入问题"""
        input_el = page.locator(self.INPUT_SELECTOR).first
        await input_el.wait_for(state="visible", timeout=10000)
        await input_el.click()
        await asyncio.sleep(0.3)

        # 统一用 keyboard.type() 模拟真实键盘输入。
        # fill() 会绕过 React onChange，导致发送按钮无法激活。
        await page.keyboard.type(question, delay=30)

    async def _send_question(self, page: Page):
        """发送问题"""
        # 先尝试点击发送按钮（多种选择器回退）
        try:
            for selector in [
                "button[aria-label='发送']",
                "button[aria-label='Send']",
                "[class*='send-btn']",
                "[class*='send-button']",
                "[data-testid='send-button']",
            ]:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    logger.info("WebChat doubao: sent via button click")
                    return
        except Exception:
            pass

        # 回退 1: 聚焦输入框后按 Enter
        try:
            input_el = page.locator(self.INPUT_SELECTOR).first
            await input_el.click()
            await asyncio.sleep(0.2)
            await input_el.press("Enter")
            logger.info("WebChat doubao: sent via Enter on input")
            return
        except Exception:
            pass

        # 回退 2: 全局 Enter
        await page.keyboard.press("Enter")
        logger.info("WebChat doubao: sent via global Enter")

    async def _wait_for_response(self, page: Page, timeout: int = 120):
        """等待豆包响应完成

        策略：定期检查文本增长 + 稳定性。
        豆包的搜索元数据（"搜索X个关键词 参考XX篇资料"）
        在回答完成后出现在响应区域顶部。
        不依赖 CSS 选择器匹配（豆包 DOM 结构不确定）。
        """
        # 等 AI 生成回答，定期检查文本增长
        start_text_len = await self._get_visible_text_len(page)
        logger.info(f"WebChat doubao: waiting for response (initial text: {start_text_len} chars)")

        max_wait = 90  # 最多等 90 秒
        elapsed = 0
        stable_count = 0  # 连续稳定次数
        prev_len = start_text_len

        while elapsed < max_wait:
            await asyncio.sleep(5)
            elapsed += 5

            current_len = await self._get_visible_text_len(page)
            logger.info(f"WebChat doubao: text len after {elapsed}s: {current_len} chars")

            if current_len > prev_len:
                # 文本还在增长，重置稳定计数
                stable_count = 0
                prev_len = current_len
            else:
                # 文本没有增长，增加稳定计数
                stable_count += 1
                if stable_count >= 2:
                    # 文本连续 2 次检查（10秒）没有变化，认为完成
                    # 额外等 3 秒让搜索元数据卡片加载
                    await asyncio.sleep(3)
                    final_len = await self._get_visible_text_len(page)
                    logger.info(f"WebChat doubao: response complete ({final_len} chars)")
                    return

    async def _get_visible_text_len(self, page: Page) -> int:
        """用 JS 提取页面可见文本长度（排除 UI 元素）"""
        try:
            text = await page.evaluate("""() => {
                const exclude = 'input, textarea, button, [role="navigation"], [role="menubar"], header, footer, script, style, noscript, link, meta';
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    {
                        acceptNode: (node) => {
                            const parent = node.parentElement;
                            if (!parent) return NodeFilter.FILTER_REJECT;
                            if (parent.closest(exclude)) return NodeFilter.FILTER_REJECT;
                            // 排除侧边栏、导航栏、logo、品牌区
                            if (parent.closest('nav, [role="sidebar"], [class*="sidebar"], [class*="left-side"], [class*="logo"], [class*="brand"]'))
                                return NodeFilter.FILTER_REJECT;
                            const t = node.textContent.trim();
                            if (t.length < 3) return NodeFilter.FILTER_REJECT;
                            return NodeFilter.FILTER_ACCEPT;
                        }
                    }
                );
                let total = 0;
                let n;
                while (n = walker.nextNode()) total += n.textContent.length;
                return total;
            }""")
            return text or 0
        except Exception:
            return 0

    async def _extract_response(self, page: Page) -> str:
        """提取豆包响应文本，包括引用链接和搜索元数据

        优先用 RESPONSE_SELECTOR 定位响应区域提取文本和链接，
        回退到 TreeWalker 提取可见文本。
        同时提取搜索元数据（关键词数、参考资料数）。
        """
        text = ""
        links = []

        # 1) 尝试用 RESPONSE_SELECTOR 定位响应区域
        try:
            response_area = page.locator(self.RESPONSE_SELECTOR).last
            await response_area.wait_for(state="visible", timeout=5000)
            text = await response_area.inner_text()

            # 提取响应区域内的 <a href> 链接
            links = await response_area.evaluate("""
                el => {
                    const links = el.querySelectorAll('a[href]');
                    return Array.from(links).map(a => ({
                        text: a.textContent.trim(),
                        href: a.href
                    }));
                }
            """)
            logger.info(f"WebChat doubao: extracted {len(text)} chars via RESPONSE_SELECTOR, {len(links)} links")
        except Exception:
            # 2) 回退：TreeWalker 提取可见文本
            logger.info("WebChat doubao: RESPONSE_SELECTOR failed, falling back to TreeWalker")

            # 同时从整个页面提取链接作为补充
            try:
                links = await page.evaluate("""() => {
                    const links = document.querySelectorAll('a[href]');
                    return Array.from(links).map(a => ({
                        text: a.textContent.trim(),
                        href: a.href
                    }));
                }""")
            except Exception:
                links = []

            text = await page.evaluate("""() => {
                const exclude = 'input, textarea, button, [role="navigation"], [role="menubar"], header, footer, script, style, noscript, link, meta';
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    {
                        acceptNode: (node) => {
                            const parent = node.parentElement;
                            if (!parent) return NodeFilter.FILTER_REJECT;
                            if (parent.closest(exclude)) return NodeFilter.FILTER_REJECT;
                            if (parent.closest('nav, [role="sidebar"], [class*="sidebar"], [class*="left-side"], [class*="logo"], [class*="brand"]'))
                                return NodeFilter.FILTER_REJECT;
                            const style = window.getComputedStyle(parent);
                            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0)
                                return NodeFilter.FILTER_REJECT;
                            const t = node.textContent.trim();
                            if (t.length < 3) return NodeFilter.FILTER_REJECT;
                            return NodeFilter.FILTER_ACCEPT;
                        }
                    }
                );
                const texts = [];
                let n;
                while (n = walker.nextNode()) texts.push(n.textContent.trim());
                return texts.join('\\n').trim();
            }""")
            if text:
                logger.info(f"WebChat doubao: extracted {len(text)} chars via TreeWalker fallback, {len(links)} links")

        # 3) 提取搜索元数据（关键词数、参考资料数）
        try:
            search_meta = await page.evaluate("""() => {
                const allText = document.body.innerText || '';
                const meta = { keyword_count: null, reference_count: null };
                const kwMatch = allText.match(/搜索\\s*(\\d+)\\s*个?关键词/);
                if (kwMatch) meta.keyword_count = parseInt(kwMatch[1]);
                const refMatch = allText.match(/参考\\s*(?:了)?\\s*(\\d+)\\s*篇\\s*(?:资料|来源|文献|文章)/);
                if (refMatch) meta.reference_count = parseInt(refMatch[1]);
                return meta;
            }""")
            if search_meta and (search_meta.get("keyword_count") or search_meta.get("reference_count")):
                meta_parts = []
                if search_meta.get("keyword_count"):
                    meta_parts.append(f"搜索关键词: {search_meta['keyword_count']}个")
                if search_meta.get("reference_count"):
                    meta_parts.append(f"参考资料: {search_meta['reference_count']}篇")
                text = text + "\n\n---\n[搜索元数据]\n" + "\n".join(meta_parts)
                logger.info(f"WebChat doubao: search_meta kw={search_meta.get('keyword_count')} ref={search_meta.get('reference_count')}")
        except Exception:
            pass

        # 4) 将链接追加到文本末尾
        if links:
            citation_lines = []
            for i, link in enumerate(links):
                href = link.get("href", "")
                if href.startswith("javascript:") or href.startswith("#"):
                    continue
                if "doubao.com" in href and "/chat" in href:
                    continue
                if "bytedance.com" in href:
                    continue
                link_text = link.get("text") or f"[{i+1}]"
                citation_lines.append(f"[{i+1}] {link_text}: {href}")

            if citation_lines:
                text += "\n\n---\n引用来源:\n" + "\n".join(citation_lines)

        return text or ""
        return text or ""

    async def _start_new_chat(self, page: Page):
        """开始新对话"""
        try:
            new_btn = page.locator(self.NEW_CHAT_SELECTOR).first
            if await new_btn.is_visible(timeout=3):
                await new_btn.click()
                await asyncio.sleep(2)
            else:
                await page.goto("https://www.doubao.com/chat", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(5)
        except Exception:
            await page.goto("https://www.doubao.com/chat", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)


class QwenWebChatClient(WebChatClientBase):
    """千问 (www.qianwen.com) WebChat 客户端

    阿里巴巴旗下 AI 聊天平台，支持思考/研究模式联网搜索。
    注意：tongyi.aliyun.com 已废弃，新网址是 www.qianwen.com。
    页面 UI 清晰，contenteditable 输入框，有"新建对话"按钮。
    """

    # ── 千问选择器 ──
    INPUT_SELECTOR = (
        "[contenteditable='true'], "
        "textarea[class*='chat-input'], textarea[class*='input'], "
        "[data-testid='chat-input']"
    )
    SEND_SELECTOR = (
        "button[aria-label*='发送'], button[aria-label*='Send'], "
        "button[aria-label*='send'], button[class*='send'], "
        "[data-testid='send-button']"
    )
    RESPONSE_SELECTOR = (
        "[class*='message-content'], [class*='markdown'], "
        "[class*='assistant'], [class*='response'], "
        "[role='article']"
    )
    NEW_CHAT_SELECTOR = (
        "button[aria-label*='新建'], "
        "button[class*='new-chat'], "
        "a[href='/'][class*='sidebar'], "
        "[data-testid='new-chat']"
    )
    SEARCH_INDICATOR = (
        "[class*='searching'], [class*='search-indicator'], "
        "[class*='联网'], [class*='research']"
    )

    async def _navigate_to_chat(self, page: Page):
        """导航到千问聊天页面"""
        await page.goto("https://www.qianwen.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

    async def _type_question(self, page: Page, question: str):
        """在输入框中输入问题"""
        input_el = page.locator(self.INPUT_SELECTOR).first
        await input_el.wait_for(state="visible", timeout=10000)
        await input_el.click()
        await asyncio.sleep(0.3)
        await page.keyboard.type(question, delay=30)

    async def _send_question(self, page: Page):
        """发送问题"""
        try:
            send_btn = page.locator(self.SEND_SELECTOR).first
            if await send_btn.is_visible(timeout=5000):
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")
        except Exception:
            await page.keyboard.press("Enter")

    async def _wait_for_response(self, page: Page, timeout: int = 120):
        """等待千问响应完成

        千问有思考/研究模式，会联网搜索。
        先检测搜索指示器，再等文本稳定。
        """
        try:
            search_indicator = page.locator(self.SEARCH_INDICATOR).first
            if await search_indicator.is_visible(timeout=10000):
                await search_indicator.wait_for(state="hidden", timeout=60000)
                logger.info(f"WebChat qwen: search completed")
        except Exception:
            pass

        try:
            resp_area = page.locator(self.RESPONSE_SELECTOR).last
            await resp_area.wait_for(state="visible", timeout=30000)
        except Exception:
            await asyncio.sleep(10)

        await self._wait_for_text_stability(
            page, self.RESPONSE_SELECTOR, timeout=timeout
        )

    async def _extract_response(self, page: Page) -> str:
        """提取千问响应文本"""
        try:
            response_area = page.locator(self.RESPONSE_SELECTOR).last
            await response_area.wait_for(state="visible", timeout=10000)
        except Exception:
            return ""

        text = await response_area.inner_text()

        links = await response_area.evaluate("""
            el => {
                const links = el.querySelectorAll('a[href]');
                return Array.from(links).map(a => ({
                    text: a.textContent.trim(),
                    href: a.href
                }));
            }
        """)

        if links:
            citation_lines = []
            for i, link in enumerate(links):
                href = link["href"]
                if href.startswith("javascript:") or href.startswith("#"):
                    continue
                if "qianwen.com" in href and "/chat" in href:
                    continue
                link_text = link["text"] or f"[{i+1}]"
                citation_lines.append(f"[{i+1}] {link_text}: {href}")
            if citation_lines:
                text += "\n\n---\n引用来源:\n" + "\n".join(citation_lines)

        return text

    async def _start_new_chat(self, page: Page):
        """开始新对话"""
        try:
            new_btn = page.locator(self.NEW_CHAT_SELECTOR).first
            if await new_btn.is_visible(timeout=3):
                await new_btn.click()
                await asyncio.sleep(2)
            else:
                await page.goto("https://www.qianwen.com", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
        except Exception:
            await page.goto("https://www.qianwen.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)


# ── 客户端工厂 ──

WEBCHAT_CLIENT_CLASSES = {
    "deepseek": DeepSeekWebChatClient,
    "ernie": ErnieWebChatClient,
    "doubao": DoubaoWebChatClient,
    "kimi": KimiWebChatClient,
    "qwen": QwenWebChatClient,
}


def create_web_chat_client(model_key: str) -> WebChatClientBase:
    """创建 WebChat 客户端实例"""
    cls = WEBCHAT_CLIENT_CLASSES.get(model_key)
    if not cls:
        raise ValueError(f"未知模型: {model_key}")
    return cls(model_key)