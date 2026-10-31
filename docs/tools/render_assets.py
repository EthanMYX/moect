"""Render Moect's README artwork using the real UI and fictional data only.

Requires playwright (uses installed Edge); no live WeChat data or UI tests.
Run from any directory: python docs/tools/render_assets.py.
"""
import functools
import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.service import Service  # noqa: E402


def avatar(label,color):
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80">'
         f'<rect width="80" height="80" rx="40" fill="{color}"/>'
         f'<text x="40" y="51" text-anchor="middle" font-size="34" fill="white" '
         f'font-family="Microsoft YaHei">{label}</text></svg>')
    return 'data:image/svg+xml,'+quote(svg)


def fixtures(raw):
    with tempfile.TemporaryDirectory(prefix='moect-artwork-') as temporary:
        service=Service(ROOT/'ui',Path(temporary))
        state=service.demo()
        sessions=service.sessions()
        preview=service.qce_preview({'peer':{'peerUid':sessions[0]['username']},'limit':50})
        service.shutdown()
    colors=['#8373be','#779d8f','#c2947e','#a58bb1','#8e9dbe','#be9b68','#8f9aa3']
    for i,session in enumerate(sessions):
        session['avatar_url']=avatar(session['display'][0],colors[i%len(colors)])
    for i,name in enumerate(['周五放映室','咖啡与散步','周末菜市场','吉他练习室','灵感收集箱','旅行搭子','日常碎片']):
        sessions.append(dict(sessions[i],username=f'demo_more_{i}@chatroom',display=name,
            is_group=True,avatar_url=avatar(name[0],colors[(i+3)%len(colors)])))
    state['library']['name']='Moect 演示'
    state['library']['profile']={'name':'Moect 演示','wxid':'demo_moect','avatar_url':avatar('M','#8070c3')}
    state['export_dir']='文档 / Moect / exports'
    for m in preview['messages']:
        m['senderAvatar']=avatar((m['sendNickName'] or '我')[0],'#8373be' if not m['sendType'] else '#779d8f')
    # A composed, fictional archive for the documentation image. No export job.
    for i,(label,color) in enumerate([('林','#8373be'),('我','#779d8f')]):
        svg=avatar(label,color).split(',',1)[1]
        from urllib.parse import unquote
        (raw/f'avatar{i}.svg').write_text(unquote(svg),encoding='utf-8')
    (raw/'sunset.svg').write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="440" viewBox="0 0 800 440"><defs><linearGradient id="s" x2="0" y2="1"><stop stop-color="#7773b4"/><stop offset=".6" stop-color="#e8b4b9"/><stop offset="1" stop-color="#f5d0af"/></linearGradient></defs><rect width="800" height="440" fill="url(#s)"/><circle cx="550" cy="206" r="55" fill="#fff0c9"/><path d="M0 300 140 202 310 305 438 247 620 337 800 230V440H0Z" fill="#777d9c"/><path d="M0 370 175 293 340 374 550 282 800 360V440H0Z" fill="#4d526f"/><path d="M0 420 260 350 480 433 800 380V440H0Z" fill="#343851"/></svg>''',encoding='utf-8')
    rows=[]
    def message(sender,text,kind='text',extra=None,resources=None):
        i=len(rows);me=sender=='我'
        rows.append(dict(server_id=str(i+1),create_time=1793325600+i*60,
            time_str='2026-10-30 10:%02d:00'%(10+i),sender=sender,is_sender=me,
            avatar=f'avatar{1 if me else 0}.svg',kind=kind,text=text,extra=extra or {},resources=resources or []))
    message('林间','周末去山里走走吧，天气正好。')
    message('我','好呀，带上相机和热咖啡。')
    message('林间','',kind='image',resources=[dict(path='sunset.svg',kind='image',status='available',name='山间日落')])
    message('我','把这些小小的日常，好好留下来。')
    message('林间','路线也整理好啦。',kind='link',extra={'title':'周末山野计划','description':'两小时的步道，一场慢下来的旅行。','source_name':'旅行笔记','url':'https://example.com/journey'},resources=[dict(path='sunset.svg',kind='image',role='thumbnail',status='available',name='山间日落')])
    manifest={'name':'周末出走计划','demo':True,'count':len(rows),'exported_at':'2026-10-30',
        'chunks':[{'file':'sample.js','count':len(rows)}]}
    (raw/'sample.js').write_text('window.__wxChunk='+json.dumps(rows,ensure_ascii=False)+';',encoding='utf-8')
    (raw/'viewer.html').write_text((ROOT/'ui/viewer.html').read_text(encoding='utf-8').replace('__MANIFEST__',json.dumps(manifest,ensure_ascii=False)),encoding='utf-8')
    return {'state':state,'sessions':sessions,'preview':preview}


def layout(kind):
    common='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
    @font-face{font-family:Harmony;src:url('/frontend/fonts/HarmonyOS_Sans_SC_Regular.ttf')}
    *{box-sizing:border-box}body{margin:0;font-family:Harmony,'Microsoft YaHei',sans-serif;color:#272238}
    .art{width:1600px;height:760px;overflow:hidden;position:relative;background:radial-gradient(ellipse at 85% 30%,#e3dbff 0,transparent 62%),radial-gradient(ellipse at 5% 100%,#e7e3fa,transparent 60%),#faf9fd;border:1px solid #e8e3f2;border-radius:28px}
    .art:before{content:'';position:absolute;inset:0;opacity:.19;pointer-events:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' opacity='.23' filter='url(%23n)'/%3E%3C/svg%3E")}
    .label{font-size:17px;letter-spacing:3px;color:#8a78bc;font-weight:600;text-transform:uppercase;margin-bottom:27px}.copy{position:absolute;left:88px;top:154px;width:590px}h1{margin:0;font-size:64px;line-height:1.27;letter-spacing:-2px;font-weight:800}h1 em{font-style:normal;color:#8971d2}p{font-size:23px;line-height:1.85;color:#80758d;max-width:510px;margin-top:28px}.window{position:absolute;background:white;border:1px solid #e9e5ee;border-radius:20px;box-shadow:0 20px 70px #5741791c;overflow:hidden}.window img{width:100%;display:block}.small{position:absolute;left:88px;bottom:45px;font-size:14px;color:#a095ae}.chip{display:inline-flex;align-items:center;border:1px solid #dcd2ee;border-radius:50px;padding:8px 17px;font-size:16px;color:#77628f;margin:0 7px 9px 0;background:#ffffff66}.chips{margin-top:28px;max-width:520px}
    </style>'''
    if kind=='banner':
        return common+'''<div class="art" style="height:940px"><div style="position:absolute;left:85px;top:52px;display:flex;gap:15px;align-items:center;color:#827197;font-size:19px;letter-spacing:2px"><img src="/ui/icon.svg" width="45">微信聊天记录 · 本地归档</div><div style="position:absolute;left:78px;top:105px;font-size:196px;line-height:1;font-weight:800;color:#d8cdf2;letter-spacing:-9px">Moect</div><div style="position:absolute;left:785px;top:142px;font-size:36px;font-weight:600;line-height:1.5;color:#76628f">把对话留下，<br>把日常珍藏。</div><div class="window" style="left:172px;top:330px;width:1190px"><img src="/docs/images/raw/sessions.png"></div><div class="window" style="left:1070px;top:450px;width:440px;transform:rotate(2deg)"><img src="/docs/images/raw/viewer.png"></div><div style="position:absolute;right:48px;bottom:30px;font-size:14px;color:#a095ae">Moect 1.1.0 · 界面为虚构演示数据</div></div>'''
    cards={
      'features-1':('01 / 会话与批量导出','想留下哪段对话，<br><em>就从这里开始。</em>','好友、群聊，一眼找到。<br>点开即预览，也可以一次导出多个会话。','sessions.png','HTML / JSON / TXT / CSV / JSONL / Markdown'),
      'features-2':('02 / 本地离线归档','打开归档，<br><em>就回到那段对话。</em>','图片、表情、引用和分享卡片，<br>随可用资源一起保存到本地。','viewer.png','搜索消息 · 时间筛选 · 合并转发'),
      'features-3':('03 / 为你的习惯而设','选好格式，<br><em>让记录各得其所。</em>','给回忆一份可阅读的 HTML，<br>也给整理和分析保留结构化数据。','export.png','Windows 一键安装 · 本机处理')}
    label,title,body,shot,caption=cards[kind]
    return common+f'''<div class="art"><div class="copy"><div class="label">{label}</div><h1>{title}</h1><p>{body}</p><div class="chips"><span class="chip">{caption}</span></div></div><div class="window" style="left:720px;top:122px;width:1100px;transform:rotate(-1deg)"><img src="/docs/images/raw/{shot}"></div><div class="small">Moect · 界面为虚构演示数据</div></div>'''


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):pass


