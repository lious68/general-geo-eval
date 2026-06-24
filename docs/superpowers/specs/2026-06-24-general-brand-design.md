# 通用化改造设计（general-geo-eval：从 UCloud 专用到任意品牌）

> 日期：2026-06-24
> 范围：把固定服务 UCloud 的 GEO 评测系统改为通用版本——任意品牌输入品牌/官网/行业后，AI 生成题集并完成端到端评测。

## Context（为什么做）

当前系统围绕 UCloud 写死：

- `core/questions.py` 是 100 道固定的 UCloud 云服务题。
- `core/config.py` 的 `BRAND_KEYWORDS` / `citation.url_patterns` / `reference_keywords` 全部指向 UCloud。
- `core/analyzer.py` 的 `ResponseAnalyzer` 直接读 `config.BRAND_KEYWORDS`，且 `_detect_recommendations` / `_calculate_rank` / `_detect_all_urls` / `_incorporate_search_results` 内多处硬编码 `"UCloud"` / `"优刻得"` / `"ucloud"` 字面量。
- `core/metrics.py`、`backend/database.py`、`backend/services/eval_runner.py` 各自复制了一份 `ucloud|优刻得` 正则用于"自然问题"判定（引导型/题干含品牌词的题不计入提及率、TOP3 分母）。
- 换一个品牌后：题集不会变、提及/引用/推荐指标也不会统计新品牌——系统无法复用。

本次目标：

1. **问题管理 AI 通用生成**：根据用户输入的品牌、网址、行业，用 AI 按行业特性生成题集——每个场景恰好 5 个示例问题，可含品牌词/公司名/产品型号，简洁模拟真实搜索意图。
2. **首页改造**：首页改为让用户输入测试品牌、网站；未输入时对话框提示必选。
3. **分析引擎全量通用化**：让提及率/引用率/TOP3 推荐率等指标对任意品牌生效。

## 关键决策（已与用户确认）

| 决策点 | 选择 |
|--------|------|
| "每场景 5 题"中的"场景" | AI 按用户行业自动生成若干场景（category），每场景恰好 5 题；场景数由 AI 按行业特性决定（默认 8~12） |
| 通用化范围 | 全量——分析器/品牌关键词/引用 URL 规则一并通用化 |
| AI 生成用哪个模型 | 复用系统设置里已配置的 5 个模型之一（默认 DeepSeek，前端可下拉选） |
| 生成题集如何与现有题集共存 | 替换为当前品牌题集（单品牌部署）：生成时先把旧题 `is_active=0`，再插入新题 |
| 品牌关键词来源 | 由品牌名/公司名/官网自动派生 primary/aliases/official_domains/url_patterns/reference_keywords，用户可在设置微调 |
| DB 字段 `is_ucloud` | 保留字段名不动，语义泛化为"是否被测品牌官方引用"，避免数据迁移 |

## 架构：品牌档案 BrandProfile

新增 `core/brand_profile.py`，定义统一品牌档案，集中承载"当前测试品牌"信息，替代散落各处的 UCloud 硬编码。档案存于 `app_settings`（单品牌部署）。

### `BrandProfile` dataclass

输入项：
- `brand_name`（品牌名，如 "UCloud"）
- `company_name`（公司名，如 "优刻得"，可选）
- `website`（官网，如 "https://www.ucloud.cn"）
- `industry`（行业，如 "云计算"）

派生项（`derive_from_input()` 自动生成）：
- `keywords = {primary, products, flagship, aliases}` —— primary/aliases 由 brand_name + company_name 组合；products/flagship 默认空，留给用户补
- `official_domains` —— 从 website 解析主域名及 www 变体（如 `ucloud.cn`）
- `url_patterns` —— 由 official_domains 生成正则字符串列表（如 `https?://(www\.)?ucloud\.cn`）
- `reference_keywords` —— 由品牌名生成（如 "据UCloud"、"UCloud官网"）
- `display_names` —— brand_name + company_name + aliases，用于推荐/排名检测中的品牌文本匹配

### 提供的函数

- `default_brand_profile()` —— 从现有 `config.BRAND_KEYWORDS` 构造 UCloud 默认档案，保证 CLI `main.py` / 旧数据向后兼容
- `load_brand_profile_from_settings(get_setting)` —— 服务端从 `app_settings` 读取并反序列化
- `is_natural_question(question, category, profile)` —— 用 profile.primary+aliases 判定自然问题，替代 3 处写死的 `ucloud|优刻得` 正则
- `build_question_pattern(profile)` —— 编译品牌关键词正则

## 改造点明细

### A. 分析引擎通用化

`ResponseAnalyzer.__init__(brand_profile=None)`：传入则用档案，不传用 UCloud 默认。

| 方法 | 改造 |
|------|------|
| `_detect_brand_mentions` | 已用 `self.brand_keywords`，改为来自档案 |
| `_detect_citations` | `url_patterns` / `reference_keywords` 来自档案 |
| `_detect_all_urls` | `channel.startswith("UCloud") or "ucloud" in url` → `url 命中 official_domains` |
| `_incorporate_search_results` | 同上 |
| `_detect_recommendations` | `"UCloud" in ctx or "优刻得" in ctx` → `any(name in ctx for name in display_names)`；`brand="UCloud"` → `brand=profile.brand_name` |
| `_calculate_rank` | `brand_positions["UCloud"]` → `brand_positions["__target__"]` |

