"""Author-only signed static publishing. Private key/state live outside the repository."""
import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import unquote,urlsplit
from contextlib import contextmanager

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from Cryptodome.PublicKey import ECC
from core.online_protocol import file_hash,sign_feed,verify_feed,version
from core.publisher_paths import author_root,prepare_author_root

SOURCE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
ROOT=author_root()
IMAGE=re.compile(r'!\[([^\]]*)\]\(([^\n)]+)\)')


def initialize(domain='motanseat.asia'):
    if not re.fullmatch(r'[a-z0-9.-]+',domain) or '.' not in domain:raise ValueError('域名格式无效')
    prepare_author_root(ROOT,SOURCE/'ui/online-config.json')
    ROOT.mkdir(parents=True,exist_ok=True);key_path=ROOT/'signing-key.pem'
    destination=SOURCE/'ui/online-config.json'
    if not key_path.exists() and (destination.exists() or getattr(sys,'frozen',False)):
        raise ValueError('未找到原发布签名私钥。请恢复本机作者资料，不能生成新密钥替代原密钥。')
    if not key_path.exists():
        with key_path.open('x',encoding='ascii') as stream:stream.write(ECC.generate(curve='Ed25519').export_key(format='PEM'))
        try:key_path.chmod(0o600)
        except OSError:pass
    key=ECC.import_key(key_path.read_text());public=key.public_key().export_key(format='PEM')
    endpoint='https://updates.'+domain+'/channel/stable.json'
    config={'endpoint':endpoint,'public_key':public,'hosts':['updates.'+domain]}
    if destination.exists():
        previous=json.loads(destination.read_text(encoding='utf-8'))
        if previous.get('public_key') and previous['public_key']!=public:raise ValueError('当前签名密钥与客户端公钥不一致，已停止，不能静默更换。')
    if not getattr(sys,'frozen',False):
        destination.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    if not (ROOT/'draft.json').exists():(ROOT/'draft.json').write_text(json.dumps({'schema':1,'channel':'stable','sequence':0,'announcements':[],'release':None}),encoding='utf-8')
    return config


def load_draft():
    prepare_author_root(ROOT,SOURCE/'ui/online-config.json')
    return json.loads((ROOT/'draft.json').read_text(encoding='utf-8'))


def utc():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def prepare_announcement(draft,title,body_file,uid=None,days=90):
    uid=uid or datetime.now().strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:10]
    if not re.fullmatch('[a-zA-Z0-9_-]{1,80}',uid):raise ValueError('公告编号无效')
    if any(i['id']==uid for i in draft['announcements']):raise ValueError('公告编号已存在，请使用新编号')
    config=json.loads((SOURCE/'ui/online-config.json').read_text());base=config['endpoint'].rsplit('/channel/',1)[0]
    assets={};uploads=[];body_file=Path(body_file).resolve();body=body_file.read_text(encoding='utf-8')
    def image(match):
        source=unquote(match.group(2).strip().strip('<>'))
        if source.startswith(('http:','https:','data:')):raise ValueError('请插入本机图片，发布器会自动上传并转换链接。')
        path=(body_file.parent/source).resolve()
        if not path.is_file() or path.stat().st_size>5*1024*1024:raise ValueError('公告图片不存在或大于 5 MB')
        from PIL import Image
        with Image.open(path) as img:
            if img.format not in ('PNG','JPEG','WEBP','GIF') or img.width*img.height>24_000_000:raise ValueError('公告图片格式或尺寸不受支持')
            extension={'PNG':'png','JPEG':'jpg','WEBP':'webp','GIF':'gif'}[img.format];img.verify()
        sha=file_hash(path);key=f'announcements/{uid}/{sha}.{extension}';url=base+'/'+key;assets[url]=sha;uploads.append((path,key))
        return '!['+match.group(1)+']('+url+')'
    body=IMAGE.sub(image,body)
    notice={'id':uid,'title':title,'body':body,'assets':assets,'published_at':utc()}
    if days:notice['expires_at']=(datetime.now(timezone.utc)+timedelta(days=days)).isoformat(timespec='seconds')
    result=copy.deepcopy(draft);result['announcements'].append(notice)
    if len(result['announcements'])>50:raise ValueError('请先撤下过期公告，最多保留 50 条')
    return result,uploads


