"""External updater. Built separately so the running application can exit first."""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from core.online_protocol import verify_feed,file_hash,version
from core.update_apply import unpack_portable,replace_portable,backup_program,restore_program
from core.paths import app_data_root
from core.channel_control import current_feed,require_current_release
from core.windows_version import require_windows_build


def wait_for_parent(pid):
    if type(pid) is not int or pid<=0 or pid==os.getpid():raise ValueError('更新进程信息无效')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];kernel.WaitForSingleObject.restype=ctypes.c_ulong
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x100000,False,pid)
    if not handle:
        if ctypes.get_last_error()==87:return
        raise ValueError('无法确认旧程序已经退出，请关闭 Moect 后重新更新。')
    try:
        if kernel.WaitForSingleObject(handle,90000)!=0:raise ValueError('旧程序尚未退出，已停止更新。')
    finally:kernel.CloseHandle(handle)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--plan');parser.add_argument('--verify-feed');args=parser.parse_args()
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).parent));trust=json.loads((base/'ui/online-config.json').read_text(encoding='utf-8'))
    if args.verify_feed:
        verify_feed(json.loads(Path(args.verify_feed).read_text(encoding='utf-8')),trust['public_key'],set(trust['hosts']));return
    if not args.plan:raise ValueError('缺少更新计划')
    plan=json.loads(Path(args.plan).read_text(encoding='utf-8'));feed=verify_feed(plan['envelope'],trust['public_key'],set(trust['hosts']))
    release=feed['release'];mode=plan['mode'];target=Path(plan['target']).resolve();package=Path(plan['package']).resolve()
    if mode not in ('installer','portable') or not release or mode not in release['packages']:raise ValueError('更新资源无效')
    require_windows_build(release.get('minimum_windows_build',17763))
    if not package.is_relative_to((app_data_root()/'online/downloads').resolve()):raise ValueError('更新包不在下载目录中')
    expected=release['packages'][mode]
    if not package.is_file() or package.stat().st_size!=expected['size'] or file_hash(package)!=expected['sha256']:raise ValueError('更新包校验失败')
    current=json.loads((target/'program-files.json').read_text(encoding='utf-8'))
    if version(release['version'])<=version(current['version']):raise ValueError('不能安装旧版本')
    wait_for_parent(plan['parent_pid'])
    _,latest=current_feed(trust,minimum_sequence=feed['sequence'])
    require_current_release(release,latest.get('release'))
    recovery=app_data_root()/'online/recovery'/(str(feed['sequence'])+'-'+uuid.uuid4().hex[:8]);recovery.mkdir(parents=True,exist_ok=False)
    if mode=='portable':
        with tempfile.TemporaryDirectory(prefix='moect-update-stage-') as temporary:
            stage=Path(temporary);unpack_portable(package,stage)
            if json.loads((stage/'program-files.json').read_text(encoding='utf-8')).get('version')!=release['version']:raise ValueError('便携包内的版本与发布信息不符')
            replace_portable(target,stage,recovery)
    else:
        backup_program(target,recovery)
        result=subprocess.run([str(package),'/SP-','/SILENT','/NORESTART','/NOFORCECLOSEAPPLICATIONS','/DIR='+str(target)],check=False)
        if result.returncode not in (0,3010):
            restore_program(target,recovery);raise ValueError('安装未完成，旧程序文件已恢复。')
        if result.returncode==3010:raise ValueError('更新已安装，需要重新启动 Windows 后再使用。')
    subprocess.Popen([str(target/'Moect.exe')],cwd=target,close_fds=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        # Only operational failure text; never include signed content or tokens.
        message=str(error) if isinstance(error,(ValueError,PermissionError)) else '更新未完成，请保留旧程序并重试，或使用完整安装包修复。'
        ctypes.windll.user32.MessageBoxW(None,message,'Moect 更新',0x10)
        sys.exit(1)