def main():
    images=ROOT/'docs/images';raw=images/'raw';raw.mkdir(parents=True,exist_ok=True)
    render=ROOT/'docs/.render';render.mkdir(exist_ok=True)
    fixture=fixtures(raw)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:'+str(server.server_port)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':1360,'height':900},device_scale_factor=1.5,locale='zh-CN')
            page=context.new_page()
            page.add_init_script('''window.__docs='''+json.dumps(fixture,ensure_ascii=False)+''';
            window.pywebview={api:{invoke:async(action,payload)=>({result:
              action==='state'?window.__docs.state:action==='sessions'?window.__docs.sessions:
              action==='qce_preview'?window.__docs.preview:action==='window_state'?{maximized:false}:{ok:true}})}};''')
            page.goto(base+'/ui-qce/index.html');page.wait_for_function('window.__ready===true')
            page.evaluate('document.fonts.ready');page.evaluate("window.__wce.setTab('sessions')")
            page.wait_for_timeout(700);page.screenshot(path=str(raw/'sessions.png'))
            page.evaluate("window.__wce.chooseItems(['demo_design@chatroom','demo_lin'])")
            page.wait_for_timeout(700);page.screenshot(path=str(raw/'export.png'))
            viewer=context.new_page();viewer.set_viewport_size({'width':1000,'height':1190})
            viewer.goto(base+'/docs/images/raw/viewer.html');viewer.wait_for_timeout(500)
            viewer.screenshot(path=str(raw/'viewer.png'))
            art=context.new_page();art.set_viewport_size({'width':1600,'height':940})
            for name in ['banner','features-1','features-2','features-3']:
                (render/(name+'.html')).write_text(layout(name),encoding='utf-8')
                art.goto(base+'/docs/.render/'+name+'.html');art.evaluate('document.fonts.ready')
                art.wait_for_timeout(250);art.locator('.art').screenshot(path=str(images/(name+'.png')))
            browser.close()
    finally:server.shutdown();server.server_close()
    print(json.dumps({'artwork':[str(p.relative_to(ROOT)) for p in images.glob('*.png')],'data':'fictional only'}))


if __name__=='__main__':main()
