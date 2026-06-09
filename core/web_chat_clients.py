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

    async def initialize(self):
        """启动浏览器（在评测开始时调用一次）

        豆包等网站检测 Playwright 自动化浏览器，需要在有 X 显示的环境下
        使用 headless=False（配合 xvfb-run）才能绕过反爬检测。
        服务器上 systemd 服务需用 xvfb-run 启动 uvicorn。
        """
        if not self.is_configured:
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
            storage_state=self._auth_state,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
                current_length = await page.evaluate(
                    f"() => (document.querySelector('{selector}')?.innerText || '').length"
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

        logger.warning(f"WebChat {self.model_key}: response timeout after {timeout}s")
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

    async def _navigate_to_chat(self, page: Page):
        """导航到 Kimi 新对话页面"""
        await page.goto("https://www.kimi.com", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

    async def _type_question(self, page: Page, question: str):
        """在输入框中输入问题（Kimi 用 contenteditable div，不是 textarea）"""
        input_box = page.locator(self.INPUT_SELECTOR).first
        await input_box.wait_for(state="visible", timeout=10000)
        await input_box.click()
        await asyncio.sleep(0.3)
        # contenteditable div 用 fill 不一定可靠，用 type 更接近真实输入
        await page.keyboard.type(question, delay=30)

    async def _send_question(self, page: Page):
        """发送问题"""
        # 尝试点击发送按钮
        try:
            send_btn = page.locator(self.SEND_SELECTOR).first
            if await send_btn.is_visible():
                await send_btn.click()
            else:
                # 回退：用 Enter 键发送
                await page.keyboard.press("Enter")
        except Exception:
            await page.keyboard.press("Enter")

    async def _wait_for_response(self, page: Page, timeout: int = 120):
        """等待 Kimi 响应完成

        Kimi 搜索流程：先搜索（显示"搜索中..."）→ 再生成回答 → 流式输出
        等待策略：先等搜索指示器消失，再等文本稳定
        """
        # 先等搜索指示器出现然后消失
        try:
            search_indicator = page.locator(self.SEARCH_INDICATOR).first
            if await search_indicator.is_visible(timeout=10000):
                # 等搜索完成
                await search_indicator.wait_for(state="hidden", timeout=60000)
                logger.info(f"WebChat kimi: search completed")
        except Exception:
            # 可能没有搜索指示器，直接继续
            pass

        # 等响应区域出现 + 文本稳定
        # Kimi 的响应在 segment.segment-assistant 中
        await page.wait_for_selector("segment.segment-assistant, .segment-assistant", timeout=60000)
        await self._wait_for_text_stability(
            page, "segment.segment-assistant, .segment-assistant", timeout=timeout
        )

    async def _extract_response(self, page: Page) -> str:
        """提取 Kimi 响应文本，包括引用链接

        Kimi 的响应在 segment.segment-assistant 中，markdown-container 包含正文
        """
        # 找到响应区域：segment-assistant
        try:
            response_area = page.locator("segment.segment-assistant, .segment-assistant").last
            await response_area.wait_for(state="visible", timeout=10000)
        except Exception:
            # 回退：用 markdown-container
            try:
                response_area = page.locator(".markdown-container, .markdown").last
                await response_area.wait_for(state="visible", timeout=10000)
            except Exception:
                # 最终回退：返回空字符串
                return ""

        # 提取纯文本
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

        # 将链接追加到文本末尾
        if links:
            citation_lines = []
            for i, link in enumerate(links):
                href = link["href"]
                if href.startswith("javascript:") or href.startswith("#"):
                    continue
                if "kimi.com" in href and "/chat" in href:
                    continue
                link_text = link["text"] or f"[{i+1}]"
                citation_lines.append(f"[{i+1}] {link_text}: {href}")

            if citation_lines:
                text += "\n\n---\n引用来源:\n" + "\n".join(citation_lines)

        return text

    async def _start_new_chat(self, page: Page):
        """开始新对话"""
        try:
            new_chat_btn = page.locator(self.NEW_CHAT_SELECTOR).first
            if await new_chat_btn.is_visible(timeout=3):
                await new_chat_btn.click()
                await asyncio.sleep(2)
            else:
                # 回退：直接导航到首页
                await page.goto("https://www.kimi.com", wait_until="networkidle", timeout=30000)
                await asyncio.sleep(2)
        except Exception:
            await page.goto("https://www.kimi.com", wait_until="networkidle", timeout=30000)
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
        "[contenteditable='true'][class*='input'], "
        "#chat-input, .chat-input textarea"
    )
    SEND_SELECTOR = (
        "button[data-testid='send-button'], "
        "button[aria-label*='Send'], button[aria-label*='send'], "
        "button[class*='send'], img[class*='send'], "
        "button[type='submit'][class*='chat']"
    )
    RESPONSE_SELECTOR = (
        "[data-testid='assistant-message'], "
        "[class*='assistant-message'], [class*='message-assistant'], "
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
        input_el = page.locator(self.INPUT_SELECTOR).first
        await input_el.wait_for(state="visible", timeout=10000)
        await input_el.click()
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
        # 等响应区域出现
        try:
            resp_area = page.locator(self.RESPONSE_SELECTOR).last
            await resp_area.wait_for(state="visible", timeout=30000)
        except Exception:
            # 回退：等页面内容变化
            await asyncio.sleep(10)

        # 等文本稳定
        await self._wait_for_text_stability(
            page, self.RESPONSE_SELECTOR, timeout=timeout
        )

    async def _extract_response(self, page: Page) -> str:
        """提取 DeepSeek 响应文本，包括引用链接"""
        try:
            response_area = page.locator(self.RESPONSE_SELECTOR).last
            await response_area.wait_for(state="visible", timeout=10000)
        except Exception:
            try:
                response_area = page.locator("[class*='markdown']").last
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
    """文心一言 (yiyan.baidu.com) WebChat 客户端

    百度的 AI 聊天平台，支持联网搜索和深度思考。
    Baidu 使用哈希化的 CSS 类名（如 editable__T7WAW4uW），
    因此选择器以结构/语义属性为主，辅以类名模式匹配。
    """

    # ── 文心一言选择器 ──
    INPUT_SELECTOR = (
        "[contenteditable='true'], "
        "[class*='editable'], "
        "[class*='input-area'], textarea"
    )
    SEND_SELECTOR = (
        "button[aria-label*='发送'], button[aria-label*='Send'], "
        "button[class*='send']"
    )
    # 回答容器：answerBox 是最终输出区域（含思考+答案）
    RESPONSE_SELECTOR = (
        "[class*='answerBox'], "
        "[class*='answer']"
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

    async def _navigate_to_chat(self, page: Page):
        """导航到文心一言"""
        await page.goto("https://yiyan.baidu.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

    async def _type_question(self, page: Page, question: str):
        """在输入框中输入问题"""
        input_el = page.locator(self.INPUT_SELECTOR).first
        await input_el.wait_for(state="visible", timeout=10000)
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

        文心一言有"深度思考"模式，会先输出思考过程再输出最终答案。
        等待策略：先等 answerBox 出现 → 等深度思考完成 → 等文本稳定
        """
        # 等待回答区域出现
        try:
            resp_area = page.locator("[class*='answerBox'], [class*='answer']").last
            await resp_area.wait_for(state="visible", timeout=30000)
        except Exception:
            await asyncio.sleep(10)

        # 等待深度思考完成：思考中会显示"深度思考中..."之类的指示器
        try:
            thinking_el = page.locator("[class*='thinking'], [class*='loading']").first
            if await thinking_el.is_visible(timeout=5000):
                await thinking_el.wait_for(state="hidden", timeout=120000)
                logger.info(f"WebChat ernie: deep thinking completed")
        except Exception:
            pass

        # 等文本稳定（文心思考模式较慢，给更长的稳定等待时间）
        await self._wait_for_text_stability(
            page, "[class*='answerBox'], [class*='answer']", timeout=timeout
        )

    async def _extract_response(self, page: Page) -> str:
        """提取文心一言响应文本

        文心一言的回答区域包含"深度思考"过程和最终答案。
        需要过滤掉思考过程的文本，只保留最终答案。
        """
        try:
            answer_box = page.locator("[class*='answerBox'], [class*='answer']").last
            await answer_box.wait_for(state="visible", timeout=10000)
        except Exception:
            return ""

        # 提取最终答案：获取最后一个 agent-markdown 的内容
        # 文心一言的 answerBox 结构：
        #   - 思考过程（第一个 agent-markdown）
        #   - "准备输出结果" 分隔线
        #   - 最终答案文本
        text = await answer_box.evaluate("""el => {
            // 尝试获取最终答案文本
            // 思考过程在 agent-markdown 元素中，最终答案在它们之后
            const allText = el.innerText || '';

            // 如果有"准备输出结果"分隔线，取其之后的内容
            const marker = '准备输出结果';
            const idx = allText.lastIndexOf(marker);
            if (idx !== -1) {
                return allText.substring(idx + marker.length).trim();
            }

            // 如果有"思考完成"分隔线，取其之后的内容
            const thinkMarker = '思考完成';
            const thinkIdx = allText.lastIndexOf(thinkMarker);
            if (thinkIdx !== -1) {
                return allText.substring(thinkIdx + thinkMarker.length).trim();
            }

            // 兜底：取全文
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
                await page.goto("https://yiyan.baidu.com", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
        except Exception:
            await page.goto("https://yiyan.baidu.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)


class DoubaoWebChatClient(WebChatClientBase):
    """豆包 (doubao.com/chat) WebChat 客户端

    字节跳动旗下 AI 聊天平台，强联网搜索集成。
    使用 Semi Design UI 框架（class 前缀 semi-* / samantha-*）。
    页面在未登录状态下也能看到聊天 UI 结构。
    """

    # ── 豆包选择器 ──
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
    NEW_CHAT_SELECTOR = (
        "button[class*='new-chat'], "
        "button[aria-label*='新建对话'], "
        "[class*='samantha'][class*='new'], "
        "a[class*='sidebar'][href*='chat']"
    )
    SEARCH_INDICATOR = (
        "[class*='searching'], [class*='searching'], "
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

        豆包会联网搜索，先等搜索指示器消失，再等文本稳定。
        """
        # 1. 等待搜索指示器消失（如果有）
        try:
            search_indicator = page.locator(self.SEARCH_INDICATOR).first
            if await search_indicator.is_visible(timeout=10000):
                await search_indicator.wait_for(state="hidden", timeout=60000)
                logger.info(f"WebChat doubao: search completed")
        except Exception:
            pass

        # 2. 等待响应区域出现
        try:
            resp_area = page.locator(self.RESPONSE_SELECTOR).last
            await resp_area.wait_for(state="visible", timeout=30000)
            logger.info("WebChat doubao: response area visible")
        except Exception:
            # 没匹配到，给个短暂等待后继续
            logger.warning("WebChat doubao: response selector not matched, continuing")
            await asyncio.sleep(2)

        # 3. 等文本稳定
        await self._wait_for_text_stability(
            page, self.RESPONSE_SELECTOR, timeout=timeout
        )

    async def _extract_response(self, page: Page) -> str:
        """提取豆包响应文本"""
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
                if "doubao.com" in href and "/chat" in href:
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