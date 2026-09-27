"""Stdlib client. Agent operates browser; this tool handles transport and leases."""
import argparse
import base64
import ctypes
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import platform
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlsplit

HOME = Path(os.environ.get('GEO_CROWD_HOME', str(Path.home() / '.geo-crowd')))
VERSION = '20260926-client47'

class ServiceError(ValueError):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(f'HTTP {status}：{message}')

def error_message(exc, redactions=()):
    """Show only a bounded public error message, never a raw response or headers."""
    message = '服务请求失败，请稍后重试' if exc.code >= 500 else '请求未通过，请检查参数或设备绑定'
    try:
        data = json.loads(exc.read(8192))
        detail = data.get('error', data.get('detail')) if isinstance(data, dict) else None
        if isinstance(detail, dict):detail = detail.get('message')
        if isinstance(detail, str) and detail.strip():message = detail
    except (ValueError, OSError):pass
    for secret in redactions:
        if secret:message = message.replace(secret, '[已隐藏]')
    return ''.join(ch for ch in message if ch.isprintable())[:1000]

class BindingInputCancelled(KeyboardInterrupt):
    pass

def masked_console_input(read_key, output):
    """Read a Windows console code without ever echoing its characters."""
    chars = []
    while True:
        char = read_key()
        if char in ('\x00', '\xe0'):  # Function / arrow key prefix.
            read_key()
            continue
        if char in ('\r', '\n'):
            if not chars:
                continue
            output.write('\n'); output.flush()
            return ''.join(chars)
        if char in ('\x03', '\x1a'):
            output.write('\n'); output.flush()
            raise BindingInputCancelled
        if char in ('\b', '\x7f'):
            if chars:
                chars.pop(); output.write('\b \b'); output.flush()
        elif char == '\x15':  # Ctrl+U clears the current input.
            output.write('\b \b' * len(chars)); output.flush(); chars.clear()
        elif char in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' and len(chars) < 128:
            chars.append(char); output.write('*'); output.flush()

def read_binding_code():
    if os.name == 'nt' and sys.stdin.isatty():
        import msvcrt
        print('请粘贴绑定码：每个字符显示为 *，按回车确认，退格可删除，Ctrl+C 可取消。')
        print('准活一次性绑定码：', end='', flush=True)
        return masked_console_input(msvcrt.getwch, sys.stdout)
    return getpass.getpass('准活一次性绑定码（当前标准输入模式不显示星号）：')

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as f:
            temp=Path(f.name)
            json.dump(data,f,ensure_ascii=False,indent=2)
        os.chmod(temp,0o600)
        temp.replace(path)
    finally:
        if temp and temp.exists():temp.unlink()

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def protect(raw, decrypt=False):
    if os.name != 'nt':
        return raw
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    dest = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise OSError('Windows 设备凭据加密失败')
    try:
        return ctypes.string_at(dest.data, dest.size)
    finally:
        ctypes.windll.kernel32.LocalFree(dest.data)

def request(action, body=None, anonymous=False, base_url=None):
    if not anonymous and not (HOME / 'config.json').exists():
        raise ValueError('尚未绑定：请先在准活生成一次性绑定码，在本机运行 bind，再运行 projects。')
    config = {'url': base_url} if anonymous and base_url else read(HOME / 'config.json')
    base = config['url']
    url = urlsplit(base)
    if url.scheme != 'https' or url.username or url.password or url.query or url.fragment:
        raise ValueError('客户端仅支持 HTTPS 服务')
    headers = {'Content-Type': 'application/json'}
    token = ''
    if not anonymous:
        if config.get('expires', float('inf')) <= time.time():raise ValueError('设备授权已过期，请在准活生成新绑定码并重新绑定。')
        token = protect(base64.b64decode(config['credential']), True).decode()
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base.rstrip('/') + '/api/geo/' + action,
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers=headers)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise ServiceError(exc.code,error_message(exc,(token,str((body or {}).get('code',''))))) from None
    except urllib.error.URLError:
        raise ValueError('网络连接失败；待传文件已保留。恢复网络后 retry，不要重新提问。') from None

