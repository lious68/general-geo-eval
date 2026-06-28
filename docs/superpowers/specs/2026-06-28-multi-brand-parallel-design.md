# 多品牌并行独立评测（general-geo-eval：从单品牌可切换到多品牌并行）

> 日期：2026-06-28
> 范围：在已完成「单品牌通用化」（见 `2026-06-24-general-brand-design.md`）的基础上，把系统升级为多品牌并行独立评测——`brand_id` 贯穿题集 → 任务 → 批次 → 结果 → 评分全链路，各品牌数据隔离，靠全局「当前品牌」选择器切换；UCloud 作为预置默认品牌，首屏体验不变。

## Context（为什么做）

`2026-06-24-general-brand-design.md` 已让系统从"UCloud 写死"变为"任意单品牌可测"：`core/brand_profile.py` 的 `BrandProfile` 集中承载品牌信息，`derive_from_input()` 按品牌名/公司/官网/行业派生关键词/官方域名/引用规则，分析引擎对任意品牌生效。

但当前仍是**单品牌**部署：

- 品牌档案存于 `app_settings` 的单一键 `brand_profile`（`backend/routers/settings.py:173` `GET/PUT /api/settings/brand-profile`），全局只有"一个当前品牌"。
- `questions` / `tasks` / `evaluation_runs` / `analysis_results` / `geo_scores` 表**没有 brand_id**——所有题集、任务、结果、评分混在一起，靠"当前品牌档案"这一个全局量兜底。
- `db._BRAND_PROFILE_CACHE`（`backend/database.py:26`）是单个缓存，`get_brand_profile()` 返回当前品牌；`recalculate_task_scores`（`backend/services/task_service.py:238`）与 `evaluations.py:157` 都直接 `db.get_brand_profile()`。
- Home.vue 是单品牌档案设置页，未设品牌时强制弹必填框。

**多品牌并行的需求**：一套系统同时维护多个被测品牌，每个品牌有自己独立的题集/任务/分数，互不污染，随时切换查看；换品牌不覆盖旧品牌的题集与分数。

**核心矛盾**：当前"全局单品牌档案 + 无 brand_id 的表"在多品牌下会错乱——切到品牌 B 时重算 UCloud 老任务会用 B 的口径；题集切换会覆盖；任务列表混在一起。必须让 `brand_id` 贯穿全链路，并把"全局档案"降级为"按 task 所属品牌取档案"。

**约束（用户明确）**：UCloud 作为日常主力品牌，操作路径不能变复杂。多品牌只在不增加单品牌用户负担的前提下提供。

## 关键决策（已与用户确认）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 核心使用场景 | 多品牌并行独立评测 | 各品牌题集/任务/分数互不污染，不跨品牌横向对比 |
| 界面组织 | 全局「当前品牌」选择器（顶部导航栏，每页可见） | 单品牌操作路径零增量；多品牌一键切换 |
| 数据模型 | 彻底重表：brand_id 贯穿全链路 + 索引 | 多品牌并行最干净；加列轻量方案留包袱 |
| 历史数据兼容 | 迁移补 brand_id='ucloud'，预置 UCloud 品牌 | 首屏无感；老任务/评分全部可见 |
| 题集归属 | 题集品牌私有（questions 加 brand_id） | 与"并行独立"一致，UCloud 题集与品牌 B 互不可见 |
| 品牌档案存储 | 新建 `brands` 表（id/brand_name/.../brand_profile_json）+ 品牌列表页 | 取代单一 app_settings.brand_profile 键，可索引可维护 |
| Home 页 | Home.vue 改造为品牌列表页 | 多品牌入口集中；品牌档案设置不再是独立首屏 |
| 本地 runner 归属 | task_config.json 带 brand_id + 该品牌 profile | 多品牌并行时导入不归错；runner 口径与服务器一致 |
| 评分口径 | 不变：仍按 task 内全部模型×问题做分母；但 profile 按 task.brand_id 取 | 与现状一致，仅修正 profile 来源 |
| UCloud 预置 | 迁移时预置 brand_id='ucloud'，设为 current_brand_id | 首屏默认 UCloud，体验不变 |

## 架构：品牌成为一等公民

### 数据模型

**新增 `brands` 表：**

