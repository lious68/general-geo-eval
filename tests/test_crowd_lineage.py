"""Every crowd item carries brand / task / subtask / question lineage, out and back."""
import asyncio
import pytest
import database as db
from crowd_store import CrowdStore
from services import crowd_evaluation as bridge
from test_crowd import sample


def test_lineage_out_and_back(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'geo.db'))

    async def run():
        await db.init_db()
        qs = (await db.get_questions(active_only=True))[:3]
        await db.create_task('大任务A', '大任务A', [q['id'] for q in qs], brand_id='ucloud')
        store = CrowdStore(tmp_path / 'crowd.db')
        mk = lambda plat, qq: store.create(dict(title='x', platform=plat, entry_url='https://www.kimi.com/zh', questions=[q['question'] for q in qq]))
        p1, p2 = mk('kimi', qs[:2]), mk('豆包', qs[1:])
        await bridge.attach(store, p1['id'], '大任务A')
        await bridge.attach(store, p2['id'], '大任务A')
        by = {p['id']: p for p in store.projects()}
        l1, l2 = by[p1['id']]['lineage'], by[p2['id']]['lineage']
        assert (l1['subtask_no'], l2['subtask_no']) == (1, 2)
        assert l1['brand_id'] == 'ucloud' and l1['task_id'] == '大任务A'
        assert l1['label'].endswith('/ 大任务A / 子任务01·kimi')

        # outbound: every assignment in the lease names its source
        lease = store.claim('zhun:7', p2['id'])
        a0 = lease['assignments'][0]
        assert a0['source'] == l2['label'] + ' / ' + qs[1 + a0['question']]['id']
        assert lease['project_config']['lineage']['subtask_no'] == 2

        # inbound: the sample is stamped at submit and keeps it even if the project is renamed later
        store.start('zhun:7', a0['id'])
        body = sample(lease); body.update(platform='豆包')
        sid = store.submit('zhun:7', body)['id']
        with store.connect() as c:
            c.execute("UPDATE projects SET body=json_set(body,'$.lineage.label','改名') WHERE id=?", (p2['id'],))
        s = store.samples(sample_id=sid)[0]
        assert s['source_label'] == a0['source']
        assert s['source']['question_id'] == qs[1 + a0['question']]['id'] and s['source']['subtask_no'] == 2

        # re-attach keeps the number; cannot move to another task
        assert store.assign_lineage(p1['id'], bridge.lineage_for(by[p1['id']]['evaluation']))['subtask_no'] == 1
        with pytest.raises(ValueError):
            store.assign_lineage(p1['id'], dict(bridge.lineage_for(by[p1['id']]['evaluation']), task_id='other'))

    asyncio.run(run())


def test_backfill_existing_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'geo.db'))

    async def run():
        await db.init_db()
        qs = (await db.get_questions(active_only=True))[:1]
        await db.create_task('T', 'T', [q['id'] for q in qs], brand_id='ucloud')
        store = CrowdStore(tmp_path / 'crowd.db')
        p = store.create(dict(title='old', platform='kimi', entry_url='https://www.kimi.com/zh', questions=[qs[0]['question']]))
        lease = store.claim('zhun:1', p['id']); store.start('zhun:1', lease['assignments'][0]['id'])
        body = sample(lease); body.update(platform='kimi')
        sid = store.submit('zhun:1', body)['id']
        assert store.samples(sample_id=sid)[0]['source_label'] is None  # legacy: no lineage yet
        await bridge.attach(store, p['id'], 'T')  # attach backfills
        assert store.samples(sample_id=sid)[0]['source_label'].endswith('/ T / 子任务01·kimi / ' + qs[0]['id'])
        assert store.stamp_existing(p['id']) == 0  # idempotent

    asyncio.run(run())


def test_create_requires_task():
    from fastapi.testclient import TestClient
    import app as geo_app
    from routers import auth
    geo_app.app.dependency_overrides[auth.get_current_user] = lambda: {'role': 'admin', 'username': 'a'}
    try:
        r = TestClient(geo_app.app).post('/api/crowd/admin/projects', json=dict(title='t', platform='kimi', entry_url='https://www.kimi.com/zh', questions=['q']))
        assert r.status_code == 400 and '大任务' in r.json()['detail']
    finally:
        geo_app.app.dependency_overrides.clear()
