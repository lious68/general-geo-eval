# 样本提交契约

`validate --file 样本.json` / `submit --dry-run --file 样本.json` 只做本地格式检查，不上传、不绑定、不验证服务端分配与验收结论。submit 自动执行相同检查。

| 字段 | 约束 |
|---|---|
| assignment_id | 当前分配的 32 位小写十六进制编号；不能自行生成 |
| prompt / platform | 非空字符串，必须与分配结果完全一致，服务端核对 |
| answer | 非空原始回答，不改写 |
| answer_complete | JSON 布尔值 true / false |
| citations_state | complete / incomplete / none_visible |
| citations | 数组；complete 不能空，none_visible 必须空 |
| citations[].kind | citation（正文引用）或 search_source（参考来源） |
| citations[].url | HTTP(S) 完整真实 URL 字符串，不能为 null、对象或猜测值 |
| citations[].title / marker | 页面实际标题、标记，不能据截断标签猜测；缺失说明写入 completeness_notes |
| conditions.model | 非空字符串；不可确认写 unknown |
| conditions.web_search | on / off / unknown |
| conditions.new_conversation | 布尔值 |
| conditions.collected_at | 带时区 ISO 8601 时间 |
| conditions 中其他字段 | 保留项目要求的实际观察值；验收核对项目 conditions |
| evidence.page_text | 当前题页面原文非空字符串 |
| evidence.completeness_notes | 建议字符串数组，记录缺失项、证据与原因，不包含凭据 |
| screenshot_paths | 1–20 个本机 PNG/JPEG 路径；相对路径相对于 JSON 所在目录 |

总包（包括编码后的截图）不超过 5,000,000 字节。截图应可阅读，完整覆盖任务内容，不包含其他会话、账号资料或凭据。优先文件传递，不让模型复制或转录图片 Base64。脚本进行签名与编码检查，不能替代肉眼检查截图可读性。

服务端还会核对分配归属、开始记录、题目和渠道、批次有效性、幂等状态；本地 valid=true 不是服务端一定接收或验收通过的保证。

claim 返回的每道题带 `source`（来源编号：品牌 / 大任务 / 子任务NN·平台 / 题号，如 `UCloud / 925 众包测试 / 子任务03·kimi / q007`）。它由服务端生成，提交时服务端会自动把这条编号盖到样本上，样本 JSON 不需要也不能填写它。进度记录、证据目录名和汇报中请同时写 assignment_id 与 source，方便回收时核对归属。历史项目可能没有 source，此时照常采集。

| 状态 | 含义与下一步 |
|---|---|
| pending | 已提交、待人工验收；不重新提问，没有承诺的固定审批时长 |
| accepted | 已验收通过，不能改写；不等于已付款。forced_acceptance=true 表示管理员人工强制通过，原始完整性问题仍保留 |
| revision | 退回补充，读 review.reason；恢复原会话，以原 assignment_id 追加版本 |
| rejected | 最终驳回，不能覆写；有异议联系负责人 |
| late | 迟交或已释放批次后首次提交，保留但不计入配额；联系负责人核对 |

网络失败：outbox 保留，恢复后 retry。服务端明确拒绝（400/422）：原上传包保留至 archive 与 failed，可修正源文件再次 submit。成功：archive 按题目分配编号和内容摘要保存各版本，receipts 保留回执和摘要。不会删除传入的源 JSON；本地留档包含任务正文与截图，请勿把整个目录随意分享。

限速仍由服务端执行。start 返回 retry_after 时按值等待；resume_only=true 只恢复已有会话，不重新发送问题。当前没有在 claim 返回全部限额余额，不把文档的上限解释为平台保证额度。
