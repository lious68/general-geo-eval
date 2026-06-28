# 豆包 (doubao.com/chat) WebChat DOM 结构与抓取

> 客户端：`core/web_chat_clients.py` `DoubaoWebChatClient`（约 L1153）
> 证据脚本：`scripts/diag_doubao_refs.py`（产物 `output/doubao_search_dom.json`）

## 页面概览

- 站点：`https://www.doubao.com/chat`。字节跳动，Semi Design UI（class 前缀 `semi-*` / `samantha-*`）。
- 强联网搜索集成，回答下方有「搜索 N 个关键词，参考 X 篇资料」折叠卡片。
- 未登录也能看到聊天 UI 结构，但发不出请求。

## 回答正文

- `RESPONSE_SELECTOR = "[class*='message-content'], [class*='markdown'], [class*='response'], [class*='assistant'], [role='article'], [class*='chat-message']"`。
- 实测 `RESPONSE_SELECTOR` 常失败（命中不到稳定气泡）→ 回退 **TreeWalker** 取 `[class*="message-list"]` 内可见文本，排除 `nav/sidebar/logo/brand` 与 `display:none/visibility:hidden/opacity:0`。对话隔离由 `_start_new_chat` 保证（见下）。

## ★ 引用源

豆包的联网搜索引用源在回答下方「搜索N个关键词，参考X篇资料」折叠卡片里，每篇资料一个 `<a href>`（标题 + URL）：

- 卡片标题元素：`<div class="relative flex-row inline-flex ... cursor-pointer ...">搜索 3 个关键词，参考 17 篇资料</div>`。
- 资料链接共同祖先：`div.container-SIvZXF ... > a.flex-row.max-w-full.min-w-0`。
- **无 iframe / shadow DOM**，且页面默认就渲染了（不用点展开也能抓到）。
- 搜索元数据（关键词数/参考资料数）在 `document.body.innerText` 里匹配 `搜索\s*(\d+)\s*个?关键词` / `参考\s*(?:了)?\s*(\d+)\s*篇\s*(?:资料|来源|文献|文章)`。

**抓取**（`_extract_doubao_reference_links`）：
1. 先点开折叠的「参考资料」触发器（`div.cursor-pointer, [class*="reference"], [class*="source"], details, summary`，文本含「参考」+「篇/资料/来源」）。
2. 找标题元素（文本匹配 `参考(?:了)?\s*\d+\s*篇\s*(?:资料|来源|文献|文章)` 且 <60 字），向上找含 ≥2 个 `<a href>` 的祖先容器作为资料列表根；也纳入标题父节点的兄弟链（折叠内容常在兄弟节点）。
3. 兜底：回答消息区 `[class*="message-list"], [class*="container-SIvZXF"]` 内所有 `<a href>`。
4. 过滤 `doubao.com/chat`、`bytedance.com` 站内跳转；按 href 去重；append 进 `引用来源` 段。

## 题间对话隔离（关键）

豆包是 SPA，点 logo / 点「新对话」**只改路由不重置 SPA 状态**——发送下一题时 SPA 仍持有旧会话 id，回到旧会话或竞态下不渲染。

`_start_new_chat` 用**硬 `goto /chat` 整页重载**撕掉 SPA 旧会话指针，再等输入框就绪，并校验 URL 为 `/chat`（无 session id）且 `message-list` 为空。证据：`diag_doubao_newchat3/4`（点 logo 后 URL 弹回 `/chat/<id>`；硬 goto 后干净）。

## 已知问题

- `RESPONSE_SELECTOR` 命中率低，常走 TreeWalker 回退（日志 `extracted N chars via TreeWalker fallback`）。
- 引用源抓取偶尔返回 0（`reference links extracted: 0`）但 `search_meta ref=17`——说明卡片 DOM 改版或加载时序问题，待复现。
