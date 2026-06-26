# GEO 评估指标与引用源计算说明

> 本文档说明 general-geo-eval 系统四大核心指标（提及率 / 引用率 / TOP3 推荐率 / 情感值）的精确计算口径，以及引用源数据的来源、判定逻辑与后续价值。
>
> **代码来源**：`core/metrics.py`（评分引擎）、`core/analyzer.py`（单条响应分析）、`core/brand_profile.py`（品牌档案与自然问题判定）、`backend/database.py`（落库与读侧重算）、`core/config.py`（权重与关键词配置）。

---

## 一、四大指标总览

| 指标 | 字段 | 分母 | 分子 | 权重 |
|---|---|---|---|---|
| 提及率 | `coverage_rate` | **自然问题**数 | UCloud 被提及的自然问题数 | 0.45 |
| 引用率 | `citation_rate` | 全部有效问题数 | 含「有效引用」的有效问题数 | 0.25 |
| TOP3 推荐率 | `recommendation_rate` | **自然问题**数 | UCloud 排名 ≤ 3 的自然问题数 | 0.20 |
| 情感值 | `sentiment_score` | 全部有效问题数 | 所有有效响应情感值平均 | 0.10 |

**综合 GEO 分数**（0–100）：

```
geo_score = round( (coverage×0.45 + citation×0.25 + recommendation×0.20 + sentiment×0.10) × 100, 2 )
```

权重定义在 `core/metrics.py:96-102` 的 `GEO_WEIGHTS`，`backend/database.py:get_scores` 内联硬编码相同权重（`database.py:665-670`）。

### 一个关键分母差异（务必记住）

- **提及率 / TOP3 推荐率**：分母**只算自然问题**（排除引导型、题干含品牌词的送分题）。
- **引用率 / 情感值**：分母是**全部有效问题**（含引导型）。

原因：引导型题（如「UCloud 云主机怎么样」）题干本身就把 UCloud 摆出来了，算它「被提及/被推荐」是送分，会虚高指标。所以提及与推荐只看自然问题；引用和情感与品牌是否被「点名」无关（模型引用了 UCloud 官网、或对 UCloud 的描述情感正面，即使题干没点名也算），故用全部有效问题。

### 「自然问题」的判定（`is_natural_question`，`core/brand_profile.py:226-237`）

一个问题算「自然问题」当且仅当：
1. `category != "引导型"`，**且**
2. 题干文本**不含**任何品牌主词/别名（UCloud 默认档案里是 `primary + aliases`，即 `UCloud` / `优刻得` 等）。

匹配用 `build_keyword_pattern` 编译成大小写不敏感的正则交替。换句话说：题干里只要出现「UCloud」「优刻得」，就判为引导型/非自然问题（送分题），不计入提及率/TOP3 分母。

> **历史坑**：`core/metrics.py` 曾有 fallback——无自然问题时回退到「全部有效问题」当分母，导致引导型批次分数虚高（联调 kimi 曾虚高到 75，真实 18.29）。commit `ef221ed` 修为「无自然问题 → 提及率/TOP3 置 0」。结论：**测真实 GEO 分必须用含自然问题的题集（q011+）**；引导型批次 GEO 低是正常的，不是 bug。

---

## 二、各指标详细计算

### 1. 提及率（coverage_rate）——「UCloud 在自然提问下被提到的概率」

```
提及率 = (UCloud 被提及的自然问题数) / (自然问题总数)
```

- **「被提及」判定**（`analyzer.py:_detect_brand_mentions`, 163-200）：对响应正文用品牌关键词字典（`BRAND_KEYWORDS`：`primary`/`products`/`flagship`/`aliases`）做正则匹配。ASCII 关键词（如 `UCloud`）大小写不敏感；非 ASCII（如 `优刻得`）大小写敏感。命中 ≥1 次 → `ucloud_mentioned=True`。
- **分母**：`natural_results`，无自然问题时直接 0（`metrics.py:148-152`）。
- **衍生量**：`ucloud_mention_count`（提及次数）、`ucloud_first_position`（首次出现字符位置）、`position_weight`（位置权重，见下）。

> 另有 `mention_rate`（提及频次）字段，按 `ucloud_mention_count × position_weight` 加权平均，但**权重为 0，不参与 GEO 得分**，仅作诊断参考。

