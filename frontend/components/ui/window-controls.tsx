// Adapted from QCE's window-controls.tsx; visual classes are unchanged.
// Native WebView2 regions handle pointer capture on the window's UI thread.
import {useEffect,useState} from 'react'
import {Maximize2,Minus,Square,X} from 'lucide-react'
import {call} from '@/src/native'

export function WindowDragRegion({className=''}:{className?:string}){
  return <div data-window-drag className={`h-full min-w-0 flex-1 ${className}`}
    onMouseDown={e=>{if(!window.__wceNativeRegions&&e.button===0&&e.target===e.currentTarget)void call('window_drag')}}
    onDoubleClick={e=>{if(!window.__wceNativeRegions&&e.target===e.currentTarget)void call('window_maximize')}}/>
}
const buttonClass='flex h-full w-11 items-center justify-center text-muted-foreground/60 transition-colors hover:bg-black/[0.04] hover:text-foreground dark:hover:bg-white/[0.06]'
export function WindowControls(){
  const [maximized,setMaximized]=useState(false)
  useEffect(()=>{void call('window_state').then(data=>setMaximized(data.maximized));const listener=(e:any)=>setMaximized(e.detail.maximized);window.addEventListener('wce-window-state',listener);return()=>window.removeEventListener('wce-window-state',listener)},[])
  return <div className="flex h-12 -mr-4 ml-1 flex-shrink-0 select-none"><button type="button" aria-label="最小化" onClick={()=>void call('window_minimize')} className={buttonClass}><Minus className="w-3.5 h-3.5" strokeWidth={1.6}/></button><button type="button" aria-label={maximized?'还原':'最大化'} onClick={()=>void call('window_maximize').then(data=>setMaximized(data.maximized))} className={buttonClass}>{maximized?<Square className="w-2.5 h-2.5" strokeWidth={1.4}/>:<Maximize2 className="w-3 h-3" strokeWidth={1.4}/>}</button><button type="button" aria-label="关闭" onClick={()=>void call('window_close')} className={`${buttonClass} hover:bg-red-500 hover:text-white dark:hover:bg-red-500`}><X className="w-3.5 h-3.5" strokeWidth={1.6}/></button></div>
}
