<template>
  <div class="task-list">
    <h2 class="page-title"><el-icon><Promotion /></el-icon> 执行评测（任务 → 批次 → 问题）</h2>

    <el-card>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-weight:600">任务列表（点行首 ▸ 展开看批次 / 子任务）</span>
        <div>
          <el-button v-if="isAdmin()" type="warning" plain :loading="recalculating" @click="onRecalcAll">
            <el-icon><Refresh /></el-icon> 重算全部评分
          </el-button>
          <el-button v-if="isAdmin()" type="primary" @click="openWizard">
            <el-icon><Plus /></el-icon> 新建任务
          </el-button>
        </div>
      </div>
      <el-alert type="info" :closable="false" style="margin-bottom:12px">
        一个任务 = 固定总题集。展开任务行即可看到其下<b>批次（子任务）</b>，每个批次 = 一个模型+题区间的下载配置。
        可反复「添加批次」：<b>先 ds、再豆包 1-12、再豆包 13-40、再 kimi、再文心</b>……每批独立下载、本机运行、导入，
        服务器按 (任务,模型,问题) 自动合并，并以任务内全部模型×问题为分母重算 GEO。慢慢补，不必一次全跑。
      </el-alert>

      <el-table :data="tasks" v-loading="loading" stripe row-key="id" @expand-change="onExpand">
        <el-table-column type="expand" width="100">
          <template #header><span class="expand-hdr">展开</span></template>
          <template #default="{ row }">
            <div class="expand-box">
              <div class="expand-head">
                <span style="font-weight:600">
                  评测批次（子任务）· 共 {{ (batchesOf(row.id) || []).length }} 个批次
                </span>
                <div>
                  <el-button v-if="isAdmin()" size="small" type="primary" plain @click="openBatch(row)">
                    <el-icon><Plus /></el-icon> 添加批次
                  </el-button>
                </div>
              </div>

              <el-table :data="batchesOf(row.id) || []" size="small" border
                        row-key="batch_id"
                        v-loading="expandLoading[row.id]" style="width:100%"
                        @expand-change="onBatchExpand">
                <el-table-column type="expand" width="100">
                  <template #header><span class="expand-hdr">展开</span></template>
                  <template #default="{ row: b }">
                    <div class="batch-results-box">
                      <div v-if="batchResultsLoading[b.batch_id]" class="batch-results-tip">加载中…</div>
                      <div v-else-if="!(batchResultsOf(b.batch_id) || []).length" class="batch-results-tip">
                        暂无导入结果，点该批次「导入」上传本地 runner 产出的 JSON
                      </div>
                      <div v-else>
                        <div class="batch-results-head">
                          共 {{ (batchResultsOf(b.batch_id) || []).length }} 条结果（题目 + 模型回答）
                        </div>
                        <div v-for="(r, idx) in (batchResultsOf(b.batch_id) || [])" :key="idx" class="result-card">
                          <div class="result-card-head">
                            <el-tag size="small">{{ r.model_key }}</el-tag>
                            <span class="result-qid">{{ r.question_id }}</span>
                            <el-tag v-if="r.question_category" size="small" type="info" effect="plain">{{ r.question_category }}</el-tag>
                            <span class="result-flags">
                              <el-tag v-if="r.ucloud_mentioned" size="small" type="success">提及</el-tag>
                              <el-tag v-if="r.ucloud_recommended" size="small" type="success">推荐</el-tag>
                              <el-tag v-if="r.has_citation" size="small" type="warning">引用{{ r.citation_count }}</el-tag>
                              <el-tag v-if="r.ucloud_rank" size="small">排名#{{ r.ucloud_rank }}</el-tag>
                              <el-tag size="small" effect="plain">情感{{ r.sentiment_label }}({{ (r.sentiment_score||0).toFixed(2) }})</el-tag>
                            </span>
                          </div>
                          <div class="result-q"><b>题目：</b>{{ r.question_text || '(题目原文缺失)' }}</div>
                          <div v-if="r.error_message" class="result-error"><el-icon><WarningFilled /></el-icon> {{ r.error_message }}</div>
                          <div v-else class="result-ans"><b>模型回答：</b>
                            <pre class="result-pre">{{ r.raw_content || '(空)' }}</pre>
                          </div>
                        </div>
                      </div>
                      <div class="import-logs-box">
                        <div class="import-logs-head">
                          <el-icon><Upload /></el-icon> 导入历史（{{ (batchImportLogsOf(b.batch_id) || []).length }} 次）
                        </div>
                        <div v-if="batchImportLogsLoading[b.batch_id]" class="batch-results-tip">加载中…</div>
                        <div v-else-if="!(batchImportLogsOf(b.batch_id) || []).length" class="batch-results-tip">暂无导入记录</div>
                        <div v-else class="import-log-list">
                          <div v-for="lg in (batchImportLogsOf(b.batch_id) || [])" :key="lg.id" class="import-log-item">
                            <span class="il-time">{{ fmtImportTimeFull(lg.imported_at) }}</span>
                            <el-tag size="small" type="success">{{ lg.results_inserted }} 条</el-tag>
                            <span class="il-file">{{ lg.file_name || '(未命名)' }}</span>
                            <span v-if="lg.file_size != null" class="il-size">{{ fmtFileSize(lg.file_size) }}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </template>
                </el-table-column>
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
                <el-table-column label="结果" width="150">
                  <template #default="{ row: b }">
                    <el-tag v-if="(b.result_count || 0) > 0" size="small" type="success">已导入 {{ b.result_count }}</el-tag>
                    <el-tag v-else size="small" type="info" effect="plain">未导入</el-tag>
                    <div v-if="b.last_import_at" class="last-import-time">{{ fmtImportTime(b.last_import_at) }}</div>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="130">
                  <template #default="{ row: b }">
                    <el-tag size="small" :type="batchTagType(b.status)">{{ b.status || '-' }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="160" fixed="right">
                  <template #default="{ row: b }">
                    <el-button v-if="isAdmin()" size="small" link type="success" @click="openImport(b)">
                      <el-icon><Upload /></el-icon> 导入
                    </el-button>
                    <el-button size="small" link type="primary" @click="downloadBatchConfig(b)">
                      <el-icon><Download /></el-icon> 配置
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
        <el-table-column label="操作" width="320">
          <template #default="{ row }">
            <el-button size="small" @click="$router.push(`/tasks/${row.id}`)">详情</el-button>
            <el-button v-if="row.coverage_rate > 0" size="small" type="primary" @click="viewResult(row)">
              <el-icon><DataAnalysis /></el-icon> 查看结果
            </el-button>
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

    <!-- 导入结果对话框（批次级） -->
    <el-dialog v-model="importDialog" :title="`导入结果到批次「${importBatch ? importBatch.batch_id : ''}」`" width="480px">
      <el-upload drag :auto-upload="false" :on-change="onFile" accept=".json" :limit="1">
        <div style="padding:20px"><p style="color:#999">拖入该批次对应 local_webchat_runner 产出的 .json</p></div>
      </el-upload>
      <div v-if="importFile" style="margin-top:12px">{{ importFile.name }}</div>
      <template #footer>
        <el-button @click="importDialog=false">取消</el-button>
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
import { listTasks, createTask, deleteTask, getTask, importBatchResults, getBatchResults, getBatchImportLogs, recalculateAllTaskScores } from '../api/tasks'
import BatchDownloadDialog from '../components/BatchDownloadDialog.vue'

const router = useRouter()
const tasks = ref([])
const loading = ref(false)
const wizard = ref(false)
const form = ref({ name: 'GEO评估' })
const creating = ref(false)
const recalculating = ref(false)

// 批次（子任务）懒加载
const batchesMap = ref({})
const expandLoading = ref({})

// 添加批次对话框
const batchDialog = ref(false)
const batchTaskId = ref('')
const batchTaskName = ref('')
const batchTotalQids = ref([])

// 导入结果（批次级）
const importDialog = ref(false)
const importFile = ref(null)
const importing = ref(false)
const importBatch = ref(null)   // { task_id, batch_id }
// 批次展开结果（懒加载）
const batchResultsMap = ref({})       // batch_id -> 结果数组
const batchResultsLoading = ref({})   // batch_id -> bool

const batchImportLogsMap = ref({})       // batch_id -> 日志数组
const batchImportLogsLoading = ref({})   // batch_id -> bool

function batchImportLogsOf(batchId) { return batchImportLogsMap.value[batchId] }


function fmtImportTime(s) {
  if (!s) return ''
  const d = new Date(String(s).replace(' ', 'T'))
  if (isNaN(d.getTime())) return String(s)
  const p = n => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function fmtImportTimeFull(s) {
  if (!s) return ''
  const d = new Date(String(s).replace(' ', 'T'))
  if (isNaN(d.getTime())) return String(s)
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
function fmtFileSize(n) {
  if (!n && n !== 0) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

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

function batchResultsOf(batchId) { return batchResultsMap.value[batchId] }

async function onBatchExpand(row, expandedRows) {
  // row = batch；只在展开时懒加载该批次结果
  const opened = expandedRows.some(r => r.batch_id === row.batch_id)
  if (!opened) return
  await loadBatchResults(row)
}

async function loadBatchResults(b) {
  const taskId = b.task_id
  const batchId = b.batch_id
  if (!taskId || !batchId) return
  batchResultsLoading.value = { ...batchResultsLoading.value, [batchId]: true }
  try {
    const [res, logs] = await Promise.all([
      getBatchResults(taskId, batchId),
      getBatchImportLogs(taskId, batchId).catch(() => null),
    ])
    if (res?.success) batchResultsMap.value = { ...batchResultsMap.value, [batchId]: res.data || [] }
    if (logs?.success) batchImportLogsMap.value = { ...batchImportLogsMap.value, [batchId]: logs.data || [] }
  } catch (e) {
    ElMessage.error(`加载批次结果失败: ${e.message || e}`)
  } finally {
    batchResultsLoading.value = { ...batchResultsLoading.value, [batchId]: false }
  }
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

function openImport(b) {
  // b = batch 行；pin 到该批次
  importBatch.value = { task_id: b.task_id, batch_id: b.batch_id }
  importFile.value = null
  importDialog.value = true
}
function onFile(f) { importFile.value = f.raw }
async function doImport() {
  if (!importBatch.value) return
  const { task_id, batch_id } = importBatch.value
  importing.value = true
  try {
    const res = await importBatchResults(task_id, batch_id, importFile.value)
    if (!res?.success) return ElMessage.error(res?.detail || '导入失败')
    ElMessage.success(res.message || '导入成功')
    importDialog.value = false
    importFile.value = null
    await load()
    await refreshBatches(task_id)
    // 若该批次已展开，刷新其结果
    await loadBatchResults({ task_id, batch_id })
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

async function onRecalcAll() {
  await ElMessageBox.confirm(
    '将按当前已导入结果重算全部任务的 GEO 评分（提及率/引用率/TOP3推荐率等）。用于评分口径修复后刷新历史数据。继续？',
    '重算全部评分', { type: 'warning' })
  recalculating.value = true
  try {
    const res = await recalculateAllTaskScores()
    if (!res?.success) return ElMessage.error(res?.detail || '重算失败')
    ElMessage.success(res.message || '重算完成')
    await load()
  } catch (e) {
    ElMessage.error(`重算失败: ${e.message || e}`)
  } finally { recalculating.value = false }
}

onMounted(async () => { await load() })
</script>

<style scoped>
.page-title { font-size: var(--fs-page-title); margin-bottom: 20px; color: var(--color-text); display: flex; align-items: center; gap: 8px; }
/* 展开箭头 + "展开"表头：加粗 + 蓝色系，hover/展开转深蓝（旋转由 EP 原生处理） */
.expand-hdr { color: var(--el-color-primary); font-size: 12px; font-weight: 700; white-space: nowrap; }
:deep(.el-table__expand-icon) {
  font-size: 18px;
  color: var(--el-color-primary);
  /* SVG chevron 不吃 font-weight，用 scale 放大+加粗描边等效 */
  transform: scale(1.18);
  transition: color .2s ease;
}
:deep(.el-table__expand-icon .el-icon) { font-size: 18px; stroke: currentColor; stroke-width: 0.6; }
:deep(.el-table__expand-icon:hover) { color: var(--el-color-primary-dark-2); }
:deep(.el-table__expand-icon--expanded) { color: var(--el-color-primary-dark-2); }
.expand-box { padding: 8px 16px 16px 48px; }
.expand-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.empty-tip { color: #bbb; font-size: 13px; padding: 12px 0; }
.model-qids { display: flex; align-items: baseline; gap: 6px; line-height: 1.7; }
.model-qids .qid-list { font-size: 12px; color: #555; word-break: break-all; }
.batch-results-box { padding: 8px 16px 8px 24px; background: #fafbfc; }
.batch-results-tip { color: #bbb; font-size: 13px; padding: 8px 0; }
.batch-results-head { font-size: 13px; color: #555; margin-bottom: 8px; font-weight: 600; }
.result-card { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px; margin-bottom: 10px; background: #fff; }
.result-card-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.result-qid { font-family: monospace; font-size: 13px; font-weight: 600; }
.result-flags { display: inline-flex; gap: 4px; flex-wrap: wrap; margin-left: auto; }
.result-q { font-size: 13px; color: #333; margin-bottom: 6px; }
.result-ans { font-size: 13px; color: #333; }
.result-error { color: #c0392b; font-size: 13px; display: flex; align-items: center; gap: 4px; }
.result-pre { white-space: pre-wrap; word-break: break-word; background: #f6f8fa; border-radius: 4px; padding: 8px; max-height: 240px; overflow: auto; margin: 4px 0 0; font-size: 12px; line-height: 1.5; }
.last-import-time { font-size: 11px; color: #a8abb2; margin-top: 2px; }
.import-logs-box { margin-top: 10px; padding-top: 8px; border-top: 1px dashed #ebeef5; }
.import-logs-head { font-size: 13px; color: #555; font-weight: 600; margin-bottom: 8px; }
.import-log-list { display: flex; flex-direction: column; gap: 6px; }
.import-log-item { display: flex; align-items: center; gap: 8px; font-size: 12px; flex-wrap: wrap; }
.il-time { font-family: monospace; color: #333; }
.il-file { color: #888; }
.il-size { color: #bbb; }
</style>
