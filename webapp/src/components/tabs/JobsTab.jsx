import { useDemo } from '../../demoContext';
import React, { useState } from 'react';
import {
  AlertCircle, RefreshCw, ChevronDown, Wand2, ArrowLeft, CheckCircle2,
  Sparkles, Pencil, ExternalLink, FileText, Mail, Layers, Download, Briefcase,
  X, SlidersHorizontal, Save, CheckSquare, Square, Info, Trash2, LayoutGrid, Table
} from 'lucide-react';
import { STATUS_ORDER, STATUS_CONFIG } from '../../constants/status';
import { AiTaskProgress } from '../AiTaskProgress';
import { StatusSelect } from '../StatusControls';
import { germanLevelLabel } from '../../constants/german';
import { formatDateDisplay } from '../../constants/dates';

const getMatchTier = (job) => {
  if (job?.match_analysis?.tier) return job.match_analysis.tier;
  if (typeof job?.data?.match_analysis?.tier === 'string') return job.data.match_analysis.tier;
  if (job?.match_score == null || job?.match_score === undefined || job?.match_score === '') return null;
  const score = Number(job.match_score);
  if (isNaN(score)) return null;
  if (score >= 80) return 'Strong Match';
  if (score >= 65) return 'Good Match';
  if (score >= 50) return 'Moderate Match';
  return 'Reach';
};

const getTierBadgeClass = (tier) => {
  switch (tier) {
    case 'Strong Match': return 'table-tier-strong';
    case 'Good Match': return 'table-tier-good';
    case 'Moderate Match': return 'table-tier-moderate';
    case 'Reach': return 'table-tier-reach';
    default: return '';
  }
};

const isJobStale = (job) => {
  if (!job?.date_scraped) return false;
  const status = job.status || (job.applied ? 'applied' : 'new');
  if (status !== 'new') return false;
  const age = (Date.now() - new Date(`${job.date_scraped}T00:00:00`).getTime()) / 86400000;
  return age > 21;
};

/** Short display name for a job's Source label. */
function sourceLabel(source) {
  const value = String(source || '');
  if (/^karriere/i.test(value)) return 'Karriere';
  if (/^company feed/i.test(value)) return 'Company feed';
  if (/^linkedin/i.test(value)) return 'LinkedIn';
  if (value === 'manual') return 'Manual';
  return value || 'Unknown';
}

