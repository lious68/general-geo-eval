<template>
  <div class="history">
    <h2 class="page-title">🕐 历史记录</h2>
    <el-card>
      <el-table :data="runs" stripe>
        <el-table-column prop="id" label="评测ID" width="200" />
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status==='completed'?'success':row.status==='running'?'warning':'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="120">
          <template #default="{ row }">{{ row.completed_questions }}/{{ row.total_questions }}</template>
        </el-table-column>
        <el-table-column prop="started_at" label="开始时间" width="180" />
        <el-table-column prop="completed_at" label="完成时间" width="180" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="viewResult(row.id)" :disabled="row.status!=='completed'">查看</el-button>
            <el-button size="small" type="danger" @click="deleteRun(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../composables/useWebSocket'

const router = useRouter()
const runs = ref([])

async function loadRuns() {
  try {
    const res = await apiFetch('/evaluations')
    runs.value = res.data || []
  } catch (e) { console.error(e) }
}

function viewResult(runId) {
  router.push({ path: '/dashboard', query: { run_id: runId } })
}

async function deleteRun(runId) {
  try {
    await ElMessageBox.confirm('确定删除此评测记录？', '确认', { type: 'warning' })
    await apiFetch(`/evaluations/${runId}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await loadRuns()
  } catch (e) { /* cancelled */ }
}

onMounted(loadRuns)
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
</style>
