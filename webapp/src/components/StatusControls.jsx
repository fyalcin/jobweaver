import { ChevronDown } from 'lucide-react'
import { useDemo } from '../demoContext'
import { STATUS_CONFIG, STATUS_ORDER } from '../constants/status'

export function StatusBadge({ status, size = 'sm' }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.new
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      padding: size === 'sm' ? '0.2rem 0.55rem' : '0.3rem 0.75rem',
      borderRadius: '9999px',
      fontSize: size === 'sm' ? '0.72rem' : '0.82rem',
      fontWeight: 600,
      backgroundColor: cfg.bg,
      color: cfg.color,
      border: `1px solid ${cfg.border}`,
      whiteSpace: 'nowrap'
    }}>
      {cfg.label}
    </span>
  )
}

export function StatusSelect({ value, onChange, compact = false, ariaLabel = 'Job application status' }) {
  const demo = useDemo()
  const cfg = STATUS_CONFIG[value || 'new'] || STATUS_CONFIG.new
  return (
    <span
      className={`stage-select-wrap ${compact ? 'is-compact' : ''}`}
      onClick={e => e.stopPropagation()}
    >
      <select
        disabled={demo}
        aria-label={ariaLabel}
        value={value || 'new'}
        onChange={e => onChange(e.target.value)}
        className={`stage-select ${compact ? 'is-compact' : ''}`}
        style={{
          backgroundColor: cfg.bg,
          color: cfg.color,
          borderColor: cfg.border,
        }}
      >
        {STATUS_ORDER.map(s => (
          <option key={s} value={s} style={{ background: 'var(--surface-card)', color: 'var(--text-primary)' }}>
            {STATUS_CONFIG[s].label}
          </option>
        ))}
      </select>
      <ChevronDown
        size={compact ? 12 : 13}
        className="stage-select-chevron"
        style={{ color: cfg.color }}
        aria-hidden="true"
      />
    </span>
  )
}
