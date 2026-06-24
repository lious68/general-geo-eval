import { apiFetch } from '../composables/useWebSocket'

export function listTasks() {
  return apiFetch('/tasks')
}

export function createTask({ name, categories, question_ids }) {
  return apiFetch('/tasks', {
    method: 'POST',
    body: JSON.stringify({ name, categories: categories || null, question_ids: question_ids || null }),
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
