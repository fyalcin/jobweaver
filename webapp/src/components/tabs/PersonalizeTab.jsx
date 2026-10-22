import React, { useState, useEffect } from 'react';
import { User, RefreshCw, Save, RotateCcw, FileText, AlertTriangle, MessageSquareText, Sparkles } from 'lucide-react';

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
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
          <FileText size={13} />
          {notes?.exists
            ? <>Loaded from: <code style={{ fontSize: '0.75rem' }}>{notes.loaded_from}</code></>
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
        These instructions are appended to every AI prompt when generating documents for you
        (in addition to the selected CV profile). Leave a box empty for no extra instructions.
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

  const pathsDiffer = cv.loaded_from !== cv.save_path;

  return (
    <>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
          <FileText size={13} />
          {cv.exists
            ? <>Loaded from: <code style={{ fontSize: '0.75rem' }}>{cv.loaded_from}</code></>
            : <>No CV file on disk yet &mdash; start typing below and save to create it.</>}
        </span>
        {pathsDiffer && (
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
            <AlertTriangle size={13} color="#f59e0b" />
            Showing the generic base template CV. Saving creates your own copy at{' '}
            <code style={{ fontSize: '0.75rem' }}>{cv.save_path}</code>.
          </span>
        )}
      </div>

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
    <div style={{ maxWidth: '900px', margin: '0 auto' }}>
      <div className="card">
        <h2 className="card-title"><User size={20} /> Personal CV (Plain Text)</h2>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          This text is injected into every AI prompt: job match scoring, document generation,
          and refinement all read it. Edit it here and save &mdash; the file on disk is updated immediately.
        </div>

        {loadingCv && (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={24} style={{ margin: '0 auto', display: 'block' }} />
          </div>
        )}

        {!loadingCv && cv && (
          // Keyed by disk-truth version so the editor resets when a fresh
          // copy is loaded or saved, while keeping local draft state in between.
          <CvEditor key={cvVersion} cv={cv} savingCv={savingCv} saveCv={saveCv} />
        )}
      </div>

      <div className="card" style={{ marginTop: '2rem' }}>
        <h2 className="card-title"><Sparkles size={20} /> Recent Experience &amp; Standing Notes</h2>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          Quickly jot down new tools, technologies, recent projects, or things you've been working on lately.
          These notes are automatically appended to your CV text during job match scoring and document generation,
          authorizing the AI to highlight them without having to rewrite your main CV.
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
        <h2 className="card-title"><MessageSquareText size={20} /> AI Generation Instructions</h2>
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
  );
}
