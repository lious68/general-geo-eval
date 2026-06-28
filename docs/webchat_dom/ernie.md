# 文心一言 (chat.baidu.com) WebChat DOM 结构与抓取

> 客户端：`core/web_chat_clients.py` `ErnieWebChatClient`（约 L903）
> 证据脚本：`scripts/diag_ernie_*.py`

## 页面概览

- 站点：`https://chat.baidu.com`（旧 `yiyan.baidu.com` 已迁移，2026）。
- 百度，支持联网搜索和深度思考。使用**哈希化 CSS 类名**（如 `editable__T7WAW4uW`），故选择器以结构/语义属性为主，辅以类名模式匹配。

## 回答正文

- `RESPONSE_SELECTOR = ".answer-box.last-answer-box, .answer-box, .conversation-flow-answer-container"`（`.last` 取最新回答回合）。
- 实测 DOM（`diag_ernie_response2`）：`conversation-flow-answer-container > answer-box.last-answer-box > chat-search-answer-generate > ... > cs-answer-container`。
- 旧选择器 `[class*='answerBox']`(驼峰) 匹配不到——实际类名是 `answer-box`(短横线)；`[class*='answer']`(小写) 过宽，`.last` 会命中底部空的 `answer-tips-wrapper`(innerText="") → 死循环到超时 / 返回 ""。

**正文提取**（`_extract_response` 的 evaluate）：
- 优先取内容子区 `.chat-search-answer-generate, .cs-answer-container, .answer-container`（其文本仅比 `answer-box` 少 ~73 字 UI chrome），取不到回退 `answer-box` 全文。
- `answer-box` 的 `innerText` 混入了兄弟 UI chrome：`cs-answer-hover-menu-container`（「深度思考/对话支持收藏啦/👌好的继续吧」）、`answer-ask-container`（追问建议）——这些不是答案正文。
- 防御：若仍含悬停菜单，裁掉「深度思考」起的尾部 chrome（加位置守卫 `>40%` 避免误裁答案正文里合法提及的「深度思考」）。
- 旧结构兼容：按「准备输出结果 / 思考完成」分隔线取后半。

## ★ 引用源

- 从 `answer-box` 内取 `<a href>`，过滤 `javascript:` / `#` / `baidu.com/chat` 站内。
- append 进 `引用来源` 段。

## 登录态

- 首页输入框匿名态就可见——基类「输入框可见」弱信号会误判已登录 → 抢救保存只有匿名 cookie 的半成品 state → 下次一加载被踢回登录页（「每次要重新登录」根因）。
- 强信号 = **BDUSS cookie**：百度通行证 httpOnly 登录凭证，仅完整登录后下发。httpOnly → `document.cookie` 读不到，必须用 `context.cookies()`。
- 证据：`diag_ernie_login_state.py` 登录翻转 [2]→[5]：登录前只有匿名态 cookie（BAIDUID/RT/ab_sr…，无 BDUSS）；登录后 BDUSS+STOKEN+PTOKEN+UBI 写入。