```sql
CREATE TABLE IF NOT EXISTS brands (
    id                TEXT PRIMARY KEY,          -- slug，如 'ucloud'、'acme'
    brand_name        TEXT NOT NULL,
    company_name      TEXT DEFAULT '',
    website           TEXT DEFAULT '',
    industry          TEXT DEFAULT '',
    brand_profile_json TEXT NOT NULL,            -- BrandProfile.to_dict() 完整序列化
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active         INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_brands_active ON brands(is_active);
```

- `id` 用 slug（小写、无空格），便于 URL/日志/外键可读。预置 `ucloud`，`brand_profile_json` = 现有 `default_brand_profile().to_dict()`。
- `brand_profile_json` 承载完整 `BrandProfile`（keywords/official_domains/url_patterns/reference_keywords/display_names），取代现在 `app_settings.brand_profile` 单键。
- `app_settings` 新增键 `current_brand_id`（TEXT，默认 'ucloud'）记录当前选中品牌。

**贯穿 brand_id（加列 + 索引 + 迁移补值，全部幂等）：**

| 表 | 新增列 | 默认值 | 索引 |
|----|--------|--------|------|
| `questions` | `brand_id TEXT DEFAULT 'ucloud'` | 'ucloud' | `idx_questions_brand(brand_id, is_active)` |
| `tasks` | `brand_id TEXT DEFAULT 'ucloud'` | 'ucloud' | `idx_tasks_brand(brand_id)` |
| `evaluation_runs` | `brand_id TEXT DEFAULT 'ucloud'` | 'ucloud' | `idx_runs_brand(brand_id)` |
| `analysis_results` | `brand_id TEXT DEFAULT 'ucloud'` | 'ucloud' | `idx_results_brand(brand_id)` |
| `geo_scores` | `brand_id TEXT DEFAULT 'ucloud'` | 'ucloud' | `idx_scores_brand(brand_id)` |

迁移用现有 `column_exists()`（`database.py:348`）前置检查 → `ALTER TABLE ... ADD COLUMN ... DEFAULT 'ucloud'`（SQLite ADD COLUMN with DEFAULT 自动给现有行补默认值）→ `CREATE INDEX IF NOT EXISTS`。`task_units` 表不加 brand_id（它按 run_id 关联，run 已带 brand_id，避免冗余）。

### 品牌档案缓存层修正

现有 `_BRAND_PROFILE_CACHE`（单个 `BrandProfile`）改为**按 brand_id 缓存的 dict**：

```python
_BRAND_PROFILE_CACHE: Dict[str, BrandProfile] = {}  # brand_id -> profile

def get_brand_profile(brand_id: str = None) -> BrandProfile:
    """取某品牌档案；brand_id 为 None 时取 current_brand_id；缓存未命中从 brands 表加载。"""

def get_brand_profile_by_id(brand_id: str) -> BrandProfile:
    """显式按 brand_id 取档案（评分重算用，不依赖 current）。"""
```

`refresh_brand_profile_cache()` 改为 `refresh_brand_cache()`：启动时把所有 active 品牌档案加载到 dict；品牌 CRUD 后局部刷新。

### 关键口径修正（多品牌必须）

现在 `recalculate_task_scores`（`task_service.py:238`，用 `db.get_brand_profile()`）和 `evaluations.py:157`（同）都依赖**全局当前品牌**。多品牌后这是 bug：切到品牌 B 时重算 UCloud 老任务会用 B 的口径。

修正原则：**评分始终按 task 所属品牌的档案算，不依赖全局 current_brand_id。**

| 调用点 | 现状 | 改为 |
|--------|------|------|
| `task_service.recalculate_task_scores(task_id)` | `db.get_brand_profile()` | `get_task(task_id)` 拿 `brand_id` → `db.get_brand_profile_by_id(brand_id)` |
| `task_service.create_batch_config` | `db.get_brand_profile()`（写 config.brand_profile） | 按 `task.brand_id` 取该品牌 profile |
| `task_service.import_batch_results` | 走 recalculate，间接修正 | 同上（recalculate 修正后自动正确） |
| `backend/routers/evaluations.py:157`（单次 API 评测，无 task） | `db.get_brand_profile()` | `db.get_brand_profile()`（取 current_brand_id）——单次评测属当前品牌，正确 |
| `backend/routers/results.py`（历史 run 重算） | 视 run 是否属 task | 属 task 用 task.brand_id；裸 run 用 current |
| `database.backfill_citations` / `is_natural_question` 同步辅助 | `_active_brand_profile()`（单缓存） | 按 row.brand_id 取；无 brand_id 列时 fallback current |

