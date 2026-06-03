<template>
  <div class="dashboard">
    <h2 class="page-title">📊 GEO 评估仪表盘</h2>
    <div v-if="latestRun && route.query.run_id" class="run-breadcrumb">
      <span>正在查看：</span>
      <el-tag size="small">{{ latestRun.name || 'GEO评估' }}</el-tag>
      <span style="color:#999;margin-left:4px">{{ formatRunTime(latestRun.started_at) }}</span>
      <el-button size="small" link type="primary" style="margin-left:8px" @click="$router.push('/history')">← 返回历史</el-button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>正在加载评测数据...</p>
    </div>

    <!-- 无数据空状态 -->
    <div v-else-if="!hasData" class="empty-state">
      <el-empty description="暂无评测数据" :image-size="120">
        <template #description>
          <p style="color:#999;margin-bottom:8px">尚未执行过评测，或评测仍在运行中</p>
        </template>
        <el-button type="primary" @click="$router.push('/evaluation')">
          <el-icon><VideoPlay /></el-icon> 前往执行评测
        </el-button>
      </el-empty>

      <!-- 即使无数据，也展示指标说明卡片 -->
      <div class="metric-intro-section" style="margin-top:32px">
        <h3 class="section-title">GEO 评估指标说明</h3>
        <el-row :gutter="16">
          <el-col :span="6" v-for="m in metricDefinitions" :key="m.key">
            <el-card shadow="hover" class="intro-card">
              <div class="intro-card-header">
                <span class="intro-icon">{{ m.icon }}</span>
                <span class="intro-label">{{ m.label }}</span>
                <el-tooltip placement="top" :width="320" effect="light">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">{{ m.label }} - 计算公式</div>
                      <div class="formula-expr">{{ m.formula }}</div>
                      <div class="formula-desc">{{ m.description }}</div>
                      <div v-if="m.example" class="formula-example">{{ m.example }}</div>
                    </div>
                  </template>
                  <span class="formula-trigger">ⓘ</span>
                </el-tooltip>
              </div>
              <p class="intro-desc">{{ m.brief }}</p>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </div>

    <!-- ===== 有数据时的完整仪表盘 ===== -->
    <template v-else>

      <!-- 核心指标卡片 -->
      <div class="metric-cards-section">
        <h3 class="section-title">核心指标概览</h3>
        <el-row :gutter="16">
          <el-col :span="5" v-for="m in coreMetrics" :key="m.key">
            <el-card shadow="hover" class="metric-card" :class="'metric-' + m.key">
              <div class="metric-card-header">
                <span class="metric-icon">{{ m.icon }}</span>
                <span class="metric-label">{{ m.label }}</span>
                <el-tooltip placement="top" :width="340" effect="light">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">{{ m.label }} - 计算公式</div>
                      <div class="formula-expr">{{ m.formula }}</div>
                      <div class="formula-desc">{{ m.description }}</div>
                      <div v-if="m.example" class="formula-example">{{ m.example }}</div>
                      <div class="formula-weight">GEO权重: {{ m.weight }}%</div>
                    </div>
                  </template>
                  <span class="formula-trigger">ⓘ</span>
                </el-tooltip>
              </div>
              <div class="metric-value">{{ m.displayValue }}</div>
              <div class="metric-best">最佳渠道: {{ m.bestModel || '-' }}</div>
              <div class="metric-bar-wrap">
                <div class="metric-bar" :style="{ width: m.barPercent + '%' }"></div>
              </div>
            </el-card>
          </el-col>
          <!-- GEO 综合得分 -->
          <el-col :span="4">
            <el-card shadow="hover" class="metric-card metric-geo_score">
              <div class="metric-card-header">
                <span class="metric-icon">🏆</span>
                <span class="metric-label">GEO 综合得分</span>
                <el-tooltip placement="top" :width="380" effect="light">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">GEO 综合得分 - 计算公式</div>
                      <div class="formula-expr">GEO = (提及率×45% + 引用率×25% + TOP3 推荐率×20% + 情感值×10%) × 100</div>
                      <div class="formula-desc">各指标归一化到0-1后加权求和，再乘以100转换为0-100分制</div>
                      <div class="formula-weight">加权系数: 提及率45%、引用率25%、TOP3 推荐率20%、情感值10%</div>
                    </div>
                  </template>
                  <span class="formula-trigger">ⓘ</span>
                </el-tooltip>
              </div>
              <div class="metric-value geo-value">{{ geoBestScore }}</div>
              <div class="metric-best">最佳渠道: {{ geoBestModel || '-' }}</div>
              <div class="metric-bar-wrap">
                <div class="metric-bar geo-bar" :style="{ width: geoBestScore + '%' }"></div>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </div>

      <!-- 各渠道(模型)分值详情 -->
      <div class="channel-section" style="margin-top:20px">
        <h3 class="section-title">各渠道分值详情</h3>
        <el-card>
          <el-table :data="channelDetails" stripe border style="width:100%">
            <el-table-column label="渠道" width="120" fixed>
              <template #default="{ row }">
                <span class="channel-name">{{ row.model_name }}</span>
              </template>
            </el-table-column>
            <el-table-column width="120" sortable sort-by="geo_score">
              <template #header>
                <span>GEO得分</span>
                <el-tooltip placement="top" effect="light" :width="360">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">GEO 综合得分</div>
                      <div class="formula-expr">GEO = (提及率×45% + 引用率×25% + TOP3 推荐率×20% + 情感值×10%) × 100</div>
                      <div class="formula-desc">各指标归一化到0-1后加权求和，再乘100转为0-100分制</div>
                    </div>
                  </template>
                  <span class="col-formula-trigger">ⓘ</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                <strong :class="row.geo_score >= 50 ? 'score-good' : 'score-low'">{{ row.geo_score.toFixed(1) }}</strong>
              </template>
            </el-table-column>
            <el-table-column width="120">
              <template #header>
                <span>提及率</span>
                <el-tooltip placement="top" effect="light" :width="300">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">提及率 Mention Rate</div>
                      <div class="formula-expr">提及率 = UCloud 被提及的有效响应数 / 有效响应总数</div>
                      <div class="formula-desc">仅统计题干不自带 UCloud/优刻得 字眼的自然问题响应；在这些有效响应中，UCloud被提及（品牌名/产品名/别名）的响应占比</div>
                      <div class="formula-example">48条有效响应中20条提及UCloud → 20/48 = 41.7%</div>
                      <div class="formula-weight">GEO权重: 45%</div>
                    </div>
                  </template>
                  <span class="col-formula-trigger">ⓘ</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                {{ (row.coverage_rate * 100).toFixed(1) }}%
              </template>
            </el-table-column>
            <el-table-column width="120">
              <template #header>
                <span>引用率</span>
                <el-tooltip placement="top" effect="light" :width="300">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">引用率 Citation Rate</div>
                      <div class="formula-expr">引用率 = 含 UCloud 官方来源或第三方来源引用的响应数 / 有效响应总数</div>
                      <div class="formula-desc">官方来源直接计入；回答提及 UCloud 时，知乎、CSDN、掘金、GitHub、B站等第三方来源链接也计入</div>
                      <div class="formula-example">36条自然有效响应中4条含有效来源引用 → 4/36 = 11.1%</div>
                      <div class="formula-weight">GEO权重: 25%</div>
                    </div>
                  </template>
                  <span class="col-formula-trigger">ⓘ</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                {{ (row.citation_rate * 100).toFixed(1) }}%
              </template>
            </el-table-column>
            <el-table-column width="120">
              <template #header>
                <span>TOP3 推荐率</span>
                <el-tooltip placement="top" effect="light" :width="320">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">TOP3 推荐率 Top3 Recommendation Rate</div>
                      <div class="formula-expr">TOP3 推荐率 = 品牌进入 Top3 的回答次数 / 有效回答总次数</div>
                      <div class="formula-desc">统计 UCloud 在回答中进入品牌推荐列表 Top3 的比例</div>
                      <div class="formula-example">48条有效回答中有12条进入Top3 → 12/48 = 25.0%</div>
                      <div class="formula-weight">GEO权重: 20%</div>
                    </div>
                  </template>
                  <span class="col-formula-trigger">ⓘ</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                {{ (row.recommendation_rate * 100).toFixed(1) }}%
              </template>
            </el-table-column>
            <el-table-column width="120">
              <template #header>
                <span>情感值</span>
                <el-tooltip placement="top" effect="light" :width="300">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">情感值 Sentiment Score</div>
                      <div class="formula-expr">情感值 = Σ(被提及响应的情感分数) / 被提及响应数</div>
                      <div class="formula-desc">仅UCloud被提及时计算，范围0-1</div>
                      <div class="formula-example">&gt;0.6 正面，0.4~0.6 中性，&lt;0.4 负面</div>
                      <div class="formula-weight">GEO权重: 10%</div>
                    </div>
                  </template>
                  <span class="col-formula-trigger">ⓘ</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                {{ row.sentiment_score.toFixed(2) }}
              </template>
            </el-table-column>
            <el-table-column label="平均排名" width="100">
              <template #default="{ row }">
                {{ row.avg_rank ? row.avg_rank.toFixed(1) : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="明细" width="90" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" link size="small" @click="openDrilldown(row.model_key)">
                  📋 查看
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>

      <!-- 图表区 -->
      <el-row :gutter="16" style="margin-top:20px">
        <el-col :span="12">
          <el-card><div ref="radarRef" style="height:400px"></div></el-card>
        </el-col>
        <el-col :span="12">
          <el-card><div ref="barRef" style="height:400px"></div></el-card>
        </el-col>
      </el-row>
      <el-row :gutter="16" style="margin-top:16px">
        <el-col :span="12">
          <el-card><div ref="coverageRef" style="height:400px"></div></el-card>
        </el-col>
        <el-col :span="12">
          <el-card><div ref="sentimentRef" style="height:400px"></div></el-card>
        </el-col>
      </el-row>

      <!-- 引用详情（贡献GEO得分的引用） -->
      <div class="citation-section" style="margin-top:20px" v-if="hasCitationData">
        <h3 class="section-title">📎 引用详情（贡献 GEO 得分的引用）</h3>
        <el-card>
          <el-collapse v-model="activeCitationPanels">
            <el-collapse-item v-for="(data, mk) in citationDetails" :key="mk" :name="mk">
              <template #title>
                <span class="collapse-title">{{ data.model_name }}</span>
                <el-tag size="small" type="info" style="margin-left:8px">{{ data.citation_questions.length }} 条引用</el-tag>
              </template>
              <el-table :data="data.citation_questions" stripe size="small" style="width:100%">
                <el-table-column label="问题" min-width="200">
                  <template #default="{ row }">
                    <span class="question-text">{{ row.question_text || row.question_id }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="引用内容" min-width="300">
                  <template #default="{ row }">
                    <div v-for="(cit, ci) in row.citations" :key="ci" class="citation-item">
                      <el-tag v-if="cit.citation_type === 'url'" size="small" type="success" class="cit-type-tag">URL</el-tag>
                      <el-tag v-else size="small" type="warning" class="cit-type-tag">文本引用</el-tag>
                      <a v-if="cit.citation_type === 'url'" :href="cit.content" target="_blank" class="citation-url">{{ cit.content }}</a>
                      <span v-else class="citation-ref">{{ cit.content }}</span>
                      <el-tag v-if="cit.source_channel" size="small" type="info" class="cit-channel-tag">{{ cit.source_channel }}</el-tag>
                    </div>
                    <span v-if="!row.citations || !row.citations.length" style="color:#999">—</span>
                  </template>
                </el-table-column>
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </div>

      <!-- 引用来源渠道聚类统计 -->
      <div class="channel-clustering-section" style="margin-top:20px" v-if="hasChannelData">
        <h3 class="section-title">📊 引用来源渠道聚类统计</h3>
        <el-row :gutter="16">
          <el-col :span="14">
            <el-card>
              <div ref="channelChartRef" style="height:350px"></div>
            </el-card>
          </el-col>
          <el-col :span="10">
            <el-card>
              <template #header><strong>渠道 × 模型 引用矩阵</strong></template>
              <el-table :data="channelMatrixData" stripe size="small" style="width:100%">
                <el-table-column prop="channel" label="来源渠道" width="110" fixed />
                <el-table-column v-for="col in channelMatrixCols" :key="col" :label="col" width="80" align="center">
                  <template #default="{ row }">{{ row[col] || 0 }}</template>
                </el-table-column>
                <el-table-column label="合计" width="70" align="center">
                  <template #default="{ row }">
                    <strong>{{ channelMatrixCols.reduce((s, c) => s + (row[c] || 0), 0) }}</strong>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </div>

      <!-- 问题级下钻抽屉 -->
      <el-drawer v-model="drawerVisible" :title="`${drilldownModelName} — 问题明细`" size="70%" direction="rtl" :destroy-on-close="true">
        <div v-if="drilldownLoading" style="text-align:center;padding:40px">
          <el-icon class="is-loading" :size="24"><Loading /></el-icon>
          <p style="color:#999;margin-top:8px">加载中...</p>
        </div>
        <template v-else-if="drilldownData">
          <!-- 概览 -->
          <div class="drilldown-header">
            <span class="drilldown-total">共 <strong>{{ drilldownData.total_questions }}</strong> 题</span>
            <span class="drilldown-filter-info" v-if="filterMetric !== 'all'">
              · 筛选: {{ filterMetricLabel }} {{ filterCondition === 'gt0' ? '> 0' : '= 0' }}
              · 命中 <strong>{{ filteredDrilldown.length }}</strong> 题
            </span>
          </div>

          <!-- 筛选栏 -->
          <div class="drilldown-filters">
            <el-select v-model="filterMetric" placeholder="指标筛选" size="small" style="width:140px">
              <el-option label="全部指标" value="all" />
              <el-option label="提及率" value="coverage" />
              <el-option label="引用率" value="citation" />
              <el-option label="TOP3 推荐率" value="recommendation" />
              <el-option label="情感值" value="sentiment" />
            </el-select>
            <el-select v-model="filterCondition" placeholder="条件" size="small" style="width:120px;margin-left:8px" v-if="filterMetric !== 'all'">
              <el-option label="全部" value="all" />
              <el-option label="> 0（有值）" value="gt0" />
              <el-option label="= 0（无值）" value="eq0" />
            </el-select>
          </div>

          <!-- 问题列表 -->
          <el-table :data="filteredDrilldown" stripe size="small" style="width:100%"
            :default-sort="{ prop: 'question_id', order: 'ascending' }">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="expand-content">
                  <div class="expand-label">题目：</div>
                  <div class="expand-text">{{ row.question_text }}</div>
                  <div class="expand-label" style="margin-top:8px">AI 回答摘要：</div>
                  <div class="expand-text" v-if="row.response_summary">{{ row.response_summary }}</div>
                  <div class="expand-text" v-else style="color:#999">（无回答内容）</div>
                  <div v-if="row.error_message" class="expand-error">⚠️ 错误: {{ row.error_message }}</div>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="question_id" label="题号" width="90" sortable />
            <el-table-column label="品类" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="categoryTagType(row.category)">{{ row.category }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="提及率" width="80" sortable :sort-method="(a,b) => a.metrics.coverage.numerator - b.metrics.coverage.numerator">
              <template #default="{ row }">
                <span :class="row.metrics.coverage.numerator ? 'val-hit' : 'val-miss'">{{ row.metrics.coverage.value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="引用率" width="80" sortable :sort-method="(a,b) => a.metrics.citation.numerator - b.metrics.citation.numerator">
              <template #default="{ row }">
                <span :class="row.metrics.citation.numerator ? 'val-hit' : 'val-miss'">{{ row.metrics.citation.value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="TOP3 推荐率" width="120" sortable :sort-method="(a,b) => a.metrics.recommendation.numerator - b.metrics.recommendation.numerator">
              <template #default="{ row }">
                <span :class="row.metrics.recommendation.numerator ? 'val-hit' : 'val-miss'">{{ row.metrics.recommendation.value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="情感" width="80" sortable :sort-method="(a,b) => a.metrics.sentiment.score - b.metrics.sentiment.score">
              <template #default="{ row }">
                <span :class="sentimentClass(row.metrics.sentiment)">{{ row.metrics.sentiment.score.toFixed(2) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="提及" width="60" prop="mention_count" sortable>
              <template #default="{ row }">{{ row.mention_count || 0 }}</template>
            </el-table-column>
            <el-table-column label="排名" width="60" prop="ucloud_rank" sortable>
              <template #default="{ row }">{{ row.ucloud_rank || '-' }}</template>
            </el-table-column>
          </el-table>
        </template>
      </el-drawer>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { useRoute } from 'vue-router'
import { apiFetch } from '../composables/useWebSocket'

const route = useRoute()

function formatRunTime(ts) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return ts }
}

const scores = ref([])
const charts = ref({})
const latestRun = ref(null)
const loading = ref(true)
const hasData = computed(() => scores.value.length > 0)

// 引用详情 & 渠道聚类
const citationDetails = ref({})
const channelClustering = ref({})
const activeCitationPanels = ref([])
const channelChartRef = ref(null)

const hasCitationData = computed(() => Object.keys(citationDetails.value).length > 0)
const hasChannelData = computed(() => Object.keys(channelClustering.value).length > 0)

// 渠道聚类矩阵数据（用于表格）
const channelMatrixCols = computed(() => {
  const names = new Set()
  for (const mk in channelClustering.value) {
    names.add(channelClustering.value[mk].model_name)
  }
  return [...names]
})

const channelMatrixData = computed(() => {
  // 收集所有渠道名
  const channelSet = new Set()
  for (const mk in channelClustering.value) {
    for (const ch of channelClustering.value[mk].channels) {
      channelSet.add(ch.channel)
    }
  }
  // 构建矩阵行
  return [...channelSet].map(channel => {
    const row = { channel }
    for (const mk in channelClustering.value) {
      const mn = channelClustering.value[mk].model_name
      const found = channelClustering.value[mk].channels.find(c => c.channel === channel)
      row[mn] = found ? found.count : 0
    }
    return row
  }).sort((a, b) => {
    const totalA = channelMatrixCols.value.reduce((s, c) => s + (a[c] || 0), 0)
    const totalB = channelMatrixCols.value.reduce((s, c) => s + (b[c] || 0), 0)
    return totalB - totalA
  })
})

const radarRef = ref(null), barRef = ref(null), coverageRef = ref(null), sentimentRef = ref(null)

// 下钻抽屉
const drawerVisible = ref(false)
const drilldownData = ref(null)
const drilldownModelKey = ref('')
const drilldownModelName = ref('')
const drilldownLoading = ref(false)
const filterMetric = ref('all')
const filterCondition = ref('all')

const filterMetricLabel = computed(() => {
  const map = { coverage: '提及率', citation: '引用率', recommendation: 'TOP3 推荐率', sentiment: '情感值' }
  return map[filterMetric.value] || ''
})

const filteredDrilldown = computed(() => {
  if (!drilldownData.value || !drilldownData.value.questions) return []
  const qs = drilldownData.value.questions
  if (filterMetric.value === 'all' || filterCondition.value === 'all') return qs
  const metric = filterMetric.value
  const cond = filterCondition.value
  return qs.filter(q => {
    if (metric === 'sentiment') {
      const score = q.metrics.sentiment.score
      return cond === 'gt0' ? score > 0.5 : score <= 0.5
    }
    const num = q.metrics[metric]?.numerator || 0
    return cond === 'gt0' ? num > 0 : num === 0
  })
})

function categoryTagType(cat) {
  const map = { '云计算': '', '云存储': 'success', '云数据库': 'warning', 'CDN': 'danger', 'AI服务': 'info',
    '安全服务': 'danger', '大数据': 'success', '容器/K8s': 'warning', '行业方案': 'info', '性价比': '' }
  return map[cat] || ''
}

function sentimentClass(sentiment) {
  if (sentiment.label === 'positive') return 'val-hit'
  if (sentiment.label === 'negative') return 'val-miss'
  return 'val-neutral'
}

async function openDrilldown(modelKey) {
  drilldownModelKey.value = modelKey
  // 从 scores 中找到 model_name
  const s = scores.value.find(s => s.model_key === modelKey)
  drilldownModelName.value = s ? s.model_name : modelKey
  drilldownData.value = null
  filterMetric.value = 'all'
  filterCondition.value = 'all'
  drawerVisible.value = true
  drilldownLoading.value = true

  try {
    const runId = latestRun.value?.id
    if (!runId) return
    const res = await apiFetch(`/results/${runId}/question-drilldown?model_key=${modelKey}`)
    drilldownData.value = res.data || null
  } catch (e) {
    console.error('Drilldown error:', e)
  } finally {
    drilldownLoading.value = false
  }
}

const rankedScores = computed(() => [...scores.value].sort((a, b) => b.geo_score - a.geo_score))

const channelDetails = computed(() => {
  return rankedScores.value.map(s => ({
    ...s,
    _mentioned_count: Math.round(s.coverage_rate * s.valid_responses),
  }))
})

// ===== 指标定义（含公式说明） =====
const metricDefinitions = [
  {
    key: 'coverage_rate', label: '提及率', icon: '📡',
    brief: 'UCloud 被提及的有效响应比例',
    formula: '提及率 = UCloud 被提及的有效响应数 / 有效响应总数',
    description: '仅统计题干不自带 UCloud/优刻得 字眼的自然问题响应；在这些有效响应中，UCloud 被提及（出现品牌名/产品名/别名）的响应占比',
    example: '如48条有效响应中有20条提及UCloud，则提及率=20/48=41.7%',
    weight: 45,
  },
  {
    key: 'citation_rate', label: '引用率', icon: '🔗',
    brief: '包含UCloud引用/链接的响应比例',
    formula: '引用率 = 含 UCloud 官方来源或第三方来源引用的响应数 / 有效响应总数',
    description: '官方来源直接计入；回答提及 UCloud 时，知乎、CSDN、掘金、GitHub、B站等第三方来源链接也计入',
    example: '如36条自然有效响应中有4条含有效来源引用，则引用率=4/36=11.1%',
    weight: 25,
  },
  {
    key: 'recommendation_rate', label: 'TOP3 推荐率', icon: '👍',
    brief: '品牌进入 Top3 的回答比例',
    formula: 'TOP3 推荐率 = 品牌进入 Top3 的回答次数 / 有效回答总次数',
    description: '统计 UCloud 在回答中进入品牌推荐列表 Top3 的比例',
    example: '如48条有效回答中有12条进入Top3，则TOP3推荐率=12/48=25.0%',
    weight: 20,
  },
  {
    key: 'sentiment_score', label: '情感值', icon: '💛',
    brief: 'UCloud提及时的平均情感倾向',
    formula: '情感值 = Σ(被提及响应的情感分数) / 被提及响应数',
    description: '仅在UCloud被提及时计算，范围0-1，>0.6为正面，0.4-0.6为中性，<0.4为负面',
    example: '如20条提及响应的平均情感为0.72，则情感值=0.72（偏正面）',
    weight: 10,
  },
]

// ===== 计算核心指标卡片 =====
function getBest(key) {
  if (!scores.value.length) return null
  return [...scores.value].sort((a, b) => b[key] - a[key])[0]
}

function formatMetricValue(key, raw) {
  if (key === 'coverage_rate' || key === 'citation_rate' || key === 'recommendation_rate') {
    return (raw * 100).toFixed(1) + '%'
  }
  if (key === 'sentiment_score') return raw.toFixed(2)
  return raw
}

const coreMetrics = computed(() => {
  return metricDefinitions.map(m => {
    const best = getBest(m.key)
    const raw = best ? best[m.key] : 0
    return {
      ...m,
      displayValue: best ? formatMetricValue(m.key, raw) : '-',
      bestModel: best ? best.model_name : '',
      barPercent: m.key === 'coverage_rate' || m.key === 'citation_rate' || m.key === 'recommendation_rate'
        ? raw * 100
        : m.key === 'sentiment_score' ? raw * 100
        : 0,
    }
  })
})

const geoBest = computed(() => getBest('geo_score'))
const geoBestScore = computed(() => geoBest.value ? geoBest.value.geo_score.toFixed(1) : '-')
const geoBestModel = computed(() => geoBest.value ? geoBest.value.model_name : '')

// ===== 图表渲染 =====
function renderChart(domRef, option) {
  if (!domRef) return
  const chart = echarts.init(domRef)
  chart.setOption(option)
  window.addEventListener('resize', () => chart.resize())
}

async function loadData() {
  loading.value = true
  try {
    // 优先使用 query param 中的 run_id（从历史页跳转过来）
    const queryRunId = route.query.run_id
    let runId = null

    if (queryRunId) {
      runId = queryRunId
      // 补充 latestRun 信息
      const runRes = await apiFetch(`/evaluations/${runId}`)
      latestRun.value = runRes.data || null
    } else {
      const runsRes = await apiFetch('/evaluations?limit=1')
      const runs = runsRes.data || []
      if (!runs.length) {
        loading.value = false
        return
      }
      latestRun.value = runs[0]
      runId = runs[0].id
    }

    const scoresRes = await apiFetch(`/results/${runId}/scores`)
    scores.value = scoresRes.data || []

    const chartsRes = await apiFetch(`/results/${runId}/charts`)
    charts.value = chartsRes.data || {}

    loading.value = false

    await nextTick()
    if (charts.value.radar) renderChart(radarRef.value, charts.value.radar)
    if (charts.value.bar) renderChart(barRef.value, charts.value.bar)
    if (charts.value.coverage) renderChart(coverageRef.value, charts.value.coverage)
    if (charts.value.sentiment) renderChart(sentimentRef.value, charts.value.sentiment)

    // 加载引用详情和渠道聚类（不阻塞主面板渲染）
    try {
      const citationsRes = await apiFetch(`/results/${runId}/citations`)
      citationDetails.value = citationsRes.data || {}
      // 默认展开第一个面板
      const keys = Object.keys(citationDetails.value)
      if (keys.length) activeCitationPanels.value = [keys[0]]
    } catch (e) { console.warn('Citations load error:', e) }

    try {
      const channelsRes = await apiFetch(`/results/${runId}/citation-channels`)
      channelClustering.value = channelsRes.data || {}
      await nextTick()
      renderChannelChart()
    } catch (e) { console.warn('Citation channels load error:', e) }
  } catch (e) {
    console.error('Dashboard loadData error:', e)
    loading.value = false
  }
}

function renderChannelChart() {
  if (!channelChartRef.value) return
  const data = channelClustering.value
  const models = Object.keys(data)
  if (!models.length) return

  // 收集所有渠道
  const channelSet = new Set()
  for (const mk of models) {
    for (const ch of data[mk].channels) {
      channelSet.add(ch.channel)
    }
  }
  const channels = [...channelSet]

  // 颜色池
  const palette = ['#409eff','#67c23a','#e6a23c','#f56c6c','#909399','#9b59b6','#1abc9c','#e74c3c','#3498db','#f39c12']

  const series = channels.map((channel, idx) => ({
    name: channel,
    type: 'bar',
    stack: 'total',
    data: models.map(mk => {
      const found = data[mk].channels.find(c => c.channel === channel)
      return found ? found.count : 0
    }),
    itemStyle: { color: palette[idx % palette.length] },
    emphasis: { focus: 'series' },
  }))

  const option = {
    title: { text: '引用来源渠道分布', left: 'center', top: 5, textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, type: 'scroll' },
    grid: { left: 80, right: 20, top: 40, bottom: 60 },
    xAxis: { type: 'value', name: '引用次数' },
    yAxis: { type: 'category', data: models.map(mk => data[mk].model_name) },
    series,
  }

  const chart = echarts.init(channelChartRef.value)
  chart.setOption(option)
  window.addEventListener('resize', () => chart.resize())
}

onMounted(loadData)
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
.section-title { font-size: 16px; font-weight: 600; color: #1a1a2e; margin-bottom: 14px; padding-left: 2px; }
.run-breadcrumb { font-size: 13px; color: #666; margin-bottom: 16px; display: flex; align-items: center; }

/* 加载/空状态 */
.loading-state { text-align: center; padding: 80px 0; color: #999; }
.loading-state .el-icon { font-size: 32px; margin-bottom: 12px; }
.empty-state { text-align: center; padding: 40px 0; }

/* ===== 指标卡片 ===== */
.metric-cards-section { margin-bottom: 4px; }
.metric-card { text-align: center; padding: 6px 10px; position: relative; border-radius: 10px; transition: transform 0.2s; }
.metric-card:hover { transform: translateY(-3px); }
.metric-card-header { display: flex; align-items: center; justify-content: center; gap: 4px; margin-bottom: 8px; }
.metric-icon { font-size: 18px; }
.metric-label { font-size: 13px; color: #666; font-weight: 500; }
.metric-value { font-size: 28px; font-weight: 700; color: #1a1a2e; margin: 4px 0; }
.metric-value.geo-value { color: #e6a23c; }
.metric-best { font-size: 11px; color: #888; margin-bottom: 6px; }
.metric-bar-wrap { height: 4px; background: #eee; border-radius: 2px; overflow: hidden; }
.metric-bar { height: 100%; border-radius: 2px; transition: width 0.6s ease; }
.metric-coverage_rate .metric-bar { background: #409eff; }
.metric-citation_rate .metric-bar { background: #e6a23c; }
.metric-recommendation_rate .metric-bar { background: #f56c6c; }
.metric-sentiment_score .metric-bar { background: #f5c542; }
.metric-geo_score .metric-bar, .geo-bar { background: linear-gradient(90deg, #e6a23c, #f56c6c); }

/* 圆圈问号触发器 */
.formula-trigger {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%;
  background: #e8edf3; color: #606266; font-size: 12px;
  cursor: pointer; transition: all 0.2s; font-weight: 600;
  line-height: 1; user-select: none;
}
.formula-trigger:hover { background: #409eff; color: #fff; }

/* 表头列标题的小气泡触发器 */
.col-formula-trigger {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; border-radius: 50%;
  background: #e8edf3; color: #909399; font-size: 10px;
  cursor: pointer; transition: all 0.2s; font-weight: 700;
  line-height: 1; margin-left: 4px; user-select: none;
  vertical-align: middle;
}
.col-formula-trigger:hover { background: #409eff; color: #fff; }

/* 公式 tooltip 内容 */
.formula-tooltip { font-size: 13px; line-height: 1.6; }
.formula-title { font-weight: 700; font-size: 14px; margin-bottom: 6px; color: #1a1a2e; }
.formula-expr {
  background: #f0f5ff; border-left: 3px solid #409eff;
  padding: 6px 10px; margin: 6px 0; border-radius: 4px;
  font-family: 'Consolas', 'Monaco', monospace; font-size: 13px;
  color: #1a1a2e;
}
.formula-desc { color: #666; font-size: 12px; margin-top: 4px; }
.formula-example { color: #999; font-size: 12px; margin-top: 4px; font-style: italic; }
.formula-weight { color: #e6a23c; font-size: 12px; margin-top: 6px; font-weight: 600; }

/* 渠道名称 */
.channel-name { font-weight: 600; color: #1a1a2e; }
.score-good { color: #67c23a; }
.score-low { color: #f56c6c; }

/* 空状态下的指标说明卡片 */
.intro-card { padding: 14px; border-radius: 10px; }
.intro-card-header { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.intro-icon { font-size: 20px; }
.intro-label { font-size: 14px; font-weight: 600; color: #1a1a2e; }
.intro-desc { font-size: 12px; color: #999; line-height: 1.5; }

/* ===== 引用详情区 ===== */
.collapse-title { font-weight: 600; font-size: 14px; color: #1a1a2e; }
.question-text { font-size: 13px; color: #333; }
.citation-item { margin-bottom: 4px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cit-type-tag { flex-shrink: 0; }
.cit-channel-tag { flex-shrink: 0; }
.citation-url { color: #409eff; text-decoration: none; font-size: 12px; word-break: break-all; }
.citation-url:hover { text-decoration: underline; }
.citation-ref { font-size: 12px; color: #666; background: #f5f7fa; padding: 1px 6px; border-radius: 3px; }

/* ===== 渠道聚类区 ===== */
.channel-clustering-section .el-card { height: 100%; }

/* ===== 下钻抽屉 ===== */
.drilldown-header { margin-bottom: 12px; font-size: 14px; color: #333; }
.drilldown-total { margin-right: 8px; }
.drilldown-filter-info { color: #999; font-size: 13px; }
.drilldown-filters { margin-bottom: 12px; display: flex; align-items: center; }
.val-hit { color: #67c23a; font-weight: 600; }
.val-miss { color: #c0c4cc; }
.val-neutral { color: #e6a23c; }
.expand-content { padding: 8px 16px; background: #fafafa; }
.expand-label { font-size: 12px; color: #909399; margin-bottom: 2px; }
.expand-text { font-size: 13px; color: #333; line-height: 1.6; white-space: pre-wrap; }
.expand-error { color: #f56c6c; font-size: 12px; margin-top: 6px; }
</style>
