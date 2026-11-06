"""Stable author storage across packaged (MSIX) and ordinary desktop processes."""
import json
import os
import shutil
import sys
from pathlib import Path

from Cryptodome.PublicKey import ECC
from .paths import is_link


def physical_path(path):
    """Path.resolve does not expose Windows package AppData redirection."""
    path=Path(path)
    if sys.platform!='win32':return path.resolve()
    import ctypes
    from ctypes import wintypes as wt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wt.LPCWSTR,wt.DWORD,wt.DWORD,ctypes.c_void_p,wt.DWORD,wt.DWORD,wt.HANDLE];kernel.CreateFileW.restype=wt.HANDLE
    kernel.GetFinalPathNameByHandleW.argtypes=[wt.HANDLE,wt.LPWSTR,wt.DWORD,wt.DWORD];kernel.GetFinalPathNameByHandleW.restype=wt.DWORD
    kernel.CloseHandle.argtypes=[wt.HANDLE]
    handle=kernel.CreateFileW(str(path),0,7,None,3,0x02000000,None)
    if not handle or handle==ctypes.c_void_p(-1).value:return path.absolute()
    try:
        output=ctypes.create_unicode_buffer(32768)
        length=kernel.GetFinalPathNameByHandleW(handle,output,len(output),0)
        if not 0<length<len(output):return path.absolute()
        value=output.value
        if value.startswith('\\\\?\\UNC\\'):value='\\\\'+value[8:]
        elif value.startswith('\\\\?\\'):value=value[4:]
        return Path(value)
    finally:kernel.CloseHandle(handle)


def profile_root():return Path(os.environ.get('USERPROFILE') or Path.home())


def author_root():return profile_root()/'.moect-publisher'


def package_caches():
    packages=profile_root()/'AppData/Local/Packages'
    return sorted(packages.glob('OpenAI.Codex_*/LocalCache')) if packages.is_dir() else []


def unique_existing(paths):
    seen=set()
    for path in paths:
        path=physical_path(path);key=os.path.normcase(str(path))
        if key not in seen and path.exists():seen.add(key);yield path


def legacy_author_roots():
    local=Path(os.environ.get('LOCALAPPDATA',profile_root()/'AppData/Local'))
    return list(unique_existing([local/'MoectPublisher',profile_root()/'AppData/Local/MoectPublisher',
                                *(cache/'Local/MoectPublisher' for cache in package_caches())]))


def oauth_path():
    relative='xdg.config/.wrangler/config/default.toml'
    roaming=Path(os.environ.get('APPDATA',profile_root()/'AppData/Roaming'))
    candidates=[roaming/relative,profile_root()/'AppData/Roaming'/relative,
                *(cache/'Roaming'/relative for cache in package_caches())]
    return next((path for path in unique_existing(candidates) if path.is_file()),roaming/relative)


def matches_key(path,public_key):
    try:
        key=ECC.import_key(Path(path).read_text(encoding='utf-8-sig'));public=ECC.import_key(public_key)
        return key.has_private() and not public.has_private() and key.curve==public.curve=='Ed25519' and key.public_key().export_key(format='DER')==public.export_key(format='DER')
    except (OSError,ValueError,TypeError,IndexError):return False


def migrate_author_data(destination,candidates,public_key):
    """Copy only this publisher's validated identity; preserve every original."""
    destination=Path(destination)
    if (destination/'signing-key.pem').exists():return None
    source=next((Path(root) for root in candidates if matches_key(Path(root)/'signing-key.pem',public_key)),None)
    if source is None:return None
    destination.mkdir(parents=True,exist_ok=True)
    if physical_path(destination)!=destination.absolute():raise ValueError('新的作者目录仍被重定向，已停止迁移。')
    def copy_missing(src,dst):
        src=Path(src);dst=Path(dst)
        if dst.exists() or is_link(src) or not src.is_file():return
        dst.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive creation must never overwrite restored or concurrently saved data.
        try:
            with src.open('rb') as reader,dst.open('xb') as writer:shutil.copyfileobj(reader,writer)
        except FileExistsError:pass
    for name in ('cloudflare.json','draft.json','editor-state.json','publisher-ui.json','history.json','retired.json','cleanup-pending.json','wrangler.json'):
        copy_missing(source/name,destination/name)
    for name in ('editor-images','public-assets'):
        folder=source/name
        if not folder.is_dir() or is_link(folder):continue
        for base,dirs,files in os.walk(folder,followlinks=False):
            dirs[:]=[d for d in dirs if not is_link(Path(base)/d)]
            for filename in files:
                original=Path(base)/filename;copy_missing(original,destination/name/original.relative_to(folder))
    copy_missing(source/'signing-key.pem',destination/'signing-key.pem')
    if not matches_key(destination/'signing-key.pem',public_key):raise ValueError('迁移后的原签名私钥校验失败，已停止发布。')
    return source


def prepare_author_root(destination,trust_file):
    if Path(destination)!=author_root():return None
    try:trust=json.loads(Path(trust_file).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return None
    if not isinstance(trust,dict):return None
    return migrate_author_data(destination,legacy_author_roots(),trust.get('public_key',''))
