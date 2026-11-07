"""Account-scoped emoticon cache decoding, with bounded local key discovery.

Format references: CN-Grace/Wechat-Emoticon-Parser (v4.0-plus, MIT).
Key derivation and package offsets are implemented independently here.
"""
import hashlib
import os
import re
import time
from collections import OrderedDict
from pathlib import Path

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import unpad

from .account_assets import HASH,text
from .media_codec import image_prefix,encrypted_media_variants
from .paths import app_data_root


def derive_emoticon_key(seed,wxid):return hashlib.md5((str(seed)+wxid+'EMOTICON').encode()).digest()


def decrypt_cache(raw,key):
    if not raw or len(raw)%16 or not key:return None
    try:return unpad(AES.new(key,AES.MODE_CBC,iv=key).decrypt(raw),16)
    except ValueError:return None


def discover_emoticon_key(raw,wxid,cancel,timeout=20,validate=None):
    """Only read Weixin.exe. Neither candidate seeds nor process bytes are logged."""
    if os.name!='nt' or not wxid or len(raw)<32 or len(raw)%16:return None
    import ctypes
    from wx4 import key as memory
    deadline=time.monotonic()+timeout;seen=set();pattern=re.compile(rb'(?<!\d)\d{5,20}(?!\d)')
    memory.enable_debug_privilege()
    for process in memory.find_weixin_processes()[:3]:
        if time.monotonic()>=deadline:return None
        handle=memory._open(process['pid'])
        if not handle:continue
        try:
            # Enumerate with the same explicit 64-bit API types as the DB reader.
            address=0;regions=[];mbi=memory._MBI()
            while address<memory.MAX_USER_ADDRESS and time.monotonic()<deadline:
                cancel()
                if not memory.kernel32.VirtualQueryEx(handle,ctypes.c_void_p(address),ctypes.byref(mbi),ctypes.sizeof(mbi)):break
                base,size=mbi.BaseAddress,mbi.RegionSize;address=base+size
                if address<=base:break
                if mbi.State==memory.MEM_COMMIT and not mbi.Protect&0x100 and mbi.Protect&0xff in memory.READABLE:
                    regions.append((0 if mbi.Type==0x20000 else 1,base,size))
            def read(address,size):
                cancel()
                return memory._read(handle,address,size) if time.monotonic()<deadline else b''
            for _,chunk in memory._iter_chunks([(base,size) for priority,base,size in sorted(regions)],read,overlap=24):
                if time.monotonic()>=deadline:return None
                for match in pattern.finditer(chunk):
                    candidate=match.group()
                    if candidate in seen:continue
                    seen.add(candidate)
                    if len(seen)%256==0:
                        cancel()
                        if time.monotonic()>=deadline:return None
                    if len(seen)>200000:return None
                    key=derive_emoticon_key(candidate.decode('ascii'),wxid)
                    prefix=AES.new(key,AES.MODE_CBC,iv=key).decrypt(raw[:32])
                    if image_prefix(prefix):
                        plain=decrypt_cache(raw,key)
                        if plain and image_prefix(plain) and (validate is None or validate(plain)):return key
        finally:memory.kernel32.CloseHandle(handle)
    return None


