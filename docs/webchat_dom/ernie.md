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

文心一言的参考资料列表项是 `<li class="_reference-item_*">`，**本身不是 `<a href>`**——只有少数可见链接（如「UCDN节点分布」的 `a.marklang-link`）是真正的 `<a>`。每条来源的真实 URL 藏在 `li` 的属性里：

```
<li class="_reference-item_1jesp_5"
    data-long-press-ext-info='{"link":"https://docs.ucloud.cn/...","linkTitle":"节点分布...",...}'>
  1. 节点分布 云分发 UCDN_文档中心_UCloud中立云计算服务商
</li>
```

响应文本里能看到「共参考31篇资料」+序号+标题，但 12 个 li 都 `href=None`，原版只抓 `a[href]` 只能拿到 1 条 → `citation_rate` 偏低。

**抓取**（`_extract_response` 的 evaluate）：
1. `a[href]`：普通可见链接（`marklang-link` 等），过滤 `javascript:` / `#` / `baidu.com/chat`。
2. `li[data-long-press-ext-info]`：解析该属性（`&quot;` 先解码成 `"`）取 `link`，`linkTitle` 作为标题。
3. 按 href 去重，append 进 `引用来源` 段。

证据：`scripts/diag_ernie_refs2.py`。实测（q003，单题复跑）：`citation_count` 0→29，`all_cited_urls` 含 `docs.ucloud.cn`、`www.ucloud.cn`（is_ucloud）及知乎/bilibili/搜狐等第三方源。

## 登录态

- 首页输入框匿名态就可见——基类「输入框可见」弱信号会误判已登录 → 抢救保存只有匿名 cookie 的半成品 state → 下次一加载被踢回登录页（「每次要重新登录」根因）。
- 强信号 = **BDUSS cookie**：百度通行证 httpOnly 登录凭证，仅完整登录后下发。httpOnly → `document.cookie` 读不到，必须用 `context.cookies()`。
- 证据：`diag_ernie_login_state.py` 登录翻转 [2]→[5]：登录前只有匿名态 cookie（BAIDUID/RT/ab_sr…，无 BDUSS）；登录后 BDUSS+STOKEN+PTOKEN+UBI 写入。
