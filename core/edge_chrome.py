"""WinForms native frame with client title bar and per-monitor DPI rounding."""
import ctypes
import ctypes.wintypes as wt
from .window_chrome import configure_frame,native_message,user32,dwmapi

PROC=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,wt.HWND,wt.UINT,wt.WPARAM,wt.LPARAM,ctypes.c_size_t,ctypes.c_size_t)
comctl=ctypes.WinDLL('comctl32',use_last_error=True)
comctl.SetWindowSubclass.argtypes=[wt.HWND,PROC,ctypes.c_size_t,ctypes.c_size_t]
comctl.SetWindowSubclass.restype=wt.BOOL
comctl.DefSubclassProc.argtypes=[wt.HWND,wt.UINT,wt.WPARAM,wt.LPARAM]
comctl.DefSubclassProc.restype=ctypes.c_ssize_t
comctl.RemoveWindowSubclass.argtypes=[wt.HWND,PROC,ctypes.c_size_t]
comctl.RemoveWindowSubclass.restype=wt.BOOL
user32.GetDpiForWindow.argtypes=[wt.HWND];user32.GetDpiForWindow.restype=wt.UINT
user32.ReleaseCapture.argtypes=[];user32.ReleaseCapture.restype=wt.BOOL
user32.SendMessageW.argtypes=[wt.HWND,wt.UINT,wt.WPARAM,wt.LPARAM]
user32.SendMessageW.restype=ctypes.c_ssize_t
user32.GetCursorPos.argtypes=[ctypes.POINTER(wt.POINT)];user32.GetCursorPos.restype=wt.BOOL


class NativeFrame:
    def __init__(self,hwnd):
        self.hwnd=hwnd
        self.callback=PROC(self._message)
        if not comctl.SetWindowSubclass(hwnd,self.callback,1,0):raise OSError('Cannot install native window frame')
        configure_frame(hwnd)

    def isMaximized(self):return bool(user32.IsZoomed(self.hwnd))
    def devicePixelRatioF(self):return user32.GetDpiForWindow(self.hwnd)/96

    def hideBorder(self):
        # DWMWA_COLOR_NONE removes the Win11 outline while retaining DWM's
        # rounded HWND and shadow. Older Windows simply ignores this attribute.
        value=wt.DWORD(0xFFFFFFFE)
        dwmapi.DwmSetWindowAttribute(self.hwnd,34,ctypes.byref(value),ctypes.sizeof(value))

    def _message(self,hwnd,message,wparam,lparam,*_):
        # Never let a Python exception cross the native window-procedure ABI.
        try:
            msg=wt.MSG();msg.hWnd=hwnd;msg.message=message;msg.wParam=wparam;msg.lParam=lparam
            result=native_message(ctypes.addressof(msg),self)
            if result is not None:return result[1]
            if message==0x82:comctl.RemoveWindowSubclass(hwnd,self.callback,1)
        except Exception:pass
        return comctl.DefSubclassProc(hwnd,message,wparam,lparam)

    def drag(self):
        user32.ReleaseCapture();user32.SendMessageW(self.hwnd,0xA1,2,0)

    def resize(self,edge):
        hit={'w':10,'e':11,'n':12,'nw':13,'ne':14,'s':15,'sw':16,'se':17}.get(edge)
        if not hit or self.isMaximized():return
        point=wt.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):return
        position=(point.x&0xffff)|((point.y&0xffff)<<16)
        user32.ReleaseCapture();user32.SendMessageW(self.hwnd,0xA1,hit,position)
