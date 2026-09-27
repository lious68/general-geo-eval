"""Admin API plus TLS/SSH-protected service gateway for zhun.ai."""
import hmac
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from routers.auth import get_current_user
from crowd_store import CrowdStore

router = APIRouter(prefix='/api/crowd', tags=['crowd'])

def store():
    return CrowdStore(os.environ.get('GEO_CROWD_DB', str(Path(__file__).resolve().parents[2] / 'data' / 'crowd.db')))

async def admin(user=Depends(get_current_user)):
    if user.get('role') != 'admin':
        raise HTTPException(403, '需要管理员权限')
    return user

def invoke(fn, *args):
    try:
        return fn(*args)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from None

@router.get('/admin/projects')
def projects(user=Depends(admin)):
    return store().projects()

@router.post('/admin/projects')
async def create(body: dict, user=Depends(admin)):
    # 传出去的每道题都要能追溯到 品牌/大任务/子任务/题，所以新项目必须先选所属大任务。
    if not body.get('task_id'):raise HTTPException(400,'请先选择所属评测任务（大任务），题目将按 品牌/大任务/子任务/题 编号后再传出')
    from services import crowd_evaluation
    try:
        await crowd_evaluation.mapping(body['task_id'],body)
        p=store().create(body)
        await crowd_evaluation.attach(store(),p['id'],body['task_id'])
        return p
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.post('/admin/projects/{project}/state')
def state(project: str, body: dict, user=Depends(admin)):
    if type(body.get('active')) is not bool:
        raise HTTPException(400, 'active 必须是布尔值')
    invoke(store().active, project, body['active'])
    return {'ok': True}

@router.post('/admin/projects/{project}/delete')
def delete_project(project: str, user=Depends(admin)):
    return invoke(store().delete_project, project)

@router.get('/admin/samples')
def samples(user=Depends(admin)):
    return [{k:v for k,v in s.items() if k!='body'} for s in store().samples()]

@router.get('/admin/samples/{sample_id}')
def sample_detail(sample_id: str,user=Depends(admin)):
    rows=store().samples(sample_id=sample_id)
    if not rows:raise HTTPException(404,'样本不存在')
    return rows[0]

@router.post('/admin/projects/{project}/link-code')
def link_code(project: str,user=Depends(admin)):
    return invoke(store().link_code,project)

@router.post('/admin/samples/{sample}/review')
async def review(sample: str, body: dict, user=Depends(admin)):
    result=invoke(store().review,sample,body.get('decision'),body.get('reason',''),user.get('username','admin'),body.get('confirmed',False))
    if result['status']=='accepted':
        from services import crowd_evaluation
        p=next(s['project'] for s in store().samples() if s['id']==sample)
        try:result['evaluation']=await crowd_evaluation.sync(store(),p)
        except Exception:result['sync_error']='验收已保存，但评分同步失败，请点击项目的同步评分重试'
    return result

@router.post('/admin/projects/{project}/evaluation')
async def evaluation(project: str,body:dict,user=Depends(admin)):
    from services import crowd_evaluation
    try:return await crowd_evaluation.attach(store(),project,body.get('task_id'))
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.post('/admin/projects/{project}/lineage')
async def backfill_lineage(project: str,user=Depends(admin)):
    """补编号：按项目已关联的大任务盖上 品牌/大任务/子任务 编号，并给已有样本补盖来源编号。不改回答和分数。"""
    from services import crowd_evaluation
    s=store();p=next((p for p in s.projects() if p['id']==project),None)
    if not p:raise HTTPException(404,'项目不存在')
    if not p.get('evaluation'):raise HTTPException(400,'项目未关联大任务，请先关联')
    lin=invoke(s.assign_lineage,project,crowd_evaluation.lineage_for(p['evaluation']))
    return {'lineage':lin,'stamped':s.stamp_existing(project)}

@router.post('/admin/projects/{project}/sync-evaluation')
async def sync_evaluation(project: str,user=Depends(admin)):
    from services import crowd_evaluation
    try:return await crowd_evaluation.sync(store(),project)
    except ValueError as exc:raise HTTPException(400,str(exc))

@router.post('/gateway/{action}')
async def gateway(action: str, body: dict, request: Request):
    secret = os.environ.get('GEO_CROWD_SECRET', '')
    if len(secret) < 32 or not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + secret):
        raise HTTPException(401, '服务认证失败')
    s = store()
    if action == 'review':
        sample_id=body.get('sample')
        rows=s.samples(sample_id=sample_id) if isinstance(sample_id,str) and sample_id else []
        if not rows:raise HTTPException(404,'样本不存在')
        project=next((p for p in s.projects() if p['id']==rows[0]['project']),None)
        owner=(project or {}).get('task_link') or {}
        if not owner.get('owner') or owner['owner']!=body.get('owner'):raise HTTPException(403,'只有发布者可验收')
        result=invoke(s.review,sample_id,'accepted','发布者批量验收通过','zhun:'+str(body['owner']))
        from services import crowd_evaluation
        try:result['evaluation']=await crowd_evaluation.sync(s,rows[0]['project'])
        except Exception:result['sync_error']='验收已保存，评分同步失败，请在 GEO 同步评分'
        return result
    if action == 'workflow':return s.workflow_feed()
    if action == 'identities':return invoke(s.identities,body.get('users',[]))
    if action == 'link-task':return invoke(s.link_task,body.get('code',''),body.get('link',{}),body.get('expected_project'))
    if action == 'import-preview':return invoke(s.import_preview,body.get('code',''))
    if action == 'projects':
        return [{k: v for k, v in p.items() if k != 'questions'} | {'question_count': len(p['questions'])} for p in s.projects()]
    worker = body.get('worker')
    if not isinstance(worker, str) or not worker.startswith('zhun:'):
        raise HTTPException(400, '缺少参与者身份')
    if action == 'withdraw':return invoke(s.withdraw,worker,body.get('project'))
    if action == 'claim':
        return invoke(s.claim, worker, body.get('project'))
    if action in ('heartbeat', 'release'):
        return invoke(s.heartbeat, worker, body.get('lease'), action == 'release')
    if action == 'submit':
        return invoke(s.submit, worker, body.get('sample', {}))
    if action == 'start':
        return invoke(s.start, worker, body.get('assignment'))
    if action == 'samples':
        return [{k: v for k, v in sample.items() if k != 'body'} for sample in s.samples(worker)]
    raise HTTPException(404, '未知操作')
