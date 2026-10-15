import json
import pytest
from test_crowd import store, project, sample

def linked(store):
    p=project(store)
    with store.connect() as c:c.execute('INSERT INTO task_links VALUES(?,?)',(p['id'],json.dumps({'task_id':24})))
    return p

def state(p, **kwargs):
    return dict(project=p['id'],task_id=24,status='deleted',can_archive=True,blockers=[],**kwargs)

def test_archive_restore_retains_link_and_audit(store):
    p=linked(store)
    with pytest.raises(ValueError,match='同步'):store.delete_project(p['id'])
    store.update_lifecycle([state(p)])
    store.delete_project(p['id'],'alice')
    assert store.projects()[0]['archived'] and not store.projects()[0]['active']
    assert store.projects()[0]['task_link']['task_id']==24
    with pytest.raises(ValueError):store.active(p['id'],True)
    with pytest.raises(ValueError):store.claim('zhun:1',p['id'])
    store.restore_project(p['id'],'bob')
    assert not store.projects()[0]['archived'] and not store.projects()[0]['active']
    with pytest.raises(ValueError):store.active(p['id'],True)
    assert [x['actor'] for x in store.project_history(p['id'])]==['bob','alice']

def test_lifecycle_fail_closed_and_transactional(store):
    p=linked(store)
    st=state(p);st['can_archive']=False;st['blockers']=['1 条已通过样本待登记付款']
    store.update_lifecycle([st])
    with pytest.raises(ValueError,match='付款'):store.delete_project(p['id'])
    st['can_archive']=True;store.update_lifecycle([st])
    with store.connect() as c:c.execute('UPDATE task_lifecycle SET updated=0')
    with pytest.raises(ValueError,match='过期'):store.delete_project(p['id'])
    st['task_id']=99
    with pytest.raises(ValueError,match='不一致'):store.update_lifecycle([st])

def test_samples_retained_and_pending_blocks(store):
    p=linked(store);lease=store.claim('zhun:1',p['id']);body=sample(lease)
    store.start('zhun:1',body['assignment_id']);sid=store.submit('zhun:1',body)['id']
    store.update_lifecycle([state(p)])
    with pytest.raises(ValueError,match='样本'):store.delete_project(p['id'])
    store.review(sid,'accepted','ok','reviewer')
    with pytest.raises(ValueError,match='付款记录'):store.delete_project(p['id'])
    store.update_lifecycle([state(p,settled_samples=[sid])]);store.delete_project(p['id'])
    assert store.samples()[0]['status']=='accepted'
    assert store.submit('zhun:1',body)['id']==sid
    assert len(store.workflow_feed()['samples'])==1
