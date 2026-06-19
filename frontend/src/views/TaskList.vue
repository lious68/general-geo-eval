<template>
  <div class="task-list">
    <h2 class="page-title">🚀 执行评测（任务 → 批次 → 问题）</h2>

    <el-card>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-weight:600">任务列表（点行首 ▸ 展开看批次 / 子任务）</span>
        <el-button v-if="isAdmin()" type="primary" @click="openWizard">
          <el-icon><Plus /></el-icon> 新建任务
        </el-button>
      </div>
      <el-alert type="info" :closable="false" style="margin-bottom:12px">
        一个任务 = 固定总题集。展开任务行即可看到其下<b>批次（子任务）</b>，每个批次 = 一个模型+题区间的下载配置。
        可反复「添加批次」：<b>先 ds、再豆包 1-12、再豆包 13-40、再 kimi、再文心</b>……每批独立下载、本机运行、导入，
        服务器按 (任务,模型,问题) 自动合并，并以任务内全部模型×问题为分母重算 GEO。慢慢补，不必一次全跑。
      </el-alert>

      <el-table :data="tasks" v-loading="loading" stripe row-key="id" @expand-change="onExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-box">
              <div class="expand-head">
                <span style="font-weight:600">
                  评测批次（子任务）· 共 {{ (batchesOf(row.id) || []).length }} 个批次
                </span>
                <div>
                  <el-button v-if="isAdmin()" size="small" type="primary" plain @click="openBatch(row)">
                    ➕ 添加批次
                  </el-button>
                  <el-button v-if="isAdmin()" size="small" type="success" @click="openImport(row)">
                    📥 导入结果
                  </el-button>
                  <el-button v-if="row.coverage_rate > 0" size="small" type="primary" @click="viewResult(row)">
                    📊 查看结果
                  </el-button>
                </div>
              </div>

              <el-table :data="batchesOf(row.id) || []" size="small" border
                        v-loading="expandLoading[row.id]" style="width:100%">
                <el-table-column label="批次 / run_id" min-width="210">
                  <template #default="{ row: b }">
                    <span style="font-family:monospace;font-size:12px">{{ b.batch_id }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="模型 × 已选题号" min-width="340">
                  <template #default="{ row: b }">
                    <div v-for="mk in batchModels(b)" :key="mk" class="model-qids">
                      <el-tag size="small">{{ mk }}</el-tag>
                      <span class="qid-list" :title="modelQids(b, mk).join(', ')">
                        {{ modelQidsText(b, mk) }}
                      </span>
                    </div>
                    <span v-if="!batchModels(b).length" style="color:#bbb;font-size:12px">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="题数" width="70">
                  <template #default="{ row: b }">{{ (b.question_ids || []).length }}</template>
                </el-table-column>
                <el-table-column label="状态" width="140">
                  <template #default="{ row: b }">
                    <el-tag size="small" :type="batchTagType(b.status)">{{ b.status || '-' }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="110" fixed="right">
                  <template #default="{ row: b }">
                    <el-button size="small" link type="primary" @click="downloadBatchConfig(b)">
                      ⬇ 下载配置
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>

              <div v-if="!expandLoading[row.id] && !(batchesOf(row.id) || []).length" class="empty-tip">
                暂无批次，点「添加批次」下载第一个配置
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="name" label="任务名" min-width="150" />
        <el-table-column label="模型">
          <template #default="{ row }">
            <el-tag v-for="m in row.models" :key="m" size="small" style="margin:2px">{{ m }}</el-tag>
            <span v-if="!(row.models || []).length" style="color:#bbb;font-size:12px">尚未添加批次</span>
          </template>
        </el-table-column>
        <el-table-column label="总题数" width="80">
          <template #default="{ row }">{{ (row.question_ids || []).length }}</template>
        </el-table-column>
        <el-table-column label="覆盖率" width="170">
          <template #default="{ row }">
            <el-progress :percentage="Math.round((row.coverage_rate || 0) * 100)"
                         :status="row.coverage_rate >= 1 ? 'success' : ''" />
            <span style="font-size:12px;color:#999">{{ row.done_cells }}/{{ row.total_cells }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250">
          <template #default="{ row }">
            <el-button size="small" @click="$router.push(`/tasks/${row.id}`)">详情</el-button>
            <el-button v-if="isAdmin()" size="small" type="primary" plain @click="openBatch(row)">添加批次</el-button>
            <el-button v-if="isAdmin()" size="small" type="danger" plain @click="onDel(row)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建任务向导：只建任务（= GEO 计算的总集/范围），不再选品类 -->
    <el-dialog v-model="wizard" title="新建任务" width="520px">
      <el-form label-width="100px">
        <el-form-item label="任务名">
          <el-input v-model="form.name" placeholder="GEO评估" />
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" style="margin-top:4px">
        任务 = <b>GEO 计算的总集/范围</b>（默认全部题）。这一步<b>只建任务</b>，
        建好后回列表展开该任务，点「添加批次」再建子任务（模型 × 品类 × 题号区间）。
      </el-alert>
      <template #footer>
        <el-button @click="wizard=false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createTaskStep">创建任务</el-button>
      </template>
    </el-dialog>

    <!-- 下载配置（添加批次）对话框 -->
    <BatchDownloadDialog v-model:visible="batchDialog"
      :task-id="batchTaskId" :task-name="batchTaskName" :total-qids="batchTotalQids"
      @downloaded="onBatchDownloaded" />

    <!-- 导入结果对话框 -->
    <el-dialog v-model="importDialog" :title="`导入结果到「${batchTaskName}」`" width="480px">
      <el-upload drag :auto-upload="false" :on-change="onFile" accept=".json" :limit="1">
        <div style="padding:20px"><p style="color:#999">拖入 local_webchat_runner 产出的 .json</p></div>
      </el-upload>
      <div v-if="importFile" style="margin-top:12px">{{ importFile.name }}</div>
      <template #footer>
        <el-button type="primary" :loading="importing" :disabled="!importFile" @click="doImport">上传并合并</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch, isAdmin } from '../composables/useWebSocket'
import { listTasks, createTask, deleteTask, getTask, importResults } from '../api/tasks'
import BatchDownloadDialog from '../components/BatchDownloadDialog.vue'

const router = useRouter()
const tasks = ref([])
const loading = ref(false)
const wizard = ref(false)
const form = ref({ name: 'GEO评估' })
const creating = ref(false)

// 批次（子任务）懒加载
const batchesMap = ref({})
const expandLoading = ref({})

// 添加批次对话框
const batchDialog = ref(false)
const batchTaskId = ref('')
const batchTaskName = ref('')
const batchTotalQids = ref([])

// 导入结果
const importDialog = ref(false)
const importFile = ref(null)
const importing = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await listTasks()
    tasks.value = res.data || []
  } finally { loading.value = false }
}

