<template>
  <div class="action-plan-page">
    <h2 class="page-title"><el-icon><List /></el-icon> 行动计划</h2>
    <p class="page-subtitle">基于每次评测的自然题表现，动态生成「内容该往哪投、用什么结构」的行动清单。引导型题已饱和，所有建议聚焦自然题。</p>

    <!-- 任务选择 -->
    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <div class="filter-item">
          <span class="filter-label">任务：</span>
          <el-select v-model="selectedTaskId" placeholder="选择任务" filterable style="width:340px"
                     :loading="taskLoading" @change="onTaskChange">
            <el-option v-for="t in tasks" :key="t.id"
                       :label="`${t.name}（覆盖 ${Math.round((t.coverage_rate||0)*100)}%）`"
                       :value="t.id" />
          </el-select>
        </div>
        <div class="filter-item">
          <span class="filter-label">模型：</span>
          <el-select v-model="modelKey" style="width:140px" @change="onModelChange">
            <el-option label="全部模型" :value="''" />
            <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
          </el-select>
        </div>
      </div>
    </el-card>

    <el-empty v-if="!tasks.length && !taskLoading"
              description="暂无任务，先去执行评测"
              :image-size="80">
      <el-button type="primary" @click="$router.push('/evaluation')">执行评测</el-button>
    </el-empty>

    <ActionPlanPanel v-else-if="selectedTaskId"
                     :task-id="selectedTaskId"
                     :model-key="modelKey || null" />
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listTasks } from '../api/tasks'
import ActionPlanPanel from '../components/ActionPlanPanel.vue'

const route = useRoute()
const router = useRouter()
const tasks = ref([])
const taskLoading = ref(false)
const selectedTaskId = ref('')
const modelKey = ref('')
const modelOptions = ['deepseek', 'ernie', 'doubao', 'kimi', 'qwen']

async function loadTasks() {
  taskLoading.value = true
  try {
    const res = await listTasks()
    tasks.value = res.data || []
    // 默认选第一个有覆盖率（已有结果）的任务；或 URL ?task_id= 指定
    const fromUrl = route.query.task_id
    if (fromUrl && tasks.value.find(t => t.id === fromUrl)) {
      selectedTaskId.value = fromUrl
    } else {
      const firstWithResults = tasks.value.find(t => (t.coverage_rate || 0) > 0) || tasks.value[0]
      selectedTaskId.value = firstWithResults?.id || ''
    }
  } catch (e) {
    console.error('load tasks failed', e)
  } finally {
    taskLoading.value = false
  }
}

function onTaskChange(id) {
  router.replace({ query: { ...route.query, task_id: id } })
}
function onModelChange() { /* modelKey 是响应式，ActionPlanPanel 会 watch 重载 */ }

onMounted(loadTasks)
watch(() => route.query.task_id, (v) => {
  if (v && v !== selectedTaskId.value) selectedTaskId.value = v
})
</script>

<style scoped>
.action-plan-page { max-width: 1200px; }
.page-title { display: flex; align-items: center; gap: 8px; font-size: var(--fs-page-title); margin-bottom: 4px; }
.page-subtitle { color: var(--color-text-sec); font-size: 13px; margin-bottom: 16px; }
.filter-card { margin-bottom: 16px; }
.filters { display: flex; gap: 24px; flex-wrap: wrap; align-items: center; }
.filter-item { display: flex; align-items: center; gap: 8px; }
.filter-label { font-size: 13px; color: var(--color-text-sec); }
</style>
