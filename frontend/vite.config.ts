import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'
import path from 'node:path'
export default defineConfig({base:'./',plugins:[react(),tailwind()],resolve:{alias:{'@':path.resolve(import.meta.dirname)}},build:{outDir:'../ui-qce',emptyOutDir:true,target:'chrome120'}})