### 2. 引用率（citation_rate）——「回答里有没有给 UCloud 站住脚的来源」

> **回答你之前的问题：引用率不一定要「引用链接」才算。**
>
> 引用率分子 = 含「有效引用」的问题数。有效引用有 **3 条路径**，只有路径③需要链接，路径①②不需要：

| 路径 | 是否需要链接 | 判定 |
|---|---|---|
| ① UCloud 官方 URL | 需要 URL | 响应里出现 UCloud 官方域名（`ucloud.cn`/`ucloud.com`/`ucloudstack.com`）的链接 |
| ② 参考措辞（reference） | **不需要链接** | 响应里出现「据UCloud」「UCloud官网」「UCloud数据显示」「根据UCloud」「UCloud报告」「UCloud官方」等参考措辞 |
| ③ 第三方来源 URL | 需要 URL | 回答**提及了 UCloud** 且引用了第三方域名（知乎/CSDN/雪球/百度百科…26 个域名）的链接，且该链接前后 ±180 字符上下文含品牌词 |

任何一条命中即算该问题有有效引用。

**计算**（`metrics.py:_has_effective_citation`, 22-46 + `:171-172`）：

```
引用率 = (含有效引用的有效问题数) / (全部有效问题数)
```

判定顺序：
1. 扫 `citations` 列表：任一条 `is_ucloud=True` → 有效（覆盖路径①②，以及官方子域 URL）。
2. 扫 `all_cited_urls` 列表：任一条 `is_ucloud=True` → 有效（补漏：`docs.ucloud.cn`/`astraflow.ucloud.cn` 等子域只进 `all_cited_urls`，因为 `url_patterns` 只匹配三个根域）。
3. 若 `ucloud_mentioned` 为真，扫 `citations` 里 `citation_type=="url"` 且 `is_ucloud=False` 的第三方 URL，域名命中 `THIRD_PARTY_CITATION_DOMAINS` → 有效（路径③）。

**为什么 ② 不需要链接**：参考措辞（「据UCloud…」）本身就是模型在「引用」UCloud 的信息来源，语义上等同于引用，只是用文字而非 URL 表达。所以只要正文出现这些措辞就算有效引用。

**第三方来源为什么要求「提及 UCloud + 上下文相关」**：纯出现一个知乎链接不算引用 UCloud——必须是「在讨论 UCloud 的语境下」引用的第三方来源才算。`is_ucloud_related_citation`（`database.py:65-93`）用 ±180 字符窗口检查上下文是否含品牌词（`primary+products+aliases`）。API 搜索结果类引用（`position < 0`，见下）例外，直接算相关。

#### THIRD_PARTY_CITATION_DOMAINS 完整清单（`analyzer.py:15-25`，`database.py:52-62` 同步）

```
技术社区:    zhihu.com, csdn.net, juejin.cn, github.com, bilibili.com,
             segmentfault.com, oschina.net, cnblogs.com, infoq.cn, 51cto.com,
             mp.weixin.qq.com, jianshu.com, oscimg.com, stackoverflow.com,
             gitee.com, readthedocs.io
资讯/社交:   weibo.com, 36kr.com, toutiao.com, baijiahao.baidu.com, sohu.com, 163.com
企业信息:    tianyancha.com, qcc.com
```

#### UCloud 官方 URL 模式（`config.py:163-167`）

```
https?://(www\.)?ucloud\.cn
https?://(www\.)?ucloud\.com
https?://(www\.)?ucloudstack\.com
```

对应渠道映射：`ucloud.cn → "UCloud官网"`、`ucloud.com → "UCloud国际站"`、`ucloudstack.com → "UCloudStack"`。

#### 参考措辞关键词（`config.py:168-173`）

```
据UCloud, UCloud官网, UCloud数据显示, 根据UCloud, UCloud报告, UCloud官方, UCloud白皮书
（注：源码里 "UCloud数据显示" 重复了一次）
```

### 3. TOP3 推荐率（recommendation_rate）——「UCloud 在品牌推荐里进没进前三」

```
TOP3 推荐率 = (UCloud 排名 ≤ 3 的自然问题数) / (自然问题总数)
```

