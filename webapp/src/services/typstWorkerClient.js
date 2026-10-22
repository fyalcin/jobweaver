/**
 * typstWorkerClient.js
 * Client wrapper to communicate with the dedicated Typst WASM Web Worker.
 */

let workerInstance = null
let nextRequestId = 1
const pendingRequests = new Map()

export function isTypstWasmSupported() {
  return typeof window !== 'undefined' &&
    typeof window.Worker !== 'undefined' &&
    typeof window.WebAssembly !== 'undefined'
}

export function getTypstWorker() {
  if (!workerInstance && isTypstWasmSupported()) {
    workerInstance = new Worker(
      new URL('../workers/typst.worker.js', import.meta.url),
      { type: 'module' }
    )

    workerInstance.onmessage = (event) => {
      const { type, id, format, result, error } = event.data || {}
      const callbacks = pendingRequests.get(id)
      if (!callbacks) return

      clearTimeout(callbacks.timer)
      pendingRequests.delete(id)
      if (type === 'ERROR') {
        callbacks.reject(new Error(error || 'Typst compilation failed'))
      } else {
        callbacks.resolve({ format, result })
      }
    }

    workerInstance.onerror = (err) => {
      console.error('[TypstWorker] Worker error:', err)
      for (const [id, callbacks] of pendingRequests.entries()) {
        clearTimeout(callbacks.timer)
        callbacks.reject(new Error(err.message || 'Typst worker crashed'))
        pendingRequests.delete(id)
      }
      workerInstance.terminate()
      workerInstance = null
    }
  }

  return workerInstance
}

/**
 * Compiles Typst source string client-side via Web Worker.
 * @param {string} source - Typst markup source code
 * @param {'svg' | 'pdf'} format - Output format ('svg' or 'pdf')
 * @returns {Promise<{ result: string | Uint8Array, format: string }>}
 */
export function compileTypstClient(source, format = 'svg') {
  const worker = getTypstWorker()
  if (!worker) {
    return Promise.reject(new Error('Web Workers / WebAssembly are not supported in this environment'))
  }

  const id = nextRequestId++
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      terminateTypstWorker()
    }, 45000)
    pendingRequests.set(id, { resolve, reject, timer })
    worker.postMessage({
      type: 'COMPILE',
      id,
      source,
      format,
    })
  })
}

/**
 * Pre-warms the Typst worker WASM engines in the background.
 */
export function initTypstWorker() {
  const worker = getTypstWorker()
  if (!worker) return Promise.reject(new Error('Web Workers not supported'))

  const id = nextRequestId++
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      terminateTypstWorker()
    }, 45000)
    pendingRequests.set(id, { resolve, reject, timer })
    worker.postMessage({ type: 'INIT', id })
  })
}

/**
 * Converts a Uint8Array to a standard base64 string safely without stack overflow.
 * @param {Uint8Array} bytes
 * @returns {string}
 */
export function uint8ArrayToBase64(bytes) {
  if (!bytes || !(bytes instanceof Uint8Array)) return ''
  let binary = ''
  const chunkSize = 8192
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize)
    binary += String.fromCharCode.apply(null, chunk)
  }
  return window.btoa(binary)
}

/**
 * Initiates an immediate client-side browser download for PDF bytes.
 * @param {Uint8Array} pdfBytes
 * @param {string} filename
 */
export function downloadPdfBlob(pdfBytes, filename = 'document.pdf') {
  if (!pdfBytes) return
  const blob = new Blob([pdfBytes], { type: 'application/pdf' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.pdf') ? filename : `${filename}.pdf`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * Terminates active worker instance.
 */
export function terminateTypstWorker() {
  if (workerInstance) {
    workerInstance.terminate()
    workerInstance = null
    for (const callbacks of pendingRequests.values()) {
      clearTimeout(callbacks.timer)
      callbacks.reject(new Error('Document compilation stopped or timed out. Please try again.'))
    }
    pendingRequests.clear()
  }
}
