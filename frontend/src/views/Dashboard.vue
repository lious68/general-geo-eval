<template>
  <div class="dashboard">
    <h2 class="page-title">📊 GEO 评估仪表盘</h2>

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
          <el-col :span="8" v-for="m in metricDefinitions" :key="m.key">
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

      <!-- 五大核心指标卡片 -->
      <div class="metric-cards-section">
        <h3 class="section-title">核心指标概览</h3>
        <el-row :gutter="16">
          <el-col :span="4" v-for="m in coreMetrics" :key="m.key">
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
                      <div class="formula-expr">GEO = (覆盖率×25% + 提及率×15% + 引用率×15% + 推荐率×25% + 情感值×20%) × 100</div>
                      <div class="formula-desc">各指标归一化到0-1后加权求和，再乘以100转换为0-100分制</div>
                      <div class="formula-example">提及率归一化: min(提及率/3.0, 1.0)，即提及3次及以上为满分</div>
                      <div class="formula-weight">加权系数: 覆盖率25%、提及率15%、引用率15%、推荐率25%、情感值20%</div>
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
                      <div class="formula-expr">GEO = (覆盖率×25% + 提及率×15% + 引用率×15% + 推荐率×25% + 情感值×20%) × 100</div>
                      <div class="formula-desc">各指标归一化到0-1后加权求和，再乘100转为0-100分制</div>
                      <div class="formula-example">提及率归一化: min(提及率/3.0, 1.0)</div>
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
                <span>覆盖率</span>
                <el-tooltip placement="top" effect="light" :width="300">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">覆盖率 Coverage Rate</div>
                      <div class="formula-expr">覆盖率 = UCloud被提及的问题数 / 有效问题总数</div>
                      <div class="formula-desc">在所有有效响应中，UCloud被提及（品牌名/产品名/别名）的问题占比</div>
                      <div class="formula-example">48题中20题提及UCloud → 20/48 = 41.7%</div>
                      <div class="formula-weight">GEO权重: 25%</div>
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
                <span>提及率</span>
                <el-tooltip placement="top" effect="light" :width="320">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">提及率 Mention Rate</div>
                      <div class="formula-expr">提及率 = Σ(提及次数 × 位置权重) / 有效响应总数</div>
                      <div class="formula-desc">综合考量提及频次和首次出现位置，越靠前权重越高</div>
                      <div class="formula-example">位置权重: 首位1.0, 第2位0.8, 第3位0.6, 第4位0.4, 第5+位0.2</div>
                      <div class="formula-weight">GEO权重: 15% (归一化: min(提及率/3.0, 1.0))</div>
                    </div>
                  </template>
                  <span class="col-formula-trigger">ⓘ</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                {{ row.mention_rate.toFixed(2) }}
              </template>
            </el-table-column>
            <el-table-column width="120">
              <template #header>
                <span>引用率</span>
                <el-tooltip placement="top" effect="light" :width="300">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">引用率 Citation Rate</div>
                      <div class="formula-expr">引用率 = 包含UCloud引用/链接的响应数 / 有效响应总数</div>
                      <div class="formula-desc">AI回答中主动给出 ucloud.cn 链接或明确引用UCloud来源的比例</div>
                      <div class="formula-example">48条响应中8条含UCloud链接 → 8/48 = 16.7%</div>
                      <div class="formula-weight">GEO权重: 15%</div>
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
                <span>推荐率</span>
                <el-tooltip placement="top" effect="light" :width="320">
                  <template #content>
                    <div class="formula-tooltip">
                      <div class="formula-title">推荐率 Recommendation Rate</div>
                      <div class="formula-expr">推荐率 = UCloud被推荐的响应数 / 有效响应总数</div>
                      <div class="formula-desc">AI明确推荐UCloud作为首选或备选方案的响应占比</div>
                      <div class="formula-example">强推荐=明确首推UCloud，中等推荐=列入推荐列表，弱推荐=顺带提及</div>
                      <div class="formula-weight">GEO权重: 25%</div>
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
                      <div class="formula-weight">GEO权重: 20%</div>
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
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { apiFetch } from '../composables/useWebSocket'

