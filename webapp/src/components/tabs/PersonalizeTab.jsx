import React, { useState, useEffect } from 'react';
import { User, RefreshCw, Save, RotateCcw, FileText, AlertTriangle, MessageSquareText, Lock } from 'lucide-react';
import { PageHeader } from '../PageHeader';

function formatAssetPath(path) {
  if (!path) return path;
  return String(path)
    .replace(/^(?:\.\.\/)+(?:tmp|run\/user\/\d+)\/[^/]+\//, '')
    .replace(/^.*\/profiles\/[^/]+\//, '');
}

function NotesEditor({ notes, savingNotes, saveNotes }) {
  const [draft, setDraft] = useState(notes?.notes || '');
  const dirty = draft !== (notes?.notes || '');

  useEffect(() => {
    if (!dirty) return;
    const handler = (e) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  return (
    <>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
          <FileText size={13} style={{ flexShrink: 0 }} />
          {notes?.exists
            ? <><span>Loaded from:</span> <code style={{ fontSize: '0.75rem' }}>{formatAssetPath(notes.loaded_from)}</code></>
            : <>No standing notes file yet &mdash; start typing below and save to create it.</>}
        </span>
      </div>

      <textarea
        className="input-base"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        spellCheck={false}
        placeholder={`Add your recent focus, ongoing projects, new tools, or standing notes here...\n\nExample:\n- Recently built multi-agent workflows using Claude 3.7 Sonnet, OpenAI o3-mini, and Gemini 2.0 Flash with Google Antigravity and Cursor.\n- Exploring LangGraph, LlamaIndex, and local LLMs with Ollama.\n- Strong focus on agentic coding and prompt engineering.`}
        style={{
          width: '100%',
          minHeight: '180px',
          resize: 'vertical',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
          fontSize: '13px',
          lineHeight: '1.5',
          padding: '0.75rem',
          whiteSpace: 'pre-wrap',
        }}
      />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '0.75rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span>{draft.length.toLocaleString()} chars</span>
          {dirty && (
            <span style={{ color: '#f59e0b', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <AlertTriangle size={13} /> Unsaved changes
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="btn"
            disabled={!dirty || savingNotes}
            onClick={() => setDraft(notes?.notes || '')}
          >
            <RotateCcw size={16} />&nbsp;Discard
          </button>
          <button
            className="btn btn-primary"
            disabled={!dirty || savingNotes}
            onClick={() => saveNotes(draft)}
          >
            {savingNotes ? <RefreshCw className="spinner" size={16} /> : <Save size={16} />}
            &nbsp;Save Notes
          </button>
        </div>
      </div>
    </>
  );
}

function InstructionsEditor({ instructions, saving, onSave }) {
  const [cvDraft, setCvDraft] = useState(instructions.cv || '');
  const [clDraft, setClDraft] = useState(instructions.cover_letter || '');
  const dirty = cvDraft !== (instructions.cv || '') || clDraft !== (instructions.cover_letter || '');

  return (
    <>
      <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
        Extra drafting preferences for your CV and cover letter (in addition to the selected CV profile). Leave a box empty if you need no extra instructions.
      </div>
      <div className="form-group">
        <label className="form-label"><FileText size={13} style={{ verticalAlign: '-2px' }} /> CV-specific instructions</label>
        <textarea
          className="input-base"
          value={cvDraft}
          onChange={(e) => setCvDraft(e.target.value)}
          placeholder="e.g. Emphasize leadership experience; never mention specific employers from over five years ago..."
          style={{ width: '100%', minHeight: '90px', resize: 'vertical', fontSize: '13px', lineHeight: '1.5', padding: '0.6rem' }}
        />
      </div>
      <div className="form-group">
        <label className="form-label"><MessageSquareText size={13} style={{ verticalAlign: '-2px' }} /> Cover-letter-specific instructions</label>
        <textarea
          className="input-base"
          value={clDraft}
          onChange={(e) => setClDraft(e.target.value)}
          placeholder="e.g. In the closing paragraph, mention that I am comfortable saying 'I don't know' and proactively help colleagues..."
          style={{ width: '100%', minHeight: '90px', resize: 'vertical', fontSize: '13px', lineHeight: '1.5', padding: '0.6rem' }}
        />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.5rem' }}>
        {dirty && (
          <span style={{ fontSize: '0.8rem', color: '#f59e0b', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            <AlertTriangle size={13} /> Unsaved changes
          </span>
        )}
        <button
          className="btn btn-primary"
          disabled={!dirty || saving}
          onClick={() => onSave({ cv: cvDraft, cover_letter: clDraft })}
        >
          {saving ? <RefreshCw className="spinner" size={16} /> : <Save size={16} />}
          &nbsp;Save Instructions
        </button>
      </div>
    </>
  );
}

function CvReadOnly({ cv }) {
  // The text comes from the career record (ADR-0004); the server refuses saves here.
  return (
    <>
      <div role="note" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
        <Lock size={13} style={{ flexShrink: 0 }} />
        Read-only: this text comes from your {formatAssetPath(cv.loaded_from) || 'career record'}. Edit the career record to change it.
      </div>
      <pre style={{
        margin: 0, maxHeight: '55vh', overflow: 'auto', padding: '0.75rem', whiteSpace: 'pre-wrap',
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: '13px', lineHeight: '1.5',
        background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '8px',
      }}>{cv.content}</pre>
    </>
  );
}

function CvEditor({ cv, savingCv, saveCv }) {
  const [draft, setDraft] = useState(cv.content);
  const dirty = draft !== cv.content;

  // Warn before leaving the page with unsaved edits.
  useEffect(() => {
    if (!dirty) return;
    const handler = (e) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);


  return (
    <>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
          <FileText size={13} style={{ flexShrink: 0 }} />
          {cv.exists
            ? <>Loaded from: <code style={{ fontSize: '0.75rem' }}>{formatAssetPath(cv.loaded_from)}</code></>
            : <>No CV file yet &mdash; saving creates <code style={{ fontSize: '0.75rem' }}>{formatAssetPath(cv.save_path)}</code>.</>}
        </span>
      </div>
      {cv.missing_message && (
        <div role="status" className="cv-getting-started" style={{ marginBottom: '1rem', padding: '0.75rem 1rem', borderRadius: '8px', border: '1px solid rgba(245,158,11,0.35)', backgroundColor: 'rgba(245,158,11,0.07)', fontSize: '0.85rem', display: 'flex', alignItems: 'flex-start', gap: '0.5rem', flexWrap: 'wrap' }}>
          <AlertTriangle size={15} color="#f59e0b" style={{ flexShrink: 0, marginTop: '0.1rem' }} />
          <span style={{ flex: 1, minWidth: '12rem' }}>
            <strong>Getting started:</strong> job scoring and document generation stay off until you save your own CV here.
            {cv.template ? ' You can start from the fictional example and replace it with your details.' : ''}
          </span>
          {cv.template && (
            <button type="button" className="btn btn-secondary" disabled={draft.trim() !== ''} onClick={() => setDraft(cv.template)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.75rem' }}>
              Start from the example
            </button>
          )}
        </div>
      )}

      <textarea
        className="input-base"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        spellCheck={false}
        placeholder="Paste or write your plain-text CV here..."
        style={{
          width: '100%',
          minHeight: '55vh',
          resize: 'vertical',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
          fontSize: '13px',
          lineHeight: '1.5',
          padding: '0.75rem',
          whiteSpace: 'pre-wrap',
        }}
      />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '0.75rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span>{draft.length.toLocaleString()} chars</span>
          {dirty && (
            <span style={{ color: '#f59e0b', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <AlertTriangle size={13} /> Unsaved changes
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="btn"
            disabled={!dirty || savingCv}
            onClick={() => setDraft(cv.content)}
          >
            <RotateCcw size={16} />&nbsp;Discard
          </button>
          <button
            className="btn btn-primary"
            disabled={!dirty || savingCv}
            onClick={() => saveCv(draft)}
          >
            {savingCv ? <RefreshCw className="spinner" size={16} /> : <Save size={16} />}
            &nbsp;Save to Disk
          </button>
        </div>
      </div>
    </>
  );
}

export function PersonalizeTab({
  cv,
  cvVersion,
  cvLoaded,
  loadingCv,
  savingCv,
  fetchCv,
  saveCv,
  notes,
  notesVersion,
  notesLoaded,
  loadingNotes,
  savingNotes,
  fetchNotes,
  saveNotes,
  scraperConfig,
  saveConfig,
  savingConfig,
}) {
  useEffect(() => {
    if (!cvLoaded && !loadingCv) fetchCv();
    if (!notesLoaded && !loadingNotes && fetchNotes) fetchNotes();
  }, [cvLoaded, loadingCv, fetchCv, notesLoaded, loadingNotes, fetchNotes]);

  return (
    <div className="page-shell">
      <PageHeader
        title="Personalize"
        subtitle="Manage your career record, recent experience & standing notes, and extra drafting preferences."
      />
      <div className="page-body-narrow">
      <div className="card">
        <h2 className="card-title"><User size={20} /> Personal CV (Plain Text)</h2>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          Source record used for requirement checks, match ratings, and application drafts. Edit it here and save &mdash; the file on disk is updated immediately.
        </div>

        {loadingCv && (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={24} style={{ margin: '0 auto', display: 'block' }} />
          </div>
        )}

        {!loadingCv && cv && (
          // Keyed by disk-truth version so the editor resets when a fresh
          // copy is loaded or saved, while keeping local draft state in between.
          cv.read_only
            ? <CvReadOnly cv={cv} />
            : <CvEditor key={cvVersion} cv={cv} savingCv={savingCv} saveCv={saveCv} />
        )}
      </div>

      <div className="card" style={{ marginTop: '2rem' }}>
        <h2 className="card-title"><FileText size={20} /> Recent Experience &amp; Standing Notes</h2>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          Notes on recent projects, tools, and work preferences (location, work model, travel). Checked alongside your CV during requirement matching and document drafting.
        </div>

        {loadingNotes && (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={24} style={{ margin: '0 auto', display: 'block' }} />
          </div>
        )}

        {!loadingNotes && notes && (
          <NotesEditor
            key={notesVersion}
            notes={notes}
            savingNotes={savingNotes}
            saveNotes={saveNotes}
          />
        )}
      </div>

      <div className="card" style={{ marginTop: '2rem' }}>
        <h2 className="card-title"><MessageSquareText size={20} /> Document Drafting Instructions</h2>
        {!scraperConfig ? (
          <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={24} style={{ margin: '0 auto', display: 'block' }} />
          </div>
        ) : (
          // Keyed by the stored instructions so drafts reset when a fresh
          // config arrives (login, save, or user switch).
          <InstructionsEditor
            key={JSON.stringify(scraperConfig.document_instructions || {})}
            instructions={scraperConfig.document_instructions || {}}
            saving={savingConfig}
            onSave={(instructions) => saveConfig({ document_instructions: instructions })}
          />
        )}
      </div>
      </div>
    </div>
  );
}
