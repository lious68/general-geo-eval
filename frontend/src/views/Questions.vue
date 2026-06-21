<template>
  <div class="questions">
    <h2 class="page-title"><el-icon><Document /></el-icon> 问题管理</h2>
    <el-card>
      <div style="margin-bottom:16px;display:flex;justify-content:space-between">
        <div>
          <el-select v-model="filterCategory" placeholder="品类筛选" clearable style="width:150px;margin-right:8px">
            <el-option v-for="c in categoryList" :key="c" :label="c" :value="c" />
          </el-select>
          <el-select v-model="filterType" placeholder="类型筛选" clearable style="width:150px">
            <el-option v-for="t in typeList" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <el-button v-if="isAdmin()" type="primary" @click="openAddDialog"><el-icon><Plus /></el-icon> 新增问题</el-button>
      </div>

      <el-table :data="filteredQuestions" stripe max-height="600">
        <el-table-column prop="id" label="ID" width="90" />
        <el-table-column prop="category" label="品类" width="100" />
        <el-table-column prop="question_type" label="类型" width="110" />
        <el-table-column prop="question" label="问题" min-width="300" />
        <el-table-column prop="difficulty" label="难度" width="80">
          <template #default="{ row }">
            <el-tag :type="row.difficulty==='easy'?'success':row.difficulty==='hard'?'danger':'info'" size="small">{{ row.difficulty }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button v-if="isAdmin()" type="primary" size="small" link @click="editQ(row)">编辑</el-button>
            <el-button v-if="isAdmin()" type="danger" size="small" link @click="deleteQ(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增/编辑对话框 -->
    <el-dialog v-model="showDialog" :title="editingQ ? '编辑问题' : '新增问题'" width="500px" @close="resetForm">
      <el-form :model="formQ" label-width="80px">
        <el-form-item label="ID"><el-input v-model="formQ.id" placeholder="如 custom_01" :disabled="!!editingQ" /></el-form-item>
        <el-form-item label="品类"><el-input v-model="formQ.category" placeholder="如 云计算" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="formQ.question_type">
            <el-option label="品牌词" value="品牌词" />
            <el-option label="品类词" value="品类词" />
            <el-option label="对比词" value="对比词" />
            <el-option label="场景词" value="场景词" />
          </el-select>
        </el-form-item>
        <el-form-item label="问题"><el-input v-model="formQ.question" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="submitQ">{{ editingQ ? '保存' : '添加' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch, isAdmin } from '../composables/useWebSocket'

const questions = ref([])
const filterCategory = ref('')
const filterType = ref('')
const showDialog = ref(false)
const editingQ = ref(null)
const defaultForm = { id: '', category: '', question_type: '品类词', question: '', tags: [], difficulty: 'medium' }
const formQ = ref({ ...defaultForm })

const categoryList = computed(() => [...new Set(questions.value.map(q => q.category))])
const typeList = computed(() => [...new Set(questions.value.map(q => q.question_type))])
const filteredQuestions = computed(() => {
  return questions.value.filter(q => {
    if (filterCategory.value && q.category !== filterCategory.value) return false
    if (filterType.value && q.question_type !== filterType.value) return false
    return true
  })
})

function openAddDialog() {
  editingQ.value = null
  formQ.value = { ...defaultForm }
  showDialog.value = true
}

function editQ(row) {
  editingQ.value = row
  formQ.value = { id: row.id, category: row.category, question_type: row.question_type, question: row.question, tags: row.tags || [], difficulty: row.difficulty || 'medium' }
  showDialog.value = true
}

function resetForm() {
  editingQ.value = null
  formQ.value = { ...defaultForm }
}

async function submitQ() {
  try {
    if (editingQ.value) {
      await apiFetch(`/questions/${editingQ.value.id}`, {
        method: 'PUT',
        body: JSON.stringify({ category: formQ.value.category, question_type: formQ.value.question_type, question: formQ.value.question })
      })
      ElMessage.success('保存成功')
    } else {
      await apiFetch('/questions', { method: 'POST', body: JSON.stringify(formQ.value) })
      ElMessage.success('添加成功')
    }
    showDialog.value = false
    await loadQuestions()
  } catch (e) { ElMessage.error(e.message) }
}

async function loadQuestions() {
  try {
    const res = await apiFetch('/questions')
    questions.value = res.data || []
  } catch (e) { console.error(e) }
}

async function deleteQ(id) {
  try {
    await apiFetch(`/questions/${id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await loadQuestions()
  } catch (e) { ElMessage.error(e.message) }
}

onMounted(loadQuestions)
</script>

<style scoped>
.page-title { font-size: var(--fs-page-title); margin-bottom: 20px; color: var(--color-text); display: flex; align-items: center; gap: 8px; }
</style>
