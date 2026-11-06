import {memo,useEffect,useRef,useState} from 'react'
import ReactMarkdown,{type Components} from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {Bell,Upload,History,Settings,ArrowUpRight,ImagePlus,FileText,CheckCircle2,Cloud,ShieldCheck,FolderOpen,RefreshCw,ArrowRight,Download,ChevronRight,Minus,Square,X,Moon,Sun,Link,Heading2,Bold,Eye,PenLine,LoaderCircle,Send,Package,AlertCircle,ExternalLink,Undo2} from 'lucide-react'
import {call} from './native'
import {useWindowEdges} from './useWindowEdges'
import {PublisherHistory} from './PublisherHistory'

const empty={title:'',body:'',days:90,version:'',notes:'',installer:'',portable:'',tab:'announcement'}
const nav=[['announcement',Bell,'发布公告'],['release',Upload,'发布更新'],['history',History,'发布记录'],['settings',Settings,'设置与连接']] as const
const formatDate=(value:string)=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'—'

function PreviewImage({src,alt}:{src?:string;alt?:string}){
  const [image,setImage]=useState<{source:string;url:string}|null>(null)
  useEffect(()=>{let active=true;setImage(null);if(src)void call('publisher_preview_image',{source:src}).then(r=>{if(active&&r.url)setImage({source:src,url:r.url})}).catch(()=>{});return()=>{active=false}},[src])
  return image&&image.source===src?<img src={image.url} alt={alt||'公告配图'}/>:<span className="pub-image-empty"><ImagePlus size={18}/>{alt||'请通过“插入图片”添加本机图片'}</span>
}
// Polling and editor changes must not change React's image component type.
const previewComponents:Components={
  img:({src,alt})=><PreviewImage src={typeof src==='string'?src:''} alt={alt}/>,
  a:({href,children})=><button className="pub-text-link" onClick={()=>href&&void call('publisher_open_link',{url:href}).catch(()=>{})}>{children}<ArrowUpRight size={12}/></button>,
}
const previewPlugins=[remarkGfm]
const Markdown=memo(function Markdown({body}:{body:string}){
  return <div className="pub-markdown"><ReactMarkdown skipHtml remarkPlugins={previewPlugins} components={previewComponents}>{body}</ReactMarkdown></div>
})