`core/metrics.py` 的 `MetricsCalculator.calculate_scores(..., brand_profile=)` 签名不变——它本就接收 profile 参数，只是调用方传对的 profile。

## 改造点明细

### A. 后端：brands 表 + 品牌档案迁移

`backend/database.py`：

1. `SCHEMA_SQL` 加 `brands` 表定义。
2. `init_db()` 迁移块（`_migrate_add_columns` 之后）幂等执行：
   - 建 `brands` 表；
   - 若 `brands` 为空且 `app_settings.brand_profile` 有值 → 把现有单品牌档案迁为 `ucloud` 一行（或新建 ucloud 用 default_brand_profile）；同时把 `current_brand_id` 设为该 brand_id；
   - 各表 `ADD COLUMN brand_id ... DEFAULT 'ucloud'`（`column_exists` 前置）+ 建索引；
   - 调 `refresh_brand_cache()`。
3. 新增 `db.list_brands()` / `get_brand(brand_id)` / `create_brand(...)` / `update_brand(...)` / `delete_brand(brand_id)`（删除前校验该品牌无活跃题集/任务，或级联软删）。
4. 新增 `db.get_current_brand_id()` / `db.set_current_brand_id(brand_id)`（读写 `app_settings.current_brand_id`）。
5. 改 `get_brand_profile(brand_id=None)` / `get_brand_profile_by_id(brand_id)` / `refresh_brand_cache()` 如上。
6. 改 `save_brand_profile`：不再写单一键，改为 `update_brand(brand_id, profile)`（更新 brands 行）。
7. `get_questions` / `list_tasks` / `list_task_batches` / `get_task_results` / `get_task_scores` / `get_task_coverage` 等查询加 `brand_id` 过滤参数（默认 current；显式传可查指定品牌）。
8. `create_task` / `add_task_batch` / `save_task_analysis_result` / `save_task_geo_scores` / `upsert_question` 写入时带 brand_id（task/批次用所属品牌；题集用 current 或指定）。

### B. 后端：brands 路由

新增 `backend/routers/brands.py`，prefix `/api/brands`：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `` | 列出所有 active 品牌（含题集数/任务数/覆盖率摘要） |
| POST | `` | 新建品牌（brand_name/company/website/industry → `derive_from_input` → 入库；返回 profile） |
| GET | `/{brand_id}` | 取单品牌档案 |
| PUT | `/{brand_id}` | 更新品牌档案（重新 derive） |
| DELETE | `/{brand_id}` | 删除品牌（校验无活跃数据或级联） |
| GET | `/current` | 取 current_brand_id + 其档案 |
| PUT | `/current` | 设 current_brand_id（body: {brand_id}） |

`/api/settings/brand-profile`（旧）**保留兜底**：GET 返回 current 品牌档案（兼容旧前端缓存）；PUT 转发为"更新 current 品牌档案"。避免老缓存前端报错，但新前端改用 `/api/brands`。

### C. 后端：questions/tasks 路由按品牌过滤

- `GET /api/questions`：加 `brand_id` query（默认 current）；`get_questions` 已加过滤。
- `POST /api/questions/generate`：body 加 `brand_id`（默认 current）；`generate_and_replace` 生成题集绑定到该 brand_id（`upsert_question` 带 brand_id），并把档案写入该 brands 行（不再覆盖全局）。
- `GET /api/tasks`：加 `brand_id` query；`list_tasks` 已加过滤。
- `POST /api/tasks`：创建时带 brand_id（默认 current）；`create_task` 带 brand_id。
- `GET /api/tasks/{task_id}` 等详情接口：不变（按 task_id 取，task 自带 brand_id）。
- `task_config.json`（`create_batch_config`）：加 `brand_id`（= task.brand_id）+ `brand_profile`（= 该品牌 profile）。

### D. 前端：全局当前品牌选择器

新增 composable `frontend/src/composables/useCurrentBrand.js`：
- reactive `currentBrand`（{id, brand_name, ...}）+ `setCurrentBrand(id)`（调 `PUT /api/brands/current` 后更新 + 触发全局 reload 事件）。
- 提供 `onBrandChanged(cb)` 供各页订阅切换事件。

