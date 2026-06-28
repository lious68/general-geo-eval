# WebChat 各模型 DOM 结构与内容抓取说明

本目录按模型逐一记录其官网 WebChat 的 DOM 结构、回答正文选择器、**引用源/参考资料**在 DOM 里的真实位置与抓取方式。各模型的页面 DOM 差异极大，引用源尤其如此（有的是 `<a href>`、有的是折叠卡片、有的是 base64 编码的 favicon 代理图），故每个模型单独一份。

> 抓取实现见 `core/web_chat_clients.py`（每个 `XxxWebChatClient._extract_response()`），证据采集脚本见 `scripts/diag_*_*.py`。抓回来的 URL 以 `[n] text: url` 形式 append 进响应文本末尾的 `---\n引用来源:\n` 段，由 `core/analyzer.py` 的通用 URL 正则自动收录进 `all_cited_urls` / `citations`，最终影响 `citation_rate`（权重 0.25）。

| 模型 | 文件 | 引用源 DOM 形态 |
|---|---|---|
| 千问 qwen | [qwen.md](qwen.md) | favicon 代理 img，base64 编码真实 URL，**非** `<a href>` |
| 豆包 doubao | [doubao.md](doubao.md) | 「搜索N关键词，参考X篇资料」折叠卡片里的 `<a href>` |
| Kimi kimi | [kimi.md](kimi.md) | segment-assistant 区内 `<a href>`（易混入页脚招聘链接，需过滤） |
| 文心一言 ernie | [ernie.md](ernie.md) | answer-box 内 `<a href>`，需裁掉思考过程/悬停菜单 chrome |
| DeepSeek deepseek | [deepseek.md](deepseek.md) | ds-markdown 区内 `<a href>`（模型纯推理，引用来自正文 markdown） |

## 通用约定

- **正文选择器**：每个类的 `RESPONSE_SELECTOR`，`.last` 取最新回答回合（多轮对话取最后一个）。
- **引用 append 格式**：`text += "\n\n---\n引用来源:\n" + "\n".join([f"[{i+1}] {link_text}: {href}" ...])`。analyzer 用 `https?://` 正则扫全文收录，所以只要 URL 出现在文本里就会被计入 `all_cited_urls`。
- **宁缺毋滥**：所有模型都**不**回退到「全页抓 `<a href>`」。Kimi 的教训——页脚「社会招聘/校园招聘」会被当成引用灌进去造成假阳性。必须锚定「参考资料容器」。
- **状态机**：`_start_new_chat()` → `_type_question()` → `_send_question()` → `_wait_for_response()` → `_extract_response()`，每题重置对话（SPA 模型用硬 goto 整页重载撕掉会话指针，见 doubao.md）。
