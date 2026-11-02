import {useEffect,useRef} from 'react'
import '../../../ui/date-range-picker.js'

export interface DateRangePickerProps {
  startTime?:string
  endTime?:string
  onChange?:(start:string,end:string)=>void
  className?:string
  emptyLabel?:string
  disabled?:boolean
}

/** Identical calendar and clock controls in the desktop and offline HTML. */
export function DateRangePicker({startTime='',endTime='',onChange,className,emptyLabel,disabled}:DateRangePickerProps){
  const host=useRef<HTMLDivElement>(null),callback=useRef(onChange)
  callback.current=onChange
  useEffect(()=>{
    const element=document.createElement('moect-date-range')
    const changed=(event:Event)=>{const {start,end}=(event as CustomEvent).detail;callback.current?.(start,end)}
    element.addEventListener('range-change',changed);host.current?.append(element)
    return()=>{element.removeEventListener('range-change',changed);element.remove()}
  },[])
  useEffect(()=>{
    const element=host.current?.firstElementChild
    element?.setAttribute('start',startTime);element?.setAttribute('end',endTime)
    element?.setAttribute('empty-label',emptyLabel||'选择时间范围')
    element?.toggleAttribute('disabled',!!disabled)
  },[startTime,endTime,emptyLabel,disabled])
  return <div ref={host} className={className}/>
}
