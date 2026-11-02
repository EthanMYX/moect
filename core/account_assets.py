"""Read account-owned sticker catalogs and scoped, locally cached Moments.

Only documented table identities are accepted. No arbitrary table is treated
as a sticker collection or as a timeline. Author selections are parameterized
and XML authors must agree with database authors. Media credentials stay private.
"""
import hashlib
import re
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode

from wx4.reader import sqlite_text

HASH=re.compile(r'^[a-fA-F0-9]{32}$')


def text(value):
    if isinstance(value,bytes):
        try:return value.decode('utf-8')
        except UnicodeError:return ''
    return str(value) if value is not None else ''


def integer(value,default=0):
    try:return int(value)
    except (ValueError,TypeError,OverflowError):return default


def fields(row):return {str(k).lower().strip('_'):v for k,v in dict(row).items()}


def identity(value):return hashlib.sha256(text(value).encode('utf-8')).hexdigest()[:20]


def open_asset_db(library,relative):
    root=Path(library.get('assets_root') or library['root'])
    target=root/relative
    if not target.is_file():target=Path(library['root'])/relative
    if not target.is_file():return None
    try:
        con=sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)
        con.row_factory=sqlite3.Row;con.text_factory=sqlite_text
        con.execute('PRAGMA query_only=ON')
        return con
    except sqlite3.Error:raise ValueError('资源数据库无法读取，请重新连接并整理微信。') from None


def tables(con):return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def table_rows(con,name,available,limit=100000):
    if name not in available:return []
    # Table names here are fixed source-code constants, never bridge inputs.
    return [fields(row) for row in con.execute('SELECT * FROM "'+name+'" LIMIT ?', (limit,))]


class StickerCatalog:
    def __init__(self,library,cancel=lambda:None):
        self.groups=[];self.available=False
        con=open_asset_db(library,'emoticon/emoticon.db')
        if con is None:return
        try:
            known=tables(con)
            if 'kNonStoreEmoticonTable' not in known and 'kStoreEmoticonFilesTable' not in known:return
            self.available=True
            metadata={text(r.get('md5')).lower():r for r in table_rows(con,'kNonStoreEmoticonTable',known)}
            for table,name,key in [('kFavEmoticonOrderTable','收藏的表情','favorites'),('kCustomEmoticonOrderTable','自定义表情','custom')]:
                members=[];seen=set()
                for order,row in enumerate(table_rows(con,table,known)):
                    cancel();digest=text(row.get('md5')).lower()
                    if not HASH.fullmatch(digest) or digest in seen:continue
                    seen.add(digest);info=dict(metadata.get(digest,{}))
                    members.append(dict(md5=digest,caption=text(info.get('caption')),order=order,metadata=info))
                if members:self.groups.append(dict(id=key,name=name,members=members))
            captions={}
            for row in table_rows(con,'kStoreEmoticonCaptionsTable',known):
                key=(text(row.get('package_id')),text(row.get('md5')).lower())
                caption=text(row.get('caption'));language=text(row.get('language')).lower().replace('-','_')
                if caption and (key not in captions or language in ('zh_cn','zh_hans','zh')):captions[key]=caption
            packages={}
            for row in table_rows(con,'kStoreEmoticonPackageTable',known):
                cancel();pid=text(row.get('package_id'))
                if not pid or integer(row.get('remove_time'))>0:continue
                packages[pid]=dict(id='pack_'+identity(pid),name=text(row.get('package_name')) or '未命名表情专辑',package_id=pid,
                                   order=integer(row.get('sort_order')),members=[])
            for row in table_rows(con,'kStoreEmoticonFilesTable',known):
                cancel();pid=text(row.get('package_id'));digest=text(row.get('md5')).lower()
                if pid not in packages or not HASH.fullmatch(digest):continue
                packages[pid]['members'].append(dict(md5=digest,caption=captions.get((pid,digest),''),order=integer(row.get('sort_order')),
                    package_id=pid,offset=integer(row.get('emoticon_offset'),-1),size=integer(row.get('emoticon_size')),
                    thumb_offset=integer(row.get('thumb_offset'),-1),thumb_size=integer(row.get('thumb_size')),metadata=dict(metadata.get(digest,{}))))
            for group in sorted(packages.values(),key=lambda row:(row['order'],row['id'])):
                group['members'].sort(key=lambda row:(row['order'],row['md5']))
                self.groups.append(group)
        except sqlite3.Error:raise ValueError('表情数据库结构与当前适配不一致，请重新整理微信后重试。') from None
        finally:con.close()

    def summary(self):
        return {'available':self.available,'total':sum(len(g['members']) for g in self.groups),
                'groups':[{'id':g['id'],'name':g['name'],'count':len(g['members'])} for g in self.groups],
                'notice':'按微信本地收藏顺序和已安装的表情专辑分类。未缓存或缺少解密材料的表情会单独记录，缩略图不会冒充原图。'}


