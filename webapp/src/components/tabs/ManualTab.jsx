import React from 'react';
import { FileText, RefreshCw, Search, AlertCircle, Briefcase, Mail, Sparkles, X } from 'lucide-react';
import { PageHeader } from '../PageHeader';

export function ManualTab({
  manualUrl, setManualUrl,
  fetchingUrl, fetchUrlWarning, setFetchUrlWarning, handleFetchJobUrl,
  manualTitle, setManualTitle,
  manualCompany, setManualCompany,
  manualCvProfile, setManualCvProfile,
  manualCompact, setManualCompact,
  cvProfiles,
  manualDescription, setManualDescription,
  addingManualJob, handleAddManualJob,
  manualNotice, setManualNotice, retryManualAnalysis
}) {
  return (
    <div className="page-shell">
      <PageHeader
        title="Add Job"
        subtitle="Paste a posting URL or job description to evaluate fit and save it to your Jobs workspace."
      />
      <div className="page-body-narrow">
        <div className="card" style={{ marginBottom: '2rem' }}>
          {/* URL auto-fetch */}
          <div className="form-group" style={{ marginBottom: '1.25rem' }}>
            <label className="form-label">Job URL (Optional — auto-fills fields below)</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <input type="url" className="input-base" style={{ flex: 1, minWidth: 0 }}
                value={manualUrl} onChange={e => { setManualUrl(e.target.value); setFetchUrlWarning(null); }}
                placeholder="Paste job posting URL..." />
              <button className="btn btn-primary" onClick={handleFetchJobUrl} disabled={fetchingUrl || !manualUrl.trim()} style={{ whiteSpace: 'nowrap', minWidth: '90px' }}>
                {fetchingUrl ? <RefreshCw className="spinner" size={16} /> : <Search size={16} />}
                &nbsp;Fetch
              </button>
            </div>
            {fetchUrlWarning && (
              <div style={{ marginTop: '0.4rem', fontSize: '0.8rem', color: 'var(--warning-color)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <AlertCircle size={13} /> {fetchUrlWarning}
              </div>
            )}
          </div>
          <div className="manual-entry-top" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '1rem', marginBottom: '1rem' }}>
            <div className="form-group">
              <label className="form-label">Job Title (Optional)</label>
              <input type="text" className="input-base" value={manualTitle} onChange={e => setManualTitle(e.target.value)} placeholder="e.g. Senior Frontend Engineer" />
            </div>
            <div className="form-group">
              <label className="form-label">Company (Optional)</label>
              <input type="text" className="input-base" value={manualCompany} onChange={e => setManualCompany(e.target.value)} placeholder="e.g. Acme Corp" />
            </div>
          </div>
          <div className="form-group" style={{ marginBottom: '1rem' }}>
            <label className="form-label">Role Family</label>
            <select className="input-base" value={manualCvProfile} onChange={e => setManualCvProfile(e.target.value)}>
              <option value="">Choose automatically from job description</option>
              {cvProfiles.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
            <small style={{ color: 'var(--text-secondary)', display: 'block', marginBottom: '0.5rem' }}>Saved with the manual job and used when drafting tailored CVs.</small>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.85rem' }}>
              <input
                type="checkbox"
                checked={manualCompact || false}
                onChange={e => setManualCompact(e.target.checked)}
              />
              <span>Select fewer CV evidence bullets</span>
            </label>
          </div>
          <div className="form-group">
            <label className="form-label">Job Description (Required)</label>
            <textarea className="input-base" style={{ resize: 'vertical', minHeight: '115px', padding: '0.55rem 0.65rem', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.45' }}
              value={manualDescription} onChange={e => setManualDescription(e.target.value)} placeholder="Paste the full job description here..." />
          </div>
          <div className="manual-submit-bar">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => handleAddManualJob(null)}
              disabled={addingManualJob || !manualDescription.trim()}
            >
              {addingManualJob ? <RefreshCw className="spinner" size={16} /> : <Briefcase size={16} />}
              <span>{addingManualJob ? 'Saving & Analyzing…' : 'Save & Analyze Job'}</span>
            </button>
            <div className="manual-quick-draft-group">
              <span className="manual-quick-draft-label">Or one-off draft:</span>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => handleAddManualJob('all')}
                disabled={addingManualJob || !manualDescription.trim()}
              >
                <Sparkles size={13} />
                <span>CV &amp; Letter</span>
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => handleAddManualJob('cv')}
                disabled={addingManualJob || !manualDescription.trim()}
              >
                <FileText size={13} />
                <span>CV</span>
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => handleAddManualJob('letter')}
                disabled={addingManualJob || !manualDescription.trim()}
              >
                <Mail size={13} />
                <span>Letter</span>
              </button>
            </div>
          </div>
          {manualNotice && (
            <div role="alert" className="manual-notice" style={{ marginTop: '1rem', padding: '0.75rem 1rem', borderRadius: '8px', display: 'flex', alignItems: 'flex-start', gap: '0.6rem', flexWrap: 'wrap', fontSize: '0.85rem',
              border: `1px solid ${manualNotice.kind === 'analysis' ? 'rgba(245,158,11,0.35)' : 'rgba(239,68,68,0.35)'}`,
              backgroundColor: manualNotice.kind === 'analysis' ? 'rgba(245,158,11,0.07)' : 'rgba(239,68,68,0.07)' }}>
              <AlertCircle size={16} color={manualNotice.kind === 'analysis' ? '#f59e0b' : 'var(--error-color)'} style={{ flexShrink: 0, marginTop: '0.1rem' }} />
              <div style={{ flex: 1, minWidth: '12rem' }}>
                <strong>{manualNotice.message}</strong>
                <div style={{ color: 'var(--text-secondary)', marginTop: '0.2rem', overflowWrap: 'anywhere' }}>Reason: {manualNotice.reason}</div>
                {manualNotice.kind === 'analysis' && (
                  <div style={{ color: 'var(--text-secondary)', marginTop: '0.2rem' }}>The posting is in the Jobs list under failed analyses. Retry here or from there.</div>
                )}
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', flexShrink: 0 }}>
                {manualNotice.kind === 'analysis' && retryManualAnalysis && (
                  <button type="button" className="btn btn-secondary" onClick={retryManualAnalysis} style={{ fontSize: '0.78rem', padding: '0.3rem 0.75rem' }}>
                    <RefreshCw size={12} />&nbsp;Retry analysis
                  </button>
                )}
                <button type="button" className="btn btn-secondary" aria-label="Dismiss message" title="Dismiss" onClick={() => setManualNotice(null)} style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem' }}>
                  <X size={12} />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
