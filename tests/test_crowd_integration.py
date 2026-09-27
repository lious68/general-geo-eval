"""Real loopback HTTP integration; set ZHUN_SOURCE_ROOT when repos aren't siblings."""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
from http.cookiejar import CookieJar
import json
import pytest
from fastapi import FastAPI
import uvicorn
from routers import crowd
from test_crowd import sample


def test_zhun_to_geo_full_flow(tmp_path, monkeypatch):
    root = Path(os.environ.get('ZHUN_SOURCE_ROOT', str(Path(__file__).resolve().parents[2] / 'youhuo')))
    if not (root / 'server.py').exists():
        pytest.skip('Set ZHUN_SOURCE_ROOT to test the other repository')
    monkeypatch.syspath_prepend(str(root))
    spec = importlib.util.spec_from_file_location('zhun_integration_server', root / 'server.py')
    zhun = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(zhun)
    monkeypatch.setattr(zhun, 'DATA', tmp_path / 'zhun')
    monkeypatch.setattr(zhun, 'DEMO', True)
    monkeypatch.setenv('GEO_CROWD_DB', str(tmp_path / 'geo.db'))
    monkeypatch.setenv('GEO_CROWD_SECRET', 'integration-only-secret-' + 'x' * 32)
    app = FastAPI(); app.include_router(crowd.router)
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    uv = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=uv.run, kwargs={'sockets':[sock]}, daemon=True); thread.start()
    monkeypatch.setenv('GEO_CROWD_URL', f'http://127.0.0.1:{port}')
    zhun.init()
    http = zhun.ThreadingHTTPServer(('127.0.0.1', 0), zhun.Handler)
    front = threading.Thread(target=http.serve_forever, daemon=True); front.start()
    base = f'http://127.0.0.1:{http.server_port}'
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    def call(action, body=None, token=None):
        headers = {'Content-Type':'application/json'}
        if token: headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(base + action, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with browser.open(req, timeout=10) as response: return json.load(response)
    try:
        deadline = time.monotonic() + 10
        while not uv.started and time.monotonic() < deadline: time.sleep(.05)
        assert uv.started
        p = crowd.store().create(dict(title='Integration', platform='test', entry_url='https://example.com', questions=['q1'], conditions={'new_conversation':True}))
        call('/api/login', {'email':'owner@demo.local', 'password':'Demo12345!'})
        task=call('/api/tasks',dict(kind='skill',category='软件测试',title='GEO integration',description='每条验收通过样本报酬 2 元',requirements='完整原始证据',target='',amount=200,seats=2,deadline='2099-12-31',city='远程'))
        code=crowd.store().link_code(p['id'])['code']
        linked=call('/api/geo/link-task',dict(task_id=task['id'],code=code,confirmed_unit_price=True))
        assert linked['project']==p['id'] and linked['target_samples']==1
        assert call('/api/geo/link-task',dict(task_id=task['id'],code=code,confirmed_unit_price=True))==linked
        call('/api/login', {'email':'worker@demo.local', 'password':'Demo12345!'})
        assert call('/api/geo/projects')['projects'][0]['question_count'] == 1
        call('/api/geo/enroll', {'project':p['id']})
        code = call('/api/geo/binding', {})['code']
        token = call('/api/geo/bind', {'code':code})['token']
        lease = call('/api/geo/claim', {'project':p['id']}, token)['data']
        assert call('/api/geo/start', {'assignment':lease['assignments'][0]['id']}, token)['data']['started']
        raw = sample(lease);raw['citations_state']='incomplete'
        receipt = call('/api/geo/submit', {'sample':raw}, token)['data']
        assert receipt['status'] == 'pending'
        assert call('/api/geo/submit', {'sample':raw}, token)['data'] == receipt
        with pytest.raises(ValueError):crowd.store().review(receipt['id'],'accepted','checked','test-admin')
        crowd.store().review(receipt['id'],'revision','补充真实引用链接','test-admin')
        assert call('/api/work')['claims'][0]['status']=='revision'
        before=call('/api/notifications')
        assert any('补充' in n['title'] for n in before['items'])
        assert call('/api/notifications')==before
        corrected=dict(raw,citations_state='complete',citations=[dict(kind='citation',title='source',url='https://example.com/article')])
        revised=call('/api/geo/submit', {'sample':corrected}, token)['data']
        assert revised['version']==1 and revised['id']==receipt['id']
        with crowd.store().connect() as c:
            assert json.loads(c.execute('SELECT body FROM samples WHERE id=?',(receipt['id'],)).fetchone()[0])['citations_state']=='incomplete'
            assert c.execute('SELECT COUNT(*) FROM sample_versions').fetchone()[0]==1
        crowd.store().review(receipt['id'], 'accepted', 'integration evidence checked', 'test-admin')
        assert call('/api/geo/samples', token=token)['data'][0]['status'] == 'accepted'
        work=call('/api/work')['claims'][0]
        assert work['status']=='approved' and work['amount']==200 and work['geo_project']==p['id']
        with pytest.raises(urllib.error.HTTPError):call('/api/geo/settle',dict(sample=receipt['id'],confirmed=True,reference='test-only'))
        call('/api/login', {'email':'owner@demo.local', 'password':'Demo12345!'})
        assert call('/api/geo/workflow')['samples'][0]['can_settle']
        assert call('/api/geo/settle',dict(sample=receipt['id'],confirmed=True,reference='test-only'))=={'ok':True}
        with pytest.raises(urllib.error.HTTPError):call('/api/geo/settle',dict(sample=receipt['id'],confirmed=True,reference='test-only'))
        assert not call('/api/geo/workflow')['samples'][0]['can_settle']
        call('/api/geo/release', {'lease':lease['id']}, token)
        imported=crowd.store().create(dict(title='Carry questions',platform='豆包',entry_url='https://example.com',questions=['第一题','第二题'],replicas=2,conditions={'new_conversation':True}))
        import_code=crowd.store().link_code(imported['id'])['code']
        preview=call('/api/geo/import',{'code':import_code})
        assert preview['questions']==['第一题','第二题']
        with pytest.raises(urllib.error.HTTPError):call('/api/geo/import',{'code':import_code},token)
        payload=dict(kind='skill',category='软件测试',title='Imported GEO',description='真实导入',requirements='完整证据',amount=200,seats=2,deadline='2099-12-31',city='远程',geo_code=import_code,confirmed_unit_price=True)
        drafted=call('/api/tasks',payload)
        assert drafted['geo_pending']
        assert call('/api/tasks',payload)['id']==drafted['id']
        assert drafted['id'] not in [t['id'] for t in call('/api/tasks')]
        assert call('/api/tasks/'+str(drafted['id']))['geo_config']['questions']==imported['questions']
        call('/api/login', {'email':'worker@demo.local', 'password':'Demo12345!'})
        with pytest.raises(urllib.error.HTTPError):call('/api/claim',{'task_id':drafted['id']})
        call('/api/login', {'email':'owner@demo.local', 'password':'Demo12345!'})
        body=dict(task_id=drafted['id'],code=import_code,confirmed_unit_price=True)
        assert call('/api/geo/link-task',body)['target_samples']==4
        assert call('/api/geo/link-task',body)['project']==imported['id']
        assert drafted['id'] in [t['id'] for t in call('/api/tasks')]
        assert call('/api/tasks/'+str(drafted['id']))['geo_project']==imported['id']
        with zhun.db() as c:assert c.execute('SELECT amount FROM orders WHERE task_id=?',(drafted['id'],)).fetchone()[0]==800
        with browser.open(base + '/geo/index.html') as response: assert response.status == 200
    finally:
        http.shutdown(); http.server_close(); front.join(timeout=5)
        uv.should_exit = True; thread.join(timeout=5); sock.close()
