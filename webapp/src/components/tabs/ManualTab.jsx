import React from 'react';
import { FileText, RefreshCw, Search, AlertCircle, Briefcase, Mail, Sparkles } from 'lucide-react';

export function ManualTab({
  manualUrl, setManualUrl,
  fetchingUrl, fetchUrlWarning, setFetchUrlWarning, handleFetchJobUrl,
  manualTitle, setManualTitle,
  manualCompany, setManualCompany,
  manualCvProfile, setManualCvProfile,
  manualCompact, setManualCompact,
  cvProfiles,
  manualDescription, setManualDescription,
  addingManualJob, handleAddManualJob
}) {
  return (
    <div style={{ maxWidth: '800px', margin: '0 auto' }}>
      <div className="card" style={{ marginBottom: '2rem' }}>
        <h2 className="card-title"><FileText size={20} /> Manual Job Entry / Document Generation</h2>
        {/* URL auto-fetch */}
        <div className="form-group" style={{ marginBottom: '1.25rem' }}>
          <label className="form-label">Job URL (Optional — auto-fills fields below)</label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <input type="url" className="input-base" style={{ flex: 1, minWidth: 0 }}
              value={manualUrl} onChange={e => { setManualUrl(e.target.value); setFetchUrlWarning(null); }}
              placeholder="Link to a job posting (career site, karriere.at, Greenhouse, Personio, ...)" />
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
          <label className="form-label">CV Profile</label>
          <select className="input-base" value={manualCvProfile} onChange={e => setManualCvProfile(e.target.value)}>
            <option value="">Automatic selection from job description</option>
            {cvProfiles.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
          <small style={{ color: 'var(--text-secondary)', display: 'block', marginBottom: '0.5rem' }}>Saved with the manual job and used for CV generation.</small>
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
          <textarea className="input-base" style={{ resize: 'vertical', minHeight: '100px', padding: '0.5rem', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.4' }}
            value={manualDescription} onChange={e => setManualDescription(e.target.value)} placeholder="Paste the full job description here..." />
        </div>
        <div className="manual-action-row">
          <button
            type="button"
            className="btn btn-primary btn-generate-both"
            onClick={() => handleAddManualJob('all')}
            disabled={addingManualJob || !manualDescription.trim()}
          >
            {addingManualJob ? <RefreshCw className="spinner" size={16} /> : <Sparkles size={16} />}
            <span>Generate Both</span>
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => handleAddManualJob('cv')}
            disabled={addingManualJob || !manualDescription.trim()}
          >
            {addingManualJob ? <RefreshCw className="spinner" size={16} /> : <FileText size={16} />}
            <span>Generate CV</span>
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => handleAddManualJob('letter')}
            disabled={addingManualJob || !manualDescription.trim()}
          >
            {addingManualJob ? <RefreshCw className="spinner" size={16} /> : <Mail size={16} />}
            <span>Generate Cover Letter</span>
          </button>
          <button
            type="button"
            className="btn btn-secondary manual-btn-add-db"
            onClick={() => handleAddManualJob(null)}
            disabled={addingManualJob || !manualDescription.trim()}
          >
            {addingManualJob ? <RefreshCw className="spinner" size={16} /> : <Briefcase size={16} />}
            <span>Add to Database</span>
          </button>
        </div>
      </div>
    </div>
  );
}
