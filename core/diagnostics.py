"""Content-free connection diagnostics suitable for a user-supplied report."""
import ctypes
import json
import platform
from datetime import datetime
from pathlib import Path

from .version import VERSION


class ConnectionProblem(ValueError):
    def __init__(self, message, code, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def file_version(path):
    try:
        from ctypes import wintypes
        library = ctypes.WinDLL('version', use_last_error=True)
        library.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        library.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        library.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        size = library.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ''
        buffer = ctypes.create_string_buffer(size)
        if not library.GetFileVersionInfoW(str(path), 0, size, buffer):
            return ''
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not library.VerQueryValueW(buffer, '\\', ctypes.byref(pointer), ctypes.byref(length)):
            return ''
        values = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
        return '.'.join(str(v) for v in (values[2] >> 16, values[2] & 65535, values[3] >> 16, values[3] & 65535))
    except (OSError, ValueError, AttributeError):
        return ''


def environment(processes):
    import psutil
    versions = set()
    for process in processes:
        try:
            value = file_version(psutil.Process(process['pid']).exe())
            if value:
                versions.add(value)
        except psutil.Error:
            pass
    return {'moect_version': VERSION, 'windows': platform.version(), 'wechat_versions': sorted(versions)}


def write_report(service, directory, job_id=None):
    with service.lock:
        jobs = [task for task in service.config['tasks'] if not job_id or task['id'] == job_id][-20:]
        # Deliberately select fields. Exception strings, usernames, paths,
        # keys and message text never enter this report.
        entries = [{key: task[key] for key in ('kind', 'status', 'progress', 'stage', 'error_code', 'diagnostic', 'created_at') if key in task} for task in jobs]
        allowed = {'moect_version', 'windows', 'wechat_versions', 'missing', 'resolved_databases',
                   'failed_databases', 'skipped_databases', 'denied_processes', 'database_count'}
        for entry in entries:
            if 'diagnostic' in entry:
                entry['diagnostic'] = {key: value for key, value in entry['diagnostic'].items() if key in allowed}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/('Moect-diagnostics-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    payload = {'application': 'Moect', 'version': VERSION, 'windows': platform.version(), 'tasks': entries}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'path': str(path), 'count': len(entries)}
