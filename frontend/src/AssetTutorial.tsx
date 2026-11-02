import {useEffect,useRef,useState,type ReactNode} from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import {ArrowRight,BookOpen,Check,CheckCircle2,Download,FolderHeart,Image,Images,MessageCircle,RefreshCw,Smile,Sticker,X} from 'lucide-react'
import {WindowControls,WindowDragRegion} from '@/components/ui/window-controls'
import {Button} from '@/components/ui/button'
import {toast} from '@/components/ui/toast'
import {call} from './native'
import './asset-tutorial.css'

type Kind='moments'|'stickers'|'app'
const shownThisSession=new Set<Kind>()

/** Read first; acknowledge only when shown, so a cancelled React mount loses nothing. */
export function useAssetTutorial(kind:Kind,enabled=true){
  const [open,setOpen]=useState(false)
  const [checked,setChecked]=useState(false)
  useEffect(()=>{
    let stopped=false
    if(enabled&&shownThisSession.has(kind))setChecked(true)
    if(enabled&&!shownThisSession.has(kind))void call('tutorial_status',{kind}).then(result=>{
      if(stopped)return
      setChecked(true)
      if(!result.seen&&!shownThisSession.has(kind)){shownThisSession.add(kind);setOpen(true)}
    }).catch(()=>{if(!stopped)setChecked(true)})
    return()=>{stopped=true}
  },[kind,enabled])
  useEffect(()=>{
    if(!open)return
    shownThisSession.add(kind)
    void call('tutorial_seen',{kind}).catch(error=>toast.warning('教程显示记录未保存',{description:(error as Error).message}))
  },[open,kind])
  return {open,checked,show:()=>{shownThisSession.add(kind);setOpen(true)},close:()=>setOpen(false)}
}

function FlowArrow(){return <svg className="tutorial-flow-arrow" viewBox="0 0 48 40" aria-hidden="true"><path className="flow-path" d="M3 29C16 8 29 8 42 21"/><path d="m32 22 11 1-2-11"/></svg>}
function TinyLandscape({index=0}:{index?:number}){return <svg viewBox="0 0 90 74" className={'tiny-landscape landscape-'+index} aria-hidden="true"><rect width="90" height="74" rx="4"/><circle cx={index%2?25:66} cy="20" r="8"/><path d="M0 60 28 29 51 55 69 38 90 61V74H0Z"/></svg>}
function MockTitle({children}:{children:ReactNode}){return <div className="tutorial-mock-title"><span className="mock-dots"><i/><i/><i/></span><span>{children}</span></div>}

export function BrowseIllustration({kind}:{kind:Kind}){
  const sticker=kind==='stickers'
  return <div className="tutorial-illustration browse-illustration"><div className="tutorial-mock-window browse-window">
    <MockTitle><MessageCircle size={12}/>{sticker?'微信 · 表情':'微信 · 朋友圈'}</MockTitle>
    {sticker?<><div className="mock-tabs"><span className="chosen">收藏</span><span>表情专辑</span><span>＋</span></div><div className="mock-emojis">{['😊','✨','🐱','😎','🌷','🥳','🐼','💜','🍀'].map((emoji,index)=><span key={index}>{emoji}</span>)}</div></>:<><div className="mock-profile"><span className="mock-avatar"><Smile size={18}/></span><div><b>想保存的内容</b><div className="mock-text-line"/></div></div><div className="mock-photos">{Array.from({length:6},(_,i)=><TinyLandscape index={i} key={i}/>)}</div><div className="mock-range-tags"><span>目标日期</span><span>好友主页</span><span>我的朋友圈</span></div></>}
  </div><span className="illustration-note"><span className="note-spark">✦</span>先在微信里看一遍</span></div>
}

export function RefreshIllustration({kind}:{kind:Kind}){
  return <div className="tutorial-illustration refresh-illustration"><div className="tutorial-mock-window refresh-window">
    <MockTitle>Moect · {kind==='moments'?'朋友圈':'表情包'}</MockTitle>
    <div className="mock-refresh-row"><span className="mock-heading">{kind==='moments'?<Images size={16}/>:<Sticker size={16}/>}本地内容</span><span className="mock-refresh-target"><RefreshCw size={12}/>刷新资源快照</span></div>
    <div className="refresh-callout"><svg viewBox="0 0 86 33" aria-hidden="true"><path d="M3 27C28 33 59 23 76 3m-12 2 14-3-1 14"/></svg><span>回来点这里</span></div>
    <div className="mock-updated-list">{[0,1].map(i=><div key={i}><span className="mock-avatar small">{kind==='moments'?<Image size={13}/>:<Smile size={13}/>}</span><span className="mock-skeleton"><i/><i/></span><Check size={12}/></div>)}</div>
    <div className="mock-updated"><CheckCircle2 size={13}/>新的内容出现了</div>
  </div></div>
}

