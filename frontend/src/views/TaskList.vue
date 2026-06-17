<template>
  <div class="task-list">
    <h2 class="page-title">🚀 执行评测（任务 → 模型 → 问题）</h2>

    <el-card>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-weight:600">任务列表</span>
        <el-button v-if="isAdmin()" type="primary" @click="openWizard">
          <el-icon><Plus /></el-icon> 新建任务
        </el-button>
      </div>
      <el-table :data="tasks" v-loading="loading" stripe>
        <el-table-column prop="name" label="任务名" min-width="160" />
        <el-table-column label="模型">
          <template #default="{ row }">
            <el-tag v-for="m in row.models" :key="m" size="small" style="margin:2px">{{ m }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="题数" width="80">
          <template #default="{ row }">{{ (row.question_ids||[]).length }}</template>
        </el-table-column>
        <el-table-column label="覆盖率" width="160">
          <template #default="{ row }">
            <el-progress :percentage="Math.round((row.coverage_rate||0)*100)" :status="row.coverage_rate>=1?'success':''" />
            <span style="font-size:12px;color:#999">{{ row.done_cells }}/{{ row.total_cells }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status==='active'?'success':'info'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="$router.push(`/tasks/${row.id}`)">详情</el-button>
            <el-button v-if="isAdmin()" size="small" type="danger" plain @click="onDel(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建向导 -->
    <el-dialog v-model="wizard" title="新建任务" width="640px">
      <el-steps :active="step" finish-status="success" align-center>
        <el-step title="定任务总题集" />
        <el-step title="挂模型 + 题区间" />
      </el-steps>

      <div v-if="step===0" style="margin-top:20px">
        <el-form label-width="100px">
          <el-form-item label="任务名">
            <el-input v-model="form.name" placeholder="GEO评估" />
          </el-form-item>
          <el-form-item label="品类筛选">
            <el-select v-model="form.categories" multiple placeholder="全部品类" style="width:100%">
              <el-option v-for="c in categories" :key="c.name" :label="`${c.name} (${c.count})`" :value="c.name" />
            </el-select>
          </el-form-item>
        </el-form>
      </div>

      <div v-if="step===1" style="margin-top:20px">
        <el-alert type="info" :closable="false" style="margin-bottom:12px">
          任务总题集已固定为 {{ totalQids.length }} 题。下面添加本次要下载的模型与题区间（可后续再补）。
        </el-alert>
        <div v-for="(row, i) in batchRows" :key="i" style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
          <el-select v-model="row.model_key" placeholder="选模型" style="width:160px">
            <el-option v-for="m in readyModels" :key="m.key" :label="m.name" :value="m.key" :disabled="batchRows.some((r,j)=>j!==i&&r.model_key===m.key)" />
          </el-select>
          <el-select v-model="row.question_ids" multiple placeholder="题区间（默认全选）" style="flex:1">
            <el-option v-for="qid in totalQids" :key="qid" :label="qid" :value="qid" />
          </el-select>
          <el-button type="danger" link @click="batchRows.splice(i,1)">删</el-button>
        </div>
        <el-button size="small" @click="batchRows.push({model_key:'',question_ids:[]})">+ 添加模型</el-button>
        <el-form-item label="请求间隔" label-width="100px" style="margin-top:12px">
          <el-slider v-model="form.delay" :min="3" :max="15" :step="1" show-input />
        </el-form-item>
      </div>

      <template #footer>
        <el-button v-if="step>0" @click="step--">上一步</el-button>
        <el-button v-if="step===0" type="primary" @click="createTaskStep">下一步</el-button>
        <el-button v-if="step===1" type="success" @click="downloadBatch">下载任务配置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch, isAdmin } from '../composables/useWebSocket'
import { listTasks, createTask, deleteTask, createBatch } from '../api/tasks'

const tasks = ref([])
const loading = ref(false)
const wizard = ref(false)
const step = ref(0)
const categories = ref([])
const models = ref([])
const webchatStatus = ref({})
const form = ref({ name: 'GEO评估', categories: [], delay: 8 })
const totalQids = ref([])
const createdTaskId = ref('')
const batchRows = ref([{ model_key: '', question_ids: [] }])

const readyModels = ref([])
const displayModels = ref([])

async function load() {
  loading.value = true
  try {
    const res = await listTasks()
    tasks.value = res.data || []
  } finally { loading.value = false }
}

async function openWizard() {
  step.value = 0
  form.value = { name: 'GEO评估', categories: [], delay: 8 }
  totalQids.value = []
  createdTaskId.value = ''
  batchRows.value = [{ model_key: '', question_ids: [] }]
  if (!categories.value.length) await loadConfig()
  wizard.value = true
}

async function loadConfig() {
  const [mRes, cRes, wsRes] = await Promise.all([
    apiFetch('/settings/models'),
    apiFetch('/questions/categories'),
    apiFetch('/webchat/auth/status'),
  ])
  models.value = (mRes.data && (mRes.data.models || mRes.data)) || []
  categories.value = cRes.data || []
  webchatStatus.value = wsRes.data || {}
  displayModels.value = models.value.map(m => {
    const ws = webchatStatus.value[m.key] || {}
    return { ...m, webchat_status: ws.has_auth ? 'ready' : 'no_auth' }
  })
  readyModels.value = displayModels.value.filter(m => m.webchat_status === 'ready')
}

async function createTaskStep() {
  const res = await createTask({ name: form.value.name, categories: form.value.categories.length ? form.value.categories : null })
  if (!res?.success) return ElMessage.error(res?.detail || '建任务失败')
  createdTaskId.value = res.data.id
  totalQids.value = res.data.question_ids || []
  step.value = 1
  if (!readyModels.value.length) await loadConfig()
  ElMessage.success(`任务已创建，总题集 ${totalQids.value.length} 题`)
}

async function downloadBatch() {
  const rows = batchRows.value.filter(r => r.model_key)
  if (!rows.length) return ElMessage.warning('请至少添加一个模型')
  const per_model = {}
  for (const r of rows) per_model[r.model_key] = r.question_ids.length ? r.question_ids : [...totalQids.value]
  const res = await createBatch(createdTaskId.value, { model_keys: Object.keys(per_model), per_model_question_ids: per_model, delay: form.value.delay })
  if (!res?.success) return ElMessage.error(res?.detail || '生成配置失败')
  const cfg = res.data
  const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `task_${form.value.name}_${cfg.batch_id}.json`
  document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
  ElMessage.success('任务配置已下载，请在本机运行 local_webchat_runner.py --config 该文件')
  wizard.value = false
  await load()
}

async function onDel(row) {
  await ElMessageBox.confirm(`确定删除任务「${row.name}」及全部结果？`, '删除', { type: 'warning' })
  await deleteTask(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(async () => { await load(); await loadConfig() })
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
</style>
