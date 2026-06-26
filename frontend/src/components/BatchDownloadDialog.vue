<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
             title="添加批次（子任务：模型 × 品类 × 题号区间）" width="820px" @open="onOpen">
    <el-alert type="info" :closable="false" style="margin-bottom:12px">
      每个批次 = <b>一个模型</b>（或<b>全部模型</b>）+ <b>一个品类</b>（或全部）+ <b>题号区间</b>。
      选「全部模型」时该行的品类/题区间应用到所有模型，下载配置时展开成每模型一个 unit。
      同一模型可分多次下载不同品类/区间（如 豆包·海外云主机·1-12，再 豆包·海外云主机·13-20），
      导入后按 (任务,模型,问题) 自动合并，不会覆盖已导入结果。
      <br/>模型不要求预先登录：未登录的模型首次运行时会弹浏览器让你登录，登录态自动保存复用。
    </el-alert>

    <div v-for="(row, i) in batchRows" :key="i" class="batch-row">
      <div class="row-line1">
        <el-select v-model="row.model_key" placeholder="选模型" style="width:220px">
          <el-option label="全部模型 (all)" value="__all__" />
          <el-option v-for="m in allModels" :key="m.key" :label="m.name + (m.is_logged_in ? ' ✓' : '')"
                     :value="m.key"
                     :disabled="batchRows.some((r,j)=>j!==i&&r.model_key===m.key)" />
        </el-select>
        <el-select v-model="row.category" placeholder="品类" style="width:200px" @change="onCategoryChange(row)">
          <el-option label="全部品类" value="全部" />
          <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
        </el-select>
        <span class="pool-hint">该品类下 {{ poolQids(row).length }} 题</span>
        <el-button type="danger" link @click="batchRows.splice(i,1)" style="margin-left:auto">删</el-button>
      </div>
      <div class="row-line2">
        <span class="range-hint">题号区间</span>
        <el-input v-model="row.from" placeholder="起" size="small" style="width:60px" :disabled="row.model_key === '__all__'" />
        <span>-</span>
        <el-input v-model="row.to" placeholder="止" size="small" style="width:60px" :disabled="row.model_key === '__all__'" />
        <el-button size="small" link type="primary" @click="applyRange(row)" :disabled="row.model_key === '__all__'">应用区间</el-button>
        <el-button size="small" link @click="selectAll(row)">全选该品类</el-button>
        <el-button size="small" link @click="row.question_ids=[]">清空</el-button>
        <span class="range-count">已选 {{ row.question_ids.length }}/{{ poolQids(row).length }}</span>
      </div>
      <el-select v-model="row.question_ids" multiple collapse-tags collapse-tags-tooltip
                 :placeholder="row.model_key === '__all__' ? '题区间（all=该品类全部题，每个模型相同）' : '题区间（默认=该品类全部）'"
                 style="width:100%;margin-top:4px">
        <el-option v-for="qid in poolQids(row)" :key="qid" :label="qid" :value="qid" />
      </el-select>
    </div>

    <el-button size="small" @click="addRow">+ 添加模型</el-button>

    <el-form-item label="请求间隔" label-width="100px" style="margin-top:12px">
      <el-slider v-model="delay" :min="3" :max="15" :step="1" show-input />
    </el-form-item>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="success" :loading="downloading" @click="downloadBatch">确定并下载配置</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../composables/useWebSocket'
import { createBatch } from '../api/tasks'

const props = defineProps({
  visible: Boolean,
  taskId: { type: String, required: true },
  taskName: { type: String, default: 'task' },
  totalQids: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'downloaded'])

const allModels = ref([])            // 全部模型（不按登录态过滤），登录态仅作角标显示
const taskQuestions = ref([])        // [{id, category, ...}] 限本任务总题集
const batchRows = ref([])
const delay = ref(8)
const downloading = ref(false)

const categoryOptions = computed(() => {
  const set = []
  for (const q of taskQuestions.value) if (q.category && !set.includes(q.category)) set.push(q.category)
  return set
})

function new_row() { return { model_key: '', category: '全部', question_ids: [], from: '', to: '' } }

async function onOpen() {
  batchRows.value = [new_row()]
  delay.value = 8
  await Promise.all([loadModels(), loadQuestions()])
}