export function ExportIllustration({kind}:{kind:Kind}){
  const sticker=kind==='stickers'
  return <div className="tutorial-illustration export-illustration"><div className="tutorial-mock-window export-window">
    <MockTitle>选好范围，保存下来</MockTitle>
    {sticker?<div className="mock-categories">{['收藏的表情','喜欢的专辑','其他专辑'].map((name,i)=><div key={name} className={i<2?'selected':''}><span>{i<2&&<Check size={11}/>}</span><Smile size={14}/>{name}</div>)}</div>:<><div className="mock-tabs"><span className="chosen">我的</span><span>公共</span><span>指定账号</span></div><div className="mock-date"><span>▦</span>日期按需选择</div><div className="mock-result"><TinyLandscape index={2}/><span className="mock-skeleton"><i/><i/></span></div></>}
    <div className="mock-export-button"><Download size={13}/>{sticker?'导出所选分类':'导出所选朋友圈'}</div>
  </div><div className="mock-saved-file"><FolderHeart size={19}/><span>{sticker?'我的表情包':'朋友圈.html'}</span><CheckCircle2 size={14}/></div></div>
}

export function AssetTutorial({kind,open,onClose}:{kind:Exclude<Kind,'app'>;open:boolean;onClose:()=>void}){
  const title=useRef<HTMLHeadingElement>(null)
  const sticker=kind==='stickers',name=sticker?'表情包':'朋友圈'
  const steps=sticker?[
    ['先在微信打开表情','点开收藏，或想保存的表情专辑，让表情在电脑上显示出来。'],
    ['回到 Moect，刷新一下','点击右上角的“刷新资源快照”，把刚看过的表情整理进来。'],
    ['勾选分类，一键保存','选中想保存的分类，点击“导出所选分类”，不用一张张另存。'],
  ]:[
    ['先在微信找到内容','浏览到想保存的日期，或打开好友、自己的朋友圈。想保存的图片和视频也点开看看。'],
    ['回到 Moect，刷新一下','点击右上角的“刷新资源快照”，刚看过的内容就会出现在列表里。'],
    ['选好范围，一键导出','选择“我的”“公共”或“指定账号”，再点击导出。日期可以按需筛选。'],
  ]
  const finish=()=>{
    onClose()
    requestAnimationFrame(()=>{
      const target=document.getElementById(kind+'-refresh-resources')
      if(!target)return
      target.classList.remove('asset-tutorial-target');void target.offsetWidth;target.classList.add('asset-tutorial-target')
      setTimeout(()=>target.classList.remove('asset-tutorial-target'),2800)
    })
  }
  return <Dialog.Root open={open} onOpenChange={next=>{if(!next)onClose()}}><Dialog.Portal><Dialog.Content className="asset-tutorial" aria-describedby="asset-tutorial-description" onOpenAutoFocus={event=>{event.preventDefault();title.current?.focus()}}>
    <header className="tutorial-topbar"><span className="tutorial-brand"><img src="./icon.svg" alt=""/>Moect</span><span className="tutorial-header-divider"/><span className="tutorial-header-label"><BookOpen size={13}/>{name} · 新手教程</span><WindowDragRegion/><WindowControls/></header>
    <main className="tutorial-main"><div className="tutorial-hero"><span className="tutorial-kicker">从微信到 Moect <ArrowRight size={12}/></span><Dialog.Title ref={title} tabIndex={-1}>{name}，三步保存。</Dialog.Title><Dialog.Description id="asset-tutorial-description">{sticker?'先打开喜欢的表情，再回来按分类保存。':'先在微信看一遍，再回到这里整理、导出。'}</Dialog.Description><span className="tutorial-hero-count">01 <i/> 02 <i/> 03</span></div>
      <div className="tutorial-steps">{steps.map(([title,copy],index)=><section className="tutorial-step" key={title}><div className="tutorial-step-number"><span>0{index+1}</span>{index===0?'在微信':index===1?'在 Moect':'保存到电脑'}</div>{index===0?<BrowseIllustration kind={kind}/>:index===1?<RefreshIllustration kind={kind}/>:<ExportIllustration kind={kind}/>}<h2>{title}</h2><p>{copy}</p>{index<2&&<FlowArrow/>}</section>)}</div>
      <div className="tutorial-bottom-note"><CheckCircle2 size={15}/>{sticker?'少了某个表情？先在微信打开对应专辑，再回来刷新。':'少了某条内容？先在微信里打开它，再回来刷新。'}</div>
    </main>
    <footer className="tutorial-footer"><span><BookOpen size={14}/>以后想再看，点页面右上角的“新手教程”</span><div><Button variant="ghost" className="rounded-full" onClick={onClose}><X size={14} className="mr-1.5"/>关闭教程</Button><Button className="rounded-full px-6" onClick={finish}>知道了，开始使用<ArrowRight size={14} className="ml-2"/></Button></div></footer>
  </Dialog.Content></Dialog.Portal></Dialog.Root>
}
