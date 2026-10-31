"""Resolve message identities, normalize media, then publish portable references.

The resource-index and structured-reply stages follow QCE's export pipeline;
WeChat ChatName2Id/MessageResourceInfo and DAT decryption remain WeChat-specific.
"""
import hashlib
import json
import os
import re
import sqlite3
import ssl
import tempfile
import time
import urllib.request
import urllib.error
from itertools import chain
from pathlib import Path
from urllib.parse import urlparse
from .avatars import AvatarStore,image_type
from .media_codec import ImageKeys,MediaCodec,media_type,encrypted_media_variants
from wx4.reader import reference_text
from wx4.forward import build_forward

HASH=re.compile(r'(?i)(?<![a-f0-9])[a-f0-9]{32}(?![a-f0-9])')

def media_url(url):
    try:
        p=urlparse(url);host=(p.hostname or '').lower()
        domains=('qpic.cn','qlogo.cn','weixin.qq.com','wxs.qq.com','wxapp.tc.qq.com','vweixinf.tc.qq.com')
        return len(url)<=8192 and p.scheme in ('http','https') and not p.username and p.port in (None,80,443) and any(host==d or host.endswith('.'+d) for d in domains)
    except ValueError:return False


def quoted_identifier(value):return '"'+value.replace('"','""')+'"'


def thumbnail_candidate(path,hints):
    stem=path.stem.lower()
    if stem.endswith(('_t','.t','_thumb','.thumb')):return True
    base=re.sub(r'(?:_h|\.h|_hd|\.hd)$','',stem)
    return base in hints.get('thumbnail_hashes',[]) and base not in hints.get('main_hashes',[])


