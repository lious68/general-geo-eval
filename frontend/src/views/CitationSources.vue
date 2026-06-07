<template>
  <div class="citation-sources">
    <h2 class="page-title">🔗 引用源情况</h2>
    <p class="page-subtitle">汇总评测问题中被引用的平台来源，支持按时间、AI 渠道和来源名称筛选</p>

    <el-card class="filter-card">
      <div class="filters">
        <div class="filter-item date-filter">
          <span class="filter-label">日期：</span>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="→"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            :clearable="false"
            @change="renderCharts"
          />
        </div>
        <div class="platform-tabs">
          <el-button
            v-for="platform in platformOptions"
            :key="platform.key"
            :type="selectedPlatform === platform.key ? 'primary' : 'default'"
            @click="selectedPlatform = platform.key; renderCharts()"
          >
            {{ platform.name }}
          </el-button>
        </div>
        <el-input
          v-model="searchKeyword"
          class="search-input"
          clearable
          placeholder="搜索来源..."
          prefix-icon="Search"
          @input="renderCharts"
        />
      </div>
    </el-card>

    <div v-if="loading" class="loading-state">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>正在加载引用源数据...</p>
    </div>

    <template v-else>
      <div class="stat-grid">
        <el-card>
          <div class="stat-label">引用来源数</div>
          <div class="stat-value">{{ summary.sourceCount }}</div>
        </el-card>
        <el-card>
          <div class="stat-label">总引用次数</div>
          <div class="stat-value">{{ summary.totalCitations }}</div>
        </el-card>
        <el-card>
          <div class="stat-label">平均引用次数</div>
          <div class="stat-value">{{ summary.avgCitations }}</div>
        </el-card>
      </div>

      <div v-if="!filteredSources.length" class="empty-wrap">
        <el-empty description="当前筛选条件下暂无引用源数据" />
      </div>

      <template v-else>
        <div class="chart-layout">
          <el-card class="bar-card">
            <template #header><strong>Top 10 引用来源</strong></template>
            <div ref="topSourceChartRef" class="chart chart-large"></div>
          </el-card>
          <el-card>
            <template #header><strong>渠道引用占比</strong></template>
            <div ref="platformPieChartRef" class="chart chart-pie"></div>
            <div class="platform-list">
              <div v-for="item in platformShare" :key="item.name" class="platform-row">
                <span class="dot" :style="{ background: item.color }"></span>
                <span class="platform-name">{{ item.name }}</span>
                <strong>{{ item.count }}</strong>
              </div>
            </div>
          </el-card>
        </div>

        <el-card style="margin-top:20px">
          <template #header><strong>引用来源明细</strong></template>
          <el-table :data="filteredSources" stripe style="width:100%">
            <el-table-column prop="source" label="引用来源" min-width="180" />
            <el-table-column label="引用次数" width="110" sortable>
              <template #default="{ row }">
                <el-button type="primary" link size="small" @click="openDrilldown(row.source)">
                  {{ row.count }}
                </el-button>
              </template>
            </el-table-column>
            <el-table-column label="涉及渠道" min-width="220">
              <template #default="{ row }">
                <el-tag v-for="p in row.platforms" :key="p.name" size="small" style="margin:2px" effect="plain">
                  {{ p.name }}：{{ p.count }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="示例链接" min-width="320">
              <template #default="{ row }">
                <div v-for="url in row.sample_urls.slice(0, 3)" :key="url" class="sample-url">
                  <a :href="url" target="_blank">{{ url }}</a>
                </div>
                <span v-if="!row.sample_urls.length" style="color:#999">—</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 下钻弹窗 -->
        <el-dialog v-model="drilldownVisible" :title="`📎 ${drilldownSource} 引用详情`" width="820px" top="6vh">
          <div v-if="drilldownLoading" style="text-align:center;padding:30px">
            <el-icon class="is-loading" :size="24"><Loading /></el-icon>
            <p style="color:#64748b;margin-top:10px">正在加载...</p>
          </div>
          <template v-else>
            <el-collapse v-for="(data, mk) in drilldownData" :key="mk">
              <el-collapse-item :name="mk">
                <template #title>
                  <strong>{{ data.model_name }}</strong>
                  <el-tag size="small" type="info" style="margin-left:8px">{{ data.questions.length }} 条引用</el-tag>
                </template>
                <el-table :data="data.questions" stripe size="small" style="width:100%">
                  <el-table-column label="问题" min-width="200">
                    <template #default="{ row }">
                      <span>{{ row.question_text || row.question_id }}</span>
                      <el-tag v-if="row.ucloud_mentioned" size="small" type="success" style="margin-left:6px">提及UCloud</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="引用链接" min-width="340">
                    <template #default="{ row }">
                      <div v-for="u in row.urls" :key="u.content" class="sample-url">
                        <el-tag v-if="u.is_ucloud" size="small" type="success" style="margin-right:4px">UCloud</el-tag>
                        <a :href="u.content" target="_blank">{{ u.content }}</a>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>
              </el-collapse-item>
            </el-collapse>
            <el-empty v-if="!Object.keys(drilldownData).length" description="暂无引用详情" />
          </template>
        </el-dialog>
      </template>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { apiFetch } from '../composables/useWebSocket'

const loading = ref(true)
const runs = ref([])
const sourceRows = ref([])
const dateRange = ref([])
const selectedPlatform = ref('all')
const searchKeyword = ref('')
const topSourceChartRef = ref(null)
const platformPieChartRef = ref(null)
const drilldownVisible = ref(false)
const drilldownSource = ref('')
const drilldownData = ref({})
const drilldownLoading = ref(false)

const platformColors = ['#5b5cf6', '#ec4899', '#f59e0b', '#10b981', '#3b82f6']
const fixedPlatforms = [
  { key: 'qwen', name: '通义千问', aliases: ['qwen', '通义千问', '通义', 'qianwen'] },
  { key: 'kimi', name: 'Kimi', aliases: ['kimi', '月之暗面', 'moonshot'] },
  { key: 'ernie', name: '文心一言', aliases: ['ernie', '文心一言', '文心', 'baidu'] },
  { key: 'deepseek', name: 'DeepSeek', aliases: ['deepseek'] },
  { key: 'doubao', name: '豆包', aliases: ['doubao', '豆包', 'bytedance'] },
]

const completedRuns = computed(() => runs.value.filter(r => r.status === 'completed'))
const platformOptions = computed(() => [
  { key: 'all', name: '全部渠道' },
  ...fixedPlatforms.map(({ key, name }) => ({ key, name })),
])

function platformMatches(row, platformKey) {
  if (platformKey === 'all') return true
  const platform = fixedPlatforms.find(p => p.key === platformKey)
  if (!platform) return row.model_key === platformKey
  const haystack = `${row.model_key || ''} ${row.model_name || ''}`.toLowerCase()
  return platform.aliases.some(alias => haystack.includes(alias.toLowerCase()))
}

function platformDisplayName(row) {
  return fixedPlatforms.find(p => platformMatches(row, p.key))?.name || row.model_name || row.model_key
}

function sortPlatforms(list) {
  return list.sort((a, b) => {
    const ai = fixedPlatforms.findIndex(p => p.name === a.name)
    const bi = fixedPlatforms.findIndex(p => p.name === b.name)
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi)
  })
}

