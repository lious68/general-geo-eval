<template>
  <div class="evaluation">
    <h2 class="page-title">🚀 执行评测</h2>

    <!-- 评测配置 -->
    <el-card v-if="!evalStore.running">
      <el-form :model="form" label-width="100px">
        <el-form-item label="评测名称">
          <el-input v-model="form.name" placeholder="GEO评估" />
        </el-form-item>

        <el-form-item label="评测模式">
          <el-radio-group v-model="form.mode" @change="onModeChange">
            <el-radio value="api">API 模式（纯文本生成）</el-radio>
            <el-radio value="webchat">🌐 WebChat 模式（联网搜索）</el-radio>
          </el-radio-group>
          <el-alert v-if="form.mode === 'webchat'" type="info" :closable="false" style="margin-top:8px">
            WebChat 模式通过浏览器自动化模拟真实用户在各 AI 官网提问，模型会联网搜索并引用真实来源。需先在「系统设置」配置各网站的登录状态。
          </el-alert>
          <div v-if="form.mode === 'webchat'" style="margin-top:8px">
            <el-tag v-if="evalStore.agentConnected" type="success" effect="dark">
              ✓ 本地 Agent 已连接
            </el-tag>
            <el-alert v-else type="warning" :closable="false" show-icon style="display:inline-block">
              未检测到本地 Agent，请先在本地运行:
              <code style="background:#f5f5f5;padding:2px 6px;border-radius:3px">python scripts/local_agent.py --server 113.31.106.119 --password 你的密码</code>
            </el-alert>
          </div>
        </el-form-item>

        <el-form-item label="选择模型">
          <el-checkbox-group v-model="form.model_keys">
            <el-checkbox v-for="m in displayModels" :key="m.key" :label="m.key">
              {{ m.name }}
              <el-tag v-if="form.mode === 'api'" :type="m.has_api_key ? 'success' : 'danger'" size="small" style="margin-left:4px">
                {{ m.has_api_key ? '✓ API' : '未配置' }}
              </el-tag>
              <el-tag v-if="form.mode === 'webchat'" :type="m.webchat_status === 'ready' ? 'success' : (m.webchat_status === 'no_auth' ? 'danger' : 'warning')" size="small" style="margin-left:4px">
                {{ m.webchat_status === 'ready' ? '✓ 已登录' : (m.webchat_status === 'no_auth' ? '未登录' : m.webchat_status === 'stub' ? '暂不支持' : '已过期') }}
              </el-tag>
            </el-checkbox>
          </el-checkbox-group>
          <div v-if="form.mode === 'api' && !displayModels.some(m => m.has_api_key)" style="margin-top:8px">
            <el-alert type="warning" :closable="false" show-icon>
              所有模型均未配置 API Key，请先到「系统设置」配置 API Key 或启用 ModelVerse 中转
            </el-alert>
          </div>
          <div v-if="form.mode === 'webchat' && !displayModels.some(m => m.webchat_status === 'ready')" style="margin-top:8px">
            <el-alert type="warning" :closable="false" show-icon>
              没有已登录的 WebChat 模型，请先到「系统设置」上传各网站的登录状态文件
            </el-alert>
          </div>
        </el-form-item>

        <el-form-item label="品类筛选">
          <el-select v-model="form.categories" multiple placeholder="全部品类" style="width:100%">
            <el-option v-for="c in categories" :key="c.name" :label="`${c.name} (${c.count})`" :value="c.name" />
          </el-select>
        </el-form-item>

        <el-form-item v-if="form.mode === 'api'" label="请求间隔">
          <el-slider v-model="form.delay" :min="0" :max="5" :step="0.5" show-input />
        </el-form-item>
        <el-form-item v-if="form.mode === 'webchat'" label="请求间隔">
          <el-slider v-model="form.delay" :min="3" :max="15" :step="1" show-input />
          <span style="color:#999;font-size:12px">WebChat 模式建议 8 秒以上，避免被网站限速</span>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="startEval" :disabled="!form.model_keys.length || !canStart || (form.mode === 'webchat' && !evalStore.agentConnected)">
            <el-icon><VideoPlay /></el-icon> 开始评测
          </el-button>
          <span v-if="!canStart" style="margin-left:12px;color:#999">
            {{ form.mode === 'api' ? '请至少选择一个已配置 API Key 的模型' : '请至少选择一个已登录的 WebChat 模型' }}
          </span>
          <span v-if="form.mode === 'webchat' && canStart && !evalStore.agentConnected" style="margin-left:12px;color:#e6a23c">
            请先启动本地 Agent
          </span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 进度显示 -->
    <el-card v-if="evalStore.running">
      <div style="text-align:center;margin-bottom:20px">
        <el-progress type="circle" :percentage="evalStore.progressPercent" :width="120"
          :status="evalStore.progressPercent >= 100 ? 'success' : ''" />
        <div style="margin-top:12px;font-size:16px">{{ evalStore.statusText }}</div>
        <el-tag v-if="evalStore.evalMode === 'webchat'" type="info" style="margin-top:8px">🌐 WebChat 模式</el-tag>
        <div style="margin-top:16px">
          <el-popconfirm title="确定要强制中断评测吗？已完成的题目结果会保留。" confirm-button-text="确定中断" cancel-button-text="取消" @confirm="evalStore.cancelEval()">
            <template #reference>
              <el-button type="danger" :disabled="evalStore.statusText === '评测已中断'">
                <el-icon><CloseBold /></el-icon> 强制中断
              </el-button>
            </template>
          </el-popconfirm>
        </div>
      </div>

      <!-- 活跃状态心跳指示器 -->
      <div class="heartbeat-row">
        <span :class="evalStore.heartbeatActive ? 'heartbeat-dot active' : 'heartbeat-dot inactive'"></span>
        <span v-if="evalStore.heartbeatActive" style="color:#10b981;font-size:13px">进程活跃 · 正在执行中</span>
        <span v-else style="color:#ef4444;font-size:13px">
          {{ evalStore.heartbeatStalled ? '⚠️ 进程可能挂了 · 已超过120秒无更新' : '等待首次进度...' }}
        </span>
        <span style="color:#999;font-size:12px;margin-left:12px">上次更新: {{ evalStore.lastUpdateTime || '—' }}</span>
        <el-button v-if="evalStore.heartbeatStalled" size="small" type="warning" style="margin-left:8px" @click="evalStore.checkStatus()">
          检查状态
        </el-button>
      </div>

      <el-timeline style="margin-top:16px">
        <el-timeline-item v-for="(log, i) in evalStore.logs" :key="i" :timestamp="log.time" placement="top">
          {{ log.text }}
        </el-timeline-item>
      </el-timeline>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../composables/useWebSocket'
