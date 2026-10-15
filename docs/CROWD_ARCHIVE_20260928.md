

## 2026-09-28 项目分组与可恢复回收站
- GEO Crowd.vue 改为大任务分组、默认展开最近一项、每页6个大任务，支持搜索和空分组；新增子项目预填所属任务。大任务覆盖率取原 tasks API，未改评分计算。
- delete 接口改为软回收；project_archive 保留回收状态，project_audit 追加审计，恢复保持暂停。保留 task_links、samples、评分来源，不执行硬删除。
- 准活 geo_workflow.sync 经认证 gateway/lifecycle 推送关联任务状态、未结事项和已登记付款样本ID；GEO 仅在状态新鲜（180秒内）、准活已取消/回收、无待处理样本且已通过样本均有付款登记时允许回收。新验收但尚未同步结算的样本也会阻止回收。
- 回收禁用项目、释放其租约、作废发布关联码；恢复不恢复租约或订单，不自动重新发布；终止任务不再被定时同步改回进行中。
- 测试：GEO test_crowd + test_crowd_archive 22项、准活 test_geo_batch + test_geo_crowd + test_ops_work + test_geo_lifecycle 35项通过；Vite 构建通过；check_archive_groups.js 模拟浏览器验证8大任务分页/预填/回收/恢复/审计成功。未用真实任务执行回收、验收或付款。
- 生产版本及备份详见 geo-crowd-deployment/archive2-deploy-report.json（部署成功后写入）。部署1/2脚本有固定版本保护，不直接重跑。新增表可保留兼容旧代码；不要为回滚覆盖整个数据库，否则会丢掉期间业务数据。代码回滚不会恢复暂停状态，应按任务实际状态人工核对。
- 此轮代码仍为未提交改动；测试和部署脚本需一并保留。准活#24的回收与订单由用户处理，本轮只同步状态，不代用户回收GEO子项目15。
