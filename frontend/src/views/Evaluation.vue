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
            <el-radio value="api">API 模式（通过各模型API调用）</el-radio>
            <el-radio value="webchat">🌐 WebChat 模式（浏览器自动化）</el-radio>
          </el-radio-group>
          <el-alert v-if="form.mode === 'api'" type="info" :closable="false" style="margin-top:8px">
            API 模式通过各模型的API接口提问，支持开启联网搜索（见下方开关）。DeepSeek 官方 API 无内置联网，需额外配置外部搜索服务。
          </el-alert>
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
              <el-tag v-if="form.mode === 'api' && m.has_api_key" type="warning" size="small" style="margin-left:4px">
                {{ m.has_search ? '🔍 支持联网' : '无联网' }}
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

        <el-form-item v-if="form.mode === 'api'" label="联网搜索">
          <el-switch v-model="form.enable_search" active-text="启用" />
          <span style="color:#999;font-size:12px;margin-left:8px">
            开启后各模型将按各自的联网搜索参数提问（通义千问 forced_search、Kimi builtin_function、豆包 enable_search 等）
          </span>
        </el-form-item>

        <el-form-item>
          <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
            <el-button type="primary" @click="startEval" :disabled="!form.model_keys.length || !canStart || form.mode === 'webchat'">
              <el-icon><VideoPlay /></el-icon> 开始评测
            </el-button>
            <el-button v-if="form.mode === 'webchat'" type="success" @click="downloadConfig" :loading="downloadingConfig">
              <el-icon><Download /></el-icon> 下载任务配置（在本地电脑运行）
            </el-button>
            <span v-if="!canStart" style="margin-left:12px;color:#999">
              {{ form.mode === 'api' ? '请至少选择一个已配置 API Key 的模型' : '请至少选择一个已登录的 WebChat 模型' }}
            </span>
            <el-tag v-if="form.mode === 'webchat'" type="info" size="small">
              WebChat 模式需在本地电脑运行，点击「下载任务配置」获取配置文件
            </el-tag>
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 本地 WebChat 结果导入 -->
    <el-card style="margin-top:16px">
      <template #header>
        <div style="display:flex;align-items:center;gap:8px">
          <span>📂 导入本地 WebChat 结果</span>
          <el-tag type="info" size="small">方案A</el-tag>
        </div>
      </template>
      <div style="font-size:13px;color:#666;margin-bottom:12px">
        <strong>完整流程：</strong>在上方「下载任务配置」→ 将 JSON 传到本地电脑
        → 运行 <code>python scripts/local_webchat_runner.py --config task_config.json</code>
        （或交互式 <code>python scripts/webchat_run.py</code>，浏览器弹出后可手动处理验证码/登录）
        → 生成的 .json 结果文件上传到此处。
        适用于 API 无法调通的模型（如文心一言）。
      </div>
      <div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap">
        <!-- 上传区域 -->
        <div style="flex:1;min-width:280px">
          <el-upload
            drag
            :auto-upload="false"
            :on-change="onFileSelect"
            accept=".json"
            :limit="1"
            ref="uploadRef"
          >
            <div style="padding:20px">
              <p style="font-size:14px;color:#999">将本地运行导出的 .json 结果文件拖到此处，或 <em style="color:#409eff">点击选择</em></p>
            </div>
          </el-upload>
        </div>
        <!-- 已选文件信息 + 上传按钮 -->
        <div v-if="selectedFile" style="min-width:240px;flex:0 0 280px">
          <el-card shadow="never" style="background:#f5f7fa">
            <div style="font-size:14px;font-weight:600;margin-bottom:8px">
              📄 {{ selectedFile.name }}
            </div>
            <div style="font-size:12px;color:#999;margin-bottom:4px">
              大小: {{ (selectedFile.size / 1024).toFixed(1) }} KB
            </div>
            <div v-if="filePreview" style="font-size:12px;color:#666;margin-bottom:12px">
              <div>模型: {{ filePreview.models }}</div>
              <div>问题: {{ filePreview.questions }} 个</div>
              <div>结果: {{ filePreview.results }} 条</div>
            </div>
            <el-button
              type="primary"
              size="small"
              :loading="importing"
              @click="uploadResults"
              style="width:100%"
            >
              <el-icon><Upload /></el-icon> 上传到服务器
            </el-button>
          </el-card>
        </div>
      </div>
      <!-- 导入成功提示 -->
      <el-alert
        v-if="importResult"
        :title="importResult"
        type="success"
        :closable="true"
        show-icon
        style="margin-top:12px"
      >
        <template #default>
          <el-button type="primary" link size="small" @click="goToDashboard(importRunId)">查看结果 →</el-button>
        </template>
      </el-alert>
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

      <!-- 操作按钮：终止 / 删除 -->
      <div style="text-align:center;margin-top:16px">
        <el-button v-if="evalStore.progressPercent < 100 && evalStore.runId" type="warning" plain @click="cancelEval">
          <el-icon><CircleClose /></el-icon> 终止评测
        </el-button>
        <el-button v-if="evalStore.progressPercent >= 100 && evalStore.runId" type="danger" plain @click="deleteEval">
          <el-icon><Delete /></el-icon> 删除此评测
        </el-button>
        <el-button v-if="evalStore.progressPercent >= 100" type="primary" @click="viewResult">
          <el-icon><DataAnalysis /></el-icon> 查看结果
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../composables/useWebSocket'
import { useEvalProgressStore } from '../stores/evalProgress'

