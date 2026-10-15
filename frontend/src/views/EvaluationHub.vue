<template>
  <div>
    <h2>评测任务</h2>
    <el-tabs v-model="tab" type="border-card" class="evaluation-tabs">
      <el-tab-pane label="任务列表" name="tasks"><TaskList v-if="tab === 'tasks'" /></el-tab-pane>
      <el-tab-pane label="趋势对比" name="trends"><TaskTrends v-if="tab === 'trends'" /></el-tab-pane>
      <el-tab-pane label="旧版记录" name="legacy">
        <template v-if="tab === 'legacy'"><el-alert title="保留旧 API / WebChat 运行记录；与大任务分开统计，不重复计入任务评分。" type="info" :closable="false" /><History /></template>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TaskList from './TaskList.vue'
import TaskTrends from './TaskTrends.vue'
import History from './History.vue'
const route = useRoute(), router = useRouter()
const tab = computed({get: () => ['trends','legacy'].includes(route.query.tab) ? route.query.tab : 'tasks', set: value => router.replace({path:'/tasks',query:value === 'tasks' ? {} : {tab:value}})})
</script>
<style scoped>
h2 { margin: 0 0 18px; }
.evaluation-tabs :deep(.el-tabs__item) { font-size: 16px; font-weight: 600; padding: 0 28px; height: 48px; }
</style>
