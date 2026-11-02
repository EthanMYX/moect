import {useEffect} from 'react'
import {call} from './native'

/** The full-client WebView forwards only the user's own edge drags to Windows. */
export function useWindowEdges(){
  useEffect(()=>{
    let maximized=false,disposed=false
    void call('window_state').then(state=>{maximized=state.maximized;sync()}).catch(()=>{})
    const style=document.createElement('style')
    style.textContent='[data-window-edge]{position:fixed;z-index:2147483647;app-region:no-drag;-webkit-app-region:no-drag;touch-action:none}html[data-resize-cursor] *{cursor:var(--resize-cursor)!important}'
    const edges:Record<string,string>={n:'top:0;left:8px;right:8px;height:6px',s:'bottom:0;left:8px;right:8px;height:6px',w:'left:0;top:8px;bottom:8px;width:6px',e:'right:0;top:8px;bottom:8px;width:6px',nw:'top:0;left:0;width:8px;height:8px',ne:'top:0;right:0;width:8px;height:8px',sw:'bottom:0;left:0;width:8px;height:8px',se:'bottom:0;right:0;width:8px;height:8px'}
    const zones=Object.entries(edges).map(([edge,css])=>{const el=document.createElement('div');el.dataset.windowEdge=edge;el.style.cssText=css;el.setAttribute('aria-hidden','true');return el})
    const sync=()=>{if(!disposed)zones.forEach(el=>el.hidden=maximized);clear()}
    const clear=()=>{document.documentElement.removeAttribute('data-resize-cursor');document.documentElement.style.removeProperty('--resize-cursor')}
    const edgeAt=(e:PointerEvent)=>{
      if(maximized||e.pointerType==='touch')return ''
      if(e.clientY<8){if(e.clientX<8)return 'nw';if(e.clientX>=innerWidth-8)return 'ne'}
      if(e.clientY>=innerHeight-8){if(e.clientX<8)return 'sw';if(e.clientX>=innerWidth-8)return 'se'}
      const left=e.clientX<6,right=e.clientX>=innerWidth-6,top=e.clientY<6,bottom=e.clientY>=innerHeight-6
      return top?(left?'nw':right?'ne':'n'):bottom?(left?'sw':right?'se':'s'):left?'w':right?'e':''
    }
    const move=(e:PointerEvent)=>{const edge=edgeAt(e);if(!edge){clear();return}document.documentElement.setAttribute('data-resize-cursor','');document.documentElement.style.setProperty('--resize-cursor',edge+'-resize')}
    const down=(e:PointerEvent)=>{const edge=edgeAt(e);if(!edge||e.button!==0)return;e.preventDefault();e.stopImmediatePropagation();clear();void call('window_resize',{edge}).catch(()=>{})}
    const state=(e:Event)=>{maximized=(e as CustomEvent).detail.maximized;sync()}
    document.head.append(style);zones.forEach(el=>document.body.append(el))
    window.addEventListener('pointermove',move,true);window.addEventListener('pointerdown',down,true);window.addEventListener('blur',clear);window.addEventListener('wce-window-state',state)
    return()=>{disposed=true;clear();style.remove();zones.forEach(el=>el.remove());window.removeEventListener('pointermove',move,true);window.removeEventListener('pointerdown',down,true);window.removeEventListener('blur',clear);window.removeEventListener('wce-window-state',state)}
  },[])
}
