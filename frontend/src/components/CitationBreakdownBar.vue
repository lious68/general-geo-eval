<template>
  <div class="citation-breakdown-bar">
    <div v-if="loading" class="bar-loading">加载中...</div>
    <div v-else-if="breakdown && breakdown.total > 0">
      <div class="bar-container">
        <div
          v-if="breakdown.pretraining > 0"
          class="bar-segment pretraining"
          :style="{ width: getPercentage(breakdown.pretraining) + '%' }"
          :title="`预训练: ${breakdown.pretraining}`"
        ></div>
        <div
          v-if="breakdown.user_provided > 0"
          class="bar-segment user-provided"
          :style="{ width: getPercentage(breakdown.user_provided) + '%' }"
          :title="`用户提供: ${breakdown.user_provided}`"
        ></div>
        <div
          v-if="breakdown.web_search > 0"
          class="bar-segment web-search"
          :style="{ width: getPercentage(breakdown.web_search) + '%' }"
          :title="`网络搜索: ${breakdown.web_search}`"
        ></div>
        <div
          v-if="breakdown.undetected > 0"
          class="bar-segment undetected"
          :style="{ width: getPercentage(breakdown.undetected) + '%' }"
          :title="`未检测: ${breakdown.undetected}`"
        ></div>
      </div>
      <div v-if="showLegend" class="legend">
        <span class="legend-item">
          <span class="legend-color pretraining"></span>
          预训练 ({{ breakdown.pretraining }})
        </span>
        <span class="legend-item">
          <span class="legend-color user-provided"></span>
          用户提供 ({{ breakdown.user_provided }})
        </span>
        <span class="legend-item">
          <span class="legend-color web-search"></span>
          网络搜索 ({{ breakdown.web_search }})
        </span>
        <span class="legend-item">
          <span class="legend-color undetected"></span>
          未检测 ({{ breakdown.undetected }})
        </span>
      </div>
    </div>
    <div v-else class="bar-empty">无引用数据</div>
  </div>
</template>

<script>
import { ref, watch, onMounted } from 'vue'
import { apiFetch } from '../composables/useWebSocket'

export default {
  name: 'CitationBreakdownBar',
  props: {
    runId: {
      type: String,
      default: '0'
    },
    taskId: {
      type: String,
      default: null
    },
    modelKey: {
      type: String,
      default: null
    },
    showLegend: {
      type: Boolean,
      default: false
    }
  },
  setup(props) {
    const breakdown = ref(null)
    const loading = ref(false)

    async function loadBreakdown() {
      loading.value = true
      try {
        let url = `/results/${props.runId}/citation-breakdown`
        const params = []
        if (props.taskId) params.push(`task_id=${encodeURIComponent(props.taskId)}`)
        if (props.modelKey) params.push(`model_key=${encodeURIComponent(props.modelKey)}`)
        if (params.length) url += '?' + params.join('&')

        const res = await apiFetch(url)
        breakdown.value = res.data || null
      } catch (e) {
        console.error('Failed to load citation breakdown:', e)
        breakdown.value = null
      } finally {
        loading.value = false
      }
    }

    function getPercentage(count) {
      if (!breakdown.value || breakdown.value.total === 0) return 0
      return (count / breakdown.value.total) * 100
    }

    watch(() => [props.runId, props.taskId, props.modelKey], loadBreakdown, { immediate: true })

    return { breakdown, loading, getPercentage }
  }
}
</script>

<style scoped>
.citation-breakdown-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bar-container {
  display: flex;
  height: 24px;
  border-radius: 4px;
  overflow: hidden;
  background-color: #f0f0f0;
}

.bar-segment {
  transition: width 0.3s ease;
  cursor: pointer;
}

.bar-segment:hover {
  opacity: 0.8;
}

.bar-segment.pretraining {
  background-color: #409eff;
}

.bar-segment.user-provided {
  background-color: #67c23a;
}

.bar-segment.web-search {
  background-color: #e6a23c;
}

.bar-segment.undetected {
  background-color: #909399;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-color {
  width: 12px;
  height: 12px;
  border-radius: 2px;
}

.legend-color.pretraining {
  background-color: #409eff;
}

.legend-color.user-provided {
  background-color: #67c23a;
}

.legend-color.web-search {
  background-color: #e6a23c;
}

.legend-color.undetected {
  background-color: #909399;
}
</style>
