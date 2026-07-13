import { apiFetch } from '../composables/useWebSocket'

export function listTasks(brandId = null) {
  const q = brandId ? `?brand_id=${encodeURIComponent(brandId)}` : ''
  return apiFetch(`/tasks${q}`)
}

export function createTask({ name, categories, question_ids, brand_id }) {
  return apiFetch('/tasks', {
    method: 'POST',
    body: JSON.stringify({ name, categories: categories || null, question_ids: question_ids || null, brand_id: brand_id || null }),
  })
}

export function getTask(taskId) {
  return apiFetch(`/tasks/${taskId}`)
}

export function deleteTask(taskId) {
  return apiFetch(`/tasks/${taskId}`, { method: 'DELETE' })
}

export function createBatch(taskId, { model_keys, per_model_question_ids, delay }) {
  return apiFetch(`/tasks/${taskId}/batches`, {
    method: 'POST',
    body: JSON.stringify({ model_keys, per_model_question_ids, delay }),
  })
}

export function importResults(taskId, file) {
  const formData = new FormData()
  formData.append('file', file)
  return apiFetch(`/tasks/${taskId}/import-results`, { method: 'POST', body: formData })
}

export function importBatchResults(taskId, batchId, file) {
  const formData = new FormData()
  formData.append('file', file)
  return apiFetch(`/tasks/${taskId}/batches/${batchId}/import-results`, { method: 'POST', body: formData })
}

export function getBatchResults(taskId, batchId) {
  return apiFetch(`/tasks/${taskId}/batches/${batchId}/results`)
}

export function repushBatch(taskId, batchId) {
  return apiFetch(`/tasks/${taskId}/batches/${batchId}/repush`, { method: 'POST' })
}

export function getBatchImportLogs(taskId, batchId) {
  return apiFetch(`/tasks/${taskId}/batches/${batchId}/import-logs`)
}

export function getTaskScores(taskId, category = null) {
  const q = category ? `?category=${encodeURIComponent(category)}` : ''
  return apiFetch(`/tasks/${taskId}/scores${q}`)
}

export function getTaskDetails(taskId, modelKey = null) {
  const q = modelKey ? `?model_key=${encodeURIComponent(modelKey)}` : ''
  return apiFetch(`/tasks/${taskId}/details${q}`)
}

export function recalculateTaskScores(taskId) {
  return apiFetch(`/tasks/${taskId}/recalculate`, { method: 'POST' })
}

export function recalculateAllTaskScores() {
  return apiFetch('/tasks/recalculate-all', { method: 'POST' })
}

export function getCitationBreakdown(runId, params = {}) {
  const q = new URLSearchParams()
  if (params.task_id) q.append('task_id', params.task_id)
  if (params.model_key) q.append('model_key', params.model_key)
  const qs = q.toString() ? `?${q.toString()}` : ''
  return apiFetch(`/results/${runId}/citation-breakdown${qs}`)
}

export function getActionPlan(runId, params = {}) {
  // 行动计划诊断（纯只读）。run_id 模式传真实 run_id；task_id 模式 run_id 传 '0' 占位。
  // apiFetch 会自动加 /api 前缀，这里只传 /results/...
  const q = new URLSearchParams()
  if (params.task_id) q.append('task_id', params.task_id)
  if (params.model_key) q.append('model_key', params.model_key)
  const qs = q.toString() ? `?${q.toString()}` : ''
  return apiFetch(`/results/${runId}/action-plan${qs}`)
}
