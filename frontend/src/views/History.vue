<template>
  <div class="history">
    <h2 class="page-title">🕐 历史评测情况</h2>

    <el-card v-if="!runs.length && !loading" style="text-align:center;padding:40px">
      <el-empty description="暂无评测记录" :image-size="80">
        <el-button type="primary" @click="$router.push('/evaluation')">执行第一次评测</el-button>
      </el-empty>
    </el-card>

    <template v-else>
      <!-- 评测列表 -->
      <el-card>
        <el-table :data="runs" stripe style="width:100%">
          <el-table-column label="评测时间" width="180">
            <template #default="{ row }">
              {{ formatTime(row.started_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" width="140" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="模型" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="mk in parseModels(row.model_keys)" :key="mk" size="small"
                style="margin:2px" effect="plain">{{ mk }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="100">
            <template #default="{ row }">
              <el-progress :percentage="Math.round((row.completed_questions||0)/(row.total_questions||1)*100)"
                :status="row.status==='completed'?'success':row.status==='failed'?'exception':''"
                :stroke-width="10" style="width:70px" />
            </template>
          </el-table-column>
          <el-table-column label="最佳GEO" width="100">
            <template #default="{ row }">
              <strong v-if="row.best_geo != null" :class="row.best_geo >= 30 ? 'score-good' : 'score-low'">
                {{ row.best_geo.toFixed(1) }}
              </strong>
              <span v-else style="color:#c0c4cc">—</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="90">
            <template #default="{ row }">
              {{ duration(row) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" @click="viewResult(row.id)" :disabled="row.status!=='completed'">
                📊 查看
              </el-button>
              <el-button size="small" type="danger" @click="deleteRun(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 对比区 -->
      <div class="compare-section" v-if="completedRuns.length >= 2" style="margin-top:20px">
        <h3 class="section-title">📈 评测趋势对比</h3>
        <el-card>
          <div ref="trendChartRef" style="height:300px"></div>
        </el-card>
        <div class="metric-trend-grid">
          <el-card v-for="metric in metricTrendDefs" :key="metric.key">
            <div :ref="el => { if (el) metricChartRefs[metric.key] = el }" style="height:280px"></div>
          </el-card>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import { apiFetch } from '../composables/useWebSocket'

const router = useRouter()
const runs = ref([])
const loading = ref(true)
const trendChartRef = ref(null)
const metricChartRefs = ref({})

const metricTrendDefs = [
  { key: 'coverage_rate', name: '提及率', color: '#409eff' },
  { key: 'citation_rate', name: '引用率', color: '#e6a23c' },
  { key: 'recommendation_rate', name: 'TOP3 推荐率', color: '#f56c6c' },
  { key: 'sentiment_score', name: '情感值', color: '#67c23a' },
]

const completedRuns = computed(() => runs.value.filter(r => r.status === 'completed'))

function formatTime(ts) {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return ts }
}

function statusType(s) {
  return s === 'completed' ? 'success' : s === 'running' ? 'warning' : 'danger'
}

function statusLabel(s) {
  return s === 'completed' ? '已完成' : s === 'running' ? '运行中' : s === 'failed' ? '失败' : '等待中'
}

function parseModels(mk) {
  if (!mk) return []
  if (typeof mk === 'string') {
    try { return JSON.parse(mk) } catch { return [mk] }
  }
  return Array.isArray(mk) ? mk : []
}

function duration(row) {
  if (!row.started_at) return '—'
  const start = new Date(row.started_at)
  const end = row.completed_at ? new Date(row.completed_at) : new Date()
  const mins = Math.round((end - start) / 60000)
  if (mins < 1) return '<1分钟'
  if (mins < 60) return `${mins}分钟`
  return `${Math.floor(mins / 60)}时${mins % 60}分`
}

function calcMetricAverages(scores) {
  const keys = ['coverage_rate', 'citation_rate', 'recommendation_rate', 'sentiment_score']
  if (!scores.length) return Object.fromEntries(keys.map(k => [k, 0]))
  return Object.fromEntries(keys.map(k => {
    const total = scores.reduce((sum, s) => sum + (Number(s[k]) || 0), 0)
    return [k, total / scores.length]
  }))
}

async function loadRuns() {
  loading.value = true
  try {
    const res = await apiFetch('/evaluations?limit=50')
    runs.value = res.data || []

    // 为已完成的评测加载最佳 GEO 得分
    for (const run of runs.value) {
      if (run.status === 'completed') {
        try {
          const scoresRes = await apiFetch(`/results/${run.id}/scores`)
          const scores = scoresRes.data || []
          if (scores.length) {
            run.best_geo = Math.max(...scores.map(s => s.geo_score || 0))
            run.metric_averages = calcMetricAverages(scores)
          }
        } catch { /* ignore */ }
      }
    }

    loading.value = false

    // 渲染趋势图
    await nextTick()
    if (completedRuns.value.length >= 2) {
      renderTrendChart()
      renderMetricTrendCharts()
    }
  } catch (e) {
    console.error('Load runs error:', e)
    loading.value = false
  }
}

function renderTrendChart() {
  if (!trendChartRef.value) return
  const data = completedRuns.value.slice().reverse()

  const dates = data.map(r => formatTime(r.started_at))
  const geoScores = data.map(r => r.best_geo ?? 0)

  const chart = echarts.init(trendChartRef.value)
  chart.setOption({
    title: { text: 'GEO 综合得分趋势', left: 'center', top: 5, textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 30, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value', name: 'GEO得分', min: 0 },
    series: [{
      type: 'line',
      data: geoScores,
      smooth: true,
      itemStyle: { color: '#409eff' },
      areaStyle: { color: 'rgba(64,158,255,0.1)' },
      label: { show: true, formatter: '{c}', fontSize: 12, fontWeight: 'bold' },
    }],
  })
  window.addEventListener('resize', () => chart.resize())
}

function renderMetricTrendCharts() {
  const data = completedRuns.value.slice().reverse()
  const dates = data.map(r => formatTime(r.started_at))

  metricTrendDefs.forEach(metric => {
    const chartEl = metricChartRefs.value[metric.key]
    if (!chartEl) return

    const chart = echarts.init(chartEl)
    chart.setOption({
      title: { text: `${metric.name}趋势（5渠道平均值）`, left: 'center', top: 5, textStyle: { fontSize: 14 } },
      tooltip: { trigger: 'axis', valueFormatter: value => `${Number(value).toFixed(1)}%` },
      grid: { left: 55, right: 25, top: 45, bottom: 35 },
      xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 11 } },
      yAxis: { type: 'value', name: '%', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
      series: [{
        name: metric.name,
        type: 'line',
        data: data.map(r => Number(((r.metric_averages?.[metric.key] || 0) * 100).toFixed(1))),
        smooth: true,
        itemStyle: { color: metric.color },
        lineStyle: { width: 2 },
        areaStyle: { color: `${metric.color}1a` },
        label: { show: true, formatter: '{c}%', fontSize: 11 },
      }],
    })
    window.addEventListener('resize', () => chart.resize())
  })
}

function viewResult(runId) {
  router.push({ path: '/dashboard', query: { run_id: runId } })
}

async function deleteRun(runId) {
  try {
    await ElMessageBox.confirm('确定删除此评测记录及所有结果数据？', '确认删除', { type: 'warning' })
    await apiFetch(`/evaluations/${runId}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await loadRuns()
  } catch { /* cancelled */ }
}

onMounted(loadRuns)
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
.section-title { font-size: 16px; font-weight: 600; color: #1a1a2e; margin-bottom: 14px; padding-left: 2px; }
.metric-trend-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
.score-good { color: #67c23a; font-weight: 600; }
.score-low { color: #f56c6c; }

@media (max-width: 900px) {
  .metric-trend-grid { grid-template-columns: 1fr; }
}
</style>
