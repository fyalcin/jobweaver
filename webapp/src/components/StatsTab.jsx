import { useState } from 'react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  CartesianGrid
} from 'recharts'
import {
  RefreshCw,
  BarChart2,
  Layers,
  ChevronDown,
  CalendarDays,
  TrendingUp,
  AlertTriangle,
  ChevronRight,
  Download
} from 'lucide-react'
import { STATUS_CONFIG } from '../constants/status'
import { sourceLabel } from '../constants/ratings'
import { formatDateDisplay } from '../constants/dates'
import { PageHeader } from './PageHeader'

const SKILLS_PAGE_SIZE = 20

// Category colors stay attached to their source when the chart order changes.
function sourceColor(source) {
  const name = String(source).toLowerCase()
  const category = name.includes('linkedin') ? 'linkedin' : name.includes('karriere') ? 'karriere'
    : name.includes('manual') ? 'manual' : /company|greenhouse|personio|smartrecruiters|successfactors/.test(name) ? 'company' : 'other'
  return `var(--chart-source-${category})`
}

function ratingBarFill(rating) {
  const key = String(rating || '').toLowerCase()
  if (key.includes('blocked')) return 'color-mix(in srgb, var(--danger-color) 72%, var(--surface-card))'
  if (key.includes('great')) return 'var(--primary-color)'
  if (key.includes('good')) return 'color-mix(in srgb, var(--primary-color) 76%, var(--surface-card))'
  if (key.includes('ok')) return 'color-mix(in srgb, var(--primary-color) 52%, var(--surface-card))'
  if (key.includes('poor')) return 'color-mix(in srgb, var(--primary-color) 32%, var(--surface-card))'
  return 'color-mix(in srgb, var(--text-muted) 42%, var(--surface-card))'
}

