import base64
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from crowd_store import CrowdStore
from routers import crowd

@pytest.fixture
def store(tmp_path):
    return CrowdStore(tmp_path / 'crowd.db')

def project(store, **kw):
    return store.create(dict(title='test', platform='test', entry_url='https://example.com', questions=['q1','q2'], batch_size=1, **kw))

def sample(lease):
    a=lease['assignments'][0]
    return dict(assignment_id=a['id'], prompt=a['prompt'], platform='test', answer='原始回答', answer_complete=True,
        citations_state='none_visible', citations=[], conditions={'new_conversation':True,'model':'unknown','web_search':'unknown','collected_at':'2026-09-25T10:00:00+08:00'},
        evidence={'page_text':a['prompt']+' 原始回答','screenshots':[{'mime':'image/png','base64':base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()}]})

def test_concurrent_allocation_and_resume(store):
    p=project(store)
    with ThreadPoolExecutor(max_workers=8) as pool:
        leases=list(pool.map(lambda i:store.claim('zhun:'+str(i),p['id']),range(8)))
    assert len([x for x in leases if x])==1
    lease=next(x for x in leases if x)
    assert store.claim(lease['worker'],p['id'])['id']==lease['id']

def test_idempotency_and_identity(store):
    p=project(store);lease=store.claim('zhun:1',p['id']);store.start('zhun:1',lease['assignments'][0]['id']);body=sample(lease)
    with pytest.raises(ValueError):store.submit('zhun:2',body)
    result=store.submit('zhun:1',body)
    assert store.submit('zhun:1',body)==result
    with pytest.raises(ValueError):store.submit('zhun:1',dict(body,answer='changed'))
    assert len(store.samples())==1

def test_expired_and_replicas(store):
    p=project(store,replicas=2);lease=store.claim('zhun:1',p['id'])
    store.start('zhun:1',lease['assignments'][0]['id'])
    with store.connect() as c:c.execute('UPDATE leases SET expires=0 WHERE id=?',(lease['id'],))
    result=store.submit('zhun:1',sample(lease));assert result['status']=='late'
    with pytest.raises(ValueError):store.review(result['id'],'accepted','reason','admin')
    with pytest.raises(ValueError):store.heartbeat('zhun:1',lease['id'])
    new=store.claim('zhun:1',p['id']);assert new['assignments'][0]['question']==1
    assert store.claim('zhun:2',p['id'])['assignments'][0]['question']==0

def test_review_completeness_and_pause(store):
    p=project(store);lease=store.claim('zhun:1',p['id'])
    store.start('zhun:1',lease['assignments'][0]['id']);body=sample(lease);body['citations_state']='incomplete'
    result=store.submit('zhun:1',body)
    with pytest.raises(ValueError):store.review(result['id'],'accepted','checked','admin')
    store.review(result['id'],'rejected','missing links','admin')
    store.heartbeat('zhun:1',lease['id'],True)
    assert store.claim('zhun:2',p['id'])['assignments'][0]['question']==0
    store.active(p['id'],False)
    with pytest.raises(ValueError):store.claim('zhun:3',p['id'])

def test_task_link_identity_and_trial_boundary(store):
    p=project(store)
    link=dict(task_id=123,owner=1,unit_amount=200,title='task',url='https://zhun.ai/#task/123')
    code=store.link_code(p['id'])['code']
    result=store.link_task(code,link)
    assert result==dict(project=p['id'],target_samples=2)
    assert store.link_task(code,link)==result
    other=project(store)
    with pytest.raises(ValueError):store.link_task(store.link_code(other['id'])['code'],dict(link,title='changed'))
    lease=store.claim('zhun:1',other['id'])
    with pytest.raises(ValueError):store.link_task(store.link_code(other['id'])['code'],dict(link,task_id=124))

def test_revision_reserves_quota_and_preserves_original(store):
    p=store.create(dict(title='test',platform='test',entry_url='https://example.com',questions=['q1']))
    lease=store.claim('zhun:1',p['id']);store.start('zhun:1',lease['assignments'][0]['id'])
    body=sample(lease);body['citations_state']='incomplete';sid=store.submit('zhun:1',body)['id']
    store.review(sid,'revision','missing refs','admin')
    store.heartbeat('zhun:1',lease['id'],True)
    assert store.claim('zhun:2',p['id']) is None
    corrected=dict(body,citations_state='complete',citations=[dict(kind='citation',url='https://example.com/ref')])
    assert store.submit('zhun:1',corrected)['status']=='pending'
    store.review(sid,'accepted','checked','admin')
    assert store.samples()[0]['review']['reason']=='checked'
    assert store.samples()[0]['version']==1

