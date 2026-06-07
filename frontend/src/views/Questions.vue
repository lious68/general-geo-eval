<template>
  <div class="questions">
    <h2 class="page-title">📝 问题管理</h2>
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
        <el-button type="primary" @click="showAddDialog = true"><el-icon><Plus /></el-icon> 新增问题</el-button>
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
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="danger" size="small" link @click="deleteQ(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增对话框 -->
    <el-dialog v-model="showAddDialog" title="新增问题" width="500px">
      <el-form :model="newQ" label-width="80px">
        <el-form-item label="ID"><el-input v-model="newQ.id" placeholder="如 custom_01" /></el-form-item>
        <el-form-item label="品类"><el-input v-model="newQ.category" placeholder="如 云计算" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="newQ.question_type">
            <el-option label="品牌词" value="品牌词" />
            <el-option label="品类词" value="品类词" />
            <el-option label="对比词" value="对比词" />
            <el-option label="场景词" value="场景词" />
          </el-select>
        </el-form-item>
        <el-form-item label="问题"><el-input v-model="newQ.question" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="addQuestion">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../composables/useWebSocket'

const questions = ref([])
const filterCategory = ref('')
const filterType = ref('')
const showAddDialog = ref(false)
const newQ = ref({ id: '', category: '', question_type: '品类词', question: '', tags: [], difficulty: 'medium' })

const categoryList = computed(() => [...new Set(questions.value.map(q => q.category))])
const typeList = computed(() => [...new Set(questions.value.map(q => q.question_type))])
const filteredQuestions = computed(() => {
  return questions.value.filter(q => {
    if (filterCategory.value && q.category !== filterCategory.value) return false
    if (filterType.value && q.question_type !== filterType.value) return false
    return true
  })
})

async function loadQuestions() {
  try {
    const res = await apiFetch('/questions')
    questions.value = res.data || []
  } catch (e) { console.error(e) }
}

async function addQuestion() {
  try {
    await apiFetch('/questions', { method: 'POST', body: JSON.stringify(newQ.value) })
    ElMessage.success('添加成功')
    showAddDialog.value = false
    await loadQuestions()
  } catch (e) { ElMessage.error(e.message) }
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
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
</style>
