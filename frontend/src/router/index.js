import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../composables/useWebSocket'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/evaluation', name: 'Evaluation', component: () => import('../views/Evaluation.vue') },
  { path: '/questions', name: 'Questions', component: () => import('../views/Questions.vue') },
  { path: '/history', name: 'History', component: () => import('../views/History.vue') },
  { path: '/citation-sources', name: 'CitationSources', component: () => import('../views/CitationSources.vue') },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳转登录页
const PROTECTED_ROUTES = ['/evaluation', '/questions', '/settings']

router.beforeEach(async (to, from, next) => {
  if (to.meta.public || to.path === '/login') {
    return next()
  }

  // 检查登录状态
  const token = getToken()
  if (!token && PROTECTED_ROUTES.some(r => to.path.startsWith(r))) {
    return next('/login')
  }

  // 验证 token 有效性
  if (token) {
    try {
      const res = await fetch('/api/auth/check', {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      const data = await res.json()
      if (!data.data?.authenticated) {
        return next('/login')
      }
    } catch (e) {
      // 网络错误不拦截
    }
  }

  next()
})

export default router