def validate_sample(sample):
    if not isinstance(sample,dict):raise ValueError('样本必须为 JSON 对象')
    aid=sample.get('assignment_id','')
    if not isinstance(aid,str) or len(aid)!=32 or any(ch not in '0123456789abcdef' for ch in aid):raise ValueError('assignment_id 必须是分配结果中的 32 位编号')
    for key in ('prompt','platform','answer'):
        if not isinstance(sample.get(key),str) or not sample[key].strip():raise ValueError(key+' 必须是非空原文字符串')
    if type(sample.get('answer_complete')) is not bool:raise ValueError('answer_complete 必须为 true 或 false')
    citations=sample.get('citations');state=sample.get('citations_state')
    if state not in ('complete','incomplete','none_visible'):raise ValueError('citations_state 必须为 complete / incomplete / none_visible')
    if not isinstance(citations,list):raise ValueError('citations 必须为数组')
    for i,c in enumerate(citations):
        field=f'citations[{i}]'
        if not isinstance(c,dict) or c.get('kind') not in ('citation','search_source'):raise ValueError(field+'.kind 必须为 citation 或 search_source')
        if not isinstance(c.get('url'),str):raise ValueError(field+'.url 必须为真实链接字符串；空卡片请记入 completeness_notes，不能填写 null')
        url=urlsplit(c['url'])
        if url.scheme not in ('http','https') or not url.hostname or url.username:raise ValueError(field+'.url 必须为完整 HTTP(S) 链接，不能猜测')
    if state=='complete' and not citations:raise ValueError('没有可见引用时用 none_visible；引用缺失时用 incomplete')
    if state=='none_visible' and citations:raise ValueError('none_visible 不能同时包含引用')
    conditions=sample.get('conditions')
    if not isinstance(conditions,dict):raise ValueError('conditions 必须为对象')
    if not isinstance(conditions.get('model'),str) or not conditions['model'].strip():raise ValueError('conditions.model 必填；无法确认写 unknown')
    if conditions.get('web_search') not in ('on','off','unknown'):raise ValueError('conditions.web_search 必须为 on / off / unknown')
    if type(conditions.get('new_conversation')) is not bool:raise ValueError('conditions.new_conversation 必须为 true 或 false')
    try:
        if datetime.fromisoformat(conditions['collected_at'].replace('Z','+00:00')).tzinfo is None:raise ValueError()
    except (KeyError,AttributeError,TypeError,ValueError):raise ValueError('conditions.collected_at 必须是带时区时间，例如 2026-09-25T14:00:00+08:00') from None
    evidence=sample.get('evidence')
    if not isinstance(evidence,dict) or not isinstance(evidence.get('page_text'),str) or not evidence['page_text'].strip():raise ValueError('evidence.page_text 必须包含当前任务页面原文')
    screenshots=evidence.get('screenshots')
    if not isinstance(screenshots,list) or not 1<=len(screenshots)<=20:raise ValueError('缺少截图：需要 1–20 张当前任务页面截图；请填写 screenshot_paths')
    for i,shot in enumerate(screenshots):
        try:
            raw=base64.b64decode(shot['base64'],validate=True)
            assert (shot['mime']=='image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (shot['mime']=='image/jpeg' and raw.startswith(b'\xff\xd8\xff'))
        except (KeyError,ValueError,TypeError,AssertionError):raise ValueError(f'evidence.screenshots[{i}] 不是有效 PNG/JPEG 编码') from None
    if len(json.dumps(sample,ensure_ascii=False).encode())>5_000_000:raise ValueError('打包后超过 5 MB，请减少重复截图或适度压缩，保持文字可读')
    return {'valid':True,'assignment_id':aid,'citations':len(citations),'screenshots':len(screenshots),'citations_state':state,'note':'仅检查本地格式；不代表服务器接收、验收通过或已付款'}

def prepare_sample(file):
    if not file:raise ValueError('需要 --file 样本.json')
    path=Path(file);sample=read(path)
    if not isinstance(sample,dict):raise ValueError('样本必须为 JSON 对象')
    if 'screenshot_paths' in sample:
        paths=sample.pop('screenshot_paths')
        if not isinstance(paths,list) or not 1<=len(paths)<=20:raise ValueError('screenshot_paths 必填 1–20 个 PNG/JPEG 文件路径，不能是空数组')
        shots=[];total=0
        for name in paths:
            if not isinstance(name,str) or not name:raise ValueError('screenshot_paths 中的每项必须为文件路径字符串')
            image=Path(name)
            if not image.is_absolute():image=path.parent/image
            if not image.is_file():raise ValueError('截图文件不存在：'+str(image))
            total+=image.stat().st_size
            if total>5_000_000:raise ValueError('截图文件合计超过 5 MB，打包后还会增大，请适度压缩')
            raw=image.read_bytes()
            if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff')):raise ValueError('截图仅支持 PNG/JPEG：'+str(image))
            shots.append({'base64':base64.b64encode(raw).decode(),'mime':'image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg'})
        if not isinstance(sample.get('evidence'),dict):raise ValueError('evidence 必须为对象')
        sample['evidence']['screenshots']=shots
    validate_sample(sample)
    return sample

def upload(path):
    sample = read(path)
    digest=hashlib.sha256(json.dumps(sample,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    archive=HOME/'archive'/path.stem/(digest+'.json')
    save(archive,sample)
    try:result = request('submit', {'sample': sample})
    except ServiceError as exc:
        if exc.status in (400,422):
            failed=HOME/'failed'/path.stem/(digest+'.json');save(failed,sample);path.unlink()
            raise ServiceError(exc.status,exc.message+f'；原样本保留在 {failed}，修正源文件后重新 submit。') from None
        raise
    summary={'prompt':sample.get('prompt'),'platform':sample.get('platform'),'citations':len(sample.get('citations',[])),
             'screenshots':len(sample.get('evidence',{}).get('screenshots',[])),'citations_state':sample.get('citations_state'),'archive':str(archive)}
    save(HOME / 'receipts' / path.name, {**result,'local_summary':summary})
    path.unlink()
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['doctor', 'bind', 'projects', 'claim', 'start', 'start-heartbeat', '_heartbeat', 'validate', 'submit', 'retry', 'status', 'release', 'revoke'])
    parser.add_argument('--url', default='https://zhun.ai')
    parser.add_argument('--project')
    parser.add_argument('--file')
    parser.add_argument('--lease')
    parser.add_argument('--assignment')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--code-stdin',action='store_true',help='Read one binding code from stdin without a console prompt')
    args = parser.parse_args()
    if args.command == 'doctor':
        accessible = False
        try:
            with urllib.request.urlopen('https://zhun.ai/api/session', timeout=10) as response:
                accessible = response.status == 200
        except OSError:
            pass
        return {'client_version':VERSION,'system': platform.system(), 'computer': platform.node(), 'python': platform.python_version(),
                'credential_directory': str(HOME), 'service_accessible': accessible,
                'windows_binding_supported': os.name == 'nt',
                'host_verification': '请核对这是参与者自己的电脑；这些信息不能单独证明有本机浏览器操作权限。'}
    if args.command == 'bind':
        if os.name != 'nt':
            raise ValueError('当前分发版只支持在参与者本人的 Windows 电脑绑定。请勿在远程沙箱兑换绑定码。')
        code = sys.stdin.readline(257).strip() if args.code_stdin else read_binding_code()
        if not code or len(code)>256:
            raise ValueError('需要有效的一次性绑定信息，请重新复制任务指令')
        print('正在连接准活并验证绑定码…', flush=True)
        result = request('bind', {'code': code}, anonymous=True, base_url=args.url)
        save(HOME / 'config.json', {'url': args.url, 'credential': base64.b64encode(protect(result['token'].encode())).decode(), 'expires': result['expires']})
        return {'bound': True, 'expires': result['expires']}
    if args.command == 'projects':
        return request('projects')
    if args.command == 'start':
        if not args.assignment:
            raise ValueError('需要 --assignment')
        return request('start', {'assignment': args.assignment})
    if args.command == 'claim':
        if not args.project:
            raise ValueError('需要 --project')
        result = request('claim', {'project': args.project})
        save(HOME / 'lease.json', result['data'])
        return result
    if args.command in ('submit','validate'):
        sample = prepare_sample(args.file)
        if args.command=='validate' or args.dry_run:return validate_sample(sample)
        assignment = sample.get('assignment_id', '')
        if len(assignment) != 32 or any(ch not in '0123456789abcdef' for ch in assignment):
            raise ValueError('assignment_id 无效')
        path = HOME / 'outbox' / (assignment + '.json')
        if path.exists() and read(path) != sample:
            raise ValueError('已有不同的待传原始样本，不能覆盖')
        save(path, sample)
        return upload(path)
    if args.command == 'retry':
        return [upload(path) for path in sorted((HOME / 'outbox').glob('*.json'))]
    if args.command == 'status':
        lease=read(HOME/'lease.json') if (HOME/'lease.json').exists() else None
        heartbeat=read(HOME/'heartbeat.json') if (HOME/'heartbeat.json').exists() else None
        if heartbeat:heartbeat['stale']=time.time()-heartbeat.get('updated',0)>150
        return {'client_version':VERSION,'lease':lease,'heartbeat':heartbeat,
                'lease_remaining_seconds':max(0,(heartbeat.get('expires',0) if heartbeat and lease and heartbeat.get('lease')==lease['id'] else (lease or {}).get('expires',0))-int(time.time())),
                'archive_directory':str(HOME/'archive'),
                'pending_uploads': len(list((HOME / 'outbox').glob('*.json'))), 'samples': request('samples')}
    if args.command == 'revoke':
        result = request('revoke', {})
        (HOME / 'config.json').unlink()
        return result
    lease = read(HOME / 'lease.json')
    if not lease:
        raise ValueError('没有当前批次')
    if args.command == 'start-heartbeat':
        previous=read(HOME/'heartbeat.json') if (HOME/'heartbeat.json').exists() else {}
        if previous.get('lease')==lease['id'] and previous.get('state') in ('running','retrying') and time.time()-previous.get('updated',0)<90:
            return {'heartbeat':'already_running','pid':previous.get('pid'),'state_file':str(HOME/'heartbeat.json')}
        proc=subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_heartbeat', '--lease', lease['id']],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return {'heartbeat': 'starting', 'launcher_pid':proc.pid,'lease': lease['id'], 'max_seconds': 172800,'state_file':str(HOME/'heartbeat.json'),'note':'以状态文件中的工作进程 PID 和最后成功时间为准；解释器包装层可能多一个进程'}
    if args.command == '_heartbeat':
        return heartbeat_loop(args.lease)
    if args.command == 'release':
        save(HOME / 'lease.json', None)
        return request('release', {'lease': lease['id']})

def heartbeat_loop(lease_id):
    # One actual worker per lease, irrespective of Python launcher wrappers.
    if not isinstance(lease_id,str) or len(lease_id)!=32 or any(c not in '0123456789abcdef' for c in lease_id):raise ValueError('批次编号无效')
    HOME.mkdir(parents=True,exist_ok=True)
    with open(HOME/('heartbeat-'+lease_id+'.lock'),'a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:return {'heartbeat':'already_running'}
        state={'pid':os.getpid(),'lease':lease_id,'last_success':None,'last_error':None,'expires':0}
        failures=0
        for _ in range(2880):
            current = read(HOME / 'lease.json') if (HOME/'lease.json').exists() else None
            if not current or current['id'] != lease_id:
                break
            try:
                result=request('heartbeat', {'lease':lease_id})
                failures=0;state.update(last_success=int(time.time()),last_error=None,state='running',expires=result.get('data',{}).get('expires',current.get('expires',0)))
            except Exception as exc:
                failures+=1;state.update(last_error=str(exc)[:1000],state='retrying')
                if isinstance(exc,ServiceError) and 400<=exc.status<500 and exc.status!=429:failures=3
            state.update(updated=int(time.time()),remaining_attempts=2879-_)
            save(HOME/'heartbeat.json',state)
            if failures>=3:break
            time.sleep(60)
        state.update(state='failed' if failures>=3 else 'stopped',updated=int(time.time()))
        save(HOME/'heartbeat.json',state)
        return {'heartbeat': 'stopped'}

if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False, indent=2))
    except BindingInputCancelled:
        print('已取消输入；未发送绑定请求。', file=sys.stderr)
        sys.exit(130)
    except KeyboardInterrupt:
        print('操作已中断；如果请求已经发出，请先确认结果。', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        # Only bounded public messages are extracted from HTTP errors above.
        print('操作失败：' + str(exc), file=sys.stderr)
        sys.exit(1)