function CustomTooltip({ active, payload, label, labelFormatter }) {
  if (active && payload && payload.length) {
    const rawLabel = label ?? payload[0]?.name
    const displayLabel = labelFormatter ? labelFormatter(rawLabel) : rawLabel
    return (
      <div style={{ background: 'var(--surface-card)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '0.5rem 0.75rem', fontSize: '0.82rem', boxShadow: 'var(--shadow-md)' }}>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '2px' }}>{displayLabel}</p>
        <p style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{payload[0].value}</p>
      </div>
    )
  }
  return null
}

function SkillsTooltip({ active, payload }) {
  if (active && payload && payload.length) {
    const { skill, count } = payload[0].payload
    return (
      <div style={{ background: 'var(--surface-card)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '0.5rem 0.75rem', fontSize: '0.82rem', boxShadow: 'var(--shadow-md)' }}>
        <p style={{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: '2px' }}>{skill}</p>
        <p style={{ color: 'var(--text-secondary)' }}>{count} job{count !== 1 ? 's' : ''}</p>
      </div>
    )
  }
  return null
}

function ChartEmptyState({ icon: Icon, title, message }) {
  return (
    <div className="chart-empty-state">
      {Icon && (
        <div className="chart-empty-icon-wrap">
          <Icon size={22} />
        </div>
      )}
      <div className="chart-empty-title">{title}</div>
      {message && <p className="chart-empty-subtitle">{message}</p>}
    </div>
  )
}

function exportSkillsStats(skillsStats) {
  const payload = {
    exported_at: new Date().toISOString(),
    total_unique_skills: skillsStats.total_unique,
    total_jobs_analyzed: skillsStats.total_jobs_analyzed,
    ai_normalized: skillsStats.ai_normalized,
    skills: skillsStats.skills,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')
  const a = document.createElement('a')
  a.href = url
  a.download = `skills_stats_${ts}.json`
  a.click()
  URL.revokeObjectURL(url)
}

export function StatsTab({ stats, statsLoading, fetchStats, skillsStats, skillsLoading, skillsError, fetchSkillsStats }) {
  const [skillsVisible, setSkillsVisible] = useState(SKILLS_PAGE_SIZE)

  if (statsLoading) {
    return (
      <div className="page-shell">
        <PageHeader
          title="Analytics"
          subtitle="Track posting volume, evidence-based match ratings, pipeline conversion, and recurring skills."
        />
        <div style={{ padding: '4rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <RefreshCw className="spinner" size={32} style={{ margin: '0 auto 1rem', display: 'block' }} />
          <p>Loading statistics…</p>
        </div>
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="page-shell">
        <PageHeader
          title="Analytics"
          subtitle="Track posting volume, evidence-based match ratings, pipeline conversion, and recurring skills."
        />
        <div style={{ padding: '4rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <BarChart2 size={40} style={{ margin: '0 auto 1rem', opacity: 0.4, display: 'block' }} />
          <p>No stats available yet.</p>
          <button className="btn btn-secondary" style={{ marginTop: '1rem' }} onClick={fetchStats}>
            <RefreshCw size={16} /> Load Stats
          </button>
        </div>
      </div>
    )
  }

  const skillsSlice = skillsStats ? skillsStats.skills.slice(0, skillsVisible) : []
  const canShowMore = skillsStats && skillsVisible < skillsStats.skills.length
  const canShowLess = skillsVisible > SKILLS_PAGE_SIZE

  // Dynamic chart height: 36px per row, min 200px
  const skillsChartHeight = Math.max(200, skillsSlice.length * 36)

  return (
    <div className="page-shell">
      <PageHeader
        title="Analytics"
        subtitle="Track posting volume, evidence-based match ratings, pipeline conversion, and recurring skills."
        actions={
          <button type="button" className="btn btn-secondary btn-sm" onClick={fetchStats}>
            <RefreshCw size={14} />
            <span>Refresh</span>
          </button>
        }
      />

      {/* Top metrics - 2-tier structure: Hero metrics + Pipeline status */}
      <div className="stats-hero-grid">
        <div className="metric-card stats-hero-card">
          <span className="metric-label">Total Jobs</span>
          <span className="metric-value">{stats.total_jobs}</span>
        </div>
        <div className="metric-card stats-hero-card">
          <span className="metric-label">Rated jobs</span>
          <span className="metric-value" style={{ color: 'var(--primary-color)' }}>
            {stats.rated_jobs ?? '—'}
          </span>
        </div>
      </div>

      <div className="stats-pipeline-grid">
        {stats.status_funnel.map(({ status, count }) => (
          <div key={status} className="metric-card" style={{ opacity: count === 0 ? 0.45 : 1, transition: 'opacity 0.2s ease' }}>
            <span className="metric-label">{STATUS_CONFIG[status]?.label || status}</span>
            <span className="metric-value" style={{
              color: STATUS_CONFIG[status]?.color || 'var(--text-primary)',
              fontSize: count === 0 ? '1.4rem' : undefined
            }}>{count}</span>
          </div>
        ))}
      </div>

      {/* Compute data presence for charts */}
      {(() => {
        const hasMatchRatings = stats.match_rating_distribution && stats.match_rating_distribution.some(d => (d.count || 0) > 0)
        const totalSourceCount = stats.source_breakdown?.reduce((acc, s) => acc + (s.count || 0), 0) || 0
        const totalFunnelCount = stats.status_funnel?.reduce((acc, f) => acc + (f.count || 0), 0) || 0
        const hasJobsPerDay = stats.jobs_per_day && stats.jobs_per_day.length > 0 && stats.jobs_per_day.some(d => (d.count || 0) > 0)

        return (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 480px), 1fr))', gap: '1.5rem' }}>

            {/* Match ratings */}
            <div className="card" style={{ minWidth: 0 }}>
              <h3 className="card-title"><BarChart2 size={18} /> Match ratings</h3>
              {hasMatchRatings ? (
                <><ul className="rating-distribution-list">{stats.match_rating_distribution.map(item => <li key={item.rating}>{item.rating}: {item.count}</li>)}</ul><ResponsiveContainer width="100%" height={220}>
                  <BarChart data={stats.match_rating_distribution} margin={{ top: 5, right: 8, bottom: 5, left: -22 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                    <XAxis dataKey="rating" interval={0} tick={{ fill: 'var(--text-secondary)', fontSize: 10.5 }} />
                    <YAxis allowDecimals={false} width={36} tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                      {stats.match_rating_distribution.map((entry, i) => (
                        <Cell key={i} fill={ratingBarFill(entry.rating)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer></>
              ) : (
                <ChartEmptyState
                  icon={BarChart2}
                  title="No evidence-based ratings yet"
                  message="Rate incoming or historical postings to compare requirement evidence. Historical scores are not converted to ratings."
                />
              )}
            </div>

            {/* Source Breakdown */}
            <div className="card" style={{ minWidth: 0 }}>
              <h3 className="card-title"><Layers size={18} /> Source Breakdown</h3>
              {totalSourceCount > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', height: 220 }}>
                  <div style={{ flex: 1, minHeight: 0 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={stats.source_breakdown.filter(s => s.count > 0)}
                          dataKey="count"
                          nameKey="source"
                          cx="50%"
                          cy="50%"
                          innerRadius={45}
                          outerRadius={72}
                          paddingAngle={2}
                          isAnimationActive={false}
                        >
                          {stats.source_breakdown.filter(s => s.count > 0).map((item, i) => (
                            <Cell key={i} fill={sourceColor(item.source)} />
                          ))}
                        </Pie>
                        <Tooltip content={<CustomTooltip labelFormatter={sourceLabel} />} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="source-legend-row">
                    {stats.source_breakdown.filter(s => s.count > 0).map((item) => {
                      const pct = totalSourceCount > 0 ? ((item.count / totalSourceCount) * 100).toFixed(0) : 0
                      const displaySource = sourceLabel(item.source)
                      return (
                        <div key={item.source} className="source-legend-item" title={`${displaySource}: ${item.count} jobs`}>
                          <span className="source-legend-dot" style={{ background: sourceColor(item.source) }} />
                          <span className="source-legend-name">{displaySource}</span>
                          <span className="source-legend-pct">{pct}%</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ) : (
                <ChartEmptyState
                  icon={Layers}
                  title="No Source Breakdown"
                  message="Source distribution will appear as jobs are ingested from scraping channels."
                />
              )}
            </div>

            {/* Application Funnel */}
            <div className="card" style={{ minWidth: 0 }}>
              <h3 className="card-title"><ChevronDown size={18} /> Application Funnel</h3>
              {totalFunnelCount > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={stats.status_funnel}
                    layout="vertical"
                    margin={{ top: 5, right: 20, bottom: 5, left: 60 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" horizontal={false} />
                    <XAxis type="number" allowDecimals={false} tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} />
                    <YAxis
                      type="category"
                      dataKey="status"
                      tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
                      tickFormatter={s => STATUS_CONFIG[s]?.label || s}
                      width={55}
                    />
                    <Tooltip content={<CustomTooltip labelFormatter={s => STATUS_CONFIG[s]?.label || s} />} />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                      {stats.status_funnel.map(({ status }) => (
                        <Cell key={status} fill={STATUS_CONFIG[status]?.color || 'var(--text-muted)'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <ChartEmptyState
                  icon={ChevronDown}
                  title="No Pipeline Activity"
                  message="Track your applications through review, interview, and offer stages."
                />
              )}
            </div>

            {/* Jobs Per Day */}
            <div className="card" style={{ minWidth: 0 }}>
              <h3 className="card-title"><CalendarDays size={18} /> Jobs Per Day</h3>
              {hasJobsPerDay ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={stats.jobs_per_day.slice(-30)}
                    margin={{ top: 5, right: 10, bottom: 30, left: -10 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={v => formatDateDisplay(v)}
                      tick={{ fill: 'var(--text-secondary)', fontSize: 10, angle: -45, textAnchor: 'end' }}
                      interval="preserveStartEnd"
                    />
                    <YAxis allowDecimals={false} tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} />
                    <Tooltip content={<CustomTooltip labelFormatter={v => formatDateDisplay(v)} />} />
                    <Bar dataKey="count" fill="var(--primary-color)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <ChartEmptyState
                  icon={CalendarDays}
                  title="No Ingestion History"
                  message="Daily scraping volume will be graphed here over the last 30 days."
                />
              )}
            </div>
          </div>
        )
      })()}

      {/* ── Skills in Demand ─────────────────────────────────────────── */}
      <div className="card" style={{ marginTop: '1.5rem' }}>
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem' }}>
          <h3 className="card-title" style={{ margin: 0 }}>
            <TrendingUp size={18} /> Skills in Demand
          </h3>
           <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            {/* Badge */}
            {skillsStats && !skillsLoading && (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
                padding: '0.2rem 0.6rem', borderRadius: '999px', fontSize: '0.75rem',
                background: 'var(--nav-soft-bg)',
                color: 'var(--text-secondary)',
                border: '1px solid var(--border-color)',
              }}>
                {skillsStats.total_unique} unique skills · {skillsStats.total_jobs_analyzed} jobs
              </span>
            )}
            {/* Refresh button */}
            <button
              id="skills-refresh-btn"
              className="btn btn-secondary btn-sm"
              disabled={skillsLoading}
              onClick={() => {
                setSkillsVisible(SKILLS_PAGE_SIZE)
                fetchSkillsStats()
              }}
            >
              <RefreshCw size={13} className={skillsLoading ? 'spinner' : ''} />
              {skillsLoading ? 'Loading…' : 'Refresh'}
            </button>
            {/* Export button — only when data is available */}
            {skillsStats && !skillsLoading && skillsStats.skills.length > 0 && (
              <button
                id="skills-export-btn"
                className="btn btn-secondary btn-sm"
                onClick={() => exportSkillsStats(skillsStats)}
                title="Download skills data as JSON"
              >
                <Download size={13} />
                Export JSON
              </button>
            )}
          </div>
        </div>

        {/* Error state */}
        {skillsError && !skillsLoading && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '0.5rem',
            padding: '0.6rem 0.8rem', borderRadius: '6px', marginBottom: '0.75rem',
            background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)',
            color: '#d97706', fontSize: '0.83rem',
          }}>
            <AlertTriangle size={15} />
            {skillsError}
            <button className="btn btn-secondary" style={{ marginLeft: 'auto', fontSize: '0.78rem', padding: '0.2rem 0.5rem' }}
              onClick={() => fetchSkillsStats()}>
              Retry
            </button>
          </div>
        )}

        {/* Loading state */}
        {skillsLoading && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.75rem', padding: '3rem 0', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            <RefreshCw className="spinner" size={20} />
            Analyzing skills with AI — this may take a moment…
          </div>
        )}

        {/* Empty state */}
        {!skillsLoading && skillsStats && skillsStats.skills.length === 0 && (
          <ChartEmptyState
            icon={TrendingUp}
            title="No Skills Extracted Yet"
            message="Skills analysis will populate once AI normalization extracts keywords from active listings."
          />
        )}

        {/* Not-yet-loaded state */}
        {!skillsLoading && !skillsStats && !skillsError && (
          <ChartEmptyState
            icon={TrendingUp}
            title="Skill frequency across postings"
            message="Click 'Refresh' above to count recurring skills and group synonyms across your saved postings."
          />
        )}

        {/* Chart */}
        {!skillsLoading && skillsSlice.length > 0 && (
          <>
            <ResponsiveContainer width="100%" height={skillsChartHeight}>
              <BarChart
                data={skillsSlice}
                layout="vertical"
                margin={{ top: 4, right: 40, bottom: 4, left: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" horizontal={false} />
                <XAxis type="number" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} allowDecimals={false} />
                <YAxis
                  type="category"
                  dataKey="skill"
                  width={130}
                  tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
                  tickLine={false}
                />
                <Tooltip content={<SkillsTooltip />} />
                <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={22} isAnimationActive={false}>
                  {skillsSlice.map((_, i) => <Cell key={i} fill="var(--primary-color)" />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>

            {/* Show more / less */}
            <div style={{ display: 'flex', justifyContent: 'center', gap: '0.5rem', marginTop: '0.75rem' }}>
              {canShowMore && (
                <button
                  id="skills-show-more-btn"
                  className="btn btn-secondary"
                  style={{ fontSize: '0.82rem' }}
                  onClick={() => setSkillsVisible(v => v + SKILLS_PAGE_SIZE)}
                >
                  <ChevronRight size={14} /> Show {Math.min(SKILLS_PAGE_SIZE, skillsStats.skills.length - skillsVisible)} more
                </button>
              )}
              {canShowLess && (
                <button
                  className="btn btn-secondary"
                  style={{ fontSize: '0.82rem' }}
                  onClick={() => setSkillsVisible(SKILLS_PAGE_SIZE)}
                >
                  Show less
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
