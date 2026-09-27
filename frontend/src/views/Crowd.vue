<template>
  <div class="crowd">
    <header class="crowd-hero"><div><div class="eyebrow">GEO / 众包评测</div></div><div class="hero-actions"><a href="https://zhun.ai/geo/publisher.html" target="_blank" rel="noopener">准活发布工作台 ↗</a><el-button type="primary" @click="$router.push('/evaluation?create=1')">＋ 新建采集项目</el-button></div></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <nav class="work-tabs" aria-label="众包评测功能导航">
      <button aria-label="项目管理" :aria-pressed="activeTab==='projects'" :class="{active:activeTab==='projects'}" @click="activeTab='projects'"><b class="nav-icon" aria-hidden="true">▦</b><div class="nav-copy"><strong>项目管理</strong><small>查看项目 · 跟进采集进度</small></div><em>{{ activeTab==='projects'?'当前页面':'进入 →' }}</em></button>
      <button aria-label="样本验收" :aria-pressed="activeTab==='review'" :class="{active:activeTab==='review'}" @click="activeTab='review'"><b class="nav-icon" aria-hidden="true">✓</b><div class="nav-copy"><strong>样本验收 <span class="review-count">{{ samples.filter(s=>s.status==='pending').length }} 待验收</span></strong><small>核对证据 · 批量通过样本</small></div><em>{{ activeTab==='review'?'当前页面':'进入 →' }}</em></button>
      <button aria-label="配置新项目" :aria-pressed="activeTab==='create'" :class="{active:activeTab==='create'}" @click="activeTab='create'"><b class="nav-icon" aria-hidden="true">＋</b><div class="nav-copy"><strong>配置新项目</strong><small>选择题目与平台 · 创建采集项目</small></div><em>{{ activeTab==='create'?'当前页面':'进入 →' }}</em></button>
    </nav>
    <div class="overview"><div><span>采集项目</span><strong>{{ projects.length }}</strong><small>{{ projects.filter(p=>p.active).length }} 个开放分配<template v-if="scopeLabel"> · 当前筛选 {{ scopedProjects.length }}</template></small></div><div class="overview-link" role="button" tabindex="0" title="查看全部待验收样本" @click="showAllPending" @keydown.enter="showAllPending"><span>待验收 →</span><strong>{{ samples.filter(s=>s.status==='pending').length }}</strong><small>等待核对原始证据<template v-if="scopeLabel"> · 当前筛选 {{ reviewScope.filter(s=>s.status==='pending').length }}</template></small></div><div><span>已通过样本</span><strong>{{ samples.filter(s=>s.status==='accepted').length }}</strong><small>关联后计入评测评分<template v-if="scopeLabel"> · 当前筛选 {{ reviewScope.filter(s=>s.status==='accepted').length }}</template></small></div><div><span>需跟进</span><strong>{{ samples.filter(s=>['late','revision'].includes(s.status)).length }}</strong><small>迟交核对 / 退回补充<template v-if="scopeLabel"> · 当前筛选 {{ reviewScope.filter(s=>['late','revision'].includes(s.status)).length }}</template></small></div></div>

    <el-card v-show="activeTab==='create'" class="form-panel" shadow="never"><div class="panel-heading"><div><h2>配置采集项目</h2><p>选择大任务与平台，题目会自动带入。保存后再到准活确认报酬并发布。</p></div><span class="step-label">01 配题 → 02 发布 → 03 验收</span></div><el-form label-position="top" class="project-form">
      <el-form-item label="所属评测任务" class="key-field"><el-select v-model="taskId" filterable placeholder="选择执行评测中的大任务" @change="loadTaskQuestions"><el-option v-for="t in evaluationTasks" :key="t.id" :label="t.name" :value="t.id"/></el-select><span class="help">选定后导入大任务题目；验收通过后自动计入该任务覆盖率和评分。</span></el-form-item>
      <el-form-item label="项目名称" class="key-field"><el-input v-model="form.title" /></el-form-item>
      <el-form-item label="采集平台"><el-checkbox-group v-model="selectedPlatforms"><el-checkbox v-for="p in platformOptions" :key="p.name" :label="p.name">{{ p.name }}</el-checkbox></el-checkbox-group><p class="help">支持多选，平台入口已配置。每个平台单独生成一个项目，共用下方题目，分别发布到准活。</p></el-form-item>
      <el-form-item label="选择题目"><div class="question-picker"><div class="question-toolbar"><el-input v-model="questionSearch" clearable placeholder="搜索题号或问题"/><el-button @click="selectVisibleQuestions">全选当前结果</el-button><el-button @click="selectedQuestionIds=[]">清空</el-button><el-button :disabled="!taskId||busy" @click="refreshQuestionProgress">刷新进度</el-button></div><p class="help">已选 {{ selectedQuestionIds.length }} / {{ taskQuestions.length }} 题。已完成表示已进入大任务评分；待验收、待补充与迟交尚不计入覆盖率。</p><div class="coverage-summary"><div>总格数<strong>{{ coverageTotal }}</strong></div><div>已完成<strong>{{ coverageDone }}</strong></div><div>缺失<strong>{{ coverageTotal-coverageDone }}</strong></div><div class="coverage-rate">覆盖率<el-progress :percentage="coverageTotal?Math.round(coverageDone/coverageTotal*100):0"/></div></div><p class="help">✓ 已完成并计入评分 · 待验收 / 待同步尚未计入 · · 未完成；悬停格子查看题目及状态。</p><div class="coverage-scroll"><table class="coverage-matrix"><thead><tr><th scope="col">平台 / 题号</th><th v-for="q in taskQuestions" :key="q.id" scope="col" :title="q.question">{{ q.id }}</th></tr></thead><tbody><tr v-for="p in platformOptions" :key="p.name"><th scope="row">{{ p.name }}</th><td v-for="q in taskQuestions" :key="q.id" :class="questionProgress(p,q).kind" :title="q.id+' · '+q.question+'：'+questionProgress(p,q).label" :aria-label="p.name+' '+q.id+' '+questionProgress(p,q).label">{{ questionProgress(p,q).kind==='done'?'✓':questionProgress(p,q).kind==='missing'?'·':questionProgress(p,q).label }}</td></tr></tbody></table></div><el-table :data="filteredQuestions" max-height="460" row-key="id" empty-text="请先选择所属评测任务"><el-table-column label="选择" width="62"><template #default="{row}"><el-checkbox :model-value="selectedQuestionIds.includes(row.id)" :aria-label="'选择题目 '+row.id" @change="checked=>toggleQuestion(row.id,checked)"/></template></el-table-column><el-table-column prop="id" label="题号" width="85"/><el-table-column prop="question" label="问题" min-width="250"/><el-table-column v-for="p in platformOptions" :key="p.name" :label="p.name" width="95"><template #default="{row}"><span :class="['question-state',questionProgress(p,row).kind]">{{ questionProgress(p,row).label }}</span></template></el-table-column></el-table></div></el-form-item>
      <el-form-item label="对话方式"><el-checkbox v-model="newConversation">每道题新开一个对话（推荐）</el-checkbox><p class="help">避免上一道题影响回答。不勾选表示不限制，助手会记录实际情况。</p></el-form-item>
      <el-button type="primary" :loading="busy" @click="publish">保存题目，等待关联准活任务</el-button>
    </el-form></el-card>
    <section v-show="activeTab==='projects'" class="work-panel"><div class="panel-heading"><div><h2>采集项目</h2><p>每个平台独立发布，已通过样本汇总到所属评测任务。</p></div><el-button @click="load">刷新项目</el-button></div><div v-if="projects.some(p=>!p.evaluation)" class="review-filters"><el-select v-model="taskId" filterable placeholder="为历史项目选择所属大任务"><el-option v-for="t in evaluationTasks" :key="t.id" :label="t.name" :value="t.id"/></el-select><span class="help">选择后，点击项目行内的关联按钮。</span></div><el-table :data="visibleProjects" empty-text="还没有采集项目，点击右上角新建"><el-table-column label="大类任务" min-width="220"><template #default="{row}"><div v-if="row.evaluation" class="task-cell"><a :href="'/tasks/'+row.evaluation.task_id">{{ row.evaluation.task_name }}</a><el-button size="small" link type="primary" @click="syncEvaluation(row)">同步评分</el-button></div><el-button v-else size="small" @click="attachEvaluation(row)">关联所选大类任务</el-button></template></el-table-column><el-table-column label="采集项目" min-width="170"><template #default="{row}"><strong v-if="row.lineage" class="subtask-no">子任务{{ String(row.lineage.subtask_no).padStart(2,'0') }}</strong> {{ row.title }}<small v-if="row.lineage" class="source-id">{{ row.lineage.label }}</small></template></el-table-column><el-table-column prop="platform" label="平台" width="95"/><el-table-column label="准活任务"><template #default="{row}"><a v-if="row.task_link" :href="row.task_link.url" target="_blank" rel="noopener">#{{ row.task_link.task_id }} {{ row.task_link.title }}</a><template v-else><el-button type="primary" @click="publishToZhun(row)">带到准活发布</el-button></template></template></el-table-column><el-table-column label="题数"><template #default="{row}">{{ row.questions.length }}</template></el-table-column><el-table-column label="状态" min-width="145"><template #default="{row}"><el-tag :type="projectProgress(row).complete?'success':row.task_link?'primary':'info'">{{ projectProgress(row).complete?'已验收':row.task_link?'已发布':'待发布' }}</el-tag><small class="progress-note">已验收 {{ projectProgress(row).accepted }} / {{ projectProgress(row).target }} 份</small><small v-if="!row.active" class="progress-note">已暂停分配</small></template></el-table-column><el-table-column label="操作" width="150"><template #default="{row}"><el-button v-if="!projectProgress(row).complete" size="small" link @click="toggle(row)">{{ row.active ? '暂停分配' : '恢复分配' }}</el-button><span v-else class="help">采集完成</span><el-button size="small" link type="danger" :disabled="busy" @click="deleteProject(row)">删除</el-button></template></el-table-column></el-table><div class="project-pages"><span class="help">共 {{ projects.length }} 个项目</span><el-button v-if="projectPage>1" size="small" @click="projectPage--">上一页</el-button><span>{{ projectPage }} / {{ Math.max(1,Math.ceil(projects.length/6)) }}</span><el-button v-if="projectPage*6<projects.length" size="small" @click="projectPage++">更多</el-button></div>
    </section><section v-show="activeTab==='review'" class="work-panel"><div class="panel-heading"><div><h2>原始样本与验收</h2><p>验收通过仅计入有效样本，不自动付款。迟交样本保留，可核对证据后填写理由并强制通过；通过后计入配额，已被重新占用的名额不能重复计入。</p></div></div><div v-if="focusedProject||focusedWorker" class="scope-banner"><div><strong>当前只显示准活跳转的范围：</strong>{{ focusDescription }}<span class="scope-count">（{{ reviewScope.length }} 条样本，其中待验收 {{ reviewScope.filter(s=>s.status==='pending').length }}）</span><p v-if="hiddenPending" class="scope-warn">另有 {{ hiddenPending }} 条待验收样本不在此范围内，列表中看不到。</p></div><div class="scope-actions"><el-button v-if="hiddenPending" type="warning" @click="showAllPending">查看全部 {{ samples.filter(s=>s.status==='pending').length }} 条待验收</el-button><el-button @click="focusedProject='';focusedWorker=''">查看全部样本</el-button></div></div><div class="review-filters"><el-input v-model="sampleSearch" clearable placeholder="搜索题目、项目或参与者"/><el-select v-model="sampleState"><el-option label="全部状态" value=""/><el-option label="待验收" value="pending"/><el-option label="已通过" value="accepted"/><el-option label="迟交待核对" value="late"/><el-option label="待补充" value="revision"/><el-option label="已驳回" value="rejected"/></el-select><el-button @click="load">刷新结果</el-button></div>
    <el-button type="primary" :disabled="busy||!reviewSelection.length" @click="batchAccept">批量通过（{{ reviewSelection.length }}）</el-button><el-table :data="filteredSamples" @selection-change="rows=>reviewSelection=rows" stripe empty-text="暂无符合条件的样本"><el-table-column type="selection" width="45" :selectable="row=>row.status==='pending'&&!row.review_blockers.length"/><el-table-column label="来源编号" min-width="190"><template #default="{row}"><span v-if="row.source_label" class="source-id">{{ row.source_label }}</span><template v-else>{{ row.project_title }} · 第{{ row.question_no }}题<small class="source-id">未编号</small></template></template></el-table-column><el-table-column prop="prompt" label="题目" min-width="210"/><el-table-column prop="platform" label="WebChat 渠道" width="120"/><el-table-column label="准活参与者" min-width="130"><template #default="{row}">{{ row.worker_name || '姓名同步中' }}<small style="display:block">{{ row.worker }}</small></template></el-table-column><el-table-column label="验收状态" min-width="200"><template #default="{row}"><el-tag :type="row.status==='accepted'?'success':row.status==='pending'?'warning':'info'">{{ row.forced_acceptance ? "已通过（人工强制）" : statusLabel(row.status) }}</el-tag><p v-for="b in row.review_blockers" :key="b" style="color:#a55b12"><el-button v-if="b.startsWith('引用采集不完整')" link type="warning" @click="citationDetail=row.citation_diagnostics">{{ row.citation_diagnostics?.summary || b }} · 查看原因</el-button><template v-else>{{ b }}</template></p><small v-if="row.review">{{ row.review.reason }}</small></template></el-table-column><el-table-column label="查看" width="110"><template #default="{row}"><el-button  :disabled="busy" @click="openEvidence(row)">打开证据</el-button></template></el-table-column></el-table>
    </section><el-dialog :model-value="!!citationDetail" @close="citationDetail=null" title="引用采集缺项与原因" width="min(720px, 92vw)"><template v-if="citationDetail"><el-alert :title="citationDetail.summary" type="warning" :closable="false"/><p>已采集 {{ citationDetail.collected_entries }} 条引用记录，包含 {{ citationDetail.unique_links }} 个不同链接。</p><p class="help">以下为采集客户端记录；引用位置、来源条目和不同文章的数量可能不同，不能直接相减推算缺失文章数。</p><ul><li v-for="(note,i) in citationDetail.notes" :key="i" style="white-space:pre-wrap;overflow-wrap:anywhere;margin:12px 0">{{ note }}</li></ul><p v-if="!citationDetail.notes.length">未提供具体原因，请核对原始证据或退回补充说明。</p></template></el-dialog><el-dialog v-model="showSample" title="原始采集证据" width="80%"><template v-if="selected"><el-alert v-if="error" :title="error" type="error" :closable="false"/><el-alert v-for="b in selected.review_blockers" :key="b" :title="b" type="warning" :closable="false"/><p>{{ selected.project_title }} · 第 {{ selected.question_no }} 题 · {{ selected.platform }} · {{ selected.worker_name || selected.worker }} · {{ statusLabel(selected.status) }} · 补充版本 {{ selected.version }}</p><el-alert v-if="selected.forced_acceptance" :title="'人工强制通过 · 操作人：'+selected.review.reviewer+' · 原因：'+selected.review.reason" type="warning" :closable="false"/><h3>{{ selected.body.prompt }}</h3><pre>{{ selected.body.answer }}</pre><h4>采集条件</h4><pre>{{ selected.body.conditions }}</pre><h4>引用</h4><p>{{ selected.body.citations_state }}</p><p v-for="(c,i) in selected.body.citations" :key="i">{{ c.kind }} · {{ c.title }} · {{ c.url }}</p><h4>采集完整性说明</h4><ul><li v-for="(note,i) in selected.body.evidence.completeness_notes || []" :key="i">{{ note }}</li></ul><h4>页面原文</h4><pre>{{ selected.body.evidence.page_text }}</pre><img v-for="(s,i) in selected.body.evidence.screenshots || []" :key="i" :src="'data:'+s.mime+';base64,'+s.base64" alt="采集截图" style="max-width:100%"/><p>内容摘要：{{ selected.digest }}</p><el-input v-model="reason" placeholder="通过无需填写；退回、驳回或强制通过请填写原因"/><el-button :disabled="busy || selected.status!=='pending' || selected.review_blockers.length>0" @click="review('accepted')">通过</el-button><el-button type="warning" :disabled="busy || !['pending','late'].includes(selected.status)" @click="review('force_accepted')">强制通过</el-button><el-button :disabled="busy || selected.status!=='pending'" @click="review('revision')">退回补充</el-button><el-button :disabled="busy || selected.status!=='pending'" @click="review('rejected')">最终驳回</el-button></template></el-dialog>
  </div>
