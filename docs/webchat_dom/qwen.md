# 千问 (www.qianwen.com) WebChat DOM 结构与抓取

> 客户端：`core/web_chat_clients.py` `QwenWebChatClient`（约 L1604）
> 证据脚本：`scripts/diag_qwen_refs.py`（产物 `output/qwen_search_dom.json`）

## 页面概览

- 站点：`https://www.qianwen.com`（旧 `tongyi.aliyun.com` 已废弃）。
- SPA，contenteditable 输入框，有「新建对话」。
- **模式开关**：输入框上方有 `思考 / 研究` 两个 button（`aria-label` 同名）。`研究` 模式才触发联网搜索。「研究」未选中时提问 → 千问纯推理，回答里**没有任何引用源**，且会写幻觉时间（"截至2026年6月"）。
  - 当前实现未强制切到「研究」模式，依赖用户登录态默认模式。若 citation_rate 系统性为 0，先排查是否处于思考模式。

## 回答正文

- 选择器：`RESPONSE_SELECTOR = "[class*='message-content'], [class*='markdown'], [class*='assistant'], [class*='response'], [role='article']"`。
- 实测命中 `<div class="qk-markdown qk-markdown-react ...">`（`ANSWER_HTML_PROBE` 确认 `sel=[class*="markdown"]`）。
- 正文是标准 Markdown 渲染（`qk-md-paragraph / qk-md-strong / qk-md-ul` 等），`inner_text()` 即可取。

## ★ 引用源（关键，与其它模型不同）

千问的参考资料面板「N篇来源」里，**每条来源不是 `<a href>`**，而是一个 favicon 代理 `<img>`：

```
<div class="reference-wrap-iEjeb3" id="reference-link-anchor-...">
  <div class="link-title-igf0OC">
    <div class="search-content-iMifAk">
      <div class="search-icon-list-i55_Lz">
        <div class="search-icon-item-...">
          <img src="http://s2.zimgs.cn/ims?at=smstruct&kt=url&key=aHR0cHM6..." />
        </div>
      </div>
      ... 标题 + www.ucloud.cn 2026年06月23日 - 摘要 ...
    </div>
  </div>
</div>
```

- `img.src` 的 `key=` 参数是 **base64 编码的真实来源 URL**，解码后多为 `https://<来源域名>/favicon.ico`（如 `aHR0cHM6` → `https:`）。
- 来源真实域名还会出现在卡片标题文本里，形如 `标题 www.ucloud.cn 2026年06月23日 - 摘要`。
- 面板默认折叠，需先点「N篇来源」展开才渲染全部来源项。

**原版 bug**：`_extract_response` 用 `querySelectorAll('a[href]')` → 必然返回 0 → `citation_rate` 被系统性记 0。

## 抓取方式（`_extract_qwen_reference_links`）

1. 点开「N篇来源」折叠面板（`get_by_text('篇来源')` 或 `[class*="reference-wrap"]`，best-effort）。
2. 全页找所有 `img[src*="key="]`，对每个：
   - `atob(key)`（补齐 padding）解码 favicon URL，正则取 host。
   - 取其最近祖先 `[class*="reference-wrap"]` 等容器的标题文本，正则 `((?:[a-z0-9-]+\.)+[a-z]{2,})` 提取域名。**标题域名优先**于 favicon host（favicon 可能是 CDN 代理域）。
   - 重建 `https://<host>` 作为引用 URL。
3. 跳过神马搜索快照域（`zimgs.cn / sm.cn / cdn.sm.cn / aliyuncs.com`）且标题无真实域名的项——宁缺毋滥，不当搜索缓存当引用。
4. 按 href 去重，append 进 `引用来源` 段。

## 实测结果（2026-06-28，q003「UCloud海外有哪些节点？」）

修复后单题复跑 `output/qwen_cite_verify.json`：
- `has_citation=True`、`citation_count=2`
- `all_cited_urls` 5 条：`docs.ucloud.cn`(is_ucloud=True)、`36kr.com`、`jiemian.com`、`www.ucloud.cn`(is_ucloud=True)、`vps234.com`
- `citation_rate`：0 → **1.0**
- 无页脚/导航假阳性。

## 登录态

- 登录票据 cookie：`tongyi_sso_ticket`（httpOnly, .qianwen.com, 1 年）+ `b-user-id`。
- `b-user-id` 登录前就有（浏览器指纹），**不能**据此判已登录；必须含 `tongyi_sso_ticket`。
- 证据：`scripts/test_qwen_auth_cookies.py`。