def test_force_acceptance_requires_confirmation_and_preserves_evidence(store):
    p=project(store,conditions={'web_search':'on'})
    lease=store.claim('zhun:1',p['id']);store.start('zhun:1',lease['assignments'][0]['id'])
    body=sample(lease);body['citations_state']='incomplete'
    sid=store.submit('zhun:1',body)['id']
    with pytest.raises(ValueError):store.review(sid,'accepted','checked','admin')
    with pytest.raises(ValueError):store.review(sid,'force_accepted','checked','admin')
    with pytest.raises(ValueError):store.review(sid,'force_accepted','','admin',True)
    assert store.review(sid,'force_accepted','人工核对，接受已记录的引用缺项','admin',True)['status']=='accepted'
    row=store.samples()[0]
    assert row['forced_acceptance'] and row['review']['reviewer']=='admin'
    assert row['review']['decision']=='force_accepted'
    assert row['body']==body and len(row['review_blockers'])==2
    with pytest.raises(ValueError):store.review(sid,'force_accepted','again','admin',True)

def test_missing_evidence_rejected(store):
    p=project(store);lease=store.claim('zhun:1',p['id']);store.start('zhun:1',lease['assignments'][0]['id']);body=sample(lease)
    body['evidence']['screenshots']=[]
    with pytest.raises(ValueError):store.submit('zhun:1',body)

def test_pacing_and_condition_mismatch(store):
    p=project(store,conditions={'web_search':'on'})
    lease=store.claim('zhun:1',p['id']);aid=lease['assignments'][0]['id']
    assert store.start('zhun:1',aid)=={'started':True,'resume_only':False}
    assert store.start('zhun:1',aid)['resume_only'] is True
    receipt=store.submit('zhun:1',sample(lease))
    with pytest.raises(ValueError):store.review(receipt['id'],'accepted','checked','admin')
    store.heartbeat('zhun:1',lease['id'],True)
    second=store.claim('zhun:1',p['id']);second_id=second['assignments'][0]['id']
    result=store.start('zhun:1',second_id)
    assert result['started'] is True
    store.active(p['id'],False)
    with pytest.raises(ValueError):store.start('zhun:1',second_id)

def test_api_auth(tmp_path,monkeypatch):
    monkeypatch.setenv('GEO_CROWD_DB',str(tmp_path/'api.db'))
    monkeypatch.setenv('GEO_CROWD_SECRET','s'*32)
    app=FastAPI();app.include_router(crowd.router)
    with TestClient(app) as c:
        assert c.get('/api/crowd/admin/projects').status_code==401
        assert c.post('/api/crowd/gateway/projects',json={}).status_code==401
        assert c.post('/api/crowd/gateway/projects',json={},headers={'Authorization':'Bearer '+'s'*32}).json()==[]
        app.dependency_overrides[crowd.get_current_user]=lambda:{'role':'viewer'}
        assert c.get('/api/crowd/admin/projects').status_code==403
        app.dependency_overrides[crowd.get_current_user]=lambda:{'role':'admin'}
        assert c.get('/api/crowd/admin/projects').status_code==200


def test_lease_lasts_a_day_without_heartbeat(store, monkeypatch):
    now=1800000000
    monkeypatch.setattr('crowd_store.time.time',lambda:now)
    p=project(store);lease=store.claim('zhun:1',p['id'])
    assert lease['expires']==now+172800
    store.start('zhun:1',lease['assignments'][0]['id'])
    now+=47*3600
    assert store.submit('zhun:1',sample(lease))['status']=='pending'
    assert store.heartbeat('zhun:1',lease['id'])['expires']==now+172800


def test_late_force_accept_and_quota_conflict(store):
    p=project(store);lease=store.claim('zhun:1',p['id'])
    store.start('zhun:1',lease['assignments'][0]['id'])
    with store.connect() as c:c.execute('UPDATE leases SET expires=0 WHERE id=?',(lease['id'],))
    sid=store.submit('zhun:1',sample(lease))['id']
    with pytest.raises(ValueError):store.review(sid,'force_accepted','checked','admin')
    replacement=store.claim('zhun:2',p['id'])
    with pytest.raises(ValueError,match='名额'):store.review(sid,'force_accepted','checked','admin',True)
    store.heartbeat('zhun:2',replacement['id'],True)
    assert store.review(sid,'force_accepted','迟交十六秒，已核对证据','admin',True)['status']=='accepted'
    row=store.samples()[0]
    assert row['forced_acceptance'] and '迟交样本' in row['review']['reason']
    with pytest.raises(ValueError):store.review(sid,'force_accepted','again','admin',True)

