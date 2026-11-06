// Ported from QCE qce-v4-tool/app/page.tsx TASKS and OVERVIEW rows (GPL-3.0).
import {FolderOpen,Download,Trash2,Square,FileSearch} from 'lucide-react'
import {formatBytes} from './formatBytes'
import {Button} from '@/components/ui/button'
import {Badge} from '@/components/ui/badge'
import {Progress} from '@/components/ui/progress'

const active=(s:string)=>s==='running'||s==='queued'
const names:Record<string,string>={queued:'等待中',running:'进行中',completed:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断'}
const date=(s:any)=>s?new Date(typeof s==='number'?s*1000:s.replace(' ','T')).toLocaleDateString('zh-CN'):''

export function TaskRow({task:t,compact=false,onAction,onDelete}:{task:any,compact?:boolean,onAction:(action:string,id:string)=>void,onDelete:(task:any)=>void}){
 const unit=t.category==='stickers'?'张表情':t.category==='moments'?'条朋友圈':compact?'条':'条消息'
 const summary=t.resource_summary,unavailable=(summary?.missing||0)+(summary?.encrypted||0)+(summary?.unsupported||0)+(summary?.corrupt||0)
 const badge=<Badge className={`text-[11px] px-1.5 py-0 rounded-full border-0 ${t.status==='completed'?'text-green-700 bg-green-50 dark:text-green-300 dark:bg-green-950/40':active(t.status)?'text-blue-700 bg-blue-50 dark:text-blue-300 dark:bg-blue-950/40':t.status==='failed'?'text-red-700 bg-red-50 dark:text-red-300 dark:bg-red-950/40':'text-zinc-700 bg-zinc-100 dark:text-zinc-300 dark:bg-zinc-800'}`}>{names[t.status]}</Badge>
 const metadata=<><span>{t.format==='stickers'?'表情包':t.format==='moments'?'朋友圈':t.format?.toUpperCase()}</span><span>{date(t.created_at)}</span>{t.kind==='export'&&<span>{(t.count||0).toLocaleString()} {unit}</span>}{!compact&&t.start_time&&<span className="font-medium">{date(t.start_time)} ~ {date(t.end_time)}</span>}{t.size_info&&<details className="relative"><summary className="cursor-pointer text-primary">{formatBytes(t.size_info.archive_bytes??t.size_info.bytes)}{t.encrypted?' · 加密 ZIP':t.compressed?' · ZIP':''}</summary><div className="absolute z-20 mt-2 min-w-64 rounded-xl border border-border bg-card p-3 text-xs shadow-lg space-y-1"><p>导出文件 {formatBytes(t.size_info.bytes)}</p>{t.size_info.archive_bytes!==undefined&&<p>压缩包 {formatBytes(t.size_info.archive_bytes)}</p>}{Object.entries(t.size_info.resources||{}).map(([kind,bytes])=><p key={kind}>{({image:'图片 / 表情',video:'视频',audio:'语音',file:'文件',original:'原始资源'} as any)[kind]||kind} {formatBytes(Number(bytes))}</p>)}<p className="pt-1 text-muted-foreground">当前账号源数据库总量 {formatBytes(t.size_info.source_db_bytes)}</p><p className="text-muted-foreground">源数据库包含其他会话，导出体积仅对应本次选定内容。</p></div></details>}{summary?.skipped>0&&<span title="按导出设置主动跳过，未计为资源错误">已跳过 {summary.skipped} 项资源</span>}{unavailable>0&&<span className="text-amber-700 dark:text-amber-400" title={`已导出 ${summary.available} 个资源，缺失 ${summary.missing} 个，加密 ${summary.encrypted} 个，格式不支持 ${summary.unsupported||0} 个，校验失败 ${summary.corrupt||0} 个`}>{unavailable} 个资源需处理</span>}</>
 return <div className={compact?'flex items-center justify-between px-4 py-3 hover:bg-black/[0.02] dark:hover:bg-white/[0.02] transition-colors':'flex items-center justify-between px-4 py-3.5 text-sm rounded-lg hover:bg-black/[0.03] dark:hover:bg-white/[0.03] transition-colors group'}>
  <div className={'min-w-0 flex-1'+(compact?' flex items-center gap-3':'')}>
   <div className="flex items-center gap-2 min-w-0"><span className="text-sm font-medium text-foreground truncate">{t.title}</span>{badge}{t.demo&&<Badge variant="secondary">演示</Badge>}</div>
   <div className={compact?'flex items-center gap-3 text-xs text-muted-foreground':'mt-0.5 flex flex-wrap items-center gap-3 text-xs text-muted-foreground/50'}>{metadata}</div>
   {active(t.status)&&<div className="mt-1.5 flex items-center gap-2"><Progress value={t.progress} className="h-1.5 rounded-full flex-1 max-w-[240px]"/><span className="text-xs font-medium text-muted-foreground/50 tabular-nums">{t.progress}%</span></div>}
   {(!compact&&(t.kind!=='export'||t.status==='failed'||active(t.status)))&&<div className={'mt-1.5 text-xs '+(t.status==='failed'?'text-red-600':'text-muted-foreground/50')}>{t.detail}</div>}
  </div>
  <div className="ml-3 flex items-center gap-1.5 flex-shrink-0">
   {t.status==='failed'&&<Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" title="导出此任务的诊断信息" onClick={()=>onAction('choose_diagnostics',t.id)}><FileSearch className="w-4 h-4"/></Button>}
   {active(t.status)&&<Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" title="停止" onClick={()=>onAction('cancel',t.id)}><Square className="w-4 h-4"/></Button>}
   {t.status==='completed'&&t.kind==='export'&&<><Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" title="打开文件位置" onClick={()=>onAction('open_task_folder',t.id)}><FolderOpen className="w-4 h-4"/></Button><Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" title="打开导出文件" onClick={()=>onAction('open_export',t.id)}><Download className="w-4 h-4"/></Button></>}
   {!compact&&!active(t.status)&&<Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0 text-muted-foreground/50 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30" title="删除记录" onClick={()=>onDelete(t)}><Trash2 className="w-4 h-4"/></Button>}
  </div>
 </div>
}
