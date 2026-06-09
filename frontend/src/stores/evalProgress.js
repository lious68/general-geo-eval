/**
 * UCloud GEO 评测进度全局状态管理
 *
 * 将评测运行状态从 Evaluation.vue 提升为全局 Pinia store，
 * 使得切换页面后仍能看到进度和心跳检测。
 *
 * 关键能力：页面加载时自动检测后端是否有 running 状态的评测，
 * 如果有就恢复进度显示 + 重新连接 WebSocket。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch, getToken } from '../composables/useWebSocket'

export const useEvalProgressStore = defineStore('evalProgress', () => {
  // ── 状态 ──
  const running = ref(false)
  const runId = ref('')
  const progress = ref(0)
  const statusText = ref('')
  const heartbeatActive = ref(false)
  const heartbeatStalled = ref(false)
  const lastUpdateTime = ref('')
  const logs = ref([])
  const evalMode = ref('api')  // 当前评测模式（api / webchat）
  const agentConnected = ref(false)  // 本地 Agent 是否在线

  // 内部引用（不需要 reactive）
  let ws = null
  let heartbeatTimer = null
  let agentPollTimer = null
  let secondsSinceUpdate = 0

  // ── 计算属性 ──
  const progressPercent = computed(() => Math.round(progress.value))

  // ── 心跳检测 ──
  function startHeartbeat() {
    heartbeatActive.value = false
    heartbeatStalled.value = false
    secondsSinceUpdate = 0

    heartbeatTimer = setInterval(() => {
      secondsSinceUpdate += 30
      if (secondsSinceUpdate > 120) {
        heartbeatActive.value = false
        heartbeatStalled.value = true
      }
    }, 30000)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  function onProgressReceived() {
    heartbeatActive.value = true
    heartbeatStalled.value = false
    lastUpdateTime.value = new Date().toLocaleTimeString()
    secondsSinceUpdate = 0
  }

  // ── WebSocket 连接 ──
  function connectWS(runIdValue, onComplete) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    // WebSocket 无法设置自定义 header，将 token 作为 query param 传递
    const token = getToken()
    const url = `${protocol}//${location.host}/api/evaluations/ws/${runIdValue}?token=${encodeURIComponent(token)}`
    ws = new WebSocket(url)

    ws.onopen = () => { /* connected */ }

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)

      if (data.type === 'progress') {
        progress.value = Math.round(data.completed / data.total * 100)
        statusText.value = `${data.current_model} - ${data.current_question}`
        logs.value.unshift({
          time: new Date().toLocaleTimeString(),
          text: `${data.current_model} → ${data.current_question} (${data.completed}/${data.total})`
        })
        onProgressReceived()
      } else if (data.type === 'completed') {
        progress.value = 100
        statusText.value = '评测完成！'
        heartbeatActive.value = false
        heartbeatStalled.value = false
        stopHeartbeat()
        disconnectWS()
        if (onComplete) onComplete('completed')
      } else if (data.type === 'failed') {
        statusText.value = `评测失败: ${data.error || ''}`
        heartbeatActive.value = false
        heartbeatStalled.value = false
        stopHeartbeat()
        disconnectWS()
        if (onComplete) onComplete('failed')
      } else if (data.type === 'cancelled') {
        statusText.value = '评测已中断'
        heartbeatActive.value = false
        heartbeatStalled.value = false
        stopHeartbeat()
        disconnectWS()
        if (onComplete) onComplete('cancelled')
      }
    }

    ws.onclose = () => { /* disconnected */ }
    ws.onerror = () => { /* error */ }
  }

  function disconnectWS() {
    if (ws) {
      ws.close()
      ws = null
    }
  }

  // ── 启动评测（核心 action） ──
  async function startEval(params) {
    // params: { name, model_keys, categories, delay, mode }
    const { name, model_keys, categories, delay, mode } = params

    running.value = true
    runId.value = ''
    progress.value = 0
    statusText.value = '正在启动评测...'
    lastUpdateTime.value = ''
    logs.value = []
    evalMode.value = mode
    startHeartbeat()

    try {
      const res = await apiFetch('/evaluations', {
        method: 'POST',
        body: JSON.stringify({
          name,
          model_keys,
          categories: categories.length ? categories : null,
          delay,
          mode,
        }),
      })
      runId.value = res.data.run_id

      // 建立 WebSocket 连接
      connectWS(res.data.run_id, (result) => {
        if (result === 'completed') {
          // 不自动 reset，让用户看到完成状态
        }
      })
    } catch (e) {
      ElMessage.error(e.message)
      reset()
    }
  }

  // ── 页面加载时恢复运行中评测状态 ──
  async function recoverRunningEval() {
    try {
      const res = await apiFetch('/evaluations?limit=10')
      const runs = res.data || []

      // 查找最近一个 running 状态的评测
      const activeRun = runs.find(r => r.status === 'running')
      if (!activeRun) return

      // 恢复 store 状态
      runId.value = activeRun.id
      running.value = true
      evalMode.value = activeRun.config?.mode || activeRun.mode || 'api'
      progress.value = Math.round(
        (activeRun.completed_questions || 0) / (activeRun.total_questions || 1) * 100
      )
      statusText.value = `恢复评测: ${activeRun.name} (${activeRun.completed_questions}/${activeRun.total_questions})`
      logs.value = [{
        time: new Date().toLocaleTimeString(),
        text: `恢复评测状态: ${activeRun.name} — ${activeRun.completed_questions}/${activeRun.total_questions} 已完成`
      }]
      heartbeatActive.value = true
      heartbeatStalled.value = false
      lastUpdateTime.value = new Date().toLocaleTimeString()
      startHeartbeat()

      // 重新连接 WebSocket
      connectWS(activeRun.id)
    } catch (e) {
      // 静默失败，不影响正常使用
      console.warn('Recover running eval failed:', e)
    }
  }

  // ── 强制中断评测 ──
  async function cancelEval() {
    if (!runId.value) return
    try {
      await apiFetch(`/evaluations/${runId.value}/cancel`, { method: 'POST' })
    } catch (e) {
      ElMessage.error('中断评测失败: ' + e.message)
    }
  }

  // ── 检查评测状态（心跳 stalled 时手动调用） ──
  async function checkStatus() {
    if (!runId.value) return
    try {
      const res = await apiFetch(`/evaluations/${runId.value}`)
      const run = res.data
      if (run.status === 'completed') {
        progress.value = 100
        statusText.value = '评测已完成'
        heartbeatActive.value = false
        heartbeatStalled.value = false
        stopHeartbeat()
        disconnectWS()
      } else if (run.status === 'failed') {
        statusText.value = '评测失败'
        heartbeatActive.value = false
        heartbeatStalled.value = false
        stopHeartbeat()
        disconnectWS()
      } else if (run.status === 'cancelled') {
        statusText.value = '评测已中断'
        heartbeatActive.value = false
        heartbeatStalled.value = false
        stopHeartbeat()
        disconnectWS()
      } else if (run.status === 'running') {
        progress.value = Math.round(
          (run.completed_questions || 0) / (run.total_questions || 1) * 100
        )
        heartbeatActive.value = true
        heartbeatStalled.value = false
        statusText.value = `评测仍在运行 (${run.completed_questions}/${run.total_questions})`
        lastUpdateTime.value = new Date().toLocaleTimeString()
        secondsSinceUpdate = 0
        ElMessage.info(`评测仍在运行，已完成 ${run.completed_questions}/${run.total_questions} 题`)
      } else {
        ElMessage.info(`评测状态: ${run.status}`)
      }
    } catch (e) {
      ElMessage.error('无法获取评测状态: ' + e.message)
    }
  }

  // ── Agent 连接状态轮询 ──
  function startAgentPoll() {
    stopAgentPoll()
    fetchAgentStatus()
    agentPollTimer = setInterval(fetchAgentStatus, 10000)
  }

  function stopAgentPoll() {
    if (agentPollTimer) {
      clearInterval(agentPollTimer)
      agentPollTimer = null
    }
  }

  async function fetchAgentStatus() {
    try {
      const res = await apiFetch('/agent/status')
      agentConnected.value = res.data?.connected || false
    } catch (e) {
      agentConnected.value = false
    }
  }

  // ── 重置状态 ──
  function reset() {
    running.value = false
    runId.value = ''
    progress.value = 0
    statusText.value = ''
    heartbeatActive.value = false
    heartbeatStalled.value = false
    lastUpdateTime.value = ''
    logs.value = []
    evalMode.value = 'api'
    stopHeartbeat()
    stopAgentPoll()
    disconnectWS()
  }

  return {
    running, runId, progress, statusText,
    heartbeatActive, heartbeatStalled, lastUpdateTime,
    logs, evalMode, progressPercent, agentConnected,
    startEval, recoverRunningEval, checkStatus, cancelEval, reset,
    startAgentPoll, stopAgentPoll,
  }
})