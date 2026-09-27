"""Independent, append-only crowd samples. SQLite serializes allocation transactions."""
import re
import hashlib
import base64
import binascii
import json
import sqlite3
import time
import uuid
import secrets
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import urlsplit


class CrowdStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS withdrawals(project TEXT NOT NULL, worker TEXT NOT NULL, PRIMARY KEY(project,worker));
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, body TEXT NOT NULL, active INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY, worker TEXT NOT NULL, project TEXT NOT NULL, expires INTEGER NOT NULL, released INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY, lease TEXT NOT NULL, project TEXT NOT NULL, question INTEGER NOT NULL, replica INTEGER NOT NULL, worker TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY, assignment TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL, created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, sample TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL, reviewer TEXT NOT NULL, created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS starts(assignment TEXT PRIMARY KEY, worker TEXT NOT NULL, platform TEXT NOT NULL, created INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS assignment_project ON assignments(project, question, replica);
            CREATE TABLE IF NOT EXISTS identities(worker TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS task_links(project TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS link_codes(code TEXT PRIMARY KEY, project TEXT NOT NULL, expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sample_versions(sample TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL, created INTEGER NOT NULL, PRIMARY KEY(sample,version));
            CREATE TABLE IF NOT EXISTS sample_lineage(sample TEXT PRIMARY KEY, body TEXT NOT NULL, created INTEGER NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    @staticmethod
    def source_label(lineage, question):
        """品牌 / 大任务 / 子任务NN·平台 / 题号 —— 单题的来源编号。"""
        if not lineage:return None
        qids=lineage.get('question_ids') or []
        qid=qids[question] if 0<=question<len(qids) else '第%d题'%(question+1)
        return f"{lineage['label']} / {qid}"

    def assign_lineage(self, project, lineage):
        """给项目盖上 品牌/大任务/子任务 编号。子任务号在同一大任务内递增、只分配一次，之后不改。"""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT body FROM projects WHERE id=?',(project,)).fetchone()
            if not row:raise ValueError('项目不存在')
            body=json.loads(row[0]);old=body.get('lineage')
            if old:
                if old['task_id']!=lineage['task_id']:raise ValueError('项目已有来源编号，不能改到其他大任务')
                return old
            used=[json.loads(r[0]).get('lineage') or {} for r in c.execute('SELECT body FROM projects')]
            no=1+max([l.get('subtask_no',0) for l in used if l.get('task_id')==lineage['task_id']] or [0])
            lin=dict(lineage,subtask_no=no,platform=body['platform'],project=project)
            lin['label']=f"{lin['brand_name']} / {lin['task_name']} / 子任务{no:02d}·{body['platform']}"
            body['lineage']=lin
            c.execute('UPDATE projects SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),project))
            return lin

    def create(self, body):
        questions = body.get('questions', [])
        if not isinstance(questions, list) or not 1 <= len(questions) <= 1000 or any(not isinstance(q, str) or not q.strip() or len(q) > 10000 for q in questions):
            raise ValueError('需要 1–1000 道非空题目')
        for key in ('title', 'platform', 'entry_url'):
            if not isinstance(body.get(key), str) or not body[key].strip():
                raise ValueError('缺少 ' + key)
        url = urlsplit(body['entry_url'])
        if url.scheme != 'https' or not url.hostname or url.username:
            raise ValueError('平台入口必须为 HTTPS')
        replicas, batch = int(body.get('replicas', 1)), len(questions)
        if not isinstance(body.get('conditions', {}), dict):
            raise ValueError('采集条件必须是对象')
        if not 1 <= replicas <= 20:
            raise ValueError('副本数须为 1–20')
        project = {k: body[k] for k in ('title', 'platform', 'entry_url')}
        project.update(id=uuid.uuid4().hex, questions=questions, replicas=replicas, batch_size=batch,
                       conditions=body.get('conditions', {}), created=int(time.time()))
        with self.connect() as c:
            c.execute('INSERT INTO projects VALUES(?,?,1)', (project['id'], json.dumps(project, ensure_ascii=False)))
        return project

    @staticmethod
    def citation_diagnostics(body):
        notes=body.get('evidence',{}).get('completeness_notes',[]) or []
        notes=[re.sub(r'\x1b\[[0-9;]*m','',n) for n in notes if isinstance(n,str)]
        counts=set()
        for note in notes:
            for match in re.finditer(r'引用(?:中)?(?:有)?\s*(\d+)\s*处未能展开',note):
                counts.add(int(match.group(1)))
        missing=next(iter(counts)) if len(counts)==1 else None
        incomplete=body.get('citations_state')=='incomplete'
        label=(f'{missing} 处引用待补全（据采集说明）' if missing is not None else '引用不完整，缺失数量未确认') if incomplete else '引用采集说明'
        return {'summary':label,'missing_mentions':missing,'collected_entries':len(body.get('citations',[])),
                'unique_links':len({x.get('url') for x in body.get('citations',[]) if x.get('url')}),'notes':notes}

    def projects(self):
        with self.connect() as c:
            return [dict(json.loads(r['body']), active=bool(r['active']), task_link=json.loads(r['link']) if r['link'] else None) for r in c.execute('SELECT p.*,l.body AS link FROM projects p LEFT JOIN task_links l ON l.project=p.id')]

    def delete_project(self, project):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM projects WHERE id=?', (project,)).fetchone():
                raise ValueError('项目不存在')
            if c.execute('SELECT 1 FROM task_links WHERE project=?', (project,)).fetchone():
                raise ValueError('项目已关联准活任务，不能删除；可暂停分配')
            if c.execute('SELECT 1 FROM assignments WHERE project=?', (project,)).fetchone():
                raise ValueError('项目已有领取或采集记录，不能删除；可暂停分配')
            c.execute('DELETE FROM link_codes WHERE project=?', (project,))
            c.execute('DELETE FROM projects WHERE id=?', (project,))
        return {'ok': True}

    def link_code(self, project):
        with self.connect() as c:
            if not c.execute('SELECT 1 FROM projects WHERE id=?',(project,)).fetchone():raise ValueError('项目不存在')
            if c.execute('SELECT 1 FROM task_links WHERE project=?',(project,)).fetchone():raise ValueError('项目已关联准活任务')
            code=secrets.token_urlsafe(24)
            c.execute('DELETE FROM link_codes WHERE project=?',(project,))
            c.execute('INSERT INTO link_codes VALUES(?,?,?)',(hashlib.sha256(code.encode()).hexdigest(),project,int(time.time())+172800))
            return {'code':code,'expires_in':172800}

    def link_task(self, code, link, expected_project=None):
        if not isinstance(code,str) or not isinstance(link,dict) or any(type(link.get(k)) is not int or link[k]<=0 for k in ('task_id','owner','unit_amount')):
            raise ValueError('任务关联参数无效')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            existing=c.execute('SELECT project FROM task_links WHERE body=?',(json.dumps(link,sort_keys=True),)).fetchone()
            if existing:
                if expected_project and existing[0]!=expected_project:raise ValueError('导入项目与关联任务不一致')
                p=json.loads(c.execute('SELECT body FROM projects WHERE id=?',(existing[0],)).fetchone()[0])
                return {'project':existing[0],'target_samples':len(p['questions'])*p['replicas']}
            if any(json.loads(r[0])['task_id']==link['task_id'] for r in c.execute('SELECT body FROM task_links')):
                raise ValueError('该准活任务已关联其他 GEO 项目')
            row=c.execute('SELECT project FROM link_codes WHERE code=? AND expires>?',(hashlib.sha256(code.encode()).hexdigest(),int(time.time()))).fetchone()
            if not row:raise ValueError('关联码无效或已过期')
            if expected_project and row[0]!=expected_project:raise ValueError('该任务只能关联原先导入的 GEO 项目')
            if c.execute('SELECT 1 FROM assignments WHERE project=?',(row[0],)).fetchone():raise ValueError('已有采集记录的试跑项目不能补建收费任务，请新建项目')
            c.execute('INSERT INTO task_links VALUES(?,?)',(row[0],json.dumps(link,sort_keys=True)))
            c.execute('DELETE FROM link_codes WHERE project=?',(row[0],))
            p=json.loads(c.execute('SELECT body FROM projects WHERE id=?',(row[0],)).fetchone()[0])
            return {'project':row[0],'target_samples':len(p['questions'])*p['replicas']}

    def import_preview(self, code):
        if not isinstance(code,str):raise ValueError('关联码无效')
        with self.connect() as c:
            row=c.execute('SELECT p.body,p.active FROM projects p JOIN link_codes l ON l.project=p.id WHERE l.code=? AND l.expires>?',(hashlib.sha256(code.encode()).hexdigest(),int(time.time()))).fetchone()
            if not row:raise ValueError('关联码无效或已过期，请回 GEO 重新生成发布入口')
            p=json.loads(row['body'])
            if c.execute('SELECT 1 FROM assignments WHERE project=?',(p['id'],)).fetchone():raise ValueError('已有采集记录的试跑项目不能转为收费任务，请新建项目')
            if c.execute('SELECT 1 FROM task_links WHERE project=?',(p['id'],)).fetchone():raise ValueError('项目已关联正式任务')
            return p

    def identities(self, identities):
        with self.connect() as c:
            for user in identities:
                worker='zhun:'+str(int(user['id']))
                c.execute('INSERT INTO identities VALUES(?,?) ON CONFLICT(worker) DO UPDATE SET name=excluded.name',(worker,str(user['name'])[:100]))
        return {'ok':True}

    @staticmethod
    def blockers(body, expected):
        out=[]
        if body.get('answer_complete') is not True:out.append('回答未采集完整')
        if body.get('citations_state')=='incomplete':out.append('引用采集不完整，请查看采集说明并退回补充')
        for k,v in expected.items():
            if body.get('conditions',{}).get(k)!=v:out.append('采集条件不符：'+k)
        return out

    def active(self, project, active):
        with self.connect() as c:
            if c.execute('UPDATE projects SET active=? WHERE id=?', (int(active), project)).rowcount != 1:
                raise ValueError('项目不存在')

    def _lease(self, c, lease):
        result = dict(lease)
        project = json.loads(c.execute('SELECT body FROM projects WHERE id=?', (lease['project'],)).fetchone()[0])
        result['project_config'] = {k: v for k, v in project.items() if k != 'questions'}
        result['assignments'] = [dict(r, prompt=project['questions'][r['question']], source=self.source_label(project.get('lineage'), r['question'])) for r in c.execute('SELECT a.*, s.status FROM assignments a LEFT JOIN samples s ON s.assignment=a.id WHERE a.lease=?', (lease['id'],))]
        return result

    def withdraw(self, worker, project):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM projects WHERE id=?',(project,)).fetchone():
                raise ValueError('项目不存在')
            c.execute('INSERT OR IGNORE INTO withdrawals VALUES(?,?)',(project,worker))
            c.execute('UPDATE leases SET released=1 WHERE project=? AND worker=?',(project,worker))
        return {'ok': True}

    def claim(self, worker, project):
        now = int(time.time())
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM withdrawals WHERE project=? AND worker=?',(project,worker)).fetchone():raise ValueError('已退出该采集项目')
            old = c.execute('SELECT * FROM leases WHERE worker=? AND released=0 AND expires>?', (worker, now)).fetchone()
            if old and old['project']!=project:raise ValueError('请先完成或释放另一个项目的题目')
            row = c.execute('SELECT body FROM projects WHERE id=? AND active=1', (project,)).fetchone()
            if not row:
                raise ValueError('项目不存在或已暂停')
            p = json.loads(row[0])
            selected = []
            for q in range(len(p['questions'])):
                # Submitted samples prevent duplicate replicas; abandoned, unsubmitted attempts may retry.
                if c.execute('''SELECT 1 FROM assignments a JOIN leases l ON l.id=a.lease LEFT JOIN samples s ON s.assignment=a.id WHERE a.project=? AND a.question=? AND a.worker=? AND (s.id IS NOT NULL OR (l.released=0 AND l.expires>?))''', (project, q, worker, now)).fetchone():
                    continue
                for replica in range(p['replicas']):
                    occupied = c.execute('''SELECT 1 FROM assignments a JOIN leases l ON l.id=a.lease LEFT JOIN samples s ON s.assignment=a.id
                        WHERE a.project=? AND a.question=? AND a.replica=? AND
                        ((l.released=0 AND l.expires>?) OR s.status IN ('pending','accepted','revision'))''', (project, q, replica, now)).fetchone()
                    if not occupied:
                        selected.append((q, replica))
                        break
            if not selected and not old:return None
            lid = old['id'] if old else uuid.uuid4().hex
            if old:c.execute('UPDATE leases SET expires=? WHERE id=?',(now+172800,lid))
            else:c.execute('INSERT INTO leases VALUES(?,?,?,?,0)', (lid, worker, project, now + 172800))
            for q, replica in selected:
                c.execute('INSERT INTO assignments VALUES(?,?,?,?,?,?)', (uuid.uuid4().hex, lid, project, q, replica, worker))
            return self._lease(c, c.execute('SELECT * FROM leases WHERE id=?', (lid,)).fetchone())

    def heartbeat(self, worker, lease, release=False):
        with self.connect() as c:
            updated = c.execute('UPDATE leases SET expires=?, released=? WHERE id=? AND worker=? AND released=0 AND expires>?',
                                (int(time.time()) + 172800, int(release), lease, worker, int(time.time())))
            if updated.rowcount != 1:
                raise ValueError('批次已过期或不属于当前参与者')
        return {'released': release, 'expires': int(time.time()) + 172800}

    def start(self, worker, assignment):
        """Register each question start; collection pacing is controlled by the client Skill."""
        now = int(time.time())
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT a.project FROM assignments a JOIN leases l ON l.id=a.lease WHERE a.id=? AND a.worker=? AND l.expires>? AND l.released=0', (assignment, worker, now)).fetchone()
            if not row:
                raise ValueError('题目租约无效')
            p = c.execute('SELECT body,active FROM projects WHERE id=?', (row['project'],)).fetchone()
            if not p['active']:
                raise ValueError('项目已暂停')
            if c.execute('SELECT 1 FROM starts WHERE assignment=?', (assignment,)).fetchone():
                return {'started': True, 'resume_only': True}
            platform = json.loads(p['body'])['platform']
            c.execute('INSERT INTO starts VALUES(?,?,?,?)', (assignment, worker, platform, now))
            return {'started': True, 'resume_only': False}

    def submit(self, worker, body):
        canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        if len(canonical.encode()) > 5_000_000:
            raise ValueError('单份证据不得超过 5 MB')
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            a = c.execute('SELECT a.*,l.expires,l.released FROM assignments a JOIN leases l ON a.lease=l.id WHERE a.id=? AND a.worker=?', (body.get('assignment_id'), worker)).fetchone()
            if not a:
                raise ValueError('题目未分配给当前参与者')
            if c.execute('SELECT 1 FROM withdrawals WHERE project=? AND worker=?',(a['project'],worker)).fetchone():raise ValueError('已退出该采集项目，已有成果保留，请联系负责人处理补充')
            if not c.execute('SELECT 1 FROM starts WHERE assignment=?', (a['id'],)).fetchone():
                raise ValueError('请先记录本题开始采集')
            old = c.execute('SELECT * FROM samples WHERE assignment=?', (a['id'],)).fetchone()
            if old:
                latest=c.execute('SELECT digest FROM sample_versions WHERE sample=? ORDER BY version DESC LIMIT 1',(old['id'],)).fetchone()
                current_digest=latest[0] if latest else old['digest']
                if current_digest == digest:
                    return {'id':old['id'],'status':old['status'],'digest':digest}
                if old['status'] != 'revision':
                    raise ValueError('该题已提交；原始样本不可覆盖')
            p = json.loads(c.execute('SELECT body FROM projects WHERE id=?', (a['project'],)).fetchone()[0])
            if body.get('prompt') != p['questions'][a['question']] or body.get('platform') != p['platform']:
                raise ValueError('问题或平台与分配不符')
            if not isinstance(body.get('answer'), str) or not body['answer'].strip():
                raise ValueError('缺少原始回答')
            if type(body.get('answer_complete')) is not bool:
                raise ValueError('必须明确回答是否完整')
            if body.get('citations_state') not in ('complete', 'none_visible', 'incomplete') or not isinstance(body.get('citations'), list):
                raise ValueError('必须明确引用采集状态')
            for item in body['citations']:
                if not isinstance(item, dict) or item.get('kind') not in ('citation', 'search_source'):
                    raise ValueError('引用必须区分正文引用与搜索来源')
                if not isinstance(item.get('url'), str):
                    raise ValueError('引用链接必须为字符串')
                u = urlsplit(item['url'])
                if u.scheme not in ('https', 'http') or not u.hostname or u.username:
                    raise ValueError('引用必须包含真实完整链接')
            if body['citations_state'] == 'none_visible' and body['citations']:
                raise ValueError('无可见引用状态不能包含引用')
            if body['citations_state'] == 'complete' and not body['citations']:
                raise ValueError('没有可见引用时请使用 none_visible')
            if not isinstance(body.get('conditions'), dict) or not body['conditions'] or not isinstance(body.get('evidence'), dict) or not body['evidence'].get('page_text'):
                raise ValueError('缺少采集条件或页面原始证据')
            conditions = body['conditions']
            if not isinstance(conditions.get('model'), str) or not conditions['model'].strip() or conditions.get('web_search') not in ('on', 'off', 'unknown') or type(conditions.get('new_conversation')) is not bool:
                raise ValueError('必须记录模型、联网状态与是否新会话')
            try:
                collected = datetime.fromisoformat(conditions['collected_at'].replace('Z', '+00:00'))
                if collected.tzinfo is None:
                    raise ValueError('缺少时区')
            except (ValueError, TypeError, KeyError, AttributeError):
                raise ValueError('采集时间必须是带时区的 ISO 8601 时间') from None
            if not isinstance(body['evidence']['page_text'], str):
                raise ValueError('页面原文必须是文本')
            screenshots = body['evidence'].get('screenshots', [])
            if not isinstance(screenshots, list) or not 1 <= len(screenshots) <= 20:
                raise ValueError('需要 1–20 张当前任务页面截图')
            for screenshot in screenshots:
                try:
                    raw = base64.b64decode(screenshot['base64'], validate=True)
                    mime = screenshot['mime']
                except (KeyError, TypeError, ValueError, binascii.Error):
                    raise ValueError('截图编码无效') from None
                if not ((mime == 'image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (mime == 'image/jpeg' and raw.startswith(b'\xff\xd8\xff'))):
                    raise ValueError('截图只允许 PNG 或 JPEG')
            status = 'late' if a['expires'] <= time.time() or a['released'] else 'pending'
            if old:
                version=c.execute('SELECT COALESCE(MAX(version),0)+1 FROM sample_versions WHERE sample=?',(old['id'],)).fetchone()[0]
                c.execute('INSERT INTO sample_versions VALUES(?,?,?,?,?)',(old['id'],version,canonical,digest,int(time.time())))
                c.execute("UPDATE samples SET status='pending' WHERE id=?",(old['id'],))
                return {'id':old['id'],'status':'pending','digest':digest,'version':version}
            sid = uuid.uuid4().hex
            c.execute('INSERT INTO samples VALUES(?,?,?,?,?,?)', (sid, a['id'], digest, canonical, status, int(time.time())))
            self._stamp(c, sid, a['project'], a['question'])
            return {'id': sid, 'status': status, 'digest': digest}

    def _stamp(self, c, sample, project, question):
        """样本入库时盖上来源编号（品牌/大任务/子任务/题），之后项目改名也不影响已收回的样本。"""
        lin=json.loads(c.execute('SELECT body FROM projects WHERE id=?',(project,)).fetchone()[0]).get('lineage')
        if not lin:return
        qids=lin.get('question_ids') or []
        src={k:lin[k] for k in ('brand_id','brand_name','task_id','task_name','subtask_no','platform','project')}
        src.update(question_no=question+1,question_id=qids[question] if question<len(qids) else None,label=self.source_label(lin,question))
        c.execute('INSERT OR IGNORE INTO sample_lineage VALUES(?,?,?)',(sample,json.dumps(src,ensure_ascii=False),int(time.time())))

    def stamp_existing(self, project):
        """补编号：给项目下尚无来源编号的已有样本盖章。返回新盖的数量。"""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            rows=c.execute('SELECT s.id,a.question FROM samples s JOIN assignments a ON a.id=s.assignment LEFT JOIN sample_lineage l ON l.sample=s.id WHERE a.project=? AND l.sample IS NULL',(project,)).fetchall()
            for r in rows:self._stamp(c,r['id'],project,r['question'])
            return len(rows)

    def samples(self, worker=None, sample_id=None):
        with self.connect() as c:
            sql = 'SELECT s.*,a.worker,a.project,a.question,p.body AS project_body,i.name AS worker_name,sl.body AS lineage_body FROM samples s JOIN assignments a ON a.id=s.assignment JOIN projects p ON p.id=a.project LEFT JOIN identities i ON i.worker=a.worker LEFT JOIN sample_lineage sl ON sl.sample=s.id'
            filters=[];params=[]
            if worker:filters.append('a.worker=?');params.append(worker)
            if sample_id:filters.append('s.id=?');params.append(sample_id)
            rows = c.execute(sql + (' WHERE '+' AND '.join(filters) if filters else '') + ' ORDER BY s.created DESC',params)
            result=[]
            for row in rows:
                r=dict(row);p=json.loads(r.pop('project_body'));r['body']=json.loads(r['body']);lb=r.pop('lineage_body');r['source']=json.loads(lb) if lb else None;r['source_label']=r['source']['label'] if r['source'] else None
                versions=c.execute('SELECT * FROM sample_versions WHERE sample=? ORDER BY version',(r['id'],)).fetchall()
                r['version']=len(versions)
                if versions:r['body']=json.loads(versions[-1]['body']);r['digest']=versions[-1]['digest']
                r.update(project_title=p['title'],platform=p['platform'],question_no=r['question']+1,prompt=r['body']['prompt'],review_blockers=self.blockers(r['body'],p['conditions']),citation_diagnostics=self.citation_diagnostics(r['body']))
                review=c.execute('SELECT decision,reason,reviewer,created FROM reviews WHERE sample=? ORDER BY rowid DESC LIMIT 1',(r['id'],)).fetchone()
                r['review']=dict(review) if review else None
                r['forced_acceptance']=bool(review and review['decision']=='force_accepted')
                result.append(r)
            return result

    def workflow_feed(self):
        samples=[{k:v for k,v in s.items() if k!='body'} for s in self.samples()]
        with self.connect() as c:assignments=[dict(r) for r in c.execute('SELECT a.id,a.project,a.worker,a.question FROM assignments a JOIN leases l ON l.id=a.lease LEFT JOIN samples s ON s.assignment=a.id WHERE s.id IS NOT NULL OR (l.released=0 AND l.expires>?)',(int(time.time()),))]
        return {'projects':self.projects(),'samples':samples,'assignments':assignments}

    def review(self, sample, decision, reason, reviewer, confirmed=False):
        if decision not in ('accepted', 'rejected','revision','force_accepted') or not isinstance(reason,str) or not reason.strip():
            raise ValueError('验收需结论和理由')
        if decision=='force_accepted' and confirmed is not True:
            raise ValueError('强制通过需要确认：保留缺项记录，计入通过配额；正式任务进入待人工结算，不自动付款')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT status,body FROM samples WHERE id=?', (sample,)).fetchone()
            if not row or (row['status'] != 'pending' and not (row['status']=='late' and decision=='force_accepted')):
                raise ValueError('只允许验收待审样本；迟交样本请填写原因后使用强制通过')
            if row['status']=='late':
                slot=c.execute('SELECT a.* FROM assignments a JOIN samples s ON s.assignment=a.id WHERE s.id=?',(sample,)).fetchone()
                conflict=c.execute("SELECT 1 FROM assignments a JOIN leases l ON l.id=a.lease LEFT JOIN samples s ON s.assignment=a.id WHERE a.project=? AND a.question=? AND a.replica=? AND a.id!=? AND ((l.released=0 AND l.expires>?) OR s.status IN ('pending','accepted','revision'))",(slot['project'],slot['question'],slot['replica'],slot['id'],int(time.time()))).fetchone()
                if conflict:raise ValueError('该名额已重新分配或已有有效样本，请先核对其他采集记录，不能重复计入配额')
                reason='迟交样本人工核对通过：'+reason
            latest=c.execute('SELECT body FROM sample_versions WHERE sample=? ORDER BY version DESC LIMIT 1',(sample,)).fetchone()
            data = json.loads(latest[0] if latest else row['body'])
            if decision == 'accepted' and (data.get('answer_complete') is not True or data['citations_state'] == 'incomplete'):
                raise ValueError('不完整样本不可验收通过')
            project = c.execute('SELECT p.body FROM projects p JOIN assignments a ON a.project=p.id JOIN samples s ON s.assignment=a.id WHERE s.id=?', (sample,)).fetchone()
            expected = json.loads(project[0])['conditions']
            if decision == 'accepted' and any(data['conditions'].get(k) != v for k, v in expected.items()):
                raise ValueError('采集条件与项目要求不符')
            status='accepted' if decision=='force_accepted' else decision
            c.execute('UPDATE samples SET status=? WHERE id=?', (status, sample))
            c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?)', (uuid.uuid4().hex, sample, decision, reason, reviewer, int(time.time())))
        return {'status': status, **({'forced_acceptance':True} if decision=='force_accepted' else {})}