- **排名 `ucloud_rank` 怎么算**（`analyzer.py:_calculate_rank`, 471-497）：若 UCloud 未被提及 → `ucloud_rank = None`。否则收集 UCloud 首次出现位置 + 各竞品首次出现位置，按位置升序排序，UCloud 的 1-indexed 名次就是 `ucloud_rank`。`ucloud_rank=1` 表示 UCloud 出现在所有竞品之前。
- **TOP3**：`ucloud_rank is not None and ucloud_rank <= 3`（`metrics.py:178-181`）。
- **衍生**：
  - `strong_recommend_rate`：`ucloud_recommendation_strength == "strong"` 的自然问题占比。
  - `moderate_recommend_rate`：`== "moderate"` 的占比。

#### 推荐强度判定（`analyzer.py:_detect_recommendations`, 302-360）

UCloud 被提及时，取首次提及前后 `pos-150 ~ pos+300` 字符的扩展上下文，按优先级匹配关键词（先命中先返回）：
1. `strong_keywords`（「强烈推荐」「首选」「最佳选择」「最推荐」「首推」「不二之选」…）→ `strong`
2. `moderate_keywords`（「推荐」「建议」「可以考虑」「值得选择」…）→ `moderate`
3. `comparison_win_keywords`（「优于」「比…好」「更具优势」「性价比更高」…）→ 仅当上下文同时出现品牌 `display_name` 才算 `comparison_win`

`ucloud_recommended = strength ∈ {strong, moderate, comparison_win}`。

### 4. 情感值（sentiment_score）——「对 UCloud 的描述是正面还是负面」

```
情感值 = 所有有效响应 sentiment_score 的平均
```

- **主算法：SnowNLP**（`analyzer.py:_analyze_sentiment`, 362-410）——基于朴素贝叶斯的中文情感库，不是手写关键词词典。
  - 取 UCloud 前 3 次提及，各取 `pos-100 ~ pos+200` 字符上下文。
  - 每段用 `SnowNLP(ctx).sentiments` 打分（0–1），取平均，四舍五入 4 位。
  - UCloud 未被提及 → `sentiment_score=0.5`（中性）。
- **阈值**（`config.py:135-141`）：`>0.6 → 正面`、`<0.4 → 负面`、之间中性。
- **兜底**：若 `snownlp` 导入失败，回退 `_rule_based_sentiment`（`analyzer.py:412-443`）——简单关键词词典，命中正面词（好/优秀/稳定/性价比高…）+0.05、负面词（差/不稳定/贵/故障/不推荐…）-0.05，clamp 到 [0,1]。

> 情感值分母是全部有效问题（含引导型），因为即使题干没点名 UCloud，模型若在回答里评价了 UCloud，该情感也该计入。

---

## 三、引用源（citation source）数据：从哪来、怎么算

### 数据来源链路

```
模型响应正文 + API search_results 元数据
        │
        ▼  core/analyzer.py: ResponseAnalyzer.analyze()
   ┌────┴─────────────────────────────┐
   ▼                                  ▼
_detect_citations (240-300)    _detect_all_urls (499-533)
   │ 严格列表「算品牌引用」              │ 宽松列表「全量 URL」
   │ 4 类条目入 citations              │ 所有 URL 入 all_cited_urls
   └────────────┬─────────────────────┘
                ▼
        _incorporate_search_results (535-619)
        合并 API search_results URL（position 取负值）
                ▼
   save_analysis_result (database.py:524-551)
   citations / all_cited_urls 序列化成 JSON 存 analysis_results 表
```

### 两个列表的区别

| | `citations`（严格） | `all_cited_urls`（宽松） |
|---|---|---|
| 内容 | 算「品牌引用」的条目 | 响应里出现的**所有** URL |
| 条目类型 | URL + 参考措辞(reference) | 只有 URL |
| 官方 URL | 命中 `url_patterns` 正则 → `is_ucloud=True` | `is_official_url` 子串匹配（含子域） |
| 第三方 URL | 仅当「提及 UCloud + ±180 字上下文含品牌词」才入，`is_ucloud=False` | 全部入，`is_ucloud` 按是否官方判 |
| API 搜索结果 | 全部入（无论是否提及，因为「搜索结果本身就是模型来源」），`is_ucloud` 按官方判定 | 全部入 |
| 用途 | 引用率分子、来源渠道聚类 | 补漏官方子域 URL、全量来源分析 |

