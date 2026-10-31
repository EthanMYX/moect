"""Full synthetic avatar/resource/native-action checks on the shipping host."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch
import webview
import edge_app
from core.service import Service
from tests.test_resources import media_fixture,ASSETS,SESSION
import tests.edge_smoke


def run(window,api,out):
    svc=api._service;results=[];opened=[];viewer=None
    def evaluate(target,script):return target.gui.evaluate_js('JSON.stringify(('+script+'))',target.uid,True)
    def check(name,target,script):
        end=time.monotonic()+15
        while time.monotonic()<end:
            if evaluate(target,script):results.append(name);return
            time.sleep(.2)
        raise AssertionError('timeout: '+name)
    try:
        check('ready',window,'window.__ready===true')
        check('profile-and-avatars',window,"document.body.textContent.includes('合成昵称')&&document.body.textContent.includes('synthetic_alias')&&[...document.images].filter(i=>i.src.startsWith('data:image/png')&&i.naturalWidth>0).length>=2")
        evaluate(window,"(window.__wce.setTab('sessions'),true)")
        check('session-avatar',window,"[...document.images].some(i=>i.src.startsWith('data:image/png')&&i.naturalWidth>0)")
        job=svc.export({'sessions':[SESSION],'format':'html'})['job']
        check('export-complete',window,"window.__wce.state.tasks.some(t=>t.status==='completed')")
        path=svc.task_file(job);evaluate(window,"(window.__wce.setTab('tasks'),true)")
        check('task-ui',window,"document.body.textContent.includes('测试群')&&!!document.querySelector('[title=删除记录]')")
        with patch('edge_app.os.startfile',side_effect=lambda p:opened.append(p)):
            evaluate(window,"(document.querySelector('[title=打开文件位置]').click(),document.querySelector('[title=打开导出文件]').click(),true)")
            end=time.monotonic()+5
            while len(opened)<2 and time.monotonic()<end:time.sleep(.1)
        assert any(Path(p).is_dir() for p in opened) and str(path) in opened
        results.append('native-file-and-folder')
        viewer=webview.create_window('Synthetic offline export',path.as_uri(),width=1050,height=850)
        assert viewer.events._pywebviewready.wait(20)
        check('offline-chunks',viewer,"document.querySelectorAll('.row').length===8")
        evaluate(viewer,"([...document.images].forEach(i=>i.loading='eager'),true)")
        check('offline-rich-assets',viewer,"document.querySelectorAll('.avatar img').length===8&&document.querySelector('img.attachment')?.naturalWidth>0&&!!document.querySelector('video.attachment')&&[...document.querySelectorAll('a')].some(a=>a.href==='https://example.com/mini')&&document.querySelector('#messages').textContent.includes('pages/demo?id=1')")
        evaluate(window,"(document.querySelector('[title=删除记录]').click(),true)")
        check('delete-confirmation',window,"[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='删除记录')")
        evaluate(window,"([...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='删除记录').click(),true)")
        check('deleted-record',window,"window.__wce.state.tasks.length===0")
        assert path.exists()
        results.append('export-preserved-after-record-delete')
        data={'ok':True,'steps':results}
    except Exception as exc:data={'ok':False,'steps':results,'error':str(exc)}
    (out/'rich-result.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    if viewer:viewer.destroy()
    window.destroy()


def main():
    out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
    lib=media_fixture(out/'fixture');svc=Service(ASSETS,out/'state')
    svc.library=lib;svc.config['export_dir']=str(out/'exports')
    edge_app.Service=lambda *_:svc
    tests.edge_smoke.run=run
    sys.argv=['edge_app.py','--data-dir',str(out/'state'),'--smoke',str(out)]
    edge_app.main()
    return 0 if json.loads((out/'rich-result.json').read_text(encoding='utf-8'))['ok'] else 1


if __name__=='__main__':sys.exit(main())
