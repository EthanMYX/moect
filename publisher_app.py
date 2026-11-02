"""Standalone private Moect author application; no signing key is bundled."""
import argparse
import ctypes
import json
import os
import sys
import time
from pathlib import Path

import webview
from core.publisher_service import PublisherService
from core.online_protocol import web_url
from core.publisher_startup import StartupGuard

BASE=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
UI=BASE/'ui-publisher'
TITLE='Moect 发布中心'


class Api:
    def __init__(self,service,verification=False):
        self._service=service;self._window=None;self._frame=None;self._verification=verification
        self._startup=StartupGuard();self._startup_host=None

    def invoke(self,action,payload=None):
        try:
            if not isinstance(action,str) or not isinstance(payload or {},dict):raise ValueError('请求无效。')
            payload=payload or {}
            if self._verification and action=='publisher_start':raise ValueError('运行验证期间不执行发布或删除。')
            if len(json.dumps(payload,ensure_ascii=False))>180000:raise ValueError('请求过大。')
            service=self._service;window=self._window
            if action.startswith('window_'):
                from System import Action
                if action=='window_drag':window.native.Invoke(Action(self._frame.drag))
                elif action=='window_resize':
                    edge=payload.get('edge')
                    if edge not in ('n','s','e','w','nw','ne','sw','se'):raise ValueError('窗口边缘无效。')
                    window.native.Invoke(Action(lambda:self._frame.resize(edge)))
                elif action=='window_minimize':window.minimize()
                elif action=='window_maximize':window.restore() if self._frame.isMaximized() else window.maximize()
                elif action=='window_close':window.destroy()
                elif action!='window_state':raise ValueError('窗口操作无效。')
                result={'maximized':self._frame.isMaximized()}
            elif action=='publisher_state':result={**service.status(),'ui_generation':self._startup.generation}
            elif action=='publisher_ui_ready':
                accepted=self._startup.mark_ready(payload.get('generation'))
                if accepted and self._startup_host:self._startup_host.record('ui_ready')
                result={'ok':accepted}
            elif action=='publisher_ui_error':
                self._startup.fail('react_render_failed',payload.get('generation'))
                if self._startup_host:self._startup_host.record('react_render_failed')
                result={'ok':True}
            elif action=='publisher_reload_ui':
                from System import Action
                if self._startup_host:window.native.Invoke(Action(lambda:self._startup_host.reload(manual=True)))
                result={'ok':True}
            elif action=='publisher_save_editor':result=service.save_editor(payload)
            elif action=='publisher_check':result=service.check()
            elif action=='publisher_start':result=service.start(payload)
            elif action=='publisher_inspect':result=service.inspect_retired(payload.get('id'))
            elif action=='publisher_theme':
                result=service.set_theme(payload.get('theme'))
                from System import Action
                from System.Drawing import ColorTranslator
                window.native.Invoke(Action(lambda:setattr(window.native,'BackColor',ColorTranslator.FromHtml(service.appearance()['background']))))
            elif action=='publisher_preview_image':result=service.preview_image(payload.get('source'))
            elif action=='publisher_open_storage':os.startfile(str(service.root));result={'ok':True}
            elif action=='publisher_open_link':os.startfile(web_url(payload.get('url')));result={'ok':True}
            elif action=='publisher_choose':
                kind=payload.get('kind')
                types={'image':'图片 (*.png;*.jpg;*.jpeg;*.gif;*.webp)','markdown':'Markdown (*.md;*.txt)',
                    'installer':'Moect 安装包 (*.exe)','portable':'Moect 便携包 (*.zip)'}
                if kind not in types:raise ValueError('文件类型无效。')
                chosen=window.create_file_dialog(webview.FileDialog.OPEN,file_types=(types[kind],))
                if not chosen:result={'cancelled':True}
                elif kind=='image':result=service.add_image(chosen[0])
                elif kind=='markdown':result=service.import_markdown(chosen[0])
                else:result={'path':chosen[0]}
            else:raise ValueError('不支持的发布操作。')
            return {'result':result}
        except Exception as error:
            return {'error':str(error)[:500] if isinstance(error,(ValueError,OSError)) else '操作未完成，请稍后重试。'}

    def _install_frame(self):
        from System import Action
        from System.Drawing import Icon,ColorTranslator
        from System.Windows.Forms import Padding
        from core.edge_chrome import NativeFrame
        from core.window_state import WindowPlacement
        from core.publisher_window import PublisherWindow
        def install():
            form=self._window.native
            form.BackColor=ColorTranslator.FromHtml(self._service.appearance()['background'])
            form.Padding=Padding(0)
            self._frame=NativeFrame(form.Handle.ToInt64());self._frame.hideBorder()
            self._placement=WindowPlacement(form,self._service,self._frame)
            def resize(*_):
                if form.webview.IsDisposed or form.webview.CoreWebView2 is None:return
                detail=json.dumps({'maximized':self._frame.isMaximized()})
                form.webview.CoreWebView2.ExecuteScriptAsync('window.dispatchEvent(new CustomEvent("wce-window-state",{detail:'+detail+'}));')
            def ready(*_):
                core=form.webview.CoreWebView2
                if core is None:return
                try:core.Settings.IsNonClientRegionSupportEnabled=True;core.ExecuteScriptAsync('window.__wceNativeRegions=true;')
                except Exception:pass
            self._handlers=(resize,ready)
            form.Resize+=resize;form.DpiChanged+=resize
            form.webview.CoreWebView2InitializationCompleted+=ready
            if form.webview.CoreWebView2 is not None:ready()
            icon=BASE/'ui-publisher/icon.ico'
            if icon.exists():form.Icon=Icon(str(icon))
            self._startup_host=PublisherWindow(self,form)
        self._window.native.Invoke(Action(install))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-check',type=Path);parser.add_argument('--gui-check',type=Path)
    parser.add_argument('--gui-fault',choices=('reload','recreate'));args=parser.parse_args()
    if args.gui_fault and not args.gui_check:parser.error('--gui-fault requires --gui-check')
    service=PublisherService()
    if args.self_check:
        try:
            service.check_sync()
            result={'ok':True,'public_signature_verified':True,'signer_matches_client':not bool(service.setup_error),'requires_python_or_node':False}
        except Exception as error:result={'ok':False,'error':str(error)[:300],'error_code':service.setup_error_code,'author_dir':str(service.root)}
        finally:service.close()
        args.self_check.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        return 0 if result['ok'] else 1
    ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
    ctypes.windll.kernel32.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
    mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\MoectPublisher.AuthorConsole'+('.GuiCheck' if args.gui_check else ''))
    if ctypes.windll.kernel32.GetLastError()==183:
        ctypes.windll.user32.FindWindowW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p]
        ctypes.windll.user32.FindWindowW.restype=ctypes.c_void_p
        existing=ctypes.windll.user32.FindWindowW(None,TITLE)
        if existing:
            ctypes.windll.user32.ShowWindow.argtypes=[ctypes.c_void_p,ctypes.c_int]
            ctypes.windll.user32.SetForegroundWindow.argtypes=[ctypes.c_void_p]
            ctypes.windll.user32.ShowWindow(existing,9);ctypes.windll.user32.SetForegroundWindow(existing)
        service.close();return 0
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        api=Api(service,verification=bool(args.gui_check))
        window=webview.create_window(TITLE+(' · 运行验证' if args.gui_check else ''),(UI/'publisher.html').as_uri(),js_api=api,width=1120,height=800,
            min_size=(1000,680),frameless=True,easy_drag=False,shadow=True,background_color=service.appearance()['background'])
        api._window=window;window.events.before_show+=api._install_frame
        def closing():
            if service.status()['job']['status']=='running':
                from System import Action
                if api._startup_host:window.native.Invoke(Action(api._startup_host.close_blocked))
                return False
            return True
        def closed():
            try:
                if api._startup_host:api._startup_host.close()
            finally:service.close()
        window.events.closing+=closing;window.events.closed+=closed
        def verify_gui():
            if not args.gui_check:return
            deadline=time.monotonic()+70
            injected=False;generation=-1
            try:
                while time.monotonic()<deadline:
                    status=service.status()
                    if args.gui_fault and not injected and api._startup.is_ready and status['job']['status']=='done':
                        from System import Action
                        generation=api._startup.generation;injected=True
                        def fault():
                            if args.gui_fault=='recreate':api._startup_host.must_recreate=True
                            api._startup.fail('verification_fault')
                        window.native.Invoke(Action(fault))
                        continue
                    if args.gui_fault and (not injected or api._startup.generation<=generation):
                        time.sleep(.1);continue
                    if (api._startup.is_ready and status['job']['status'] in ('done','failed')) or api._startup.failed:break
                    time.sleep(.1)
                result={'ok':api._startup.is_ready and status['job']['status']=='done' and not service.setup_error,'ui_ready':api._startup.is_ready,'ui_retries':api._startup.retries,'fault':args.gui_fault,'fault_injected':injected,'job_status':status['job']['status'],'error_code':service.setup_error_code,'diagnostic':service.setup_diagnostic}
                args.gui_check.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
            finally:window.destroy()
        # A private WebView deletes this fixed directory on close, racing the
        # browser process and the next launch. Keep a dedicated stable profile.
        webview.start(verify_gui,gui='edgechromium',private_mode=False,http_server=False,storage_path=str(service.root/('webview2-verification-v2' if args.gui_check else 'webview2-v2')))
    finally:
        ctypes.windll.kernel32.CloseHandle.argtypes=[ctypes.c_void_p]
        ctypes.windll.kernel32.CloseHandle(mutex)
    return 0


if __name__=='__main__':sys.exit(main())
