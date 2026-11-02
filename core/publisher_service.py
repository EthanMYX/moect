"""Private author-console state, editing and publication jobs; never imports chat data."""
import base64
import copy
import hashlib
import io
import json
import os
import tempfile
import threading
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, unquote

from Cryptodome.PublicKey import ECC
from scripts import publish_channel as channel
from .publisher_cloud import CloudflareR2, NoRedirect, fetch_public
from .online_protocol import web_url
from .channel_control import release_key
from .publisher_management import PublicationManagement
from .publisher_paths import prepare_author_root


def atomic(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


class AuthorSetupError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


class PublisherService(PublicationManagement):
    def __init__(self):
        self.root = channel.ROOT
        prepare_author_root(self.root,channel.SOURCE/'ui/online-config.json')
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='moect-publisher')
        self.config = self._read('publisher-ui.json', {'theme': 'light'})
        self.editor = self._read('editor-state.json', {})
        self.history = self._read('history.json', [])
        if not isinstance(self.history, list):self.history = []
        self.job = {'status': 'idle', 'label': '', 'progress': 0}
        self.connection = {'status': 'unchecked', 'message': '尚未检查连接', 'checked_at': ''}
        self.setup_error = ''
        self.setup_error_code = ''
        self.setup_diagnostic = {}
        self.trust = {}
        self.refresh_setup()

    def _read(self, name, fallback):
        try:
            value=json.loads((self.root/name).read_text(encoding='utf-8'))
            return value if isinstance(value,type(fallback)) else copy.deepcopy(fallback)
        except (OSError, ValueError):return copy.deepcopy(fallback)

    def _validate_signer(self):
        try:raw=(self.root/'signing-key.pem').read_text(encoding='utf-8-sig')
        except FileNotFoundError as error:
            self.setup_diagnostic.update(operation='read_key',failed_path=str(error.filename),errno=error.errno,winerror=getattr(error,'winerror',None),key_exists=(self.root/'signing-key.pem').is_file())
            raise AuthorSetupError('missing_key','未找到原发布签名私钥，请恢复下方作者目录中的 signing-key.pem。') from None
        except OSError:
            raise AuthorSetupError('unreadable_key','原签名私钥暂时无法读取，请检查作者目录权限或文件占用，然后重新检测。') from None
        except UnicodeError:
            raise AuthorSetupError('invalid_key','原签名私钥文件编码无效，请从原作者资料恢复后重新检测。') from None
        try:key=ECC.import_key(raw)
        except (ValueError,TypeError,IndexError):
            raise AuthorSetupError('invalid_key','原签名私钥格式无效或文件已损坏，请从原作者资料恢复。') from None
        if not key.has_private() or key.curve!='Ed25519':
            raise AuthorSetupError('invalid_key','作者目录需要原始 Ed25519 签名私钥，公钥文件不能用于发布。')
        try:trusted=ECC.import_key(self.trust.get('public_key',''))
        except (ValueError,TypeError,IndexError):
            raise AuthorSetupError('invalid_trust','发布中心内置验签配置无效，请使用完整的发布中心程序。') from None
        if trusted.has_private() or trusted.curve!='Ed25519':
            raise AuthorSetupError('invalid_trust','发布中心内置验签配置无效，请使用完整的发布中心程序。')
        if key.public_key().export_key(format='DER')!=trusted.export_key(format='DER'):
            raise AuthorSetupError('key_mismatch','原签名私钥与此发布中心的公钥不匹配，已停止发布；请使用原作者资料及配套程序。')

    def refresh_setup(self):
        """Retry the actual files, never latch a transient startup read failure."""
        with self.lock:
            prepare_author_root(self.root,channel.SOURCE/'ui/online-config.json')
            self.setup_diagnostic={'at':channel.utc(),'pid':os.getpid(),'thread':threading.get_native_id(),'author_dir':str(self.root),'expected_key':str(self.root/'signing-key.pem')}
            self.trust={}
            try:
                try:trust=json.loads((channel.SOURCE/'ui/online-config.json').read_text(encoding='utf-8-sig'))
                except OSError:
                    raise AuthorSetupError('unreadable_trust','发布中心内置验签配置暂时无法读取，请重新检测；仍失败时重新打开完整程序。') from None
                except (ValueError,UnicodeError):
                    raise AuthorSetupError('invalid_trust','发布中心内置验签配置格式无效，请使用完整的发布中心程序。') from None
                if not isinstance(trust,dict) or not isinstance(trust.get('hosts'),list) or not trust['hosts'] or not all(isinstance(host,str) for host in trust['hosts']):
                    raise AuthorSetupError('invalid_trust','发布中心内置验签配置无效，请使用完整的发布中心程序。')
                try:web_url(trust.get('endpoint'),set(trust['hosts']))
                except ValueError:
                    raise AuthorSetupError('invalid_trust','发布中心内置分发地址无效，请使用完整的发布中心程序。') from None
                self.trust=trust
                self._validate_signer()
            except AuthorSetupError as error:
                self.setup_error=str(error);self.setup_error_code=error.code
                self._record_setup_diagnostic(error.code)
                return False
            self.setup_error='';self.setup_error_code=''
            self._record_setup_diagnostic('ok')
            return True

    def _record_setup_diagnostic(self,result):
        self.setup_diagnostic['result']=result
        try:
            events=self._read('identity-diagnostic.json',[])
            atomic(self.root/'identity-diagnostic.json',(events+[dict(self.setup_diagnostic)])[-30:])
        except OSError:pass

    def save(self):
        with self.lock:atomic(self.root/'publisher-ui.json', self.config)

    def appearance(self):return {'background': '#141218' if self.config.get('theme')=='dark' else '#f7f5fb'}

    def status(self):
        with self.lock:
            draft = self._read('draft.json', {'announcements': [], 'release': None, 'sequence': 0})
            release = draft.get('release')
            cloud = self._read('cloudflare.json', {})
            return {'editor': copy.deepcopy(self.editor), 'theme': self.config.get('theme', 'light'),
                'setup_error': self.setup_error,'setup_error_code':self.setup_error_code,'author_dir':str(self.root), 'connection': dict(self.connection), 'job': dict(self.job),
                'endpoint': self.trust.get('endpoint', ''), 'bucket': cloud.get('bucket', ''),
                'notices': copy.deepcopy(draft.get('announcements', [])), 'release': copy.deepcopy(release),'release_key':release_key(release),
                'history': copy.deepcopy(self.history[-200:][::-1]), 'sequence': draft.get('sequence', 0),
                'key_fingerprint': hashlib.sha256(self.trust.get('public_key','').encode()).hexdigest()[:16] if self.trust else '',**self._management_state()}

    def save_editor(self, payload):
        allowed = ('title', 'body', 'days', 'version', 'notes', 'installer', 'portable', 'tab')
        result = {k:payload[k] for k in allowed if k in payload}
        for key, value in result.items():
            if key=='days':
                if type(value) is not int or value not in (0, 7, 30, 90, 180, 365):raise ValueError('公告有效期无效。')
            elif not isinstance(value,str) or len(value)>(64000 if key in ('body','notes') else 2000):
                raise ValueError('草稿字段过长或格式无效。')
        with self.lock:
            self.editor.update(result);atomic(self.root/'editor-state.json', self.editor)
        return {'saved': True}

    def set_theme(self, theme):
        if theme not in ('light','dark'):raise ValueError('主题无效。')
        with self.lock:self.config['theme']=theme;self.save()
        return {'theme':theme}

    def _progress(self, label, received=0, total=0):
        with self.lock:
            self.job.update(label=label, received=received, total=total,
                progress=round(received*100/total) if total else 0)

    def _run(self, kind, work):
        with self.lock:
            if self.job['status']=='running':raise ValueError('已有任务正在处理，请稍候。')
            self.job={'status':'running','kind':kind,'label':'正在准备…','progress':0,'id':uuid.uuid4().hex}
        def execute():
            try:
                result=work()
                with self.lock:self.job.update(status='done',label=result.get('message','已完成'),result=result,progress=100)
            except Exception as error:
                message=str(error) if isinstance(error,(ValueError,OSError)) else '操作未完成，请检查连接后重试。'
                with self.lock:self.job.update(status='failed',label=message[:500],error=message[:500])
        self.pool.submit(execute)
        return self.status()

    def check_sync(self):
        if not self.refresh_setup():raise ValueError(self.setup_error)
        cloud=self._read('cloudflare.json',{})
        if cloud.get('control_backend')!='r2':raise ValueError('本机尚未配置 R2 发布通道。')
        self._progress('正在检查本机授权和 R2 存储桶')
        CloudflareR2(cloud).info()
        self._progress('正在验证正式公告与更新服务')
        remote=fetch_public(self.trust)
        with channel.publish_lock():
            local=channel.load_draft()
            if remote['sequence']<local.get('sequence',0):
                raise ValueError('云端返回的清单早于本机记录，请稍后刷新，避免覆盖新发布。')
            if remote['sequence']>local.get('sequence',0):atomic(self.root/'draft.json',remote)
            self._sync_retired(remote)
        with self.lock:
            self.connection={'status':'connected','message':'R2 与正式分发服务连接正常','checked_at':channel.utc()}
        return {'message':'连接正常 · 已验证签名并同步发布记录'}

    def check(self):
        def work():
            try:return self.check_sync()
            except Exception:
                with self.lock:self.connection={'status':'error','message':'暂未连接，请检查网络或本机授权','checked_at':channel.utc()}
                raise
        return self._run('check',work)

    def _record(self, kind, title, result, notice_id=''):
        entry={'id':uuid.uuid4().hex,'kind':kind,'title':title,'notice_id':notice_id,
            'sequence':result['sequence'],'version':result.get('version',''),'at':channel.utc()}
        with self.lock:
            self.history.append(entry);self.history=self.history[-1000:]
            try:atomic(self.root/'history.json',self.history)
            except OSError:return '已发布成功，但本机历史记录保存失败；请刷新查看云端状态。'
        return '已发布成功 · 用户下次联网启动时会检查'

    def start(self, payload):
        if not self.refresh_setup():raise ValueError(self.setup_error)
        snapshot=copy.deepcopy(payload)
        kind=snapshot.get('kind')
        management=('withdraw_notice','withdraw_release','delete_notice','delete_release','delete_retired','retry_cleanup')
        if kind not in ('announcement','release','validate_release',*management):
            raise ValueError('发布操作无效。')
        if kind in management:return self._run(kind,lambda:self.manage_content(snapshot))
        def work():
            self._validate_signer()
            draft=channel.load_draft();uploads=[];title='';notice_id='';retired=None
            if kind=='announcement':
                title=str(snapshot.get('title','')).strip();body=str(snapshot.get('body','')).strip()
                if not title or len(title)>160 or not body or len(body)>64000:raise ValueError('请填写标题和正文，标题最多160字。')
                days=snapshot.get('days',90)
                if type(days) is not int or days not in (0,7,30,90,180,365):raise ValueError('公告有效期无效。')
                with tempfile.TemporaryDirectory(prefix='notice-',dir=self.root) as folder:
                    source=Path(folder)/'body.md'
                    # Image references are resolved against the author asset directory.
                    def absolute(match):
                        value=match.group(2).strip().strip('<>')
                        if value.startswith(('https:','http:','data:')):return match.group(0)
                        target=(self.root/unquote(value)).resolve()
                        if not target.is_relative_to((self.root/'editor-images').resolve()):raise ValueError('请用“插入图片”选择本机图片。')
                        return '!['+match.group(1)+']('+quote(target.as_posix(),safe='/:')+')'
                    source.write_text(channel.IMAGE.sub(absolute,body),encoding='utf-8')
                    draft,uploads=channel.prepare_announcement(draft,title,source,days=days)
                notice_id=draft['announcements'][-1]['id']
            elif kind in ('release','validate_release'):
                self._progress('正在校验真实版本、签名公钥和软件包')
                previous_release=copy.deepcopy(draft.get('release'))
                title=str(snapshot.get('version','')).strip()
                draft,uploads=channel.prepare_release(draft,title,snapshot.get('installer') or None,snapshot.get('portable') or None,str(snapshot.get('notes',''))[:64000])
                if kind=='validate_release':
                    channel.publish(draft,uploads,dry_run=True)
                    return {'message':'软件包检查通过 · 未上传、未发布','packages':len(draft['release']['packages'])}
                if previous_release:retired=self._stage_retired('release',previous_release,'superseded')
            self._progress('正在签名并准备上传')
            result=channel.publish(draft,uploads,progress=self._progress)
            if retired:self._commit_retired(retired,result['sequence'])
            try:
                remote=fetch_public(self.trust)
                confirmed=remote['sequence']==result['sequence']
            except ValueError:confirmed=False
            message=self._record(kind,title,result,notice_id)
            if not confirmed:message='R2 已接收发布，但公网同步尚未确认；请点击检测连接核对，不要重复发布。'
            with self.lock:self.connection={'status':'connected' if confirmed else 'unchecked','message':'发布已完成' if confirmed else '等待公网同步','checked_at':channel.utc()}
            return {**result,'message':message,'confirmed':confirmed}
        return self._run(kind,work)

    def add_image(self, path):
        from PIL import Image
        path=Path(path)
        if not path.is_file() or path.stat().st_size>5*1024*1024:raise ValueError('图片不存在或超过5 MB。')
        blob=path.read_bytes()
        with Image.open(io.BytesIO(blob)) as picture:
            if picture.format not in ('PNG','JPEG','GIF','WEBP') or picture.width*picture.height>24_000_000:raise ValueError('请选择 PNG、JPEG、GIF 或 WebP 图片，最多2400万像素。')
            extension={'PNG':'png','JPEG':'jpg','GIF':'gif','WEBP':'webp'}[picture.format];picture.verify()
        folder=self.root/'editor-images';folder.mkdir(exist_ok=True)
        target=folder/(hashlib.sha256(blob).hexdigest()+'.'+extension)
        if not target.exists():target.write_bytes(blob)
        return {'source':target.relative_to(self.root).as_posix(),'markdown':'![公告配图]('+target.relative_to(self.root).as_posix()+')'}

    def preview_image(self, source):
        from PIL import Image
        if not isinstance(source,str) or source.startswith(('http:','data:')):return {'url':''}
        if source.startswith('https:'):
            notices=self._read('draft.json',{}).get('announcements',[])+[v['item'] for v in self._read('retired.json',[]) if v.get('kind')=='announcement']
            expected=next((n.get('assets',{}).get(source) for n in notices if source in n.get('assets',{})),None)
            if not expected:return {'url':''}
            if not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):return {'url':''}
            url=web_url(source,set(self.trust.get('hosts',[])))
            target=self.root/'public-preview'/expected
            if target.is_file():blob=target.read_bytes()
            else:
                request=urllib.request.Request(url,headers={'User-Agent':'MoectPublisher/1.0.0'})
                with urllib.request.build_opener(NoRedirect()).open(request,timeout=10) as response:blob=response.read(5*1024*1024+1)
            if len(blob)>5*1024*1024 or hashlib.sha256(blob).hexdigest()!=expected:raise ValueError('已发布公告的图片校验失败。')
        else:
            target=(self.root/unquote(source)).resolve()
            if not target.is_relative_to((self.root/'editor-images').resolve()) or not target.is_file():return {'url':''}
            if target.stat().st_size>5*1024*1024:return {'url':''}
            blob=target.read_bytes()
        with Image.open(io.BytesIO(blob)) as image:
            if image.format not in ('PNG','JPEG','GIF','WEBP') or image.width*image.height>24_000_000:return {'url':''}
            mime=Image.MIME[image.format];image.verify()
        if source.startswith('https:') and not target.exists():target.parent.mkdir(exist_ok=True);target.write_bytes(blob)
        return {'url':'data:'+mime+';base64,'+base64.b64encode(blob).decode()}

    def import_markdown(self, path):
        source=Path(path)
        if source.stat().st_size>256000:raise ValueError('Markdown 文件过大。')
        body=source.read_text(encoding='utf-8-sig')
        def image(match):
            value=match.group(2).strip().strip('<>')
            if value.startswith(('http:','https:','data:')):return match.group(0)
            target=(source.parent/unquote(value)).resolve()
            if not target.is_relative_to(source.parent.resolve()):raise ValueError('Markdown 配图须位于文档所在文件夹或其子目录；其他图片请用“插入图片”单独选择。')
            cached=self.add_image(target)
            return '!['+match.group(1)+']('+cached['source']+')'
        body=channel.IMAGE.sub(image,body)
        if len(body)>64000:raise ValueError('正文超过64000字。')
        return {'body':body}

    def close(self):self.pool.shutdown(wait=False,cancel_futures=True)