def tag(node,name):
    if node is None:return None
    return next((child for child in node if child.tag.rsplit('}',1)[-1].lower()==name.lower()),None)


def tag_text(node,name):
    child=tag(node,name)
    return child.text.strip() if child is not None and child.text else ''


def sns_url(value,node):
    try:
        parts=urlsplit(value)
        if parts.scheme not in ('http','https'):return value
        token=node.get('token','') if node is not None else ''
        query=parse_qsl(parts.query,keep_blank_values=True)
        if token:
            query=[(k,v) for k,v in query if k not in ('token','idx')]+[('token',token),('idx','1')]
        return urlunsplit(('https',parts.netloc,parts.path,urlencode(query) if token else parts.query,parts.fragment))
    except ValueError:return value


def decode_xml(value):
    if isinstance(value,bytes):
        if value.startswith(b'\x28\xb5\x2f\xfd'):
            import zstandard
            import io
            try:
                with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(value)) as reader:value=reader.read(8*1024*1024+1)
            except zstandard.ZstdError:return None
            if len(value)>8*1024*1024:return None
        try:value=value.decode('utf-8')
        except UnicodeError:return None
    if not isinstance(value,str) or len(value)>8*1024*1024:return None
    try:return ET.fromstring(value)
    except (ET.ParseError,ValueError):return None


def moment_selection(payload,owner,contacts=None,allow_empty=False):
    scope=payload.get('scope','self')
    if not isinstance(scope,str) or scope not in ('self','timeline','account'):raise ValueError('朋友圈导出范围无效')
    if scope=='self':
        if not owner:raise ValueError('无法确定当前账号 UID，请重新连接微信。')
        return {'scope':scope,'author_id':owner,'label':'我的朋友圈'}
    if scope=='timeline':return {'scope':scope,'author_id':'','label':'公共朋友圈'}
    value=payload.get('authorId','')
    if not isinstance(value,str) or len(value)>256 or '\0' in value:raise ValueError('请输入有效的微信账号 UID、微信号或昵称。')
    value=value.strip()
    if not value:
        if allow_empty:return {'scope':scope,'author_id':'','label':'指定账号的朋友圈'}
        raise ValueError('请先选择或填写要导出朋友圈的微信账号。')
    contacts=contacts or {}
    exact=contacts.get(value)
    if exact and exact.get('username')==value:
        uid=value
    else:
        aliases=set();names=set()
        for key,contact in contacts.items():
            uid=text(contact.get('username'))
            if not uid or key!=uid:continue
            if text(contact.get('alias'))==value:aliases.add(uid)
            if value in (text(contact.get('nick_name')),text(contact.get('remark'))):names.add(uid)
        matches=aliases or names
        if len(matches)>1:raise ValueError('有多个账号使用这个昵称，请从列表选择具体 UID。')
        uid=next(iter(matches)) if matches else value
    contact=contacts.get(uid) or {}
    name=text(contact.get('remark')) or text(contact.get('nick_name')) or uid
    return {'scope':scope,'author_id':uid,'label':name+'的朋友圈'}


