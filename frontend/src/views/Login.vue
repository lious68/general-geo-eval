<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <el-icon class="logo-icon"><Aim /></el-icon>
        <h2>UCloud GEO 评估系统</h2>
        <p v-if="isFirstLogin" class="first-login-tip">管理员尚未初始化，请联系服务器管理员</p>
      </div>
      <el-form @submit.prevent="handleLogin">
        <el-form-item>
          <el-input v-model="username" placeholder="用户名" size="large"
            @keyup.enter="handleLogin" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="password" :type="showPwd ? 'text' : 'password'"
            placeholder="请输入密码" size="large"
            @keyup.enter="handleLogin">
            <template #suffix>
              <el-button link @click="showPwd = !showPwd">
                <el-icon><component :is="showPwd ? 'Hide' : 'View'" /></el-icon>
              </el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-button type="primary" size="large" style="width:100%" :loading="loading" :disabled="isFirstLogin" @click="handleLogin">
          登 录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { setToken, setRole, setUsername } from '../composables/useWebSocket'

const router = useRouter()
const username = ref('admin')
const password = ref('')
const showPwd = ref(false)
const loading = ref(false)
const isFirstLogin = ref(false)

onMounted(async () => {
  try {
    const res = await fetch('/api/auth/check')
    const data = await res.json()
    isFirstLogin.value = !data.data?.has_password
  } catch (e) { /* ignore */ }
})

async function handleLogin() {
  if (isFirstLogin.value) return ElMessage.warning('请联系服务器管理员初始化账号')
  if (!username.value) return ElMessage.warning('请输入用户名')
  if (!password.value) return ElMessage.warning('请输入密码')

  loading.value = true
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.value, password: password.value }),
    })
    const data = await res.json()
    if (data.success) {
      setToken(data.data.token)
      setRole(data.data.role || 'viewer')
      setUsername(data.data.username || username.value)
      ElMessage.success(isFirstLogin.value ? '密码设置成功' : '登录成功')
      router.push('/dashboard')
    } else {
      ElMessage.error(data.detail || '登录失败')
    }
  } catch (e) {
    ElMessage.error('网络错误')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page { display: flex; justify-content: center; align-items: center; min-height: 100vh; background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%); }
.login-card { background: var(--color-card); border-radius: var(--radius-lg); padding: 40px; width: 400px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
.login-header { text-align: center; margin-bottom: 30px; }
.login-header .logo-icon { font-size: 48px; color: var(--color-primary); }
.login-header h2 { color: var(--color-text); margin-top: 12px; }
.first-login-tip { color: #e6a23c; font-size: 13px; margin-top: 8px; }
</style>
