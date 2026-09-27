"""Bridge accepted crowd evidence into the existing task analysis and score pipeline."""
import asyncio
import json
from dataclasses import asdict
import database as db
from services import task_service
from analyzer import ResponseAnalyzer, has_effective_citation

PLATFORMS={'ds':'deepseek','deepseek':'deepseek','豆包':'doubao','doubao':'doubao','kimi':'kimi','qwen':'qwen','文心':'ernie','ernie':'ernie'}
_lock=asyncio.Lock()

async def mapping(task_id, project):
    task=await db.get_task(task_id)
    if not task:raise ValueError('所属评测任务不存在')
    mk=PLATFORMS.get(project['platform'].lower())
    if not mk:raise ValueError('该采集平台尚未配置评分映射')
    questions=await db.get_questions(active_only=False,brand_id=task.get('brand_id') or 'ucloud')
    by_text={}
    for q in questions:
        if q['id'] in task['question_ids']:by_text.setdefault(q['question'].strip(),[]).append(q['id'])
    ids=[]
    for text in project['questions']:
        matches=by_text.get(text.strip(),[])
        if len(matches)!=1:raise ValueError('题目必须唯一匹配大任务中的原题，请从所属任务导入题目：'+text[:80])
        ids.append(matches[0])
    if len(set(ids))!=len(ids):raise ValueError('众包题目不能重复')
    return {'task_id':task_id,'task_name':task['name'],'model_key':mk,'question_ids':ids,'brand_id':task.get('brand_id') or 'ucloud'}

def brand_name(brand_id):
    try:
        p=db.get_brand_profile_by_id(brand_id)
        return (p.brand_name or p.company_name or brand_id).strip() or brand_id
    except Exception:
        return brand_id

def lineage_for(link):
    """品牌 / 大任务 / 子任务 / 题 —— 传出去和收回来都用这一串识别归属。"""
    return {'brand_id':link['brand_id'],'brand_name':brand_name(link['brand_id']),'task_id':link['task_id'],
            'task_name':link['task_name'],'question_ids':list(link['question_ids'])}

async def attach(store,project_id,task_id):
    async with _lock:
        p=next((p for p in store.projects() if p['id']==project_id),None)
        if not p:raise ValueError('众包项目不存在')
        old=p.get('evaluation')
        if old and old['task_id']!=task_id:raise ValueError('已关联评测任务，不能改绑以免评分串任务')
        link=await mapping(task_id,p)
        link.update(batch_id='crowd_'+project_id,run_id='crowd_run_'+project_id)
        batch=await db.get_run_by_batch_id(link['batch_id'])
        if not batch:
            await db.add_task_batch(link['run_id'],task_id,link['batch_id'],'众包 · '+p['title'],[link['model_key']],link['question_ids'],{link['model_key']:link['question_ids']},config={'source':'crowd','crowd_project':project_id})
            await db.set_batch_status(link['run_id'],'crowd_collecting',0)
        with store.connect() as c:
            row=c.execute('SELECT body FROM projects WHERE id=?',(project_id,)).fetchone()
            body=json.loads(row[0]);body['evaluation']=link
            c.execute('UPDATE projects SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),project_id))
        store.assign_lineage(project_id,lineage_for(link))
        store.stamp_existing(project_id)
    return await sync(store,project_id)

async def sync(store,project_id):
    async with _lock:
        p=next((p for p in store.projects() if p['id']==project_id),None)
        if not p or not p.get('evaluation'):return {'linked':False}
        link=p['evaluation'];task=await db.get_task(link['task_id'])
        if not task or not await db.get_run_by_batch_id(link['batch_id']):raise ValueError('所属任务或众包批次已删除，请核对后重新关联')
        existing={r['question_id']:r for r in await db.get_task_results(link['task_id'],link['model_key'])}
        accepted=sorted((s for s in store.samples() if s['project']==project_id and s['status']=='accepted'),key=lambda s:(s['created'],s['id']))
        chosen={}
        for s in accepted:chosen.setdefault(link['question_ids'][s['question']],s)
        analyzer=ResponseAnalyzer(brand_profile=db.get_brand_profile_by_id(link['brand_id']))
        imported=0;conflicts=[]
        for qid,s in chosen.items():
            if qid in existing:
                if existing[qid].get('batch_id')!=link['batch_id']:conflicts.append(qid)
                continue
            b=s['body']
            result=analyzer.analyze(qid,link['model_key'],p['platform'],b['answer'],search_results=[{'url':c.get('url',''),'title':c.get('title','')} for c in b['citations'] if c.get('url')])
            data=asdict(result);data['recommendation_strength']=data.pop('ucloud_recommendation_strength');data['has_citation']=has_effective_citation(result);data['error_message']=None
            await db.save_task_analysis_result(link['task_id'],link['batch_id'],link['run_id'],data)
            imported+=1
        await task_service.recalculate_task_scores(link['task_id'])
        count=len(await db.get_batch_results(link['task_id'],link['batch_id']))
        await db.set_batch_status(link['run_id'],'completed' if count==len(link['question_ids']) else 'crowd_collecting',count)
        if imported:await db.add_batch_import_log(link['task_id'],link['batch_id'],link['run_id'],imported,'crowd:accepted',None)
        return {'linked':True,'task_id':link['task_id'],'imported':imported,'completed':count,'conflicts':conflicts}
