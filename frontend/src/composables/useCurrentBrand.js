import { ref } from 'vue'
import { listBrands, getCurrentBrand, setCurrentBrand } from '../api/brands'

// 全局单例（模块级 ref，跨组件共享）
const currentBrand = ref(null)        // { id, brand_name, ... }
const brands = ref([])                // [{id, brand_name, ...}]
const loading = ref(false)

// 品牌切换事件订阅（各页 reload 用）
const listeners = new Set()
function emitBrandChanged() {
  listeners.forEach(cb => { try { cb(currentBrand.value) } catch (e) { console.error(e) } })
}

export function onBrandChanged(cb) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function useCurrentBrand() {
  async function refresh() {
    loading.value = true
    try {
      const [list, cur] = await Promise.all([listBrands(), getCurrentBrand()])
      brands.value = list.data || []
      currentBrand.value = cur.data || null
    } catch (e) {
      console.error('load brands error:', e)
    } finally {
      loading.value = false
    }
  }

  async function setCurrent(id) {
    if (!id) return
    try {
      const res = await setCurrentBrand(id)
      currentBrand.value = res.data || currentBrand.value
      emitBrandChanged()  // 通知各页重载
    } catch (e) {
      console.error('set current brand error:', e)
    }
  }

  return { currentBrand, brands, loading, refresh, setCurrent, onBrandChanged }
}
