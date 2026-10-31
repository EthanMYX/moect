// Ported from QCE qce-v4-tool/app/page.tsx TASKS and OVERVIEW rows (GPL-3.0).
import {FolderOpen,Download,Trash2,Square} from 'lucide-react'
import {Button} from '@/components/ui/button'
import {Badge} from '@/components/ui/badge'
import {Progress} from '@/components/ui/progress'

const active=(s:string)=>s==='running'||s==='queued'
const names:Record<string,string>={queued:'等待中',running:'进行中',completed:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断'}
const date=(s:any)=>s?new Date(typeof s==='number'?s*1000:s.replace(' ','T')).toLocaleDateString('zh-CN'):''

export function TaskRow({task:t,compact=false,onAction,onDelete}:{task:any,compact?:boolean,onAction:(action:string,id:string)=>void,onDelete:(task:any)=>void}){
 const summary=t.resource_summary,unavailable=(summary?.missing||0)+(summary?.encrypted||0)+(summary?.unsupported||0)+(summary?.corrupt||0)
 const badge=<Badge className={`text-[11px] px-1.5 py-0 rounded-full border-0 ${t.status==='completed'?'text-green-700 bg-green-50 dark:text-green-300 dark:bg-green-950/40':active(t.status)?'text-blue-700 bg-blue-50 dark:text-blue-300 dark:bg-blue-950/40':t.status==='failed'?'text-red-700 bg-red-50 dark:text-red-300 dark:bg-red-950/40':'text-zinc-700 bg-zinc-100 dark:text-zinc-300 dark:bg-zinc-800'}`}>{names[t.status]}</Badge>
 const metadata=<><span>{t.format?.toUpperCase()}</span><span>{date(t.created_at)}</span>{t.kind==='export'&&<span>{(t.count||0).toLocaleString()} {compact?'条':'条消息'}</span>}{!compact&&t.start_time&&<span className="font-medium">{date(t.start_time)} ~ {date(t.end_time)}</span>}{unavailable>0&&<span className="text-amber-700 dark:text-amber-400" title={`已导出 ${summary.available} 个资源，缺失 ${summary.missing} 个，加密 ${summary.encrypted} 个，格式不支持 ${summary.unsupported||0} 个，校验失败 ${summary.corrupt||0} 个`}>{unavailable} 个资源需处理</span>}</>
 return <div className={compact?'flex items-center justify-between px-4 py-3 hover:bg-black/[0.02] dark:hover:bg-white/[0.02] transition-colors':'flex items-center justify-between px-4 py-3.5 text-sm rounded-lg hover:bg-black/[0.03] dark:hover:bg-white/[0.03] transition-colors group'}>
  <div className={'min-w-0 flex-1'+(compact?' flex items-center gap-3':'')}>
   <div className="flex items-center gap-2 min-w-0"><span className="text-sm font-medium text-foreground truncate">{t.title}</span>{badge}{t.demo&&<Badge variant="secondary">演示</Badge>}</div>
   <div className={compact?'flex items-center gap-3 text-xs text-muted-foreground':'mt-0.5 flex flex-wrap items-center gap-3 text-xs text-muted-foreground/50'}>{metadata}</div>
   {active(t.status)&&<div className="mt-1.5 flex items-center gap-2"><Progress value={t.progress} className="h-1.5 rounded-full flex-1 max-w-[240px]"/><span className="text-xs font-medium text-muted-foreground/50 tabular-nums">{t.progress}%</span></div>}
   {(!compact&&(t.kind!=='export'||t.status==='failed'||active(t.status)))&&<div className={'mt-1.5 text-xs '+(t.status==='failed'?'text-red-600':'text-muted-foreground/50')}>{t.detail}</div>}
  </div>
  <div className="ml-3 flex items-center gap-1.5 flex-shrink-0">
   {active(t.status)&&<Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" title="停止" onClick={()=>onAction('cancel',t.id)}><Square className="w-4 h-4"/></Button>}
   {t.status==='completed'&&t.kind==='export'&&<><Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" title="打开文件位置" onClick={()=>onAction('open_task_folder',t.id)}><FolderOpen className="w-4 h-4"/></Button><Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0" title="打开导出文件" onClick={()=>onAction('open_export',t.id)}><Download className="w-4 h-4"/></Button></>}
   {!compact&&!active(t.status)&&<Button size="sm" variant="ghost" className="h-8 w-8 rounded-full p-0 text-muted-foreground/50 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30" title="删除记录" onClick={()=>onDelete(t)}><Trash2 className="w-4 h-4"/></Button>}
  </div>
 </div>
}
