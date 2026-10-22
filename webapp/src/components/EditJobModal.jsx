import React from 'react';
import { XCircle, RefreshCw } from 'lucide-react';

export function EditJobModal({
  editingJob,
  setEditingJob,
  editTitle,
  setEditTitle,
  editCompany,
  setEditCompany,
  savingEdit,
  handleSaveEdit
}) {
  if (!editingJob) return null;

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
      <div className="card" style={{ width: '100%', maxWidth: '500px', backgroundColor: 'var(--surface-color)' }}>
        <h2 className="card-title" style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          Edit Job
          <button className="btn btn-icon" onClick={() => setEditingJob(null)}><XCircle size={20} /></button>
        </h2>
        <div className="form-group">
          <label className="form-label">Position Name</label>
          <input type="text" className="input-base" value={editTitle} onChange={e => setEditTitle(e.target.value)} placeholder="Job Title" />
        </div>
        <div className="form-group" style={{ marginBottom: '2rem' }}>
          <label className="form-label">Company Name</label>
          <input type="text" className="input-base" value={editCompany} onChange={e => setEditCompany(e.target.value)} placeholder="Company Name" />
        </div>
        <div style={{ display: 'flex', gap: '1rem' }}>
          <button className="btn btn-primary" style={{ flex: 1, padding: '0.8rem' }} onClick={handleSaveEdit} disabled={savingEdit}>
            {savingEdit ? <RefreshCw className="spinner" size={18} /> : null}
            {savingEdit ? ' Saving...' : 'Save Changes'}
          </button>
          <button className="btn btn-secondary" style={{ flex: 1, padding: '0.8rem' }} onClick={() => setEditingJob(null)} disabled={savingEdit}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
