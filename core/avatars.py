"""Contact avatar lookup shared by the UI and portable exports."""
import base64
import hashlib
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def image_type(blob):
    for signature, ext, mime in ((b'\xff\xd8\xff','jpg','image/jpeg'),
            (b'\x89PNG\r\n\x1a\n','png','image/png'),(b'GIF8','gif','image/gif'),
            (b'RIFF','webp','image/webp'),(b'BM','bmp','image/bmp')):
        if blob.startswith(signature):
            if ext=='webp' and blob[8:12]!=b'WEBP':continue
            return ext,mime
    return None


def avatar_host(url):
    if not isinstance(url,str):return False
    try:
        p=urlparse(url);host=(p.hostname or '').lower()
        return p.scheme in ('http','https') and not p.username and p.port in (None,80,443) and any(
            host==d or host.endswith('.'+d) for d in ('qpic.cn','qlogo.cn','weixin.qq.com'))
    except ValueError:
        return False


class AvatarStore:
    def __init__(self, data, cache=None):
        self.data=data
        self.cache=Path(cache) if cache else None
        self.lookups={}

    def blob(self, username, download=False):
        key=(username,download)
        if key in self.lookups:return self.lookups[key]
        found=None
        # head_image.db contains local avatar blobs on installations where
        # network avatar URLs are absent or expired.
        for rel,con in self.data._conns.items():
            if not con or not any(t in rel.lower() for t in ('head','avatar')):continue
            for table in self.data.tables_of(con):
                quote=lambda v:'"'+v.replace('"','""')+'"'
                cols=[r[1] for r in con.execute('PRAGMA table_info('+quote(table)+')')]
                names={c.lower():c for c in cols}
                user=next((names[c] for c in ('username','user_name','usrname','wxid') if c in names),None)
                if not user:continue
                row=con.execute('SELECT * FROM '+quote(table)+' WHERE '+quote(user)+'=? LIMIT 1',(username,)).fetchone()
                if row:
                    for v in row:
                        if isinstance(v,bytes) and len(v)<=2*1024*1024 and image_type(v):found=v;break
                if found:break
            if found:break
        url=self.data.avatar_of(username)
        cached=self.cache/(hashlib.sha256(url.encode()).hexdigest()+'.img') if self.cache and url else None
        if not found and cached and cached.exists():
            try:
                if cached.stat().st_size<=2*1024*1024:
                    blob=cached.read_bytes()
                    if image_type(blob):found=blob
            except OSError:
                pass
        if not found and download and avatar_host(url):
            try:
                class Redirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, headers, newurl):
                        if not avatar_host(newurl):raise ValueError('Unsupported avatar redirect')
                        return super().redirect_request(req,fp,code,msg,headers,newurl)
                with urllib.request.build_opener(Redirect).open(url,timeout=3) as response:
                    blob=response.read(2*1024*1024+1)
                if len(blob)<=2*1024*1024 and image_type(blob):
                    found=blob
                    if cached:
                        cached.parent.mkdir(parents=True,exist_ok=True)
                        cached.write_bytes(blob)
            except (OSError,ValueError):pass
        if len(self.lookups)>=2048:self.lookups.clear()
        self.lookups[key]=found
        return found

    def ui(self, username):
        blob=self.blob(username)
        if blob:return 'data:'+image_type(blob)[1]+';base64,'+base64.b64encode(blob).decode()
        url=self.data.avatar_of(username)
        return url if avatar_host(url) else ''

    def export(self, username, folder):
        blob=self.blob(username,True)
        if not blob:return ''
        ext,_=image_type(blob)
        path=Path(folder)/'avatars'/(hashlib.sha256(username.encode()).hexdigest()[:24]+'.'+ext)
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_bytes(blob)
        return path.relative_to(folder).as_posix()
