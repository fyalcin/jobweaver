import { MatchRating } from '../MatchEvidence';
import { compareBestFit, ratingSummary } from '../../constants/ratings';
import { useDemo } from '../../demoContext';
import React from 'react';
import { CalendarDays, CheckCircle2, RefreshCw, Briefcase, ExternalLink, Download, FileText, Mail, XCircle, Wand2 } from 'lucide-react';
import { StatusBadge } from '../StatusControls';
import { formatDateDisplay } from '../../constants/dates';
import { PageHeader } from '../PageHeader';

function getFriendlyDateLabel(dateStr) {
  if (!dateStr) return '';
  const now = new Date();
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;

  const yesterdayDate = new Date(Date.now() - 86400000);
  const yesterdayStr = `${yesterdayDate.getFullYear()}-${String(yesterdayDate.getMonth() + 1).padStart(2, '0')}-${String(yesterdayDate.getDate()).padStart(2, '0')}`;

  const formatted = formatDateDisplay(dateStr);
  if (dateStr === todayStr) return `${formatted} (Today)`;
  if (dateStr === yesterdayStr) return `${formatted} (Yesterday)`;
  return formatted;
}

export function DailyTab({
  dailyDates, selectedDailyDate, setSelectedDailyDate,
  dailyJobs, dailyLoading, generatingDocs,
  updateJobStatus, setSelectedJobDetails, handleGenerateDocs
}) {
  const demo = useDemo();
  const recentDates = dailyDates.slice(0, 4);
  const hasOlderDates = dailyDates.length > 4;

  return (
    <div className="page-shell">
      <PageHeader
        title="Daily Matches"
        badge={dailyJobs.length > 0 ? `${dailyJobs.length} qualifying` : undefined}
        subtitle="Qualifying postings from each daily run using your configured minimum rating and eligibility checks."
        actions={
          dailyJobs.length > 0 ? (
            <button
              disabled={demo}
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                dailyJobs.filter(j => j.status !== 'applied').forEach(j => updateJobStatus(j.id, 'applied'));
              }}
            >
              <CheckCircle2 size={14} />
              <span>Mark All Applied</span>
            </button>
          ) : null
        }
      />

      <div className="card" style={{ marginBottom: '1.5rem' }}>
        {dailyDates.length === 0 ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <CalendarDays size={40} style={{ margin: '0 auto 1rem', opacity: 0.4, display: 'block' }} />
            <p>No daily scrape reports found yet.</p>
          </div>
        ) : (
          <div className="daily-date-bar">
            <div className="daily-date-pills-group">
              <span className="daily-date-label">Recent:</span>
              <div className="daily-date-pills">
                {recentDates.map(date => {
                  const isSelected = selectedDailyDate === date;
                  return (
                    <button
                      key={date}
                      type="button"
                      className={`daily-date-pill ${isSelected ? 'active' : ''}`}
                      onClick={() => setSelectedDailyDate(date)}
                    >
                      <span>{getFriendlyDateLabel(date)}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {hasOlderDates && (
              <div className="daily-older-group">
                <label htmlFor="daily-history-select" className="daily-date-label">History:</label>
                <select
                  id="daily-history-select"
                  className="input-base daily-history-select"
                  value={selectedDailyDate}
                  onChange={(e) => setSelectedDailyDate(e.target.value)}
                >
                  <optgroup label="Recent Runs">
                    {recentDates.map(d => (
                      <option key={d} value={d}>{getFriendlyDateLabel(d)}</option>
                    ))}
                  </optgroup>
                  <optgroup label={`Older Reports (${dailyDates.length - 4})`}>
                    {dailyDates.slice(4).map(d => (
                      <option key={d} value={d}>{getFriendlyDateLabel(d)}</option>
                    ))}
                  </optgroup>
                </select>
              </div>
            )}
          </div>
        )}
      </div>

      {dailyLoading ? (
        <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <RefreshCw className="spinner" size={32} style={{ margin: '0 auto 1rem', display: 'block' }} />
          <p>Loading results for {getFriendlyDateLabel(selectedDailyDate) || selectedDailyDate}...</p>
        </div>
      ) : dailyJobs.length === 0 && selectedDailyDate ? (
        <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <Briefcase size={40} style={{ margin: '0 auto 1rem', opacity: 0.4, display: 'block' }} />
          <p>No qualifying jobs found for {getFriendlyDateLabel(selectedDailyDate) || selectedDailyDate}.</p>
        </div>
      ) : (
        <>
          {dailyJobs.length > 0 && (
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
              <strong>{dailyJobs.length}</strong> qualifying job{dailyJobs.length !== 1 ? 's' : ''} on {getFriendlyDateLabel(selectedDailyDate) || selectedDailyDate}
            </p>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
            {[...dailyJobs].sort(compareBestFit).map(job => (
              <div key={job.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.5rem' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <button className="daily-job-title" onClick={() => setSelectedJobDetails(job)}>{job.title}</button>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '2px' }}>{job.company}</div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px', flexShrink: 0 }}>
                    <MatchRating job={job} />
                    {job.status && job.status !== 'new' && <StatusBadge status={job.status} />}
                  </div>
                </div>
                {job.location && <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{job.location}</div>}
                {job.salary_yearly ? (
                  <div style={{ fontSize: '0.8rem', color: 'var(--success-color)', fontWeight: 500 }}>€{Number(job.salary_yearly).toLocaleString('de-AT')} / year</div>
                ) : job.salary && job.salary !== 'Not Specified' && (
                  <div style={{ fontSize: '0.8rem', color: 'var(--success-color)', fontWeight: 500 }}>{job.salary}</div>
                )}
                <p className="calm-job-evidence">{ratingSummary(job)}</p>
                {job.summary && (
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: '1.4', borderTop: '1px solid var(--border-color)', paddingTop: '0.5rem', marginTop: '0.25rem' }}>
                    {job.summary.length > 140 ? job.summary.substring(0, 140) + '…' : job.summary}
                  </div>
                )}
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: 'auto', paddingTop: '0.75rem', flexWrap: 'wrap' }}>
                  {job.job_url && (
                    <a href={job.job_url} target="_blank" rel="noreferrer" className="btn btn-secondary daily-doc-btn">
                      <ExternalLink size={13} /> View
                    </a>
                  )}
                  {job.cv_url ? (
                    <a href={job.cv_url} target="_blank" rel="noreferrer" className="btn btn-secondary daily-doc-btn">
                      <Download size={13} /> CV
                    </a>
                  ) : (
                    <button className="btn btn-secondary daily-doc-btn" disabled style={{ opacity: 0.4 }}>
                      <FileText size={13} /> CV
                    </button>
                  )}
                  {job.letter_url ? (
                    <a href={job.letter_url} target="_blank" rel="noreferrer" className="btn btn-secondary daily-doc-btn">
                      <Download size={13} /> Letter
                    </a>
                  ) : (
                    <button className="btn btn-secondary daily-doc-btn" disabled style={{ opacity: 0.4 }}>
                      <Mail size={13} /> Letter
                    </button>
                  )}
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.4rem' }}>
                  <button disabled={demo}
                    onClick={() => updateJobStatus(job.id, job.status === 'applied' ? 'new' : 'applied')}
                    className={`btn daily-action-btn ${job.status === 'applied' ? 'daily-btn-applied' : 'btn-primary'}`}
                    style={{ flex: 1 }}
                  >
                    <CheckCircle2 size={14} />
                    {job.status === 'applied' ? 'Applied ✓' : 'Apply'}
                  </button>
                  <button disabled={demo}
                    onClick={() => updateJobStatus(job.id, job.status === 'not_interested' ? 'new' : 'not_interested')}
                    className={`btn daily-action-btn ${job.status === 'not_interested' ? 'daily-btn-skipped' : 'btn-secondary'}`}
                    style={{ flex: 1 }}
                  >
                    <XCircle size={14} />
                    {job.status === 'not_interested' ? 'Skipped' : 'Skip'}
                  </button>
                  <button
                    onClick={() => handleGenerateDocs(job)}
                    disabled={demo || generatingDocs.has(job.id)}
                    title={generatingDocs.has(job.id) ? 'Generating…' : 'Generate CV & Letter'}
                    className="btn btn-secondary daily-action-btn"
                    style={{
                      padding: '0 0.65rem',
                      color: (job.cv_url && job.letter_url) ? 'var(--success-color)' : 'var(--primary-light)',
                    }}
                  >
                    {generatingDocs.has(job.id)
                      ? <RefreshCw size={14} className="spinner" />
                      : (job.cv_url && job.letter_url)
                        ? <CheckCircle2 size={14} />
                        : <Wand2 size={14} />
                    }
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
