# Kimi (www.kimi.com) WebChat DOM 结构与抓取

> 客户端：`core/web_chat_clients.py` `KimiWebChatClient`（约 L319）
> 证据脚本：`scripts/debug_kimi*.py`、`diag_kimi_login_state.py`

## 页面概览

- 站点：`https://www.kimi.com`（已从 `kimi.moonshot.cn` 迁移）。月之暗面，SPA。
- 自动联网搜索，无需手动开启搜索模式。搜索时显示「搜索中...」，完成后有引用卡片。
- 输入框是 contenteditable div（React 编辑器，**只响应真实键盘事件**，用 `page.keyboard.type(delay=15)`）。

## 回答正文

- 优先 `segment.segment-assistant, .segment-assistant`（`.last`）。`inner_text()` 取正文，>50 字视为成功。
- 回退：TreeWalker 取全页文本，排除 `nav/menubar/header/footer` 与左屏 30% 侧边栏（`getBoundingClientRect().x < bodyW*0.3` 拒绝）。

## ★ 引用源

Kimi 的引用是 `segment-assistant` 区内的 `<a href>`。**但有页脚假阳性风险**——历史结果里出现过「社会招聘/校园招聘/探索月之暗面」等页脚/导航链接被当成引用灌进去。

**抓取**（`_extract_links_from_area`）：
- 从 `segment-assistant` 区内取 `<a href>`，过滤 `javascript:` / `#` / `kimi.com` 站内。
- 回退路径里也用 TreeWalker 收 `<a>`，同样过滤站内。
- append 进 `引用来源` 段。

> 注：Kimi 假阳性主要来自回退的 TreeWalker 全页抓取。锚定 `segment-assistant` 区可缓解；若仍出现页脚链接，需收紧到回答气泡内。

## 登录态

- `kimi-auth` cookie 登录中途就出现、聊天输入框落地页就可见，都是**弱信号**。
- 真正会话凭证在 **localStorage**：`access_token`(JWT) / `msh_user_id` 仅完整登录后写入；`anonymous_access_token` 是匿名态，不算登录。
- `_is_logged_in` 探测 `localStorage.getItem('access_token') || msh_user_id`。
- 证据：`diag_kimi_login_state.py`——登录后 localStorage 有 `access_token+refresh_token+msh_user_id`、`loginBtn=False avatar=True`；登录前只有 `anonymous_*`。
