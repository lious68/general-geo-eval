import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/evaluation', name: 'Evaluation', component: () => import('../views/Evaluation.vue') },
  { path: '/questions', name: 'Questions', component: () => import('../views/Questions.vue') },
  { path: '/history', name: 'History', component: () => import('../views/History.vue') },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
