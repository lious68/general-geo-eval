<template>
  <div class="home">
    <h2 class="page-title"><el-icon><Aim /></el-icon> 品牌管理</h2>
    <el-card v-loading="loading">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-weight:600">被测品牌列表（点「设为当前」切换评测空间）</span>
        <el-button v-if="isAdmin()" type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 新建品牌</el-button>
      </div>
      <el-table :data="brands" stripe>
        <el-table-column prop="brand_name" label="品牌名" min-width="120" />
        <el-table-column prop="company_name" label="公司名" min-width="120" />
        <el-table-column prop="industry" label="行业" width="100" />
        <el-table-column prop="website" label="官网" min-width="180" />
        <el-table-column label="题集数" width="80">
          <template #default="{ row }">{{ row.question_count || 0 }}</template>
        </el-table-column>
        <el-table-column label="任务数" width="80">
          <template #default="{ row }">{{ row.task_count || 0 }}</template>
        </el-table-column>
        <el-table-column label="当前" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.id === currentId" type="success" size="small">当前</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" :disabled="row.id === currentId" @click="onSetCurrent(row)">设为当前</el-button>
            <el-button v-if="isAdmin()" size="small" link type="primary" @click="openEdit(row)">编辑档案</el-button>
            <el-button v-if="isAdmin() && row.id !== 'ucloud'" size="small" link type="danger" @click="onDel(row)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑品牌对话框 -->
    <el-dialog v-model="dialog" :title="editing ? '编辑品牌档案' : '新建品牌'" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="品牌ID" v-if="!editing">
          <el-input v-model="form.brand_id" placeholder="如 acme（小写英文，留空则按品牌名生成）" />
        </el-form-item>
        <el-form-item label="品牌名" required>
          <el-input v-model="form.brand_name" placeholder="如 UCloud、Acme云" />
        </el-form-item>
        <el-form-item label="公司名">
          <el-input v-model="form.company_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="网站" required>
          <el-input v-model="form.website" placeholder="如 https://www.ucloud.cn" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="form.industry" placeholder="如 云计算" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">{{ editing ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isAdmin } from '../composables/useWebSocket'
import { useCurrentBrand } from '../composables/useCurrentBrand'
import { createBrand, updateBrand, deleteBrand } from '../api/brands'

const { brands, currentBrand, loading, refresh, setCurrent } = useCurrentBrand()
const currentId = computed(() => currentBrand.value?.id || '')
const dialog = ref(false)
const editing = ref(null)
const saving = ref(false)
const form = ref({ brand_id: '', brand_name: '', company_name: '', website: '', industry: '' })

async function onSetCurrent(row) {
  await setCurrent(row.id)
  ElMessage.success(`已切换到品牌「${row.brand_name}」`)
}

function openCreate() {
  editing.value = null
  form.value = { brand_id: '', brand_name: '', company_name: '', website: '', industry: '' }
  dialog.value = true
}

function openEdit(row) {
  editing.value = row
  form.value = { brand_id: row.id, brand_name: row.brand_name, company_name: row.company_name, website: row.website, industry: row.industry }
  dialog.value = true
}

async function onSave() {
  if (!form.value.brand_name.trim() || !form.value.website.trim()) {
    ElMessage.warning('品牌名和网站为必填')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await updateBrand(editing.value.id, form.value)
      ElMessage.success('品牌档案已更新')
    } else {
      await createBrand(form.value)
      ElMessage.success('品牌已创建')
    }
    dialog.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(e.message || e)
  } finally {
    saving.value = false
  }
}

async function onDel(row) {
  await ElMessageBox.confirm(`确定删除品牌「${row.brand_name}」？需先清空其题集与任务。`, '删除', { type: 'warning' })
  try {
    await deleteBrand(row.id)
    ElMessage.success('已删除')
    await refresh()
  } catch (e) {
    ElMessage.error(e.message || e)
  }
}

onMounted(refresh)
</script>

<style scoped>
.page-title { font-size: var(--fs-page-title); margin-bottom: 20px; color: var(--color-text); display: flex; align-items: center; gap: 8px; }
</style>
