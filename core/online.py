"""Public announcements and authenticated downloads, isolated from chat jobs."""
import base64
import hashlib
import io
import json
import os
import subprocess
import shutil
import uuid
import sys
import threading
import time
import urllib.request
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path

from .online_protocol import MAX_FEED,file_hash,timestamp,verify_feed,version,web_url
from .version import VERSION
from .channel_control import release_key,current_feed,require_current_release
from .windows_version import require_windows_build


class TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,hosts):self.hosts=hosts
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        web_url(newurl,self.hosts)
        return super().redirect_request(request,fp,code,msg,headers,newurl)


class OnlineChannel:
    def __init__(self,service,config=None):
        self.service=service;self.root=service.root/'online';self.lock=threading.RLock()
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='public-channel')
        self.stop=threading.Event();self.feed=None;self.envelope=None;self.notices={};self.checked_at='';self.error='';self.checking=False;self.started=False
        self.revision=0;self.visible={};self.download={'status':'idle','progress':0,'received':0,'total':0};self.downloading=False
        self.apply_pending=False
        self.initial_check_done=False;self.download_cancel=threading.Event();self.download_epoch=0
        try:self.config=config if config is not None else json.loads((service.assets/'online-config.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):self.config={}
        self.hosts=set(self.config.get('hosts',[]));self.configured=False
        try:
            web_url(self.config.get('endpoint'),self.hosts)
            self.configured=bool(self.config.get('public_key'))
        except (ValueError,TypeError):pass
        try:self.saved=json.loads((self.root/'state.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):self.saved={}
        if not isinstance(self.saved,dict):self.saved={}
        self.read=set(v for v in self.saved.get('read',[]) if isinstance(v,str)) if isinstance(self.saved.get('read',[]),list) else set()
        self.sequence=self.saved.get('sequence',0)
        if type(self.sequence) is not int or self.sequence<0:self.sequence=0
        if self.configured and self.saved.get('envelope'):
            try:self._accept(self.saved['envelope'],persist=False)
            except ValueError:pass

    def _save(self):
        self.root.mkdir(parents=True,exist_ok=True)
        state={'sequence':self.sequence,'read':sorted(self.read)[-5000:],'envelope':self.envelope}
        temporary=self.root/'state.tmp';temporary.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8');os.replace(temporary,self.root/'state.json')

    def _accept(self,envelope,persist=True):
        data=verify_feed(envelope,self.config['public_key'],self.hosts,minimum_sequence=self.sequence)
        previous=self.feed
        self.feed=data;self.envelope=envelope;self.sequence=data['sequence'];self.revision+=1
        try:
            if persist:self._save()
        finally:self._reconcile(previous,data)

    def _remove_managed(self,path,images=False):
        if not path:return
        path=Path(path)
        pattern=r'[0-9a-f]{64}' if images else r'[0-9a-f]{64}\.(exe|zip)(\.part)?'
        folder=self.root/('images' if images else 'downloads')
        try:
            if re.fullmatch(pattern,path.name) and path.parent.resolve()==folder.resolve() and path.resolve().is_relative_to(self.root.resolve()):path.unlink(missing_ok=True)
        except OSError:pass

    def _reconcile(self,previous,current):
        active={n['id'] for n in self._active_notices()}
        self.visible={uid:value for uid,value in self.visible.items() if uid in active}
        old_hashes={sha for n in (previous or {}).get('announcements',[]) for sha in n.get('assets',{}).values()}
        new_hashes={sha for n in current.get('announcements',[]) for sha in n.get('assets',{}).values()}
        for sha in old_hashes-new_hashes:self._remove_managed(self.root/'images'/sha,images=True)
        cached=getattr(self,'download_envelope',None)
        key=self.download.get('release_key')
        if not key and cached:
            try:key=release_key(verify_feed(cached,self.config['public_key'],self.hosts).get('release'))
            except ValueError:key='invalid'
        if key and key!=release_key(current.get('release')):
            self.download_epoch+=1;self.download_cancel.set()
            self._remove_managed(getattr(self,'download_path',None))
            for name in ('download_path','download_envelope'):
                if hasattr(self,name):delattr(self,name)
            self.download={'status':'revoked','progress':0,'received':0,'total':0,
                'error':'此前更新已被撤回、删除或替换，已停止使用该更新，请重新检查。'}

    def _active_notices(self):
        if not self.feed or timestamp(self.feed['expires_at'])<=time.time():return []
        now=time.time();current=version(VERSION);items=[]
        for item in self.feed['announcements']:
            if timestamp(item['published_at'])>now:continue
            if item.get('expires_at') and timestamp(item['expires_at'])<=now:continue
            if item.get('min_version') and current<version(item['min_version']):continue
            if item.get('max_version') and current>version(item['max_version']):continue
            items.append({**item,'read':item['id'] in self.read})
        return sorted(items,key=lambda i:timestamp(i['published_at']),reverse=True)

    @staticmethod
    def install_mode():
        if not getattr(sys,'frozen',False):return 'source'
        return 'installer' if any(Path(sys.executable).parent.glob('unins*.exe')) else 'portable'

    def status(self,details=False):
        with self.lock:
            notices=self._active_notices();release=(self.feed or {}).get('release')
            eligible=bool(release and timestamp(self.feed['expires_at'])>time.time() and timestamp(release['published_at'])<=time.time() and version(release['version'])>version(VERSION))
            result={'configured':self.configured,'checking':self.checking,'checked_at':self.checked_at,'error':self.error,
                    'revision':self.revision,'unread_count':sum(not i['read'] for i in notices),'has_update':eligible,
                    'latest_version':release['version'] if release else '', 'download':dict(self.download),'install_mode':self.install_mode()}
            result['initial_check_done']=self.initial_check_done;result['download']['active']=self.downloading
            if details:result.update(announcements=notices,release=release if eligible else None)
            return result

    def _opener(self):return urllib.request.build_opener(TrustedRedirect(self.hosts))

    def _bytes(self,url,limit):
        web_url(url,self.hosts)
        request=urllib.request.Request(url,headers={'User-Agent':'Moect/'+VERSION,'Accept-Encoding':'identity','Cache-Control':'no-cache'})
        with self._opener().open(request,timeout=8) as response:
            blob=response.read(limit+1)
            if len(blob)>limit:raise ValueError('发布资源超过允许大小')
            return blob

    def check(self,startup=False):
        with self.lock:
            if startup and self.started:return self.status()
            self.started=True
            if not self.configured:self.initial_check_done=True;return self.status()
            if self.checking:return self.status()
            self.checking=True
        def work():
            try:
                envelope=json.loads(self._bytes(self.config['endpoint'],MAX_FEED*2))
                with self.lock:self._accept(envelope);self.error='';self.checked_at=datetime.now(timezone.utc).isoformat()
            except Exception as error:
                with self.lock:self.error=str(error) if isinstance(error,ValueError) else '暂时无法连接发布服务，请稍后重试。'
            finally:
                with self.lock:self.checking=False;self.initial_check_done=True
        self.pool.submit(work)
        return self.status()

    def notice_focus(self,payload):
        uid=payload.get('id');active=payload.get('active')
        if not isinstance(uid,str) or not isinstance(active,bool):raise ValueError('公告阅读状态无效')
        with self.lock:
            if uid not in {i['id'] for i in self._active_notices()}:raise ValueError('该公告已不可用')
            elapsed,started=self.visible.get(uid,(0,None));now=time.monotonic()
            if started is not None:elapsed+=max(0,now-started)
            self.visible[uid]=(elapsed,now if active else None)
            return {'remaining':max(0,2-elapsed)}

    def notice_read(self,payload):
        uid=payload.get('id')
        if not isinstance(uid,str):raise ValueError('公告编号无效')
        with self.lock:
            if uid not in {i['id'] for i in self._active_notices()}:raise ValueError('该公告已不可用')
            elapsed,started=self.visible.get(uid,(0,None))
            if started is not None:elapsed+=max(0,time.monotonic()-started)
            if uid not in self.read and elapsed<2:raise ValueError('请阅读两秒后再确认')
            already=uid in self.read;self.read.add(uid)
            try:self._save()
            except OSError:
                if not already:self.read.discard(uid)
                raise ValueError('已读状态未保存，请检查数据目录写入权限。') from None
            self.revision+=1
        return self.status(True)

    def image(self,payload):
        url=payload.get('url');expected=None
        if not isinstance(url,str):return {'url':''}
        with self.lock:
            for notice in self._active_notices():
                if url in notice.get('assets',{}):expected=notice['assets'][url];break
        if not expected:return {'url':''}
        target=self.root/'images'/expected
        try:
            blob=target.read_bytes() if target.is_file() else self._bytes(url,5*1024*1024)
            if hashlib.sha256(blob).hexdigest()!=expected:raise ValueError('公告图片校验失败')
            from PIL import Image
            with Image.open(io.BytesIO(blob)) as picture:
                if picture.width*picture.height>24_000_000 or picture.format not in ('PNG','JPEG','WEBP','GIF'):raise ValueError('公告图片格式无效')
                mime=Image.MIME[picture.format];picture.verify()
            with self.lock:
                if not any(n.get('assets',{}).get(url)==expected for n in self._active_notices()):return {'url':''}
                if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(blob)
            return {'url':'data:'+mime+';base64,'+base64.b64encode(blob).decode()}
        except (OSError,ValueError):return {'url':''}

    def download_update(self):
        with self.lock:
            state=self.status(True);release=state['release']
            if not release:raise ValueError('暂无可用的新版本')
            mode=state['install_mode'];mode='installer' if mode=='source' else mode
            package=release['packages'].get(mode)
            if not package:raise ValueError('暂未发布适用于当前安装方式的更新包')
            require_windows_build(release.get('minimum_windows_build',17763))
            if self.downloading:return self.status()
            self.download_cancel=threading.Event();cancel=self.download_cancel;epoch=self.download_epoch;key=release_key(release)
            self.downloading=True;self.download={'status':'downloading','progress':0,'received':0,'total':package['size'],'version':release['version'],'mode':mode,'release_key':key}
            envelope=dict(self.envelope)
        def work():
            suffix='.exe' if mode=='installer' else '.zip';target=self.root/'downloads'/(package['sha256']+suffix);partial=target.with_suffix(suffix+'.part');replace_pending=False
            try:
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.is_file() or target.stat().st_size!=package['size'] or file_hash(target)!=package['sha256']:
                    received=0;deadline=time.monotonic()+1800
                    if shutil.disk_usage(target.parent).free<package['size']+32*1024*1024:raise ValueError('下载目录可用空间不足，请清理后重试。')
                    with partial.open('wb') as output:
                        for part in package.get('parts') or [package]:
                            request=urllib.request.Request(web_url(part['url'],self.hosts),headers={'User-Agent':'Moect/'+VERSION,'Accept-Encoding':'identity'})
                            part_hash=hashlib.sha256();part_size=0
                            with self._opener().open(request,timeout=20) as response:
                                while True:
                                    if self.stop.is_set() or cancel.is_set():raise ValueError('下载已取消')
                                    if time.monotonic()>deadline:raise ValueError('下载超时，请重试')
                                    blob=response.read(256*1024)
                                    if not blob:break
                                    received+=len(blob);part_size+=len(blob);part_hash.update(blob)
                                    if received>package['size'] or part_size>part['size']:raise ValueError('更新包大小与发布信息不符')
                                    output.write(blob)
                                    with self.lock:
                                        if cancel.is_set() or epoch!=self.download_epoch:raise ValueError('该更新已不可用')
                                        self.download.update(received=received,progress=round(received*100/package['size']))
                            if part_size!=part['size'] or part_hash.hexdigest()!=part['sha256']:raise ValueError('更新分片校验失败，请重新下载。')
                    if received!=package['size'] or file_hash(partial)!=package['sha256']:raise ValueError('更新包校验失败，请重新下载')
                    replace_pending=True
                with self.lock:
                    if cancel.is_set() or epoch!=self.download_epoch or key!=release_key((self.feed or {}).get('release')):raise ValueError('该更新已不可用')
                    if replace_pending:os.replace(partial,target)
                    self.download.update(status='ready',progress=100,received=package['size']);self.download_path=target;self.download_envelope=envelope
            except Exception as error:
                self._remove_managed(partial)
                with self.lock:
                    if cancel.is_set() or epoch!=self.download_epoch:
                        self._remove_managed(target)
                        self.download={'status':'revoked','progress':0,'received':0,'total':0,'error':'更新已被撤回、删除或替换，下载已取消。'}
                    else:self.download.update(status='failed',error=str(error) if isinstance(error,ValueError) else '更新包下载失败，请检查网络和可用空间后重试。')
            finally:
                with self.lock:self.downloading=False
        self.pool.submit(work)
        return self.status()

    def prepare_apply(self):
        with self.service.lock:
            if any(t['status'] in ('queued','running') for t in self.service.config['tasks']):raise ValueError('请等待当前连接、整理或导出任务结束后再更新。')
        with self.lock:
            if self.install_mode()=='source':raise ValueError('当前从源码运行；安装版或便携版支持更新并重启。')
            if self.apply_pending:raise ValueError('更新已准备启动，请稍候。')
            if self.download.get('status')!='ready':raise ValueError('请先下载并校验更新包')
            expected_release=verify_feed(self.download_envelope,self.config['public_key'],self.hosts).get('release');minimum=self.sequence
        envelope,latest=current_feed(self.config,minimum_sequence=minimum)
        with self.lock:
            self._accept(envelope)
            require_current_release(expected_release,latest.get('release'))
        with self.service.lock:
            if any(t['status'] in ('queued','running') for t in self.service.config['tasks']):raise ValueError('请等待当前连接、整理或导出任务结束后再更新。')
            with self.lock:
                if self.install_mode()=='source':raise ValueError('当前从源码运行；安装版或便携版支持更新并重启。')
                if self.apply_pending:raise ValueError('更新已准备启动，请稍候。')
                if self.download.get('status')!='ready':raise ValueError('请先下载并校验更新包')
                release=verify_feed(self.envelope,self.config['public_key'],self.hosts)['release'];require_current_release(expected_release,release)
                require_windows_build(release.get('minimum_windows_build',17763))
                mode=self.install_mode();package=release['packages'][mode]
                if version(release['version'])<=version(VERSION):raise ValueError('不能安装旧版本')
                if self.download_path.stat().st_size!=package['size'] or file_hash(self.download_path)!=package['sha256']:raise ValueError('更新包已变化，请重新下载')
                helper=Path(sys.executable).parent/'MoectUpdater.exe'
                if not helper.is_file():raise ValueError('更新组件缺失，请使用完整安装包修复安装。')
                plan={'target':str(Path(sys.executable).parent.resolve()),'parent_pid':os.getpid(),'package':str(self.download_path.resolve()),'mode':mode,'envelope':self.envelope}
                path=self.root/'apply.json';path.write_text(json.dumps(plan),encoding='utf-8')
                # The helper reads its own bundled trust key, never a key from this plan.
                # Run a standalone copy so Windows does not lock the helper that
                # the new installation itself needs to replace.
                helper_copy=self.root/'helpers'/uuid.uuid4().hex/'MoectUpdater.exe'
                helper_copy.parent.mkdir(parents=True);shutil.copy2(helper,helper_copy)
                self.service._updating=True
                try:subprocess.Popen([str(helper_copy),'--plan',str(path)],creationflags=0x08000000,close_fds=True)
                except Exception:
                    self.service._updating=False
                    raise
                self.apply_pending=True
                return {'ready':True}

    def close(self):self.stop.set();self.pool.shutdown(wait=False,cancel_futures=True)
