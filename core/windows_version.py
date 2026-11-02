"""Read Windows' actual kernel version without manifest-dependent GetVersionEx."""
import sys


def _rtl_version():
    import ctypes
    from ctypes import wintypes as wt

    class VersionInfo(ctypes.Structure):
        _fields_ = [('size', wt.DWORD), ('major', wt.DWORD),
                    ('minor', wt.DWORD), ('build', wt.DWORD),
                    ('platform', wt.DWORD), ('service_pack', wt.WCHAR * 128)]

    info = VersionInfo()
    info.size = ctypes.sizeof(info)
    query = ctypes.WinDLL('ntdll').RtlGetVersion
    query.argtypes = [ctypes.POINTER(VersionInfo)]
    query.restype = wt.LONG
    if query(ctypes.byref(info)) != 0:
        raise OSError('RtlGetVersion failed')
    return info.major, info.minor, info.build


def _valid_version(value):
    return (isinstance(value, (tuple, list)) and len(value) == 3
            and all(type(part) is int and part >= 0 for part in value)
            and value[0] > 0 and value[2] > 0)


def windows_version():
    try:
        actual = _rtl_version()
        if _valid_version(actual):
            return tuple(actual)
    except (OSError, AttributeError, ValueError):
        pass
    try:
        actual = sys.getwindowsversion().platform_version
        if _valid_version(actual):
            return tuple(actual)
    except (OSError, AttributeError, ValueError):
        pass
    # .build can report 9200 on Windows 10/11 when the manifest is missing.
    # An unknown version must not be presented as an old operating system.
    raise ValueError('无法确认 Windows 系统版本，请重新启动软件后重试。')


def require_windows_build(minimum=17763):
    if sys.platform != 'win32':
        return
    current = windows_version()[2]
    if current < minimum:
        raise ValueError(f'新版需要 Windows 系统内部版本 {minimum} 或以上（当前为 {current}）。')
