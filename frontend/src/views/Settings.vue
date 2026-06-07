<template>
  <div class="settings">
    <h2 class="page-title">⚙️ 系统设置</h2>

    <!-- ModelVerse 一键配置 -->
    <el-card style="margin-bottom:20px">
      <template #header><strong>🚀 ModelVerse 中转平台（推荐）</strong></template>
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        使用 ModelVerse 中转平台，一个 API Key 访问全部 5 个模型，无需单独配置各厂商 API Key
      </el-alert>
      <el-descriptions :column="2" border size="small" style="margin-bottom:16px">
        <el-descriptions-item label="平台地址">{{ mvBaseUrl }}</el-descriptions-item>
        <el-descriptions-item label="API Key">{{ mvKeyPreview }}</el-descriptions-item>
        <el-descriptions-item label="支持模型" :span="2">DeepSeek · 文心一言 · 豆包 · Kimi · 通义千问</el-descriptions-item>
      </el-descriptions>
      <el-button v-if="!useModelverse" type="primary" @click="enableModelverse" :loading="mvLoading">
        <el-icon><Connection /></el-icon> 一键启用 ModelVerse
      </el-button>
      <el-button v-else type="danger" plain @click="disableModelverse" :loading="mvLoading">
        <el-icon><SwitchButton /></el-icon> 关闭 ModelVerse，恢复原厂配置
      </el-button>
      <el-tag v-if="useModelverse" type="success" style="margin-left:12px" size="large">✓ 已启用</el-tag>
    </el-card>

    <!-- 模型API Key配置 -->
    <el-card style="margin-bottom:20px">
      <template #header>
        <strong>🔑 模型 API Key 配置</strong>
        <el-tag v-if="useModelverse" type="warning" style="margin-left:12px" size="small">当前使用 ModelVerse 中转</el-tag>
      </template>
      <el-table :data="models" stripe>
        <el-table-column prop="name" label="模型" width="120" />
        <el-table-column prop="model" label="模型ID" width="180" />
        <el-table-column prop="base_url" label="API地址" min-width="250" />
        <el-table-column label="API Key" width="220">
          <template #default="{ row }">
            <el-input v-model="row._api_key" :type="row._show_key ? 'text' : 'password'" placeholder="输入API Key" size="small">
              <template #append>
                <el-button @click="row._show_key = !row._show_key">
                  <el-icon><component :is="row._show_key ? 'Hide' : 'View'" /></el-icon>
                </el-button>
              </template>
            </el-input>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.has_api_key ? 'success' : 'danger'" size="small">{{ row.has_api_key ? '✓' : '✗' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="saveKey(row)">保存</el-button>
            <el-button size="small" @click="testModel(row.key)">测试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 评分权重 -->
    <el-card>
      <template #header><strong>⚖️ 评分权重配置</strong></template>
      <el-form label-width="120px">
        <el-form-item v-for="(label, key) in weightLabels" :key="key" :label="label">
          <el-slider v-model="weights[key]" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveWeights">保存权重</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../composables/useWebSocket'

const models = ref([])
const useModelverse = ref(false)
const mvBaseUrl = ref('https://api.modelverse.cn/v1')
const mvKeyPreview = ref('')
const mvLoading = ref(false)
const weights = reactive({ coverage_rate: 0.45, mention_rate: 0.0, citation_rate: 0.25, recommendation_rate: 0.20, sentiment_score: 0.10 })
const weightLabels = { coverage_rate: '提及率', mention_rate: '原提及频次', citation_rate: '引用率', recommendation_rate: 'TOP3 推荐率', sentiment_score: '情感值' }

async function loadModels() {
  try {
    const res = await apiFetch('/settings/models')
    const data = res.data || {}
    models.value = (data.models || []).map(m => ({ ...m, _api_key: '', _show_key: false }))
    useModelverse.value = data.use_modelverse || false
    mvBaseUrl.value = data.modelverse_base_url || mvBaseUrl.value
    mvKeyPreview.value = data.modelverse_api_key_preview || ''
  } catch (e) { console.error(e) }
}

async function loadWeights() {
  try {
    const res = await apiFetch('/settings/weights')
    if (res.data) Object.assign(weights, res.data)
  } catch (e) { console.error(e) }
}

async function enableModelverse() {
  mvLoading.value = true
  try {
    const res = await apiFetch('/settings/modelverse/enable', { method: 'POST' })
    ElMessage.success(res.message || 'ModelVerse 已启用')
    await loadModels()
  } catch (e) { ElMessage.error(e.message) }
  finally { mvLoading.value = false }
}

async function disableModelverse() {
  mvLoading.value = true
  try {
    const res = await apiFetch('/settings/modelverse/disable', { method: 'POST' })
    ElMessage.success(res.message || '已恢复原厂配置')
    await loadModels()
  } catch (e) { ElMessage.error(e.message) }
  finally { mvLoading.value = false }
}

async function saveKey(row) {
  try {
    await apiFetch(`/settings/models/${row.key}`, {
      method: 'PUT',
      body: JSON.stringify({ api_key: row._api_key, model: row.model }),
    })
    ElMessage.success(`${row.name} API Key 已保存`)
    await loadModels()
  } catch (e) { ElMessage.error(e.message) }
}

async function testModel(key) {
  try {
    ElMessage.info('正在测试连接...')
    const res = await apiFetch(`/settings/models/${key}/test`, { method: 'POST' })
    if (res.success) {
      ElMessage.success(`连接成功！UCloud提及: ${res.data?.ucloud_mentioned ? '是' : '否'}`)
    } else {
      ElMessage.error(`连接失败: ${res.message}`)
    }
  } catch (e) { ElMessage.error(e.message) }
}

async function saveWeights() {
  try {
    await apiFetch('/settings/weights', { method: 'PUT', body: JSON.stringify(weights) })
    ElMessage.success('权重已保存')
  } catch (e) { ElMessage.error(e.message) }
}

onMounted(() => { loadModels(); loadWeights() })
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
</style>
