<template>
  <div class="settings">
    <h2 class="page-title"><el-icon><Setting /></el-icon> 系统设置</h2>

    <!-- 查看者提示 -->
    <el-card v-if="!isAdmin()" style="margin-bottom:20px">
      <el-alert type="info" :closable="false">当前以查看者身份登录，仅可查看数据，无法修改配置</el-alert>
    </el-card>

    <!-- ModelVerse 一键配置 -->
    <el-card v-if="isAdmin()" style="margin-bottom:20px">
      <template #header><strong><el-icon><Promotion /></el-icon> ModelVerse 中转平台（推荐）</strong></template>
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
    <el-card v-if="isAdmin()" style="margin-bottom:20px">
      <template #header>
        <strong><el-icon><Key /></el-icon> 模型 API Key 配置</strong>
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
    <el-card v-if="isAdmin()" style="margin-bottom:20px">
      <template #header><strong><el-icon><Histogram /></el-icon> 评分权重配置</strong></template>
      <el-form label-width="120px">
        <el-form-item v-for="(label, key) in weightLabels" :key="key" :label="label">
          <el-slider v-model="weights[key]" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveWeights">保存权重</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 用户管理 -->
    <el-card v-if="isAdmin()" style="margin-bottom:20px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <strong><el-icon><User /></el-icon> 用户管理</strong>
          <el-button type="primary" size="small" @click="showAddUserDialog = true">添加用户</el-button>
        </div>
      </template>
      <el-table :data="users" stripe>
        <el-table-column prop="username" label="用户名" width="180" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">{{ row.role === 'admin' ? '管理员' : '查看者' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button v-if="row.username !== currentUsername" size="small" type="danger" plain @click="deleteUser(row.id, row.username)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 添加用户对话框 -->
    <el-dialog v-model="showAddUserDialog" title="添加用户" width="400px">
      <el-form label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="newUser.username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="newUser.password" type="password" placeholder="请输入密码" show-password />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="newUser.role" style="width:100%">
            <el-option label="查看者" value="viewer" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddUserDialog = false">取消</el-button>
        <el-button type="primary" @click="addUser" :loading="addUserLoading">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isAdmin, getUsername, apiFetch } from '../composables/useWebSocket'

const models = ref([])
const useModelverse = ref(false)
const mvBaseUrl = ref('https://api.modelverse.cn/v1')
const mvKeyPreview = ref('')
const mvLoading = ref(false)
const weights = reactive({ coverage_rate: 0.45, mention_rate: 0.0, citation_rate: 0.25, recommendation_rate: 0.20, sentiment_score: 0.10 })
const weightLabels = { coverage_rate: '提及率', mention_rate: '原提及频次', citation_rate: '引用率', recommendation_rate: 'TOP3 推荐率', sentiment_score: '情感值' }

// 用户管理
const users = ref([])
const showAddUserDialog = ref(false)
const addUserLoading = ref(false)
const newUser = ref({ username: '', password: '', role: 'viewer' })
const currentUsername = computed(() => getUsername())

async function loadUsers() {
  try {
    const res = await apiFetch('/auth/users')
    users.value = res.data || []
  } catch (e) { console.error(e) }
}

async function addUser() {
  if (!newUser.value.username || !newUser.value.password) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  addUserLoading.value = true
  try {
    await apiFetch('/auth/users', {
      method: 'POST',
      body: JSON.stringify(newUser.value),
    })
    ElMessage.success('用户添加成功')
    showAddUserDialog.value = false
    newUser.value = { username: '', password: '', role: 'viewer' }
    await loadUsers()
  } catch (e) { ElMessage.error(e.message) }
  finally { addUserLoading.value = false }
}

async function deleteUser(id, username) {
  try {
    await ElMessageBox.confirm(`确定要删除用户 "${username}" 吗？`, '确认删除', { type: 'warning' })
    await apiFetch(`/auth/users/${id}`, { method: 'DELETE' })
    ElMessage.success('用户已删除')
    await loadUsers()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}

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

onMounted(() => { loadModels(); loadWeights(); if (isAdmin()) loadUsers() })
</script>

<style scoped>
.page-title { font-size: var(--fs-page-title); margin-bottom: 20px; color: var(--color-text); display: flex; align-items: center; gap: 8px; }
</style>
