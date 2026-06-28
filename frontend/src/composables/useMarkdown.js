// 轻量 Markdown 渲染 — 仅支持模型回答里常见的基础语法：
//   标题(#)、有序/无序列表、粗体、行内代码、分隔线(---)、段落、链接。
// 不引入 marked / markdown-it 等大依赖（前端当前没有 markdown 库）。
// 安全：所有输出经过转义，杜绝 XSS；链接强制 target=_blank rel=noopener。
// 设计取舍：模型回答（豆包/千问/文心/Kimi/DeepSeek）基本都是结构化列表+粗体，
// 复杂表格/嵌套极少，手写一个小解析器足够，且可定制度高（如把"引用来源"段做成可点链接）。

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

// 行内格式：粗体、行内代码、链接 [text](url)、裸 URL
function renderInline(line) {
  let s = escapeHtml(line)
  // 行内代码 `code`（先处理，避免内部被二次解析）
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  // 链接 [text](url)
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (m, txt, url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${txt}</a>`)
  // 粗体 **text** 或 __text__
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>')
  // 裸 URL（未被链接包裹的）→ 可点链接。
  // 避开已生成的 href="..." 里的 URL：用捕获组保留前缀字符（非 " = 字母）。
  s = s.replace(/(^|[^"=\w])(https?:\/\/[^\s<]+)/g,
    (m, pre, url) => `${pre}<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>`)
  return s
}

/**
 * 把模型回答的 markdown 文本渲染成 HTML 字符串（供 v-html）。
 * @param {string} md
 * @returns {string}
 */
export function renderMarkdown(md) {
  if (!md) return ''
  const lines = String(md).replace(/\r\n/g, '\n').split('\n')
  const out = []
  let listType = null      // 'ul' | 'ol' | null
  let inCitations = false  // 是否进入"引用来源"段（做成链接清单）

  const closeList = () => {
    if (listType) { out.push(`</${listType}>`); listType = null }
  }

  for (let raw of lines) {
    const line = raw.replace(/\s+$/, '')

    // 引用来源段标记
    if (/^-{3,}\s*$/.test(line.trim())) {
      closeList()
      out.push('<hr/>')
      // 下一行若是"引用来源:"则进入链接清单样式
      inCitations = true
      continue
    }
    if (inCitations && /^引用来源[:：]?\s*$/.test(line.trim())) {
      closeList()
      out.push('<div class="md-citations-label">📎 引用来源</div>')
      continue
    }

    // 空行
    if (!line.trim()) { closeList(); continue }

    // 标题
    const hm = line.match(/^(#{1,6})\s+(.*)$/)
    if (hm) {
      closeList()
      const lvl = hm[1].length
      out.push(`<h${lvl}>${renderInline(hm[2])}</h${lvl}>`)
      continue
    }

    // 有序列表项：开头是 数字. 或 [n]
    const om = line.match(/^\s*(\d+)[.、)]\s+(.*)$/)
    const bm = line.match(/^\s*[-*+]\s+(.*)$/)

    if (inCitations) {
      // 引用来源段：把 "[n] text: url" 渲染成可点链接行
      const cm = line.match(/^\s*\[(\d+)\]\s*(.*?)\s*:\s*(https?:\/\/\S+)\s*$/)
      if (cm) {
        if (listType !== 'ul') { closeList(); out.push('<ul class="md-citations">'); listType = 'ul' }
        out.push(`<li><span class="md-cite-idx">[${cm[1]}]</span> ${renderInline(cm[2])} <a href="${escapeHtml(cm[3])}" target="_blank" rel="noopener noreferrer">${escapeHtml(cm[3])}</a></li>`)
        continue
      }
      // 非标准行则退出引用段样式
      inCitations = false
    }

    if (om) {
      if (listType !== 'ol') { closeList(); out.push('<ol>'); listType = 'ol' }
      out.push(`<li>${renderInline(om[2])}</li>`)
      continue
    }
    if (bm) {
      if (listType !== 'ul') { closeList(); out.push('<ul>'); listType = 'ul' }
      out.push(`<li>${renderInline(bm[1])}</li>`)
      continue
    }

    // 普通段落
    closeList()
    out.push(`<p>${renderInline(line)}</p>`)
  }
  closeList()
  return out.join('\n')
}
