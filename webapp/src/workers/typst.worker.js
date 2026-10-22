import compilerWasmUrl from '@myriaddreamin/typst-ts-web-compiler/pkg/typst_ts_web_compiler_bg.wasm?url'
import rendererWasmUrl from '@myriaddreamin/typst-ts-renderer/pkg/typst_ts_renderer_bg.wasm?url'
import { $typst, initOptions, MemoryAccessModel, loadFonts } from '@myriaddreamin/typst.ts'

let isInitialized = false
let initPromise = null

/**
 * Custom package registry resolving Typst package imports (@preview/...) to MemoryAccessModel paths.
 */
const offlinePackageRegistry = {
  resolve(spec) {
    return `/@memory/fetch/packages/${spec.namespace}/${spec.name}/${spec.version}`
  },
}

/**
 * Lazily initialize compiler and renderer WASM instances with offline packages and fonts.
 */
async function initTypst() {
  if (isInitialized) return
  if (initPromise) return initPromise

  initPromise = (async () => {
    // 1. Fetch package and font manifest
    const manifestRes = await fetch('/typst/manifest.json')
    if (!manifestRes.ok) {
      throw new Error(`Failed to load /typst/manifest.json: HTTP ${manifestRes.status}`)
    }
    const manifest = await manifestRes.json()

    // 2. Preload offline packages into MemoryAccessModel
    const mem = new MemoryAccessModel()
    const packageFetchPromises = manifest.packages.flatMap((pkg) =>
      pkg.files.map(async (file) => {
        const fileUrl = `/typst/packages/${pkg.namespace}/${pkg.name}/${pkg.version}/${file}`
        const res = await fetch(fileUrl)
        if (!res.ok) {
          throw new Error(`Failed to fetch Typst package file ${fileUrl}: HTTP ${res.status}`)
        }
        const buf = new Uint8Array(await res.arrayBuffer())
        const vpath = `/@memory/fetch/packages/${pkg.namespace}/${pkg.name}/${pkg.version}/${file}`
        mem.insertFile(vpath, buf, new Date())
      })
    )
    await Promise.all(packageFetchPromises)

    // 3. Preload core fonts (New Computer Modern & Font Awesome)
    const fontFetchPromises = (manifest.fonts || []).map(async (fontFile) => {
      const fontUrl = `/typst/fonts/${encodeURIComponent(fontFile)}`
      const res = await fetch(fontUrl)
      if (!res.ok) {
        throw new Error(`Failed to fetch Typst font ${fontUrl}: HTTP ${res.status}`)
      }
      return new Uint8Array(await res.arrayBuffer())
    })
    const fontBuffers = await Promise.all(fontFetchPromises)

    // 4. Register access model and package registry via $typst.use
    $typst.use({
      key: 'access-model',
      forRoles: ['compiler'],
      provides: [initOptions.withAccessModel(mem)],
    })

    $typst.use({
      key: 'package-registry',
      forRoles: ['compiler'],
      provides: [initOptions.withPackageRegistry(offlinePackageRegistry)],
    })

    // 5. Configure compiler and renderer with local WASM modules and fonts
    $typst.setCompilerInitOptions({
      getModule: () => compilerWasmUrl,
      beforeBuild: [
        loadFonts(fontBuffers, { assets: false }),
      ],
    })

    $typst.setRendererInitOptions({
      getModule: () => rendererWasmUrl,
    })

    // Pre-warm compiler and renderer
    await $typst.getCompiler()
    await $typst.getRenderer()
    isInitialized = true
  })()

  return initPromise
}

/**
 * Handle compile requests from main thread.
 */
async function handleCompile(id, source, format = 'svg') {
  try {
    await initTypst()
    if (format === 'pdf') {
      const pdfBytes = await $typst.pdf({ mainContent: source })
      self.postMessage({ type: 'COMPILED', id, format: 'pdf', result: pdfBytes })
    } else {
      const svg = await $typst.svg({ mainContent: source })
      self.postMessage({ type: 'COMPILED', id, format: 'svg', result: svg })
    }
  } catch (err) {
    self.postMessage({
      type: 'ERROR',
      id,
      error: err instanceof Error ? err.message : String(err),
    })
  }
}

self.addEventListener('message', async (event) => {
  const { type, id, source, format } = event.data || {}

  if (type === 'INIT') {
    try {
      await initTypst()
      self.postMessage({ type: 'INIT_OK', id })
    } catch (err) {
      self.postMessage({
        type: 'ERROR',
        id,
        error: err instanceof Error ? err.message : String(err),
      })
    }
  } else if (type === 'COMPILE') {
    await handleCompile(id, source, format)
  }
})
