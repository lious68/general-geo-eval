<template>
  <el-container class="app-container">
    <el-aside width="220px" class="sidebar">
      <div class="logo">
        <span class="logo-icon">🎯</span>
        <span class="logo-text">UCloud GEO</span>
      </div>
      <el-menu :default-active="currentRoute" router class="sidebar-menu">
        <el-menu-item index="/dashboard">
          <el-icon><DataAnalysis /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/evaluation">
          <el-icon><VideoPlay /></el-icon>
          <span>执行评测</span>
        </el-menu-item>
        <el-menu-item index="/history">
          <el-icon><Clock /></el-icon>
          <span>历史评测情况</span>
        </el-menu-item>
        <el-menu-item index="/citation-sources">
          <el-icon><Link /></el-icon>
          <span>引用源情况</span>
        </el-menu-item>
        <el-menu-item index="/questions">
          <el-icon><Document /></el-icon>
          <span>问题管理</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <el-button text style="color:rgba(255,255,255,0.5);width:100%" @click="handleLogout">
          <el-icon><SwitchButton /></el-icon> 退出登录
        </el-button>
      </div>
    </el-aside>
    <el-main class="main-content">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { removeToken, getToken } from './composables/useWebSocket'

const route = useRoute()
const router = useRouter()
const currentRoute = computed(() => route.path)

async function handleLogout() {
  const token = getToken()
  if (token) {
    try { await fetch('/api/auth/logout', { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } }) } catch (e) {}
  }
  removeToken()
  router.push('/login')
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f0f2f5; }
.app-container { height: 100vh; }
.sidebar { background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%); overflow-y: auto; display: flex; flex-direction: column; }
.sidebar .logo { padding: 20px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.1); }
.sidebar .logo-icon { font-size: 28px; }
.sidebar .logo-text { color: #fff; font-size: 18px; font-weight: 700; margin-left: 8px; }
.sidebar-menu { border-right: none !important; flex: 1; }
.sidebar .el-menu { background: transparent; }
.sidebar .el-menu-item { color: rgba(255,255,255,0.7); }
.sidebar .el-menu-item:hover { color: #fff; background: rgba(255,255,255,0.1); }
.sidebar .el-menu-item.is-active { color: #fff; background: rgba(15,52,96,0.6); border-right: 3px solid #409eff; }
.sidebar-footer { padding: 12px; border-top: 1px solid rgba(255,255,255,0.1); }
.main-content { padding: 24px; overflow-y: auto; background: #f0f2f5; }
</style>
