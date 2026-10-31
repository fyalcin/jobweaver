import React, { useEffect } from 'react';
import { X, RefreshCw } from 'lucide-react';

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
  const isOpen = editingJob !== null && editingJob !== undefined && editingJob !== false;

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e) => {
      if (e.key === 'Escape' && !savingEdit) {
        setEditingJob(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, savingEdit, setEditingJob]);

  if (!isOpen) return null;

  return (
    <div
      className="modal-backdrop"
      onClick={() => { if (!savingEdit) setEditingJob(null); }}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.55)',
        backdropFilter: 'blur(3px)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1rem',
      }}
    >
      <div
        className="card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-job-modal-title"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%',
          maxWidth: '480px',
          backgroundColor: 'var(--surface-card)',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        <div style={{ marginBottom: '1.25rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 id="edit-job-modal-title" className="card-title" style={{ margin: 0 }}>
            Edit Job Details
          </h2>
          <button
            type="button"
            className="btn-icon"
            aria-label="Close modal"
            onClick={() => setEditingJob(null)}
            disabled={savingEdit}
          >
            <X size={18} />
          </button>
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="edit-job-title-input">Position Name</label>
          <input
            id="edit-job-title-input"
            type="text"
            className="input-base"
            autoFocus
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !savingEdit) handleSaveEdit(); }}
            placeholder="Job Title"
          />
        </div>
        <div className="form-group" style={{ marginBottom: '1.5rem' }}>
          <label className="form-label" htmlFor="edit-job-company-input">Company Name</label>
          <input
            id="edit-job-company-input"
            type="text"
            className="input-base"
            value={editCompany}
            onChange={(e) => setEditCompany(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !savingEdit) handleSaveEdit(); }}
            placeholder="Company Name"
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.65rem' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setEditingJob(null)}
            disabled={savingEdit}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSaveEdit}
            disabled={savingEdit}
          >
            {savingEdit ? <RefreshCw className="spinner" size={16} /> : null}
            <span>{savingEdit ? 'Saving…' : 'Save Changes'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
