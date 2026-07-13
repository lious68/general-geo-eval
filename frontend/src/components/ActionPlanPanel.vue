<template>
  <div class="action-plan-panel">
    <!-- 加载态 -->
    <el-skeleton v-if="loading" :rows="8" animated />

    <!-- 空数据 -->
    <el-empty v-else-if="!data || !data.summary || !data.summary.natural_total"
              description="该任务暂无有效评测数据，完成评测后即可生成行动计划"
              :image-size="80" />

    <template v-else>
      <!-- ① 真实成绩单：自然题 vs 引导题 -->
      <el-card shadow="never" class="ap-card" :class="{ embedded }">
        <div class="card-title">
          <el-icon><DataAnalysis /></el-icon> 真实成绩单（自然题 vs 引导题）
        </div>
        <el-alert type="warning" :closable="false" style="margin-bottom:12px"
                  title="引导型题（题干自带品牌词）模型照抄即可，已饱和；自然题才是 GEO 真战场。以下行动项全部基于自然题。" />
        <div class="stat-row">
          <div class="stat-block natural">
            <div class="stat-label">自然题</div>
            <div class="stat-grid">
              <div><span class="num">{{ data.summary.natural_total }}</span><span class="cap">样本</span></div>
              <div><span class="num">{{ pct(data.summary.natural_mention_rate) }}</span><span class="cap">提及率</span></div>
              <div><span class="num">{{ pct(data.summary.natural_cite_rate) }}</span><span class="cap">引用率</span></div>
              <div><span class="num">{{ pct(data.summary.natural_top3_rate) }}</span><span class="cap">TOP3</span></div>
            </div>
          </div>
          <div class="stat-block leading">
            <div class="stat-label">引导型题</div>
            <div class="stat-grid">
              <div><span class="num">{{ data.summary.leading_total }}</span><span class="cap">样本</span></div>
              <div><span class="num muted">送分</span><span class="cap">提及率</span></div>
              <div><span class="num muted">送分</span><span class="cap">引用率</span></div>
              <div><span class="num muted">送分</span><span class="cap">TOP3</span></div>
            </div>
          </div>
        </div>
      </el-card>

      <!-- ② 品类表现表 -->
      <el-card shadow="never" class="ap-card">
        <div class="card-title"><el-icon><Grid /></el-icon> 品类表现（仅自然题，洼地排前）</div>
        <el-table :data="data.by_category" size="small" :row-class-name="catRowClass">
          <el-table-column prop="category" label="品类" min-width="120" />
          <el-table-column label="样本" width="70" prop="n" />
          <el-table-column label="提及率" width="90">
            <template #default="{ row }">{{ pct(row.mentioned_pct) }}</template>
          </el-table-column>
          <el-table-column label="引用率" width="90">
            <template #default="{ row }">
              <span :class="{ 'zero': row.cited_pct === 0 }">{{ pct(row.cited_pct) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="TOP3" width="80">
            <template #default="{ row }">{{ pct(row.top3_pct) }}</template>
          </el-table-column>
          <el-table-column label="缺口题" min-width="120">
            <template #default="{ row }">
              <el-tag v-for="q in row.gap_qids" :key="q" size="small" type="danger" effect="plain"
                      style="margin:2px;cursor:pointer"
                      @click="goDrilldown(q)">{{ q }}</el-tag>
              <span v-if="!row.gap_qids.length" style="color:#c0c4cc">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- ③ 缺口题 vs 强项题 -->
      <el-card shadow="never" class="ap-card">
        <div class="card-title"><el-icon><Aim /></el-icon> 缺口题（5 模型全空白）vs 强项题（≥3 模型提及）</div>
        <el-row :gutter="16">
          <el-col :span="12">
            <div class="sub-title danger">❌ 缺口题（{{ data.gap_questions.length }}）—— 内容投入精确打击点</div>
            <div v-for="q in data.gap_questions" :key="q.qid" class="q-item gap" @click="goDrilldown(q.qid)">
              <el-tag size="small" type="danger" effect="plain">{{ q.qid }}</el-tag>
              <el-tag size="small" type="info" effect="plain">{{ q.category }}</el-tag>
              <span class="q-text">{{ q.question }}</span>
            </div>
            <el-empty v-if="!data.gap_questions.length" description="无缺口题" :image-size="40" />
          </el-col>
          <el-col :span="12">
            <div class="sub-title success">✅ 强项题（{{ data.strength_questions.length }}）—— 已验证护城河，可扩大</div>
            <div v-for="q in data.strength_questions" :key="q.qid" class="q-item strength" @click="goDrilldown(q.qid)">
              <el-tag size="small" type="success" effect="plain">{{ q.qid }}</el-tag>
              <el-tag size="small" type="info" effect="plain">{{ q.category }}</el-tag>
              <span class="q-text">{{ q.mention_models }}/{{ q.total_models }} 模型提及 · {{ q.question }}</span>
            </div>
            <el-empty v-if="!data.strength_questions.length" description="无强项题" :image-size="40" />
          </el-col>
        </el-row>
      </el-card>

      <!-- ④ 渠道分布 -->
      <el-card shadow="never" class="ap-card">
        <div class="card-title"><el-icon><Link /></el-icon> 引用渠道分布（按权威性分层）</div>
        <el-row :gutter="16">
          <el-col :span="14">
            <el-table :data="channelRows" size="small" max-height="320">
              <el-table-column label="分层" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="tierType(row.tier)" effect="plain">{{ row.tier }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="channel" label="渠道" min-width="140" />
              <el-table-column prop="count" label="被引次数" width="90" sortable />
            </el-table>
          </el-col>
          <el-col :span="10">
            <div class="sub-title">每模型 官方URL占比</div>
            <el-table :data="data.by_model" size="small">
              <el-table-column prop="model_key" label="模型" width="90" />
              <el-table-column label="提及" width="70">
                <template #default="{ row }">{{ row.mentioned }}/{{ row.n }}</template>
              </el-table-column>
              <el-table-column label="引用" width="70">
                <template #default="{ row }">{{ row.cited }}/{{ row.n }}</template>
              </el-table-column>
              <el-table-column label="官方占比" width="100">
                <template #default="{ row }">
                  <span :class="{ 'low': row.official_url_ratio < 0.10 }">{{ pct(row.official_url_ratio) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-col>
        </el-row>
      </el-card>

      <!-- ⑤ 做得好的结构（标杆模板） -->
      <el-card v-if="data.templates.length" shadow="never" class="ap-card">
        <div class="card-title"><el-icon><Trophy /></el-icon> 做得好的结构（照此模仿）</div>
        <el-row :gutter="12">
          <el-col v-for="t in data.templates" :key="t.qid + t.model" :span="8">
            <div class="tpl-card">
              <div class="tpl-head">
                <el-tag size="small" type="success">{{ t.template_type }}</el-tag>
                <span class="tpl-meta">{{ t.qid }} · {{ t.model }} · rank{{ t.rank }} · {{ t.strength }}</span>
              </div>
              <div class="tpl-q">{{ t.question }}</div>
              <div class="tpl-body">{{ t.head }}</div>
              <div class="tpl-tip">↑ 拆出这个结构（{{ t.template_type }}），复制到同品类其他题</div>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <!-- ⑥ 行动计划清单 -->
      <el-card shadow="never" class="ap-card">
        <div class="card-title">
          <el-icon><List /></el-icon> 行动计划（按优先级，根据本次评测数据生成）
          <el-button size="small" link type="info" @click="clearChecks" style="margin-left:auto">清除勾选</el-button>
        </div>
        <el-collapse v-model="activePriorities">
          <el-collapse-item v-for="p in ['P0','P1','P2','P3']" :key="p" :name="p">
            <template #title>
              <el-tag :type="priorityType(p)" effect="dark" size="small" style="margin-right:8px">{{ p }}</el-tag>
              <span>{{ priorityLabel(p) }}（{{ itemsByPriority[p]?.length || 0 }}）</span>
            </template>
            <div v-for="(item, idx) in (itemsByPriority[p] || [])" :key="p + idx" class="action-item">
              <el-checkbox :model-value="isChecked(p, idx)" @change="toggleCheck(p, idx, $event)">
                <span class="action-title">{{ item.title }}</span>
              </el-checkbox>
              <div class="action-evidence">依据：{{ item.evidence }}</div>
              <ul class="action-list">
                <li v-for="(a, i) in item.actions" :key="i">{{ a }}</li>
              </ul>
            </div>
            <el-empty v-if="!(itemsByPriority[p] || []).length" description="无" :image-size="40" />
          </el-collapse-item>
        </el-collapse>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getActionPlan } from '../api/tasks'

const props = defineProps({
  taskId: { type: String, required: true },
  modelKey: { type: String, default: null },
  embedded: { type: Boolean, default: false },
})

const router = useRouter()
const data = ref(null)
const loading = ref(false)
const activePriorities = ref(['P0', 'P1'])
const checks = ref({})  // { 'P0-0': true, ... }

const STORAGE_KEY = computed(() => `geo_action_checks_${props.taskId}`)

function loadChecks() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY.value)
    checks.value = raw ? JSON.parse(raw) : {}
  } catch (e) {
    checks.value = {}
  }
}
function saveChecks() {
  try { localStorage.setItem(STORAGE_KEY.value, JSON.stringify(checks.value)) } catch (e) {}
}
function isChecked(p, idx) { return !!checks.value[`${p}-${idx}`] }
function toggleCheck(p, idx, val) {
  const k = `${p}-${idx}`
  if (val) checks.value[k] = true
  else delete checks.value[k]
  saveChecks()
}
function clearChecks() {
  checks.value = {}
  saveChecks()
}

const itemsByPriority = computed(() => {
  const out = {}
  for (const it of (data.value?.action_items || [])) {
    (out[it.priority] = out[it.priority] || []).push(it)
  }
  return out
})

const channelRows = computed(() => data.value?.channels || [])

function pct(v) {
  if (v == null) return '—'
  return (v * 100).toFixed(0) + '%'
}
function tierType(tier) {
  return { '官方': 'success', '权威参考': 'primary', '权威社区': 'info', '一般UGC': 'warning', '未映射': '', '其他已映射': 'info' }[tier] || ''
}
function priorityType(p) {
  return { P0: 'danger', P1: 'warning', P2: 'primary', P3: 'info' }[p] || ''
}
function priorityLabel(p) {
  return { P0: '立即做', P1: '尽快做', P2: '补强', P3: '低优先级' }[p] || p
}
function catRowClass({ row }) {
  if (row.cited_pct === 0 || row.mentioned_pct < 0.20) return 'warn-row'
  return ''
}
function goDrilldown(qid) {
  // 跳 Dashboard 下钻（task_id 模式）
  router.push({ path: '/dashboard', query: { task_id: props.taskId } })
}

async function load() {
  if (!props.taskId) return
  loading.value = true
  try {
    const params = { task_id: props.taskId }
    if (props.modelKey) params.model_key = props.modelKey
    const res = await getActionPlan('0', params)
    data.value = res.data || null
  } catch (e) {
    console.error('action-plan load failed', e)
    data.value = null
  } finally {
    loading.value = false
  }
}

watch(() => [props.taskId, props.modelKey], load, { immediate: false })
onMounted(() => { loadChecks(); load() })
</script>

<style scoped>
.action-plan-panel { display: flex; flex-direction: column; gap: 14px; }
.ap-card { border-radius: 10px; }
.ap-card.embedded { box-shadow: none; }
.card-title { display: flex; align-items: center; gap: 6px; font-size: 15px; font-weight: 600; margin-bottom: 10px; color: var(--color-text); }

.stat-row { display: flex; gap: 16px; }
.stat-block { flex: 1; padding: 12px; border-radius: 8px; }
.stat-block.natural { background: rgba(64,158,255,0.08); border: 1px solid rgba(64,158,255,0.2); }
.stat-block.leading { background: rgba(144,147,153,0.08); border: 1px solid rgba(144,147,153,0.2); }
.stat-label { font-size: 13px; color: var(--color-text-sec); margin-bottom: 8px; }
.stat-grid { display: flex; gap: 16px; flex-wrap: wrap; }
.stat-grid > div { display: flex; flex-direction: column; }
.stat-grid .num { font-size: 20px; font-weight: 700; color: var(--color-primary); }
.stat-grid .num.muted { color: var(--color-text-sec); font-size: 16px; }
.stat-grid .cap { font-size: 11px; color: #999; }

.sub-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.sub-title.danger { color: #f56c6c; }
.sub-title.success { color: #67c23a; }
.q-item { padding: 6px 8px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.q-item:hover { background: var(--color-primary-soft); }
.q-item.gap { border-left: 3px solid #f56c6c; }
.q-item.strength { border-left: 3px solid #67c23a; }
.q-text { font-size: 12px; color: var(--color-text-sec); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

:deep(.warn-row) { background: rgba(245,108,108,0.06) !important; }
.zero { color: #f56c6c; font-weight: 700; }
.low { color: #e6a23c; }

.tpl-card { border: 1px solid var(--color-border); border-radius: 8px; padding: 10px; height: 100%; }
.tpl-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.tpl-meta { font-size: 11px; color: #999; }
.tpl-q { font-size: 12px; color: var(--color-text); margin-bottom: 6px; font-weight: 600; }
.tpl-body { font-size: 11px; color: var(--color-text-sec); max-height: 120px; overflow: auto; white-space: pre-wrap; background: #fafafa; padding: 6px; border-radius: 4px; }
.tpl-tip { font-size: 11px; color: var(--color-primary); margin-top: 6px; }

.action-item { padding: 10px; border: 1px solid var(--color-border); border-radius: 6px; margin-bottom: 8px; }
.action-title { font-weight: 600; font-size: 13px; }
.action-evidence { font-size: 11px; color: #999; margin: 4px 0 4px 24px; }
.action-list { margin: 4px 0 0 24px; padding-left: 16px; }
.action-list li { font-size: 12px; color: var(--color-text-sec); line-height: 1.8; }
</style>