const router = useRouter()
const evalStore = useEvalProgressStore()

// 本地结果导入状态
const selectedFile = ref(null)
const filePreview = ref(null)
const importResult = ref(null)
const importRunId = ref(null)
const importing = ref(false)
const uploadRef = ref(null)

// 仅保留 form 本地状态（配置项不需要全局共享）
const models = ref([])
const webchatStatus = ref({})
const categories = ref([])
const downloadingConfig = ref(false)
const form = ref({
  name: 'GEO评估',
  model_keys: [],
  categories: [],
  delay: 1.0,
  mode: 'api',
  enable_search: false,
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

async function downloadConfig() {
  // 过滤出已登录的 WebChat 模型
  const selectedAvailable = form.value.model_keys.filter(k =>
    displayModels.value.find(m => m.key === k)?.webchat_status === 'ready'
  )

  if (!selectedAvailable.length) {
    ElMessage.warning('请选择至少一个已登录的 WebChat 模型')
    return
  }

  downloadingConfig.value = true
  try {
    const response = await apiFetch('/evaluations/export-webchat-config', {
      method: 'POST',
      body: JSON.stringify({
        name: form.value.name,
        model_keys: selectedAvailable,
        categories: form.value.categories.length ? form.value.categories : undefined,
        delay: form.value.delay,
        mode: 'webchat',
        enable_search: false,
      }),
    })

    if (!response?.success || !response?.data) {
      throw new Error(response?.message || '生成配置失败')
    }

    const config = response.data
    const filename = `webchat_task_${form.value.name.replace(/\s+/g, '_')}_${Date.now()}.json`

    // 浏览器下载
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    ElMessage.success(`任务配置已下载: ${filename}`)
  } catch (e) {
    ElMessage.error(`下载失败: ${e.message}`)
  } finally {
    downloadingConfig.value = false
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
    enable_search: form.value.enable_search,
  })
}

async function cancelEval() {
  try {
    await ElMessageBox.confirm('确定终止当前评测？已完成的题目数据会保留。', '终止评测', { type: 'warning' })
    await apiFetch(`/evaluations/${evalStore.runId}/cancel`, { method: 'POST' })
    evalStore.reset()
    ElMessage.success('评测已终止')
  } catch { /* cancelled */ }
}

async function deleteEval() {
  try {
    await ElMessageBox.confirm('确定删除此评测及所有结果数据？删除后不可恢复。', '确认删除', { type: 'warning' })
    await apiFetch(`/evaluations/${evalStore.runId}`, { method: 'DELETE' })
    evalStore.reset()
    ElMessage.success('评测已删除')
  } catch { /* cancelled */ }
}

function viewResult() {
  router.push({ path: '/dashboard', query: { run_id: evalStore.runId } })
}

function goToDashboard(runId) {
  router.push({ path: '/dashboard', query: { run_id: runId } })
}

// ── 本地结果导入 ──

function onFileSelect(file) {
  selectedFile.value = file.raw
  importResult.value = null

  // 预览文件内容
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result)
      const analysisResults = data.analysis_results || {}
      const models = Object.keys(analysisResults)
      const totalResults = Object.values(analysisResults).reduce((s, v) => s + v.length, 0)
      filePreview.value = {
        models: models.map(m => {
          const name = analysisResults[m]?.[0]?.model_name || m
          return `${name} (${analysisResults[m]?.length || 0}条)`
        }).join(', '),
        questions: (data.questions || []).length,
        results: totalResults,
      }
    } catch {
      filePreview.value = null
      ElMessage.warning('JSON 文件格式不正确')
    }
  }
  reader.readAsText(file.raw)
}

async function uploadResults() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择文件')
    return
  }

  importing.value = true
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)

    const response = await fetch('/api/evaluations/import-results', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${localStorage.getItem('geo_auth_token') || ''}` },
      body: formData,
    })

    const result = await response.json()

    if (!response.ok || !result.success) {
      throw new Error(result.detail || result.message || '上传失败')
    }

    importResult.value = result.message
    importRunId.value = result.data?.run_id
    ElMessage.success('导入成功！')

    // 清除已选文件
    selectedFile.value = null
    filePreview.value = null
    if (uploadRef.value) uploadRef.value.clearFiles()

  } catch (e) {
    ElMessage.error(`上传失败: ${e.message}`)
  } finally {
    importing.value = false
  }
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