const filteredRawRows = computed(() => {
  const [start, end] = dateRange.value || []
  const keyword = searchKeyword.value.trim().toLowerCase()
  return sourceRows.value.filter(row => {
    if (!platformMatches(row, selectedPlatform.value)) return false
    if (start && row.run_date < start) return false
    if (end && row.run_date > end) return false
    if (keyword && !row.source.toLowerCase().includes(keyword)) return false
    return true
  })
})

const filteredSources = computed(() => {
  const map = new Map()
  filteredRawRows.value.forEach(row => {
    if (!map.has(row.source)) {
      map.set(row.source, { source: row.source, count: 0, platformMap: new Map(), sample_urls: [] })
    }
    const item = map.get(row.source)
    item.count += row.count
    item.platformMap.set(platformDisplayName(row), (item.platformMap.get(platformDisplayName(row)) || 0) + row.count)
    row.sample_urls.forEach(url => {
      if (item.sample_urls.length < 6 && !item.sample_urls.includes(url)) item.sample_urls.push(url)
    })
  })
  return Array.from(map.values()).map(item => ({
    source: item.source,
    count: item.count,
    platforms: sortPlatforms(Array.from(item.platformMap.entries()).map(([name, count]) => ({ name, count }))),
    sample_urls: item.sample_urls,
  })).sort((a, b) => b.count - a.count)
})

const platformShare = computed(() => {
  return fixedPlatforms.map((platform, i) => {
    const count = filteredRawRows.value
      .filter(row => platformMatches(row, platform.key))
      .reduce((sum, row) => sum + row.count, 0)
    return { name: platform.name, count, color: platformColors[i % platformColors.length] }
  })
})

const summary = computed(() => {
  const total = filteredSources.value.reduce((sum, row) => sum + row.count, 0)
  const sourceCount = filteredSources.value.length
  return {
    sourceCount,
    totalCitations: total,
    avgCitations: sourceCount ? (total / sourceCount).toFixed(1) : '0.0',
  }
})

