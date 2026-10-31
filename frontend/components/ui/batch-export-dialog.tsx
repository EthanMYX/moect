"use client"

import { useState, useEffect, useRef } from "react"
import { call } from "@/src/native"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { DateRangePicker } from "@/components/ui/date-range-picker"
import { CheckCircle2, XCircle, Users, User, FolderOpen, HelpCircle } from "lucide-react"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip"
import { Loader } from "@/components/ui/loader"
import { ScrollArea } from "@/components/ui/scroll-area"
import { toggleSkipResourceType, type SkipDownloadResourceType } from "@/lib/skip-resource-types"
import { EXPORT_OPTION_TOOLTIPS } from "@/lib/export-option-tooltips"

const PILL_INPUT =
  "h-[36px] px-3.5 rounded-full border-0 bg-black/[0.04] dark:bg-white/[0.06] text-[13px] outline-none placeholder:text-muted-foreground/70 focus:bg-black/[0.06] dark:focus:bg-white/[0.09] transition-colors"
const PILL_TEXTAREA =
  "px-3.5 py-2.5 rounded-[18px] border-0 bg-black/[0.04] dark:bg-white/[0.06] text-[13px] outline-none placeholder:text-muted-foreground/70 focus:bg-black/[0.06] dark:focus:bg-white/[0.09] transition-colors"
const SECTION_TITLE = "text-[14px] font-medium text-foreground mb-5"

export interface BatchExportItem {
  type: 'group' | 'friend'
  id: string
  name: string
  chatType: number
  peerUid: string
  peerUin?: string
  avatarUrl?: string
}

export type ExportProgressCallback = (
  index: number,
  status: 'success' | 'failed',
  error?: string
) => void

interface BatchExportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  items: BatchExportItem[]
  onExport: (config: BatchExportConfig, onProgress?: ExportProgressCallback) => Promise<void>
}

export interface BatchExportConfig {
  format: 'HTML' | 'TXT' | 'JSON' | 'CSV' | 'JSONL' | 'MD'
  timeRange: 'all' | 'recent' | 'custom'
  customStartDate?: string
  customEndDate?: string
  includeSystemMessages: boolean
  quickExport: boolean
  includeAvatars: boolean
  skipDownloadResourceTypes?: SkipDownloadResourceType[]
  outputDir: string
  keywords: string
}

export interface BatchExportProgress {
  current: number
  total: number
  currentItem: string
  status: 'idle' | 'running' | 'completed' | 'failed'
  results: Array<{
    name: string
    status: 'success' | 'failed' | 'pending'
    error?: string
  }>
}


function ExportSwitch({id,title,description,checked,disabled,onChange}:{id:string,title:string,description:string,checked:boolean,disabled?:boolean,onChange:(value:boolean)=>void}) {
  return <div className="flex items-center justify-between gap-6 px-5 py-4"><div className="min-w-0"><label htmlFor={id} className="block text-[13px] font-medium cursor-pointer">{title}</label><p id={id+'-description'} className="text-[12px] text-muted-foreground leading-relaxed mt-1">{description}</p></div><Switch id={id} aria-describedby={id+'-description'} checked={checked} disabled={disabled} onCheckedChange={onChange}/></div>
}

