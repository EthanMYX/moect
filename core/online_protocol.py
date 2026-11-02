"""Signed, bounded public channel data. No publisher credentials in the client."""
import base64
import hashlib
import json
import re
from datetime import datetime,timezone
from urllib.parse import urlsplit
from Cryptodome.PublicKey import ECC
from Cryptodome.Signature import eddsa

MAX_FEED=1024*1024


def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}',value):raise ValueError('版本信息格式无效')
    return tuple(map(int,value.split('.')))


def timestamp(value):
    try:
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
        if date.tzinfo is None:raise ValueError()
        return date.timestamp()
    except (ValueError,TypeError,AttributeError,OverflowError):raise ValueError('发布时间格式无效') from None


def web_url(value,hosts=None):
    if not isinstance(value,str) or not 1<=len(value)<=4096 or any(ord(c)<32 for c in value):raise ValueError('链接无效')
    try:
        parts=urlsplit(value)
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.port not in (None,443):raise ValueError()
        if hosts is not None and parts.hostname.lower() not in hosts:raise ValueError()
        return value
    except ValueError:raise ValueError('链接不在可信发布范围内') from None


def text(value,limit):
    if not isinstance(value,str) or len(value)>limit:raise ValueError('公告内容格式无效')
    return value


def digest(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('资源校验信息无效')
    return value


def verify_feed(envelope,public_key,hosts,now=None,minimum_sequence=0):
    now=datetime.now(timezone.utc).timestamp() if now is None else now
    try:
        if not isinstance(envelope,dict):raise ValueError()
        raw=base64.b64decode(envelope['payload'],validate=True)
        signature=base64.b64decode(envelope['signature'],validate=True)
        if len(raw)>MAX_FEED or len(signature)!=64:raise ValueError()
        key=ECC.import_key(public_key)
        if key.has_private() or key.curve!='Ed25519':raise ValueError()
        eddsa.new(key,'rfc8032').verify(raw,signature)
        data=json.loads(raw)
    except (KeyError,ValueError,TypeError,UnicodeError):raise ValueError('发布信息签名校验失败，已停止使用该内容') from None
    if not isinstance(data,dict) or data.get('schema')!=1 or data.get('channel')!='stable':raise ValueError('发布协议不受支持')
    sequence=data.get('sequence')
    if type(sequence) is not int or not minimum_sequence<=sequence<10**16:raise ValueError('收到过期的发布序列，已忽略')
    if timestamp(data.get('issued_at'))>now+600 or timestamp(data.get('expires_at'))<=now:raise ValueError('发布信息已过期或本机时间不准确')
    announcements=data.get('announcements')
    if not isinstance(announcements,list) or len(announcements)>50:raise ValueError('公告列表格式无效')
    ids=set()
    for item in announcements:
        if not isinstance(item,dict):raise ValueError('公告格式无效')
        uid=item.get('id')
        if not isinstance(uid,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}',uid) or uid in ids:raise ValueError('公告编号无效')
        ids.add(uid);text(item.get('title'),200);text(item.get('body'),64000);timestamp(item.get('published_at'))
        if item.get('expires_at'):timestamp(item['expires_at'])
        for field in ('min_version','max_version'):
            if item.get(field):version(item[field])
        assets=item.get('assets',{})
        if not isinstance(assets,dict) or len(assets)>40:raise ValueError('公告图片列表无效')
        for url,sha in assets.items():web_url(url,hosts);digest(sha)
    release=data.get('release')
    if release is not None:
        if not isinstance(release,dict):raise ValueError('更新信息无效')
        if 'id' in release and (not isinstance(release['id'],str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}',release['id'])):raise ValueError('更新编号无效')
        version(release.get('version'));text(release.get('notes',''),64000);timestamp(release.get('published_at'))
        if release.get('platform')!='windows-x64':raise ValueError('更新平台不受支持')
        if type(release.get('minimum_windows_build',17763)) is not int:raise ValueError('系统版本信息无效')
        packages=release.get('packages')
        if not isinstance(packages,dict) or not packages or any(k not in ('installer','portable') for k in packages):raise ValueError('更新资源无效')
        for package in packages.values():
            if not isinstance(package,dict):raise ValueError('更新资源无效')
            digest(package.get('sha256'))
            if type(package.get('size')) is not int or not 1<=package['size']<=2*1024**3:raise ValueError('更新文件大小无效')
            parts=package.get('parts')
            if parts is None:web_url(package.get('url'),hosts)
            else:
                if not isinstance(parts,list) or not 1<=len(parts)<=200:raise ValueError('更新分片信息无效')
                total=0
                for part in parts:
                    if not isinstance(part,dict):raise ValueError('更新分片信息无效')
                    web_url(part.get('url'),hosts);digest(part.get('sha256'))
                    if type(part.get('size')) is not int or not 1<=part['size']<=20*1024*1024:raise ValueError('更新分片大小无效')
                    total+=part['size']
                if total!=package['size']:raise ValueError('更新分片总大小不匹配')
    return data


def sign_feed(data,private_key):
    raw=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return {'payload':base64.b64encode(raw).decode(),'signature':base64.b64encode(eddsa.new(ECC.import_key(private_key),'rfc8032').sign(raw)).decode()}


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for blob in iter(lambda:stream.read(1024*1024),b''):h.update(blob)
    return h.hexdigest()
