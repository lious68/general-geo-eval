# DeepSeek (chat.deepseek.com) WebChat DOM 结构与抓取

> 客户端：`core/web_chat_clients.py` `DeepSeekWebChatClient`（约 L702）

## 页面概览

- 站点：`https://chat.deepseek.com`。React SPA，需登录后才看到聊天界面。
- **纯推理模型，不内置联网搜索**（与 Kimi/豆包/千问不同）。因此引用源来自模型正文里 markdown 自带的链接，而非平台搜索卡片。

## 回答正文

- `RESPONSE_SELECTOR = "[class*='assistant-message'], div.ds-markdown.ds-assistant-message-main-content, div.ds-markdown, [data-testid='assistant-message'], [class*='message-assistant'], [class*='markdown-body'], [class*='markdown'], .chat-message-assistant, .message-content"`。
- `_extract_response` 优先精确选择器 `div.ds-markdown.ds-assistant-message-main-content`、`[class*='assistant-message']`（`.last`），避免匹配到 markdown 子元素；都失败回退 `[class*='markdown']`。

## ★ 引用源

- 从 `response_area` 内取 `<a href>`，过滤 `javascript:` / `#`。
- append 进 `引用来源` 段。
- 因模型纯推理，链接是模型在正文里「引用」的（如知乎/CSDN/博客园等技术社区文章），由 analyzer 通用正则收录，第三方域名（知乎/CSDN 等）在「回答提及 UCloud」时计入引用（见 `analyzer._detect_citations` 第 4 步 + `THIRD_PARTY_CITATION_DOMAINS`）。

## 题间隔离

- `_start_new_chat`：优先点「新建对话」按钮（`NEW_CHAT_SELECTOR`），失败回退硬 `goto https://chat.deepseek.com`。
