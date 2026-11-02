import hashlib
import json
import os
import shutil
import threading
import uuid
import base64
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .data import Archive, validate_root
from .demo import DemoArchive
from .exporting import FORMATS, export_index, export_session, clean, export_folder_name, unused_folder
from .avatars import AvatarStore, image_type, avatar_host
from .version import VERSION,APP_NAME
from .paths import app_data_root
from .export_options import export_preferences,is_system_message
from .themes import ACCENT_IDS,palette,accent_choices
from wx4.forward import build_forward

SORT_FIELDS=('frequentExport','name','memberCount','id','lastActivity','exportedCount')


def session_sort(value):
    if not isinstance(value,dict) or value.get('field') not in SORT_FIELDS or value.get('order') not in ('asc','desc'):
        raise ValueError('会话排序选项无效')
    return {'field':value['field'],'order':value['order']}


def task_category(task):
    category=task.get('category') or task.get('format')
    if category in ('moments','stickers'):return category
    return 'sessions' if task.get('kind') in ('export','connect') else 'other'


class Cancelled(Exception):
    pass


def atomic_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def options_from(payload):
    result = {'query': str(payload.get('query', ''))[:200], 'kind': payload.get('kind', 'all')}
    result.update(export_preferences(payload))
    if result['kind'] not in ('all','text','image','voice','video','file','link','system'):
        raise ValueError('消息类型不受支持')
    for key, tail in [('start', 'T00:00:00'), ('end', 'T23:59:59')]:
        value = payload.get(key)
        if value:
            value=str(value)
            normalized=value[:16]+(':00' if key=='start' else ':59') if 'T' in value else value[:10]+tail
            result[key] = int(datetime.fromisoformat(normalized).replace(
                tzinfo=timezone(timedelta(hours=8))).timestamp())
    if result.get('start', 0) > result.get('end', 10**12):
        raise ValueError('开始日期不能晚于结束日期')
    return result