`MetricsCalculator.calculate_scores(..., brand_profile=None)`：自然问题过滤改用 `brand_profile`。

`database.is_natural_question` / `eval_runner._is_natural_question` / `metrics._is_natural_question` 三处重复正则统一改为调用 `core.brand_profile.is_natural_question`，消除重复。`results.py:424` 同步。

服务端构造 analyzer/calculator 处（`eval_runner.py`、`task_service.recalculate_task_scores`、`database.backfill_citations`）传入从 DB 加载的档案。

**本地 runner**：`task_config.json` 增补 `brand_profile` 块（建批次时由 server 写入），`local_webchat_runner.py` 读取后传给 `ResponseAnalyzer`，保证本地分析口径与服务端一致。

> 字段名 `is_ucloud`（citations/all_cited_urls 里的布尔标记）保留不动，语义泛化为"是否被测品牌官方引用"。analyzer 设置该值时改用 official_domains 判定。

### B. 问题管理 AI 通用生成（需求1）

新增后端 `POST /api/questions/generate`，body：
```json
{ "brand_name", "company_name", "website", "industry", "model_key": "deepseek", "scenario_count": null }
```

流程：
1. 用 `ModelClient(model_key).chat()` 调用（**不开联网搜索**，纯生成）。model_key 默认 deepseek；若该模型未配 API Key 返回 400 提示先配置。
2. Prompt 要求：按行业特性生成 N 个场景（N 默认由 AI 在 8~12 间决定，可被 scenario_count 覆盖），**每个场景恰好 5 题**，覆盖品牌词/品类词/对比词/场景词四种 question_type，含品牌词/公司名/产品型号，简洁模拟真实搜索意图；输出严格 JSON 数组：
   ```json
   [{ "category": "...", "question_type": "...", "question": "...", "tags": [...] }, ...]
   ```
3. 解析 JSON → 校验每场景恰好 5 题（不足/超出场景记录告警，不阻断）→ 分配 id（`gen_001`…按场景分组）→ `db.deactivate_all_questions()` 把旧题置 `is_active=0` → 逐条 `db.upsert_question()` 插入新题。
4. 同时把品牌档案写入 `app_settings`（brand_profile + brand_keywords + brand_url_patterns 等），保证分析与题集品牌一致。
5. 返回 `{ generated, scenarios, questions }`。

新增 `db.deactivate_all_questions()`：`UPDATE questions SET is_active=0`。

前端 `Questions.vue` 增"AI 生成问题"按钮 + 对话框（品牌/公司/网站/行业/模型下拉/场景数），生成中 loading，完成后刷新列表并提示场景数与题数。生成时若首页已设品牌档案，自动带入默认值。

### C. 首页改造（需求2）

新增 `Home.vue` 作为首页；路由 `/` 改为指向 `Home`（不再重定向 dashboard）。

- 展示当前品牌档案（品牌/公司/网站/行业）+ 编辑表单 +「保存品牌档案」+「一键生成问题」按钮
- **onMounted 检测未设置品牌档案（brand_name 为空）时，自动弹出 `el-dialog`，`:close-on-click-modal="false"` `:close-on-press-escape="false"` `:show-close="false"`，提示"请先填写测试品牌和网站（必选）"**，品牌名+网站为必填，填写后方可关闭继续
- 保存 → `PUT /api/settings/brand-profile`（写 app_settings 并自动 derive 派生项）→ 可选立即触发生成问题
- 侧边栏增加"首页"菜单项（`/`）；Dashboard 仍在侧边栏可进入看结果

后端新增 `GET/PUT /api/settings/brand-profile`：GET 返回当前档案（无则返回空 + 默认 UCloud 档案作参考）；PUT 接收输入项，调用 `derive_from_input` 生成派生项，存 `brand_profile` / `brand_keywords` / `brand_url_patterns` / `brand_reference_keywords` / `brand_domains` 到 app_settings。

### D. 文案与命名通用化

- `app.py` FastAPI title/description、`App.vue` logo "UCloud GEO" → "GEO 评估"
- Dashboard/Settings 文案中"UCloud"措辞改为"被测品牌"或在文案说明
- README 增加通用版使用说明（设品牌 → 生成题集 → 评测）
- `ucloud-geo.service` / `deploy.sh` 等部署文件保持可用（systemd 服务名次要，本次不改名）

## 实施顺序（分步可验证）

1. `core/brand_profile.py` + analyzer/metrics/database/eval_runner/results 通用化 + 跑现有自检脚本确保不回归
2. 后端 `brand-profile` & `questions/generate` 接口 + `db.deactivate_all_questions`
3. 前端 `Home.vue`（首页必选提示）+ `Questions.vue` 生成入口 + 路由/侧边栏调整
4. 本地 runner `brand_profile` 透传 + task_config 写入
5. 文案/README 通用化，提交推送

## 风险与回退

- analyzer 通用化改动面大，依赖现有 5 个自检脚本（`test_db_migration` / `test_tasks_service` / `test_tasks_api` / `test_runner_v2_config` / `test_scheduler_selfcheck`）防止回归；这些脚本用 mock，不真打平台。
- 旧 UCloud 数据库仍可工作：无 brand_profile 时 fallback 到 `default_brand_profile()`（UCloud），向后兼容。
- 生成题集"替换"是软删除（is_active=0），旧题仍在库中可恢复。
