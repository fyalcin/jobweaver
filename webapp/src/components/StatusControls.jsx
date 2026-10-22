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
  return (
    <select disabled={demo}
      aria-label={ariaLabel}
      value={value || 'new'}
      onChange={e => onChange(e.target.value)}
      onClick={e => e.stopPropagation()}
      style={{
        backgroundColor: STATUS_CONFIG[value || 'new'].bg,
        color: STATUS_CONFIG[value || 'new'].color,
        border: `1px solid ${STATUS_CONFIG[value || 'new'].border}`,
        borderRadius: '9999px',
        padding: compact ? '0.18rem 0.5rem' : '0.3rem 0.6rem',
        fontSize: compact ? '0.72rem' : '0.82rem',
        fontWeight: 600,
        cursor: 'pointer',
        outline: 'none',
        appearance: 'none',
        WebkitAppearance: 'none',
        paddingRight: compact ? '1.4rem' : '1.6rem',
        backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23a1a1aa' stroke-width='2.5'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E")`,
        backgroundRepeat: 'no-repeat',
        backgroundPosition: 'right 0.4rem center',
      }}
    >
      {STATUS_ORDER.map(s => (
        <option key={s} value={s} style={{ background: '#18181b', color: '#fafafa' }}>
          {STATUS_CONFIG[s].label}
        </option>
      ))}
    </select>
  )
}
