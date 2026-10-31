"""Exercise synthetic contact avatars, rich exports and native task actions."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from app import Window
from core.service import Service
from tests.test_resources import media_fixture,ASSETS,SESSION


def main():
    out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);lib=media_fixture(out/'fixture')
    svc=Service(ASSETS,out/'state');svc.library=lib
    svc.config['export_dir']=str(out/'exports')
    window=Window(svc);window.show()
    viewer=QWebEngineView();viewer.resize(1050,850)
    results=[];opened=[];job=None;index=0;tries=0
    patcher=patch('app.os.startfile',side_effect=lambda target:opened.append(str(target)));patcher.start()
    def save(name):window.view.grab().save(str(out/(name+'.png')))
    def start_export():
        nonlocal job
        job=svc.export({'sessions':[SESSION],'format':'html'})['job']
    def load_viewer():
        viewer.load(QUrl.fromLocalFile(str(svc.task_file(job))));viewer.show()
    steps=[
        ('ready',window,lambda:'window.__ready===true',None),
        ('profile-avatar',window,lambda:"document.body.textContent.includes('合成昵称')&&document.body.textContent.includes('synthetic_alias')&&document.querySelectorAll('img').length>=2&&[...document.querySelectorAll('img')].filter(i=>i.src.startsWith('data:image/png')&&i.naturalWidth>0).length>=2",lambda:save('01-profile')),
        ('sessions',window,lambda:"window.__wce.setTab('sessions');true",None),
        ('session-avatar',window,lambda:"[...document.querySelectorAll('img')].some(i=>i.src.startsWith('data:image/png')&&i.naturalWidth>0)",lambda:save('02-sessions')),
        ('export',window,lambda:'true',start_export),
        ('complete',window,lambda:"window.__wce.state.tasks.some(t=>t.kind==='export'&&t.status==='completed')",lambda:(window.page.runJavaScript("window.__wce.setTab('tasks')"),save('03-task'))),
        ('task-actions',window,lambda:"document.querySelector('[title=打开文件位置]').click();document.querySelector('[title=打开导出文件]').click();true",None),
        ('file-actions-verified',window,lambda:'true',lambda:verify_opened()),
        ('load-offline',window,lambda:'true',load_viewer),
        ('offline-rich',viewer,lambda:"document.querySelectorAll('.avatar img').length>=6&&document.querySelectorAll('img.attachment').length===1&&document.querySelector('img.attachment').naturalWidth>0&&document.querySelector('video.attachment')!==null&&[...document.querySelectorAll('a')].some(a=>a.href==='https://example.com/mini')&&document.body.textContent.includes('pages/demo?id=1')&&document.body.textContent.includes('本机未找到此附件')",lambda:viewer.grab().save(str(out/'04-offline.png'))),
        ('delete-record',window,lambda:"document.querySelector('[title=删除记录]').click();true",None),
        ('confirm-delete',window,lambda:"[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='删除记录').click();true",None),
        ('deleted',window,lambda:"window.__wce.state.tasks.length===0",None),
    ]
    def verify_opened():
        if len(opened)!=2 or not any(Path(p).is_dir() for p in opened) or not any(Path(p).suffix=='.html' for p in opened):raise AssertionError('Native file/folder targets failed')
    def finish(ok,error=None):
        patcher.stop()
        (out/'rich-result.json').write_text(json.dumps({'ok':ok,'steps':results,'error':error},ensure_ascii=False,indent=2),encoding='utf-8')
        svc.shutdown();viewer.close();window.close();app.exit(0 if ok else 1)
    def tick():
        nonlocal index,tries
        if index==len(steps):finish(True);return
        name,target,script,after=steps[index]
        def checked(value):
            nonlocal index,tries
            if value:
                try:
                    if after:after()
                except Exception as exc:finish(False,str(exc));return
                results.append(name);index+=1;tries=0
            else:tries+=1
            if tries>50:finish(False,'timeout: '+name)
            else:QTimer.singleShot(400,tick)
        page=target.page if target is window else target.page()
        page.runJavaScript(script(),checked)
    QTimer.singleShot(2000,tick)
    return app.exec()


if __name__=='__main__':sys.exit(main())
