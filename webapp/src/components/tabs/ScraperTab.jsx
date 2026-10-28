import React from 'react';
import { Settings, RefreshCw, Search, AlertCircle, CheckCircle2, ChevronDown, Info } from 'lucide-react';
import { AiTaskProgress } from '../AiTaskProgress';
import { formatDateDisplay, formatDateTimeDisplay } from '../../constants/dates';

export function ScraperTab({
  source, setSource,
  karriereKeyword, setKarriereKeyword,
  keywords, setKeywords,
  resultsLimit, setResultsLimit,
  hoursOld, setHoursOld,
  distance, setDistance,
  scraping, handleScrape,
  unprocessedJobs, reprocessTaskId, reprocessProgress, handleStartReprocess,
  activeScrapeTaskId, scrapeAiProgress, scrapeStatus, scrapeLogs, fetchLogs
}) {
  return (
    <div style={{ maxWidth: '800px', margin: '0 auto' }}>
      <div className="card" style={{ marginBottom: '2rem' }}>
        <h2 className="card-title"><Settings size={20} /> Scraper Settings</h2>
        <div className="form-group">
          <label className="form-label">Job Source</label>
          <select className="input-base" value={source} onChange={e => setSource(e.target.value)}>
            <optgroup label="Employers' own job feeds (free, no key)">
              <option value="company-feeds">Company feeds (companies.json)</option>
            </optgroup>
            <optgroup label="LinkedIn">
              <option value="linkedin-apify">LinkedIn (Apify)</option>
            </optgroup>
            <optgroup label="Karriere.at">
              <option value="karriere-apify">Karriere (Apify)</option>
            </optgroup>
          </select>
        </div>
        {source === 'company-feeds' ? (
          <div className="form-group">
            <p className="form-label">Reads every employer in your companies.json (see companies.example.json). Keywords and limits do not apply.</p>
          </div>
        ) : source.startsWith('karriere') ? (
          <div className="form-group">
            <label className="form-label">Job Keywords (comma-separated)</label>
            <textarea className="input-base" style={{ resize: 'vertical', minHeight: '60px', padding: '0.5rem', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.4' }}
              value={karriereKeyword} onChange={e => setKarriereKeyword(e.target.value)} placeholder="e.g. Python, Data Science, Software Developer" />
          </div>
        ) : (
          <div className="form-group">
            <label className="form-label">Job Keywords</label>
            <textarea className="input-base" style={{ resize: 'vertical', minHeight: '60px', padding: '0.5rem', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.4' }}
              value={keywords} onChange={e => setKeywords(e.target.value)} placeholder="e.g. data science OR python OR backend developer" />
          </div>
        )}
        {source === 'company-feeds' ? null : source.startsWith('karriere') ? (
          <div className="form-group">
            <label className="form-label">Results Limit</label>
            <input type="number" className="input-base" value={resultsLimit} onChange={e => setResultsLimit(parseInt(e.target.value))} />
          </div>
        ) : (
          <div className="scraper-params-grid">
            <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label className="form-label">Results Limit</label>
              <input type="number" className="input-base" style={{ width: '100%' }} value={resultsLimit} onChange={e => setResultsLimit(parseInt(e.target.value))} />
            </div>
            <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label className="form-label">Max Age (Hours)</label>
              <input type="number" className="input-base" style={{ width: '100%' }} value={hoursOld} onChange={e => setHoursOld(parseInt(e.target.value))} />
            </div>
            <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <label className="form-label">Distance (km)</label>
              <input type="number" className="input-base" style={{ width: '100%' }} value={distance} onChange={e => setDistance(parseInt(e.target.value))} />
            </div>
          </div>
        )}
        <button className="btn btn-primary" style={{ width: '100%', marginTop: '1rem' }} onClick={handleScrape} disabled={scraping}>
          {scraping ? <RefreshCw className="spinner" size={18} /> : <Search size={18} />}
          {scraping ? 'Scraping...' : 'Scrape Jobs'}
        </button>
      </div>

      {/* Processing Queue */}
      <div className="card" style={{ marginBottom: '2rem' }}>
        <h2 className="card-title" style={{ marginBottom: '1rem' }}>
          <AlertCircle size={20} color={unprocessedJobs.length > 0 ? '#f59e0b' : 'var(--text-secondary)'} />
          Processing Queue
          <span style={{
            marginLeft: '0.5rem', fontSize: '0.78rem', fontWeight: 600,
            padding: '0.15rem 0.5rem', borderRadius: '999px',
            background: unprocessedJobs.length > 0 ? 'rgba(245,158,11,0.15)' : 'var(--bg-secondary)',
            color: unprocessedJobs.length > 0 ? '#f59e0b' : 'var(--text-secondary)',
            border: `1px solid ${unprocessedJobs.length > 0 ? 'rgba(245,158,11,0.35)' : 'var(--border-color)'}`,
          }}>
            {unprocessedJobs.length}
          </span>
        </h2>

        {unprocessedJobs.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '1.5rem 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            <CheckCircle2 size={28} style={{ margin: '0 auto 0.5rem', display: 'block', opacity: 0.4 }} />
            All scraped jobs have been processed.
          </div>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '0.85rem', gap: '1rem' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  {reprocessTaskId && reprocessProgress ? (
                    <span style={{ color: 'var(--text-primary)' }}>
                      {reprocessProgress.status === 'queued' ? 'Waiting for an available worker…' : 'Processing with AI…'}{' '}
                      <span style={{ color: '#f59e0b', fontWeight: 600 }}>{reprocessProgress.processed} / {reprocessProgress.total}</span>
                      {reprocessProgress.failed > 0 && (
                        <span style={{ color: 'var(--error-color)', marginLeft: '0.5rem' }}>({reprocessProgress.failed} failed)</span>
                      )}
                    </span>
                  ) : (
                    <span>
                      <span style={{ color: '#f59e0b', fontWeight: 600 }}>{unprocessedJobs.length} job{unprocessedJobs.length !== 1 ? 's' : ''}</span>
                      {' '}awaiting AI analysis
                    </span>
                  )}
                </div>
                {reprocessTaskId && reprocessProgress && reprocessProgress.total > 0 && (
                  <AiTaskProgress
                    label="Job analysis (persists if you reload)"
                    processed={reprocessProgress.processed}
                    total={reprocessProgress.total}
                    failed={reprocessProgress.failed}
                    accent="#f59e0b"
                  />
                )}
              </div>
              <button
                className="btn"
                onClick={handleStartReprocess}
                disabled={!!reprocessTaskId}
                style={{
                  fontSize: '0.78rem', padding: '0.35rem 0.9rem', flexShrink: 0,
                  backgroundColor: reprocessTaskId ? 'rgba(245,158,11,0.1)' : 'rgba(245,158,11,0.85)',
                  color: reprocessTaskId ? '#f59e0b' : '#18181b',
                  border: '1px solid rgba(245,158,11,0.4)',
                  display: 'flex', alignItems: 'center', gap: '5px',
                }}
              >
                {reprocessTaskId
                  ? <><RefreshCw size={12} className="spinner" /> Processing…</>
                  : <><RefreshCw size={12} /> Process Now</>
                }
              </button>
            </div>

            <div style={{ overflowX: 'auto', borderRadius: '6px', border: '1px solid var(--border-color)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)', background: 'var(--bg-secondary)' }}>
                    {['Title', 'Company', 'Source', 'Scraped'].map(h => (
                      <th key={h} style={{ padding: '0.5rem 1rem', textAlign: 'left', color: 'var(--text-secondary)', fontWeight: 500, whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {unprocessedJobs.map((job, i) => (
                    <tr key={job.id} style={{ borderBottom: i < unprocessedJobs.length - 1 ? '1px solid var(--border-color)' : 'none' }}>
                      <td style={{ padding: '0.45rem 1rem', maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{job.title || '—'}</td>
                      <td style={{ padding: '0.45rem 1rem', whiteSpace: 'nowrap' }}>{job.company || '—'}</td>
                      <td style={{ padding: '0.45rem 1rem', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>{job.source || '—'}</td>
                      <td style={{ padding: '0.45rem 1rem', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>{formatDateDisplay(job.date_scraped, '—')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">
          <Info size={20} />
          {activeScrapeTaskId ? 'Live Scraping Logs' : 'Scraping Logs History'}
          {activeScrapeTaskId && <RefreshCw className="spinner" size={16} style={{ marginLeft: '0.5rem', opacity: 0.6 }} />}
        </h2>
        {activeScrapeTaskId && scrapeStatus === 'queued' && <p>Scraping is queued, waiting for an available worker.</p>}
        {scrapeAiProgress && scrapeAiProgress.total > 0 && (
          <div style={{ marginBottom: '0.85rem' }}>
            <AiTaskProgress
              label="AI job analysis during this scrape (persists if you reload)"
              processed={scrapeAiProgress.processed}
              total={scrapeAiProgress.total}
              failed={scrapeAiProgress.failed}
              accent="#0ea5e9"
            />
          </div>
        )}
        <div style={{ maxHeight: '180px', overflowY: 'auto', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          {scrapeLogs.length === 0 ? (
            <div style={{ padding: '1rem', textAlign: 'center' }}>No logs yet</div>
          ) : (
            <ul style={{ listStyleType: 'none', padding: 0, margin: 0 }}>
              {scrapeLogs.map((log, i) => (
                <li key={i} style={{
                  borderBottom: '1px solid var(--border-color)', padding: '0.5rem 0',
                  color: log.level === 'warning' ? 'var(--warning-color)' : log.level === 'error' ? 'var(--danger-color)' : log.level === 'success' ? 'var(--success-color)' : 'inherit'
                }}>
                  <div style={{ opacity: 0.7, fontSize: '0.75rem', marginBottom: '2px' }}>{formatDateTimeDisplay(log.timestamp)}</div>
                  <div>{log.message}</div>
                </li>
              ))}
            </ul>
          )}
          <button className="btn" style={{ width: '100%', marginTop: '0.5rem', padding: '0.4rem', fontSize: '0.8rem' }} onClick={fetchLogs}>
            <RefreshCw size={14} style={{ marginRight: '4px' }} /> Refresh Logs
          </button>
        </div>
      </div>
    </div>
  );
}