function batchesOf(id) { return batchesMap.value[id] }

async function onExpand(row, expandedRows) {
  const opened = expandedRows.some(r => r.id === row.id)
  if (!opened) return
  if (batchesMap.value[row.id]) return
  expandLoading.value = { ...expandLoading.value, [row.id]: true }
  try {
    const res = await getTask(row.id)
    if (res?.success) batchesMap.value[row.id] = res.data.batches || []
  } catch (e) {
    ElMessage.error(`加载批次失败: ${e.message || e}`)
  } finally {
    expandLoading.value = { ...expandLoading.value, [row.id]: false }
  }
}

async function refreshBatches(taskId) {
  try {
    const res = await getTask(taskId)
    if (res?.success) batchesMap.value = { ...batchesMap.value, [taskId]: res.data.batches || [] }
  } catch (e) { /* ignore */ }
}

function openBatch(row) {
  batchTaskId.value = row.id
  batchTaskName.value = row.name
  batchTotalQids.value = row.question_ids || []
  batchDialog.value = true
}

async function onBatchDownloaded() {
  await load()
  if (batchTaskId.value) await refreshBatches(batchTaskId.value)
}

async function downloadBatchConfig(b) {
  const taskId = b.task_id
  const batchId = b.batch_id
  if (!taskId || !batchId) return ElMessage.error('批次信息缺失')
  try {
    const res = await apiFetch(`/tasks/${taskId}/batches/${batchId}/config`)
    if (!res?.success) return ElMessage.error(res?.detail || '获取配置失败')
    const cfg = res.data
    const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `task_${cfg.task_name || taskId}_${batchId}.json`
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
    ElMessage.success('配置已下载，可用 local_webchat_runner.py --config 该文件 重跑')
  } catch (e) {
    ElMessage.error(`下载失败: ${e.message || e}`)
  }
}

function openImport(row) {
  batchTaskId.value = row.id
  batchTaskName.value = row.name
  importFile.value = null
  importDialog.value = true
}
function onFile(f) { importFile.value = f.raw }
async function doImport() {
  importing.value = true
  try {
    const res = await importResults(batchTaskId.value, importFile.value)
    if (!res?.success) return ElMessage.error(res?.detail || '导入失败')
    ElMessage.success(res.message || '导入成功')
    importDialog.value = false
    importFile.value = null
    await load()
    await refreshBatches(batchTaskId.value)
  } finally { importing.value = false }
}