def moment_interactions(*roots):
    """Read explicit social lists, never infer comment/like types from integers."""
    result={'likes':[],'comments':[]};seen={'likes':set(),'comments':set()}
    normalize=lambda name:re.sub(r'[^a-z0-9]','',name.rsplit('}',1)[-1].lower())
    def value(node,*names):
        wanted={normalize(n) for n in names}
        for child in node:
            if normalize(child.tag) in wanted and child.text:return child.text.strip()
        return ''
    for root in roots:
        if root is None:continue
        for container in root.iter():
            name=normalize(container.tag)
            kind='likes' if name in ('likeuserlist','likelist') else 'comments' if name in ('commentuserlist','commentlist') else None
            if not kind:continue
            for row in container:
                uid=value(row,'username','user_name','fromUsername');nickname=value(row,'nickname','nick_name','fromNickname')
                content=value(row,'content','commentContent')
                if not uid and not nickname:continue
                if value(row,'deleteFlag','delStatus','isDeleted','b_deleted') in ('1','true'):continue
                item={'uid':uid,'name':nickname or uid,'create_time':integer(value(row,'createTime','create_time'))}
                if kind=='comments':
                    ident=next((v for v in (value(row,'comment64Id'),value(row,'commentId','cmtid','id')) if v and v!='0'),'')
                    reference=next((v for v in (value(row,'refComment64Id'),value(row,'refCommentId','replyCommentId')) if v and v!='0'),'')
                    item.update(id=ident,text=content,
                        reply_uid=value(row,'refUsername','replyUsername','toUsername'),
                        reply_name=value(row,'refNickname','replyNickname','toNickname'),
                        reply_id=reference)
                    attachments=[]
                    for media in row.iter():
                        media_tag=normalize(media.tag)
                        if media_tag not in ('emojiinfo','imageinfo'):continue
                        keys=[v for v in (value(media,'aes_key'),value(media,'key')) if v]
                        urls=[];hashes=[]
                        for field in ('extern_url','url','encrypt_url','thumb_url'):
                            url=value(media,field)
                            if not url:continue
                            role='thumbnail' if field=='thumb_url' else 'main'
                            token=value(media,'thumb_url_token' if role=='thumbnail' else 'token')
                            url=sns_url(url,ET.Element('url',{'token':token}))
                            urls.append({'url':url,'role':role});hashes.append(hashlib.md5(url.encode()).hexdigest())
                        hashes.extend(v.lower() for v in (value(media,'md5'),value(media,'extern_md5')) if HASH.fullmatch(v))
                        attachments.append({'kind':'image','_media':{'urls':urls,'hashes':hashes,'keys':keys,
                            'stream_keys':[v for v in keys if re.fullmatch(r'[0-9]{1,20}',v)],'animated':media_tag=='emojiinfo'}})
                    if attachments:item['_attachments']=attachments[:20]
                key=(uid or nickname,) if kind=='likes' else ('id',item['id']) if item['id'] else (uid,nickname,content,item['create_time'],item['reply_uid'])
                if key in seen[kind]:continue
                seen[kind].add(key);result[kind].append(item)
    by_id={c['id']:c for c in result['comments'] if c['id']}
    for comment in result['comments']:
        target=by_id.get(comment['reply_id'])
        if target:
            comment['reply_uid']=comment['reply_uid'] or target['uid']
            comment['reply_name']=comment['reply_name'] or target['name']
    return result


def moment_from_row(row,owner=None):
    # Database and XML author must agree for every scope. A shared article's
    # source author does not replace the author of the Moment itself.
    author_id=text(row['user_name'])
    if not author_id or owner is not None and author_id!=owner:return None
    root=decode_xml(row['content'])
    if root is not None:
        timeline=next((n for n in root.iter() if n.tag.rsplit('}',1)[-1].lower()=='timelineobject'),None)
    else:timeline=None
    result={'id':str(integer(row['tid'])%(1<<64)),'author':author_id,'text':'','create_time':0,'media':[],'status':'unsupported'}
    if timeline is None:return result
    author=tag_text(timeline,'username')
    if author and author!=author_id:return None
    result.update(id=tag_text(timeline,'id') or result['id'],text=tag_text(timeline,'contentDesc'),
                  create_time=integer(tag_text(timeline,'createTime')),status='available')
    extra=decode_xml(row['pack_info_buf']) if 'pack_info_buf' in row.keys() else None
    result.update(moment_interactions(root,extra))
    content=tag(timeline,'ContentObject')
    result.update(title=tag_text(content,'title'),description=tag_text(content,'description'),url=tag_text(content,'contentUrl'),
                  type=integer(tag_text(content,'type') or tag_text(content,'contentStyle')))
    location=tag(timeline,'location')
    if location is not None:result['location']=location.get('poiName') or location.get('poiAddress') or location.get('city') or ''
    media_list=tag(content,'mediaList')
    for media in list(media_list)[:100] if media_list is not None else []:
        if media.tag.rsplit('}',1)[-1].lower()!='media':continue
        url_node=tag(media,'url');thumb_node=tag(media,'thumb')
        url=tag_text(media,'url');thumb=tag_text(media,'thumb');media_id=tag_text(media,'id')
        hashes=[];keys=[];stream_keys=[];main_hashes=[];thumbnail_hashes=[]
        for node in (url_node,thumb_node,tag(media,'enc')):
            if node is None:continue
            for name,value in node.attrib.items():
                if 'md5' in name.lower() and HASH.fullmatch(value):
                    hashes.append(value.lower());(thumbnail_hashes if node is thumb_node else main_hashes).append(value.lower())
                if name.lower() in ('key','aeskey','aes_key') and value:keys.append(value)
                if name.lower()=='key' and re.fullmatch(r'[0-9]{1,20}',value):stream_keys.append(value)
        for node in timeline.iter():
            if node.tag.rsplit('}',1)[-1].lower()=='enc':
                value=node.get('key','')
                if re.fullmatch(r'[0-9]{1,20}',value):stream_keys.append(value)
        for value in (media_id,):
            if HASH.fullmatch(value):hashes.append(value.lower());main_hashes.append(value.lower())
        for value,group in ((url,main_hashes),(thumb,thumbnail_hashes)):
            if value:
                digest=hashlib.md5(value.encode()).hexdigest();hashes.append(digest);group.append(digest)
        kind='video' if integer(tag_text(media,'type')) in (6,15) or result['type'] in (4,15) else 'image'
        # Desktop SNS cache identities describe the post/media pair, not the
        # downloaded content or URL. Keep decimal u64 IDs as strings throughout.
        if re.fullmatch(r'[0-9]{1,20}',result['id']) and re.fullmatch(r'[0-9]{1,20}',media_id):
            for cache_type in ((3,) if kind=='video' else (result['type'],integer(tag_text(media,'type')),1,2,6)):
                if cache_type not in (1,2,3,6):continue
                digest=hashlib.md5(f"{result['id']}_{media_id}_{cache_type}".encode()).hexdigest()
                hashes.append(digest)
                (thumbnail_hashes if kind=='image' and cache_type==1 else main_hashes).append(digest)
        normalized_url=sns_url(url,url_node);normalized_thumb=sns_url(thumb,thumb_node)
        for value,group in ((normalized_url,main_hashes),(normalized_thumb,thumbnail_hashes)):
            if value:
                digest=hashlib.md5(value.encode()).hexdigest();hashes.append(digest);group.append(digest)
        result['media'].append({'id':media_id,'kind':kind,'_media':{'urls':[{'url':v,'role':role,'encrypted':bool(stream_keys)} for v,role in ((normalized_url,'main'),(normalized_thumb,'thumbnail')) if v],
                                 'hashes':list(dict.fromkeys(hashes)),'main_hashes':main_hashes,'thumbnail_hashes':thumbnail_hashes,'keys':keys,'stream_keys':list(dict.fromkeys(stream_keys)),'paths':[]}})
    return result


