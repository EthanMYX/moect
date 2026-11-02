"""Render Moect's README artwork using the real UI and fictional data only.

Requires playwright (uses installed Edge); no live WeChat data or UI tests.
Run from any directory: python docs/tools/render_assets.py.
"""
import argparse
import base64
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
from core.version import VERSION  # noqa: E402
from core.themes import ACCENTS  # noqa: E402


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
    state['library'].update(demo=False,live=True)
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
    template=(ROOT/'ui/viewer.html').read_text(encoding='utf-8').replace('__DATE_RANGE_PICKER__',(ROOT/'ui/date-range-picker.js').read_text(encoding='utf-8'))
    (raw/'viewer.html').write_text(template.replace('__MANIFEST__',json.dumps(manifest,ensure_ascii=False)),encoding='utf-8')
    landscapes=[]
    schemes=[('#a8b6d6','#f0d7c3','#5b657d'),('#a7c1ba','#e9dfc4','#53736c'),('#b5add3','#ead4dc','#75628d'),
             ('#c9b2bc','#f4d2aa','#8c6a7b'),('#93afb4','#d7e1d1','#456a71'),('#9f9bc4','#e9c4bf','#655c8c'),
             ('#afc7be','#f0e4c9','#5d7b69'),('#b8bad4','#e7d4e0','#6f6b91'),('#9fb4ce','#efdabd','#566c87')]
    for i,(sky,sand,mountain) in enumerate(schemes):
        svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="440" height="440" viewBox="0 0 440 440"><defs><linearGradient id="s" x2="0" y2="1"><stop stop-color="{sky}"/><stop offset="1" stop-color="{sand}"/></linearGradient></defs><rect width="440" height="440" fill="url(#s)"/><circle cx="{290-i%3*50}" cy="{130+i%3*12}" r="37" fill="#fff2d9"/><path d="M0 280 100 190 230 285 340 175 440 265V440H0Z" fill="{mountain}" opacity=".65"/><path d="M0 345 125 250 265 350 440 245V440H0Z" fill="{mountain}"/><path d="M0 410Q180 310 440 390V440H0Z" fill="#35454b" opacity=".5"/></svg>'''
        (raw/f'landscape-{i}.svg').write_text(svg,encoding='utf-8')
        landscapes.append('data:image/svg+xml;base64,'+base64.b64encode(svg.encode()).decode())
    state['online']={'configured':False,'checking':False,'initial_check_done':True,'revision':0,'error':'','has_update':False,'unread_count':0,'announcements':[],'download':{'status':'idle'}}
    state['tasks']=[]
    moments={'available':True,'count':28,'unparsed':0,'selection':{'label':'我的朋友圈'},'authors':[{'uid':'demo_moect','name':'林间'}],
        'posts':[{'id':'synthetic-landscape','author':'demo_moect','author_name':'林间','create_time':1793521800,'image_count':9,'thumbnails':landscapes,'text':'周末的九个瞬间。\n把生活过慢一点，把喜欢的风景留下来。'},
                 {'id':'synthetic-coffee','author':'demo_moect','author_name':'林间','create_time':1793435400,'image_count':1,'thumbnails':landscapes[:1],'text':'散步、咖啡，还有一个不用赶时间的下午。'}]}
    stickers={'available':True,'total':276,'notice':'按收藏、自定义表情和已安装专辑分类，选好后即可保存到本地。',
        'groups':[{'id':str(i),'name':name,'count':count} for i,(name,count) in enumerate([('我收藏的表情',86),('自定义表情',42),('打工人的日常',36),('小猫营业中',48),('天气刚刚好',32),('快乐充电站',32)])]}
    collection={'category':'moments','name':'林间的朋友圈','owner':{'name':'林间','uid':'demo_moect'},'exported_at':'2026-11-02','notice':'把日常留在本地，随时离线翻阅。','resource_summary':{'available':9},
        'items':[{'id':'synthetic-landscape','author':'demo_moect','author_name':'林间','author_avatar':'avatar0.svg','create_time':1793521800,'time_str':'2026-11-01 16:30','text':'周末的九个瞬间。\n把喜欢的风景，好好留下来。',
                  'resources':[{'kind':'image','status':'available','path':f'landscape-{i}.svg'} for i in range(9)],
                  'likes':[{'uid':'demo_friend_'+str(i),'name':name,'avatar':f'avatar{i%2}.svg'} for i,name in enumerate(['陈一','小满','沈河','阿柚','周周'])],
                  'comments':[{'uid':'demo_chen','name':'陈一','avatar':'avatar1.svg','text':'这一组配色，好像周末的心情。'},{'uid':'demo_me','name':'林间','avatar':'avatar0.svg','reply_name':'陈一','text':'下次一起去走走吧。'}]}]}
    template=(ROOT/'ui/collection.html').read_text(encoding='utf-8').replace('__DATE_RANGE_PICKER__',(ROOT/'ui/date-range-picker.js').read_text(encoding='utf-8'))
    (raw/'moments-viewer.html').write_text(template.replace('__COLLECTION__',json.dumps(collection,ensure_ascii=False)),encoding='utf-8')
    return {'state':state,'sessions':sessions,'preview':preview,'moments':moments,'stickers':stickers}


def layout(kind):
    common='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
    @font-face{font-family:Harmony;src:url('/frontend/fonts/HarmonyOS_Sans_SC_Regular.ttf')}
    *{box-sizing:border-box}body{margin:0;font-family:Harmony,'Microsoft YaHei',sans-serif;color:#272238}
    .art{width:1600px;height:760px;overflow:hidden;position:relative;background:radial-gradient(ellipse at 85% 30%,#e3dbff 0,transparent 62%),radial-gradient(ellipse at 5% 100%,#e7e3fa,transparent 60%),#faf9fd;border:1px solid #e8e3f2;border-radius:28px}
    .art:before{content:'';position:absolute;inset:0;opacity:.19;pointer-events:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' opacity='.23' filter='url(%23n)'/%3E%3C/svg%3E")}
    .label{font-size:17px;letter-spacing:3px;color:#8a78bc;font-weight:600;text-transform:uppercase;margin-bottom:27px}.copy{position:absolute;left:88px;top:154px;width:590px}h1{margin:0;font-size:64px;line-height:1.27;letter-spacing:-2px;font-weight:800}h1 em{font-style:normal;color:#8971d2}p{font-size:23px;line-height:1.85;color:#80758d;max-width:510px;margin-top:28px}.window{position:absolute;background:white;border:1px solid #e9e5ee;border-radius:20px;box-shadow:0 20px 70px #5741791c;overflow:hidden}.window img{width:100%;display:block}.small{position:absolute;left:88px;bottom:45px;font-size:14px;color:#a095ae}.chip{display:inline-flex;align-items:center;border:1px solid #dcd2ee;border-radius:50px;padding:8px 17px;font-size:16px;color:#77628f;margin:0 7px 9px 0;background:#ffffff66}.chips{margin-top:28px;max-width:520px}
    </style>'''
    if kind=='banner':
        theme_dots=''.join(f'<i style="width:12px;height:12px;border-radius:50%;background:{row[2]};display:block"></i>' for row in ACCENTS)
        return common+f'''<div class="art" style="height:940px"><div style="position:absolute;left:85px;top:47px;display:flex;gap:14px;align-items:center;color:#827197;font-size:18px;letter-spacing:2px"><img src="/ui/icon.svg" width="43">微信记录 · 本地珍藏</div><div class="chip" style="position:absolute;right:70px;top:49px;font-size:16px;padding:7px 19px;color:#7956bd">Moect {VERSION}</div><div style="position:absolute;left:78px;top:117px;font-size:190px;line-height:1;font-weight:800;color:#ccbee9;letter-spacing:-9px">Moect</div><div style="position:absolute;left:785px;top:151px;font-size:36px;font-weight:600;line-height:1.5;color:#65517e">不止对话，<br>也把日常珍藏。</div><div style="position:absolute;left:787px;top:277px;display:flex;gap:15px;font-size:16px;color:#91819f"><span>会话</span><span>·</span><span>朋友圈</span><span>·</span><span>表情包</span></div><div style="position:absolute;left:88px;top:315px;display:flex;align-items:center;gap:10px;color:#8b7a9b;font-size:14px">{theme_dots}<span style="margin-left:5px">8 种主题色 · 离线归档</span></div><div class="window" style="left:118px;top:352px;width:1230px"><img src="/docs/images/raw/sessions.png"></div><div class="window" style="left:1092px;top:410px;width:430px;transform:rotate(2deg)"><img src="/docs/images/raw/moments-viewer.png"></div><div style="position:absolute;right:59px;bottom:27px;font-size:12px;color:#8b7b9c;background:#faf9fdeb;padding:5px 12px;border:1px solid #e8e0f2;border-radius:20px">界面与插画均为虚构演示</div></div>'''
    cards={
      'features-1':('01 / 朋友圈与表情包','把日常的碎片，<br><em>也收进回忆里。</em>','按账号与时间整理朋友圈，<br>把收藏的表情，按分类保存。','moments.png','九宫格与互动 · 动画表情 · 离线阅读'),
      'features-2':('02 / 本地离线归档','打开归档，<br><em>就回到那段对话。</em>','图片、表情与可直接播放的语音，<br>随可用资源一起保存在本地。','viewer.png','数字分页 · 时间筛选 · 合并转发'),
      'features-3':('03 / 为你的习惯而设','选好格式，<br><em>让记录各得其所。</em>','给回忆一份可阅读的 HTML，<br>也给整理和分析保留结构化数据。','export.png','Windows 一键安装 · 本机处理')}
    label,title,body,shot,caption=cards[kind]
    extra=''
    if kind=='features-1':
        extra='''<div class="window" style="left:972px;top:445px;width:570px;transform:rotate(1.5deg);border-radius:16px"><img src="/docs/images/raw/sticker-panel.png"></div>'''
    return common+f'''<div class="art"><div class="copy"><div class="label">{label}</div><h1 style="font-size:59px">{title}</h1><p>{body}</p><div class="chips"><span class="chip">{caption}</span></div></div><div class="window" style="left:720px;top:90px;width:1100px;transform:rotate(-1deg)"><img src="/docs/images/raw/{shot}"></div>{extra}<div class="small">Moect {VERSION} · 朋友圈使用本机缓存 · 界面为虚构演示数据</div></div>'''


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only',nargs='+',choices=['banner','features-1','features-2','features-3'],
                        default=['banner','features-1','features-2','features-3'])
    args=parser.parse_args()
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
            window.pywebview={api:{invoke:async(action,payload={})=>{
              let result={ok:true};
              if(action==='state')result=window.__docs.state;
              else if(action==='sessions')result=window.__docs.sessions;
              else if(action==='qce_preview')result=window.__docs.preview;
              else if(action==='tutorial_status')result={seen:true};
              else if(action==='startup_reconnect')result={skipped:true};
              else if(action==='online_status'||action==='online_check')result=window.__docs.state.online;
              else if(action==='account_assets')result=window.__docs[payload.kind];
              else if(action.startsWith('window_'))result={maximized:false};
              return {result:structuredClone(result)};
            }}};''')
            page.goto(base+'/ui-qce/index.html');page.wait_for_function('window.__ready===true')
            page.evaluate('document.fonts.ready');page.evaluate("window.__wce.setTab('sessions')")
            page.wait_for_timeout(400);page.screenshot(path=str(raw/'sessions.png'))
            page.evaluate("window.__wce.setTab('moments')")
            page.wait_for_selector('img[alt="朋友圈图片"]');page.wait_for_timeout(250)
            page.screenshot(path=str(raw/'moments.png'))
            page.evaluate("window.__wce.setTab('stickers')")
            page.get_by_text('我收藏的表情',exact=True).wait_for();page.wait_for_timeout(200)
            page.locator('.max-w-5xl').screenshot(path=str(raw/'sticker-panel.png'))
            if 'features-3' in args.only:
                page.evaluate("window.__wce.setTab('sessions')")
                page.evaluate("window.__wce.chooseItems(['demo_design@chatroom','demo_lin'])")
                page.wait_for_timeout(500);page.screenshot(path=str(raw/'export.png'))
            viewer=context.new_page();viewer.set_viewport_size({'width':1000,'height':1190})
            viewer.goto(base+'/docs/images/raw/viewer.html');viewer.wait_for_timeout(500)
            viewer.screenshot(path=str(raw/'viewer.png'))
            viewer.set_viewport_size({'width':900,'height':1340})
            viewer.goto(base+'/docs/images/raw/moments-viewer.html')
            viewer.wait_for_selector('.post .photo');viewer.wait_for_timeout(250)
            viewer.screenshot(path=str(raw/'moments-viewer.png'))
            art=context.new_page();art.set_viewport_size({'width':1600,'height':940})
            for name in args.only:
                (render/(name+'.html')).write_text(layout(name),encoding='utf-8')
                art.goto(base+'/docs/.render/'+name+'.html');art.evaluate('document.fonts.ready')
                art.wait_for_timeout(250);art.locator('.art').screenshot(path=str(images/(name+'.png')))
            browser.close()
    finally:server.shutdown();server.server_close()
    print(json.dumps({'artwork':['docs/images/'+name+'.png' for name in args.only],'version':VERSION,'data':'fictional only'}))


if __name__=='__main__':main()