class StickerCache:
    def __init__(self,data,codec,cancel,status=lambda _:None):
        self.data=data;self.codec=codec;self.cancel=cancel;self.status=status
        self.account=Path(data.account_dir()).resolve();self.base=self.account/'business/emoticon'
        token=hashlib.sha256((str(self.account)+'\0'+data.wxid).encode()).hexdigest()
        self.key_path=Path(getattr(data,'cache_root',None) or app_data_root())/'media-cache'/token/'emoticon-key.bin'
        self.key=None;self.scanned=False;self.scan_timeout=20;self.packages=OrderedDict()
        try:
            value=self.key_path.read_bytes()
            if len(value)==16:self.key=value
        except OSError:pass

    def safe_read(self,path,limit=128*1024*1024):
        self.cancel();path=Path(path)
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(self.account) or not path.is_file() or path.stat().st_size>limit:return None
            return path.read_bytes()
        except OSError:return None

    def plain(self,raw):
        if not raw:return None
        if image_prefix(raw):return raw
        plain=decrypt_cache(raw,self.key)
        if plain and image_prefix(plain):return plain
        if len(raw)%16:return None
        if self.scanned or self.scan_timeout<=0:return None
        self.scanned=True;self.status('正在获取当前账号的表情缓存解密材料…')
        key=discover_emoticon_key(raw,self.data.wxid,self.cancel,timeout=self.scan_timeout,
                                  validate=lambda value:self.codec.sticker(value) is not None)
        if key:
            plain=decrypt_cache(raw,key)
            if plain is None or self.codec.sticker(plain) is None:return None
            self.key=key
            try:
                self.key_path.parent.mkdir(parents=True,exist_ok=True)
                temp=self.key_path.with_suffix('.tmp');temp.write_bytes(key);os.replace(temp,self.key_path)
            except OSError:pass
            return plain
        return None

    def render(self,raw,keys=()):
        if not raw:return None
        direct=self.codec.sticker(raw)
        if direct:return direct
        for plain in encrypted_media_variants(raw,keys,self.cancel):
            image=self.codec.sticker(plain)
            if image:return image
        plain=self.plain(raw)
        return self.codec.sticker(plain) if plain else None

    def package_member(self,member,thumbnail=False):
        package=member.get('package_id')
        if not package:return None
        digest=hashlib.md5(package.encode()).hexdigest();kind='ThumbStore' if thumbnail else 'PersistStore'
        marker=(kind,digest)
        if marker in self.packages:
            plain=self.packages.pop(marker);self.packages[marker]=plain
        else:
            raw=self.safe_read(self.base/kind/digest[:2]/digest)
            plain=self.plain(raw) if raw else None
            # A package is one CBC stream; database offsets point into plaintext.
            if plain is not None:
                self.packages[marker]=plain
                while len(self.packages)>2:self.packages.popitem(last=False)
        if plain is None:return None
        offset=member.get('thumb_offset' if thumbnail else 'offset',-1)
        size=member.get('thumb_size' if thumbnail else 'size',0)
        if not isinstance(offset,int) or not isinstance(size,int) or offset<0 or size<=0 or offset+size>len(plain):return None
        return self.codec.sticker(plain[offset:offset+size])

    def local(self,member,thumbnail=False):
        digest=member['md5']
        if not HASH.fullmatch(digest):return None
        metadata=member.get('metadata') or {};keys=[text(metadata.get('aes_key'))]
        kind='Thumb' if thumbnail else 'Persist'
        candidates=[self.base/kind/digest[:2]/(digest+('.thumb' if thumbnail else ''))]
        if not thumbnail:
            cache=self.account/'cache'
            if cache.is_dir():
                for month in sorted(cache.iterdir(),reverse=True):
                    if month.is_dir() and not month.is_symlink():candidates.append(month/'Emoticon'/digest[:2]/digest)
        for path in candidates:
            result=self.render(self.safe_read(path),keys)
            if result:return result
        return self.package_member(member,thumbnail)

    def resolve(self,member,resources,download=True):
        image=self.local(member)
        if image:return image,'original'
        info=member.get('metadata') or {};keys=[text(info.get('aes_key'))]
        def source(url,limit):
            if download:return resources._download(url,limit)
            path=resources.keys.path.parent/'downloads'/(hashlib.sha256(url.encode()).hexdigest()+'.media')
            try:return path if path.is_file() and not path.is_symlink() and path.stat().st_size<=limit else None
            except OSError:return None
        for field in ('cdn_url','tp_url','encrypt_url','extern_url'):
            url=text(info.get(field))
            if not url:continue
            path=source(url,24*1024*1024)
            if path:
                image=self.render(path.read_bytes(),keys)
                if image:return image,'original'
        image=self.local(member,thumbnail=True)
        if image:return image,'thumbnail'
        if info.get('thumb_url'):
            path=source(text(info['thumb_url']),8*1024*1024)
            if path:
                image=self.render(path.read_bytes(),keys)
                if image:return image,'thumbnail'
        return None,'unavailable'