class MomentsCatalog:
    def __init__(self,library,owner,scope='self',author_id=''):
        if scope not in ('self','timeline','account'):raise ValueError('朋友圈导出范围无效')
        self.library=library;self.owner=owner;self.scope=scope;self.author_id=author_id
        self.available=False;self.unparsed=0

    def posts(self,cancel=lambda:None):
        con=open_asset_db(self.library,'sns/sns.db')
        if con is None:return
        try:
            if 'SnsTimeLine' not in tables(con):return
            columns={r[1] for r in con.execute('PRAGMA table_info(SnsTimeLine)')}
            if not {'tid','user_name','content'}<=columns:raise ValueError('朋友圈数据库结构暂不受支持。')
            if self.scope=='self' and not self.owner:raise ValueError('无法确定当前账号 UID，已停止朋友圈导出。请重新连接微信。')
            self.available=True
            if self.scope=='account' and not self.author_id:return
            target=self.owner if self.scope=='self' else self.author_id if self.scope=='account' else None
            query='SELECT tid,user_name,content'+(',pack_info_buf' if 'pack_info_buf' in columns else '')+' FROM SnsTimeLine'
            if target is not None:query+=' WHERE user_name=?'
            for row in con.execute(query+' ORDER BY tid DESC',(target,) if target is not None else ()):
                cancel();post=moment_from_row(row,target)
                if post:
                    if post['status']!='available':self.unparsed+=1
                    yield post
        except sqlite3.Error:raise ValueError('朋友圈数据库无法读取，请重新整理微信后重试。') from None
        finally:con.close()

    def authors(self,name_of=lambda uid:uid):
        con=open_asset_db(self.library,'sns/sns.db')
        if con is None:return []
        try:
            if 'SnsTimeLine' not in tables(con):return []
            values=[text(row[0]) for row in con.execute("SELECT DISTINCT user_name FROM SnsTimeLine WHERE user_name IS NOT NULL AND user_name<>''")]
            return sorted([{'uid':uid,'name':name_of(uid) or uid} for uid in values],key=lambda row:(row['uid']!=self.owner,row['name'].casefold(),row['uid']))
        except sqlite3.Error:raise ValueError('朋友圈账号列表无法读取，请刷新资源快照。') from None
        finally:con.close()

    def summary(self,start=None,end=None,name_of=lambda uid:uid):
        previews=[];count=0;unparsed=0
        for post in self.posts():
            if start is not None and post['create_time']<start or end is not None and post['create_time']>end:continue
            count+=1
            if post['status']!='available':unparsed+=1
            if len(previews)<12:previews.append({**{k:post.get(k) for k in ('id','author','text','title','create_time','status')},'author_name':name_of(post['author']) or post['author']})
        return {'available':self.available,'count':count,'unparsed':unparsed,'posts':previews,'scope':self.scope,
                'authors':self.authors(name_of),
                'notice':'读取本地已缓存的朋友圈。手动在微信浏览新内容后，点击刷新资源快照即可更新。'}
