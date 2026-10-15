# 众包采集运行方式

2026-10-03 起，WebChat 采集仅使用：GEO 评测大任务 → 采集子项目 → 准活正式任务 → 参与者星图/WorkBuddy Skill → 原始证据验收 → 评分与覆盖率。

- 不再配置 Windows 执行机、远程桌面、守护进程、Webhook、浏览器登录态上传或下载执行配置。
- 服务端保留题库、品牌、历史结果、历史结果导入、引用分析、评分、众包与准活通信；既有 API 模型分析能力保留。历史 WebChat 模式标签只用于辨认已有数据。
- 众包 Skill 中的有头浏览器/CDP 是参与者本机能力，不属于被删除的服务端爬虫。
- `/api/batches/*`、`/api/webchat/auth/*`、批次配置下载/创建/重推接口不再注册。服务端评测请求 mode=webchat 会被拒绝且不会新建执行记录。
- 历史数据库表、样本、截图、评分和凭证文件不随源码清理删除。Windows 云主机并未销毁；本次也未对其服务或任务计划作停用确认，不应假定资源已释放。

## 开发验证
在仓库根目录 PowerShell：`$env:PYTHONPATH="$PWD/backend"; python -m pytest tests -q`。
前端构建仍使用部署材料中的 baseline/frontend，并同步本轮修改的 TaskList.vue、TaskDetail.vue、api/tasks.js。
后端入口 backend/app.py，生产服务 geo-eval.service。