function viewResult(row) {
  router.push({ path: '/dashboard', query: { task_id: row.id } })
}

function qnum(qid) {
  const m = String(qid).match(/(\d+)/)
  return m ? parseInt(m[1]) : NaN
}
function fmtRange(qids) {
  if (!qids || !qids.length) return '-'
  const nums = qids.map(qnum).filter(n => !isNaN(n)).sort((a, b) => a - b)
  if (!nums.length) return qids.length + ' 题'
  let contiguous = true
  for (let i = 1; i < nums.length; i++) if (nums[i] - nums[i - 1] !== 1) { contiguous = false; break }
  const pad = n => 'q' + String(n).padStart(3, '0')
  if (contiguous) return `${pad(nums[0])} ~ ${pad(nums[nums.length - 1])} (${nums.length}题)`
  return `${pad(nums[0])} 等 ${nums.length} 题`
}
// 取某批次的模型列表（优先 v2 config.units，回退 model_keys）
function batchModels(b) {
  const units = b.config && b.config.units
  if (units && units.length) return units.map(u => u.model_key)
  return b.model_keys || []
}
// 取某批次某模型已选的具体题号（v2 config.units > per_model_question_ids > 整批 question_ids 兜底）
function modelQids(b, mk) {
  const cfg = b.config || {}
  const units = cfg.units || []
  const u = units.find(x => x.model_key === mk)
  if (u && u.question_ids && u.question_ids.length) return u.question_ids
  const pm = cfg.per_model_question_ids
  if (pm && pm[mk] && pm[mk].length) return pm[mk]
  return b.question_ids || []
}
// 题号展示：尽量合并成区间，否则枚举前几个+省略
function modelQidsText(b, mk) {
  const qids = modelQids(b, mk)
  if (!qids.length) return '(未选题)'
  const nums = qids.map(qnum).filter(n => !isNaN(n)).sort((a, b) => a - b)
  if (!nums.length) return qids.length + ' 题'
  // 合并连续区间
  const parts = []
  let start = nums[0], prev = nums[0]
  for (let i = 1; i < nums.length; i++) {
    if (nums[i] === prev + 1) { prev = nums[i]; continue }
    parts.push(start === prev ? `${start}` : `${start}-${prev}`)
    start = nums[i]; prev = nums[i]
  }
  parts.push(start === prev ? `${start}` : `${start}-${prev}`)
  let txt = parts.join(',')
  if (txt.length > 42) txt = txt.slice(0, 42) + `… (+${nums.length}题)`
  else txt += ` (${nums.length}题)`
  return txt
}
function fmtModelRange(b, mk) {
  return fmtRange(modelQids(b, mk))
}
function batchTagType(status) {
  if (status === 'completed') return 'success'
  if (status === 'config_downloaded') return 'info'
  if (status === 'running') return 'warning'
  if (status === 'failed') return 'danger'
  return ''
}

async function openWizard() {
  form.value = { name: 'GEO评估' }
  wizard.value = true
}

async function createTaskStep() {
  creating.value = true
  try {
    const res = await createTask({ name: form.value.name })
    if (!res?.success) return ElMessage.error(res?.detail || '建任务失败')
    const task = res.data
    ElMessage.success(`任务已创建（总题集 ${task.question_ids.length} 题）。展开该任务，点「添加批次」创建子任务（模型×品类×题号区间）`)
    wizard.value = false
    await load()
  } catch (e) {
    ElMessage.error(`建任务失败: ${e.message || e}`)
  } finally { creating.value = false }
}

async function onDel(row) {
  await ElMessageBox.confirm(`确定删除任务「${row.name}」及全部结果？`, '删除', { type: 'warning' })
  try {
    const res = await deleteTask(row.id)
    if (!res?.success) return ElMessage.error(res?.detail || '删除失败')
    ElMessage.success('已删除')
    delete batchesMap.value[row.id]
    await load()
  } catch (e) {
    ElMessage.error(`删除失败: ${e.message || e}`)
  }
}

onMounted(async () => { await load() })
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
.expand-box { padding: 8px 16px 16px 48px; }
.expand-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.empty-tip { color: #bbb; font-size: 13px; padding: 12px 0; }
.model-qids { display: flex; align-items: baseline; gap: 6px; line-height: 1.7; }
.model-qids .qid-list { font-size: 12px; color: #555; word-break: break-all; }
</style>
