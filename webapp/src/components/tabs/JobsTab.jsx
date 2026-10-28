import { useDemo } from '../../demoContext';
import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, RefreshCw, ChevronDown, MoreHorizontal, X } from 'lucide-react';
import { STATUS_ORDER, STATUS_CONFIG } from '../../constants/status';
import { RATINGS, RATING_GROUPS, RATING_DEFINITIONS, ratingLabel, ratingSummary, matchesStage, jobStatus, sourceLabel } from '../../constants/ratings';
import { MatchRating } from '../MatchEvidence';
import { AiTaskProgress } from '../AiTaskProgress';
import { germanLevelLabel } from '../../constants/german';
import { formatDateDisplay } from '../../constants/dates';

const stageOptions = [['new', 'New'], ['interested', 'Shortlisted'], ['pipeline', 'Applied'], ['All', 'All']];

export function JobsTab({
  jobs, loading, appliedCount, sortedJobs,
  unprocessedJobs, reprocessTaskId, reprocessProgress, handleStartReprocess,
  searchQuery, setSearchQuery, germanFilter, setGermanFilter,
  statusFilter, setStatusFilter, sourceFilter, setSourceFilter,
  scrapeDateFilter, setScrapeDateFilter, minimumRating, setMinimumRating,
  uniqueSources, uniqueScrapeDates, activeFilters, filteredOutCount, clearFilters, clearFilter,
  applyView, savedViews, saveCurrentView, deleteSavedView,
  selectedJobIds, selectedJobs, selectedCount, toggleSelectedJob, setVisibleSelection,
  batchGenProgress, batchGenSubmitting, batchGenTaskId, handleBatchGenerate, handleBatchGenerateForce, handleBatchGenerateCancel,
  batchMarkStatus, setBatchMarkStatus, batchMarkActive, handleBatchMark,
  sortConfig, setSortConfig, paginatedJobs, setSelectedJobDetails,
  updateJobStatus, setEditingJob, setEditTitle, setEditCompany, handleJobsGenerateCV, generatingJobsDocs, handleJobsGenerateLetter, handleJobsGenerateBoth,
  handleDeleteJob, onAddPosting,
  currentPage, setCurrentPage, itemsPerPage, setItemsPerPage, totalPages
}) {
  const demo = useDemo();
  const [unprocessedExpanded, setUnprocessedExpanded] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [openActions, setOpenActions] = useState(null);
  const actionsRef = useRef(null);
  const triggerRef = useRef(null);
  const [expandedGroups, setExpandedGroups] = useState({ Poor: false, Blocked: false });
  const failedAnalysisJobs = unprocessedJobs.filter(job => job.analysis_state === 'failed');
  const shortError = text => String(text || '').length > 160 ? `${String(text).slice(0, 157)}…` : String(text || '');
  useEffect(() => {
    if (openActions == null) return;
    const outside = event => {
      if (!actionsRef.current?.contains(event.target) && !triggerRef.current?.contains(event.target)) setOpenActions(null);
    };
    const escape = event => {
      if (event.key === 'Escape') { event.preventDefault(); setOpenActions(null); triggerRef.current?.focus(); }
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [openActions]);
  const closeAnd = action => { setOpenActions(null); triggerRef.current?.focus(); action(); };
  const menuAction = (label, action, disabled = false) => <button type="button" disabled={disabled} onClick={() => closeAnd(action)}>{label}</button>;
  return <div className="calm-jobs">
    <div className="calm-jobs-heading"><h2>Jobs</h2><button className="btn btn-primary" disabled={demo} onClick={onAddPosting}>Add posting</button></div>
    <p className="jobs-stats-summary-row">{jobs.length.toLocaleString()} jobs · {appliedCount} in the application pipeline · {sortedJobs.length} visible{filteredOutCount > 0 && ` · ${filteredOutCount} hidden by filters`}</p>
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
                    {reprocessProgress.status === 'queued' ? 'Waiting for an available worker…' : 'Processing with AI…'}{' '}
                    <span style={{ color: '#f59e0b', fontWeight: 600 }}>{reprocessProgress.processed} / {reprocessProgress.total}</span>
                    {reprocessProgress.failed > 0 && (
                      <span style={{ color: 'var(--error-color)', marginLeft: '0.5rem' }}>({reprocessProgress.failed} failed)</span>
                    )}
                  </span>
                ) : (
                  <span style={{ color: 'var(--text-primary)' }}>
                    <span style={{ color: '#f59e0b', fontWeight: 600 }}>{unprocessedJobs.length} job{unprocessedJobs.length !== 1 ? 's' : ''}</span>
                    {' '}awaiting analysis; failed jobs can be retried
                    {failedAnalysisJobs.length > 0 && (
                      <span style={{ color: 'var(--error-color)', marginLeft: '0.35rem' }}>
                        ({failedAnalysisJobs.length} failed)
                      </span>
                    )}
                  </span>
                )}
              </div>
              {failedAnalysisJobs.length > 0 && !reprocessTaskId && (
                <ul className="failed-analysis-list" aria-label="Jobs whose analysis failed" style={{ listStyle: 'none', margin: '0.5rem 0 0', padding: 0, display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                  {failedAnalysisJobs.slice(0, 5).map(job => (
                    <li key={job.id} style={{ fontSize: '0.8rem', overflowWrap: 'anywhere' }}>
                      <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{job.title || 'Untitled posting'}</span>
                      {job.company ? <span style={{ color: 'var(--text-secondary)' }}> · {job.company}</span> : null}
                      <span style={{ color: 'var(--error-color)' }}> — analysis failed{job.analysis_error ? `: ${shortError(job.analysis_error)}` : ''}</span>
                    </li>
                  ))}
                  {failedAnalysisJobs.length > 5 && (
                    <li style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>…and {failedAnalysisJobs.length - 5} more (Show lists them all).</li>
                  )}
                </ul>
              )}
              {reprocessTaskId && reprocessProgress && reprocessProgress.total > 0 && (
                  <AiTaskProgress
                  label="Job analysis (persists if you reload)"
                  processed={reprocessProgress.processed} total={reprocessProgress.total}
                  failed={reprocessProgress.failed} accent="#f59e0b"
                />
              )}
            </div>
            <div className="pending-analysis-banner-actions" style={{ display: 'flex', gap: '0.5rem', flexShrink: 0 }}>
              <button className="btn" onClick={() => handleStartReprocess()} disabled={demo || !!reprocessTaskId}
                style={{ fontSize: '0.78rem', padding: '0.3rem 0.75rem', backgroundColor: reprocessTaskId ? 'rgba(245,158,11,0.1)' : 'rgba(245,158,11,0.85)', color: reprocessTaskId ? '#f59e0b' : '#18181b', border: '1px solid rgba(245,158,11,0.4)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                {reprocessTaskId ? <><RefreshCw size={12} className="spinner" /> Processing…</> : <><RefreshCw size={12} /> {failedAnalysisJobs.length > 0 ? 'Retry / Process Now' : 'Process Now'}</>}
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
                    {['Title', 'Company', 'Source', 'Scraped', 'Analysis'].map(h => (
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
                      <td style={{ padding: '0.45rem 1rem', maxWidth: '320px', color: job.analysis_state === 'failed' ? 'var(--error-color)' : 'var(--text-secondary)' }}
                        title={job.analysis_error || undefined}>
                        {job.analysis_state === 'failed' ? `Failed${job.analysis_error ? `: ${shortError(job.analysis_error)}` : ''}` : 'Pending'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}


    <div className="calm-jobs-toolbar">
      <div className="jobs-stage-tabs" role="group" aria-label="Job stage">
        {stageOptions.map(([value, label]) => <button key={value} className={statusFilter === value ? 'active' : ''} aria-pressed={statusFilter === value} onClick={() => setStatusFilter(value)}>{label} <span>{jobs.filter(job => matchesStage(job, value)).length}</span></button>)}
      </div>
      <div className="calm-jobs-search"><input className="input-base" aria-label="Search jobs" placeholder="Search title, company or skill" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
        <button className="btn btn-secondary" aria-expanded={filtersOpen} aria-controls="jobs-filter-panel" onClick={() => setFiltersOpen(value => !value)}>Filter</button>
      </div>
    </div>
    {filtersOpen && <section id="jobs-filter-panel" className="calm-filter-panel" aria-label="Job filters">
      <label>German level<select aria-label="German level" className="input-base" value={germanFilter} onChange={e => setGermanFilter(e.target.value)}>{['All', 'none', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2', 'unknown'].map(level => <option key={level} value={level}>{level === 'All' ? 'Any level' : level === 'B1' ? 'B1 or below' : germanLevelLabel(level)}</option>)}</select></label>
      <label>Status<select aria-label="Status" className="input-base" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="All">Any status</option><option value="pipeline">Applied pipeline</option>{STATUS_ORDER.map(status => <option key={status} value={status}>{STATUS_CONFIG[status].label}</option>)}</select></label>
      <label>Source<select aria-label="Source" className="input-base" value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}><option value="All">Any source</option>{uniqueSources.map(source => <option key={source} value={source}>{sourceLabel(source)}</option>)}</select></label>
      <label>Found<select aria-label="Found" className="input-base" value={scrapeDateFilter} onChange={e => setScrapeDateFilter(e.target.value)}>{[['__all', 'Any date'], ['__today', 'Today'], ['__last7', 'Last 7 days (keeps pipeline)'], ['__recent21', 'Last 21 days (keeps pipeline)'], ['__last30', 'Last 30 days (keeps pipeline)']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}{uniqueScrapeDates.map(date => <option key={date} value={date}>{formatDateDisplay(date)}</option>)}</select></label>
      <label>Minimum rating<select aria-label="Minimum rating" className="input-base" value={minimumRating} onChange={e => setMinimumRating(e.target.value)}><option value="">Any rating, including unrated</option>{RATINGS.slice(0, -1).map(rating => <option key={rating} value={rating}>{rating} or better</option>)}</select></label>
      <label>Sort within rating<select aria-label="Sort within rating" className="input-base" value={`${sortConfig.key}:${sortConfig.direction}`} onChange={e => { const [key, direction] = e.target.value.split(':'); setSortConfig({ key, direction }); }}><option value="match_rating:desc">Best fit first</option><option value="date_scraped:desc">Newest first</option><option value="salary_yearly:desc">Highest salary first</option><option value="title:asc">Title A–Z</option><option value="company:asc">Company A–Z</option></select></label>
      <details className="calm-saved-views"><summary>Saved views</summary><button className="btn btn-secondary" onClick={() => { const name = window.prompt('Name this view'); if (name) saveCurrentView(name); }}>Save current view</button>{savedViews.map(view => <div key={view.name}><button onClick={() => applyView(view)}>{view.name}</button><button aria-label={`Delete saved view ${view.name}`} onClick={() => deleteSavedView(view.name)}><X size={14} /></button></div>)}</details>
      <button className="btn btn-secondary" onClick={clearFilters}>Clear filters</button>
    </section>}
    <div className="calm-filter-labels">{activeFilters.map(filter => <button className="calm-filter-label" key={filter.key} onClick={() => clearFilter(filter.key)} aria-label={`Remove ${filter.label}`}>{filter.label} <X size={12} /></button>)}</div>
    {selectedCount > 0 && <div className="calm-batch-bar" aria-label="Selected jobs">
      <span>{selectedCount} selected</span>
      <button className="btn btn-secondary" onClick={() => setVisibleSelection(selectedJobs, false)}>Clear selection</button>
      <button className="btn btn-secondary" onClick={() => setVisibleSelection(paginatedJobs, true)}>Select this page</button>
      <label>Mark as <select className="input-base" value={batchMarkStatus} onChange={e => setBatchMarkStatus(e.target.value)}>{STATUS_ORDER.map(status => <option key={status} value={status}>{STATUS_CONFIG[status].label}</option>)}</select></label>
      <button className="btn btn-secondary" disabled={demo || batchMarkActive} onClick={() => handleBatchMark(selectedJobs)}>Mark selected</button>
      <button className="btn btn-primary" disabled={demo || !!batchGenTaskId || batchGenSubmitting} onClick={() => handleBatchGenerate(selectedJobs)}>Generate documents</button>
      <button className="btn btn-secondary" disabled={demo || !!batchGenTaskId || batchGenSubmitting} onClick={() => handleBatchGenerateForce(selectedJobs)}>Regenerate documents</button>
    </div>}
    {(batchGenTaskId || batchGenSubmitting) && <div className="calm-operation-status" role="status"><span>Document generation {batchGenProgress?.stage === 'cancelling' ? 'stopping after running calls finish' : batchGenProgress?.status || 'starting'} · {batchGenProgress?.processed || 0} / {batchGenProgress?.total || 0} · {batchGenProgress?.failed || 0} failed</span><button className="btn btn-secondary" disabled={demo || !batchGenTaskId} onClick={handleBatchGenerateCancel}>Cancel generation</button></div>}
    {reprocessTaskId && !unprocessedJobs.length && <p role="status">Rating {reprocessProgress?.status || 'in progress'} · {reprocessProgress?.processed || 0} / {reprocessProgress?.total || 0}</p>}
    {loading ? <p role="status">Loading jobs…</p> : !jobs.length ? <p>No jobs tracked yet. Add a posting to get started.</p> : !sortedJobs.length ? <div className="jobs-empty-filtered"><h3>No jobs match these filters</h3><button className="btn btn-secondary" onClick={clearFilters}>Clear filters</button></div> : <>
      <div className="jobs-rating-groups">
        {RATING_GROUPS.map(group => {
          const groupJobs = paginatedJobs.filter(job => ratingLabel(job) === group);
          if (!groupJobs.length) return null;
          const collapsible = group === 'Poor' || group === 'Blocked';
          const open = !collapsible || expandedGroups[group];
          return <section key={group} className={`jobs-rating-group ${collapsible ? 'quiet-group' : ''}`} aria-label={`${group} jobs`}>
            <div className="rating-group-heading"><h3>{collapsible ? <button aria-expanded={open} onClick={() => setExpandedGroups(prev => ({ ...prev, [group]: !open }))}><ChevronDown size={16} style={{ transform: open ? 'none' : 'rotate(-90deg)' }} />{group} <span>{groupJobs.length}</span></button> : <>{group} <span>{groupJobs.length}</span></>}</h3><p>{RATING_DEFINITIONS[group]}{['Great', 'Good', 'Decent', 'Stretch'].includes(group) && ' Soft preference conflicts can lower the result.'}</p></div>
            {open && groupJobs.map(job => {
              const openJob = () => setSelectedJobDetails(job);
              const busyCV = generatingJobsDocs.has(`${job.id}-cv`), busyLetter = generatingJobsDocs.has(`${job.id}-letter`);
              const docs = job.cv_url && job.letter_url ? 'CV and letter ready' : job.cv_url ? 'CV ready' : job.letter_url ? 'Letter ready' : 'No documents yet';
              const actionsOpen = openActions === job.id;
              return <article key={job.id} className={`calm-job-row ${selectedJobIds.has(job.id) ? 'selected' : ''}`} tabIndex={0} role="link" aria-label={`Open ${job.title} at ${job.company}`} onClick={openJob} onKeyDown={event => { if (event.target === event.currentTarget && ['Enter', ' '].includes(event.key)) { event.preventDefault(); openJob(); } }}>
                <input type="checkbox" aria-label={`Select ${job.title}`} checked={selectedJobIds.has(job.id)} onClick={e => e.stopPropagation()} onChange={() => toggleSelectedJob(job.id)} />
                <div className="calm-job-main"><div className="calm-job-title">{job.title}</div><div className="calm-job-meta"><span className="calm-job-company">{job.company}</span>{job.location && ` · ${job.location}`}{job.work_model && ` · ${job.work_model}`}</div>
                  <div className="calm-job-facts">German: {germanLevelLabel(job.german_level ?? job.requires_german)} · {job.salary_yearly ? `€${Number(job.salary_yearly).toLocaleString('de-AT')} a year` : job.salary && job.salary !== 'Not Specified' ? job.salary : 'Salary not stated'} · {sourceLabel(job.source)}</div>
                  <p className="calm-job-evidence">{ratingSummary(job)}</p>
                </div>
                <div className="calm-job-rating"><MatchRating job={job} /></div>
                <div className="calm-job-state"><span>{STATUS_CONFIG[jobStatus(job)]?.label || jobStatus(job)}</span><div>{formatDateDisplay(job.date_scraped, 'Date unknown')}</div><span className={job.cv_url || job.letter_url ? 'docs-ready' : ''}>{busyCV || busyLetter ? 'Generating documents…' : docs}</span></div>
                <div className="calm-job-actions" onClick={e => e.stopPropagation()}>
                  <button type="button" className="btn btn-icon" aria-label={`Actions for ${job.title}`} aria-expanded={actionsOpen} aria-controls={`job-actions-${job.id}`} onClick={e => { triggerRef.current = e.currentTarget; setOpenActions(actionsOpen ? null : job.id); }}><MoreHorizontal size={19} /></button>
                  {actionsOpen && <div id={`job-actions-${job.id}`} ref={actionsRef} className="calm-row-menu" role="group" aria-label={`Actions for ${job.title}`}>
                    {menuAction('Open job', openJob)}
                    {job.job_url && <a href={job.job_url} target="_blank" rel="noreferrer">Open original posting</a>}
                    {job.cv_url && <a href={job.cv_url} target="_blank" rel="noreferrer">Download CV</a>}
                    {job.letter_url && <a href={job.letter_url} target="_blank" rel="noreferrer">Download letter</a>}
                    <label>Change status<select className="input-base" aria-label={`Status for ${job.title}`} disabled={demo} value={jobStatus(job)} onChange={e => closeAnd(() => updateJobStatus(job.id, e.target.value))}>{STATUS_ORDER.map(status => <option key={status} value={status}>{STATUS_CONFIG[status].label}</option>)}</select></label>
                    {menuAction('Tailor documents', () => setSelectedJobDetails({ ...job, initialTab: 'studio' }))}
                    {menuAction('Generate CV', () => handleJobsGenerateCV(job), demo || busyCV)}
                    {menuAction('Generate letter', () => handleJobsGenerateLetter(job), demo || busyLetter)}
                    {menuAction('Generate CV and letter', () => handleJobsGenerateBoth(job), demo || busyCV || busyLetter)}
                    {menuAction(['Needs re-rating', 'Unrated'].includes(group) ? 'Re-rate' : 'Rate again', () => handleStartReprocess(job.id), demo || !!reprocessTaskId)}
                    {menuAction('Edit job', () => { setEditingJob(job); setEditTitle(job.title || ''); setEditCompany(job.company || ''); }, demo)}
                    {menuAction('Delete job', () => handleDeleteJob(job), demo)}
                  </div>}
                </div>
              </article>;
            })}
          </section>;
        })}
      </div>
      <div className="jobs-pagination-bar"><span>Showing {Math.min((currentPage - 1) * itemsPerPage + 1, sortedJobs.length)}–{Math.min(currentPage * itemsPerPage, sortedJobs.length)} of {sortedJobs.length} jobs</span><div>
        <select aria-label="Jobs per page" className="input-base" value={itemsPerPage} onChange={e => { setItemsPerPage(Number(e.target.value)); setCurrentPage(1); }}>{[10, 25, 50, 100].map(size => <option key={size} value={size}>{size} per page</option>)}</select>
        <button className="btn btn-secondary" disabled={currentPage === 1} onClick={() => setCurrentPage(page => page - 1)}>Previous</button><span>Page {currentPage} of {totalPages}</span><button className="btn btn-secondary" disabled={currentPage >= totalPages} onClick={() => setCurrentPage(page => page + 1)}>Next</button>
      </div></div>
    </>}
  </div>;
}
