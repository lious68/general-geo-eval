"""
UCloud GEO 评估框架 - WebChat 浏览器自动化客户端
使用 Playwright 模拟真实用户在各 AI 模型官网的 Web Chat 交互，
获取带联网搜索引用的完整响应。

当前已实现：Kimi（联网搜索最强）
其他模型暂为 stub，后续逐个调试适配。
"""
import asyncio
import logging
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
        """启动浏览器（在评测开始时调用一次）"""
        if not self.is_configured:
            logger.warning(f"WebChat {self.model_key}: 无认证状态，无法评测")
            return False

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        self._context = await self._browser.new_context(
            storage_state=self._auth_state,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self._page = await self._context.new_page()
        logger.info(f"WebChat {self.model_key}: 浏览器已启动")
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
                                         timeout: int = 120, interval: int = 2,
                                         stable_threshold: int = 3):
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
                    logger.info(f"WebChat {self.model_key}: response stable after {elapsed}s ({stable_count} checks)")
                    # 等额外 5 秒，让可能的后续引用卡片加载
                    await asyncio.sleep(5)
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

        # 文本稳定
        await self._wait_for_text_stability(
            page, self.RESPONSE_SELECTOR, timeout=timeout
        )

    async def _extract_response(self, page: Page) -> str:
        """提取 Kimi 响应文本，包括引用链接

        Kimi 的引用格式：搜索结果卡片 + 正文中 [1][2] 等引用标记
        需要把引用链接嵌入到正文中，使 ResponseAnalyzer 能识别
        """
        # 等响应区域出现
        try:
            response_area = page.locator(self.RESPONSE_SELECTOR).last
            await response_area.wait_for(state="visible", timeout=10000)
        except Exception:
            # 回退：获取最后一个消息元素
            response_area = page.locator("[class*='message']").last

        # 提取纯文本
        text = await response_area.inner_text()

        # 提取所有 <a href> 链接，嵌入到文本中
        links = await page.evaluate("""
            () => {
                const responseEl = document.querySelector('[class*="markdown"], [class*="message-content"], [class*="assistant"]');
                if (!responseEl) return [];
                const links = responseEl.querySelectorAll('a[href]');
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
                # 过滤掉站内导航链接和 javascript:
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
    """DeepSeek WebChat 客户端（暂未实现，需调试选择器）"""
    async def _navigate_to_chat(self, page: Page):
        raise NotImplementedError("DeepSeek WebChat 尚未适配，请使用 API 模式")
    async def _type_question(self, page: Page, question: str):
        raise NotImplementedError
    async def _send_question(self, page: Page):
        raise NotImplementedError
    async def _wait_for_response(self, page: Page, timeout: int = 120):
        raise NotImplementedError
    async def _extract_response(self, page: Page) -> str:
        raise NotImplementedError
    async def _start_new_chat(self, page: Page):
        raise NotImplementedError


class ErnieWebChatClient(WebChatClientBase):
    """文心一言 WebChat 客户端（暂未实现）"""
    async def _navigate_to_chat(self, page: Page):
        raise NotImplementedError("文心一言 WebChat 尚未适配，请使用 API 模式")
    async def _type_question(self, page: Page, question: str):
        raise NotImplementedError
    async def _send_question(self, page: Page):
        raise NotImplementedError
    async def _wait_for_response(self, page: Page, timeout: int = 120):
        raise NotImplementedError
    async def _extract_response(self, page: Page) -> str:
        raise NotImplementedError
    async def _start_new_chat(self, page: Page):
        raise NotImplementedError


class DoubaoWebChatClient(WebChatClientBase):
    """豆包 WebChat 客户端（暂未实现）"""
    async def _navigate_to_chat(self, page: Page):
        raise NotImplementedError("豆包 WebChat 尚未适配，请使用 API 模式")
    async def _type_question(self, page: Page, question: str):
        raise NotImplementedError
    async def _send_question(self, page: Page):
        raise NotImplementedError
    async def _wait_for_response(self, page: Page, timeout: int = 120):
        raise NotImplementedError
    async def _extract_response(self, page: Page) -> str:
        raise NotImplementedError
    async def _start_new_chat(self, page: Page):
        raise NotImplementedError


class QwenWebChatClient(WebChatClientBase):
    """通义千问 WebChat 客户端（暂未实现）"""
    async def _navigate_to_chat(self, page: Page):
        raise NotImplementedError("通义千问 WebChat 尚未适配，请使用 API 模式")
    async def _type_question(self, page: Page, question: str):
        raise NotImplementedError
    async def _send_question(self, page: Page):
        raise NotImplementedError
    async def _wait_for_response(self, page: Page, timeout: int = 120):
        raise NotImplementedError
    async def _extract_response(self, page: Page) -> str:
        raise NotImplementedError
    async def _start_new_chat(self, page: Page):
        raise NotImplementedError


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