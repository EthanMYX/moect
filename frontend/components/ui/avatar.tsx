"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import {call} from '@/src/native'

// Shared native-resolution promises prevent repeat requests on page switches.
const resolvedAvatars=new Map<string,Promise<string>>()
function resolveAvatar(src:string){
  if(!/^https?:/i.test(src))return Promise.resolve(src)
  if(!resolvedAvatars.has(src)){
    if(resolvedAvatars.size>=2048)resolvedAvatars.clear()
    resolvedAvatars.set(src,call('avatar',{url:src}).then(r=>r.url||'').catch(()=>''))
  }
  return resolvedAvatars.get(src)!
}

interface AvatarContextValue {
  imageLoaded: boolean
  setImageLoaded: (loaded: boolean) => void
}

const AvatarContext = React.createContext<AvatarContextValue>({
  imageLoaded: false,
  setImageLoaded: () => {},
})

const Avatar = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => {
  const [imageLoaded, setImageLoaded] = React.useState(false)
  
  return (
    <AvatarContext.Provider value={{ imageLoaded, setImageLoaded }}>
      <div
        ref={ref}
        className={cn(
          "relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full",
          className
        )}
        {...props}
      />
    </AvatarContext.Provider>
  )
})
Avatar.displayName = "Avatar"

const AvatarImage = React.forwardRef<
  HTMLImageElement,
  React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, onLoad, onError, src, ...props }, ref) => {
  const { setImageLoaded } = React.useContext(AvatarContext)
  const [localSrc,setLocalSrc]=React.useState('')
  React.useEffect(()=>{
    let current=true
    setLocalSrc('');setImageLoaded(false)
    if(src)resolveAvatar(src).then(url=>{if(current)setLocalSrc(url)})
    return()=>{current=false}
  },[src])
  if(!localSrc)return null
  
  return (
    <img
      ref={ref}
      src={localSrc}
      className={cn("aspect-square h-full w-full object-cover", className)}
      onLoad={(e) => {
        setImageLoaded(true)
        onLoad?.(e)
      }}
      onError={(e) => {
        setImageLoaded(false)
        onError?.(e)
      }}
      {...props}
    />
  )
})
AvatarImage.displayName = "AvatarImage"

const AvatarFallback = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => {
  const { imageLoaded } = React.useContext(AvatarContext)
  
  if (imageLoaded) return null
  
  return (
    <div
      ref={ref}
      className={cn(
        "absolute inset-0 flex h-full w-full items-center justify-center rounded-full bg-neutral-100 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-300",
        className
      )}
      {...props}
    />
  )
})
AvatarFallback.displayName = "AvatarFallback"

export { Avatar, AvatarImage, AvatarFallback }
