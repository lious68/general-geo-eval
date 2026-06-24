<template>
  <div class="home">
    <h2 class="page-title"><el-icon><Aim /></el-icon> 品牌设置</h2>

    <el-card v-loading="loading">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <strong><el-icon><OfficeBuilding /></el-icon> 被测品牌档案</strong>
          <el-tag v-if="configured" type="success" size="small">已设置</el-tag>
          <el-tag v-else type="danger" size="small">未设置</el-tag>
        </div>
      </template>

      <el-alert v-if="!configured" type="warning" :closable="false" style="margin-bottom:16px">
        尚未设置被测品牌。请先填写<strong>品牌名</strong>与<strong>网站</strong>（必选），系统会据此生成题集并让评测指标对该品牌生效。
      </el-alert>

      <el-form :model="form" label-width="100px" style="max-width:640px">
        <el-form-item label="品牌名" required>
          <el-input v-model="form.brand_name" placeholder="如 UCloud、Acme云" />
        </el-form-item>
        <el-form-item label="公司名">
          <el-input v-model="form.company_name" placeholder="如 优刻得、阿克米科技（可选，用于更全的品牌匹配）" />
        </el-form-item>
        <el-form-item label="网站" required>
          <el-input v-model="form.website" placeholder="如 https://www.ucloud.cn" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="form.industry" placeholder="如 云计算、新能源汽车、在线教育（用于按行业生成题集）" />
        </el-form-item>
      </el-form>

      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
        <el-button type="primary" :loading="saving" @click="save">
          <el-icon><Check /></el-icon> 保存品牌档案
        </el-button>
        <el-button type="success" :disabled="!configured" @click="goGenerate">
          <el-icon><MagicStick /></el-icon> 去生成问题题集
        </el-button>
      </div>

      <!-- 派生信息预览 -->
      <el-descriptions v-if="profile" :column="1" border size="small" style="margin-top:20px" title="自动派生（保存后生效）">
        <el-descriptions-item label="官方域名">{{ (profile.official_domains || []).join('、') || '—' }}</el-descriptions-item>
        <el-descriptions-item label="品牌关键词">{{ brandKeywordPreview }}</el-descriptions-item>
        <el-descriptions-item label="引用参考词">{{ (profile.reference_keywords || []).slice(0, 6).join('、') || '—' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 必填对话框：未设置品牌时强制弹出，不可关闭 -->
    <el-dialog v-model="requiredDialog" title="请先设置被测品牌" width="460px"
      :close-on-click-modal="false" :close-on-press-escape="false" :show-close="false"
      :align-center="true">
      <el-alert type="info" :closable="false" style="margin-bottom:12px">
        检测到尚未设置被测品牌。<strong>品牌名</strong>与<strong>网站</strong>为必选项，填写后方可继续使用评测系统。
      </el-alert>
      <el-form :model="form" label-width="80px">
        <el-form-item label="品牌名" required>
          <el-input v-model="form.brand_name" placeholder="如 UCloud" />
        </el-form-item>
        <el-form-item label="网站" required>
          <el-input v-model="form.website" placeholder="如 https://www.ucloud.cn" />
        </el-form-item>
        <el-form-item label="公司名">
          <el-input v-model="form.company_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="form.industry" placeholder="如 云计算" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="primary" :loading="saving" @click="saveFromDialog">保存并继续</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../composables/useWebSocket'

const router = useRouter()
const loading = ref(true)
const saving = ref(false)
const configured = ref(false)
const profile = ref(null)
const requiredDialog = ref(false)
const form = ref({ brand_name: '', company_name: '', website: '', industry: '' })

const brandKeywordPreview = computed(() => {
  const kw = profile.value?.keywords || {}
  return [...(kw.primary || []), ...(kw.aliases || [])].slice(0, 8).join('、') || '—'
})

async function loadProfile() {
  loading.value = true
  try {
    const res = await apiFetch('/settings/brand-profile')
    const d = res.data || {}
    configured.value = !!d.configured
    profile.value = d
    form.value = {
      brand_name: d.brand_name || '',
      company_name: d.company_name || '',
      website: d.website || '',
      industry: d.industry || '',
    }
    // 未设置品牌 → 强制弹必填对话框
    if (!configured.value) {
      requiredDialog.value = true
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!form.value.brand_name.trim() || !form.value.website.trim()) {
    ElMessage.warning('品牌名和网站为必选项')
    return
  }
  await doSave()
}

async function saveFromDialog() {
  if (!form.value.brand_name.trim() || !form.value.website.trim()) {
    ElMessage.warning('品牌名和网站为必选项，请填写后再继续')
    return
  }
  const ok = await doSave()
  if (ok) requiredDialog.value = false
}

async function doSave() {
  saving.value = true
  try {
    const res = await apiFetch('/settings/brand-profile', {
      method: 'PUT',
      body: JSON.stringify(form.value),
    })
    ElMessage.success(res.message || '品牌档案已保存')
    configured.value = true
    profile.value = res.data
    return true
  } catch (e) {
    ElMessage.error(e.message)
    return false
  } finally {
    saving.value = false
  }
}

function goGenerate() {
  router.push('/questions')
}

onMounted(loadProfile)
</script>

<style scoped>
.page-title { font-size: var(--fs-page-title); margin-bottom: 20px; color: var(--color-text); display: flex; align-items: center; gap: 8px; }
</style>