function toDateOnly(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

function initDateRange() {
  const dates = completedRuns.value.map(r => toDateOnly(r.completed_at || r.started_at)).filter(Boolean).sort()
  if (dates.length) dateRange.value = [dates[0], dates[dates.length - 1]]
}

async function loadData() {
  loading.value = true
  try {
    const res = await apiFetch('/evaluations?limit=100')
    runs.value = res.data || []
    initDateRange()

    const rows = []
    for (const run of completedRuns.value) {
      try {
        const channelsRes = await apiFetch(`/results/${run.id}/citation-channels`)
        const byModel = channelsRes.data || {}
        Object.entries(byModel).forEach(([modelKey, modelData]) => {
          ;(modelData.channels || []).forEach(channel => {
            rows.push({
              run_id: run.id,
              run_date: toDateOnly(run.completed_at || run.started_at),
              model_key: modelKey,
              model_name: modelData.model_name || modelKey,
              source: channel.channel || '其他',
              count: Number(channel.count) || 0,
              sample_urls: channel.sample_urls || [],
            })
          })
        })
      } catch { /* ignore single run */ }
    }
    sourceRows.value = rows
  } finally {
    loading.value = false
    await nextTick()
    renderCharts()
  }
}

function renderCharts() {
  nextTick(() => {
    renderTopSourceChart()
    renderPlatformPieChart()
  })
}

function renderTopSourceChart() {
  if (!topSourceChartRef.value) return
  const data = filteredSources.value.slice(0, 10).reverse()
  const chart = echarts.init(topSourceChartRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 130, right: 24, top: 20, bottom: 35 },
    xAxis: { type: 'value', name: '引用次数' },
    yAxis: { type: 'category', data: data.map(d => d.source), axisLabel: { width: 120, overflow: 'truncate' } },
    series: [{
      type: 'bar',
      data: data.map((d, i) => ({ value: d.count, itemStyle: { color: platformColors[i % platformColors.length] } })),
      barWidth: 20,
      label: { show: true, position: 'right' },
    }],
  })
  window.addEventListener('resize', () => chart.resize())
}

function renderPlatformPieChart() {
  if (!platformPieChartRef.value) return
  const chart = echarts.init(platformPieChartRef.value)
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['48%', '72%'],
      center: ['50%', '52%'],
      data: platformShare.value.map(item => ({ name: item.name, value: item.count, itemStyle: { color: item.color } })),
      label: { show: false },
    }],
  })
  window.addEventListener('resize', () => chart.resize())
}

onMounted(loadData)

async function openDrilldown(source) {
  drilldownSource.value = source
  drilldownVisible.value = true
  drilldownLoading.value = true
  drilldownData.value = {}

  try {
    const result = {}
    for (const run of completedRuns.value) {
      try {
        const res = await apiFetch(`/results/${run.id}/citation-drilldown?source_channel=${encodeURIComponent(source)}`)
        const data = res.data || {}
        for (const [mk, modelData] of Object.entries(data)) {
          if (!result[mk]) {
            result[mk] = { model_name: modelData.model_name, questions: [] }
          }
          for (const q of modelData.questions) {
            // 标记评测时间
            q.run_date = toDateOnly(run.completed_at || run.started_at)
            result[mk].questions.push(q)
          }
        }
      } catch { /* ignore */ }
    }
    drilldownData.value = result
  } finally {
    drilldownLoading.value = false
  }
}
</script>

<style scoped>
.page-title { font-size: 28px; margin-bottom: 6px; color: #0f172a; font-weight: 800; }
.page-subtitle { color: #64748b; margin-bottom: 22px; }
.filter-card { margin-bottom: 20px; }
.filters { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.filter-item { display: flex; align-items: center; gap: 8px; }
.filter-label { color: #64748b; font-weight: 600; white-space: nowrap; }
.platform-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
.search-input { width: 240px; }
.loading-state { text-align: center; padding: 80px 0; color: #64748b; }
.stat-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-bottom: 20px; }
.stat-label { color: #64748b; margin-bottom: 10px; }
.stat-value { font-size: 30px; font-weight: 800; color: #0f172a; }
.chart-layout { display: grid; grid-template-columns: 2.1fr 1.1fr; gap: 20px; }
.chart { width: 100%; }
.chart-large { height: 420px; }
.chart-pie { height: 260px; }
.platform-list { margin-top: 10px; }
.platform-row { display: flex; align-items: center; gap: 8px; margin: 10px 0; color: #334155; }
.platform-name { flex: 1; }
.dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.sample-url { line-height: 1.6; }
.sample-url a { color: #409eff; text-decoration: none; word-break: break-all; }
.sample-url a:hover { text-decoration: underline; }
.empty-wrap { background: #fff; border-radius: 12px; padding: 60px 0; }

@media (max-width: 1100px) {
  .chart-layout { grid-template-columns: 1fr; }
}
@media (max-width: 800px) {
  .stat-grid { grid-template-columns: 1fr; }
  .search-input { width: 100%; }
}
</style>
