"""Local test/demo fixture only; no browser, webhook or production execution."""
import uuid
async def seed_batch(task_id, model_keys, per_model_question_ids, delay=0):
    import database as db
    task=await db.get_task(task_id)
    batch_id='fixture_'+uuid.uuid4().hex
    run_id='fixture_run_'+uuid.uuid4().hex
    units=[{'model_key':mk,'question_ids':per_model_question_ids[mk]} for mk in model_keys]
    qids=list(dict.fromkeys(q for u in units for q in u['question_ids']))
    cfg={'version':2,'task_id':task_id,'batch_id':batch_id,'run_id':run_id,'units':units}
    await db.add_task_batch(run_id,task_id,batch_id,task['name'],model_keys,qids,per_model_question_ids,config={'source':'test_fixture'})
    return cfg