async function loadModels() {
  try {
    const [mRes, wsRes] = await Promise.all([
      apiFetch('/settings/models'),
      apiFetch('/webchat/auth/status'),
    ])
    const models = (mRes.data && (mRes.data.models || mRes.data)) || []
    const ws = wsRes.data || {}
    // 不再按登录态过滤：未登录的模型也能选，首次运行时会弹浏览器引导登录并保存。
    // 登录态仅作为「✓」角标展示，提示用户哪些已可直接跑、哪些会触发首次登录。
    allModels.value = models.map(m => {
      const w = ws[m.key] || {}
      return { ...m, is_logged_in: !!(w.has_auth && w.is_valid) }
    })
    if (!allModels.value.length) ElMessage.warning('未获取到任何模型配置')
  } catch (e) {
    ElMessage.error(`加载模型失败: ${e.message || e}`)
  }
}

async function loadQuestions() {
  try {
    const res = await apiFetch('/questions')
    const all = res.data || []
    const idset = new Set(props.totalQids && props.totalQids.length ? props.totalQids : all.map(q => q.id))
    taskQuestions.value = all.filter(q => idset.has(q.id))
  } catch (e) {
    ElMessage.error(`加载题目失败: ${e.message || e}`)
  }
}

function poolQids(row) {
  if (row.category === '全部') return taskQuestions.value.map(q => q.id)
  return taskQuestions.value.filter(q => q.category === row.category).map(q => q.id)
}
function onCategoryChange(row) {
  row.question_ids = []
  row.from = ''; row.to = ''
}

function qnum(qid) { const m = String(qid).match(/(\d+)/); return m ? parseInt(m[1]) : NaN }
function applyRange(row) {
  const a = parseInt(row.from), b = parseInt(row.to)
  if (isNaN(a) || isNaN(b) || a > b) return ElMessage.warning('请输入有效起止题号')
  row.question_ids = poolQids(row).filter(qid => { const n = qnum(qid); return !isNaN(n) && n >= a && n <= b })
  if (!row.question_ids.length) ElMessage.warning('该区间在所选品类下未匹配到题目')
}
function selectAll(row) { row.question_ids = [...poolQids(row)] }
function addRow() { batchRows.value.push(new_row()) }

async function downloadBatch() {
  const rows = batchRows.value.filter(r => r.model_key)
  if (!rows.length) return ElMessage.warning('请至少添加一个模型')
  const per_model = {}
  for (const r of rows) per_model[r.model_key] = r.question_ids.length ? r.question_ids : [...poolQids(r)]
  // 校验非空
  for (const mk in per_model) if (!per_model[mk].length) return ElMessage.warning(`模型 ${mk} 所选品类下无题目`)

  // 「all」展开成全部模型，每个模型沿用同一题区间；
  // 显式选过的模型优先（不重复）。未登录的模型也展开——首次运行时会弹浏览器引导登录并保存。
  const ALL_KEY = '__all__'
  const explicitKeys = Object.keys(per_model).filter(k => k !== ALL_KEY)
  const finalPerModel = {}
  for (const k of explicitKeys) finalPerModel[k] = per_model[k]
  if (ALL_KEY in per_model) {
    for (const m of allModels.value) {
      if (m.key in finalPerModel) continue
      finalPerModel[m.key] = per_model[ALL_KEY]
    }
  }
  if (!Object.keys(finalPerModel).length) return ElMessage.warning('没有可展开「all」的模型')

  downloading.value = true
  try {
    const res = await createBatch(props.taskId, {
      model_keys: Object.keys(finalPerModel),
      per_model_question_ids: finalPerModel,
      delay: delay.value,
    })
    if (!res?.success) return ElMessage.error(res?.detail || '生成配置失败')
    const cfg = res.data
    const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `task_${props.taskName}_${cfg.batch_id}.json`
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
    ElMessage.success('任务配置已下载，请在本机运行 local_webchat_runner.py --config 该文件')
    emit('downloaded')
    emit('update:visible', false)
  } catch (e) {
    ElMessage.error(`下载失败: ${e.message || e}`)
  } finally { downloading.value = false }
}
</script>

<style scoped>
.batch-row {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 10px;
}
.row-line1 { display: flex; align-items: center; gap: 8px; }
.row-line2 { display: flex; align-items: center; gap: 4px; margin-top: 8px; flex-wrap: wrap; }
.range-hint { font-size: 12px; color: #666; }
.range-count { font-size: 12px; color: #999; margin-left: 4px; }
.pool-hint { font-size: 12px; color: #999; }
</style>
