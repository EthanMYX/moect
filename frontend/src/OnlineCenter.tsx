import {memo,useCallback,useEffect,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import ReactMarkdown,{type Components} from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {Bell,Check,Download,ExternalLink,Megaphone,RefreshCw,X} from 'lucide-react'
import {Dialog,DialogContent,DialogTitle} from '@/components/ui/dialog'
import {Button} from '@/components/ui/button'
import {Progress} from '@/components/ui/progress'
import {toast} from '@/components/ui/toast'
import {call} from './native'
import './online.css'

function OnlineImage({src,alt}:{src?:string;alt?:string}){
  const [image,setImage]=useState<{source:string;url:string}|null>(null)
  useEffect(()=>{let cancelled=false;setImage(null);if(src)void call('online_image',{url:src}).then(result=>{if(!cancelled&&result.url)setImage({source:src,url:result.url})}).catch(()=>{});return()=>{cancelled=true}},[src])
  return image&&image.source===src?<img src={image.url} alt={alt||'公告配图'} loading="lazy"/>:<span className="online-image-placeholder">{alt||'图片暂未载入'}</span>
}
// Renderer identity must survive parent renders. Inline component functions
// remount images on every 100 ms read-timer tick and each status refresh.
const markdownComponents:Components={
  a:({href,children})=><button type="button" role="link" className="online-link" onClick={()=>{if(href)void call('online_open_link',{url:href}).catch(error=>toast.error('无法打开链接',{description:error.message}))}}>{children}<ExternalLink size={12}/></button>,
  img:({src,alt})=><OnlineImage src={typeof src==='string'?src:''} alt={alt}/>,
  table:({children})=><div className="online-table"><table>{children}</table></div>,
}
const markdownPlugins=[remarkGfm]
export const OnlineMarkdown=memo(function OnlineMarkdown({body}:{body:string}){
  return <div className="online-markdown"><ReactMarkdown skipHtml remarkPlugins={markdownPlugins} components={markdownComponents}>{body}</ReactMarkdown></div>
})

export function OnlineCenter({summary,blocked,sidebar}:{summary:any;blocked:boolean;sidebar:boolean}){
  const [data,setData]=useState<any>(null),[mode,setMode]=useState<'notices'|'update'|null>(null),[panel,setPanel]=useState<'notices'|'update'>('notices'),[selected,setSelected]=useState(''),[remaining,setRemaining]=useState(2),[saving,setSaving]=useState(false),[host,setHost]=useState<HTMLElement|null>(null)
  const shown=useRef(new Set<string>()),focusQueue=useRef<Promise<any>>(Promise.resolve()),openRef=useRef(mode),blockedRef=useRef(blocked),dataRef=useRef<any>(null)
  openRef.current=mode;blockedRef.current=blocked;dataRef.current=data
  const load=useCallback(async()=>{const next=await call('online_status');setData(next);return next},[])
  useEffect(()=>{void load().catch(()=>{});void call('online_check',{startup:true}).catch(()=>{})},[load])
  useEffect(()=>{void load().catch(()=>{})},[load,summary?.revision,summary?.checking,summary?.error,summary?.download?.status,summary?.download?.progress,summary?.download?.active,summary?.initial_check_done])
  useEffect(()=>{
    const check=()=>{
      const target=document.getElementById('sidebar-online');setHost(old=>old===target?old:target)
      if(openRef.current||blockedRef.current||document.querySelector('[role="dialog"][data-state="open"],dialog[open]'))return
      if(!dataRef.current?.initial_check_done||dataRef.current?.checking||dataRef.current?.error)return
      const unread=dataRef.current?.announcements?.find((n:any)=>!n.read&&!shown.current.has(n.id))
      if(unread){shown.current.add(unread.id);openRef.current='notices';setSelected(unread.id);setPanel('notices');setMode('notices')}
    }
    const observer=new MutationObserver(check);observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['data-state','open']});check()
    return()=>observer.disconnect()
  },[blocked,data,sidebar])
  const notices=data?.announcements||[],notice=notices.find((n:any)=>n.id===selected),release=data?.release,download=data?.download||summary?.download||{},unread=data?.unread_count??summary?.unread_count??0
  const dismiss=()=>{if(mode==='notices')notices.forEach((n:any)=>shown.current.add(n.id));setMode(null)}
  useEffect(()=>{if(mode==='notices'&&selected&&data?.initial_check_done&&!data?.checking&&!data?.error&&!notices.some((n:any)=>n.id===selected)){setMode(null);setSelected('')}},[mode,selected,data])
  useEffect(()=>{
    if(mode!=='notices'||!notice||notice.read){setRemaining(0);return}
    let stopped=false,available=2,started=0,isActive=false
    const sync=()=>{
      const active=document.visibilityState==='visible'&&document.hasFocus();isActive=false
      focusQueue.current=focusQueue.current.catch(()=>{}).then(()=>call('notice_focus',{id:notice.id,active})).then(result=>{if(stopped)return;available=result.remaining;started=performance.now();isActive=active;setRemaining(available)}).catch(()=>{if(!stopped)setRemaining(2)})
    }
    setRemaining(2);sync();window.addEventListener('focus',sync);window.addEventListener('blur',sync);document.addEventListener('visibilitychange',sync)
    const timer=setInterval(()=>{if(!stopped&&isActive)setRemaining(Math.max(0,available-(performance.now()-started)/1000))},100)
    return()=>{stopped=true;clearInterval(timer);window.removeEventListener('focus',sync);window.removeEventListener('blur',sync);document.removeEventListener('visibilitychange',sync);focusQueue.current=focusQueue.current.catch(()=>{}).then(()=>call('notice_focus',{id:notice.id,active:false})).catch(()=>{})}
  },[mode,notice?.id,notice?.read])
  const show=(next:'notices'|'update')=>{setPanel(next);setMode(next);if(next==='notices'){const first=notices.find((n:any)=>!n.read)||notices[0];setSelected(first?.id||'');if(first)shown.current.add(first.id)}void call('online_check').catch(()=>{})}
  const read=async()=>{
    if(!notice)return
    if(notice.read){dismiss();return}
    setSaving(true)
    try{await focusQueue.current;const next=await call('notice_read',{id:notice.id});setData(next);const following=next.announcements.find((n:any)=>!n.read);if(following){shown.current.add(following.id);setSelected(following.id)}else setMode(null)}catch(error){toast.error('未能保存阅读状态',{description:(error as Error).message})}finally{setSaving(false)}
  }
  const check=async()=>{try{await call('online_check');await load()}catch(error){toast.error('检查未完成',{description:(error as Error).message})}}
  const downloadUpdate=async()=>{try{await call('update_download');await load()}catch(error){toast.error('暂时无法更新',{description:(error as Error).message})}}
  const apply=async()=>{setSaving(true);try{await call('update_apply')}catch(error){toast.error('暂时无法安装更新',{description:(error as Error).message});setSaving(false)}}
  const hasUpdate=data?.has_update??summary?.has_update
  const controls=<div className="online-shortcuts"><button type="button" className={'online-update-shortcut '+(hasUpdate?'available':'')} title={hasUpdate?'发现新版本，点击更新':'检查更新'} aria-label={hasUpdate?'发现新版本，点击更新':'检查更新'} onClick={()=>show('update')}><Download size={16}/>{hasUpdate&&<i className="online-update-dot" aria-hidden="true"/>}</button><button type="button" className="online-notice-shortcut" title={unread?`${unread} 条未读公告`:'公告'} aria-label="公告" onClick={()=>show('notices')}><Megaphone size={16}/>{unread>0&&<i/>}</button></div>
  // Keep the chosen content during Radix's closing animation. A closed notice
  // must not turn into update details just because mode has become null.
  return <>{host&&createPortal(controls,host)}<Dialog open={mode!==null} onOpenChange={open=>{if(!open)dismiss()}}><DialogContent className={panel==='notices'?'online-dialog notice-dialog':'online-dialog update-dialog'} aria-describedby="online-description">
    <header className="online-dialog-header"><span className="online-header-icon">{panel==='notices'?<Megaphone size={20}/>:<Download size={20}/>}</span><div><DialogTitle className="text-base font-semibold">{panel==='notices'?'Moect 公告':'软件更新'}</DialogTitle><p id="online-description">{panel==='notices'?'来自 Moect 的消息与使用提醒':'获取新功能和修复，保留你的本地归档'}</p></div><button type="button" aria-label="关闭" onClick={dismiss}><X size={17}/></button></header>
    {panel==='notices'?<>
      <div className={'online-notices '+(notices.length>1?'multiple':'')}>{notices.length>1&&<nav aria-label="公告列表">{notices.map((n:any)=><button type="button" key={n.id} className={n.id===selected?'selected':''} onClick={()=>{setSelected(n.id);shown.current.add(n.id)}}><span>{!n.read&&<i/>}{n.title}</span><small>{new Date(n.published_at).toLocaleDateString('zh-CN')}</small></button>)}</nav>}<article>{notice?<><div className="online-notice-meta"><span>{notice.read?'已阅读':'未读公告'}</span><time>{new Date(notice.published_at).toLocaleString('zh-CN')}</time></div><h2>{notice.title}</h2><OnlineMarkdown body={notice.body}/></>:<div className="online-empty"><Bell size={34}/><strong>{data?.configured?(data?.error?'暂时无法获取公告':'暂无公告'):'公告服务正在准备中'}</strong><p>{data?.error||'有新的消息时，会在这里通知你。'}</p></div>}</article></div>
      <footer className="online-dialog-footer"><span>{notice&&!notice.read?(remaining>0?'阅读两秒后可确认':'感谢阅读'):'已读记录仅保存在这台电脑'}</span><div><Button variant="ghost" className="rounded-full" onClick={check} disabled={data?.checking}><RefreshCw size={14} className={data?.checking?'animate-spin mr-1.5':'mr-1.5'}/>刷新</Button>{notice&&<Button className="rounded-full px-5" onClick={read} disabled={saving||(!notice.read&&remaining>0)}>{remaining>0&&!notice.read?`知道了（${Math.ceil(remaining)}秒）`:notice.read?'关闭':'知道了'}{remaining<=0&&<Check size={14} className="ml-1.5"/>}</Button>}</div></footer>
    </>:<><div className="online-update-body"><div className={'online-version-icon '+(hasUpdate?'has-update':'')}><Download size={31}/></div><h2>{hasUpdate?`发现新版本 ${data?.latest_version||summary?.latest_version}`:data?.checking?'正在检查新版本…':data?.error?'暂时无法检查更新':data?.configured?(data?.checked_at?(data.latest_version?'已是最新版本':'暂无可用更新'):'检查软件更新'):'更新服务正在准备中'}</h2><p className="online-version-copy">{hasUpdate?'新功能和修复已就绪，更新后继续使用原有归档。':data?.error||'联网后会自动检查，也可以点击下方按钮手动检查。'}</p>{release&&<div className="online-release-notes"><OnlineMarkdown body={release.notes||'本次更新带来体验改进与问题修复。'}/></div>}{download.status==='downloading'&&<div className="online-download-progress"><Progress value={download.progress}/><p>{download.progress}%<span>{(download.received/1024/1024).toFixed(1)} / {(download.total/1024/1024).toFixed(1)} MB</span></p></div>}{['failed','revoked'].includes(download.status)&&<p className="online-update-error">{download.error}</p>}{download.status==='ready'&&<p className="online-download-ready"><Check size={14}/>更新包已下载并通过校验</p>}{data?.install_mode==='source'&&hasUpdate&&<p className="online-version-copy">当前从源码启动；安装版和便携版支持更新并重启。</p>}</div><footer className="online-dialog-footer"><span>软件更新会保留配置、任务和聊天归档</span><div><Button variant="ghost" className="rounded-full" onClick={check} disabled={data?.checking||download.active||download.status==='downloading'}><RefreshCw size={14} className={data?.checking?'animate-spin mr-1.5':'mr-1.5'}/>检查更新</Button>{hasUpdate&&(download.status==='ready'?<Button className="rounded-full" onClick={apply} disabled={saving||data?.install_mode==='source'}>更新并重启</Button>:<Button className="rounded-full" onClick={downloadUpdate} disabled={download.active||download.status==='downloading'}><Download size={14} className="mr-1.5"/>{download.active&&download.status==='revoked'?'正在停止下载':download.status==='downloading'?'正在下载':'下载更新'}</Button>)}</div></footer></>}
  </DialogContent></Dialog></>
}
