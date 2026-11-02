import {useEffect,useRef,useState} from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import {AnimatePresence,motion,useReducedMotion} from 'framer-motion'
import {ArrowLeft,ArrowRight,Check,CheckCircle2,Download,FolderHeart,Images,LockKeyhole,MessageCircle,Monitor,Plug,RefreshCw,ShieldCheck,Sparkles,Sticker} from 'lucide-react'
import {WindowControls,WindowDragRegion} from '@/components/ui/window-controls'
import {BrowseIllustration,ExportIllustration} from './AssetTutorial'
import './app-tutorial.css'

const pages=[
  {label:'你好，Moect',title:<>把聊天与回忆，<br/><em>好好留在身边。</em></>,copy:'会话、朋友圈、表情包。把想留下的内容，整理成自己电脑里的归档。',note:'几步上手，慢慢收藏。'},
  {label:'01 / 连接微信',title:<>先登录微信，<br/><em>再连接 Moect。</em></>,copy:'在电脑上打开并登录微信，回到这里点击“连接微信”。等整理完成，就能浏览会话。',note:'整理的是本机数据；下次启动会尝试更新已连接的账号。'},
  {label:'02 / 保存会话',title:<>选中一个对话，<br/><em>把它保存下来。</em></>,copy:'在“会话”中点开预览，点击导出。按需选择时间与媒体，常用的 HTML 格式用浏览器就能看。',note:'视频太多？导出时可以跳过图片或视频，节省空间。'},
  {label:'03 / 更多回忆',title:<>微信里先看一遍，<br/><em>回来刷新、导出。</em></>,copy:'朋友圈和表情包依赖本机缓存。先在微信打开想保存的内容，再点“刷新资源快照”，选好范围后导出。',note:'Moect 不会替你操作微信；没缓存的内容可能无法保存。'},
  {label:'准备好了',title:<>回忆属于你，<br/><em>归档也在你手里。</em></>,copy:'导出完成后，在“任务”里打开文件夹。分享 HTML 时，请把它所在的整个文件夹一起带上，图片和视频才不会丢。',note:'原始聊天不会被修改。请妥善保存包含私人信息的归档。'},
]

function Scene({page}:{page:number}){
  if(page===0)return <div className="welcome-orbit"><span className="orbit-ring ring-one"/><span className="orbit-ring ring-two"/><div className="orbit-logo"><img src="./icon.svg" alt="Moect"/></div><span className="orbit-item orbit-chat"><MessageCircle/><span>每一句话</span></span><span className="orbit-item orbit-image"><Images/><span>每个瞬间</span></span><span className="orbit-item orbit-sticker"><Sticker/><span>每份可爱</span></span><span className="orbit-star star-one">✦</span><span className="orbit-star star-two">✧</span></div>
  if(page===1)return <div className="onboarding-connect"><div className="connect-app wechat-app"><MessageCircle size={44}/><b>电脑微信</b><span><CheckCircle2 size={13}/>已登录</span></div><div className="connect-direction"><i/><i/><i/><ArrowRight size={20}/></div><div className="connect-app moect-app"><img src="./icon.svg" alt=""/><b>Moect</b><span><Plug size={13}/>连接微信</span></div><div className="connect-summary"><RefreshCw size={17}/><span>读取本机内容 <ArrowRight size={13}/> 整理归档 <ArrowRight size={13}/> 准备就绪</span></div></div>
  if(page===2)return <div className="onboarding-chat"><div className="onboarding-mockbar"><span/><span/><span/><b>Moect · 会话预览</b></div><div className="onboarding-bubble"><i>😊</i><span>今天也有值得记住的小事。</span></div><div className="onboarding-bubble outgoing"><span>那就好好保存下来 ✨</span></div><div className="onboarding-export"><span><Check size={13}/> HTML</span><span><Check size={13}/> 自选时间</span><strong><Download size={15}/>导出聊天记录</strong></div><div className="onboarding-floating"><FolderHeart size={20}/><span>回忆，已保存。</span><CheckCircle2 size={15}/></div></div>
  if(page===3)return <div className="onboarding-assets"><div><BrowseIllustration kind="moments"/><span>① 在微信打开</span></div><ArrowRight className="assets-arrow"/><div><ExportIllustration kind="moments"/><span>② 刷新后保存</span></div></div>
  return <div className="onboarding-archive"><div className="archive-folder"><FolderHeart size={92} strokeWidth={1}/><span>我的回忆</span></div><div className="archive-files"><span><Monitor size={17}/>index.html<Check size={14}/></span><span><Images size={17}/>图片与视频<Check size={14}/></span><span><MessageCircle size={17}/>聊天内容<Check size={14}/></span></div><span className="archive-local"><ShieldCheck size={16}/>保存在你的电脑里</span></div>
}