顶部导航栏（`App.vue` 或 layout）加 `el-select`：
- 列出所有品牌（`GET /api/brands`），label 显示 brand_name，当前选中 current。
- 切换 → `setCurrentBrand` → 各页通过 `onBrandChanged` 重载数据（Questions/TaskList/Dashboard 等）。
- 默认 current=ucloud，UCloud 用户首屏无需操作。

### E. 前端：Home.vue 改造为品牌列表页

`Home.vue` 从"单品牌档案设置页"改为"品牌列表页"：
- 卡片/表格列出所有品牌：brand_name、industry、website、题集数、任务数、覆盖率摘要（从 `GET /api/brands`）。
- 每张卡片操作：「设为当前」（setCurrentBrand）、「编辑档案」（弹框编辑 brand_name/company/website/industry → `PUT /api/brands/{id}` 重新 derive）、「查看题集/任务」（跳对应页并切到该品牌）。
- 顶部「新建品牌」按钮：填 brand_name/company/website/industry → `POST /api/brands`（derive_from_input）→ 刷新列表。
- 原"必填品牌弹窗"逻辑保留但改为：**无任何品牌时**强制弹"新建第一个品牌"（系统初始化时已有预置 ucloud，正常不会触发；纯空库兜底）。
- 原 Home 的派生信息预览（官方域名/关键词/引用词）移到品牌编辑弹框内。

### F. 前端：Questions/TaskList/TaskDetail/Dashboard 按当前品牌过滤

- `Questions.vue`：`loadQuestions` 默认取当前品牌题集（`GET /api/questions?brand_id=current`）；"AI 生成"对话框不再每次手填品牌信息，从当前品牌档案预填（brand_name/company/website/industry 只读带入，可改场景数/模型），生成绑定当前品牌。订阅 `onBrandChanged` 重载。
- `TaskList.vue`：`listTasks` 带当前品牌；新建任务默认归属当前品牌。订阅 `onBrandChanged` 重载。
- `TaskDetail.vue`：不变（按 task_id 取，task 自带品牌；面包屑可显示所属品牌名）。
- `Dashboard.vue`：任务下拉（`listTasks`）只列当前品牌任务（你刚做的下拉天然兼容，只需 `listTasks` 带 brand_id）。订阅 `onBrandChanged` 重载。
- `BatchDownloadDialog.vue`：不变（题区间选择基于当前品牌 task 总题集，已天然隔离）。

### G. 前端：Settings.vue 清理

- 移除"品牌关键词"相关（已迁到品牌档案编辑，`/api/settings/keywords` 旧接口保留兜底但前端不再用）。
- 模型 API Key / 评分权重 / 用户管理 / ModelVerse 保留（这些是全局配置，不分品牌）。
- 可选：Settings 顶部加"当前品牌"只读提示。

## UCloud 操作复杂度评估（核心约束验证）

| 操作 | 现状（单品牌） | 多品牌后 | 增量 |
|------|----------------|----------|------|
| 进系统 | 直接看 UCloud | current 默认 UCloud，首屏同 | 0 |
| 看题集 | 问题管理 | 问题管理（已过滤 UCloud） | 0 |
| 建任务 | 新建任务 | 新建任务（默认 UCloud） | 0 |
| 加批次 | 添加批次 | 添加批次 | 0 |
| 看仪表盘 | 仪表盘 | 仪表盘（任务下拉只 UCloud） | 0 |
| 换品牌看 | — | 顶部下拉切一下 | +1 次点击 |
| 测新品牌 | — | 品牌列表页「新建品牌」 | 新增能力 |

**结论**：UCloud 单品牌用户除顶部多一个品牌选择器（且默认就是 UCloud）外，操作路径零增量。只有真要测第二个品牌时才需去品牌列表新建。满足"通用又不让 UCloud 变复杂"。

## 实施顺序（分步可验证）

