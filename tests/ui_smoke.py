"""Instrumented desktop UI smoke test. Uses only the fictional demo."""
import json
from PySide6.QtCore import QTimer


def run(window, directory, app):
    directory.mkdir(parents=True,exist_ok=True)
    window.service.config['export_dir']=str(directory/'exports')
    results=[]
    def capture(name):window.view.grab().save(str(directory/(name+'.png')))
    def fail(message):
        (directory/'ui-result.json').write_text(json.dumps({'ok':False,'error':message,'steps':results},ensure_ascii=False,indent=2),encoding='utf-8')
        app.exit(1)
    steps=[
        ('ready',"window.__ready===true",None),
        ('overview',"document.querySelector('#nav-overview')!==null && document.querySelector('[aria-label=最大化]')!==null",lambda:capture('01-overview')),
        ('maximize',"document.querySelector('[aria-label=最大化]').click();true",None),
        ('maximized',"document.querySelector('[aria-label=还原]')!==null",None),
        ('restore',"document.querySelector('[aria-label=还原]').click();true",None),
        ('open-sessions',"window.__wce.setTab('sessions');true",None),
        ('sessions-loaded',"[...document.querySelectorAll('button')].filter(b=>b.textContent.trim()==='导出').length===7",lambda:capture('02-sessions')),
        ('open-preview',"window.__wce.showPreview('demo_design@chatroom');true",None),
        ('preview-loaded',"document.body.textContent.includes('周末的天气看起来不错')",lambda:capture('03-message-preview')),
        ('close-preview',"window.__wce.closePreview();true",None),
        ('show-export',"window.__wce.chooseItems(['demo_design@chatroom','demo_lin']);true",None),
        ('export-dialog',"document.querySelector('[role=dialog]')?.textContent.includes('配置就绪')",lambda:capture('04-export-dialog')),
        ('create-export',"[...document.querySelectorAll('button')].find(b=>b.textContent==='开始批量导出').click();true",None),
        ('job-completed',"window.__wce.state.tasks.some(t=>t.kind==='export'&&t.status==='completed')",lambda:capture('05-tasks')),
        ('theme',"document.querySelector('[title=切换主题]').click();true",None),
        ('dark-mode',"document.documentElement.classList.contains('dark')",lambda:capture('06-dark')),
        ('about',"window.__wce.setTab('about');true",None),
        ('about-rendered',"document.body.textContent.includes('GPL-3.0')",lambda:capture('07-about')),
        ('perf-start',"window.__perf={samples:[],done:false};let prior;const f=t=>{if(prior)window.__perf.samples.push(t-prior);prior=t;if(window.__perf.samples.length<100)requestAnimationFrame(f);else window.__perf.done=true};requestAnimationFrame(f);true",None),
        ('perf-done',"window.__perf.done",None),
    ]
    index=0;tries=0
    def tick():
        nonlocal index,tries
        if index>=len(steps):
            def metrics(value):
                from core.window_chrome import corner_preference, user32, GWL_STYLE, WS_THICKFRAME, WS_CAPTION
                hwnd=int(window.winId())
                native={'corner_preference':corner_preference(hwnd),
                        'native_resize_frame':bool(user32.GetWindowLongPtrW(hwnd,GWL_STYLE)&WS_THICKFRAME),
                        'native_caption_capability':bool(user32.GetWindowLongPtrW(hwnd,GWL_STYLE)&WS_CAPTION)}
                okay=native['corner_preference']==2 and native['native_resize_frame'] and native['native_caption_capability']
                (directory/'ui-result.json').write_text(json.dumps({'ok':okay,'steps':results,'native_window':native,'render_metrics':json.loads(value) if isinstance(value,str) and value else value},ensure_ascii=False,indent=2),encoding='utf-8')
                window.service.shutdown();app.exit(0 if okay else 1)
            window.page.runJavaScript('JSON.stringify((()=>{const a=window.__perf.samples.sort((a,b)=>a-b);return {frames:a.length,p95_ms:a[Math.floor(a.length*.95)],max_ms:a[a.length-1],font:getComputedStyle(document.body).fontFamily}})())',metrics)
            return
        name,script,after=steps[index]
        def checked(value):
            nonlocal index,tries
            if value:
                results.append(name)
                if after:QTimer.singleShot(300,after)
                index+=1;tries=0;QTimer.singleShot(750,tick)
            else:
                tries+=1
                if tries>40:fail('timeout: '+name)
                else:QTimer.singleShot(500,tick)
        window.page.runJavaScript(script,checked)
    tick()
