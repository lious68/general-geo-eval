import importlib.util
from pathlib import Path
import pytest
import io
import json
import urllib.error
from test_crowd import sample

spec=importlib.util.spec_from_file_location('crowd_client',Path(__file__).resolve().parents[1]/'skills/geo-crowd/scripts/client.py')
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)

def test_device_encryption():
    secret=b'test-device-token'
    encrypted=client.protect(secret)
    assert client.protect(encrypted,True)==secret

def test_masked_binding_paste_and_edit():
    keys=iter('Ab_9-\bX\xe0K\r')
    output=io.StringIO()
    assert client.masked_console_input(lambda:next(keys),output)=='Ab_9X'
    assert output.getvalue()=='*****\b \b*\n'

def test_masked_binding_clear_and_cancel():
    keys=iter('old\x15new\r');output=io.StringIO()
    assert client.masked_console_input(lambda:next(keys),output)=='new'
    assert 'old' not in output.getvalue() and 'new' not in output.getvalue()
    with pytest.raises(KeyboardInterrupt):
        client.masked_console_input(lambda:'\x03',io.StringIO())

def test_outbox_survives_network_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(client,'HOME',tmp_path)
    path=tmp_path/'outbox'/'sample.json';client.save(path,{'assignment_id':'a'*32})
    def failed(*args,**kwargs):raise OSError('offline')
    monkeypatch.setattr(client,'request',failed)
    with pytest.raises(OSError):client.upload(path)
    assert path.exists()
    monkeypatch.setattr(client,'request',lambda *a,**k:{'data':{'id':'receipt'}})
    assert client.upload(path)['data']['id']=='receipt'
    assert not path.exists()
    assert client.read(tmp_path/'receipts'/'sample.json')['data']['id']=='receipt'
    archived=list((tmp_path/'archive'/'sample').glob('*.json'))
    assert len(archived)==1 and client.read(archived[0])=={'assignment_id':'a'*32}

def valid_sample():
    return sample({'assignments':[{'id':'a'*32,'prompt':'q1'}]})

def test_preflight_contract(tmp_path):
    body=valid_sample()
    assert client.validate_sample(body)['valid']
    body['citations']=[{'kind':'citation','url':None}]
    with pytest.raises(ValueError,match=r'citations\[0\].url'):client.validate_sample(body)
    body=valid_sample();body['evidence']['screenshots']=[]
    with pytest.raises(ValueError,match='1–20'):client.validate_sample(body)
    body=valid_sample();body['conditions']['collected_at']='2026-09-25T14:00:00'
    with pytest.raises(ValueError,match='collected_at'):client.validate_sample(body)

def test_prepare_relative_files_dry_run_keeps_source(tmp_path,monkeypatch):
    body=valid_sample();body['screenshot_paths']=['answer.png'];body['evidence'].pop('screenshots')
    (tmp_path/'answer.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
    source=tmp_path/'sample.json';client.save(source,body);before=source.read_bytes()
    monkeypatch.setattr(client,'HOME',tmp_path/'unbound')
    monkeypatch.setattr(client.sys,'argv',['client.py','submit','--dry-run','--file',str(source)])
    assert client.main()['screenshots']==1
    assert not (tmp_path/'unbound').exists()
    assert source.read_bytes()==before

def test_public_http_error_redaction(monkeypatch):
    exc=urllib.error.HTTPError('https://zhun.ai',400,'Bad Request',{},io.BytesIO(json.dumps({'error':{'message':'缺少截图 secret-code','field':'evidence.screenshots'},'credential':'do-not-print'}).encode()))
    class Opener:
        def open(self,*a,**kw):raise exc
    monkeypatch.setattr(client.urllib.request,'build_opener',lambda *a:Opener())
    with pytest.raises(client.ServiceError) as caught:client.request('bind',{'code':'secret-code'},anonymous=True,base_url='https://zhun.ai')
    assert '缺少截图' in str(caught.value)
    assert 'secret-code' not in str(caught.value) and 'do-not-print' not in str(caught.value)
    assert caught.value.status==400

def test_missing_binding_message(tmp_path,monkeypatch):
    monkeypatch.setattr(client,'HOME',tmp_path)
    with pytest.raises(ValueError,match='尚未绑定'):client.request('projects')

def test_rejected_upload_retained_for_correction(tmp_path,monkeypatch):
    monkeypatch.setattr(client,'HOME',tmp_path)
    path=tmp_path/'outbox'/('a'*32+'.json');client.save(path,valid_sample())
    def rejected(*a,**kw):raise client.ServiceError(400,'引用链接必须为字符串')
    monkeypatch.setattr(client,'request',rejected)
    with pytest.raises(client.ServiceError,match='引用链接'):client.upload(path)
    assert not path.exists()
    assert len(list((tmp_path/'failed').rglob('*.json')))==1
    assert len(list((tmp_path/'archive').rglob('*.json')))==1

def test_heartbeat_error_visible_and_bounded(tmp_path,monkeypatch):
    monkeypatch.setattr(client,'HOME',tmp_path)
    client.save(tmp_path/'lease.json',{'id':'a'*32,'expires':123})
    def offline(*a,**kw):raise ValueError('网络连接失败')
    monkeypatch.setattr(client,'request',offline);monkeypatch.setattr(client.time,'sleep',lambda _:None)
    client.heartbeat_loop('a'*32)
    state=client.read(tmp_path/'heartbeat.json')
    assert state['state']=='failed' and state['remaining_attempts']==2877
    assert state['last_error']=='网络连接失败'

def test_heartbeat_success_reports_expiry(tmp_path,monkeypatch):
    monkeypatch.setattr(client,'HOME',tmp_path)
    client.save(tmp_path/'lease.json',{'id':'a'*32,'expires':123})
    monkeypatch.setattr(client,'request',lambda *a,**kw:{'data':{'expires':9999999999}})
    monkeypatch.setattr(client.time,'sleep',lambda _:client.save(tmp_path/'lease.json',None))
    client.heartbeat_loop('a'*32)
    state=client.read(tmp_path/'heartbeat.json')
    assert state['state']=='stopped' and state['last_success'] and state['expires']==9999999999