</template>
<script setup>
import {ref,computed,onMounted} from 'vue'
import {ElMessageBox,ElMessage} from 'element-plus'
import {useRoute} from 'vue-router'
import {getToken} from '../composables/useWebSocket'
const platformOptions=[{name:'ds',url:'https://chat.deepseek.com/'},{name:'豆包',url:'https://www.doubao.com/chat/'},{name:'kimi',url:'https://www.kimi.com/zh'},{name:'qwen',url:'https://chat.qwen.ai/'},{name:'文心',url:'https://wenxin.baidu.com/?enter_type=yiyan_site'}]
const selectedPlatforms=ref(['豆包']),newConversation=ref(true)
const form=ref({title:'',replicas:1,batch_size:5}),error=ref(''),busy=ref(false),projects=ref([]),samples=ref([]),selected=ref(null),reason=ref('')
const projectPage=ref(1)
const visibleProjects=computed(()=>[...projects.value].sort((a,b)=>(b.created||0)-(a.created||0)||(Number(b.task_link?.task_id)||0)-(Number(a.task_link?.task_id)||0)).slice((projectPage.value-1)*6,projectPage.value*6))
const route=useRoute(),taskId=ref(route.query.task_id||''),evaluationTasks=ref([])
const activeTab=ref(route.query.view==='review'?'review':route.query.task_id?'create':'projects'),sampleSearch=ref(''),sampleState=ref('')
const focusedProject=ref(route.query.project||''),focusedWorker=ref(route.query.worker||'')
const statusRank={pending:0,late:1,revision:2,rejected:3,accepted:4}
const filteredSamples=computed(()=>samples.value.filter(s=>(!focusedProject.value||s.project===focusedProject.value)&&(!focusedWorker.value||s.worker===focusedWorker.value)&&(!sampleState.value||s.status===sampleState.value)&&[s.prompt,s.project_title,s.source_label||'',s.worker_name,s.worker].join(' ').toLowerCase().includes(sampleSearch.value.toLowerCase())).map((s,i)=>[s,i]).sort((a,b)=>(statusRank[a[0].status]??5)-(statusRank[b[0].status]??5)||a[1]-b[1]).map(x=>x[0]))
const reviewScope=computed(()=>samples.value.filter(s=>(!focusedProject.value||s.project===focusedProject.value)&&(!focusedWorker.value||s.worker===focusedWorker.value)))
const scopedProjects=computed(()=>focusedProject.value?projects.value.filter(p=>p.id===focusedProject.value):projects.value)
const scopeLabel=computed(()=>focusedProject.value||focusedWorker.value?'（当前筛选）':'')
const hiddenPending=computed(()=>samples.value.filter(s=>s.status==='pending').length-reviewScope.value.filter(s=>s.status==='pending').length)
const focusDescription=computed(()=>{const parts=[];if(focusedProject.value){const p=projects.value.find(x=>x.id===focusedProject.value);parts.push('项目「'+(p?p.title+' · '+p.platform:focusedProject.value.slice(0,8))+'」')}if(focusedWorker.value){const s=samples.value.find(x=>x.worker===focusedWorker.value);parts.push('参与者 '+(s?.worker_name?s.worker_name+'（'+focusedWorker.value+'）':focusedWorker.value))}return parts.join(' · ')})
function showAllPending(){focusedProject.value='';focusedWorker.value='';sampleSearch.value='';sampleState.value='pending';activeTab.value='review'}
const taskQuestions=ref([]),selectedQuestionIds=ref([]),questionSearch=ref(''),taskCoverage=ref({}),loadedTaskId=ref('')
const filteredQuestions=computed(()=>taskQuestions.value.filter(q=>(q.id+' '+q.question).toLowerCase().includes(questionSearch.value.toLowerCase())))
const modelKeys={ds:'deepseek','豆包':'doubao',kimi:'kimi',qwen:'qwen','文心':'ernie'}
function questionProgress(platform,q){
 const native=taskCoverage.value[modelKeys[platform.name]]?.[q.id]
 if(native==='done')return {kind:'done',label:'已完成'}
 const links=projects.value.filter(p=>p.evaluation?.task_id===loadedTaskId.value&&p.evaluation.model_key===modelKeys[platform.name])
 const states=[]
 for(const p of links){const i=p.evaluation.question_ids.indexOf(q.id);if(i>=0)states.push(...samples.value.filter(s=>s.project===p.id&&s.question===i).map(s=>s.status))}
 if(states.includes('accepted'))return {kind:'pending',label:'待同步评分'}
 if(states.includes('pending'))return {kind:'pending',label:'待验收'}
 if(states.includes('revision'))return {kind:'warning',label:'待补充'}
 if(states.includes('late'))return {kind:'warning',label:'迟交待核对'}
 if(native==='failed'||states.includes('rejected'))return {kind:'warning',label:'待重采'}
 return {kind:'missing',label:'未完成'}
}
const coverageTotal=computed(()=>taskQuestions.value.length*platformOptions.length)
const coverageDone=computed(()=>platformOptions.reduce((n,p)=>n+platformCompleted(p),0))
function platformCompleted(p){return taskQuestions.value.filter(q=>taskCoverage.value[modelKeys[p.name]]?.[q.id]==='done').length}
function toggleQuestion(id,checked){selectedQuestionIds.value=checked?[...new Set([...selectedQuestionIds.value,id])]:selectedQuestionIds.value.filter(x=>x!==id)}
function selectVisibleQuestions(){selectedQuestionIds.value=[...new Set([...selectedQuestionIds.value,...filteredQuestions.value.map(q=>q.id)])]}
const showSample=computed({get:()=>!!selected.value,set:v=>{if(!v)selected.value=null}})
async function api(path,body){const r=await fetch('/api/crowd/admin/'+path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+getToken(),'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});const d=await r.json();if(!r.ok)throw Error(d.detail||'请求失败');return d}
async function safe(fn){error.value='';busy.value=true;try{await fn()}catch(e){error.value=e.message}finally{busy.value=false}}
async function load(){await safe(async()=>{[projects.value,samples.value]=await Promise.all([api('projects'),api('samples')])})}
async function taskApi(path){const r=await fetch('/api/tasks'+path,{headers:{Authorization:'Bearer '+getToken()}});const d=await r.json();if(!r.ok)throw Error(d.detail||'任务加载失败');return d.data}
async function fetchTaskQuestions(preserve=false){
 if(!taskId.value)throw Error('请先选择所属评测任务')
 const id=taskId.value,d=await taskApi('/'+id)
 if(taskId.value!==id)return
 const old=preserve&&loadedTaskId.value===id?selectedQuestionIds.value:[]
 taskQuestions.value=d.questions;taskCoverage.value=d.coverage||{};loadedTaskId.value=id
 selectedQuestionIds.value=old.filter(id=>d.questions.some(q=>q.id===id))
 if(!form.value.title)form.value.title=d.task.name
}
async function loadTaskQuestions(){taskQuestions.value=[];selectedQuestionIds.value=[];taskCoverage.value={};loadedTaskId.value='';await safe(()=>fetchTaskQuestions())}
async function refreshQuestionProgress(){await safe(async()=>{[projects.value,samples.value]=await Promise.all([api('projects'),api('samples')]);await fetchTaskQuestions(true)})}
async function attachEvaluation(row){await safe(async()=>{if(!taskId.value)throw Error('请先在上方选择所属评测任务');await api('projects/'+row.id+'/evaluation',{task_id:taskId.value});projects.value=await api('projects');ElMessage.success('已关联大任务并同步已通过样本')})}
async function syncEvaluation(row){await safe(async()=>{const r=await api('projects/'+row.id+'/sync-evaluation',{});ElMessage.success('已同步 '+r.completed+' 道题'+(r.conflicts?.length?'；'+r.conflicts.length+' 道题已有其他批次结果，未覆盖':''))})}

async function publish(){await safe(async()=>{
 if(!taskId.value)throw Error('请选择所属评测任务')
 if(loadedTaskId.value!==taskId.value)throw Error('请先加载所属任务的题目')
 const questions=taskQuestions.value.filter(q=>selectedQuestionIds.value.includes(q.id)).map(q=>q.question)
 if(!taskId.value)throw Error('请先选择所属评测任务：传出去的每道题都按 品牌 / 大任务 / 子任务 / 题 编号')
 if(!form.value.title.trim())throw Error('请填写项目名称')
 if(!selectedPlatforms.value.length)throw Error('请至少选择一个采集平台')
 if(!questions.length)throw Error('请至少勾选一道题')
 const conditions={}
 if(newConversation.value)conditions.new_conversation=true
 const chosen=platformOptions.filter(p=>selectedPlatforms.value.includes(p.name)),multiple=chosen.length>1
 try{for(const p of chosen){await api('projects',{...form.value,task_id:taskId.value,title:multiple?form.value.title+' · '+p.name:form.value.title,platform:p.name,entry_url:p.url,questions,conditions});selectedPlatforms.value=selectedPlatforms.value.filter(name=>name!==p.name)}projectPage.value=1;activeTab.value='projects';ElMessage.success('项目已保存，请带到准活发布')}finally{projects.value=await api('projects')}
})}

function projectProgress(row){
 const counts=new Map()
 for(const s of samples.value){if(s.project===row.id&&s.status==='accepted'){const key=s.question;const workers=counts.get(key)||new Set();workers.add(s.worker);counts.set(key,workers)}}
 const replicas=row.replicas||1,target=row.questions.length*replicas
 const accepted=row.questions.reduce((n,_,i)=>n+Math.min(replicas,counts.get(i)?.size||0),0)
 return {accepted,target,complete:target>0&&accepted===target}
}
async function deleteProject(row){
 if(row.task_link){ElMessage.warning('项目已关联准活任务，不能删除；可暂停分配');return}
 try{await ElMessageBox.confirm('确认删除采集项目「'+row.title+'」？删除后无法恢复；所属评测大任务不受影响。已有领取或采集记录的项目不能删除。','删除采集项目',{type:'warning',confirmButtonText:'确认删除',cancelButtonText:'取消'})}catch{return}
 await safe(async()=>{await api('projects/'+row.id+'/delete',{});projects.value=await api('projects');projectPage.value=Math.min(projectPage.value,Math.max(1,Math.ceil(projects.value.length/6)));ElMessage.success('采集项目已删除')})
}
async function toggle(row){await safe(async()=>{await api('projects/'+row.id+'/state',{active:!row.active});projects.value=await api('projects')})}
async function openEvidence(row){await safe(async()=>{selected.value=await api('samples/'+row.id);reason.value=''})}
const reviewSelection=ref([]),citationDetail=ref(null)
async function batchAccept(){await safe(async()=>{const rows=[...reviewSelection.value],failures=[];let done=0;for(const row of rows){try{const r=await api('samples/'+row.id+'/review',{decision:'accepted',reason:'批量验收通过'});done++;if(r.sync_error)failures.push(r.sync_error)}catch(e){failures.push(row.question_no+'题：'+e.message)}}samples.value=await api('samples');reviewSelection.value=[];ElMessage.success('已通过 '+done+' 条');if(failures.length)error.value=failures.join('；')})}
async function review(decision){await safe(async()=>{if(decision==='accepted'&&!reason.value.trim())reason.value='验收通过';if(!reason.value.trim())throw Error('请填写验收理由，再提交处理结果');if(decision==='force_accepted'){try{await ElMessageBox.confirm('强制通过会保留缺项和条件不符记录，并计入通过配额；正式任务按约定单价进入待人工结算，不会自动付款。原因：'+reason.value,'确认强制通过',{type:'warning',confirmButtonText:'确认强制通过',cancelButtonText:'取消'})}catch{return}}const reviewed=await api('samples/'+selected.value.id+'/review',{decision,reason:reason.value,confirmed:decision==='force_accepted'});selected.value=null;samples.value=await api('samples');if(reviewed.sync_error)error.value=reviewed.sync_error})}
function statusLabel(s){return {pending:'待验收',accepted:'已通过',revision:'待补充',rejected:'已驳回',late:'迟交待核对'}[s]||s}

async function publishToZhun(row){await safe(async()=>{const r=await api('projects/'+row.id+'/link-code',{});window.location.assign('https://zhun.ai/#publish/skill/geo/'+encodeURIComponent(r.code))})}
onMounted(async()=>{await load();await safe(async()=>{evaluationTasks.value=await taskApi('');if(!taskId.value&&evaluationTasks.value.length)taskId.value=evaluationTasks.value[0].id});if(taskId.value)await loadTaskQuestions()})
</script>
<style scoped>
/* 众包评测：沿用 GEO 全局变量（App.vue :root），与任务/看板页一致。
   字号阶梯：页面标题 22 / 区块标题 16 / 正文 14 / 辅助 13 / 注释 12。 */
.crowd{--c-primary:var(--el-color-primary,#409eff);--c-text:var(--color-text,#1a1a2e);--c-sec:#606266;--c-muted:#909399;--c-border:var(--color-border,#ebeef5);--c-soft:#f5f7fa;
  max-width:1600px;margin:0 auto;padding:0 0 24px;color:var(--c-text);font-size:14px;line-height:1.6}
.crowd a{color:var(--c-primary);text-decoration:none}
.crowd a:hover{text-decoration:underline}
h2{font-size:var(--fs-section-title,16px);font-weight:600;margin:0;color:var(--c-text)}
h3{font-size:15px;font-weight:600;margin:12px 0 8px}
h4{font-size:14px;font-weight:600;margin:16px 0 6px;color:var(--c-text)}
p{font-size:13px;color:var(--c-sec);line-height:1.6;margin:4px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--c-soft);border:1px solid var(--c-border);padding:12px 14px;border-radius:6px;font-size:13px;line-height:1.7;margin:4px 0}

/* 页头 */
.crowd-hero{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:0 0 16px}
.eyebrow{font-size:var(--fs-page-title,22px);font-weight:700;color:var(--c-text);letter-spacing:0}
.hero-actions{display:flex;gap:16px;align-items:center;flex-shrink:0}
.hero-actions a{font-size:14px}

/* 三个入口 */
.work-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0 0 16px}
.work-tabs button{display:flex;align-items:center;gap:12px;min-height:72px;padding:14px 16px;text-align:left;font:inherit;cursor:pointer;
  background:var(--color-card,#fff);border:1px solid var(--c-border);border-radius:var(--radius,10px);color:var(--c-text);transition:border-color .15s,box-shadow .15s,background .15s}
.work-tabs button:hover:not(.active){border-color:#c6e2ff;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.work-tabs button.active{border-color:var(--c-primary);background:var(--color-primary-soft,rgba(64,158,255,.08));box-shadow:inset 0 -3px 0 var(--c-primary)}
.work-tabs button:focus-visible{outline:2px solid var(--c-primary);outline-offset:2px}
.nav-icon{display:flex;align-items:center;justify-content:center;flex-shrink:0;width:36px;height:36px;border-radius:8px;background:var(--c-soft);color:var(--c-sec);font-size:18px;font-weight:600}
.active .nav-icon{background:var(--c-primary);color:#fff}
.nav-copy{flex:1;min-width:0}
.nav-copy strong{display:flex;align-items:center;flex-wrap:wrap;gap:8px;font-size:16px;font-weight:600;line-height:1.4}
.nav-copy small{display:block;margin-top:2px;font-size:12px;color:var(--c-muted);line-height:1.5}
.work-tabs button em{font-style:normal;font-size:12px;color:var(--c-muted);white-space:nowrap}
.work-tabs button.active em{color:var(--c-primary);font-weight:600}
.review-count{background:#fdf6ec;color:#b88230;border:1px solid #faecd8;border-radius:4px;padding:0 6px;font-size:12px;font-weight:500;line-height:20px;white-space:nowrap}

/* 概览指标（与看板 metric-card 同口径） */
.overview{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:0 0 16px}
.overview>div{padding:10px 16px;background:var(--color-card,#fff);border:1px solid var(--c-border);border-radius:var(--radius,10px)}
.overview span{display:block;font-size:13px;line-height:20px;color:var(--c-sec);font-weight:500}
.overview strong{display:block;font-size:26px;font-weight:700;line-height:1.2;margin:2px 0;color:var(--c-text);font-variant-numeric:tabular-nums}
.overview>div:nth-child(2) strong{color:#e6a23c}
.overview>div:nth-child(3) strong{color:#67c23a}
.overview small{display:block;font-size:12px;line-height:18px;color:var(--c-muted)}

/* 面板 */
.work-panel,.form-panel{background:var(--color-card,#fff);border:1px solid var(--c-border);border-radius:var(--radius,10px);padding:16px 20px}
.form-panel{padding:0}
.form-panel :deep(.el-card__body){padding:16px 20px}
.panel-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid var(--c-border)}
.step-label{font-size:12px;color:var(--c-muted);white-space:nowrap;background:var(--c-soft);border-radius:4px;padding:2px 8px}
.help{display:block;width:100%;margin:4px 0 0;font-size:12px;color:var(--c-muted);line-height:1.6}
.review-filters{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:12px}
.scope-banner{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px;padding:10px 14px;background:#ecf5ff;border:1px solid #d9ecff;border-radius:8px;font-size:14px}
.scope-banner strong{font-weight:600}
.scope-count{color:var(--c-sec)}
.scope-warn{margin:4px 0 0;color:#b88230;font-size:13px;font-weight:500}
.scope-actions{display:flex;gap:8px;flex-shrink:0}
.overview-link{cursor:pointer;transition:border-color .15s,box-shadow .15s}
.overview-link:hover,.overview-link:focus-visible{border-color:#e6a23c;box-shadow:0 2px 8px rgba(230,162,60,.15);outline:none}
.review-filters .el-input{max-width:320px}
.review-filters .el-select{width:170px}
.project-pages{display:flex;align-items:center;justify-content:flex-end;gap:12px;margin-top:12px;font-size:13px;color:var(--c-sec)}

/* 表格 */
.crowd :deep(.el-table){--el-table-header-bg-color:#fafafa;--el-table-border-color:var(--c-border);font-size:14px}
.crowd :deep(.el-table th.el-table__cell){height:44px;color:var(--c-sec);font-weight:600;font-size:13px}
.crowd :deep(.el-table td.el-table__cell){padding:10px 0}
.crowd :deep(.el-table .el-button){margin:2px 6px 2px 0}
.crowd :deep(.el-table .el-button+.el-button){margin-left:0}
.task-cell{display:flex;flex-direction:column;align-items:flex-start;gap:2px}
.task-cell a{font-weight:500}
.task-cell .el-button{font-size:12px;padding:0;height:22px;min-height:0;margin:0}
.progress-note{display:block;margin-top:4px;font-size:12px;color:var(--c-muted)}

/* 表单 */
.crowd :deep(.el-form){max-width:none}
.project-form{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}
.project-form>:nth-child(n+3){grid-column:1 / -1}
.crowd :deep(.el-form-item){margin-bottom:16px}
.crowd :deep(.el-form-item__label){font-size:14px;font-weight:600;color:var(--c-text);line-height:22px;margin-bottom:6px}
.crowd :deep(.el-select){min-width:220px}
.key-field{background:var(--c-soft);border:1px solid var(--c-border);border-radius:8px;padding:12px 14px}
.key-field :deep(.el-input__wrapper),.key-field :deep(.el-select__wrapper){background:#fff}
.crowd :deep(.el-checkbox-group){display:flex;gap:8px;flex-wrap:wrap}
.crowd :deep(.el-checkbox-group .el-checkbox){height:34px;margin:0;padding:0 14px;border:1px solid #dcdfe6;border-radius:6px}
.crowd :deep(.el-checkbox-group .el-checkbox.is-checked){border-color:var(--c-primary);background:var(--color-primary-soft,rgba(64,158,255,.08))}

/* 选题与覆盖 */
.question-picker{width:100%;min-width:0}
.question-toolbar{display:flex;gap:8px;flex-wrap:wrap}
.question-toolbar .el-input{max-width:300px}
.coverage-summary{display:flex;gap:20px;align-items:center;flex-wrap:wrap;margin:8px 0;font-size:13px;color:var(--c-sec)}
.coverage-summary strong{display:block;font-size:20px;font-weight:700;color:var(--c-text);line-height:1.4}
.coverage-rate{flex:1;min-width:220px;max-width:360px}
.coverage-scroll{max-width:100%;overflow-x:auto;margin-bottom:12px;border-radius:6px}
.coverage-matrix{border-collapse:separate;border-spacing:0;width:max-content;min-width:100%;font-size:13px;text-align:center}
.coverage-matrix th,.coverage-matrix td{min-width:52px;height:32px;padding:2px 8px;border-right:1px solid var(--c-border);border-bottom:1px solid var(--c-border);white-space:nowrap}
.coverage-matrix thead th{border-top:1px solid var(--c-border)}
.coverage-matrix th{background:#fafafa;color:var(--c-sec);font-weight:600}
.coverage-matrix tr>:first-child{position:sticky;left:0;z-index:1;min-width:72px;border-left:1px solid var(--c-border)}
.coverage-matrix .done{background:#f0f9eb;color:#529b2e;font-weight:600}
.coverage-matrix .pending{background:#fdf6ec;color:#b88230}
.coverage-matrix .warning{background:#fef0f0;color:#c45656}
.coverage-matrix .missing{background:#fff;color:#c0c4cc}
.platform-progress{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:12px 0}
.platform-progress>div{background:var(--c-soft);border:1px solid var(--c-border);border-radius:6px;padding:10px 12px}
.platform-progress strong{display:block;font-size:14px}
.platform-progress span{font-size:12px;color:var(--c-muted)}
.question-state{font-size:12px;white-space:nowrap}
.question-state.done{color:#529b2e}
.question-state.pending{color:#b88230}
.question-state.warning{color:#c45656}
.question-state.missing{color:#c0c4cc}

/* 样本详情弹窗 */
.crowd :deep(.el-dialog){border-radius:var(--radius,10px)}
.crowd :deep(.el-dialog__body){font-size:14px}

@media(max-width:1100px){
  .work-tabs button{padding:12px;gap:10px}
  .work-tabs button em{display:none}
  .nav-copy strong{font-size:15px}
}
@media(max-width:900px){
  .overview{grid-template-columns:repeat(2,1fr)}
  .panel-heading{flex-direction:column;align-items:flex-start}
  .work-panel{padding:12px 14px}
  .platform-progress{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:650px){
  .crowd-hero{flex-wrap:wrap}
  .hero-actions{flex-wrap:wrap;gap:8px}
  .work-tabs{grid-template-columns:1fr;gap:8px}
  .work-tabs button{min-height:60px}
  .project-form{grid-template-columns:1fr}
  .project-form>*{grid-column:1!important}
  .overview strong{font-size:22px}
  .step-label{display:none}
}
.source-id{display:block;color:#6b7280;font-size:12px;line-height:1.4;word-break:break-all}
.subtask-no{color:#1f5fbf}
</style>
