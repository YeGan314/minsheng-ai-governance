import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

function inlineCss(): Plugin {
  return {
    name: 'inline-css-in-widget-bundle',
    generateBundle(_options, bundle) {
      const css = Object.values(bundle).find((item) => item.type === 'asset' && item.fileName.endsWith('.css'))
      if (!css || css.type !== 'asset') return
      const cssText = JSON.stringify(String(css.source))
      for (const item of Object.values(bundle)) {
        if (item.type === 'chunk' && item.fileName.endsWith('.js')) {
          item.code = `(()=>{const s=document.createElement('style');s.textContent=${cssText};document.head.appendChild(s)})();\n${item.code}`
        }
      }
      delete bundle[css.fileName]
    },
  }
}

function syncFrontendAssets(): Plugin {
  return {
    name: 'sync-frontend-datav-assets',
    writeBundle(_options, bundle) {
      const outputDir = resolve(process.cwd(), 'dist')
      const targetDir = resolve(process.cwd(), '../frontend/public/datav-map')
      const packageDir = resolve(process.cwd(), 'datav-package')
      mkdirSync(targetDir, { recursive: true })
      mkdirSync(packageDir, { recursive: true })
      const jsAsset = Object.keys(bundle).find((name) => name.endsWith('.iife.js'))
      const cssAsset = Object.keys(bundle).find((name) => name.endsWith('.css'))
      if (jsAsset) {
        const source = readFileSync(resolve(outputDir, jsAsset), 'utf8')
        const exported = source.endsWith('\nwindow.BjghDataVMap = BjghDataVMap;\n') ? source : `${source}\nwindow.BjghDataVMap = BjghDataVMap;\n`
        writeFileSync(resolve(targetDir, 'widget.js'), exported)
        writeFileSync(resolve(packageDir, 'widget.js'), exported)
      }
      if (cssAsset) {
        copyFileSync(resolve(outputDir, cssAsset), resolve(targetDir, 'widget.css'))
        copyFileSync(resolve(outputDir, cssAsset), resolve(packageDir, 'widget.css'))
      }
    },
  }
}

export default defineConfig({
  plugins: [vue(), inlineCss(), syncFrontendAssets()],
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  build: {
    // DataV 运行环境可能不是最新 Chromium，避免交付包保留可选链和空值合并语法。
    target: 'es2015', sourcemap: false, cssCodeSplit: false,
    lib: { entry: 'src/datav-entry.ts', name: 'BjghDataVMap', fileName: 'widget', formats: ['iife'] },
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
})