class ResourceStore:
    def __init__(self,data,session,destination,cancel=lambda:None,status=None):
        self.data=data;self.session=session;self.out=Path(destination);self.cancel=cancel
        self.avatars=AvatarStore(data,Path(data.root).parent/'avatar-cache')
        self.tmp=tempfile.TemporaryDirectory(prefix='wce-resource-')
        self.index=sqlite3.connect(str(Path(self.tmp.name)/'index.db'))
        self.index.executescript('''
            CREATE TABLE files (name TEXT,stem TEXT,path TEXT,scoped INTEGER);
            CREATE INDEX by_name ON files(name); CREATE INDEX by_stem ON files(stem);
            CREATE TABLE refs (server TEXT,local TEXT,kind INTEGER,ctime INTEGER,source TEXT);
            CREATE INDEX ref_server ON refs(server); CREATE INDEX ref_local ON refs(local,kind,ctime);
            CREATE TABLE messages (server TEXT,shard INTEGER,row_key INTEGER,mode TEXT);
            CREATE INDEX message_server ON messages(server);
        ''')
        self.indexed=False;self.refs_indexed=False;self.messages_indexed=False;self.forward_indexed=False;self.forward_remaining=5000
        self.codec=MediaCodec(cancel);self.keys=ImageKeys(data,cancel,self.codec,status)
        self.stats={'available':0,'missing':0,'encrypted':0,'unsupported':0,'corrupt':0}
        self.failed_downloads=set()
        self.download_outcomes={};self.prefer_direct=False
        self.report=open(self.out/'resource-report.jsonl','w',encoding='utf-8')

    def close(self):
        try:self.report.close()
        finally:self.index.close();self.tmp.cleanup()

    def _index(self):
        if self.indexed:return
        self.indexed=True
        bases=[(self.data.attach_dir(self.session),1)]
        for name in ('video','file','emoji','emotion','emoticon','record','recorditem'):
            bases.append((str(Path(self.data.msg_dir())/name),0))
        account=Path(self.data.account_dir())
        bases.extend((str(account/p),0) for p in ('cache','emotion','business/emoticon','FileStorage/CustomEmotion'))
        seen=set()
        for base,scoped in bases:
            if not base or not Path(base).is_dir():continue
            allowed=Path(base).resolve()
            if allowed in seen:continue
            seen.add(allowed)
            for root,dirs,files in os.walk(allowed,followlinks=False):
                self.cancel();dirs[:]=[d for d in dirs if not (Path(root)/d).is_symlink()]
                for name in files:
                    path=Path(root)/name
                    if path.is_symlink() or not path.resolve().is_relative_to(allowed):continue
                    if path.suffix.lower() in ('.db','.db-wal','.db-shm','.log','.ini'):continue
                    self.index.execute('INSERT INTO files VALUES (?,?,?,?)',
                        (name.casefold(),path.stem.casefold(),str(path),scoped))
        self.index.commit()

    def _index_forward_media(self):
        if self.forward_indexed:return
        self.forward_indexed=True;self._index()
        base=Path(self.data.msg_dir())/'attach'
        if not base.is_dir():return
        allowed=base.resolve();deadline=time.monotonic()+12;count=0
        # A forwarded image may retain the original conversation's file hash.
        # Only index names here; copying still requires an explicit item match.
        for root,dirs,files in os.walk(allowed,followlinks=False):
            self.cancel();dirs[:]=[d for d in dirs if not (Path(root)/d).is_symlink()]
            for name in files:
                if time.monotonic()>=deadline or count>=200000:
                    self.index.commit();return
                count+=1;path=Path(root)/name
                if path.suffix.lower() not in ('.dat','.pic','.jpg','.jpeg','.png','.gif','.webp','.wxgf','.mp4','.mov','.silk','.mp3','.wav'):continue
                if path.is_symlink() or not path.resolve().is_relative_to(allowed):continue
                self.index.execute('INSERT INTO files VALUES (?,?,?,0)',(name.casefold(),path.stem.casefold(),str(path)))
        self.index.commit()

    def _index_refs(self):
        if self.refs_indexed:return
        self.refs_indexed=True
        for rel,con in self.data._conns.items():
            if not con or 'resource' not in rel.lower():continue
            tables=self.data.tables_of(con)
            chat_ids={self.session}
            # The resource database has its OWN ChatName2Id map. Message DB
            # Name2Id rowids are not interchangeable with resource chat IDs.
            for mapping in ('ChatName2Id','Name2Id'):
                if mapping not in tables:continue
                cols={r[1].lower():r[1] for r in con.execute('PRAGMA table_info('+quoted_identifier(mapping)+')')}
                user=cols.get('user_name') or cols.get('username')
                if user:
                    for row in con.execute('SELECT rowid FROM '+quoted_identifier(mapping)+' WHERE '+quoted_identifier(user)+'=?',(self.session,)):
                        chat_ids.add(str(row[0]))
            for table in tables:
                q=quoted_identifier
                cols={r[1].lower().replace('_',''):r[1] for r in con.execute('PRAGMA table_info('+q(table)+')')}
                def column(*names):return next((cols[n] for n in names if n in cols),None)
                server=column('messagesvrid','msgsvrid','svrid','serverid')
                local=column('messagelocalid','msglocalid','localid','messageid','msgid')
                chat=column('chatid','chatnameid','username','session')
                timestamp=column('messagecreatetime','createtime','timestamp')
                kind=column('messagelocaltype','localtype','messagetype','type')
                if not server and not(local and chat):continue
                for row in con.execute('SELECT * FROM '+q(table)):
                    self.cancel()
                    if chat and str(row[chat]) not in chat_ids:continue
                    text='\n'.join(reference_text(v) for v in row if isinstance(v,(bytes,str)))
                    self.index.execute('INSERT INTO refs VALUES (?,?,?,?,?)',
                        (str(row[server]) if server and row[server] else None,
                         str(row[local]) if local and chat and row[local] else None,
                         (int(row[kind] or 0)&0xffffffff) if kind else 0,
                         int(row[timestamp] or 0) if timestamp else 0,text))
        self.index.commit()

    def _source(self,msg):
        source=msg.get('_resource_source') or msg.get('content','')
        if msg.get('_forward_item'):return source
        self._index_refs();rows=[]
        server=str(msg.get('server_id') or '')
        if server and server!='0':
            rows=list(self.index.execute('SELECT source FROM refs WHERE server=? ORDER BY ctime DESC LIMIT 8',(server,)))
        if not rows and msg.get('local_id'):
            args=(str(msg['local_id']),int(msg.get('type') or 0),int(msg.get('create_time') or 0))
            rows=list(self.index.execute('SELECT source FROM refs WHERE local=? AND kind IN (?,0) AND ctime=?',args))
            if not rows:
                # A reused local_id must never silently attach a different
                # message's media. Timestamp-less fallback is unambiguous only.
                alternatives=list(self.index.execute('SELECT ctime,source FROM refs WHERE local=? AND kind IN (?,0)',args[:2]))
                if len({t for t,_ in alternatives})==1:rows=[(s,) for _,s in alternatives]
        return source+'\n'+'\n'.join(s for s, in rows)

    def _candidates(self,msg):
        self._index();source=self._source(msg)
        hints=msg.get('_media') or {};values=list(hints.get('hashes') or [])
        values+=HASH.findall(source);values+=hints.get('paths') or []
        if msg.get('extra',{}).get('filename'):values.append(msg['extra']['filename'])
        values+=re.findall(r'[\w\-.\u4e00-\u9fff ()]+\.(?:mp4|mov|mkv|webm|jpg|jpeg|png|gif|webp|pic|dat|pdf|docx?|xlsx?|pptx?|zip|txt|silk|mp3)',source,re.I)
        found=[];kind=msg.get('kind')
        for value in dict.fromkeys(values):
            name=Path(str(value).replace(chr(92),'/')).name.casefold()
            tokens=[name,name+'_h',name+'_t'] if HASH.fullmatch(name) else [name]
            for token in tokens:
                matches=list(self.index.execute('SELECT path,scoped FROM files WHERE name=? OR stem=? ORDER BY scoped DESC,path',(token,token)))
                if len(matches)>1 and not HASH.fullmatch(name) and not any(s for _,s in matches):continue
                for path,_ in matches:
                    p=Path(path);ext=p.suffix.lower()
                    if kind in ('image','emoji') and ext not in ('','.dat','.pic','.thumb','.jpg','.jpeg','.png','.gif','.webp','.bmp','.wxgf'):continue
                    if kind=='video' and ext not in ('.mp4','.mov','.m4v','.avi','.mkv','.webm'):continue
                    expected=Path(msg.get('extra',{}).get('filename') or '').suffix.lower()
                    if kind=='file' and expected and ext!=expected and ext in ('.jpg','.jpeg','.png','.gif','.webp','.bmp'):continue
                    if p not in found:found.append(p)
        # Prefer the downloaded HD original, then the normal original, then a
        # thumbnail. Never let a successful thumbnail hide an available original.
        if kind in ('image','emoji'):
            def tier(path):
                stem=path.stem.lower()
                return 2 if thumbnail_candidate(path,hints) else 0 if stem.endswith(('_h','.h','_hd','.hd')) else 1
            found.sort(key=tier)
        return found

    def _copy(self,source,category,blob=None,extension=None,status='available',role='main',identity_source=None):
        self.cancel();identity=hashlib.sha256(str(identity_source or source).encode()).hexdigest()[:24]
        ext=extension or Path(source).suffix
        dest=self.out/'resources'/category/(identity+ext)
        dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():
            if blob is not None:dest.write_bytes(blob)
            else:
                with open(source,'rb') as src,open(dest,'wb') as out:
                    while True:
                        self.cancel();chunk=src.read(1024*1024)
                        if not chunk:break
                        out.write(chunk)
        self.stats[status]+=1
        name=Path(source).stem+ext if extension else Path(source).name
        return {'kind':category,'path':dest.relative_to(self.out).as_posix(),'name':name,'status':status,'role':role}

    def _download(self,url,limit):
        identity=hashlib.sha256(url.encode()).hexdigest()
        if not media_url(url):
            if len(self.download_outcomes)<2048:self.download_outcomes[identity]={'status':'host_not_supported'}
            return None
        if url in self.failed_downloads:return None
        cache=self.keys.path.parent/'downloads';path=cache/(identity+'.media')
        try:
            cache.mkdir(parents=True,exist_ok=True)
            if path.is_file() and 0<path.stat().st_size<=limit:
                if len(self.download_outcomes)<2048:self.download_outcomes[identity]={'status':'cached'}
                return path
        except OSError:
            if len(self.download_outcomes)<2048:self.download_outcomes[identity]={'status':'cache_unavailable'}
            return None
        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,req,fp,code,msg,headers,newurl):
                if not media_url(newurl):raise ValueError('Invalid media redirect')
                return super().redirect_request(req,fp,code,msg,headers,newurl)
        # A broken inherited proxy blocked both emoji downloads on this machine.
        # Retry the SAME allowlisted resource directly; never alter system proxy
        # settings or disable TLS verification. Remember a working transport.
        transports=(True,False) if self.prefer_direct else (False,True)
        errors=[]
        for direct in transports:
            self.cancel();temp=path.with_suffix('.part')
            try:
                handlers=[Redirect()]
                if direct:handlers.append(urllib.request.ProxyHandler({}))
                opener=urllib.request.build_opener(*handlers)
                req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'*/*'})
                deadline=time.monotonic()+25
                with opener.open(req,timeout=4) as response,open(temp,'wb') as stream:
                    length=0
                    while True:
                        self.cancel()
                        if time.monotonic()>deadline:raise TimeoutError()
                        chunk=response.read(65536)
                        if not chunk:break
                        length+=len(chunk)
                        if length>limit:raise ValueError('Media size limit')
                        stream.write(chunk)
                if not length:raise ValueError('Empty media response')
                os.replace(temp,path);self.prefer_direct=direct
                if len(self.download_outcomes)<2048:
                    self.download_outcomes[identity]={'status':'downloaded','transport':'direct' if direct else 'configured',
                        'recovered_after_retry':bool(errors)}
                return path
            except (OSError,ValueError,TimeoutError) as exc:
                temp.unlink(missing_ok=True)
                reason=getattr(exc,'reason',exc)
                category=('tls_error' if isinstance(reason,ssl.SSLCertVerificationError) else
                    'http_'+str(exc.code) if isinstance(exc,urllib.error.HTTPError) else
                    'timeout' if isinstance(reason,(TimeoutError,)) else 'connection_error')
                errors.append({'transport':'direct' if direct else 'configured','reason':category})
            finally:
                temp.unlink(missing_ok=True)
        if len(self.failed_downloads)<2048:self.failed_downloads.add(url)
        if len(self.download_outcomes)<2048:self.download_outcomes[identity]={'status':'download_failed','attempts':errors}
        return None

    def _emoticon_hints(self,msg):
        """Read same-account emoticon metadata when message URLs are absent/stale."""
        if msg.get('kind')!='emoji':return
        hints=msg['_media'];hashes=list(dict.fromkeys(hints.get('hashes') or []))[:12]
        if not hashes:return
        for rel,con in self.data._conns.items():
            if not con or not any(s in rel.lower() for s in ('emoticon','emoji')):continue
            for table in self.data.tables_of(con):
                q=quoted_identifier
                cols={r[1].lower().replace('_',''):r[1] for r in con.execute('PRAGMA table_info('+q(table)+')')}
                md5=cols.get('md5')
                if not md5 or not any(k in cols for k in ('cdnurl','encrypturl','externurl')):continue
                for value in hashes:
                    for row in con.execute('SELECT * FROM '+q(table)+' WHERE '+q(md5)+'=? LIMIT 4',(value,)):
                        for name in ('aeskey','encryptkey'):
                            if name in cols and isinstance(row[cols[name]],str) and row[cols[name]]:
                                key=row[cols[name]]
                                if key not in hints['keys']:hints['keys'].append(key)
                        for name in ('externmd5',):
                            digest=row[cols[name]] if name in cols else None
                            if isinstance(digest,str) and HASH.fullmatch(digest) and digest not in hints['hashes']:hints['hashes'].append(digest)
                        for name in ('cdnurl','encrypturl','externurl','thumburl','tpurl'):
                            url=row[cols[name]] if name in cols else None
                            if isinstance(url,str) and url.startswith(('http://','https://')) and not any(h['url']==url for h in hints['urls']):
                                hints['urls'].append({'url':url,'role':'thumbnail' if name=='thumburl' else 'main',
                                    'encrypted':name in ('encrypturl','externurl'),'field':'emoticon_db_'+name})

    def _network(self,msg,resources):
        kind=msg.get('kind');hints=msg.get('_media') or {}
        have_main=any(r['status']=='available' and r.get('role')=='main' for r in resources)
        seen=set();diagnostics=[]
        for hint in hints.get('urls') or []:
            role=hint.get('role','main')
            identity=(hint['url'],role,bool(hint.get('encrypted')))
            if identity in seen:continue
            seen.add(identity)
            if have_main and role=='main':continue
            if kind not in ('image','emoji','video','file','link','miniprogram','appmsg','location') or (kind in ('link','miniprogram','appmsg','location') and role not in ('thumbnail','source_icon')):continue
            if kind=='emoji':self.keys.progress('正在获取表情原文件…')
            source=self._download(hint['url'],128*1024*1024 if kind=='video' and role=='main' else 24*1024*1024)
            result=self.download_outcomes.get(hashlib.sha256(hint['url'].encode()).hexdigest(),{})
            entry={'field':hint.get('field','media'),'host':urlparse(hint['url']).hostname,**result}
            diagnostics.append(entry)
            if not source:continue
            try:raw=source.read_bytes()
            except OSError:
                entry['content']='cache_read_failed';continue
            variants=chain((raw,),encrypted_media_variants(raw,hints.get('keys') or [],self.cancel))
            accepted=False
            for blob in variants:
                if role in ('thumbnail','source_icon') or kind in ('image','emoji'):
                    image=self.codec.image(blob)
                    if image:
                        ext=image_type(image)[0]
                        resources.append(self._copy(source,'image',image,'.'+ext,role=role));accepted=True;break
                elif kind=='video' and media_type(blob) and media_type(blob)[1].startswith('video/'):
                    temp=Path(self.tmp.name)/'cdn-video.mp4';temp.write_bytes(blob)
                    video=self.codec.video(temp,Path(self.tmp.name)/'cdn-playback.mp4')
                    if video:resources.append(self._copy(video,'video',extension='.mp4',identity_source=source));accepted=True;break
                elif kind=='file' and not hint.get('encrypted'):
                    filename=Path(msg.get('extra',{}).get('filename') or 'attachment.bin').name
                    extension=Path(filename).suffix
                    if not re.fullmatch(r'\.[a-zA-Z0-9]{1,10}',extension):extension='.bin'
                    resource=self._copy(source,'file',blob,extension)
                    resource['name']=filename;resource['size']=len(blob);resources.append(resource);accepted=True;break
            entry['content']='accepted' if accepted else 'not_decoded'
            have_main=any(r['status']=='available' and r.get('role')=='main' for r in resources)
        return diagnostics

    def _lookup_reference(self,server):
        if not server or str(server)=='0':return None
        table=self.data.msg_table_for(self.session);q=quoted_identifier
        if not self.messages_indexed:
            self.messages_indexed=True
            for shard,con in enumerate(self.data.msg_dbs):
                if table not in self.data.tables_of(con):continue
                try:cursor=con.execute('SELECT rowid,server_id FROM '+q(table));mode='rowid'
                except sqlite3.OperationalError:cursor=con.execute('SELECT local_id,server_id FROM '+q(table));mode='local_id'
                for row in cursor:
                    self.cancel()
                    if row[1]:self.index.execute('INSERT INTO messages VALUES (?,?,?,?)',(str(row[1]),shard,row[0],mode))
            self.index.commit()
        found=self.index.execute('SELECT shard,row_key,mode FROM messages WHERE server=? LIMIT 1',(str(server),)).fetchone()
        if not found:return None
        shard,row_key,mode=found;con=self.data.msg_dbs[shard]
        from .data import FIELDS
        cols={r[1] for r in con.execute('PRAGMA table_info('+q(table)+')')}
        select=','.join(q(c) if c in cols else 'NULL AS '+q(c) for c in FIELDS)
        row=con.execute('SELECT '+select+' FROM '+q(table)+' WHERE '+q(mode)+'=? LIMIT 1',(row_key,)).fetchone()
        return self.data._build_msg(row,self.data._name2id(con),self.session,shard) if row else None

    def _quote(self,msg,depth):
        quote=msg.get('_quote')
        if not quote:return None
        reference=self._lookup_reference(quote.get('server_id'))
        if reference is None:
            try:timestamp=int(quote.get('create_time') or msg['create_time'])
            except (TypeError,ValueError):timestamp=msg['create_time']
            if timestamp<=0 or timestamp>253402300799:timestamp=msg['create_time']
            r={'local_id':0,'server_id':quote.get('server_id') or '','local_type':quote.get('type') or 1,
                'real_sender_id':1,'create_time':timestamp,
                'message_content':quote.get('content') or quote.get('text',''),'compress_content':None,'packed_info_data':None}
            reference=self.data._build_msg(r,{1:quote.get('sender_wxid','')},self.session,0)
            reference['sender']=quote.get('sender') or reference['sender']
        reference=self.enrich(reference,depth=depth+1)
        return {k:reference.get(k) for k in ('server_id','sender','sender_wxid','time_str','text','kind','extra','resources','resource_notice','forward')}

    def _forward_avatar(self,msg):
        url=msg.get('avatar_url') or ''
        if not url:return ''
        source=self._download(url,2*1024*1024)
        if not source:return ''
        try:image=self.codec.image(source.read_bytes())
        except (OSError,ValueError):return ''
        if not image:return ''
        path=self.out/'avatars'/(hashlib.sha256(url.encode()).hexdigest()[:24]+'.'+image_type(image)[0])
        path.parent.mkdir(exist_ok=True)
        if not path.exists():path.write_bytes(image)
        return path.relative_to(self.out).as_posix()

    def enrich(self,msg,depth=0):
        if depth==0:self.forward_remaining=5000
        msg=dict(msg);msg['extra']=dict(msg.get('extra') or {})
        msg['avatar']=self.avatars.export(msg.get('sender_wxid',''),self.out)
        if not msg['avatar'] and msg.get('_forward_item'):msg['avatar']=self._forward_avatar(msg)
        kind=msg.get('kind');resources=[];fallback=None;image_diagnostics={};fallback_diagnostics={}
        if kind=='emoji':
            original=msg.get('_media') or {}
            msg['_media']={name:list(original.get(name) or []) for name in ('keys','hashes','urls','paths','thumbnail_hashes','main_hashes')}
            self._emoticon_hints(msg)
        if kind=='voice':
            blob=self.data.voice_blob(self.session,msg.get('server_id'))
            if blob:resources.append(self._copy('voice_'+str(msg['server_id'])+'.silk','audio',blob,'.silk'))
        if kind in ('image','emoji','video','file'):
            candidates=self._candidates(msg)
            samples=[Path(p) for p, in self.index.execute("SELECT path FROM files WHERE name LIKE '%.dat' ORDER BY scoped DESC,name LIMIT 40")]
            for source in candidates:
                self.cancel()
                try:
                    if kind in ('image','emoji'):
                        if source.stat().st_size>128*1024*1024:continue
                        raw=source.read_bytes()
                        decoded=self.keys.decode(raw,source,samples,(msg.get('_media') or {}).get('keys') or [])
                        image=self.keys.rendered or (self.codec.image(decoded) if decoded else None)
                        if image:
                            thumb=thumbnail_candidate(source,msg.get('_media') or {})
                            resource=self._copy(source,'image',image,'.'+image_type(image)[0],role='thumbnail' if thumb else 'main')
                            resource['quality']='thumbnail' if thumb else 'original'
                            resources.append(resource)
                            if decoded and decoded.startswith(b'wxgf'):
                                original=self._copy(source,'original',decoded,'.wxgf',role='original')
                                original['name']='已解密的微信原图.wxgf';resources.append(original)
                            image_diagnostics=dict(self.keys.diagnostics);break
                        status='encrypted' if self.keys.reason in ('aes_key_unavailable','xor_unresolved','encrypted_media_unresolved') else 'unsupported' if decoded and decoded.startswith(b'wxgf') else 'corrupt'
                        if fallback is None:
                            fallback=(source,status);fallback_diagnostics={**self.keys.diagnostics,'reason':self.keys.reason}
                            image_diagnostics=fallback_diagnostics
                    elif kind=='video':
                        converted=self.codec.video(source,Path(self.tmp.name)/'playback.mp4')
                        if converted:
                            resources.append(self._copy(converted,'video',extension='.mp4',identity_source=source));break
                        if fallback is None:fallback=(source,'unsupported')
                    else:
                        resource=self._copy(source,'file');resource['size']=source.stat().st_size
                        resource['name']=msg.get('extra',{}).get('filename') or resource['name']
                        resources.append(resource);break
                except (OSError,ValueError):
                    if fallback is None:fallback=(source,'corrupt')
        network_diagnostics=self._network(msg,resources)
        main=any(r['status']=='available' and r['role']=='main' for r in resources)
        if kind in ('image','emoji','video','voice','file') and not main:
            status='missing'
            if fallback:
                source,status=fallback
                resources.append(self._copy(source,'original',status=status))
                if kind in ('image','emoji'):image_diagnostics=fallback_diagnostics
            else:self.stats['missing']+=1
            notices={'missing':'本机附件或有效 CDN 资源尚不可用，请在微信下载原文件后重新导出。',
                'encrypted':'未取得通过完整校验的图片解密材料，已保留加密原文件。请保持微信登录，在微信打开原图后重新导出。',
                'unsupported':'原文件已保存，但浏览器格式转换未成功。',
                'corrupt':'文件内容未能通过格式校验，已保留原文件。'}
            msg['resource_status']=status;msg['resource_notice']=notices[status]
            if status=='encrypted':
                reason=image_diagnostics.get('reason')
                if reason=='aes_key_unavailable':msg['resource_notice']='尚未找到通过完整 AES 校验的图片密钥，已保留加密原文件。保持微信登录并打开原图后重新导出；若微信以管理员运行，请以同等权限打开本软件。'
                elif reason=='xor_unresolved':msg['resource_notice']='AES 图片头已通过校验，但 XOR 尾段未能恢复为完整图像，已保留加密原文件。请在微信打开原图后重新导出。'
                elif reason=='encrypted_media_unresolved':msg['resource_notice']='表情缓存尚未还原为可用图像，CDN 备用资源也未取得。已保留缓存原文件；下载失败原因见资源明细。'
            if any(r['role']=='thumbnail' for r in resources):
                msg['resource_notice']=('已显示本机缩略图，原图尚未缓存或未能取得。' if status=='missing'
                    else '已提供缩略图；'+msg['resource_notice'])
        msg['resources']=resources
        if kind=='quote' and depth<6:msg['quote']=self._quote(msg,depth)
        if kind=='chatrecord' and depth<6:
            record=dict(msg.get('forward') or build_forward(self.data,msg))
            self._index_forward_media()
            children=record.get('messages',[])
            available=max(0,self.forward_remaining)
            if len(children)>available:
                children=children[:available];record.update(truncated=True,notice='转发与引用的展开消息数达到处理上限，已保留可读取内容。')
            self.forward_remaining-=len(children)
            record['messages']=[]
            for child in children:
                self.cancel();record['messages'].append(self.enrich(child,depth+1))
            record['count']=len(record['messages'])
            msg['forward']=record
        if resources or msg.get('resource_status') or network_diagnostics:
            self.report.write(json.dumps({'message_id':str(msg.get('server_id') or ''),'kind':kind,
                'status':msg.get('resource_status','available'),'notice':msg.get('resource_notice',''),
                'resources':resources,'image_diagnostics':image_diagnostics,
                'network_diagnostics':network_diagnostics},ensure_ascii=False)+'\n')
        return msg