### `citations` 的 4 类条目（`analyzer.py:240-300`）

1. **正文 URL 命中 `url_patterns`**（ucloud.cn/com/stack 根域）→ `is_ucloud=True`
2. **参考措辞**（「据UCloud」等子串匹配）→ `citation_type="reference"`, `is_ucloud=True`
3. **第三方 URL + 提及 UCloud + 上下文相关** → `is_ucloud=False`（域名须在 `THIRD_PARTY_CITATION_DOMAINS`）
4. **API `search_results` 的 URL** → 全部入，`is_ucloud` 按 `is_official_url` 判，**不查上下文**

### URL 提取正则（`analyzer.py:245, 504`）

```python
url_pattern = re.compile(r'https?://[^\s<>"\')\]，。、；：！？】}]+')
# 末尾标点再 rstrip(".,;:!?)]>》）】")
```

### API 搜索结果的 position 编码

来自模型 API `search_results` 的 URL，`position = -(i+1)*10`（负值）。负 position 在读侧有特殊待遇：`is_ucloud_related_citation` 见到 `position < 0` 直接判相关（`database.py:78-84`），不查上下文——因为 API 搜索结果本就是模型回答的来源。

### 读取侧重算（dashboard 实时）

`backend/database.py:get_effective_citations`（96-151）从 `analysis_results` 表读出 `citations`/`all_cited_urls` JSON，**重新跑一遍有效引用判定**（用当前品牌档案，不重新分析原文）：
- `citations` 里非 URL 或官方或相关 → 入 `effective`
- `all_cited_urls` 里：API 搜索结果（position<0）→ 入；正文 URL → 仅当「提及 UCloud + 第三方域名 + 上下文相关」才入

这样**历史 run 也能跟着最新引用规则更新**，无需重跑分析。

---

## 四、读侧 vs 计算侧的两套口径（重要）

系统有**两处**计算指标，口径基本一致但实现不同：

| | `core/metrics.py`（计算侧） | `backend/database.py:get_scores`（读侧） |
|---|---|---|
| 谁用 | runner / CLI 跑完即算 | dashboard 实时展示 |
| 输入 | 内存里的 `AnalysisResult` 列表 | 从 `analysis_results` 表读 JSON 重算 |
| 引用判定 | `_has_effective_citation`：扫 `citations`+`all_cited_urls` 找 `is_ucloud`，或第三方 URL 域名命中 | `has_effective_citation`→`get_effective_citations`：**重新跑** `is_ucloud_related_citation` 上下文检查 |
| 自然问题 | 跑时即分 | 从 `questions` 表读 category+题干重判 |
| 历史兼容 | 跑完即固化 | **动态重算**，规则更新后历史 run 自动跟进 |
| 额外算 | strong/moderate 推荐率、mention_rate、avg_position_weight | 不重算这些（用 geo_scores 表里存的） |

**任务级 `get_task_scores`（`database.py:1293-1306`）不同**：直接读 `geo_scores` 表，**不重算、不 backfill**。所以任务级分数是「保存时算的那个值」，引用规则改了不会自动更新，除非重跑任务或删 `geo_scores` 重存（`save_task_geo_scores` / `delete_task_geo_scores`）。

---

## 五、引用源数据对后续的价值

引用源（`citations` + `all_cited_urls`，落库在 `analysis_results` 表）不只是算引用率的中间产物，还有几层后续价值：

### 1. 来源渠道聚类（source_channel）
每条 URL 在分析时解析出 `source_channel`（如「UCloud官网」「知乎」「CSDN」「雪球」「百度百科」）。可做：
- **哪些来源最常被模型引用**：判断 UCloud 的「信息辐射面」——模型主要从官网、还是从第三方评测/百科拿信息。
- **官方 vs 第三方占比**：官方引用多说明 UCloud 官方内容被模型信任；第三方多说明口碑/测评传播广但官方 SEO 可能不足。