export function BatchExportDialog({ open, onOpenChange, items, onExport }: BatchExportDialogProps) {
  const didInitRef = useRef(false)
  const [format, setFormat] = useState<'HTML' | 'TXT' | 'JSON' | 'CSV' | 'JSONL' | 'MD'>('HTML')
  const [timeRange, setTimeRange] = useState<'all' | 'recent' | 'custom'>('all')
  const [customStartDate, setCustomStartDate] = useState('')
  const [customEndDate, setCustomEndDate] = useState('')
  const [dateError, setDateError] = useState<string | null>(null)
  const [isExporting, setIsExporting] = useState(false)
  
  const [includeSystemMessages, setIncludeSystemMessages] = useState(true)
  const [quickExport, setQuickExport] = useState(false)
  const [includeAvatars, setIncludeAvatars] = useState(true)
  const [skipDownloadResourceTypes, setSkipDownloadResourceTypes] = useState<SkipDownloadResourceType[] | undefined>(undefined)
  const [outputDir, setOutputDir] = useState('')
  const [keywords, setKeywords] = useState('')
  // Issue #134: 友好文件名格式
  
  const [progress, setProgress] = useState<BatchExportProgress>({
    current: 0,
    total: 0,
    currentItem: '',
    status: 'idle',
    results: []
  })

  // 对话框打开时重置所有状态
  useEffect(() => {
    if (didInitRef.current) return
    if (open) {
      setFormat('HTML')
      setTimeRange('all')
      setCustomStartDate('')
      setCustomEndDate('')
      setDateError(null)
      setIsExporting(false)
      setIncludeSystemMessages(true)
      setQuickExport(false)
      setIncludeAvatars(true)
      setSkipDownloadResourceTypes(undefined)
      setOutputDir('')
      setKeywords('')
      setProgress({
        current: 0,
        total: items.length,
        currentItem: '',
        status: 'idle',
        results: items.map(item => ({ name: item.name, status: 'pending' }))
      })
      didInitRef.current = true
    }
  }, [open, items])

  useEffect(() => {
    if (!open) {
      didInitRef.current = false
    }
  }, [open])



  useEffect(() => {
    if (timeRange !== 'custom') {
      setDateError(null)
      return
    }
    if (customStartDate && customEndDate) {
      const start = new Date(customStartDate)
      const end = new Date(customEndDate)
      if (end < start) {
        setDateError('结束日期不能早于起始日期')
      } else {
        setDateError(null)
      }
    } else {
      setDateError(null)
    }
  }, [timeRange, customStartDate, customEndDate])

  const handleExport = async () => {
    if (timeRange === 'custom') {
      if (!customStartDate || !customEndDate) {
        setDateError('请选择开始和结束时间')
        return
      }
      const start = new Date(customStartDate)
      const end = new Date(customEndDate)
      if (end < start) {
        setDateError('结束日期不能早于起始日期')
        return
      }
    }

    setDateError(null)
    setIsExporting(true)
    setProgress({
      current: 0,
      total: items.length,
      currentItem: items[0]?.name || '',
      status: 'running',
      results: items.map(item => ({ name: item.name, status: 'pending' }))
    })

    const config: BatchExportConfig = {
      format, timeRange,
      customStartDate: timeRange === 'custom' ? customStartDate : undefined,
      customEndDate: timeRange === 'custom' ? customEndDate : undefined,
      includeSystemMessages, quickExport, includeAvatars,
      skipDownloadResourceTypes: skipDownloadResourceTypes || [],
      outputDir, keywords,
    }

    try {
      await onExport(config, (index, status, error) => {
        setProgress(prev => {
          const nextResults = [...prev.results]
          nextResults[index] = { name: items[index]?.name || '', status, error }
          const next = Math.min(index + 1, items.length - 1)
          return { ...prev, current: next, currentItem: items[next]?.name || '', results: nextResults }
        })
      })
      setProgress(prev => ({ ...prev, status: 'completed' }))
    } catch (error) {
      setProgress(prev => ({ ...prev, status: 'failed' })); setDateError(error instanceof Error ? error.message : '创建任务失败')
    } finally {
      setIsExporting(false)
    }
  }

  const handleClose = () => {
    if (!isExporting) {
      onOpenChange(false)
    }
  }


  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        fullScreen
        overlayClassName="bg-background/80 dark:bg-background/80"
        className="inset-x-4 top-14 bottom-4 w-auto h-auto rounded-[24px] shadow-[0_20px_60px_-15px_rgba(0,0,0,0.14)] dark:shadow-[0_24px_80px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col p-0"
      >
        <DialogTitle className="sr-only">批量导出聊天记录</DialogTitle>

        <div className="flex-1 flex min-h-0 w-full">
          {/* 左侧 - 选中的会话列表 */}
          <div className="w-2/5 max-w-[500px] min-w-[300px] flex-shrink-0 flex flex-col pt-12 pl-12 pr-8 pb-6">
            <h1 className="text-[20px] font-semibold text-foreground mb-2">批量导出聊天记录</h1>
            <p className="text-[13px] text-muted-foreground mb-8 leading-relaxed">已选择 {items.length} 个会话进行批量导出。</p>
            
            <div className="flex-1 overflow-hidden">
              <ScrollArea className="h-full rounded-2xl p-2 bg-black/[0.02] dark:bg-white/[0.03]">
                <div className="space-y-1">
                  {items.map((item, idx) => (
                    <div 
                      key={`${item.type}_${item.id}`} 
                      className={[
                        "flex items-center gap-3 p-3 rounded-xl transition-all",
                        progress.current === idx && progress.status === 'running' 
                          ? "bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700" 
                          : "hover:bg-muted/50"
                      ].join(" ")}
                    >
                      {/* 头像 + 状态角标 */}
                      <div className="relative flex-shrink-0">
                        <Avatar className="w-9 h-9">
                          {item.avatarUrl && <AvatarImage src={item.avatarUrl} alt={item.name} />}
                          <AvatarFallback className="text-[13px]">
                            {item.name ? item.name.slice(0, 1) : item.type === 'group' ? <Users className="w-4 h-4" /> : <User className="w-4 h-4" />}
                          </AvatarFallback>
                        </Avatar>
                        {progress.status !== 'idle' && (
                          <span className="absolute -bottom-0.5 -right-0.5 flex items-center justify-center rounded-full bg-background">
                            {progress.results[idx]?.status === 'success' ? (
                              <CheckCircle2 className="w-4 h-4 text-green-500" />
                            ) : progress.results[idx]?.status === 'failed' ? (
                              <XCircle className="w-4 h-4 text-red-500" />
                            ) : progress.current === idx && progress.status === 'running' ? (
                              <Loader size={14} className="text-blue-500" />
                            ) : null}
                          </span>
                        )}
                      </div>

                      {/* 信息 */}
                      <div className="flex-1 min-w-0">
                        <p className={[
                          "font-medium text-sm truncate",
                          progress.current === idx && progress.status === 'running' ? 'text-blue-900 dark:text-blue-100' : 'text-foreground'
                        ].join(" ")}>
                          {item.name}
                        </p>
                        {progress.results[idx]?.error && (
                          <p className="text-xs text-red-600 dark:text-red-400 mt-0.5 truncate">{progress.results[idx].error}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          </div>

          {/* 右侧 - 配置选项 */}
          <div className="flex-1 min-w-0 overflow-y-auto px-10 xl:px-12 pt-12 pb-8">
            <div className="w-full max-w-[760px] mx-auto space-y-10">
              {/* 导出格式 */}
              <section>
                <h2 className={SECTION_TITLE}>导出格式</h2>
                <div className="inline-flex items-center flex-wrap gap-1 p-1 rounded-[20px] bg-black/[0.04] dark:bg-white/[0.06] w-fit max-w-full">
                  {(["HTML", "JSON", "TXT", "CSV", "JSONL", "MD"] as const).map((fmt) => {
                    const active = format === fmt
                    return (
                      <button
                        key={fmt}
                        type="button"
                        disabled={isExporting}
                        className={[
                          "px-5 h-[30px] text-[13px] font-medium rounded-full transition-all",
                          active
                            ? "bg-white dark:bg-white/10 text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.06)]"
                            : "text-muted-foreground hover:text-foreground"
                        ].join(" ")}
                        onClick={() => !isExporting && setFormat(fmt)}
                      >
                        {fmt}
                      </button>
                    )
                  })}
                </div>
              </section>

              {/* 时间范围 */}
              <section>
                <h2 className={SECTION_TITLE + " flex items-center gap-1.5"}>
                  时间范围
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <HelpCircle className="w-[14px] h-[14px] text-muted-foreground/60 hover:text-muted-foreground transition-colors outline-none cursor-pointer" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-[250px]">
                      {EXPORT_OPTION_TOOLTIPS.allMessages}
                    </TooltipContent>
                  </Tooltip>
                </h2>
                <div className="space-y-4">
                  <div className="inline-flex items-center flex-wrap gap-1 p-1 rounded-[20px] bg-black/[0.04] dark:bg-white/[0.06] w-fit max-w-full">
                    {[
                      { value: 'all', label: '全部消息' },
                      { value: 'recent', label: '最近 3 个月' },
                      { value: 'custom', label: '自定义' }
                    ].map((option) => {
                      const active = timeRange === option.value
                      return (
                        <button
                          key={option.value}
                          type="button"
                          disabled={isExporting}
                          className={[
                            "px-5 h-[30px] text-[13px] font-medium rounded-full transition-all",
                            active
                              ? "bg-white dark:bg-white/10 text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.06)]"
                              : "text-muted-foreground hover:text-foreground"
                          ].join(" ")}
                          onClick={() => !isExporting && setTimeRange(option.value as 'all' | 'recent' | 'custom')}
                        >
                          {option.label}
                        </button>
                      )
                    })}
                  </div>
                  {timeRange === 'custom' && (
                    <div className="space-y-2">
                      <DateRangePicker
                        startTime={customStartDate}
                        endTime={customEndDate}
                        onChange={(start, end) => { setCustomStartDate(start); setCustomEndDate(end) }}
                      />
                      {dateError && <div className="text-[13px] text-red-600 dark:text-red-400">{dateError}</div>}
                    </div>
                  )}
                </div>
              </section>

              <section>
                <h2 className={SECTION_TITLE}>导出内容</h2>
                <div className="rounded-2xl border border-black/[0.06] dark:border-white/[0.08] divide-y divide-black/[0.05] dark:divide-white/[0.06]">
                  <ExportSwitch id="include-system-messages" title="包含系统消息" description="保留群通知、撤回提示等系统消息；关闭后也会过滤合并转发中的系统消息。" checked={includeSystemMessages} onChange={setIncludeSystemMessages} disabled={isExporting}/>
                  <ExportSwitch id="quick-export" title="快速导出（跳过全部资源）" description="保留消息与卡片信息，不复制或下载附件、缩略图和头像，不进行媒体解密与转码。" checked={quickExport} onChange={setQuickExport} disabled={isExporting}/>
                  {([
                    {type:'file', title:'仅保留文件元数据，不导出文件', description:'保留已有文件名、大小等信息，不复制或下载文档和其他文件；其他媒体按各自开关处理。'},
                    {type:'image', title:'不导出图片和动画表情', description:'跳过图片、GIF 表情和卡片缩略图的复制、下载及解密。头像由下方开关单独控制。'},
                    {type:'video', title:'不导出视频', description:'不复制、下载或转码视频，减少磁盘占用；保留视频消息及已有信息。'},
                    {type:'audio', title:'不导出语音', description:'不提取或下载语音文件，保留对应的语音消息记录。'},
                  ] as const).map(option=><ExportSwitch key={option.type} id={'skip-'+option.type} title={option.title} description={option.description} checked={quickExport || !!skipDownloadResourceTypes?.includes(option.type)} disabled={isExporting || quickExport} onChange={enabled=>setSkipDownloadResourceTypes(current=>toggleSkipResourceType(current,option.type,enabled))}/>)}
                  <ExportSwitch id="include-avatars" title="导出头像" description="将可用头像一起保存到归档中；关闭后使用姓名首字作为占位。" checked={includeAvatars && !quickExport} onChange={setIncludeAvatars} disabled={isExporting || quickExport}/>
                </div>
                <p className="text-[12px] text-muted-foreground leading-relaxed mt-3">以上设置同样作用于引用回复与合并转发中的资源。主动跳过的附件会单独标注，不会记作下载失败。</p>
              </section>

              {/* 高级选项 */}
              <section>
                <h2 className={SECTION_TITLE}>高级选项</h2>
                <div className="space-y-6">
                <p className="text-[12px] text-muted-foreground leading-relaxed">按上方设置保存可用资源。HTML 可离线阅读；资源未取得或解密失败时会说明原因。</p>
                  <div className="space-y-2.5">
                    <label className="block text-[12px] font-medium text-muted-foreground pl-1">导出路径</label>
                    <div className="flex gap-2">
                      <Input placeholder="使用设置中的导出目录，可点击右侧文件夹更改" value={outputDir} readOnly disabled={isExporting} className={PILL_INPUT + " flex-1"} />
                      <Button variant="outline" size="icon" disabled={isExporting} className="rounded-full shrink-0" title="选择文件夹" onClick={async () => { const result = await call("choose_output"); if (!result.cancelled) setOutputDir(result.export_dir) }}><FolderOpen className="w-4 h-4" /></Button>
                    </div>
                  </div>

                  <div className="space-y-2.5">
                    <label className="block text-[12px] font-medium text-muted-foreground pl-1">关键词过滤</label>
                    <Textarea placeholder="输入关键词或发送者，留空导出全部" value={keywords} onChange={(e) => setKeywords(e.target.value)} disabled={isExporting} rows={2} className={PILL_TEXTAREA + " w-full"} />
                  </div>

                </div>
              </section>

              {/* 导出进度 */}
              {progress.status === 'running' && (
                <div className="space-y-4 p-5 rounded-2xl bg-black/[0.03] dark:bg-white/[0.04]">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Loader size={16} className="text-primary" />
                      <div>
                        <h4 className="text-[13px] font-medium text-foreground">正在导出</h4>
                        <p className="text-[12px] text-muted-foreground">{progress.current + 1} / {progress.total} 个会话</p>
                      </div>
                    </div>
                    <div className="text-[15px] font-semibold text-foreground tabular-nums">{progress.total > 0 ? Math.round(((progress.current + 1) / progress.total) * 100) : 0}%</div>
                  </div>
                  <Progress value={progress.total > 0 ? ((progress.current + 1) / progress.total) * 100 : 0} className="h-2" />
                  <div className="text-[12px] text-muted-foreground truncate"><span className="font-medium">当前：</span>{progress.currentItem}</div>
                </div>
              )}
            </div>
          </div>
        </div>

        {dateError && <p role="alert" className="px-10 py-2 text-sm text-red-600">{dateError}</p>}
        {/* 底部操作栏 */}
        <div className="h-[72px] flex items-center justify-between px-10 flex-shrink-0">
          <div className="text-[13px] font-medium text-muted-foreground">
            {progress.status === 'running' ? (
              <span className="text-foreground">正在导出 {progress.current + 1}/{progress.total} 个会话...</span>
            ) : progress.status === 'completed' ? (
              <span className="text-foreground">导出完成</span>
            ) : (
              <span className="text-foreground">配置就绪，将导出 {items.length} 个会话</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" onClick={handleClose} disabled={isExporting} className="rounded-full text-[13px] h-8">
              {isExporting ? '导出中...' : progress.status === 'completed' ? '关闭' : '取消'}
            </Button>
            {progress.status !== 'completed' && (
              <Button onClick={handleExport} disabled={isExporting || (timeRange === 'custom' && (!customStartDate || !customEndDate || !!dateError))} className="rounded-full text-[13px] h-8 px-6 bg-primary text-primary-foreground hover:bg-primary/90">
                {isExporting ? '导出中...' : '开始批量导出'}
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
