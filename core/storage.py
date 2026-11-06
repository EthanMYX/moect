"""Managed cache inventory, verified migration and narrowly scoped cleanup."""
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from .paths import is_link

MANAGED = ('archives', 'media-cache', 'avatar-cache', 'previews')


def files_below(root, cancel=lambda: None):
    root = Path(root)
    if not root.is_dir():
        return
    if is_link(root):
        raise ValueError('缓存目录包含外部链接，请先移除链接后重试。')
    root = root.resolve()
    for directory, directories, names in os.walk(root, followlinks=False):
        cancel()
        for name in directories + names:
            path = Path(directory)/name
            if is_link(path) or not path.resolve().is_relative_to(root):
                raise ValueError('缓存目录包含外部链接，请先移除链接后重试。')
        for name in names:
            path = Path(directory)/name
            if path.is_file():
                yield path


def managed_root(service, root):
    if is_link(root):
        raise ValueError('缓存根目录不可使用链接或目录联接。')
    root = Path(root).resolve()
    if root == service.root.resolve():
        return root
    try:
        marker = json.loads((root/'.moect-storage.json').read_text(encoding='utf-8'))
        if marker.get('owner') == service.config['storage_id']:
            return root
    except (OSError, ValueError, KeyError):
        pass
    raise ValueError('该目录不是此软件管理的缓存目录。')


def storage_info(service):
    roots = [service.storage_root, *map(Path, service.config.get('storage_history', []))]
    seen = set()
    result = []
    for candidate in roots:
        root = candidate.resolve()
        if root in seen:
            continue
        seen.add(root)
        try:
            managed_root(service, root)
            categories = {name: sum(p.stat().st_size for p in files_below(root/name)) for name in MANAGED}
        except (OSError, ValueError):
            continue
        result.append({'path': str(root), 'current': root == service.storage_root.resolve(),
                       'bytes': sum(categories.values()), 'categories': categories})
    return {'path': str(service.storage_root), 'roots': result, 'warning': service.storage_warning,
            'bytes': sum(item['bytes'] for item in result)}


