<template>
  <div class="task-detail">
    <el-page-header @back="$router.push('/tasks')" style="margin-bottom:16px">
      <template #content>{{ detail?.task?.name }} — 任务详情</template>
    </el-page-header>

    <el-card v-if="detail" v-loading="loading">
      <div style="display:flex;gap:24px;margin-bottom:16px;flex-wrap:wrap">
        <el-statistic title="总格数" :value="detail.summary.total_cells" />
        <el-statistic title="已完成" :value="detail.summary.done_cells" />
        <el-statistic title="缺失" :value="detail.summary.missing_cells" />
        <div style="min-width:200px">
          <div style="font-size:12px;color:#999;margin-bottom:4px">覆盖率</div>
          <el-progress :percentage="Math.round(detail.summary.coverage_rate*100)" />
        </div>
        <el-button v-if="isAdmin()" type="primary" plain @click="batchDialog=true">
          <el-icon><Plus /></el-icon> 添加批次
        </el-button>
        <el-button v-if="isAdmin()" type="success" @click="importDialog=true">
          <el-icon><Upload /></el-icon> 导入结果
        </el-button>
        <el-button v-if="detail.summary.coverage_rate>0" type="primary" @click="viewResult">
          <el-icon><DataAnalysis /></el-icon> 查看结果
        </el-button>
      </div>

      <!-- 覆盖率矩阵 -->
      <div style="overflow:auto">
        <table class="matrix">
          <thead>
            <tr>
              <th>模型 \\ 问题</th>
              <th v-for="q in detail.questions" :key="q.id" :title="q.question">{{ q.id }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="mk in Object.keys(detail.coverage)" :key="mk">
              <td class="row-head">{{ mk }}</td>
              <td v-for="q in detail.questions" :key="q.id"
                  :class="cellClass(detail.coverage[mk][q.id])"
                  :title="`${mk} / ${q.id}: ${detail.coverage[mk][q.id]||'missing'}`">
                {{ cellMark(detail.coverage[mk][q.id]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 批次列表 -->
      <h4 style="margin-top:20px">下载批次</h4>
      <el-table :data="detail.batches" size="small">
        <el-table-column prop="batch_id" label="批次ID" min-width="200" />
        <el-table-column label="模型">
          <template #default="{ row }">{{ (row.model_keys||[]).join(', ') }}</template>
        </el-table-column>
        <el-table-column label="题数" width="80">
          <template #default="{ row }">{{ (row.question_ids||[]).length }}</template>
        </el-table-column>
        <el-table-column label="状态" width="140">
          <template #default="{ row }">
            <el-tag size="small" :type="batchTagType(row.status)">{{ row.status || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="run_id" min-width="200" />
      </el-table>

      <!-- 本任务行动计划（基于自然题动态生成） -->
      <el-card v-if="detail && detail.summary && detail.summary.coverage_rate > 0"
               shadow="never" class="action-plan-section">
        <div class="action-plan-header">
          <el-icon><List /></el-icon>
          <span>📋 本任务行动计划</span>
          <el-button size="small" link type="primary" @click="$router.push({ path: '/action-plan', query: { task_id: route.params.taskId } })">
            前往完整页 →
          </el-button>
        </div>
        <ActionPlanPanel :task-id="route.params.taskId" embedded />
      </el-card>
    </el-card>

    <!-- 导入对话框 -->
    <el-dialog v-model="importDialog" title="导入本地 runner 结果" width="480px">
      <el-upload drag :auto-upload="false" :on-change="onFile" accept=".json" :limit="1">
        <div style="padding:20px"><p style="color:#999">拖入 local_webchat_runner 产出的 .json</p></div>
      </el-upload>
      <div v-if="file" style="margin-top:12px">{{ file.name }}</div>
      <template #footer>
        <el-button type="primary" :loading="importing" :disabled="!file" @click="doImport">上传并合并</el-button>
      </template>
    </el-dialog>

    <!-- 添加批次（下载配置）对话框 -->
    <BatchDownloadDialog v-model:visible="batchDialog"
      :task-id="route.params.taskId"
      :task-name="detail.task.name"
      :total-qids="detail.task.question_ids"
      @downloaded="onBatchCreated" />
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { isAdmin } from '../composables/useWebSocket'
import { getTask, importResults } from '../api/tasks'
import BatchDownloadDialog from '../components/BatchDownloadDialog.vue'
import ActionPlanPanel from '../components/ActionPlanPanel.vue'

const route = useRoute()
const router = useRouter()
const detail = ref(null)
const loading = ref(false)
const importDialog = ref(false)
const file = ref(null)
const importing = ref(false)
const batchDialog = ref(false)

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const res = await getTask(route.params.taskId)
    if (res?.success) detail.value = res.data
    else if (!silent) ElMessage.error('任务不存在')
  } finally { if (!silent) loading.value = false }
}

// 批次状态轮询：有活跃批次（推送/等待/运行/回传中）时每 8s 静默刷新，
// 状态自动跟进 pushed→awaiting_human→running→imported，无需人工刷新。
const ACTIVE_BATCH_STATUSES = ['pushed', 'awaiting_human', 'running', 'importing']
const POLL_INTERVAL = 8000
let pollTimer = null
function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    const bs = (detail.value && detail.value.batches) || []
    const active = bs.some(b => ACTIVE_BATCH_STATUSES.includes(b.status))
    if (active) {
      await load(true)
    } else {
      stopPolling()
    }
  }, POLL_INTERVAL)
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function cellClass(s) {
  return { done: s === 'done', failed: s === 'failed', missing: !s || s === 'missing' }
}
function cellMark(s) {
  return s === 'done' ? '✓' : s === 'failed' ? '✗' : '·'
}
function onFile(f) { file.value = f.raw }
async function doImport() {
  importing.value = true
  try {
    const res = await importResults(route.params.taskId, file.value)
    if (!res?.success) return ElMessage.error(res?.detail || '导入失败')
    ElMessage.success(res.message || '导入成功')
    importDialog.value = false; file.value = null
    await load()
  } finally { importing.value = false }
}
function viewResult() {
  router.push({ path: '/dashboard', query: { task_id: route.params.taskId } })
}

// 批次创建后启动轮询（静默刷新状态）
async function onBatchCreated() {
  await load()
  startPolling()
}

function batchTagType(status) {
  const map = {
    completed: 'success', imported: 'success',
    config_downloaded: 'info', pushed: 'info',
    awaiting_human: 'warning', running: 'warning', importing: 'warning',
    failed: 'danger', push_failed: 'danger',
  }
  return map[status] || 'info'
}

onMounted(async () => {
  await load()
  // 进入页面时若有活跃批次，直接开始轮询
  const bs = (detail.value && detail.value.batches) || []
  if (bs.some(b => ACTIVE_BATCH_STATUSES.includes(b.status))) startPolling()
})
onBeforeUnmount(() => { stopPolling() })
</script>

<style scoped>
.matrix { border-collapse: collapse; font-size: 12px; }
.matrix th, .matrix td { border: 1px solid #ebeef5; padding: 4px 6px; text-align: center; min-width: 44px; }
.matrix th { background: #f5f7fa; }
.matrix td.row-head { background: #f5f7fa; font-weight: 600; position: sticky; left: 0; }
.matrix td.done { background: #d1fae5; color: #065f46; }
.matrix td.failed { background: #fee2e2; color: #991b1b; }
.matrix td.missing { background: #f3f4f6; color: #9ca3af; }
.action-plan-section { margin-top: 20px; }
.action-plan-header { display: flex; align-items: center; gap: 6px; font-size: 15px; font-weight: 600; margin-bottom: 12px; }
</style>
