"""Validated program-only replacement with a recovery copy; never touches user data."""
import json
import os
import shutil
import stat
import zipfile
from pathlib import PurePosixPath


def relative_name(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value:raise ValueError('更新包路径无效')
    path=PurePosixPath(value)
    if path.is_absolute() or any(p in ('','.','..') or p.rstrip(' .')!=p or p.split('.')[0].upper() in ('CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]) for p in value.split('/')):raise ValueError('更新包路径无效')
    return path.as_posix()


def inside(root,name):
    path=(root/relative_name(name)).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('更新文件超出程序目录')
    return path


def unpack_portable(package,stage):
    with zipfile.ZipFile(package) as archive:
        files=[info for info in archive.infolist() if not info.is_dir()]
        if not files or len(files)>20000 or sum(i.file_size for i in files)>2*1024**3:raise ValueError('更新包文件数量或体积异常')
        names=[relative_name(info.filename) for info in files]
        prefix=names[0].split('/')[0]+'/'
        strip=all(name.startswith(prefix) for name in names) and prefix+'Moect.exe' in names
        seen=set()
        for info,name in zip(files,names):
            if stat.S_ISLNK(info.external_attr>>16):raise ValueError('更新包不允许包含符号链接')
            name=relative_name(name[len(prefix):] if strip else name)
            if name.lower() in seen:raise ValueError('更新包包含重复文件')
            seen.add(name.lower());target=inside(stage,name);target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(info) as source,target.open('wb') as output:shutil.copyfileobj(source,output,1024*1024)
    if not (stage/'Moect.exe').is_file() or not (stage/'_internal').is_dir():raise ValueError('更新包不是完整的 Moect 便携版')
    return names


def managed_files(root):
    path=root/'program-files.json'
    if not path.is_file():raise ValueError('当前程序缺少更新文件清单，请先使用完整安装包更新一次。')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or not isinstance(value.get('files'),list) or len(value['files'])>20000:raise ValueError('程序文件清单无效')
    names=[relative_name(name) for name in value['files']]
    if 'Moect.exe' not in names:raise ValueError('程序文件清单不完整')
    for name in names:inside(root,name)
    return set(names)|{'program-files.json'}


def backup_program(target,recovery,extra=()):
    target=target.resolve()
    if not (target/'Moect.exe').is_file() or not (target/'_internal').is_dir():raise ValueError('更新目标不是 Moect 程序目录')
    names=managed_files(target)|set(extra);existing=set()
    for name in names:
        source=inside(target,name)
        if source.is_file():
            destination=inside(recovery,name);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination);existing.add(name)
    (recovery/'recovery-index.json').write_text(json.dumps({'files':sorted(names),'existing':sorted(existing)}),encoding='utf-8')
    return names


def restore_program(target,recovery):
    index=json.loads((recovery/'recovery-index.json').read_text(encoding='utf-8'));existing=set(index['existing'])
    for name in index['files']:
        destination=inside(target,name)
        if name in existing:
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(inside(recovery,name),destination)
        elif destination.is_file():destination.unlink()


def replace_portable(target,stage,recovery):
    target=target.resolve();new_names=managed_files(stage);old_names=backup_program(target,recovery,new_names)
    # Every managed entry in the new package must actually be supplied.
    for name in new_names:
        if not inside(stage,name).is_file():raise ValueError('更新包缺少清单中的文件')
    try:
        for name in sorted(new_names):
            source=inside(stage,name);destination=inside(target,name);destination.parent.mkdir(parents=True,exist_ok=True)
            temporary=destination.with_name(destination.name+'.moect-new')
            try:
                shutil.copy2(source,temporary)
                os.replace(temporary,destination)
            finally:
                temporary.unlink(missing_ok=True)
        for name in old_names-new_names:
            destination=inside(target,name)
            if destination.is_file():destination.unlink()
    except Exception:
        restore_program(target,recovery)
        raise