1. **后端数据层**：`brands` 表 + 各表 brand_id 列/索引 + 迁移补 ucloud + 预置 ucloud + `refresh_brand_cache` + `get_brand_profile(_by_id)` 改造。跑 `test_db_migration` / `test_tasks_service` 确认不回归。
2. **后端口径修正**：`recalculate_task_scores` / `create_batch_config` / `evaluations` / `results` 按 task.brand_id 取 profile。跑 `test_tasks_api`。
3. **后端路由**：`brands.py` CRUD + current；questions/tasks 路由加 brand_id 过滤；task_config 加 brand_id；旧 brand-profile 兜底。跑 `test_tasks_api`。
4. **前端 composable + 选择器**：`useCurrentBrand` + 顶部 `el-select` + `onBrandChanged` 订阅。
5. **前端 Home 改品牌列表页** + Questions/TaskList/Dashboard 订阅切换重载 + Settings 清理。
6. **本地 runner**：config 带 brand_id（runner 无逻辑改动，仅 config 多字段）；服务器导入按 config.brand_id 归属。
7. **文案**：Home 标题"品牌设置"→"品牌管理"；各页"被测品牌"措辞统一。提交推送。

## 关键文件

- `backend/database.py` — brands 表 + brand_id 列/索引 + 迁移 + 缓存改造 + 查询过滤。
- `backend/routers/brands.py` — 新增品牌 CRUD + current。
- `backend/routers/questions.py` / `tasks.py` / `evaluations.py` / `results.py` / `settings.py` — brand_id 过滤/兜底。
- `backend/services/task_service.py` — recalculate/create_batch 按 task.brand_id 取 profile；config 带 brand_id。
- `backend/services/question_generator.py` — generate_and_replace 绑定 brand_id。
- `frontend/src/composables/useCurrentBrand.js` — 新增。
- `frontend/src/App.vue`（或 layout）— 顶部品牌选择器。
- `frontend/src/views/Home.vue` — 改品牌列表页。
- `frontend/src/views/Questions.vue` / `TaskList.vue` / `Dashboard.vue` / `Settings.vue` — 按当前品牌过滤 + 订阅切换。
- 不改：`core/metrics.py`（签名不变）、`core/brand_profile.py`（BrandProfile 不变，只改存储）、`core/analyzer.py`、`task_units` 表。

## 验证（端到端）

1. **迁移**：在现有 geo.db 上启动 → `brands` 表有 ucloud 一行；questions/tasks/evaluation_runs/analysis_results/geo_scores 的 brand_id 全为 'ucloud'；`current_brand_id='ucloud'`；现有任务/题集/评分全部可见。
2. **UCloud 无感**：以 UCloud 登录，首屏 Home=品牌列表且 current=ucloud；Questions/TaskList/Dashboard 数据与改造前一致；建任务/加批次/看仪表盘路径不变。
3. **多品牌并行**：新建品牌 B（如 Acme）→ 切到 B → Questions 为空（B 无题集）→ AI 生成 B 题集（绑定 B）→ 建任务/加批次（属 B）→ 导入结果 → 仪表盘只看 B 任务。切回 UCloud → UCloud 题集/任务/分数不受 B 影响（隔离验证）。
4. **口径修正**：切到 B 时对 UCloud 老任务点「重算」→ 用 UCloud 档案算（不串口径）；验证 `geo_scores` 不变（除非档案本身没变）。
5. **runner 归属**：B 品牌批次下载的 config 含 `brand_id=B` + B 的 profile；导入后结果 brand_id=B，归属正确。
6. **回退**：current_brand_id 锁 ucloud + 前端不传 brand_id → 行为等同单品牌；brand_id 列保留无害。

## 风险与回退

- **迁移风险**：ADD COLUMN DEFAULT 自动补值，幂等；现有自检脚本（test_db_migration/test_tasks_service/test_tasks_api/test_runner_v2_config/test_scheduler_selfcheck）防回归。迁移前备份 geo.db。
- **口径串品牌**：核心风险点，靠"评分按 task.brand_id 取 profile"统一修正，并在 recalculate/results 两处都改。验证步骤 4 专测。
- **旧前端缓存**：`/api/settings/brand-profile` 保留兜底；新前端改用 `/api/brands`。
- **品牌删除**：校验该品牌无活跃题集/任务，否则提示先清空或改为软删（is_active=0）。
- **回退**：brand_id 列默认 'ucloud' 保留无害；锁 current=ucloud 即恢复单品牌行为。
- 不碰 metrics/analyzer 口径逻辑，不影响其他模型和历史分数。

## 不做的事（YAGNI）

- 不做品牌间横向对比视图（并行独立，不跨品牌比）。
- 不做品牌级权限/多租户（单系统共享登录）。
- 不改 metrics 权重/口径逻辑（只改 profile 来源）。
- 不动 task_units 表结构（按 run_id 关联即可）。
- 不做品牌导入导出。