export function AppTutorial({open,onClose}:{open:boolean;onClose:()=>void}){
  const [page,setPage]=useState(0),[direction,setDirection]=useState(1),title=useRef<HTMLHeadingElement>(null)
  const scene=useRef<HTMLDivElement>(null)
  const reduced=useReducedMotion(),current=pages[page]
  useEffect(()=>{if(open){setPage(0);setDirection(1)}},[open])
  const go=(next:number)=>{if(next<0||next>=pages.length)return;setDirection(next>page?1:-1);setPage(next)}
  useEffect(()=>{if(open)title.current?.focus()},[open])
  useEffect(()=>{if(!open)return;const element=scene.current;if(!element)return;const resize=()=>element.style.setProperty('--scene-scale',String(Math.max(.7,Math.min(element.clientWidth/420,element.clientHeight/380,1.65))));const observer=new ResizeObserver(resize);observer.observe(element);resize();return()=>observer.disconnect()},[open,page])
  return <Dialog.Root open={open} onOpenChange={next=>{if(!next)onClose()}}><Dialog.Portal><Dialog.Content className="app-onboarding" aria-describedby="onboarding-copy" onPointerDownOutside={event=>event.preventDefault()} onInteractOutside={event=>event.preventDefault()} onOpenAutoFocus={e=>{e.preventDefault();title.current?.focus()}}>
    <header className="onboarding-topbar"><span className="onboarding-brand"><img src="./icon.svg" alt=""/>Moect <small>初次见面</small></span><WindowDragRegion/><WindowControls/></header>
    <main className="onboarding-stage"><div className="onboarding-decoration"><div className="onboarding-ambient ambient-one"/><div className="onboarding-ambient ambient-two"/><span className="onboarding-watermark">MOECT</span></div><AnimatePresence initial={false} mode="wait" custom={direction}><motion.div key={page} className="onboarding-slide" custom={direction} onAnimationComplete={()=>title.current?.focus({preventScroll:true})} initial={reduced?{opacity:0}:{opacity:0,x:direction*36}} animate={{opacity:1,x:0}} exit={reduced?{opacity:0}:{opacity:0,x:-direction*28}} transition={{duration:reduced ? .05 : .28,ease:'easeOut'}}>
      <section className="onboarding-text"><span className="onboarding-kicker"><Sparkles size={13}/>{current.label}</span><Dialog.Title ref={title} tabIndex={-1}>{current.title}</Dialog.Title><Dialog.Description id="onboarding-copy">{current.copy}</Dialog.Description><div className="onboarding-note"><LockKeyhole size={14}/><span>{current.note}</span></div></section><div ref={scene} className="onboarding-scene" aria-hidden="true"><div className="onboarding-scene-inner"><Scene page={page}/></div></div><div className="onboarding-takeaways">{(page===1?['打开电脑微信并登录','点击连接微信','整理完成后浏览会话']:page===2?['点开对话预览','按需选择日期和媒体','保存为离线 HTML']:page===3?['先在微信手动打开','回到这里刷新资源','选择范围后导出']:page===4?['在任务里找到归档','带上完整导出文件夹','妥善保存私人回忆']:['会话 · 每一句话','朋友圈 · 每个瞬间','表情包 · 每份可爱']).map((copy,i)=><div key={copy}><span>0{i+1}</span>{copy}<CheckCircle2 size={15}/></div>)}</div>
    </motion.div></AnimatePresence></main>
    <footer className="onboarding-footer"><div className="onboarding-progress" aria-label="教程页码">{pages.map((p,i)=><button type="button" key={i} aria-label={`第 ${i+1} 页：${p.label}`} aria-current={i===page?'step':undefined} onClick={()=>go(i)}><span/>{i===page&&<small>{String(i+1).padStart(2,'0')} / 05</small>}</button>)}</div><div className="onboarding-actions"><button type="button" className="onboarding-skip" onClick={onClose}>稍后再看</button><button type="button" className="onboarding-prev" disabled={page===0} onClick={()=>go(page-1)} aria-label="上一页"><ArrowLeft size={17}/></button><button type="button" className="onboarding-next" onClick={()=>page===4?onClose():go(page+1)}>{page===4?'开始使用':'下一页'}<ArrowRight size={17}/></button></div></footer>
  </Dialog.Content></Dialog.Portal></Dialog.Root>
}