def prepare_release(draft,release_version,installer=None,portable=None,notes=''):
    if IMAGE.search(notes):raise ValueError('更新说明请使用文字与链接；需要配图时可另发公告。')
    version(release_version);config=json.loads((SOURCE/'ui/online-config.json').read_text());base=config['endpoint'].rsplit('/channel/',1)[0]
    if draft.get('release') and version(release_version)<=version(draft['release']['version']):raise ValueError('发布版本必须高于已发布版本')
    packages={};uploads=[]
    for mode,path in (('installer',installer),('portable',portable)):
        if not path:continue
        path=Path(path).resolve();extension='.exe' if mode=='installer' else '.zip'
        if path.suffix.lower()!=extension or not path.is_file():raise ValueError('请选择对应格式的真实软件包')
        if not 0<path.stat().st_size<=2*1024*1024*1024:raise ValueError('软件包为空或超过当前2 GiB上限。')
        if mode=='portable':
            with zipfile.ZipFile(path) as archive:
                manifests=[n for n in archive.namelist() if n in ('program-files.json','Moect/program-files.json')]
                if len(manifests)!=1 or json.loads(archive.read(manifests[0])).get('version')!=release_version:raise ValueError('便携包的真实版本与填写的版本不一致，或缺少程序清单。')
                prefix=manifests[0][:-len('program-files.json')]
                if prefix+'MoectUpdater.exe' not in archive.namelist():raise ValueError('便携包缺少更新组件')
                embedded=json.loads(archive.read(prefix+'_internal/ui/online-config.json'))
                if embedded.get('public_key')!=config['public_key']:raise ValueError('便携包的更新公钥与当前发布密钥不一致')
        elif os.name=='nt':
            import ctypes
            from ctypes import wintypes as wt
            api=ctypes.WinDLL('version',use_last_error=True)
            api.GetFileVersionInfoSizeW.argtypes=[wt.LPCWSTR,ctypes.POINTER(wt.DWORD)];api.GetFileVersionInfoSizeW.restype=wt.DWORD
            api.GetFileVersionInfoW.argtypes=[wt.LPCWSTR,wt.DWORD,wt.DWORD,ctypes.c_void_p];api.GetFileVersionInfoW.restype=wt.BOOL
            api.VerQueryValueW.argtypes=[ctypes.c_void_p,wt.LPCWSTR,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wt.UINT)];api.VerQueryValueW.restype=wt.BOOL
            size=api.GetFileVersionInfoSizeW(str(path),None)
            if not size:raise ValueError('安装包没有 Windows 版本信息')
            buffer=ctypes.create_string_buffer(size);pointer=ctypes.c_void_p();length=wt.UINT()
            if not api.GetFileVersionInfoW(str(path),0,size,buffer) or not api.VerQueryValueW(buffer,'\\',ctypes.byref(pointer),ctypes.byref(length)):raise ValueError('无法读取安装包版本')
            numbers=(wt.DWORD*13).from_address(pointer.value);ms,ls=numbers[2],numbers[3]
            if (ms>>16,ms&0xffff,ls>>16)!=version(release_version):raise ValueError('安装包的真实版本与填写版本不一致')
        sha=file_hash(path);key=f'packages/{release_version}/Moect-{release_version}-{mode}-{sha[:12]}{extension}'
        package={'size':path.stat().st_size,'sha256':sha}
        if path.stat().st_size>20*1024*1024:
            import hashlib
            folder=ROOT/'package-parts';folder.mkdir(exist_ok=True);parts=[]
            with path.open('rb') as stream:
                index=0
                while True:
                    blob=stream.read(20*1024*1024)
                    if not blob:break
                    index+=1;piece_hash=hashlib.sha256(blob).hexdigest();piece=folder/(piece_hash+'.part');piece.write_bytes(blob);piece_key=key+f'.{index:03d}.part'
                    parts.append({'url':base+'/'+piece_key,'size':len(blob),'sha256':piece_hash});uploads.append((piece,piece_key))
            package['parts']=parts
        else:package['url']=base+'/'+key;uploads.append((path,key))
        packages[mode]=package
    if not packages:raise ValueError('至少选择一个软件包')
    result=copy.deepcopy(draft);result['release']={'id':'release-'+uuid.uuid4().hex,'version':release_version,'platform':'windows-x64','minimum_windows_build':17763,'published_at':utc(),'notes':notes,'packages':packages}
    return result,uploads