import { useEvalProgressStore } from '../stores/evalProgress'

const router = useRouter()
const evalStore = useEvalProgressStore()

// 仅保留 form 本地状态（配置项不需要全局共享）
const models = ref([])
const webchatStatus = ref({})
const categories = ref([])
const form = ref({
  name: 'GEO评估',
  model_keys: [],
  categories: [],
  delay: 1.0,
  mode: 'api',
})

const canStart = computed(() => {
  if (form.value.mode === 'api') {
    return form.value.model_keys.some(k => models.value.find(m => m.key === k)?.has_api_key)
  } else {
    return form.value.model_keys.some(k => displayModels.value.find(m => m.key === k)?.webchat_status === 'ready')
  }
})

const displayModels = computed(() => {
  return models.value.map(m => {
    const ws = webchatStatus.value[m.key] || {}
    let webchat_status = 'no_auth'
    if (ws.has_auth) {
      webchat_status = 'ready'
    }
    return { ...m, webchat_status }
  })
})

async function loadConfig() {
  try {
    const mRes = await apiFetch('/settings/models')
    const mData = mRes.data || {}
    models.value = mData.models || mData || []

    const cRes = await apiFetch('/questions/categories')
    categories.value = cRes.data || []

    const wsRes = await apiFetch('/webchat/auth/status')
    webchatStatus.value = wsRes.data || {}

    onModeChange(form.value.mode)
  } catch (e) { console.error('loadConfig error:', e) }
}

function onModeChange(mode) {
  if (mode === 'api') {
    form.value.delay = 1.0
    form.value.model_keys = models.value.filter(m => m.has_api_key).map(m => m.key)
    evalStore.stopAgentPoll()
  } else {
    form.value.delay = 8
    form.value.model_keys = displayModels.value.filter(m => m.webchat_status === 'ready').map(m => m.key)
    evalStore.startAgentPoll()
  }
}

async function startEval() {
  let selectedAvailable
  if (form.value.mode === 'api') {
    const availableKeys = models.value.filter(m => m.has_api_key).map(m => m.key)
    selectedAvailable = form.value.model_keys.filter(k => availableKeys.includes(k))
  } else {
    selectedAvailable = form.value.model_keys.filter(k =>
      displayModels.value.find(m => m.key === k)?.webchat_status === 'ready'
    )
  }

  if (!selectedAvailable.length) {
    ElMessage.warning(form.value.mode === 'api'
      ? '请选择至少一个已配置API Key的模型'
      : '请选择至少一个已登录的WebChat模型')
    return
  }

  // 调用全局 store 的 startEval
  await evalStore.startEval({
    name: form.value.name,
    model_keys: selectedAvailable,
    categories: form.value.categories,
    delay: form.value.delay,
    mode: form.value.mode,
  })
}

onMounted(loadConfig)
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
.heartbeat-row { display: flex; align-items: center; gap: 8px; padding: 8px 0; }
.heartbeat-dot { width: 10px; height: 10px; border-radius: 50%; }
.heartbeat-dot.active { background: #10b981; animation: pulse 1.5s ease-in-out infinite; }
.heartbeat-dot.inactive { background: #ef4444; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
</style>