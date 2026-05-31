<template>
  <div class="dashboard">
    <h2 class="page-title">📊 GEO 评估仪表盘</h2>
    <el-alert v-if="!latestRun" title="暂无评测数据" description="请先执行一次评测" type="info" show-icon :closable="false" style="margin-bottom:20px" />

    <!-- 汇总卡片 -->
    <el-row :gutter="16" v-if="scores.length">
      <el-col :span="6" v-for="card in summaryCards" :key="card.label">
        <el-card shadow="hover" class="metric-card">
          <div class="metric-label">{{ card.label }}</div>
          <div class="metric-value">{{ card.value }}</div>
          <div class="metric-model">{{ card.model }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 模型排名表 -->
    <el-card v-if="scores.length" style="margin-top:20px">
      <template #header><strong>🏆 模型排名</strong></template>
      <el-table :data="rankedScores" stripe>
        <el-table-column label="排名" width="80">
          <template #default="{ $index }">{{ ['🥇','🥈','🥉'][$index] || `#${$index+1}` }}</template>
        </el-table-column>
        <el-table-column prop="model_name" label="模型" width="120" />
        <el-table-column prop="geo_score" label="GEO得分" width="100">
          <template #default="{ row }"><strong>{{ row.geo_score.toFixed(1) }}</strong></template>
        </el-table-column>
        <el-table-column label="覆盖率" width="100">
          <template #default="{ row }">{{ (row.coverage_rate * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="提及率" width="100">
          <template #default="{ row }">{{ row.mention_rate.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="引用率" width="100">
          <template #default="{ row }">{{ (row.citation_rate * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="推荐率" width="100">
          <template #default="{ row }">{{ (row.recommendation_rate * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column label="情感值" width="100">
          <template #default="{ row }">{{ row.sentiment_score.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="平均排名" width="100">
          <template #default="{ row }">{{ row.avg_rank.toFixed(1) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 图表区 -->
    <el-row :gutter="16" v-if="charts.radar" style="margin-top:20px">
      <el-col :span="12">
        <el-card><div ref="radarRef" style="height:400px"></div></el-card>
      </el-col>
      <el-col :span="12">
        <el-card><div ref="barRef" style="height:400px"></div></el-card>
      </el-col>
    </el-row>
    <el-row :gutter="16" v-if="charts.coverage" style="margin-top:16px">
      <el-col :span="12">
        <el-card><div ref="coverageRef" style="height:400px"></div></el-card>
      </el-col>
      <el-col :span="12">
        <el-card><div ref="sentimentRef" style="height:400px"></div></el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { apiFetch } from '../composables/useWebSocket'

const scores = ref([])
const charts = ref({})
const latestRun = ref(null)
const radarRef = ref(null), barRef = ref(null), coverageRef = ref(null), sentimentRef = ref(null)

const rankedScores = computed(() => [...scores.value].sort((a, b) => b.geo_score - a.geo_score))

const summaryCards = computed(() => {
  if (!scores.value.length) return []
  const best = (key) => [...scores.value].sort((a, b) => b[key] - a[key])[0]
  return [
    { label: '最佳GEO得分', value: best('geo_score').geo_score.toFixed(1), model: best('geo_score').model_name },
    { label: '最高覆盖率', value: (best('coverage_rate').coverage_rate * 100).toFixed(1) + '%', model: best('coverage_rate').model_name },
    { label: '最高推荐率', value: (best('recommendation_rate').recommendation_rate * 100).toFixed(1) + '%', model: best('recommendation_rate').model_name },
    { label: '最高情感值', value: best('sentiment_score').sentiment_score.toFixed(2), model: best('sentiment_score').model_name },
  ]
})

function renderChart(domRef, option) {
  if (!domRef) return
  const chart = echarts.init(domRef)
  chart.setOption(option)
  window.addEventListener('resize', () => chart.resize())
}

async function loadData() {
  try {
    const runsRes = await apiFetch('/evaluations?limit=1')
    const runs = runsRes.data || []
    if (!runs.length) return
    latestRun.value = runs[0]

    const scoresRes = await apiFetch(`/results/${runs[0].id}/scores`)
    scores.value = scoresRes.data || []

    const chartsRes = await apiFetch(`/results/${runs[0].id}/charts`)
    charts.value = chartsRes.data || {}

    await nextTick()
    if (charts.value.radar) renderChart(radarRef.value, charts.value.radar)
    if (charts.value.bar) renderChart(barRef.value, charts.value.bar)
    if (charts.value.coverage) renderChart(coverageRef.value, charts.value.coverage)
    if (charts.value.sentiment) renderChart(sentimentRef.value, charts.value.sentiment)
  } catch (e) { console.error(e) }
}

onMounted(loadData)
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
.metric-card { text-align: center; padding: 10px; }
.metric-card .metric-label { font-size: 13px; color: #999; margin-bottom: 8px; }
.metric-card .metric-value { font-size: 28px; font-weight: 700; color: #1a1a2e; }
.metric-card .metric-model { font-size: 12px; color: #0f3460; margin-top: 4px; }
</style>