const scores = ref([])
const charts = ref({})
const latestRun = ref(null)
const loading = ref(true)
const hasData = computed(() => scores.value.length > 0)

const radarRef = ref(null), barRef = ref(null), coverageRef = ref(null), sentimentRef = ref(null)

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
    key: 'coverage_rate', label: '覆盖率', icon: '📡',
    brief: 'UCloud 被提及的问题比例',
    formula: '覆盖率 = UCloud被提及的问题数 / 有效问题总数',
    description: '在所有有效响应中，UCloud 被提及（出现品牌名/产品名/别名）的问题占比',
    example: '如48题中有20题提及UCloud，则覆盖率=20/48=41.7%',
    weight: 25,
  },
  {
    key: 'mention_rate', label: '提及率', icon: '💬',
    brief: '平均每条响应中UCloud提及次数(含位置权重)',
    formula: '提及率 = Σ(提及次数 × 位置权重) / 有效响应总数',
    description: '综合考量提及频次和首次出现位置，越靠前位置权重越高',
    example: '位置权重: 第1位=1.0, 第2位=0.8, 第3位=0.6, 第4位=0.4, 第5+位=0.2',
    weight: 15,
  },
  {
    key: 'citation_rate', label: '引用率', icon: '🔗',
    brief: '包含UCloud引用/链接的响应比例',
    formula: '引用率 = 包含UCloud引用的响应数 / 有效响应总数',
    description: 'AI回答中主动给出 ucloud.cn 链接或明确引用 UCloud 来源的比例',
    example: '如48条响应中有8条包含UCloud链接，则引用率=8/48=16.7%',
    weight: 15,
  },
  {
    key: 'recommendation_rate', label: '推荐率', icon: '👍',
    brief: 'UCloud被推荐的响应比例',
    formula: '推荐率 = UCloud被推荐的响应数 / 有效响应总数',
    description: 'AI明确推荐UCloud作为首选或备选方案的响应占比，含强推荐/中等推荐/弱推荐',
    example: '强推荐=明确首推UCloud，中等推荐=将UCloud列入推荐列表',
    weight: 25,
  },
  {
    key: 'sentiment_score', label: '情感值', icon: '💛',
    brief: 'UCloud提及时的平均情感倾向',
    formula: '情感值 = Σ(被提及响应的情感分数) / 被提及响应数',
    description: '仅在UCloud被提及时计算，范围0-1，>0.6为正面，0.4-0.6为中性，<0.4为负面',
    example: '如20条提及响应的平均情感为0.72，则情感值=0.72（偏正面）',
    weight: 20,
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
  if (key === 'mention_rate') return raw.toFixed(2)
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
        : m.key === 'mention_rate' ? Math.min(raw / 3 * 100, 100)
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
    const runsRes = await apiFetch('/evaluations?limit=1')
    const runs = runsRes.data || []
    if (!runs.length) {
      loading.value = false
      return
    }
    latestRun.value = runs[0]

    const scoresRes = await apiFetch(`/results/${runs[0].id}/scores`)
    scores.value = scoresRes.data || []

    const chartsRes = await apiFetch(`/results/${runs[0].id}/charts`)
    charts.value = chartsRes.data || {}

    loading.value = false

    await nextTick()
    if (charts.value.radar) renderChart(radarRef.value, charts.value.radar)
    if (charts.value.bar) renderChart(barRef.value, charts.value.bar)
    if (charts.value.coverage) renderChart(coverageRef.value, charts.value.coverage)
    if (charts.value.sentiment) renderChart(sentimentRef.value, charts.value.sentiment)
  } catch (e) {
    console.error('Dashboard loadData error:', e)
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
.section-title { font-size: 16px; font-weight: 600; color: #1a1a2e; margin-bottom: 14px; padding-left: 2px; }

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
.metric-mention_rate .metric-bar { background: #67c23a; }
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
</style>
