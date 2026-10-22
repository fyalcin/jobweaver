import React, { useState, useEffect, useRef } from 'react'
import { AlertTriangle, RefreshCw, FileText, CheckCircle2 } from 'lucide-react'
import { compileTypstClient, isTypstWasmSupported } from '../../services/typstWorkerClient'

export function TypstWasmPreview({
  source = '',
  zoom = 100,
  onPageCountChange,
  className = '',
}) {
  const [svgContent, setSvgContent] = useState('')
  const [isCompiling, setIsCompiling] = useState(false)
  const [compileError, setCompileError] = useState(null)
  const [compileTimeMs, setCompileTimeMs] = useState(null)
  const [pageCount, setPageCount] = useState(1)

  const compilationSequence = useRef(0);
  const debounceTimerRef = useRef(null)
  const latestSourceRef = useRef(source)
  latestSourceRef.current = source

  useEffect(() => {
    const sequence = ++compilationSequence.current;
    if (!source || !source.trim()) {
      setSvgContent('')
      setCompileError(null)
      return
    }

    if (!isTypstWasmSupported()) {
      setCompileError(new Error('WebAssembly/Web Worker is not supported in this browser.'))
      return
    }

    // Debounce compilation to run smoothly while typing
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
    }

    debounceTimerRef.current = setTimeout(async () => {
      const currentText = latestSourceRef.current
      if (!currentText.trim()) return

      setIsCompiling(true)
      const t0 = performance.now()

      try {
        const { result } = await compileTypstClient(currentText, 'svg')
        if (sequence !== compilationSequence.current) return;
        const elapsed = Math.round(performance.now() - t0)

        setSvgContent(result)
        setCompileError(null)
        setCompileTimeMs(elapsed)

        // Count pages from SVG output
        const pageMatches = result.match(/class="typst-page"/g)
        const pages = pageMatches ? pageMatches.length : 1
        setPageCount(pages)
        if (onPageCountChange) {
          onPageCountChange(pages)
        }
      } catch (err) {
        if (sequence !== compilationSequence.current) return;
        // Keep previous valid SVG on syntax error so the preview doesn't flash blank
        const rawMsg = err?.message || String(err)
        // Clean up common verbose diagnostic wrappers
        const cleanMsg = rawMsg.replace(/\[SourceDiagnostic\s*\{[^}]*message:\s*"([^"]+)"[^}]*\}\]/g, '$1')
        setCompileError({ message: cleanMsg, raw: rawMsg })
      } finally {
        setIsCompiling(false)
      }
    }, 350)

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
      }
    }
  }, [source, onPageCountChange])

  return (
    <div className={`typst-wasm-preview-root ${className}`}>
      {/* Live Status Bar */}
      <div className="typst-live-header-bar">
        <div className="typst-live-status-group">
          <span className="typst-live-pill">
            <span className={`pulse-dot ${isCompiling ? 'compiling' : 'ready'}`} />
            <span>{isCompiling ? 'Compiling Live…' : compileError ? 'Previous preview — out of date' : 'Live WASM'}</span>
            {compileTimeMs && !isCompiling && (
              <span className="typst-live-time">({compileTimeMs}ms)</span>
            )}
          </span>
          <span className="typst-live-page-badge">
            {pageCount} {pageCount === 1 ? 'Page' : 'Pages'}
          </span>
        </div>

        {compileError ? (
          <span className="typst-live-status-err">
            <AlertTriangle size={13} /> Syntax Error
          </span>
        ) : (
          <span className="typst-live-status-ok">
            <CheckCircle2 size={13} /> Instant Vector Preview
          </span>
        )}
      </div>

      {/* Syntax Error Banner (Non-destructive: overlayed above previous valid preview) */}
      {compileError && (
        <div className="typst-live-error-card">
          <div className="typst-live-error-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <AlertTriangle size={15} color="#f59e0b" />
              <strong>Typst Live Diagnostics</strong>
            </div>
            <span className="typst-live-error-hint">Fix code to resume live rendering</span>
          </div>
          <p className="typst-live-error-message">{compileError.message}</p>
        </div>
      )}

      {/* Scrollable Document Container */}
      <div
        className="typst-wasm-scroll-container"
        tabIndex={0}
        role="region"
        aria-label="Typst document preview canvas"
      >
        {svgContent ? (
          <div
            className="typst-pages-wrapper"
            style={{
              transform: `scale(${zoom / 100})`,
              transformOrigin: 'top center',
            }}
          >
            <div
              className="typst-page-card"
              dangerouslySetInnerHTML={{ __html: svgContent }}
            />
          </div>
        ) : isCompiling ? (
          <div className="studio-preview-placeholder">
            <RefreshCw className="spinner" size={36} style={{ marginBottom: '0.75rem', opacity: 0.6 }} />
            <h4>Compiling Typst Document in WebAssembly…</h4>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Preparing zero-latency vector preview
            </p>
          </div>
        ) : (
          <div className="studio-preview-placeholder">
            <FileText size={48} style={{ opacity: 0.3, marginBottom: '1rem' }} />
            <h4>No Content to Preview</h4>
            <p>Start typing in the editor on the left to render your Typst document.</p>
          </div>
        )}
      </div>
    </div>
  )
}
