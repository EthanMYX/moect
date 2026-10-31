"""Moect desktop shell. Local UI + allowlisted native bridge."""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal as pyqtSignal, Slot as pyqtSlot, QTimer, QEvent
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEnginePage, QWebEngineSettings, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from core.service import Service
from core.version import PROJECT_URL
from core.window_chrome import configure_frame, native_message

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
UI = BASE/'ui-qce'


class LocalOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl()
        allowed = url.scheme() in ('qrc','data','about')
        if url.isLocalFile():
            try:
                Path(url.toLocalFile()).resolve().relative_to(UI.resolve())
                allowed = True
            except ValueError:
                allowed = False
        info.block(not allowed)


class Page(QWebEnginePage):
    def acceptNavigationRequest(self, url, kind, main):
        return url.isLocalFile() and Path(url.toLocalFile()).resolve() == (UI/'index.html').resolve()

    def javaScriptConsoleMessage(self, level, message, line, source):
        # Page content may contain private records. Never log it automatically.
        if os.environ.get('WCE_DEV') == '1':
            print('UI:', level, message, line, flush=True)


class Bridge(QObject):
    response = pyqtSignal(str)
    windowState = pyqtSignal(bool)
    def __init__(self, service, parent):
        super().__init__(parent)
        self.service = service
        self.window = parent
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='ui-requests')
        self.avatar_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix='avatar-fetch')

    def send(self, request_id, result=None, error=None):
        self.response.emit(json.dumps({'id':request_id,'result':result,'error':error}, ensure_ascii=False))

    @pyqtSlot(str)
    def request(self, raw):
        request_id = ''
        try:
            if len(raw) > 100000: raise ValueError('请求过大')
            data=json.loads(raw); request_id=str(data['id'])[:80]
            action=data['action']; payload=data.get('payload') or {}
            if not isinstance(payload,dict): raise ValueError('请求无效')
            if action.startswith('window_'):
                if action=='window_drag':self.window.windowHandle().startSystemMove()
                elif action=='window_minimize':self.window.showMinimized()
                elif action=='window_maximize':
                    self.window.showNormal() if self.window.isMaximized() else self.window.showMaximized()
                elif action=='window_close':self.window.close()
                elif action!='window_state':raise ValueError('不支持的窗口操作')
                self.send(request_id,{'maximized':self.window.isMaximized()});return
            if action in ('choose_archive','choose_output','choose_storage'):
                title={'choose_archive':'选择已解密备份','choose_output':'选择导出位置','choose_storage':'选择微信账号数据目录'}[action]
                folder=QFileDialog.getExistingDirectory(self.window,title)
                if not folder:
                    self.send(request_id, {'cancelled':True}); return
                if action=='choose_output':
                    self.service.config['export_dir']=folder; self.service.save()
                    self.send(request_id,self.service.state()); return
                action, payload=('import_path',{'path':folder}) if action=='choose_archive' else ('storage_path',{'path':folder})
            if action in ('open_export','open_task_folder','open_output'):
                if action=='open_output':
                    target=Path(self.service.config['export_dir']); target.mkdir(parents=True,exist_ok=True)
                else:
                    target=self.service.task_folder(payload.get('id'))
                    if action=='open_export': target=self.service.task_file(payload.get('id'))
                if os.name=='nt':os.startfile(str(target))
                elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):raise ValueError('无法打开文件位置')
                self.send(request_id,{'ok':True}); return
            if action=='source':
                urls={'wechat':'https://github.com/LC044/WeChatMsg',
                      'wx4':'https://github.com/chenanhan230-del/WeChatMsg-4x',
                      'project':PROJECT_URL,'qce':PROJECT_URL}
                if payload.get('name') in urls: QDesktopServices.openUrl(QUrl(urls[payload['name']]))
                self.send(request_id,{'ok':True}); return
            def work(rid=request_id, a=action, p=payload):
                try:
                    if a=='import_path': result=self.service.import_archive(p['path'])
                    elif a=='storage_path': result=self.service.add_storage(p['path'])
                    else: result=self.service.call(a,p)
                    self.send(rid,result)
                except Exception as exc:
                    self.send(rid,error=str(exc)[:300] or '操作失败')
            (self.avatar_pool if action=='avatar' else self.pool).submit(work)
        except Exception as exc:
            self.send(request_id,error=str(exc)[:200])


class Window(QMainWindow):
    def __init__(self, service):
        super().__init__()
        self.service=service
        self.setWindowFlags(Qt.Window|Qt.FramelessWindowHint)
        self.setWindowTitle('Moect · 聊天记录归档')
        self.setWindowIcon(QIcon(str(UI/'icon.svg')))
        self.resize(1360,900); self.setMinimumSize(1080,720)
        self.view=QWebEngineView(self)
        self.page=Page(self.view)
        self.view.setPage(self.page)
        self.interceptor=LocalOnly(self)
        self.page.profile().setUrlRequestInterceptor(self.interceptor)
        self.page.profile().setHttpCacheType(QWebEngineProfile.NoCache)
        self.page.profile().setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        # Avatars resolve through the native bridge. Enabling remote access on
        # file pages breaks module/qrc script loading in Qt WebEngine 6.12.
        self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls,False)
        self.page.settings().setFontFamily(QWebEngineSettings.SansSerifFont,'Microsoft YaHei')
        self.page.settings().setFontFamily(QWebEngineSettings.StandardFont,'Microsoft YaHei')
        self.page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows,False)
        self.channel=QWebChannel(self.page)
        self.bridge=Bridge(service,self)
        self.channel.registerObject('native',self.bridge)
        self.page.setWebChannel(self.channel)
        self.setCentralWidget(self.view)
        self.view.load(QUrl.fromLocalFile(str(UI/'index.html')))

    def showEvent(self,event):
        super().showEvent(event)
        configure_frame(int(self.winId()))

    def changeEvent(self,event):
        if event.type()==QEvent.WindowStateChange and hasattr(self,'bridge'):
            self.bridge.windowState.emit(self.isMaximized())
        super().changeEvent(event)

    def nativeEvent(self,event_type,message):
        result=native_message(message,self)
        if result is not None:return result
        return super().nativeEvent(event_type,message)

    def closeEvent(self,event):
        active=any(t['status'] in ('running','queued') for t in self.service.config['tasks'])
        if active and QMessageBox.question(self,'退出软件','仍有任务正在处理。退出会取消这些任务，是否退出？',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            event.ignore(); return
        self.service.shutdown()
        self.bridge.pool.shutdown(wait=False,cancel_futures=True)
        self.bridge.avatar_pool.shutdown(wait=False,cancel_futures=True)
        event.accept()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--data-dir')
    parser.add_argument('--smoke',help='Synthetic UI test output directory')
    args=parser.parse_args()
    app=QApplication(sys.argv[:1])
    app.setApplicationName('Moect'); app.setOrganizationName('Moect')
    service=Service(BASE/'ui',root=args.data_dir)
    if args.demo: service.demo()
    window=Window(service); window.show()
    if args.smoke:
        from tests.ui_smoke import run
        QTimer.singleShot(2000,lambda:run(window,Path(args.smoke),app))
    return app.exec()


if __name__=='__main__':
    sys.exit(main())
