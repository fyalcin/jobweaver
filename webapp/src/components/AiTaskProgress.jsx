import React from 'react';

/** Shared determinate progress for analysis, reprocessing, and batch generation. */
export function AiTaskProgress({ label, processed, total, failed, accent }) {
  const n = Number(total) || 0;
  const p = Number(processed) || 0;
  const f = Number(failed) || 0;
  const pct = n > 0 ? Math.min(100, Math.round(((p + f) / n) * 100)) : 0;
  if (n <= 0) return null;
  
  return (
    <div style={{ marginTop: '0.45rem', width: '100%' }}>
      <div style={{
        fontSize: '0.76rem', color: 'var(--text-secondary)', marginBottom: '0.3rem',
        display: 'flex', justifyContent: 'space-between', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center',
      }}>
        <span style={{ color: 'var(--text-primary)' }}>{label}</span>
        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
          {p} ok{p + f < n ? ` · ${n - p - f} left` : ''}{f > 0 ? <span style={{ color: 'var(--error-color)', marginLeft: '0.35rem' }}>· {f} failed</span> : null}
          <span style={{ opacity: 0.65, fontWeight: 500, marginLeft: '0.35rem' }}>/ {n}</span>
        </span>
      </div>
      <div style={{
        height: 8, borderRadius: 4, background: 'var(--bg-secondary)', overflow: 'hidden',
        border: '1px solid var(--border-color)',
      }}>
        <div style={{
          height: '100%', width: `${pct}%`, background: accent, transition: 'width 0.3s ease',
        }} />
      </div>
    </div>
  );
}