def migrate(service, parent, job):
    source = managed_root(service, service.storage_root)
    parent = Path(parent).resolve()
    if service.storage_warning:
        raise ValueError('请先连接原缓存磁盘，再迁移缓存。')
    parent.mkdir(parents=True, exist_ok=True)
    forbidden = [source, service.root.resolve(), Path(service.config['export_dir']).resolve()]
    library = service.config.get('library') or {}
    if library.get('account_dir'):
        forbidden.append(Path(library['account_dir']).resolve())
    if any(parent == root or parent.is_relative_to(root) for root in forbidden):
        raise ValueError('请选择独立的缓存位置，例如 D:\\Moect缓存。')
    destination = parent/'MoectData'
    number = 2
    while destination.exists():
        destination = parent/('MoectData_' + str(number))
        number += 1
    staging = parent/('.moect-migration-' + uuid.uuid4().hex)
    check = lambda: service._check(job)
    inventory = [path for name in MANAGED for path in files_below(source/name, check)]
    total = sum(path.stat().st_size for path in inventory)
    if shutil.disk_usage(parent).free < total + 16 * 1024 * 1024:
        raise ValueError('目标磁盘可用空间不足，请选择其他位置。')
    staging.mkdir()
    committed = False
    published = False
    try:
        written = 0
        for path in inventory:
            check()
            before = path.stat()
            target = staging/path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with path.open('rb') as original, target.open('wb') as copied:
                while True:
                    check()
                    block = original.read(1024 * 1024)
                    if not block:
                        break
                    copied.write(block)
                    digest.update(block)
                    written += len(block)
            with target.open('rb') as copied:
                verification = hashlib.sha256()
                while True:
                    check()
                    block = copied.read(1024 * 1024)
                    if not block:
                        break
                    verification.update(block)
            if digest.digest() != verification.digest():
                raise ValueError('迁移文件校验失败，原缓存仍可使用。')
            after = path.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise ValueError('迁移期间缓存发生变化，请稍后重试。')
            shutil.copystat(path, target)
            service._update(job, progress=min(95, int(95 * written/max(total, 1))), detail='正在复制并校验缓存…')
        (staging/'.moect-storage.json').write_text(json.dumps({'owner': service.config['storage_id']}), encoding='utf-8')
        check()
        os.rename(staging, destination)
        published = True
        with service.lock:
            old_config = dict(service.config)
            old_library = service.library
            old_demo = service._demo_previous
            def relocated(value):
                if not value or value.get('demo'):
                    return value
                value = dict(value)
                for field in ('root', 'assets_root'):
                    path = Path(value[field]).resolve() if value.get(field) else None
                    if path is not None and path.is_relative_to(source):
                        value[field] = str(destination/path.relative_to(source))
                value['storage_root'] = str(destination)
                return value
            try:
                service.library = relocated(service.library)
                service._demo_previous = relocated(service._demo_previous)
                service.config['library'] = relocated(service.config.get('library'))
                service.config['storage_dir'] = str(destination)
                service.config['storage_history'] = list(dict.fromkeys([*service.config.get('storage_history', []), str(source)]))
                service.save()
            except BaseException:
                service.config = old_config
                service.library, service._demo_previous = old_library, old_demo
                raise
            service.storage_root = destination
            service._moments_preview_cache.clear()
            committed = True
        service._update(job, detail='缓存迁移完成。原位置的过期快照可在存储管理中清理。')
    finally:
        # Both targets are this operation's explicitly created children.
        for target in (staging, destination):
            if target.exists() and (target == staging or (published and not committed)):
                if target.resolve().parent != parent or is_link(target):
                    raise ValueError('迁移目录边界校验失败。')
                shutil.rmtree(target)


def cleanup(service, job):
    check = lambda: service._check(job)
    protected = [Path(service.config['export_dir']).resolve()]
    for library in (service.library, service.config.get('library'), service._demo_previous):
        for field in ('root', 'assets_root'):
            if library and library.get(field):
                protected.append(Path(library[field]).resolve())
    protected.extend(Path(task['folder']).resolve() for task in service.config['tasks'] if task.get('folder'))
    roots = {service.storage_root.resolve(), *[Path(p).resolve() for p in service.config.get('storage_history', [])]}
    freed = 0
    for candidate in roots:
        try:
            root = managed_root(service, candidate)
        except (OSError, ValueError):
            continue
        targets = []
        for account in (root/'archives').glob('*'):
            for path in account.glob('*'):
                if re.fullmatch(r'(?:snapshot|assets)_[0-9a-f]{12}', path.name):
                    targets.append(path)
        targets.extend((root/'media-cache').glob('*/downloads'))
        targets.append(root/'previews')
        for target in targets:
            check()
            if not target.is_dir():
                continue
            resolved = target.resolve()
            if not resolved.is_relative_to(root) or resolved == root or is_link(target):
                raise ValueError('清理目录边界校验失败。')
            if any(resolved == p or resolved.is_relative_to(p) or p.is_relative_to(resolved) for p in protected):
                continue
            size = sum(path.stat().st_size for path in files_below(target, check))
            shutil.rmtree(target)
            freed += size
            service._update(job, detail='正在清理过期缓存…')
    service._update(job, detail='清理完成，释放 %.1f MB。' % (freed/1024**2), freed_bytes=freed)


def source_database_bytes(library):
    root = Path(library['account_dir'])/'db_storage' if library.get('account_dir') else Path(library.get('root') or '')
    if not library.get('root') or not root.is_dir():
        return 0
    try:
        return sum(path.stat().st_size for path in root.rglob('*') if path.is_file() and path.suffix in ('.db', '.db-wal', '.db-shm'))
    except OSError:
        return None