export function PublisherApp(){
  useWindowEdges()
  const [state,setState]=useState<any>(null),[editor,setEditor]=useState<any>(empty),[tab,setTab]=useState('announcement'),[theme,setTheme]=useState('light'),[toast,setToast]=useState(''),[previewOnly,setPreviewOnly]=useState(false),[confirm,setConfirm]=useState<any>(null),[viewNotice,setViewNotice]=useState<any>(null)
  const initialized=useRef(false),mounted=useRef(true),textRef=useRef<HTMLTextAreaElement>(null),saveQueue=useRef<Promise<any>>(Promise.resolve()),lastCompleted=useRef(''),editorRef=useRef(editor)
  editorRef.current=editor
  const busy=state?.job?.status==='running',job=state?.job||{},connected=state?.connection?.status==='connected'
  const load=async()=>{const next=await call('publisher_state');if(!mounted.current)return;setState(next);if(!initialized.current){initialized.current=true;const saved={...empty,...next.editor};setEditor(saved);setTab(saved.tab||'announcement');setTheme(next.theme||'light');if(next.job?.status!=='running')void call('publisher_check').catch((e:Error)=>setToast(e.message))}}
  useEffect(()=>{mounted.current=true;void load().catch(e=>setToast(e.message));const timer=setInterval(()=>{void load().catch(()=>{})},1100);return()=>{mounted.current=false;clearInterval(timer)}},[])
  useEffect(()=>{document.documentElement.dataset.theme=theme},[theme])
  useEffect(()=>{if(!state)return;let painted=0;const frame=requestAnimationFrame(()=>{painted=requestAnimationFrame(()=>{window.__publisherBoot?.ready();void call('publisher_ui_ready',{generation:state.ui_generation}).catch(()=>{})})});return()=>{cancelAnimationFrame(frame);cancelAnimationFrame(painted)}},[!!state,state?.ui_generation])
  useEffect(()=>{const blocked=()=>setToast('正在处理发布任务，请等待完成后再退出。');window.addEventListener('publisher-close-blocked',blocked);return()=>window.removeEventListener('publisher-close-blocked',blocked)},[])
  useEffect(()=>{if(!initialized.current)return;const timer=setTimeout(()=>{const snapshot={...editorRef.current,tab};saveQueue.current=saveQueue.current.catch(()=>{}).then(()=>call('publisher_save_editor',snapshot)).catch((e:Error)=>setToast('草稿保存失败：'+e.message))},500);return()=>clearTimeout(timer)},[editor,tab])
  useEffect(()=>{if(job.status!=='done'&&job.status!=='failed')return;if(lastCompleted.current===job.id)return;lastCompleted.current=job.id;setToast(job.label||'已完成');void load()},[job.id,job.status])
  useEffect(()=>{if(!toast)return;const timer=setTimeout(()=>setToast(''),8500);return()=>clearTimeout(timer)},[toast])
  const update=(key:string,value:any)=>setEditor((old:any)=>({...old,[key]:value}))
  const execute=async(payload:any)=>{setConfirm(null);setToast('');try{setState(await call('publisher_start',payload))}catch(e:any){setToast(e.message)}}
  const check=async()=>{try{setState(await call('publisher_check'))}catch(e:any){setToast(e.message)}}
  const choose=async(kind:string)=>{
    try{
      const r=await call('publisher_choose',{kind})
      if(r.cancelled)return
      if(kind==='image')insert('\n\n'+r.markdown+'\n\n')
      else if(kind==='markdown'){
        if(tab==='release'&&/!\[/.test(r.body)){setToast('更新说明请使用文字与链接；配图可以另发公告。');return}
        update(tab==='release'?'notes':'body',r.body)
      }else update(kind,r.path)
    }catch(e:any){setToast(e.message)}
  }
  const insert=(text:string)=>{const field=tab==='release'?'notes':'body',target=textRef.current;const current=editorRef.current[field]||'',start=target?.selectionStart??current.length,end=target?.selectionEnd??start;update(field,current.slice(0,start)+text+current.slice(end));requestAnimationFrame(()=>{target?.focus();target?.setSelectionRange(start+text.length,start+text.length)})}
  const prepare=(kind:string)=>{
    if(kind==='announcement'&&(!editor.title.trim()||!editor.body.trim())){setToast('先写一个标题，再填写公告正文。');return}
    if(kind==='release'&&(!editor.version.trim()||(!editor.installer&&!editor.portable))){setToast('请填写真实版本号，并选择至少一个软件包。');return}
    setConfirm({kind,...editor})
  }
  const toggleTheme=async()=>{const next=theme==='light'?'dark':'light';setTheme(next);try{await call('publisher_theme',{theme:next})}catch(e:any){setToast(e.message)}}
  const pageTitle=nav.find(n=>n[0]===tab)?.[2]||'发布公告'
  const openLink=(url:string)=>void call('publisher_open_link',{url}).catch(e=>setToast(e.message))
  const closeModal=()=>{if(!busy){setConfirm(null);setViewNotice(null)}}
  const deleting=confirm?.kind?.startsWith('delete'),withdrawing=confirm?.kind?.startsWith('withdraw'),retrying=confirm?.kind==='retry_cleanup'
  const closeWindow=async()=>{if(busy){setToast('正在处理任务，请等待完成后再退出。');return}try{await call('publisher_save_editor',{...editorRef.current,tab});await call('window_close')}catch(e:any){setToast(e.message)}}
  useEffect(()=>{const key=(e:KeyboardEvent)=>{if(e.key==='Escape')closeModal();if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();void call('publisher_save_editor',{...editorRef.current,tab}).then(()=>setToast('草稿已保存到这台电脑'))}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)},[tab,busy])
  return <div className="pub-app">
    <header className="pub-titlebar" data-window-drag onPointerDown={e=>{if(e.button===0&&!window.__wceNativeRegions&&!(e.target as HTMLElement).closest('button'))void call('window_drag').catch(()=>{})}} onDoubleClick={e=>{if(!(e.target as HTMLElement).closest('button'))void call('window_maximize')}}>
      <div className="pub-window-brand"><img src="./icon.svg"/><span>Moect 发布中心</span><small>AUTHOR</small></div><div className="pub-window-controls"><button aria-label="最小化" onClick={()=>call('window_minimize')}><Minus size={15}/></button><button aria-label="最大化" onClick={()=>call('window_maximize')}><Square size={13}/></button><button className="pub-close" aria-label="关闭" onClick={closeWindow}><X size={17}/></button></div>
    </header>
    <div className="pub-shell"><aside className="pub-sidebar">
      <div className="pub-brand"><img src="./icon.svg"/><div><strong>Moect</strong><span>你的专属发布中心</span></div></div>
      <div className="pub-nav-label">内容与版本</div><nav>{nav.map(([id,Icon,label])=><button key={id} className={tab===id?'active':''} onClick={()=>{setTab(id);setPreviewOnly(false)}}><Icon size={18}/>{label}{tab===id&&<ChevronRight size={14}/>}</button>)}</nav>
      <div className="pub-sidebar-bottom"><div className="pub-private"><ShieldCheck size={18}/><div><strong>仅作者本机使用</strong><span>私钥留在你的电脑</span></div></div><button className="pub-side-link" onClick={()=>openLink('https://github.com/mofan6/Moect')}><ExternalLink size={15}/>Moect 项目主页</button><button className="pub-side-link" onClick={toggleTheme}>{theme==='light'?<Moon size={15}/>:<Sun size={15}/>}切换{theme==='light'?'深':'浅'}色外观</button><small className="pub-credit">Designed by MOFAN</small></div>
    </aside>
    <main className="pub-main"><div className="pub-pagebar"><span>发布中心 <ChevronRight size={13}/> <b>{pageTitle}</b></span><button className={'pub-connection '+(connected?'is-connected':'')} onClick={()=>setTab('settings')}><i/>{connected?'服务已连接':state?.connection?.status==='error'?'连接待检查':'正在准备连接'}</button></div>
      {state?.setup_error&&<div className="pub-alert" role="alert"><AlertCircle size={18}/><div className="pub-alert-content"><strong>{state.setup_error}</strong><small>作者资料目录：{state.author_dir||'未确定'}。EXE 不包含签名私钥，原作者资料会继续保留。</small></div><div className="pub-alert-actions"><button className="pub-button secondary" disabled={busy} onClick={check}><RefreshCw size={14} className={busy?'pub-spin':''}/>重新检测</button><button className="pub-button subtle" onClick={()=>call('publisher_open_storage').catch(e=>setToast(e.message))}><FolderOpen size={14}/>打开资料目录</button></div></div>}
      {(tab==='announcement'||tab==='release')&&<>
        <div className="pub-heading"><div><div className="pub-eyebrow">{tab==='announcement'?'LET YOUR USERS KNOW':'SHIP THE NEXT CHAPTER'}</div><h1>{tab==='announcement'?'好消息，从这里发出。':'让每一次更新，顺利抵达。'}</h1><p>{tab==='announcement'?'写下你想说的话，用户下次联网启动 Moect 时就能收到。':'选择真实的软件包，校验并发布。用户在 Moect 内完成升级。'}</p></div><div className="pub-heading-badge">{tab==='announcement'?<Bell size={25}/>:<Package size={26}/>}</div></div>
        <div className={'pub-workspace '+(previewOnly?'show-preview':'')}>
          <section className="pub-compose pub-panel"><div className="pub-panel-title"><PenLine size={16}/>{tab==='announcement'?'编辑公告':'准备更新'}<span>自动保存草稿</span><button className="pub-mobile-preview" onClick={()=>setPreviewOnly(true)}><Eye size={15}/>预览</button></div>
            <fieldset disabled={busy}>
            {tab==='announcement'?<><label className="pub-field"><span>公告标题 <small>一句话说清重点</small></span><input value={editor.title} maxLength={160} placeholder="例如：Moect 使用提醒与近期更新" onChange={e=>update('title',e.target.value)}/></label><label className="pub-field pub-expiry"><span>展示有效期</span><select value={editor.days} onChange={e=>update('days',Number(e.target.value))}>{[[7,'7天'],[30,'30天'],[90,'90天'],[180,'180天'],[365,'一年'],[0,'长期展示']].map(([v,t])=><option key={v} value={v}>{t}</option>)}</select><small>每条新公告独立记录已读状态</small></label></>:<><label className="pub-field"><span>新版本号 <small>与软件包真实版本一致</small></span><input value={editor.version} placeholder="例如 1.2.1" onChange={e=>update('version',e.target.value)}/></label><div className="pub-packages">{[['installer','安装版','EXE'],['portable','便携版','ZIP']].map(([id,label,ext])=><div className="pub-package" key={id}><span className="pub-file-icon"><Download size={17}/></span><div><strong>{label}<small>{ext}</small></strong><input aria-label={label+'路径'} placeholder="尚未选择 · 可只发布其中一种" value={editor[id]} onChange={e=>update(id,e.target.value)}/></div><button className="pub-button subtle" onClick={()=>choose(id)}><FolderOpen size={14}/>选择</button></div>)}</div></>}
            <div className="pub-body-label">{tab==='announcement'?'公告正文':'更新说明'}<small>支持 Markdown</small></div><div className="pub-editor-toolbar"><button title="二级标题" onClick={()=>insert('\n## 标题\n')}><Heading2 size={16}/></button><button title="加粗" onClick={()=>insert('**重点内容**')}><Bold size={15}/></button><button title="插入链接" onClick={()=>insert('[链接文字](https://github.com/mofan6/Moect)')}><Link size={15}/></button>{tab==='announcement'&&<button onClick={()=>choose('image')}><ImagePlus size={15}/><span>插入图片</span></button>}<button className="pub-import" onClick={()=>choose('markdown')}><FileText size={15}/><span>导入</span></button></div>
            <textarea ref={textRef} className="pub-body-input" spellCheck={false} maxLength={64000} value={tab==='announcement'?editor.body:editor.notes} placeholder={tab==='announcement'?'把想告诉用户的事写在这里…\n\n可以放使用提醒、相关链接，也可以插入图片。':'这次更新带来了哪些变化？\n\n- 新增的功能\n- 修复的问题\n- 需要用户注意的事项'} onChange={e=>update(tab==='announcement'?'body':'notes',e.target.value)}/>
            <div className="pub-editor-foot"><span>{(tab==='announcement'?editor.body:editor.notes).length.toLocaleString()} / 64,000</span><span>Ctrl + S 保存</span></div></fieldset>
          </section>
          <section className="pub-preview pub-panel"><div className="pub-panel-title"><Eye size={16}/>用户会看到什么<span>内容预览</span><button className="pub-mobile-preview" onClick={()=>setPreviewOnly(false)}><PenLine size={15}/>返回编辑</button></div><div className="pub-preview-scroll"><div className="pub-preview-hero"><span className="pub-preview-app"><img src="./icon.svg"/>Moect</span><span className="pub-preview-type">{tab==='announcement'?'一条新公告':'版本更新'}</span><h2>{tab==='announcement'?(editor.title||'你的公告标题'):(editor.version?'Moect '+editor.version:'下一次精彩更新')}</h2><span className="pub-preview-date">{new Date().toLocaleDateString('zh-CN')} · 官方发布</span></div><div className="pub-preview-body">{(tab==='announcement'?editor.body:editor.notes)?<Markdown body={tab==='announcement'?editor.body:editor.notes}/>:<div className="pub-empty-preview"><FileText size={30}/><strong>想说的话，会在这里呈现</strong><p>左侧开始编辑，右侧即时预览。<br/>正文、列表与配图都会跟随显示。</p></div>}</div><div className="pub-preview-note"><ShieldCheck size={16}/>{tab==='announcement'?'用户阅读两秒后可以确认，已读公告不再重复弹出。':'软件包通过签名清单、大小及摘要校验后才可安装。'}</div></div></section>
        </div>
        <footer className="pub-publishbar"><div><span className="pub-publish-state"><ShieldCheck size={16}/>签名发布 · R2 分发</span><small>{tab==='announcement'?'支持在线功能的 Moect，联网启动时自动收到。':'已发布的旧版需先安装一次带更新模块的新包。'}</small></div><div className="pub-actions">{tab==='release'&&<button className="pub-button secondary" disabled={busy||!!state?.setup_error} onClick={()=>execute({kind:'validate_release',...editor})}><CheckCircle2 size={16}/>检查软件包</button>}<button className="pub-button primary" disabled={busy||!!state?.setup_error} onClick={()=>prepare(tab)}>{busy?<LoaderCircle className="pub-spin" size={17}/>:tab==='announcement'?<Send size={17}/>:<Upload size={17}/>} {busy?'正在处理':tab==='announcement'?'发布公告':'发布更新'}{!busy&&<ArrowRight size={16}/>}</button></div></footer>
      </>}
      {tab==='history'&&<PublisherHistory state={state} busy={busy} onCheck={check} onAction={setConfirm} onPreview={setViewNotice} onInspect={async id=>{try{const entry=await call('publisher_inspect',{id});setViewNotice(entry.kind==='announcement'?entry.item:{title:entry.title,body:entry.item.notes,published_at:entry.item.published_at})}catch(e:any){setToast(e.message)}}}/>}
      {tab==='settings'&&<div className="pub-content-scroll"><div className="pub-heading"><div><div className="pub-eyebrow">READY WHEN YOU ARE</div><h1>一切就绪，再把好消息送出。</h1><p>此发布中心只管理 Moect 的公告与更新，沿用本机已有作者授权。</p></div></div><section className="pub-panel pub-settings-card"><div className="pub-settings-top"><span className="pub-setting-symbol"><Cloud size={24}/></span><div><h3>公告与更新服务</h3><p>{state?.connection?.message||'尚未检查连接'}</p></div><button className="pub-button primary" disabled={busy} onClick={check}><RefreshCw size={16} className={job.kind==='check'&&busy?'pub-spin':''}/>检测连接</button></div><dl><div><dt>分发地址</dt><dd>{state?.endpoint||'未配置'}</dd></div><div><dt>独立存储桶</dt><dd>{state?.bucket||'未配置'}<span className="pub-tag">Cloudflare R2</span></dd></div><div><dt>最近检查</dt><dd>{formatDate(state?.connection?.checked_at)}</dd></div><div><dt>签名公钥指纹</dt><dd className="pub-mono">{state?.key_fingerprint||'未配置'}</dd></div></dl></section><section className="pub-panel pub-settings-card"><div className="pub-settings-top"><span className="pub-setting-symbol"><ShieldCheck size={24}/></span><div><h3>本机作者资料</h3><p>草稿、发布记录和私有签名密钥保存在本机，不进入公开软件包。</p></div><button className="pub-button secondary" onClick={()=>call('publisher_open_storage').catch(e=>setToast(e.message))}><FolderOpen size={16}/>打开资料目录</button></div><p className="pub-settings-note">换电脑或清理文件前，请妥善备份 MoectPublisher 作者目录。丢失原签名私钥后，不能用新密钥直接替代。</p></section><section className="pub-panel pub-howto"><h3>从这里开始</h3>{[['01','发公告','填写标题与正文，插入配图，预览后点击发布。'],['02','发更新','填写真实版本号，选择新版安装包或便携包，检查后发布。'],['03','用户接收','支持在线模块的 Moect 下次联网启动时自动检查；旧版需先安装一次新包。']].map(([n,t,b])=><div key={n}><span>{n}</span><p><strong>{t}</strong>{b}</p></div>)}</section></div>}
      {busy&&<div className="pub-job-progress"><div><LoaderCircle size={15} className="pub-spin"/><span>{job.label}</span><b>{job.total?job.progress+'%':'请稍候'}</b></div><progress max={100} value={job.total?job.progress:undefined}/></div>}
    </main></div>
    {toast&&<div className={'pub-toast '+(job.status==='failed'?'error':'')} role="status"><span>{toast}</span><button aria-label="关闭提示" onClick={()=>setToast('')}><X size={14}/></button></div>}
    {(confirm||viewNotice)&&<div className="pub-modal-mask" onMouseDown={e=>{if(e.target===e.currentTarget)closeModal()}}><section className={'pub-modal '+(viewNotice?'pub-modal-notice':'')} role="dialog" aria-modal="true" aria-labelledby="publish-confirm-title"><button className="pub-modal-close" aria-label="关闭对话框" onClick={closeModal}><X size={19}/></button>{viewNotice?<><span className="pub-modal-symbol"><Bell size={24}/></span><h2 id="publish-confirm-title">{viewNotice.title}</h2><small>{formatDate(viewNotice.published_at)}</small><Markdown body={viewNotice.body}/><button className="pub-button secondary" onClick={closeModal}>关闭预览</button></>:<><span className="pub-modal-symbol">{(deleting||withdrawing)?<Undo2 size={24}/>:<Send size={24}/>}</span><h2 id="publish-confirm-title">{deleting?'确认永久删除这条内容？':withdrawing?'确认撤回这条内容？':retrying?'继续清理云端资源？':'准备好正式发布了吗？'}</h2><p>{deleting?'先停止分发，再删除保留内容和未被其他内容引用的云端资源。删除后无法从发布中心恢复；用户自行保存的副本和已安装版本会保留。':withdrawing?'停止展示公告或提供该更新，保留作者内容和云端资源。用户下次联网检查后生效。':retrying?'仅清理此前未完成的资源，仍被其他内容引用的文件会保留。':confirm.kind==='announcement'?'这条公告将在用户下次联网启动 Moect 时展示。':'软件包校验成功后上传，最后更新正式版本清单。'}</p><div className="pub-confirm-summary"><span>{confirm.kind==='release'?'新版本':'内容'}</span><strong>{confirm.kind==='release'?'Moect '+confirm.version:confirm.title}</strong>{confirm.kind==='announcement'&&<small>{confirm.days?confirm.days+'天有效':'长期展示'} · 支持 Markdown 与配图</small>}{confirm.kind==='release'&&<small>{[confirm.installer&&'安装版',confirm.portable&&'便携版'].filter(Boolean).join(' + ')}</small>}</div><div className="pub-modal-actions"><button className="pub-button secondary" autoFocus onClick={closeModal}>再检查一下</button><button className="pub-button primary" onClick={()=>execute(confirm)}>{deleting?'确认删除':withdrawing?'确认撤回':retrying?'开始清理':'确认发布'}<ArrowRight size={15}/></button></div></>}</section></div>}
  </div>
}