class Service:
    def __init__(self, assets, root=None):
        self.assets = Path(assets)
        self.root = Path(root) if root else app_data_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root/'config.json'
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='archive-jobs')
        self.events = {}
        self.accounts = {}
        self._moments_preview_cache={}
        self._library_epoch = 0
        self._startup_reconnect_done = False
        self._startup_reconnect_result = None
        self._updating=False
        self.config = {'theme':'light', 'accent':'violet', 'export_dir': str(Path.home()/'Documents'/APP_NAME/'exports'),
                       'library': None, 'tasks': []}
        if self.config_path.exists():
            try:
                self.config.update(json.loads(self.config_path.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                pass
        legacy_export=str(Path.home()/'Documents'/'WeChatExporter'/'exports')
        if os.path.normcase(os.path.normpath(self.config['export_dir']))==os.path.normcase(os.path.normpath(legacy_export)):
            self.config['export_dir']=str(Path.home()/'Documents'/APP_NAME/'exports')
        for task in self.config['tasks']:
            if task['status'] in ('queued','running'):
                task.update(status='interrupted', detail='上次运行已中断，请重新创建任务。')
        self.library = self.config.get('library')
        self._demo_previous = None
        try:self.config['session_sort']=session_sort(self.config.get('session_sort'))
        except ValueError:self.config['session_sort']={'field':'lastActivity','order':'desc'}
        if not isinstance(self.config.get('accent'),str) or self.config['accent'] not in ACCENT_IDS:self.config['accent']='violet'
        seen=self.config.get('asset_tutorials')
        self.config['asset_tutorials']={kind:bool(isinstance(seen,dict) and seen.get(kind) is True) for kind in ('moments','stickers')}
        self.config['app_onboarding_seen']=self.config.get('app_onboarding_seen') is True
        # Capture before the frontend marks the tutorial as shown. The first
        # process must stay manual even after closing/reloading its tutorial.
        self._startup_reconnect_allowed = self.config['app_onboarding_seen']
        from .online import OnlineChannel
        self.online=OnlineChannel(self)

    def appearance(self):return palette(self.config['theme'],self.config['accent'])

    def export_theme(self):
        with self.lock:return {'mode':self.config['theme'],'accent':self.config['accent']}

    def save(self):
        with self.lock:
            self.config['tasks'] = self.config['tasks'][-80:]
            atomic_json(self.config_path, self.config)

    def archive(self, library=None):
        lib = library or self.library
        if not lib:
            raise ValueError('请先连接微信、打开备份，或进入演示模式。')
        return DemoArchive(lib) if lib.get('demo') else Archive(lib)

    def avatar(self,url):
        if not isinstance(url,str) or len(url)>4096 or not avatar_host(url):return {'url':''}
        data=SimpleNamespace(_conns={},avatar_of=lambda user:url)
        blob=AvatarStore(data,self.root/'avatar-cache').blob('',download=True)
        return {'url':'data:'+image_type(blob)[1]+';base64,'+base64.b64encode(blob).decode() if blob else ''}

    def state(self):
        with self.lock:
            lib = self.library
            return {'version':VERSION, 'theme':self.config['theme'],
                    'online':self.online.status(),
                    'session_sort':dict(self.config['session_sort']),
                    'accent':self.config['accent'],'accents':accent_choices(),'appearance':self.appearance(),
                    'export_dir':self.config['export_dir'],
                    'library':dict(name=lib.get('profile',{}).get('name') or lib['name'],
                                   profile=lib.get('profile',{}),demo=lib.get('demo', False),
                                   live=bool(lib.get('account_dir')),assets_revision=lib.get('assets_revision',''),
                                   data_revision=hashlib.sha256((lib.get('root','')+lib.get('assets_revision','')).encode()).hexdigest()[:16],
                                   imported_at=lib.get('imported_at','')) if lib else None,
                    'tasks': [self.public_task(t) for t in reversed(self.config['tasks'])]}

    @staticmethod
    def public_task(t):
        result={k:v for k,v in t.items() if k not in ('folder','files')}
        result['category']=task_category(t)
        files=t.get('files') or []
        if files:
            result['title']='、'.join(f['name'] for f in files)
            result.setdefault('format',files[0].get('format',''))
            result.setdefault('start_time',files[0].get('start_time'))
            result.setdefault('end_time',files[-1].get('end_time'))
        return result

    def hydrate_profile(self,archive,lib):
        if isinstance(archive,Archive):
            lib['profile']=archive.profile()
            lib['wxid']=lib['profile']['wxid']
            lib['name']=lib['profile']['name']

    def _new_job(self, kind, title):
        with self.lock:
            if self._updating:raise ValueError('正在准备软件更新，请稍候。')
            if sum(t['status'] in ('queued','running') for t in self.config['tasks']) >= 10:
                raise ValueError('任务队列已满，请等待当前任务完成。')
            job = dict(id=uuid.uuid4().hex, kind=kind, title=title, status='queued', progress=0,
                       detail='等待处理', count=0, created_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
                       demo=bool(self.library and self.library.get('demo')))
            self.config['tasks'].append(job)
            self.events[job['id']] = threading.Event()
            self.save()
        return job

    def _update(self, job, **values):
        with self.lock:
            job.update(values)

    def _check(self, job):
        if self.events[job['id']].is_set():
            raise Cancelled()

    def _run(self, job, fn):
        try:
            self._check(job)
            self._update(job, status='running', detail='正在准备…')
            fn()
            self._update(job, status='completed', progress=100)
        except Cancelled:
            self._update(job, status='cancelled', detail='任务已取消，未完成的导出已清理。')
        except Exception as exc:
            # Do not return tracebacks, key values or chat content to the UI.
            message = str(exc)
            if len(message) > 240 or any(s in message for s in ('enc_key','Traceback')):
                message = '处理失败，请检查数据目录和微信登录状态后重试。'
            self._update(job, status='failed', detail=message or type(exc).__name__)
        finally:
            self.save()

    def demo(self):
        with self.lock:
            if self.library and self.library.get('demo'):return self.state()
            self._demo_previous=self.library
            self._invalidate_connections()
            self.library = dict(name='演示归档', demo=True, wxid='demo_me', root='', imported_at='虚构数据')
        return self.state()

    def return_from_demo(self):
        with self.lock:
            if self.library and self.library.get('demo'):
                self._invalidate_connections()
                self.library=self._demo_previous
                self._demo_previous=None
        return self.state()

    def _invalidate_connections(self):
        """Called under lock: a stale worker must never restore a signed-out account."""
        self._library_epoch += 1
        self._moments_preview_cache.clear()
        self._startup_reconnect_result = None
        for task in self.config['tasks']:
            if task['kind'] in ('connect','refresh_assets') and task['status'] in ('queued','running'):
                event=self.events.get(task['id'])
                if event:event.set()

    def logout(self):
        with self.lock:
            self._invalidate_connections()
            self.library=None
            self._demo_previous=None
            self.config['library']=None
            self.accounts={}
            self.save()
        return self.state()

    def startup_reconnect(self):
        # WebView2 can reload its document while installing the native frame.
        # Make this operation once per process, rather than once per React mount.
        with self.lock:
            if self._startup_reconnect_done:return self._startup_reconnect_result or {'skipped':True}
            self._startup_reconnect_done=True
            if not self._startup_reconnect_allowed:return {'skipped':True}
            lib=self.library
            # A first installation, an imported backup, demo mode or an explicit
            # logout has no previously connected live account to refresh.
            if not lib or lib.get('demo') or not lib.get('account_dir'):
                return {'skipped':True}
            if any(t['kind']=='connect' and t['status'] in ('queued','running') for t in self.config['tasks']):
                return {'skipped':True}
            detected=self.detect()
            if not detected['running']:
                return {'notice':'请先打开并登录电脑微信，再连接并整理。'}
            wanted=os.path.normcase(os.path.abspath(lib['account_dir']))
            account_id=next((i for i,a in self.accounts.items()
                if os.path.normcase(os.path.abspath(a['path']))==wanted),None)
            # A manually selected data directory might be outside WeChat's
            # discovery roots. Reuse that exact directory, never another account.
            if not account_id and (Path(lib['account_dir'])/'db_storage').is_dir():
                account_id=self.add_storage(lib['account_dir'])['id']
            if not account_id:
                return {'notice':'未找到上次连接的微信数据目录，请重新选择账号。'}
            self._startup_reconnect_result=self.connect(account_id)
            return self._startup_reconnect_result

    def import_archive(self, path):
        root = validate_root(path)
        lib = dict(name=Path(root).name or '本地归档', root=root, wxid='', imported_at=datetime.now().strftime('%Y-%m-%d %H:%M'))
        archive = Archive(lib)
        try:
            if not archive.sessions():
                raise ValueError('没有找到可浏览的会话。请检查备份是否完整。')
            self.hydrate_profile(archive,lib)
        finally:
            archive.close()
        with self.lock:
            self._invalidate_connections()
            self.library = lib
            self._demo_previous=None
            self.config['library'] = lib
            self.save()
        return self.state()

    def reconnect(self):
        """Explicit refresh always creates a fresh snapshot of this exact account."""
        with self.lock:
            lib=self.library
            if not lib:raise ValueError('请先连接微信。')
            if lib.get('demo') or not lib.get('account_dir'):return {'reload':True}
            if any(t['kind'] in ('connect','refresh_assets') and t['status'] in ('queued','running') for t in self.config['tasks']):
                raise ValueError('正在连接或整理微信，请等待当前任务完成。')
            if not self.detect()['running']:raise ValueError('请先打开并登录电脑微信。')
            wanted=os.path.normcase(os.path.abspath(lib['account_dir']))
            account_id=next((i for i,a in self.accounts.items() if os.path.normcase(os.path.abspath(a['path']))==wanted),None)
            if not account_id:account_id=self.add_storage(lib['account_dir'])['id']
            return self.connect(account_id)

    def detect(self):
        from wx4 import key, paths
        found = paths.list_account_dirs()
        self.accounts = {hashlib.sha256(a['db_storage'].encode()).hexdigest()[:16]: a for a in found}
        def label(i,a):
            lib=self.library or {}
            profile=lib.get('profile',{}) if lib.get('account_dir')==a['path'] else {}
            return {'id':i,'name':profile.get('name') or '微信账号',
                    'wxid':profile.get('alias') or a['wxid'], 'avatar_url':profile.get('avatar_url',''),
                    'connected':bool(lib.get('account_dir') and os.path.normcase(os.path.abspath(lib['account_dir']))==os.path.normcase(os.path.abspath(a['path'])))}
        return {'running':bool(key.find_weixin_processes()),
                'accounts':[label(i,a) for i,a in self.accounts.items()]}

    def add_storage(self, directory):
        from wx4 import paths
        p = Path(directory).resolve()
        if p.name != 'db_storage':
            p = p/'db_storage'
        if not p.is_dir():
            raise ValueError('请选择账号目录或其中的 db_storage 文件夹。')
        token = hashlib.sha256(str(p).encode()).hexdigest()[:16]
        self.accounts[token] = dict(dir_name=p.parent.name, wxid=paths.split_wxid(p.parent.name),
                                     path=str(p.parent), db_storage=str(p))
        return {'id':token,'name':'微信账号','wxid':self.accounts[token]['wxid']}

    def connect(self, account_id):
        with self.lock:
            if account_id not in self.accounts:
                raise ValueError('请重新检测并选择微信账号。')
            if any(t['kind']=='connect' and t['status'] in ('queued','running') for t in self.config['tasks']):
                raise ValueError('正在连接并整理微信，请等待当前任务完成。')
            account = dict(self.accounts[account_id])
            job = self._new_job('connect', '连接微信 · ' + account['dir_name'])
            job['demo'] = False
            epoch=self._library_epoch
        def check_connection():
            self._check(job)
            with self.lock:
                if epoch!=self._library_epoch:raise Cancelled()
        def work():
            from wx4 import key, decrypt
            check_connection()
            slot = self.root/'archives'/account_id
            slot.mkdir(parents=True, exist_ok=True)
            keys_file = slot/'keys.json'
            self._update(job, progress=8, detail='正在获取本机微信的读取凭据…')
            def key_progress(message):
                check_connection()
            ex = key.KeyExtractor(account['db_storage'], progress=key_progress,cancel=check_connection)
            ex.extract(save_to=str(keys_file))
            check_connection()
            keys = {k:v for k,v in key.load_keys(str(keys_file)).items() if not k.startswith('_')}
            if not keys:
                raise ValueError('未获取到可用密钥。请确认微信已登录；若权限不足，请以管理员身份重新打开软件。此版本也可能需要进一步适配。')
            destination = slot/('snapshot_'+job['id'][:12])
            self._update(job, progress=45, detail='正在创建本地聊天快照…')
            n = 0
            def dec_progress(message):
                nonlocal n
                check_connection(); n += 1
                self._update(job, progress=min(90, 45+int(45*n/max(1,len(keys)))), detail='正在整理聊天数据库…')
            try:
                res = decrypt.decrypt_all(keys, account['db_storage'], str(destination), progress=dec_progress,cancel=check_connection)
                check_connection()
                validate_root(destination)
                lib = dict(name=account['dir_name'], root=str(destination), wxid=account['wxid'],
                           account_dir=account['path'], imported_at=datetime.now().strftime('%Y-%m-%d %H:%M'))
                archive = Archive(lib)
                try:
                    sessions = archive.sessions()
                    if not sessions: raise ValueError('快照中没有可用会话，请检查账号或重新同步。')
                    self.hydrate_profile(archive,lib)
                    self._update(job,title='连接微信 · '+lib['name'])
                finally: archive.close()
                failed = len(res['failed'])
                with self.lock:
                    check_connection()
                    self.library = lib; self.config['library'] = lib
                self._update(job, detail='已连接，找到 %d 个会话%s' % (len(sessions), ('；%d 个数据库未能处理' % failed) if failed else ''))
            except BaseException:
                shutil.rmtree(destination, ignore_errors=True)
                raise
        self.pool.submit(self._run, job, work)
        return {'job':job['id']}

    def sessions(self):
        with self.lock:lib=self.library
        archive = self.archive(lib)
        try:
            self.hydrate_profile(archive,lib)
            return archive.sessions()
        finally: archive.close()

    def messages(self, payload):
        archive = self.archive()
        try:
            session = payload.get('session', '')
            if session not in {s['username'] for s in archive.sessions()}:
                raise ValueError('会话不存在')
            before=payload.get('before')
            if before is not None and (not isinstance(before,list) or len(before)!=3 or not all(isinstance(x,(int,float)) for x in before)):
                raise ValueError('分页参数无效')
            return archive.page(session, options_from(payload), before=before)
        finally: archive.close()

    def qce_preview(self,payload):
        session=(payload.get('peer') or {}).get('peerUid','')
        page=max(1,min(int(payload.get('page',1)),10000000))
        limit=max(1,min(int(payload.get('limit',50)),200))
        flt=payload.get('filter') or {}
        options={'query':str(flt.get('query',''))[:200],'kind':'all'}
        if flt.get('startTime'):options['start']=int(flt['startTime'])//1000
        if flt.get('endTime'):options['end']=int(flt['endTime'])//1000
        archive=self.archive()
        try:
            if session not in {s['username'] for s in archive.sessions()}:raise ValueError('会话不存在')
            if isinstance(archive,DemoArchive):
                rows=list(archive.messages(session,options,descending=True));total=len(rows)
                rows=rows[(page-1)*limit:page*limit]
            else:rows,total=archive.numbered_page(session,options,page,limit)
            result=[]
            for m in rows:
                rich=dict(m.get('extra',{}))
                if m.get('kind')=='chatrecord' and isinstance(archive,Archive):
                    rich['forward']=clean(build_forward(archive.data,m,limit=1500))
                result.append(dict(msgId='%s_%s_%s'%(m['shard'],m['local_id'],m['server_id']),
                                   msgSeq=m['local_id'],msgTime=m['create_time'],
                                   senderUid=m['sender_wxid'],senderUin='',
                                   senderAvatar=archive.avatars.ui(m['sender_wxid']) if isinstance(archive,Archive) else '',
                                   isSystem=is_system_message(m),
                                   richContent=rich,
                                   elements=[{'textElement':{'content':m['text']}}],
                                   peerUin=session,chatType=2 if session.endswith('@chatroom') else 1,
                                   sendType=1 if m['is_sender'] else 0,subMsgType=0,
                                   sendMemberName=m['sender'],sendNickName=m['sender']))
            return dict(messages=result,totalCount=total,currentPage=page,totalPages=max(1,(total+limit-1)//limit),hasNext=page*limit<total,fetchedAt=datetime.now().isoformat())
        finally:archive.close()

    def export(self, payload):
        if not self.library: raise ValueError('请先连接数据')
        fmt=payload.get('format','html')
        if fmt not in FORMATS: raise ValueError('不支持此格式')
        library=dict(self.library)
        archive=self.archive(library)
        try:
            wanted=set(payload.get('sessions') or [])
            sessions=[s for s in archive.sessions() if s['username'] in wanted]
        finally: archive.close()
        if not sessions: raise ValueError('请先选择至少一个会话')
        if len(sessions)>1:
            with self.lock:
                if sum(t['status'] in ('queued','running') for t in self.config['tasks'])+len(sessions)>10:
                    raise ValueError('任务队列最多容纳 10 个会话，请分批导出。')
            jobs=[self.export(dict(payload,sessions=[s['username']]))['job'] for s in sessions]
            return {'job':jobs[0],'jobs':jobs}
        options=options_from(payload); options.update(format=fmt,demo=library.get('demo',False),_theme=self.export_theme())
        output=Path(self.config['export_dir']).resolve()
        job=self._new_job('export', sessions[0]['display'])
        job.update(format=fmt,session=sessions[0]['username'],start_time=options.get('start'),end_time=options.get('end'))
        job['demo']=library.get('demo',False)
        folder_name=export_folder_name(sessions[0]['display'],sessions[0]['username'])+('_演示' if job['demo'] else '')
        def work():
            staging=output/('.partial_'+job['id'])
            staging.mkdir(parents=True, exist_ok=False)
            archive=self.archive(library)
            records=[]; total=0
            try:
                for i, session in enumerate(sessions):
                    self._check(job)
                    def progress(n):
                        self._check(job)
                        self._update(job, count=total+n, progress=int(100*i/len(sessions)),
                                     detail='正在导出 %s · %s 条' % (session['display'],n))
                    result=export_session(archive,session,options,staging,self.assets,progress,lambda:self._check(job),
                        status=lambda message:self._update(job,detail=message))
                    total+=result['count']; records.append(result)
                export_index(staging, records, demo=job['demo'],theme=options['_theme'])
                self._check(job)
                folder=unused_folder(output,folder_name)
                os.replace(staging,folder)
                for r in records: r['path']=str(folder/Path(r['path']).relative_to(staging))
                self._update(job, folder=str(folder), files=records, count=total,
                             start_time=records[0].get('start_time'),end_time=records[-1].get('end_time'),
                             resource_summary=records[0].get('resource_summary',{}),
                             detail='已保存 %d 个会话，共 %s 条消息' % (len(records),f'{total:,}'))
            finally:
                archive.close()
                if staging.exists(): shutil.rmtree(staging,ignore_errors=True)
        self.pool.submit(self._run, job, work)
        return {'job':job['id']}

    def cancel(self, job_id):
        if job_id in self.events: self.events[job_id].set()
        return {'ok':True}

    def account_assets(self,payload):
        from .account_assets import StickerCatalog,MomentsCatalog,moment_selection
        with self.lock:library=dict(self.library or {})
        if not library or library.get('demo'):
            return {'available':False,'notice':'请先连接微信账号；演示模式不包含真实的表情包和朋友圈。'}
        kind=payload.get('kind')
        if kind=='stickers':return StickerCatalog(library).summary()
        if kind!='moments':raise ValueError('不支持的资源类型')
        archive=self.archive(library)
        try:
            profile=archive.profile();selection=moment_selection(payload,profile['wxid'],archive.data.contacts,allow_empty=True)
            dates=options_from({k:payload[k] for k in ('start','end') if k in payload})
            result=MomentsCatalog(library,profile['wxid'],selection['scope'],selection['author_id']).summary(dates.get('start'),dates.get('end'),archive.data.name_of)
            result['selection']=selection
            from .account_exporting import local_moments_previews
            preview_key=(library['root'],library.get('assets_revision'),selection['scope'],selection['author_id'],dates.get('start'),dates.get('end'))
            with self.lock:posts=self._moments_preview_cache.get(preview_key)
            if posts is None:
                posts=local_moments_previews(archive,library,selection,dates.get('start'),dates.get('end'))
                with self.lock:
                    if len(self._moments_preview_cache)>=8:self._moments_preview_cache.clear()
                    self._moments_preview_cache[preview_key]=posts
            result['posts']=posts
            return result
        finally:archive.close()

    def refresh_assets(self,payload=None):
        from .account_assets import open_asset_db,tables
        payload=dict(payload or {});prepare_stickers=payload.get('kind')=='stickers'
        with self.lock:
            library=dict(self.library or {});epoch=self._library_epoch
            if not library.get('account_dir') or library.get('demo'):raise ValueError('请先连接本机微信账号，再刷新资源快照。')
            if any(t['kind'] in ('connect','refresh_assets') and t['status'] in ('queued','running') for t in self.config['tasks']):
                raise ValueError('正在连接或刷新微信，请等待当前任务完成。')
            job=self._new_job('refresh_assets','刷新表情包与朋友圈快照')
            if prepare_stickers:job.update(title='缓存所选表情资源',category='stickers')
        def check():
            self._check(job)
            with self.lock:
                if epoch!=self._library_epoch or not self.library or self.library.get('root')!=library.get('root'):raise Cancelled()
        def work():
            from wx4 import key,decrypt
            slot=Path(library['root']).parent;destination=slot/('assets_'+job['id'][:12])
            try:
                check();keys_file=slot/'keys.json'
                if not keys_file.is_file():raise ValueError('未找到当前快照的读取凭据，请重新连接微信。')
                credentials=key.load_keys(str(keys_file))
                targets={'emoticon/emoticon.db','sns/sns.db'}
                selected={name:value for name,value in credentials.items() if name.replace('\\','/') in targets}
                if not selected:raise ValueError('当前微信归档尚无表情或朋友圈读取凭据，请重新连接并整理微信。')
                self._update(job,progress=15,detail='正在复制并整理最新资源数据库…')
                result=decrypt.decrypt_all(selected,str(Path(library['account_dir'])/'db_storage'),str(destination),cancel=check)
                check();ok={name.replace('\\','/') for name in result['ok']}
                if not ok:raise ValueError('资源快照未能更新，微信凭据可能已变化。请重新连接并整理微信。')
                for relative in targets:
                    target=destination/relative
                    if relative not in ok:
                        target.unlink(missing_ok=True)
                        source=Path(library.get('assets_root') or library['root'])/relative
                        if source.is_file():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
                candidate={**library,'assets_root':str(destination)}
                for relative,table in [('emoticon/emoticon.db','kNonStoreEmoticonTable'),('sns/sns.db','SnsTimeLine')]:
                    con=open_asset_db(candidate,relative)
                    if con is not None:
                        try:
                            if table not in tables(con):raise ValueError('资源数据库结构暂不受支持，请重新连接微信。')
                        finally:con.close()
                if prepare_stickers:
                    from .account_exporting import export_stickers
                    cache_folder=destination/'sticker-cache';cache_folder.mkdir()
                    archive=self.archive(candidate)
                    try:
                        cached=export_stickers(archive,candidate,{**payload,'download':True},cache_folder,self.assets,
                            lambda n,total:self._update(job,count=n,progress=20+int(75*n/max(1,total))),check,
                            lambda msg:self._update(job,detail=msg))
                        self._update(job,resource_summary=cached['resource_summary'])
                    finally:archive.close()
                with self.lock:
                    check();self.library={**self.library,'assets_root':str(destination),'assets_revision':job['id']}
                    self.library.pop('moments_prepared',None)
                    self.config['library']=self.library
                detail='资源快照已更新。'
                if prepare_stickers:detail='所选表情资源已尝试缓存；失效链接和未开放下载地址的条目仍可能缺失。'
                self._update(job,detail=detail)
            except BaseException:
                if destination.resolve().parent==slot.resolve() and destination.name=='assets_'+job['id'][:12]:
                    shutil.rmtree(destination,ignore_errors=True)
                raise
        self.pool.submit(self._run,job,work)
        return {'job':job['id']}

    def export_account(self,payload):
        from .account_exporting import export_stickers,export_moments
        from .account_assets import moment_selection
        kind=payload.get('kind')
        if kind not in ('stickers','moments'):raise ValueError('不支持的资源类型')
        with self.lock:library=dict(self.library or {})
        if not library or library.get('demo'):raise ValueError('请先连接真实微信账号。')
        options=dict(payload);options['_theme']=self.export_theme()
        if kind=='moments':
            dates=options_from({k:payload[k] for k in ('start','end') if k in payload});options.update(_start=dates.get('start'),_end=dates.get('end'))
        archive=self.archive(library)
        try:
            profile=archive.profile()
            selection=moment_selection(payload,profile['wxid'],archive.data.contacts) if kind=='moments' else None
            if selection:options.update(scope=selection['scope'],authorId=selection['author_id'])
        finally:archive.close()
        label='表情包' if kind=='stickers' else selection['label'];title=profile['name']+' · '+label
        output=Path(self.config['export_dir']).resolve()
        job=self._new_job('export',title);job.update(category=kind,format=kind,demo=False)
        folder_name=export_folder_name(profile['name']+'_'+label,(selection['author_id'] if selection else '') or profile['wxid'])
        def work():
            staging=output/('.partial_'+job['id']);staging.mkdir(parents=True,exist_ok=False)
            archive=None
            try:
                archive=self.archive(library)
                def progress(count,total):
                    self._check(job)
                    self._update(job,count=count,progress=min(95,int(count*95/total)) if total else 20,
                                 detail='正在导出%s · %s%s'%(label,count,('/'+str(total)) if total else ''))
                exporter=export_stickers if kind=='stickers' else export_moments
                result=exporter(archive,library,options,staging,self.assets,progress,lambda:self._check(job),lambda msg:self._update(job,detail=msg))
                self._check(job);folder=unused_folder(output,folder_name);os.replace(staging,folder)
                result['path']=str(folder/'index.html')
                self._update(job,folder=str(folder),files=[result],count=result['count'],resource_summary=result['resource_summary'],
                             start_time=result.get('start_time'),end_time=result.get('end_time'),
                             detail='已保存 %s %s'%(result['count'],'张表情记录' if kind=='stickers' else '条朋友圈'))
            finally:
                if archive:archive.close()
                if staging.exists() and staging.resolve().parent==output and staging.name=='.partial_'+job['id']:
                    shutil.rmtree(staging,ignore_errors=True)
        self.pool.submit(self._run,job,work)
        return {'job':job['id']}

    def delete_task(self,job_id):
        with self.lock:
            task=next((t for t in self.config['tasks'] if t['id']==job_id),None)
            if not task:raise ValueError('任务不存在')
            if task['status'] in ('running','queued'):raise ValueError('请先停止任务')
            self.config['tasks'].remove(task)
            self.events.pop(job_id,None)
            self.save()
        return self.state()

    def delete_tasks(self,payload):
        """Remove history only. Active jobs and every exported file stay intact."""
        category=payload.get('category','all')
        if category not in ('all','sessions','moments','stickers'):raise ValueError('任务分类无效')
        clear=payload.get('clear',False);ids=payload.get('ids')
        if not isinstance(clear,bool) or clear and ids is not None:raise ValueError('清理任务选项无效')
        if not clear and (not isinstance(ids,list) or not ids or len(ids)>80 or any(not isinstance(v,str) for v in ids)):
            raise ValueError('请先选择任务记录')
        with self.lock:
            wanted=set(ids or [])
            candidates=[t for t in self.config['tasks'] if (clear or t['id'] in wanted) and (category=='all' or task_category(t)==category)]
            if not clear and any(t['status'] in ('queued','running') for t in candidates):raise ValueError('请先停止进行中的任务，再删除记录。')
            removed={t['id'] for t in candidates if t['status'] not in ('queued','running')}
            self.config['tasks']=[t for t in self.config['tasks'] if t['id'] not in removed]
            for job_id in removed:self.events.pop(job_id,None)
            self.save()
        return {'deleted':len(removed),'state':self.state()}

    def task_file(self,job_id):
        folder=self.task_folder(job_id)
        with self.lock:
            task=next(t for t in self.config['tasks'] if t['id']==job_id)
            files=task.get('files') or []
            path=Path(files[0]['path']).resolve() if len(files)==1 else folder/'index.html'
            if path.is_relative_to(folder) and path.is_file():return path
        raise ValueError('导出文件不存在')

    def task_folder(self, job_id):
        with self.lock:
            for t in self.config['tasks']:
                if t['id']==job_id and t.get('folder') and t['status']=='completed':
                    p=Path(t['folder']).resolve()
                    if p.is_dir(): return p
        raise ValueError('导出目录不存在或任务尚未完成')

    def settings(self, payload):
        preference=session_sort(payload['session_sort']) if 'session_sort' in payload else None
        with self.lock:
            theme=payload.get('theme');accent=payload.get('accent')
            if accent is not None and (not isinstance(accent,str) or accent not in ACCENT_IDS):raise ValueError('主题色不受支持')
            if theme in ('light','dark'):self.config['theme']=theme
            if accent is not None:self.config['accent']=accent
            if preference is not None:self.config['session_sort']=preference
            self.save()
        return self.state()

    def asset_tutorial(self,payload,mark=False):
        kind=payload.get('kind')
        if kind not in ('app','moments','stickers'):raise ValueError('新手教程类型无效')
        with self.lock:
            target=self.config if kind=='app' else self.config['asset_tutorials']
            key='app_onboarding_seen' if kind=='app' else kind
            seen=target[key]
            if mark and not seen:
                target[key]=True
                try:self.save()
                except OSError:
                    target[key]=False
                    raise ValueError('教程显示记录未能保存，请检查软件数据目录的写入权限。') from None
            return {'seen':target[key]}

    def call(self, action, payload):
        handlers={'state':self.state, 'demo':self.demo, 'return_from_demo':self.return_from_demo,'detect':self.detect,
                  'startup_reconnect':self.startup_reconnect, 'reconnect':self.reconnect,'logout':self.logout,
                  'avatar':lambda:self.avatar(payload.get('url')),
                  'sessions':self.sessions, 'messages':lambda:self.messages(payload),
                  'qce_preview':lambda:self.qce_preview(payload),
                  'connect':lambda:self.connect(payload.get('accountId')),
                  'export':lambda:self.export(payload),
                  'account_assets':lambda:self.account_assets(payload),
                  'refresh_assets':lambda:self.refresh_assets(payload),'export_account':lambda:self.export_account(payload),
                  'cancel':lambda:self.cancel(payload.get('id')),
                  'delete_task':lambda:self.delete_task(payload.get('id')),
                  'delete_tasks':lambda:self.delete_tasks(payload),
                  'tutorial_status':lambda:self.asset_tutorial(payload),
                  'tutorial_seen':lambda:self.asset_tutorial(payload,mark=True),
                  'online_status':lambda:self.online.status(True),
                  'online_check':lambda:self.online.check(payload.get('startup') is True),
                  'notice_focus':lambda:self.online.notice_focus(payload),
                  'notice_read':lambda:self.online.notice_read(payload),
                  'online_image':lambda:self.online.image(payload),
                  'update_download':self.online.download_update,
                  'settings':lambda:self.settings(payload)}
        if action not in handlers: raise ValueError('不支持的操作')
        return handlers[action]()

    def shutdown(self):
        self.online.close()
        for event in self.events.values(): event.set()
        self.pool.shutdown(wait=False,cancel_futures=True)
        self.save()