@pytest.mark.parametrize('released', [True, False])
def test_retry_unsubmitted_attempt(store, released):
    p=project(store)
    old=store.claim('zhun:1',p['id'])
    with store.connect() as c:
        c.execute('UPDATE leases SET released=?,expires=0 WHERE id=?',(int(released),old['id']))
    new=store.claim('zhun:1',p['id'])
    assert new['assignments'][0]['question']==0
    assert new['assignments'][0]['id']!=old['assignments'][0]['id']
    other=store.claim('zhun:2',p['id'])
    assert other is None
    store.start('zhun:1',new['assignments'][0]['id'])
    result=store.submit('zhun:1',sample(new))
    store.review(result['id'],'accepted','checked','admin')
    store.heartbeat('zhun:1',new['id'],True)
    assert [a['question'] for a in store.claim('zhun:1',p['id'])['assignments']]==[1]

def test_publisher_gateway_review_permissions(store, monkeypatch):
    p=project(store)
    code=store.link_code(p['id'])['code']
    store.link_task(code,dict(task_id=1,owner=8,unit_amount=200,title='test',url='https://zhun.ai/#task/1'))
    lease=store.claim('zhun:1',p['id']);store.start('zhun:1',lease['assignments'][0]['id'])
    body=sample(lease);body['citations_state']='incomplete'
    result=store.submit('zhun:1',body)
    monkeypatch.setattr(crowd,'store',lambda:store)
    monkeypatch.setenv('GEO_CROWD_SECRET','x'*32)
    app=FastAPI();app.include_router(crowd.router)
    client=TestClient(app)
    headers={'Authorization':'Bearer '+'x'*32}
    url='/api/crowd/gateway/review'
    assert client.post(url,json={'sample':result['id'],'owner':9},headers=headers).status_code==403
    assert client.post(url,json={'sample':result['id'],'owner':8},headers=headers).status_code==400
    assert store.samples()[0]['status']=='pending'

def test_delete_project_guards(store):
    p=project(store)
    store.link_code(p['id'])
    assert store.delete_project(p['id']) == {'ok': True}
    assert not store.projects()
    with store.connect() as c:
        assert c.execute('SELECT count(*) FROM link_codes').fetchone()[0] == 0
    p=project(store)
    store.claim('zhun:1',p['id'])
    with pytest.raises(ValueError,match='领取'):
        store.delete_project(p['id'])
    p=project(store)
    with store.connect() as c:
        c.execute('INSERT INTO task_links VALUES(?,?)',(p['id'],'{}'))
    with pytest.raises(ValueError,match='准活'):
        store.delete_project(p['id'])
    assert len(store.projects()) == 2


def test_withdraw_releases_unfinished_preserves_samples(store):
    p=project(store)
    lease=store.claim('zhun:1',p['id'])
    store.start('zhun:1',lease['assignments'][0]['id'])
    saved=store.submit('zhun:1',sample(lease))
    store.withdraw('zhun:1',p['id'])
    store.withdraw('zhun:1',p['id'])
    with pytest.raises(ValueError):store.claim('zhun:1',p['id'])
    assert store.samples()[0]['id']==saved['id']
    other=store.claim('zhun:2',p['id'])
    assert other['assignments'][0]['question']==1
    store.withdraw('zhun:2',p['id'])
    replacement=store.claim('zhun:3',p['id'])
    assert replacement['assignments'][0]['question']==1
    with pytest.raises(ValueError):store.start('zhun:2',other['assignments'][0]['id'])

def test_citation_diagnostics_reports_mentions_not_article_guess():
    d=CrowdStore.citation_diagnostics({'citations_state':'incomplete','citations':[{'url':'https://example.com'}]*3,'evidence':{'completeness_notes':['正文引用中有 2 处未能展开为完整链接']}})
    assert d['missing_mentions']==2
    assert d['collected_entries']==3 and d['unique_links']==1
    assert CrowdStore.citation_diagnostics({'citations_state':'incomplete','citations':[]})['missing_mentions'] is None


def test_all_questions_and_expand_old_lease(store,monkeypatch):
    now=1800000000
    monkeypatch.setattr('crowd_store.time.time',lambda:now)
    p=store.create(dict(title='all',platform='test',entry_url='https://example.com',questions=['q'+str(i) for i in range(60)],batch_size=5))
    first=store.claim('zhun:1',p['id'])
    assert len(first['assignments'])==60 and first['expires']==now+172800
    keep=first['assignments'][0]['id']
    with store.connect() as c:c.execute('DELETE FROM assignments WHERE lease=? AND id<>?',(first['id'],keep))
    expanded=store.claim('zhun:1',p['id'])
    assert expanded['id']==first['id'] and len(expanded['assignments'])==60
    assert keep in [a['id'] for a in expanded['assignments']]
    assert store.claim('zhun:2',p['id']) is None
    assert store.link_code(p['id'])['expires_in']==172800
