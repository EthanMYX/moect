import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
export default defineConfig({base:'./',plugins:[react()],build:{outDir:'../ui-publisher',emptyOutDir:true,target:'chrome120',rollupOptions:{input:path.resolve(import.meta.dirname,'publisher.html')}}})
