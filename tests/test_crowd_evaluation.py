import asyncio
import pytest
import database as db
from crowd_store import CrowdStore
from services import crowd_evaluation as bridge
from services import task_service
from test_crowd import sample

def test_crowd_scores_and_coverage(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'geo.db'))
    async def run():
        await db.init_db()
        qs=(await db.get_questions(active_only=True))[:2]
        assert len(qs)==2
        await db.create_task('crowd-test','test',[q['id'] for q in qs],brand_id='ucloud')
        store=CrowdStore(tmp_path/'crowd.db')
        p=store.create(dict(title='crowd',platform='kimi',entry_url='https://www.kimi.com/zh',questions=[q['question'] for q in qs],replicas=2,batch_size=1))
        await bridge.attach(store,p['id'],'crowd-test')
        detail=await task_service.build_task_detail('crowd-test')
        assert detail['summary']['total_cells']==2 and detail['summary']['done_cells']==0
        lease=store.claim('zhun:1',p['id']);store.start('zhun:1',lease['assignments'][0]['id'])
        body=sample(lease);body.update(platform='kimi',answer='UCloud 提供云服务器。');body['evidence']['page_text']=body['prompt']+body['answer']
        sid=store.submit('zhun:1',body)['id']
        assert (await bridge.sync(store,p['id']))['completed']==0
        store.review(sid,'accepted','ok','admin')
        assert (await bridge.sync(store,p['id']))['imported']==1
        assert (await bridge.sync(store,p['id']))['imported']==0
        detail=await task_service.build_task_detail('crowd-test')
        assert detail['summary']['coverage_rate']==.5 and detail['scores']
        assert len(await db.get_task_results('crowd-test'))==1
        with pytest.raises(ValueError):await bridge.mapping('crowd-test',dict(p,questions=['not in task']))
    asyncio.run(run())
