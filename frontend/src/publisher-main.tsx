import React from 'react'
import {createRoot} from 'react-dom/client'
import {PublisherApp} from './PublisherApp'
import '../styles/fonts.css'
import './publisher.css'
import {call} from './native'

declare global {interface Window {__publisherBoot?:{ready:()=>void;fail:()=>void};__publisherReady?:boolean}}

class PublisherBoundary extends React.Component<React.PropsWithChildren,{failed:boolean}>{
  state={failed:false}
  static getDerivedStateFromError(){return {failed:true}}
  componentDidCatch(){window.__publisherBoot?.fail();void call('publisher_ui_error').catch(()=>{})}
  render(){return this.state.failed?null:this.props.children}
}
createRoot(document.getElementById('root')!).render(<PublisherBoundary><PublisherApp/></PublisherBoundary>);
