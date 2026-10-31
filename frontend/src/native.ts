declare global {interface Window {QWebChannel:any; qt:any; pywebview:any; __wceNativeRegions?:boolean; __ready?:boolean; __wce?:any}}
let sequence=0
const pending=new Map<string,{resolve:(value:any)=>void,reject:(e:Error)=>void}>()
let bridge:any
export const ready=new Promise<void>(resolve=>{
  const edge=()=>{if(window.pywebview?.api?.invoke){bridge=window.pywebview.api;resolve();return true}return false}
  if(edge())return
  window.addEventListener('pywebviewready',edge,{once:true})
  if(window.qt){
    const script=document.createElement('script');script.src='qrc:///qtwebchannel/qwebchannel.js'
    script.onload=()=>new window.QWebChannel(window.qt.webChannelTransport,(channel:any)=>{
      bridge=channel.objects.native
      bridge.windowState.connect((maximized:boolean)=>window.dispatchEvent(new CustomEvent('wce-window-state',{detail:{maximized}})))
      bridge.response.connect((raw:string)=>{const data=JSON.parse(raw),p=pending.get(data.id);if(!p)return;pending.delete(data.id);data.error?p.reject(new Error(data.error)):p.resolve(data.result)})
      resolve()
    });document.head.append(script)
  }
})
export async function call(action:string,payload:any={}){
 await ready
 if(bridge.invoke){const data=await bridge.invoke(action,payload);if(data.error)throw new Error(data.error);return data.result}
 return new Promise<any>((resolve,reject)=>{const id=String(++sequence);pending.set(id,{resolve,reject});bridge.request(JSON.stringify({id,action,payload}))})
}
export async function nativeFetch(_url:string,options:any):Promise<any>{
  const payload=JSON.parse(options.body)
  const data=await call('qce_preview',payload)
  return {ok:true,status:200,json:async()=>({success:true,data})}
}
