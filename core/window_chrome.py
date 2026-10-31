"""Windows DWM corners and native frame, retaining the QCE client title bar."""
import ctypes
import ctypes.wintypes as wt
import os

if os.name == 'nt':
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    dwmapi = ctypes.WinDLL('dwmapi', use_last_error=True)
    user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.SetWindowPos.restype = wt.BOOL
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowRect.restype = wt.BOOL
    user32.IsZoomed.argtypes = [wt.HWND]
    user32.IsZoomed.restype = wt.BOOL
    user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
    user32.MonitorFromWindow.restype = wt.HANDLE
    dwmapi.DwmSetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('rcMonitor', wt.RECT),
                ('rcWork', wt.RECT), ('dwFlags', wt.DWORD)]


class MARGINS(ctypes.Structure):
    _fields_ = [('left', ctypes.c_int), ('right', ctypes.c_int),
                ('top', ctypes.c_int), ('bottom', ctypes.c_int)]


if os.name == 'nt':
    user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wt.BOOL
    dwmapi.DwmExtendFrameIntoClientArea.argtypes = [wt.HWND, ctypes.POINTER(MARGINS)]
    dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long


GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def configure_frame(hwnd):
    if os.name != 'nt': return False
    # DWM rounds the actual HWND when the normal native frame capabilities
    # exist. WM_NCCALCSIZE below removes the system title bar, not the frame.
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE,
        style | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
    preference = ctypes.c_int(DWMWCP_ROUND)
    result = dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                         ctypes.byref(preference), ctypes.sizeof(preference))
    policy = ctypes.c_int(2) # DWMNCRP_ENABLED: keep native shadow/composition.
    dwmapi.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(policy), ctypes.sizeof(policy))
    margins = MARGINS(1, 1, 1, 1)
    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0020 | 0x0001 | 0x0002 | 0x0004 | 0x0010)
    return result == 0


def corner_preference(hwnd):
    value = ctypes.c_int()
    result = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                         ctypes.byref(value), ctypes.sizeof(value))
    return value.value if result == 0 else None


def native_message(message, window):
    if os.name != 'nt': return None
    msg = wt.MSG.from_address(int(message))
    if msg.message == 0x83 and msg.wParam: # WM_NCCALCSIZE
        if user32.IsZoomed(msg.hWnd):
            # Preserve the monitor work area when maximized (taskbar remains
            # visible), including monitors with non-zero or negative origins.
            monitor = user32.MonitorFromWindow(msg.hWnd, 2)
            info = MONITORINFO(); info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                rect = wt.RECT.from_address(msg.lParam)
                rect.left, rect.top = info.rcWork.left, info.rcWork.top
                rect.right, rect.bottom = info.rcWork.right, info.rcWork.bottom
        return (True, 0)
    if msg.message == 0x84 and not window.isMaximized(): # WM_NCHITTEST
        rect = wt.RECT()
        if not user32.GetWindowRect(msg.hWnd, ctypes.byref(rect)): return None
        x = ctypes.c_short(msg.lParam & 0xffff).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xffff).value
        border = max(5, int(6 * window.devicePixelRatioF()))
        left, right = x < rect.left + border, x >= rect.right - border
        top, bottom = y < rect.top + border, y >= rect.bottom - border
        hit = (13 if top and left else 14 if top and right else 16 if bottom and left
               else 17 if bottom and right else 10 if left else 11 if right
               else 12 if top else 15 if bottom else None)
        if hit: return (True, hit)
    return None
