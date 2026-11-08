"""Explicit, cancellable image recovery confined to the connected account."""
import json
import os
import time
from pathlib import Path

from .media_codec import ImageKeys
from .paths import is_link
from wx4.media import SIG_V2, decrypt_dat_prefix, find_dat_aes_key, read_dat_key_probe


def recent_image_samples(data, cancel=lambda: None, limit=40, seconds=8):
    account = Path(data.account_dir()).resolve()
    deadline = time.monotonic() + seconds
    attach = account / 'msg/attach'
    directories = []

    def children(parent):
        if not parent.is_dir() or is_link(parent):
            return
        try:
            for path in parent.iterdir():
                cancel()
                if time.monotonic() >= deadline:
                    return
                if not is_link(path) and path.is_dir() and path.resolve().is_relative_to(account):
                    yield path
        except OSError:
            return

    # Enumerating directory metadata is cheap even for years of history. Reading
    # every old DAT first is not: a bounded walk used to expire inside the first
    # conversation, before reaching the image the user has just opened.
    for session in children(attach):
        cancel()
        if time.monotonic() >= deadline:
            break
        for month in children(session):
            cancel()
            if time.monotonic() >= deadline:
                break
            images = month / 'Img'
            if images.is_dir() and not is_link(images) and images.resolve().is_relative_to(account):
                directories.append(images)
    cache = account / 'cache'
    directories.extend(month / 'Sns' for month in children(cache)
                       if (month / 'Sns').is_dir() and not is_link(month / 'Sns'))
    ranked = []
    for directory in directories:
        cancel()
        if time.monotonic() >= deadline:
            break
        try:
            ranked.append((directory.stat().st_mtime, str(directory)))
        except OSError:
            continue
    # A newly downloaded file updates its containing directory even when its
    # session/month ancestors have not changed. Rank at the image directory.
    bases = [Path(path) for _, path in sorted(ranked, reverse=True)]
    bases.append(attach)  # Retain bounded fallback for older/unusual layouts.
    recent = []
    visited = 0
    seen = set()
    for base in bases:
        if not base.is_dir() or is_link(base):
            continue
        for directory, dirs, files in os.walk(base, followlinks=False):
            cancel()
            dirs[:] = [name for name in dirs if not is_link(Path(directory) / name)]
            candidates = []
            for name in files:
                cancel()
                visited += 1
                if visited > 50000 or time.monotonic() >= deadline:
                    return [Path(row[1]) for row in sorted(recent, reverse=True)]
                path = Path(directory) / name
                if is_link(path) or not path.resolve().is_relative_to(account):
                    continue
                try:
                    stat = path.stat()
                    if not 31 <= stat.st_size <= 128 * 1024 * 1024:
                        continue
                    candidates.append((stat.st_mtime, str(path)))
                except OSError:
                    continue
            for modified, filename in sorted(candidates, reverse=True):
                cancel()
                if time.monotonic() >= deadline:
                    return [Path(row[1]) for row in sorted(recent, reverse=True)]
                path = Path(filename)
                if path in seen:
                    continue
                seen.add(path)
                try:
                    with path.open('rb') as source:
                        if source.read(6) != SIG_V2:
                            continue
                    recent.append((modified, filename))
                    if len(recent) >= limit:
                        return [Path(row[1]) for row in sorted(recent, reverse=True)]
                except OSError:
                    continue
    return [Path(row[1]) for row in sorted(recent, reverse=True)]


def recover_local_images(data, cancel, status, timeout=45):
    status('正在检查当前账号的近期图片缓存…')
    paths = recent_image_samples(data, cancel)
    if not paths:
        raise ValueError('当前账号未找到可用于恢复的本地 V2 图片。请先在微信打开需要的图片，再重试。')
    diagnostics = {}
    status('正在读取并严格校验当前账号的图片密钥，可随时取消…')
    key = find_dat_aes_key(str(paths[0]), sample_paths=paths[1:], cancel=cancel,
                           timeout=timeout, diagnostics=diagnostics, wxid=data.wxid)
    cancel()
    if not key:
        if diagnostics.get('processes_found') == 0:
            raise ValueError('未检测到电脑微信，请打开并登录微信后重试。')
        if diagnostics.get('processes_readable') == 0:
            raise ValueError('无法读取微信进程。若微信以管理员运行，请以同等权限打开 Moect 后重试。')
        raise ValueError('本地图片已找到，但本次尚未取得通过完整校验的图片密钥。请在微信打开一张近期原图后重试。')
    keys = ImageKeys(data, cancel, progress=status)
    keys.scan_remaining = 0
    verified = None
    for path in paths:
        cancel()
        probe = read_dat_key_probe(path)
        if probe is not None and decrypt_dat_prefix(probe, key) is not None:
            verified = probe
            break
    if verified is None:
        raise ValueError('图片候选密钥未通过完整校验，未保存，请重试。')
    cancel()
    keys._remember(key, verified)
    try:
        saved = json.loads(keys.path.read_text(encoding='utf-8'))
        if key.hex() not in saved.get('keys', []):
            raise ValueError()
    except (OSError, ValueError):
        raise ValueError('图片解密材料已验证，但无法保存到当前缓存目录，请检查目录权限和可用空间。') from None
    decoded = False
    for path in paths[:8]:
        cancel()
        try:
            raw = path.read_bytes()
            plain = keys.decode(raw, path, paths)
            if keys.rendered or plain and keys.codec.image(plain):
                decoded = True
                break
        except OSError:
            continue
    return {'samples': len(paths), 'aes_verified': True, 'decoded_sample': decoded}