export function JobsTab({
  jobs, loading, appliedCount, actionableCount, sortedJobs, filteredJobs,
  unprocessedJobs, reprocessTaskId, reprocessProgress, handleStartReprocess,
  searchQuery, setSearchQuery, germanFilter, setGermanFilter,
  statusFilter, setStatusFilter, sourceFilter, setSourceFilter,
  scrapeDateFilter, setScrapeDateFilter, minMatchFilter, setMinMatchFilter,
  uniqueSources, uniqueScrapeDates, activeFilters, filteredOutCount, clearFilters, clearFilter,
  applyView, quickViews, savedViews, saveCurrentView, deleteSavedView,
  selectedJobIds, selectedJobs, selectedCount, toggleSelectedJob, setVisibleSelection,
  batchGenProgress, batchGenSubmitting, batchGenTaskId, handleBatchGenerate, handleBatchGenerateForce, handleBatchGenerateCancel,
  batchMarkStatus, setBatchMarkStatus, batchMarkActive, handleBatchMark,
  handleSort, sortConfig, setSortConfig, viewMode, setViewMode, paginatedJobs, setSelectedJobDetails, getScoreBadgeClass,
  updateJobStatus, setEditingJob, setEditTitle, setEditCompany, handleJobsGenerateCV, generatingJobsDocs, handleJobsGenerateLetter, handleJobsGenerateBoth,
  handleDeleteJob,
  currentPage, setCurrentPage, itemsPerPage, setItemsPerPage, totalPages
}) {
  const demo = useDemo();
  const [unprocessedExpanded, setUnprocessedExpanded] = useState(false);
  const [moreFiltersOpen, setMoreFiltersOpen] = useState(false);
  const [savedViewsOpen, setSavedViewsOpen] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const today = new Date().toISOString().slice(0, 10);
  const sortCol = (key) => `${sortConfig.key === key ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}`;

  const defaultGerman = 'All';
  const isDefaultFilterState = germanFilter === defaultGerman &&
    (statusFilter === 'new' || !statusFilter) &&
    (scrapeDateFilter === '__recent21' || !scrapeDateFilter) &&
    sourceFilter === 'All' &&
    minMatchFilter === '' &&
    !searchQuery.trim();

  return (
    <>
      {/* Compact stats row */}
      <div className="jobs-stats-summary-row">
        <span><span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{jobs.length.toLocaleString()}</span> total jobs</span>
        <span style={{ opacity: 0.4 }}>·</span>
        <span><span style={{ color: 'var(--success-color)', fontWeight: 600 }}>{appliedCount}</span> applied</span>
        <span style={{ opacity: 0.4 }}>·</span>
        <button className="metric-link" title="New jobs scoring above 65 with German requirements compatible with B1" onClick={() => applyView(quickViews.inbox)}>
          <span style={{ color: 'var(--warning-color)', fontWeight: 600 }}>{actionableCount}</span> need attention <Info size={12} />
        </button>
        <span style={{ opacity: 0.4 }}>·</span>
        <span style={{ color: 'var(--primary-light, #818cf8)', fontWeight: 500 }}>{sortedJobs.length.toLocaleString()} visible</span>
        {filteredOutCount > 0 && <><span style={{ opacity: 0.4 }}>·</span><span>{filteredOutCount.toLocaleString()} hidden by filters</span></>}
      </div>

      {/* Processing Queue Banner */}
      {unprocessedJobs.length > 0 && (
        <div style={{
          marginBottom: '1rem',
          borderRadius: '10px',
          border: '1px solid rgba(245,158,11,0.35)',
          backgroundColor: 'rgba(245,158,11,0.07)',
          overflow: 'hidden',
        }}>
          <div className="pending-analysis-banner-row" style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', padding: '0.75rem 1rem' }}>
            <AlertCircle size={16} color="#f59e0b" style={{ flexShrink: 0, marginTop: '0.1rem' }} />
            <div style={{ flex: 1, fontSize: '0.85rem', minWidth: 0 }}>
              <div>
                {reprocessTaskId && reprocessProgress ? (
                  <span style={{ color: 'var(--text-primary)' }}>
                    Processing with AI…{' '}
                    <span style={{ color: '#f59e0b', fontWeight: 600 }}>{reprocessProgress.processed} / {reprocessProgress.total}</span>
                    {reprocessProgress.failed > 0 && (
                      <span style={{ color: 'var(--error-color)', marginLeft: '0.5rem' }}>({reprocessProgress.failed} failed)</span>
                    )}
                  </span>
                ) : (
                  <span style={{ color: 'var(--text-primary)' }}>
                    <span style={{ color: '#f59e0b', fontWeight: 600 }}>{unprocessedJobs.length} job{unprocessedJobs.length !== 1 ? 's' : ''}</span>
                    {' '}pending AI analysis — hidden from main list until processed
                  </span>
                )}
              </div>
              {reprocessTaskId && reprocessProgress && reprocessProgress.total > 0 && (
                  <AiTaskProgress
                  label="Job analysis (persists if you reload)"
                  processed={reprocessProgress.processed} total={reprocessProgress.total}
                  failed={reprocessProgress.failed} accent="#f59e0b"
                />
              )}
            </div>
            <div className="pending-analysis-banner-actions" style={{ display: 'flex', gap: '0.5rem', flexShrink: 0 }}>
              <button className="btn" onClick={handleStartReprocess} disabled={demo || !!reprocessTaskId}
                style={{ fontSize: '0.78rem', padding: '0.3rem 0.75rem', backgroundColor: reprocessTaskId ? 'rgba(245,158,11,0.1)' : 'rgba(245,158,11,0.85)', color: reprocessTaskId ? '#f59e0b' : '#18181b', border: '1px solid rgba(245,158,11,0.4)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                {reprocessTaskId ? <><RefreshCw size={12} className="spinner" /> Processing…</> : <><RefreshCw size={12} /> Process Now</>}
              </button>
              <button className="btn btn-secondary" onClick={() => setUnprocessedExpanded(v => !v)}
                style={{ fontSize: '0.78rem', padding: '0.3rem 0.65rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <ChevronDown size={12} style={{ transform: unprocessedExpanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
                {unprocessedExpanded ? 'Hide' : 'Show'}
              </button>
            </div>
          </div>

          {unprocessedExpanded && (
            <div style={{ borderTop: '1px solid rgba(245,158,11,0.2)', overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(245,158,11,0.15)' }}>
                    {['Title', 'Company', 'Source', 'Scraped'].map(h => (
                      <th key={h} style={{ padding: '0.5rem 1rem', textAlign: 'left', color: 'var(--text-secondary)', fontWeight: 500, whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {unprocessedJobs.map(job => (
                    <tr key={job.id} style={{ borderBottom: '1px solid rgba(245,158,11,0.08)' }}>
                      <td style={{ padding: '0.45rem 1rem', maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{job.title || '—'}</td>
                      <td style={{ padding: '0.45rem 1rem', whiteSpace: 'nowrap' }}>{job.company || '—'}</td>
                      <td style={{ padding: '0.45rem 1rem', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>{job.source || '—'}</td>
                      <td style={{ padding: '0.45rem 1rem', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>{formatDateDisplay(job.date_scraped, '—')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Filters card */}
      <div className="card jobs-filter-card" style={{ marginBottom: '1.5rem', padding: '1rem 1.25rem' }}>
        <div className="quick-views-row">
          <span className="quick-views-label">Quick views</span>
          <button className="quick-view-btn" onClick={() => applyView(quickViews.inbox)}>Inbox</button>
          <button className="quick-view-btn" onClick={() => applyView(quickViews.highMatches)}>High matches</button>
          <button className="quick-view-btn" onClick={() => applyView(quickViews.last7)}>Last 7 days</button>
          <button className="quick-view-btn" onClick={() => applyView(quickViews.all)}>All jobs</button>
          <details className="saved-views-menu" open={savedViewsOpen} onToggle={e => setSavedViewsOpen(e.currentTarget.open)}>
            <summary className="quick-view-btn"><Save size={13} /> Saved views</summary>
            <div className="saved-views-content">
              <button className="btn btn-primary" onClick={() => { const name = window.prompt('Name this view'); if (name) saveCurrentView(name); }}>Save current view</button>
              {savedViews.length === 0 ? <span className="saved-view-empty">No saved views yet.</span> : savedViews.map(view => (
                <div key={view.name} className="saved-view-item">
                  <button onClick={() => applyView(view)}>{view.name}</button>
                  <button aria-label={`Delete saved view ${view.name}`} title="Delete saved view" onClick={() => deleteSavedView(view.name)}><X size={13} /></button>
                </div>
              ))}
            </div>
          </details>
          <div className="view-mode-toggle" role="group" aria-label="View mode">
            <button
              type="button"
              className={`view-mode-btn ${viewMode === 'cards' ? 'active' : ''}`}
              onClick={() => setViewMode('cards')}
              title="Cards view"
              aria-pressed={viewMode === 'cards'}
            >
              <LayoutGrid size={13} />
              <span>Cards</span>
            </button>
            <button
              type="button"
              className={`view-mode-btn ${viewMode === 'table' ? 'active' : ''}`}
              onClick={() => setViewMode('table')}
              title="Table view"
              aria-pressed={viewMode === 'table'}
            >
              <Table size={13} />
              <span>Table</span>
            </button>
          </div>
        </div>
        <div className="jobs-search-row">
          <input type="text" className="input-base jobs-search-input" placeholder="Search jobs, companies, skills..."
            value={searchQuery} onChange={e => setSearchQuery(e.target.value)} aria-label="Search jobs, companies, and skills" />
          <div className="jobs-search-actions">
            <button
              type="button"
              className={`btn btn-secondary mobile-filter-toggle-btn ${mobileFiltersOpen ? 'active' : ''}`}
              onClick={() => setMobileFiltersOpen(v => !v)}
              aria-expanded={mobileFiltersOpen}
            >
              <SlidersHorizontal size={14} />
              <span>{mobileFiltersOpen ? 'Hide filters' : 'Filters'}</span>
              {activeFilters.length > 0 && <span className="filter-count-badge">{activeFilters.length}</span>}
            </button>
            <button className="btn btn-secondary clear-filters-btn" onClick={clearFilters} disabled={isDefaultFilterState}>
              Clear filters
            </button>
          </div>
        </div>
        <div className={`job-filter-grid ${mobileFiltersOpen ? 'mobile-open' : ''}`}>
          <div style={{ minWidth: 0 }}>
            <label htmlFor="filter-german-level" className="form-label" style={{ fontSize: '0.7rem', marginBottom: '0.3rem' }}>German level</label>
            <select id="filter-german-level" aria-label="Filter by German level" className="input-base" style={{ fontSize: '0.82rem', width: '100%', height: '34px' }} value={germanFilter} onChange={e => setGermanFilter(e.target.value)}>
              <option value="All">All</option>
              <option value="B1">B1 or below</option>
              <option value="none">Not required</option>
              <option value="A1">A1</option>
              <option value="A2">A2</option>
              <option value="B2">B2</option>
              <option value="C1">C1</option>
              <option value="C2">C2</option>
              <option value="native">Native</option>
              <option value="unknown">Unknown</option>
            </select>
          </div>
          <div style={{ minWidth: 0 }}>
            <label htmlFor="filter-status" className="form-label" style={{ fontSize: '0.7rem', marginBottom: '0.3rem' }}>Status</label>
            <select id="filter-status" aria-label="Filter by status" className="input-base" style={{ fontSize: '0.82rem', width: '100%', height: '34px' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
              <option value="new">New</option>
              <option value="active">Active (Unapplied)</option>
              <option value="All">All statuses</option>
              {STATUS_ORDER.filter(s => s !== 'new').map(s => <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>)}
            </select>
          </div>
          <div style={{ minWidth: 0 }}>
            <label htmlFor="filter-source" className="form-label" style={{ fontSize: '0.7rem', marginBottom: '0.3rem' }}>Source</label>
            <select id="filter-source" aria-label="Filter by source" className="input-base" style={{ fontSize: '0.82rem', width: '100%', height: '34px' }} value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}>
              <option value="All">All</option>
              {uniqueSources.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div style={{ minWidth: 0 }}>
            <label htmlFor="filter-sort-by" className="form-label" style={{ fontSize: '0.7rem', marginBottom: '0.3rem' }}>Sort by</label>
            <select id="filter-sort-by" aria-label="Sort jobs by" className="input-base" style={{ fontSize: '0.82rem', width: '100%', height: '34px' }} value={`${sortConfig.key}:${sortConfig.direction}`} onChange={e => { const [key, direction] = e.target.value.split(':'); setSortConfig({ key, direction }); }}>
              <option value="match_score:desc">Match score (high first)</option>
              <option value="date_scraped:desc">Scraped date (newest)</option>
              <option value="date_scraped:asc">Scraped date (oldest)</option>
              <option value="salary_yearly:desc">Salary (highest)</option>
              <option value="title:asc">Title (A-Z)</option>
              <option value="company:asc">Company (A-Z)</option>
            </select>
          </div>
          <button className={`btn btn-secondary more-filters-btn ${moreFiltersOpen ? 'active' : ''}`} onClick={() => setMoreFiltersOpen(v => !v)} aria-expanded={moreFiltersOpen}>
            <SlidersHorizontal size={14} /> {moreFiltersOpen ? 'Hide filters' : 'More filters'}
          </button>
        </div>

        <div className={`job-secondary-filters ${moreFiltersOpen ? 'open' : ''}`}>
          <div style={{ minWidth: 0 }}>
            <label htmlFor="filter-timeframe" className="form-label" style={{ fontSize: '0.7rem', marginBottom: '0.3rem' }}>Timeframe / Scraped</label>
            <select id="filter-timeframe" aria-label="Filter by timeframe or scrape date" className="input-base" style={{ fontSize: '0.82rem', width: '100%', height: '34px' }} value={scrapeDateFilter || '__recent21'} onChange={e => setScrapeDateFilter(e.target.value)}>
              <option value="__recent21">Recent (≤21 days)</option>
              <option value="__last7">Last 7 days</option>
              <option value="__today">Today</option>
              <option value="__last30">Last 30 days</option>
              <option value="__all">All time</option>
              {uniqueScrapeDates.length > 0 && (
                <optgroup label="Specific scrape date">
                  {uniqueScrapeDates.map(d => <option key={d} value={d}>{d === today ? `Today (${d})` : d}</option>)}
                </optgroup>
              )}
            </select>
          </div>
          <div style={{ minWidth: 0 }}>
            <label htmlFor="filter-min-score" className="form-label" style={{ fontSize: '0.7rem', marginBottom: '0.3rem' }}>Minimum score</label>
            <input id="filter-min-score" aria-label="Minimum score" type="number" className="input-base" min="0" max="100" placeholder="0"
              style={{ padding: '0.4rem 0.5rem', fontSize: '0.82rem', width: '100%', height: '34px' }}
              value={minMatchFilter} onChange={e => setMinMatchFilter(e.target.value)} />
          </div>
        </div>

        <div className="active-filter-row" aria-label="Active filters">
          <span className="active-filter-label">Showing</span>
          {activeFilters.map(filter => (
            <button key={filter.key} className="filter-chip" onClick={() => clearFilter(filter.key)} title={`Remove ${filter.label}`}>
              {filter.label}<X size={12} aria-hidden="true" />
            </button>
          ))}
        </div>

        {/* Batch & selection action bar */}
        <div className="jobs-batch-bar">
          <div className="jobs-batch-summary">
            {batchGenProgress && batchGenProgress.total > 0 ? (
              <div className="jobs-batch-generating">
                <RefreshCw size={14} className="spinner" />
                <span style={{ fontWeight: 600, color: 'var(--primary-light)' }}>Generating documents with AI…</span>
                <AiTaskProgress
                  label="CV & cover letters (persists if you reload)"
                  processed={batchGenProgress.processed} total={batchGenProgress.total}
                  failed={batchGenProgress.failed} accent="var(--primary-light)"
                />
              </div>
            ) : batchGenSubmitting ? (
              <span style={{ color: 'var(--text-secondary)' }}>Starting batch on server…</span>
            ) : selectedCount > 0 ? (
              <div className="jobs-selection-summary">
                <span className="jobs-selection-count-badge">
                  <strong>{selectedCount}</strong> selected
                </span>
                <button
                  type="button"
                  className="btn-clear-selection"
                  onClick={() => setVisibleSelection(selectedJobs, false)}
                  title="Deselect all jobs"
                >
                  <X size={12} />
                  <span>Clear</span>
                </button>
                <span className="jobs-selection-scope-note">
                  (of {filteredJobs.length} matching)
                </span>
              </div>
            ) : (
              <span>
                <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{filteredJobs.length}</span> job{filteredJobs.length !== 1 ? 's' : ''} match filters
                {(() => {
                  const needDocs = filteredJobs.filter(j => !j.cv_url || !j.letter_url).length;
                  return needDocs > 0
                    ? <span> · <span style={{ color: 'var(--primary-light)', fontWeight: 600 }}>{needDocs}</span> need docs</span>
                    : <span style={{ color: 'var(--success-color)', marginLeft: '0.3rem' }}>· all have docs ✓</span>
                })()}
              </span>
            )}
          </div>
          <div className="jobs-batch-actions">
            {/* Batch mark status */}
            <div className="jobs-batch-mark-group">
              <select
                aria-label="Bulk mark status"
                value={batchMarkStatus} onChange={e => setBatchMarkStatus(e.target.value)} disabled={batchMarkActive}
                className="input-base batch-status-select"
              >
                {STATUS_ORDER.map(s => <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>)}
              </select>
              <button
                className="btn btn-secondary batch-mark-btn"
                onClick={() => handleBatchMark(selectedCount > 0 ? selectedJobs : filteredJobs)}
                disabled={demo || batchMarkActive || (selectedCount > 0 ? selectedJobs.length === 0 : filteredJobs.length === 0)}
              >
                {batchMarkActive ? <><RefreshCw size={12} className="spinner" /> Marking…</> : (selectedCount > 0 ? 'Mark Selected' : 'Mark All As')}
              </button>
            </div>
            {(batchGenTaskId || batchGenSubmitting) && (
              <button className="btn btn-secondary batch-cancel-btn" onClick={handleBatchGenerateCancel} disabled={demo || !batchGenTaskId}>
                Cancel
              </button>
            )}
            <button
              className="btn batch-generate-btn"
              onClick={() => handleBatchGenerate(selectedCount > 0 ? selectedJobs : undefined)}
              disabled={demo ||
                !!batchGenTaskId ||
                batchGenSubmitting ||
                (selectedCount > 0
                  ? selectedJobs.length === 0
                  : filteredJobs.filter(j => !j.cv_url || !j.letter_url).length === 0)
              }
              style={{
                backgroundColor: (batchGenTaskId || batchGenSubmitting) ? 'color-mix(in srgb, var(--primary-color) 15%, transparent)' : 'var(--primary-color)',
                color: (batchGenTaskId || batchGenSubmitting) ? 'var(--primary-color)' : 'var(--primary-text)',
                border: '1px solid color-mix(in srgb, var(--primary-color) 40%, transparent)',
                opacity: (selectedCount > 0 ? selectedJobs.length === 0 : filteredJobs.filter(j => !j.cv_url || !j.letter_url).length === 0) ? 0.4 : 1
              }}
            >
              {(batchGenTaskId || batchGenSubmitting) ? (
                <><RefreshCw size={12} className="spinner" /> Generating…</>
              ) : selectedCount > 0 ? (
                <><Wand2 size={12} /> Generate Selected Docs</>
              ) : (
                <><Wand2 size={12} /> Generate Docs for All Matching</>
              )}
            </button>
            {selectedCount === 0 && (
              <button className="btn btn-secondary batch-regen-btn" onClick={() => handleBatchGenerateForce()} disabled={demo || !!batchGenTaskId || batchGenSubmitting || filteredJobs.length === 0}
                title="Regenerate documents for all matching jobs, even those that already have docs"
                style={{ opacity: filteredJobs.length === 0 ? 0.4 : 1 }}>
                <RefreshCw size={12} /> Regenerate All
              </button>
            )}
          </div>
        </div>
      </div>

      <div className={`table-container ${viewMode === 'cards' ? 'view-cards' : 'view-table'}`} data-view-mode={viewMode}>
        {loading ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={32} style={{ margin: '0 auto 1rem', display: 'block' }} />
            <p>Loading your database...</p>
          </div>
        ) : jobs.length === 0 ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <Briefcase size={48} style={{ margin: '0 auto 1rem', opacity: 0.5, display: 'block' }} />
            <p>No jobs tracked yet. Start by scraping!</p>
          </div>
        ) : sortedJobs.length === 0 ? (
          <div className="jobs-empty-filtered">
            <SlidersHorizontal size={34} />
            <h3>No jobs match these filters</h3>
            <p>Try removing a filter or broaden the German level and date range.</p>
            <button className="btn btn-secondary" onClick={clearFilters}>Clear filters</button>
          </div>
        ) : (
          <>
            <div className="jobs-table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="th-col-select selection-column"><button className="table-checkbox" aria-label="Select all visible jobs" onClick={() => setVisibleSelection(sortedJobs, !(sortedJobs.length > 0 && sortedJobs.every(job => selectedJobIds.has(job.id))))}>{sortedJobs.length > 0 && sortedJobs.every(job => selectedJobIds.has(job.id)) ? <CheckSquare size={16} /> : <Square size={16} />}</button></th>
                    <th className="th-col-title" onClick={() => handleSort('title')} style={{ cursor: 'pointer', userSelect: 'none' }}>Job Title {sortCol('title')}</th>
                    <th className="th-col-company" onClick={() => handleSort('company')} style={{ cursor: 'pointer', userSelect: 'none' }}>Company {sortCol('company')}</th>
                    <th className="th-col-match" onClick={() => handleSort('match_score')} style={{ cursor: 'pointer', userSelect: 'none' }}>Match {sortCol('match_score')}</th>
                    <th className="th-col-german hide-on-mobile" onClick={() => handleSort('german_level')} style={{ cursor: 'pointer', userSelect: 'none' }}>German {sortCol('german_level')}</th>
                    <th className="th-col-salary" onClick={() => handleSort('salary_yearly')} style={{ cursor: 'pointer', userSelect: 'none' }}>Salary {sortCol('salary_yearly')}</th>
                    <th className="th-col-status" onClick={() => handleSort('status')} style={{ cursor: 'pointer', userSelect: 'none' }}>Status {sortCol('status')}</th>
                    <th className="th-col-scraped hide-on-mobile" onClick={() => handleSort('date_scraped')} style={{ cursor: 'pointer', userSelect: 'none' }}>Scraped {sortCol('date_scraped')}</th>
                    <th className="th-col-source hide-on-mobile" onClick={() => handleSort('source')} style={{ cursor: 'pointer', userSelect: 'none' }}>Source {sortCol('source')}</th>
                    <th className="th-col-actions" style={{ textAlign: 'center' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedJobs.map((job) => (
                    <tr key={job.id}>
                      <td className="td-col-select selection-column"><button className="table-checkbox" aria-label={`Select ${job.title}`} onClick={() => toggleSelectedJob(job.id)}>{selectedJobIds.has(job.id) ? <CheckSquare size={16} /> : <Square size={16} />}</button></td>
                      <td className="td-col-title" style={{ fontWeight: 500, cursor: 'pointer' }}
                        onClick={() => setSelectedJobDetails(job)} title={job.title}>
                        <div className="table-job-title">
                          {job.title}
                        </div>
                      </td>
                      <td className="td-col-company" title={job.company}>
                        <div className="table-job-company">
                          {job.company}
                        </div>
                      </td>
                      <td className="td-col-match">
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.2rem' }}>
                          <span className={`badge ${getScoreBadgeClass(job.match_score)}`}>{job.match_score ? `${job.match_score}/100` : 'N/A'}</span>
                          {(() => {
                            const tier = getMatchTier(job);
                            return tier ? (
                              <span className={`table-tier-pill ${getTierBadgeClass(tier)}`}>
                                {tier}
                              </span>
                            ) : null;
                          })()}
                        </div>
                      </td>
                      <td className="td-col-german hide-on-mobile">
                        {(() => {
                          const level = germanLevelLabel(job.german_level ?? job.requires_german);
                          const germanColor =
                            level === 'Not required'
                              ? 'var(--text-secondary)'
                              : level === 'B1' || level === 'A1' || level === 'A2'
                              ? 'var(--primary-light, #818cf8)'
                              : level === 'Unknown'
                              ? 'var(--text-secondary)'
                              : 'var(--danger-color)';
                          return <span style={{ color: germanColor }}>{level}</span>;
                        })()}
                      </td>
                      <td
                        className="td-col-salary"
                        style={{
                          color: job.salary_yearly ? 'var(--warning-color)' : 'var(--text-secondary)',
                          fontWeight: job.salary_yearly ? 600 : 400,
                          whiteSpace: 'nowrap',
                        }}
                        title={job.salary && job.salary !== "Not Specified" ? job.salary : undefined}
                      >
                        <div className="table-salary-val">
                          {job.salary_yearly
                            ? `€${Number(job.salary_yearly).toLocaleString('de-DE')}`
                            : !job.salary || job.salary === "Not Specified"
                            ? "—"
                            : job.salary.length > 25
                            ? `${job.salary.slice(0, 22)}...`
                            : job.salary}
                        </div>
                      </td>
                      <td className="td-col-status" style={{ whiteSpace: 'nowrap' }}>
                        <StatusSelect value={job.status || (job.applied ? 'applied' : 'new')} onChange={(newStatus) => updateJobStatus(job.id, newStatus)} compact />
                      </td>
                      <td className="td-col-scraped hide-on-mobile" style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap', fontSize: '0.8rem' }}>
                        <div>{formatDateDisplay(job.date_scraped, '-')}</div>
                        {isJobStale(job) && (
                          <span style={{ fontSize: '0.66rem', color: 'var(--text-muted, #94a3b8)', background: 'var(--bg-tag, rgba(255,255,255,0.06))', padding: '1px 5px', borderRadius: '4px', display: 'inline-block', marginTop: '2px', border: '1px solid var(--border-color, rgba(255,255,255,0.1))' }}>
                            &gt;21d old
                          </span>
                        )}
                      </td>
                      <td className="td-col-source hide-on-mobile" style={{ whiteSpace: 'nowrap' }}>
                        <span className="badge" style={{ backgroundColor: 'var(--surface-hover)', color: 'var(--text-muted, #a1a1aa)', border: '1px solid var(--border-color)' }}>
                          {sourceLabel(job.source)}
                        </span>
                      </td>
                      <td className="td-col-actions" style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', alignItems: 'center' }}>
                          <div style={{ display: 'flex', gap: '0.2rem' }}>
                            <button disabled={demo} className="btn btn-icon btn-table-action" aria-label="Edit job" title="Edit job" onClick={() => { setEditingJob(job); setEditTitle(job.title || ''); setEditCompany(job.company || ''); }}><Pencil size={14} /></button>
                            {job.job_url && (
                              <a href={job.job_url} target="_blank" rel="noreferrer" className="btn btn-icon btn-table-action" aria-label="Open original posting" title="Open original posting"><ExternalLink size={14} /></a>
                            )}
                            <button className="btn btn-icon btn-table-action" aria-label="Tailor documents" title="Tailor documents" onClick={() => setSelectedJobDetails({ ...job, initialTab: 'studio' })}><Wand2 size={14} style={{ color: 'var(--primary-color)' }} /></button>
                            <button disabled={demo} className="btn btn-icon btn-table-action" aria-label="Delete job" title="Delete job" onClick={() => handleDeleteJob(job)}><Trash2 size={14} color="#ef4444" /></button>
                          </div>
                          <div style={{ display: 'flex', gap: '0.2rem' }}>
                            <button className="btn btn-icon btn-table-action" title="Generate CV in background" onClick={() => handleJobsGenerateCV(job)} disabled={demo || generatingJobsDocs.has(`${job.id}-cv`)}>
                              {generatingJobsDocs.has(`${job.id}-cv`) ? <RefreshCw size={14} className="spinner" /> : <FileText size={14} color="#3b82f6" />}
                            </button>
                            <button className="btn btn-icon btn-table-action" title="Generate Cover Letter in background" onClick={() => handleJobsGenerateLetter(job)} disabled={demo || generatingJobsDocs.has(`${job.id}-letter`)}>
                              {generatingJobsDocs.has(`${job.id}-letter`) ? <RefreshCw size={14} className="spinner" /> : <Mail size={14} color="#10b981" />}
                            </button>
                            <button className="btn btn-icon btn-table-action" title="Generate CV & Letter in background" onClick={() => handleJobsGenerateBoth(job)} disabled={demo || generatingJobsDocs.has(`${job.id}-cv`) || generatingJobsDocs.has(`${job.id}-letter`)}>
                              {(generatingJobsDocs.has(`${job.id}-cv`) && generatingJobsDocs.has(`${job.id}-letter`)) ? <RefreshCw size={14} className="spinner" /> : <Layers size={14} style={{ color: 'var(--primary-color)' }} />}
                            </button>
                            {job.cv_url ? (
                              <a href={job.cv_url} target="_blank" rel="noreferrer" className="btn btn-icon btn-table-action btn-table-pill" title="Download CV" style={{ color: '#3b82f6', fontSize: '0.62rem', gap: '2px', display: 'flex', alignItems: 'center' }}>
                                <Download size={13} /><span>CV</span>
                              </a>
                            ) : (
                              <button className="btn btn-icon btn-table-action btn-table-pill" disabled title="CV not yet generated" style={{ opacity: 0.35, fontSize: '0.62rem', gap: '2px', display: 'flex', alignItems: 'center', cursor: 'not-allowed' }}>
                                <Download size={13} /><span>CV</span>
                              </button>
                            )}
                            {job.letter_url ? (
                              <a href={job.letter_url} target="_blank" rel="noreferrer" className="btn btn-icon btn-table-action btn-table-pill" title="Download Cover Letter" style={{ color: '#10b981', fontSize: '0.62rem', gap: '2px', display: 'flex', alignItems: 'center' }}>
                                <Download size={13} /><span>CL</span>
                              </a>
                            ) : (
                              <button className="btn btn-icon btn-table-action btn-table-pill" disabled title="Cover Letter not yet generated" style={{ opacity: 0.35, fontSize: '0.62rem', gap: '2px', display: 'flex', alignItems: 'center', cursor: 'not-allowed' }}>
                                <Download size={13} /><span>CL</span>
                              </button>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile Job Cards View */}
            <div className="jobs-cards-wrapper">
              {paginatedJobs.map((job) => (
                <div key={job.id} className="job-card">
                  <div className="job-card-header">
                    <button className="table-checkbox job-card-checkbox" aria-label={`Select ${job.title}`} onClick={() => toggleSelectedJob(job.id)}>
                      {selectedJobIds.has(job.id) ? <CheckSquare size={18} /> : <Square size={18} />}
                    </button>
                    <div className="job-card-title-wrap" onClick={() => setSelectedJobDetails(job)}>
                      <div className="job-card-title">{job.title}</div>
                      <div className="job-card-company">{job.company}</div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.2rem' }}>
                      <span className={`badge ${getScoreBadgeClass(job.match_score)} job-card-score`}>
                        {job.match_score != null ? `${job.match_score}%` : 'N/A'}
                      </span>
                      {(() => {
                        const tier = getMatchTier(job);
                        return tier ? (
                          <span className={`table-tier-pill ${getTierBadgeClass(tier)}`} style={{ fontSize: '0.62rem', padding: '0.1rem 0.35rem' }}>
                            {tier}
                          </span>
                        ) : null;
                      })()}
                    </div>
                  </div>

                  <div className="job-card-meta">
                    {(() => {
                      const level = germanLevelLabel(job.german_level ?? job.requires_german);
                      const tagClass =
                        level === 'Not required'
                          ? 'tag-german-none'
                          : level === 'B1' || level === 'A1' || level === 'A2'
                          ? 'tag-german-ok'
                          : level === 'Unknown'
                          ? 'tag-german-unknown'
                          : 'tag-german-req';
                      return (
                        <span className={`job-card-tag ${tagClass}`}>
                          DE: {level}
                        </span>
                      );
                    })()}

                    {(job.salary_yearly || (job.salary && job.salary !== "Not Specified")) && (
                      <span className="job-card-tag tag-salary">
                        {job.salary_yearly ? `€${Number(job.salary_yearly).toLocaleString('de-AT')}` : job.salary}
                      </span>
                    )}

                    <span className="job-card-tag tag-source">
                      {sourceLabel(job.source)}
                    </span>

                    {job.date_scraped && (
                      <span className="job-card-date">
                        {formatDateDisplay(job.date_scraped)}
                        {isJobStale(job) && <span style={{ marginLeft: '4px', fontSize: '0.7rem', color: 'var(--text-muted, #94a3b8)', opacity: 0.85 }}>(&gt;21d)</span>}
                      </span>
                    )}
                  </div>

                  <div className="job-card-actions">
                    <div className="job-card-status">
                      <StatusSelect value={job.status || (job.applied ? 'applied' : 'new')} onChange={(newStatus) => updateJobStatus(job.id, newStatus)} compact />
                    </div>
                    <div className="job-card-buttons">
                      <button disabled={demo} className="btn btn-icon" aria-label="Edit job" title="Edit job" onClick={() => { setEditingJob(job); setEditTitle(job.title || ''); setEditCompany(job.company || ''); }}>
                        <Pencil size={15} />
                      </button>
                      {job.job_url && (
                        <a href={job.job_url} target="_blank" rel="noreferrer" className="btn btn-icon" aria-label="Open original posting" title="Open original posting">
                          <ExternalLink size={15} />
                        </a>
                      )}
                      <button className="btn btn-icon" aria-label="Tailor documents" title="Tailor documents" onClick={() => setSelectedJobDetails({ ...job, initialTab: 'studio' })}>
                        <Wand2 size={15} style={{ color: 'var(--primary-color)' }} />
                      </button>
                      <button disabled={demo} className="btn btn-icon" aria-label="Delete job" title="Delete job" onClick={() => handleDeleteJob(job)}>
                        <Trash2 size={15} color="#ef4444" />
                      </button>
                      <button className="btn btn-icon" title="Generate CV" onClick={() => handleJobsGenerateCV(job)} disabled={demo || generatingJobsDocs.has(`${job.id}-cv`)}>
                        {generatingJobsDocs.has(`${job.id}-cv`) ? <RefreshCw size={14} className="spinner" /> : <FileText size={14} color="#3b82f6" />}
                      </button>
                      <button className="btn btn-icon" title="Generate Cover Letter" onClick={() => handleJobsGenerateLetter(job)} disabled={demo || generatingJobsDocs.has(`${job.id}-letter`)}>
                        {generatingJobsDocs.has(`${job.id}-letter`) ? <RefreshCw size={14} className="spinner" /> : <Mail size={14} color="#10b981" />}
                      </button>
                      <button className="btn btn-icon" title="Generate CV & Letter" onClick={() => handleJobsGenerateBoth(job)} disabled={demo || generatingJobsDocs.has(`${job.id}-cv`) || generatingJobsDocs.has(`${job.id}-letter`)}>
                        {(generatingJobsDocs.has(`${job.id}-cv`) && generatingJobsDocs.has(`${job.id}-letter`)) ? <RefreshCw size={14} className="spinner" /> : <Layers size={14} style={{ color: 'var(--primary-color)' }} />}
                      </button>
                      {job.cv_url ? (
                        <a href={job.cv_url} target="_blank" rel="noreferrer" className="btn btn-icon" aria-label="Download CV" title="Download CV" style={{ color: '#3b82f6', fontSize: '0.65rem', gap: '2px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Download size={14} /><span>CV</span>
                        </a>
                      ) : (
                        <button className="btn btn-icon" disabled aria-label="CV not yet generated" title="CV not yet generated" style={{ opacity: 0.35, fontSize: '0.65rem', gap: '2px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'not-allowed' }}>
                          <Download size={14} /><span>CV</span>
                        </button>
                      )}
                      {job.letter_url ? (
                        <a href={job.letter_url} target="_blank" rel="noreferrer" className="btn btn-icon" aria-label="Download Cover Letter" title="Download Cover Letter" style={{ color: '#10b981', fontSize: '0.65rem', gap: '2px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Download size={14} /><span>CL</span>
                        </a>
                      ) : (
                        <button className="btn btn-icon" disabled aria-label="Cover Letter not yet generated" title="Cover Letter not yet generated" style={{ opacity: 0.35, fontSize: '0.65rem', gap: '2px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'not-allowed' }}>
                          <Download size={14} /><span>CL</span>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {sortedJobs.length > 0 && (
              <div className="jobs-pagination-bar">
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  Showing {Math.min((currentPage - 1) * itemsPerPage + 1, sortedJobs.length)} to {Math.min(currentPage * itemsPerPage, sortedJobs.length)} of {sortedJobs.length} jobs
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                  <select aria-label="Jobs per page" className="input-base" style={{ fontSize: '0.85rem', marginRight: '1rem', backgroundColor: 'var(--bg-color)', height: '32px' }}
                    value={itemsPerPage} onChange={e => { setItemsPerPage(parseInt(e.target.value)); setCurrentPage(1); }}>
                    <option value={10}>10 per page</option>
                    <option value={25}>25 per page</option>
                    <option value={50}>50 per page</option>
                    <option value={100}>100 per page</option>
                  </select>
                  <button className="btn btn-secondary" style={{ padding: '0.4rem 0.75rem', fontSize: '0.85rem' }}
                    disabled={currentPage === 1} onClick={() => setCurrentPage(p => Math.max(1, p - 1))}>Previous</button>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-primary)', margin: '0 0.5rem' }}>Page {currentPage} of {totalPages}</div>
                  <button className="btn btn-secondary" style={{ padding: '0.4rem 0.75rem', fontSize: '0.85rem' }}
                    disabled={currentPage === totalPages || totalPages === 0} onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}>Next</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