### 2. 引用质量分析
- **官方域名细分**：`ucloud.cn`（官网）/ `ucloud.com`（国际站）/ `ucloudstack.com`（私有云）/ 子域（docs/astraflow）各被引多少 → 知道哪个站点对 GEO 贡献大，重点优化哪个。
- **子域名补漏价值**：`all_cited_urls` 专门兜 `docs.ucloud.cn` 等子域（`url_patterns` 只匹配根域会漏），这块数据只在这能捞到。

### 3. 第三方口碑溯源
路径③（提及 UCloud + 第三方来源）的引用，能定位「模型在讨论 UCloud 时参考了哪些第三方内容」——知乎高赞回答、雪球分析、百度百科词条等。这些是**可优化的外部内容资产**：
- 哪些第三方页面被反复引用 → 该页面是 UCloud 在 AI 回答里的「信息源头」，内容质量直接影响模型对 UCloud 的描述。
- 缺失的高价值平台（如某评测站从未被引）→ 可定向做内容布局。

### 4. 引用与提及/推荐的相关性
跨指标交叉：
- 「被提及但无引用」的问题 → 模型提了 UCloud 但没给来源，可信度低，可能凭训练记忆瞎说 → 这些问题的回答质量需关注。
- 「有官方引用」 vs 「只有第三方引用」 → 官方引用的响应情感/推荐强度是否更高？验证「官方内容喂进去 → 模型更倾向推荐」的假设。

### 5. 竞品对比的上下文
`competitor_mentions`（同表存储）+ 引用源 → UCloud 和竞品在哪些来源上被一起讨论、谁排前面。配合 `ucloud_rank` 可定位「UCloud 排在竞品后面时，引用源是什么类型」——是官方内容不够、还是第三方评测偏向竞品。

### 6. 历史趋势与规则迭代
因为读侧 `get_scores` 动态重算，引用源原始数据（`citations`/`all_cited_urls` JSON）是**可回溯的金矿**：
- 调整 `THIRD_PARTY_CITATION_DOMAINS` 或参考措辞词表后，历史 run 的引用率自动重算 → 能对比「口径变化前后」的差异，量化规则调整影响。
- 长期累积的引用源数据可做时间序列：某第三方站点被引频率是上升还是下降，反映 UCloud 在该平台的内容热度变化。

---

## 六、配置速查（`core/config.py` / `config.py`）

| 配置项 | 位置 | 内容 |
|---|---|---|
| `GEO_WEIGHTS` | metrics.py:96 | coverage 0.45 / citation 0.25 / recommendation 0.20 / sentiment 0.10 |
| `citation.url_patterns` | config.py:163 | ucloud.cn / ucloud.com / ucloudstack.com 三个根域正则 |
| `citation.reference_keywords` | config.py:168 | 据UCloud 等 7 条参考措辞 |
| `THIRD_PARTY_CITATION_DOMAINS` | analyzer.py:15 | 26 个第三方域名 |
| `position_weight` 桶 | config.py:176 | 前10%→1.5 / 前20%→1.2 / 前40%→1.0 / 之后→0.8 |
| `sentiment` 阈值 | config.py:135 | >0.6 正面 / <0.4 负面 |
| `recommendation` 关键词 | config.py | strong / moderate / comparison_win 三组 |

---

## 七、常见误区

1. **「引用率要链接才算」** —— 错。参考措辞（据UCloud/UCloud官网…）不需要链接，算路径②有效引用。
2. **「引导型批次 GEO 低是 bug」** —— 错。引导型题不计入提及/TOP3 分母，分数天然低；测真实分用自然问题题集。
3. **「任务级分数会随规则更新自动变」** —— 错。`get_task_scores` 读 `geo_scores` 表不重算；只有 run 级 `get_scores` 动态重算。改了规则要重跑任务或删 task geo_scores 重存。
4. **「第三方链接都算引用」** —— 错。必须「提及 UCloud + 上下文 ±180 字含品牌词」才算（路径③），纯出现一个知乎链接不算引用 UCloud。
5. **「子域名 URL 会被漏」** —— `url_patterns` 只匹配根域，`docs.ucloud.cn` 等子域靠 `all_cited_urls` + `is_official_url` 子串匹配补漏，引用率判定会扫 `all_cited_urls`。
