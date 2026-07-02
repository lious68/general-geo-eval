<template>
  <div class="metric-guide">
    <h2 class="page-title"><el-icon><Reading /></el-icon> GEO 评估指标说明</h2>
    <p class="page-subtitle">本页说明 GEO 评估五大指标的计算口径、公式与示例，可随时查阅。所有口径与后端
      <code>core/metrics.py</code> / <code>core/analyzer.py</code> 保持一致。</p>

    <!-- ===== GEO 综合得分（置顶突出） ===== -->
    <el-card shadow="never" class="geo-score-card">
      <div class="geo-score-header">
        <el-icon class="geo-score-icon"><Trophy /></el-icon>
        <span class="geo-score-title">GEO 综合得分</span>
        <el-tag type="warning" effect="dark" size="small">0 – 100 分</el-tag>
      </div>
      <div class="formula-box formula-box-primary">
        <span class="formula-label">公式</span>
        <code class="formula-expr">
          GEO = ( 提及率 × 45% + 引用率 × 25% + TOP3 推荐率 × 20% + 情感值 × 10% ) × 100
        </code>
      </div>
      <div class="geo-score-desc">
        四个核心指标各自归一化到 <strong>0–1</strong>，按权重加权求和后再 × 100 转为 <strong>0–100 分制</strong>。
        另有「提及频次」指标权重为 <strong>0%</strong>，仅作展示，<strong>不参与</strong> GEO 综合得分。
      </div>
    </el-card>

    <!-- ===== 总览速查表 ===== -->
    <el-card shadow="never" class="summary-card">
      <div class="card-title"><el-icon><Grid /></el-icon> 指标总览</div>
      <el-table :data="summaryRows" border stripe size="default" style="width:100%">
        <el-table-column prop="name" label="指标" width="150">
          <template #default="{ row }">
            <strong>{{ row.name }}</strong>
            <el-tag v-if="row.weight" size="small" type="warning" effect="plain" style="margin-left:6px">权重 {{ row.weight }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="denominator" label="分母" min-width="180" />
        <el-table-column prop="numerator" label="分子" min-width="200" />
        <el-table-column prop="range" label="范围" width="110" />
      </el-table>
    </el-card>

    <!-- ===== 自然问题定义（贯穿提及率/TOP3） ===== -->
    <el-card shadow="never" class="concept-card">
      <div class="card-title"><el-icon><InfoFilled /></el-icon> 关键概念：自然问题</div>
      <div class="concept-body">
        「自然问题」= <strong>非引导型</strong> 且 <strong>题干不含被测品牌词</strong>（如 UCloud / 优刻得）的问题。
        <ul>
          <li>题干自带品牌词的题（如「UCloud 海外有哪些节点？」）是「送分题」，必提及、必进 Top3，统计进去会<em>虚高</em>提及率与推荐率，故排除出分母。</li>
          <li>「引导型」问题（Q1–Q10）同样排除。</li>
          <li>引用率、情感值的分母是<strong>全部有效问题</strong>（含引导型），不受此过滤影响。</li>
        </ul>
        该过滤由 <code>brand_profile.is_natural_question()</code> 统一判定，提及率 / TOP3 推荐率共用同一分母口径。
      </div>
    </el-card>

    <!-- ===== 四大指标详解 ===== -->
    <el-row :gutter="16">
      <el-col :span="12">
        <!-- 提及率 -->
        <el-card shadow="never" class="metric-detail metric-coverage">
          <div class="metric-detail-header">
            <el-icon class="md-icon"><Aim /></el-icon>
            <span class="md-title">提及率</span>
            <el-tag type="warning" effect="dark" size="small">权重 45%</el-tag>
          </div>
          <div class="formula-box">
            <span class="formula-label">公式</span>
            <code class="formula-expr">提及率 = UCloud 被提及的自然有效响应数 / 自然有效响应总数</code>
          </div>
          <div class="md-section">
            <div class="md-section-title">核心解释</div>
            <ul>
              <li><strong>分母</strong>：仅「自然问题」的有效响应（排除引导型与题干含品牌词的送分题）。</li>
              <li><strong>分子</strong>：这些自然问题响应中，正文出现 UCloud 品牌词（含主词/产品词/别名）的数量。</li>
              <li>无自然问题（如全引导型批次）→ <strong>记 0</strong>，不回退到全部有效问题（否则送分题虚高）。</li>
              <li>未提及 UCloud 的响应情感固定为 0.5，不影响提及判定。</li>
            </ul>
          </div>
          <div class="md-example">
            <span class="example-tag">示例</span>
            48 条自然有效响应中有 20 条提及 UCloud → 20 / 48 = <strong>41.7%</strong>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <!-- TOP3 推荐率 -->
        <el-card shadow="never" class="metric-detail metric-recommendation">
          <div class="metric-detail-header">
            <el-icon class="md-icon"><Medal /></el-icon>
            <span class="md-title">TOP3 推荐率</span>
            <el-tag type="warning" effect="dark" size="small">权重 20%</el-tag>
          </div>
          <div class="formula-box">
            <span class="formula-label">公式</span>
            <code class="formula-expr">TOP3 推荐率 = UCloud 排名 ≤ 3 的自然回答数 / 自然有效回答总数</code>
          </div>
          <div class="md-section">
            <div class="md-section-title">核心解释</div>
            <ul>
              <li><strong>分母</strong>：自然问题（与提及率同口径）。</li>
              <li><strong>排名怎么算</strong>：收集回答中所有品牌（UCloud + 竞品）的「首次出现位置」，按位置升序排序，UCloud 的位次即其排名。越早出现排名越靠前。</li>
              <li><strong>分子</strong>：自然问题中 UCloud 排名 ≤ 3 的回答数。</li>
              <li>推荐强度细分（仅展示，不单独计入 TOP3）：
                <el-tag size="small" type="success">强推荐</el-tag>命中「强烈推荐/首选/最佳选择…」；
                <el-tag size="small" type="info">中推荐</el-tag>命中「推荐/建议/可以考虑…」；
                <el-tag size="small" type="warning">对比胜出</el-tag>命中「优于/比…好/更具优势…」。
              </li>
              <li>无自然问题 → <strong>记 0</strong>，不回退。</li>
            </ul>
          </div>
          <div class="md-example">
            <span class="example-tag">示例</span>
            48 条自然回答中有 12 条进入 Top3 → 12 / 48 = <strong>25.0%</strong>
          </div>
        </el-card>
      </el-col>

      <el-col :span="24">
        <!-- 引用率（含三路径表） -->
        <el-card shadow="never" class="metric-detail metric-citation">
          <div class="metric-detail-header">
            <el-icon class="md-icon"><Link /></el-icon>
            <span class="md-title">引用率</span>
            <el-tag type="warning" effect="dark" size="small">权重 25%</el-tag>
          </div>
          <div class="formula-box">
            <span class="formula-label">公式</span>
            <code class="formula-expr">引用率 = 含「有效引用」的有效响应数 / 全部有效响应数</code>
          </div>
          <div class="md-section">
            <div class="md-section-title">核心解释</div>
            <ul>
              <li><strong>分母</strong>：全部有效问题（不限于自然问题，引导型也算）。</li>
              <li><strong>分子</strong>：命中「有效引用」的响应数。「有效引用」有 <strong>三条判定路径</strong>，命中任一即计 1。</li>
              <li>URL 不是硬性前提——路径 ② 纯文字归属也算（详见下表）。</li>
            </ul>
          </div>

          <div class="md-section">
            <div class="md-section-title">有效引用 · 三条路径</div>
            <el-table :data="citationPaths" border stripe size="small" style="width:100%">
              <el-table-column prop="path" label="路径" width="180">
                <template #default="{ row }">
                  <strong>{{ row.path }}</strong>
                </template>
              </el-table-column>
              <el-table-column prop="needUrl" label="要 URL?" width="90" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.needUrl ? 'danger' : 'success'" size="small" effect="plain">
                    {{ row.needUrl ? '要' : '不要' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="desc" label="说明" min-width="320" />
              <el-table-column prop="example" label="举例" min-width="220" />
            </el-table>
            <div class="path-note">
              <el-icon><WarningFilled /></el-icon>
              实操中绝大多数有效引用靠 URL（路径 ① 或 ③）；纯文字路径 ② 是固定短语精确匹配（如须原样写出「据UCloud官网」），泛泛说「UCloud 方面表示」<strong>不算</strong>。
              这也是千问/豆包抓不到引用 URL 且未命中参考关键词时，引用率被压成 0 的原因。
            </div>
          </div>

          <div class="md-example">
            <span class="example-tag">示例</span>
            36 条全部有效响应中有 4 条含有效来源引用 → 4 / 36 = <strong>11.1%</strong>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <!-- 情感值 -->
        <el-card shadow="never" class="metric-detail metric-sentiment">
          <div class="metric-detail-header">
            <el-icon class="md-icon"><Sunny /></el-icon>
            <span class="md-title">情感值</span>
            <el-tag type="warning" effect="dark" size="small">权重 10%</el-tag>
          </div>
          <div class="formula-box">
            <span class="formula-label">公式</span>
            <code class="formula-expr">情感值 = Σ(全部有效响应的情感分数) / 全部有效响应数</code>
          </div>
          <div class="md-section">
            <div class="md-section-title">核心解释</div>
            <ul>
              <li><strong>分母</strong>：全部有效问题（含引导型，与引用率同口径）。</li>
              <li><strong>怎么算</strong>：用 SnowNLP 对 UCloud 提及前后 ±100~200 字上下文打情感分；取前 3 个提及上下文的平均。</li>
              <li>未提及 UCloud 的响应情感固定 <strong>0.5</strong>（中性），正常参与平均。</li>
              <li>SnowNLP 不可用时回退到规则法：上下文命中正/负情感词各 ±0.05。</li>
              <li>范围 <strong>0–1</strong>：&gt; 0.6 正面，0.4–0.6 中性，&lt; 0.4 负面。</li>
            </ul>
          </div>
          <div class="md-example">
            <span class="example-tag">示例</span>
            20 条提及响应的平均情感为 0.72 → 情感值 = <strong>0.72</strong>（偏正面）
          </div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <!-- 提及频次（不参与GEO） -->
        <el-card shadow="never" class="metric-detail metric-mention">
          <div class="metric-detail-header">
            <el-icon class="md-icon"><Histogram /></el-icon>
            <span class="md-title">提及频次（原提及率）</span>
            <el-tag type="info" effect="plain" size="small">权重 0% · 不计入 GEO</el-tag>
          </div>
          <div class="formula-box">
            <span class="formula-label">公式</span>
            <code class="formula-expr">提及频次 = Σ(提及次数 × 位置权重) / 全部有效响应数</code>
          </div>
          <div class="md-section">
            <div class="md-section-title">核心解释</div>
            <ul>
              <li>反映「平均每条响应中 UCloud 被提及的加权次数」，含位置权重（越靠前权重越高）。</li>
              <li>位置权重：前 10% → 1.5，前 20% → 1.2，前 40% → 1.0，40% 之后 → 0.8。</li>
              <li><strong>权重 0%，仅作辅助展示</strong>，不进入 GEO 综合得分。</li>
            </ul>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ===== 口径来源说明 ===== -->
    <el-card shadow="never" class="footer-card">
      <div class="card-title"><el-icon><Document /></el-icon> 口径来源</div>
      <div class="footer-body">
        以上公式与判定逻辑取自：<code>core/metrics.py</code>（指标计算与 GEO 权重）、
        <code>core/analyzer.py</code>（提及/引用/推荐/情感/排名检测，<code>has_effective_citation()</code> 为引用率唯一真源）、
        <code>core/brand_profile.py</code>（自然问题过滤、品牌档案）、<code>core/config.py</code>（推荐关键词、情感阈值、位置权重）。
        前端指标卡片的悬浮提示（仪表盘）与本页内容同源。
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'

// 指标总览速查表
const summaryRows = ref([
  {
    name: '提及率', weight: '45%',
    denominator: '自然有效响应数（排除引导型/送分题）',
    numerator: '其中正文提及 UCloud 的响应数',
    range: '0–100%',
  },
  {
    name: '引用率', weight: '25%',
    denominator: '全部有效响应数（含引导型）',
    numerator: '命中有效引用（官方链接/参考关键词/第三方来源）的响应数',
    range: '0–100%',
  },
  {
    name: 'TOP3 推荐率', weight: '20%',
    denominator: '自然有效回答数（与提及率同口径）',
    numerator: 'UCloud 排名 ≤ 3 的回答数',
    range: '0–100%',
  },
  {
    name: '情感值', weight: '10%',
    denominator: '全部有效响应数（含引导型）',
    numerator: '所有有效响应的情感平均分',
    range: '0–1',
  },
  {
    name: '提及频次', weight: '0%（不计入）',
    denominator: '全部有效响应数',
    numerator: 'Σ(提及次数 × 位置权重)',
    range: '≥ 0',
  },
])

// 引用率三路径表
const citationPaths = ref([
  {
    path: '① UCloud 官方链接',
    needUrl: true,
    desc: '回答含 ucloud.cn / ucloud.com / ucloudstack.com 根域或其子域（docs.ucloud.cn 等）的 URL。子域 URL 同时扫 all_cited_urls 兜底，避免漏判。',
    example: 'https://docs.ucloud.cn/api/uhost/…',
  },
  {
    path: '② UCloud 参考引用关键词',
    needUrl: false,
    desc: '回答出现固定文字归属短语：据UCloud / UCloud官网 / UCloud数据显示 / 根据UCloud / UCloud报告 / UCloud官方 / UCloud白皮书。纯文字，无需 URL。',
    example: '“根据UCloud官网数据显示…”',
  },
  {
    path: '③ 第三方来源链接',
    needUrl: true,
    desc: '回答提及 UCloud，且含白名单第三方域名 URL（知乎/CSDN/掘金/GitHub/B站/36氪/微信公众号/头条…），且 URL 前后 ±180 字上下文在讲 UCloud。',
    example: 'https://zhuanlan.zhihu.com/…（上下文讲 UCloud）',
  },
])
</script>

<style scoped>
.metric-guide { max-width: 1200px; }
.page-title { font-size: var(--fs-page-title); margin-bottom: 6px; color: var(--color-text); display: flex; align-items: center; gap: 8px; }
.page-subtitle { font-size: 13px; color: #888; margin-bottom: 20px; line-height: 1.6; }
.page-subtitle code { background: #eef1f5; padding: 1px 5px; border-radius: 3px; font-size: 12px; }

/* 通用卡片 */
.metric-guide :deep(.el-card) { border-radius: var(--radius); margin-bottom: 16px; }
.card-title { font-size: var(--fs-section-title); font-weight: 600; color: var(--color-text); margin-bottom: 12px; display: flex; align-items: center; gap: 6px; }

/* GEO 综合得分置顶卡 */
.geo-score-card { background: linear-gradient(135deg, #fffaf0 0%, #fff5e6 100%); border: 1px solid #f5dab1; }
.geo-score-header { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; }
.geo-score-icon { font-size: 24px; color: #e6a23c; }
.geo-score-title { font-size: 18px; font-weight: 700; color: var(--color-text); }
.geo-score-desc { font-size: 13px; color: #666; line-height: 1.7; margin-top: 10px; }

/* 公式框 */
.formula-box { background: #f0f5ff; border-left: 3px solid #409eff; padding: 8px 12px; border-radius: 4px; margin: 8px 0 14px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.formula-box-primary { background: #fff8e6; border-left-color: #e6a23c; }
.formula-label { font-size: 12px; color: #909399; font-weight: 600; flex-shrink: 0; }
.formula-expr { font-family: 'Consolas', 'Monaco', monospace; font-size: 13px; color: var(--color-text); line-height: 1.6; word-break: break-all; }

/* 指标详解卡 */
.metric-detail { height: 100%; }
.metric-detail-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.md-icon { font-size: 20px; }
.md-title { font-size: 16px; font-weight: 700; color: var(--color-text); flex: 1; }
.metric-coverage .md-icon { color: #409eff; }
.metric-citation .md-icon { color: #e6a23c; }
.metric-recommendation .md-icon { color: #f56c6c; }
.metric-sentiment .md-icon { color: #f5c542; }
.metric-mention .md-icon { color: #909399; }

.md-section { margin-top: 10px; }
.md-section-title { font-size: 13px; font-weight: 600; color: var(--color-text); margin-bottom: 6px; padding-left: 8px; border-left: 3px solid #dcdfe6; }
.md-section ul { margin: 6px 0 6px 4px; padding-left: 18px; }
.md-section li { font-size: 13px; color: #555; line-height: 1.8; margin-bottom: 2px; }
.md-section li strong { color: var(--color-text); }
.md-section li em { color: #f56c6c; font-style: normal; }

.md-example { margin-top: 12px; padding: 8px 12px; background: #f5f7fa; border-radius: 4px; font-size: 13px; color: #555; line-height: 1.6; }
.example-tag { display: inline-block; background: #67c23a; color: #fff; font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 3px; margin-right: 8px; }
.md-example strong { color: #67c23a; font-size: 14px; }

/* 引用率三路径注脚 */
.path-note { margin-top: 10px; padding: 8px 12px; background: #fef0f0; border: 1px solid #fbc4c4; border-radius: 4px; font-size: 12px; color: #c45656; line-height: 1.7; display: flex; align-items: flex-start; gap: 6px; }
.path-note .el-icon { margin-top: 2px; flex-shrink: 0; }

/* 概念卡 */
.concept-card { background: #f0f7ff; border: 1px solid #d0e3ff; }
.concept-body { font-size: 13px; color: #555; line-height: 1.8; }
.concept-body ul { margin: 8px 0 8px 4px; padding-left: 18px; }
.concept-body li { margin-bottom: 4px; }
.concept-body code { background: #e6f0ff; padding: 1px 5px; border-radius: 3px; font-size: 12px; }

/* 底部来源卡 */
.footer-card { background: #fafafa; }
.footer-body { font-size: 12px; color: #888; line-height: 1.8; }
.footer-body code { background: #eef1f5; padding: 1px 5px; border-radius: 3px; font-size: 11px; }
</style>
