<template>
  <div v-loading="loading">
    <el-alert title="按大任务创建时间对比当前得分；这是当前结果对比，不是冻结的历史快照。不同题集、平台或覆盖率会影响可比性。" type="info" :closable="false" />
    <el-checkbox v-model="includePartial" style="margin:16px 0">包含阶段分（未完成采集）</el-checkbox>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-empty v-else-if="!loading && !selected.length" description="暂无符合条件的任务评分；可勾选包含阶段分" />
    <div v-show="selected.length" ref="chartEl" style="height:340px"></div>
    <el-table :data="selected" stripe>
      <el-table-column prop="name" label="评测任务" min-width="180" />
      <el-table-column label="综合分数" width="110"><template #default="{row}"><strong>{{ Number(row.geo_score).toFixed(1) }}</strong></template></el-table-column>
      <el-table-column label="采集覆盖率" width="130"><template #default="{row}">{{ Math.round(row.coverage_rate * 100) }}% <el-tag v-if="row.coverage_rate < 1" size="small" type="warning">阶段分</el-tag></template></el-table-column>
      <el-table-column v-for="m in metrics" :key="m.key" :label="m.label" width="115"><template #default="{row}">{{ row.metric_averages ? (row.metric_averages[m.key] * 100).toFixed(1) + '%' : '—' }}</template></el-table-column>
      <el-table-column label="结果" width="100"><template #default="{row}"><el-button link type="primary" @click="$router.push({path:'/dashboard',query:{task_id:row.id}})">查看结果</el-button></template></el-table-column>
    </el-table>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { listTasks } from '../api/tasks'
const rows=ref([]), loading=ref(true), error=ref(''), includePartial=ref(false), chartEl=ref(null)
const metrics=[{key:'coverage_rate',label:'品牌覆盖率'},{key:'citation_rate',label:'引用率'},{key:'recommendation_rate',label:'TOP3 推荐率'},{key:'sentiment_score',label:'情感值'}]
const selected=computed(()=>rows.value.filter(r=>r.geo_score != null && (includePartial.value || r.coverage_rate >= 1)).slice().sort((a,b)=>String(a.created_at || '').localeCompare(String(b.created_at || ''))))
let chart
function resize(){chart?.resize()}
async function render(){await nextTick(); if(!chartEl.value || !selected.value.length) return; chart ||= echarts.init(chartEl.value); chart.setOption({tooltip:{trigger:'axis'},legend:{bottom:0},grid:{left:45,right:25,top:25,bottom:85},xAxis:{type:'category',data:selected.value.map(r=>r.name+(r.coverage_rate<1?'（阶段）':'')),axisLabel:{rotate:15}},yAxis:{type:'value',min:0,max:100},series:[{name:'综合分数',type:'line',data:selected.value.map(r=>r.geo_score),label:{show:true}},...metrics.map(m=>({name:m.label,type:'line',data:selected.value.map(r=>r.metric_averages ? Number((r.metric_averages[m.key]*100).toFixed(1)) : null)}))]},true);chart.resize()}
watch(selected,render)
onMounted(async()=>{window.addEventListener('resize',resize);try{const response=await listTasks();rows.value=response.data || []}catch{error.value='任务评分加载失败，请刷新重试'}finally{loading.value=false}})
onBeforeUnmount(()=>{window.removeEventListener('resize',resize);chart?.dispose()})
</script>