@contextmanager
def publish_lock():
    ROOT.mkdir(parents=True,exist_ok=True)
    with (ROOT/'.publish.lock').open('a+b') as stream:
        stream.seek(0,2)
        if not stream.tell():stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise ValueError('另一个发布任务正在运行，请等待完成后重试。') from None
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)


def publish(draft,uploads=(),dry_run=False,progress=None):
    with publish_lock():return _publish(draft,uploads,dry_run,progress)


def _publish(draft,uploads=(),dry_run=False,progress=None):
    config=json.loads((SOURCE/'ui/online-config.json').read_text());feed=copy.deepcopy(draft)
    previous=load_draft()
    if draft.get('sequence')!=previous.get('sequence'):raise ValueError('发布记录已发生变化，请刷新后重新操作。')
    feed.update(sequence=max(int(time.time()*1000),previous['sequence']+1),issued_at=utc(),expires_at=(datetime.now(timezone.utc)+timedelta(days=365)).isoformat(timespec='seconds'))
    envelope=sign_feed(feed,(ROOT/'signing-key.pem').read_text())
    verify_feed(envelope,config['public_key'],set(config['hosts']))
    stage=ROOT/'staged';stage.mkdir(exist_ok=True);signed=stage/'stable.json';signed.write_text(json.dumps(envelope),encoding='utf-8')
    if dry_run:return {'prepared':True,'uploads':len(uploads),'sequence':feed['sequence']}
    cloud=json.loads((ROOT/'cloudflare.json').read_text())
    if not cloud.get('account_id'):raise ValueError('尚未确定 Cloudflare 发布账户，请先完成域名接入配置。')
    backend=cloud.get('control_backend','workers')
    if backend not in ('r2','workers','pages'):raise ValueError('未识别的发布通道配置。')
    if backend=='r2':
        from core.publisher_cloud import CloudflareR2
        client=CloudflareR2(cloud);client.info()
        expected={}
        base=config['endpoint'].rsplit('/channel/',1)[0]+'/'
        for notice in feed['announcements']:
            expected.update({url[len(base):]:sha for url,sha in notice.get('assets',{}).items() if url.startswith(base)})
        for package in (feed.get('release') or {}).get('packages',{}).values():
            for part in package.get('parts') or [package]:
                if part['url'].startswith(base):expected[part['url'][len(base):]]=part['sha256']
        ordered=dict((key,Path(path)) for path,key in uploads)
        total=sum(path.stat().st_size for path in ordered.values())+signed.stat().st_size
        complete=0
        for key,path in ordered.items():
            sha=expected.get(key)
            if not sha or file_hash(path)!=sha:raise ValueError('发布资源与签名清单不一致，未提交发布。')
            def report(sent,size):
                if progress:progress('正在上传资源',complete+sent,total)
            client.put(path,key,progress=report,expected=sha);complete+=path.stat().st_size
        if progress:progress('正在发布签名清单',complete,total)
        client.put(signed,'channel/stable.json',True,expected=file_hash(signed))
        temporary=ROOT/'draft.tmp';temporary.write_text(json.dumps(feed,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,ROOT/'draft.json')
        if progress:progress('发布完成',total,total)
        return {'published':True,'sequence':feed['sequence'],'announcements':len(feed['announcements']),'version':(feed.get('release') or {}).get('version','')}
    env=os.environ.copy();env['CLOUDFLARE_ACCOUNT_ID']=cloud['account_id']
    executable=shutil.which('npx.cmd' if os.name=='nt' else 'npx')
    if not executable:raise ValueError('未找到 Node.js / npx')
    if backend in ('workers','pages'):
        public=ROOT/'worker-public';public.mkdir(exist_ok=True)
        for source,name in uploads:
            destination=public/name
            if not destination.resolve().is_relative_to(public.resolve()):raise ValueError('发布文件路径无效')
            if source.stat().st_size>20*1024*1024:raise ValueError('静态资源超过分片上限')
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
        channel=public/'channel';channel.mkdir(exist_ok=True);shutil.copy2(signed,channel/'stable.json')
        (public/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Moect</title><p>Moect 公告与更新服务</p><a href="https://github.com/mofan6/Moect">项目主页</a>',encoding='utf-8')
        (public/'_headers').write_text('/channel/stable.json\n  Cache-Control: no-store, max-age=0\n/*\n  X-Content-Type-Options: nosniff\n',encoding='utf-8')
        host=urlsplit(config['endpoint']).hostname
        wrangler=ROOT/'wrangler.json'
        if cloud.get('control_backend')=='pages':
            project=cloud.get('pages_project','moect-motanseat')
            wrangler.write_text(json.dumps({'name':project,'compatibility_date':'2026-11-01','pages_build_output_dir':str(public)}),encoding='utf-8')
            command=[executable,'--yes','wrangler@4.156.0','pages','deploy',str(public),'--project-name',project,'--branch','main','--commit-dirty=true']
        else:
            wrangler.write_text(json.dumps({'name':cloud.get('worker_name','moect-channel'),'account_id':cloud['account_id'],'compatibility_date':'2026-11-01','assets':{'directory':str(public)},'routes':[{'pattern':host,'custom_domain':True}]}),encoding='utf-8')
            command=[executable,'--yes','wrangler@4.156.0','deploy','--config',str(wrangler)]
        result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=0x08000000 if os.name=='nt' else 0)
        (ROOT/'last-deploy.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        if result.returncode:raise ValueError('静态发布失败，请检查本机作者目录的 last-deploy.log。')
    temporary=ROOT/'draft.tmp';temporary.write_text(json.dumps(feed,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,ROOT/'draft.json')
    return {'published':True,'sequence':feed['sequence'],'announcements':len(feed['announcements']),'version':(feed.get('release') or {}).get('version','')}


def main():
    parser=argparse.ArgumentParser();commands=parser.add_subparsers(dest='action',required=True)
    init=commands.add_parser('init');init.add_argument('--domain',default='motanseat.asia')
    announce=commands.add_parser('announce');announce.add_argument('--title',required=True);announce.add_argument('--file',required=True);announce.add_argument('--id');announce.add_argument('--days',type=int,default=90);announce.add_argument('--dry-run',action='store_true')
    remove=commands.add_parser('withdraw');remove.add_argument('--id',required=True);remove.add_argument('--dry-run',action='store_true')
    release=commands.add_parser('release');release.add_argument('--version',required=True);release.add_argument('--installer');release.add_argument('--portable');release.add_argument('--notes');release.add_argument('--dry-run',action='store_true')
    empty=commands.add_parser('publish');empty.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if args.action=='init':initialize(args.domain);print('发布公钥已配置，私钥保存在本机作者目录。');return
    draft=load_draft();uploads=[]
    if args.action=='announce':draft,uploads=prepare_announcement(draft,args.title,args.file,args.id,args.days)
    elif args.action=='withdraw':draft['announcements']=[i for i in draft['announcements'] if i['id']!=args.id]
    elif args.action=='release':draft,uploads=prepare_release(draft,args.version,args.installer,args.portable,Path(args.notes).read_text(encoding='utf-8') if args.notes else '')
    print(json.dumps(publish(draft,uploads,args.dry_run),ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as error:print(str(error),file=sys.stderr);sys.exit(1)
