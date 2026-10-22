import React, { useState, useRef, useEffect, useMemo } from 'react';
import {
  Play, Save, Download, Trash2, Plus, Sparkles, RefreshCw,
  AlertTriangle, Check, FileText, ChevronDown, ChevronsUpDown, ChevronsDownUp, ZoomIn, ZoomOut, Maximize2,
  FileCode2, Copy, X, Code, Eye, SlidersHorizontal, Pencil
} from 'lucide-react';
import { TypstWasmPreview } from '../studio/TypstWasmPreview';
import { TypstSimpleEditor } from '../studio/TypstSimpleEditor';
import { StudioCodeEditor } from '../studio/StudioCodeEditor';
import { EngineBadge } from '../studio/EngineBadge';
import { parseTypstDocument } from '../../services/typstParser';
import { serializeTypstDocument } from '../../services/typstSerializer';

export function CVStudioTab({
  documents = [],
  loadingDocs = false,
  templates = [],
  fetchTemplates,
  activeDocId,
  activeDoc,
  loadingDoc,
  draftContent,
  setDraftContent,
  isDirty,
  saving,
  autosaveError,
  compiling,
  aiEditing,
  zoom,
  setZoom,
  selectDocument,
  createDocument,
  saveDocument,
  compileDocument,
  downloadTypstPdf,
  aiEditDocument,
  deleteDocument,
  addToast,
}) {
  const [newModalOpen, setNewModalOpen] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDocType, setNewDocType] = useState('cv');
  const [newTemplate, setNewTemplate] = useState('');
  const [aiPrompt, setAiPrompt] = useState('');
  const [showRawLog, setShowRawLog] = useState(false);
  const [mobileView, setMobileView] = useState('editor'); // 'editor' | 'preview'
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [livePageCount, setLivePageCount] = useState(1);
  const [editorMode, setEditorMode] = useState('simple'); // 'simple' | 'advanced'
  const [parsedTypst, setParsedTypst] = useState(null);

  const textareaRef = useRef(null);
  const isLocalChangeRef = useRef(false);

  // Simple-mode accordion state lives here so the expand/collapse toggle can sit in the mode header
  const [simpleOpenSections, setSimpleOpenSections] = useState({ basics: true });

  useEffect(() => {
    // Reset the accordion when the selected document changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSimpleOpenSections({ basics: true });
  }, [activeDocId]);

  const simpleSectionKeys = useMemo(() => {
    if (!parsedTypst?.supported) return [];
    if (parsedTypst.kind === 'cover-letter') return ['recipient', 'paragraphs'];
    return (parsedTypst.data?.sections || []).map((sec, idx) => `sec-${idx}-${sec.title}`);
  }, [parsedTypst]);

  const allSimpleExpanded =
    simpleSectionKeys.length > 0 &&
    !!simpleOpenSections.basics &&
    simpleSectionKeys.every((k) => simpleOpenSections[k]);

  const toggleSimpleAll = () => {
    if (allSimpleExpanded) {
      setSimpleOpenSections({});
    } else {
      const all = { basics: true };
      simpleSectionKeys.forEach((k) => { all[k] = true; });
      setSimpleOpenSections(all);
    }
  };

  // Safety fallback: if documents exist but no document is active and not loading, auto-select first document
  useEffect(() => {
    if (documents.length > 0 && !activeDocId && !loadingDocs && !loadingDoc) {
      selectDocument(documents[0].id);
    }
  }, [documents, activeDocId, loadingDocs, loadingDoc, selectDocument]);

  // Sync title draft when active doc changes
  useEffect(() => {
    if (activeDoc) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setTitleDraft(activeDoc.title || '');
    }
  }, [activeDoc]);

  // Synchronize parsed state when activeDoc or draftContent updates (e.g. initial load or external AI edit)
  useEffect(() => {
    if (isLocalChangeRef.current) {
      isLocalChangeRef.current = false;
      return;
    }

    if (editorMode !== 'simple') return;

    if (activeDoc?.engine === 'typst' && draftContent) {
      const res = parseTypstDocument(draftContent);
      if (res.supported) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setParsedTypst(res);
      } else {

        setParsedTypst(null);
        // Graceful non-destructive fallback to Advanced mode if custom scripting is detected
        if (editorMode === 'simple') {

          setEditorMode('advanced');
          if (addToast) {
            addToast(res.reason || 'Custom Typst layout detected. Viewing in Advanced code mode.', 'info');
          }
        }
      }
    } else {

      setParsedTypst(null);

      setEditorMode('advanced');
    }
  }, [activeDoc?.id, activeDoc?.engine, draftContent, editorMode, addToast]);

  const handleSwitchMode = (mode) => {
    if (mode === 'simple') {
      if (activeDoc?.engine !== 'typst') {
        if (addToast) addToast('Simple Mode is available for Typst documents.', 'info');
        return;
      }
      const res = parseTypstDocument(draftContent);
      if (res.supported) {
        setParsedTypst(res);
        setEditorMode('simple');
      } else {
        if (addToast) {
          addToast(res.reason || 'Document uses custom Typst code. Editing in Advanced code mode.', 'warning');
        }
      }
    } else {
      setEditorMode('advanced');
    }
  };

  const handleSimpleChange = (newData) => {
    if (!parsedTypst) return;
    const updated = { ...parsedTypst, data: newData };
    setParsedTypst(updated);
    try {
      const newSource = serializeTypstDocument(parsedTypst.kind, newData, parsedTypst.rawPreamble);
      isLocalChangeRef.current = true;
      setDraftContent(newSource);
    } catch (err) {
      addToast(err.message || 'This change needs Advanced mode.', 'warning');
      setEditorMode('advanced');
    }
  };

  const lineCount = draftContent.split('\n').length;

  // Close modal on Escape key
  useEffect(() => {
    if (!newModalOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setNewModalOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [newModalOpen]);

  // When modal opens and templates become available, ensure newTemplate has a selection
  useEffect(() => {
    if (newModalOpen && !newTemplate && templates.length > 0) {
      const matching = templates.find((t) => t.doc_type === 'cv' && t.default)
        || templates.find((t) => t.doc_type === 'cv' && (t.engine === 'typst' || t.id?.endsWith('.typ')))
        || templates.find((t) => t.doc_type === 'cv');
      // Templates can arrive after the user opens the dialog.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setNewTemplate(matching ? matching.id : templates[0].id);
    }
  }, [newModalOpen, newTemplate, templates]);

  const handleOpenNewModal = () => {
    if (fetchTemplates) {
      fetchTemplates();
    }
    setNewTitle('');
    setNewDocType('cv');
    const firstCv = templates.find((t) => t.doc_type === 'cv' && t.default)
      || templates.find((t) => t.doc_type === 'cv' && (t.engine === 'typst' || t.id?.endsWith('.typ')))
      || templates.find((t) => t.doc_type === 'cv');
    setNewTemplate(firstCv ? firstCv.id : '__blank_typst__');
    setNewModalOpen(true);
  };

  const handleCreateSubmit = async (e) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    let engine = 'latex';
    let tmplSource = newTemplate || null;
    if (newTemplate === '__blank_typst__') {
      engine = 'typst';
      tmplSource = null;
    } else if (newTemplate) {
      const tmplObj = templates.find((t) => t.id === newTemplate);
      engine = tmplObj?.engine || (newTemplate.endsWith('.typ') ? 'typst' : 'latex');
    }
    const created = await createDocument({
      title: newTitle.trim(),
      doc_type: newDocType,
      engine: engine,
      template_source: tmplSource,
    });
    if (created) {
      setNewModalOpen(false);
    }
  };

  const handleSaveTitle = () => {
    if (titleDraft.trim() && titleDraft !== activeDoc?.title) {
      saveDocument(titleDraft.trim());
    }
    setIsEditingTitle(false);
  };

  const handleAiQuickChip = (chipText) => {
    setAiPrompt(chipText);
  };

  const handleTriggerAiEdit = () => {
    if (!aiPrompt.trim()) return;
    let selection = null;
    if (textareaRef.current) {
      const selStart = textareaRef.current.selectionStart;
      const selEnd = textareaRef.current.selectionEnd;
      if (selStart !== selEnd) {
        selection = draftContent.substring(selStart, selEnd);
      }
    }
    aiEditDocument(aiPrompt, selection);
  };

  return (
    <div className="studio-container">
      {/* Top Action & Navigation Bar */}
      <div className={`studio-topbar${activeDoc?.engine === 'typst' ? ' engine-typst' : ''}${autosaveError ? ' autosave-error' : ''}`}>
        {/* Row 1: Document Selector, New button, and Delete on mobile / Title on desktop */}
        <div className="studio-topbar-row-main">
          <div className="studio-doc-selector-group">
            <select
              aria-label="Select active studio document"
              className="input-base studio-select"
              value={activeDocId || ''}
              onChange={(e) => selectDocument(e.target.value)}
              disabled={loadingDocs || saving || compiling}
            >
              {documents.length === 0 && <option value="">No documents yet</option>}
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.title} {doc.doc_type === 'letter' ? '(Letter)' : ''}
                </option>
              ))}
            </select>

            <button className="btn btn-secondary btn-sm studio-btn-new" onClick={handleOpenNewModal} title="Create New Document">
              <Plus size={15} /> <span>New</span>
            </button>

            {activeDoc && (
              <button
                className="btn btn-secondary btn-sm studio-btn-delete studio-btn-delete-mobile"
                onClick={() => {
                  if (window.confirm(`Delete document "${activeDoc.title}"?`)) {
                    deleteDocument(activeDoc.id);
                  }
                }}
                title="Delete document"
              >
                <Trash2 size={15} />
              </button>
            )}
          </div>

          {activeDoc && (
            <div className="studio-title-area studio-title-area-desktop">
              {isEditingTitle ? (
                <input
                  type="text"
                  className="input-base studio-title-input"
                  value={titleDraft}
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onBlur={handleSaveTitle}
                  onKeyDown={(e) => e.key === 'Enter' && handleSaveTitle()}
                  autoFocus
                />
              ) : (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm studio-btn-rename"
                  onClick={() => setIsEditingTitle(true)}
                  title={`Rename "${activeDoc.title}"`}
                  style={{ height: '32px', padding: '0 0.6rem', gap: '0.35rem' }}
                >
                  <Pencil size={13} />
                  <span style={{ fontSize: '0.78rem' }}>Rename</span>
                </button>
              )}
              {activeDoc.engine && (
                <EngineBadge engine={activeDoc.engine} />
              )}
              {isDirty && (
                <span className="studio-dirty-badge" title={saving ? 'Saving…' : 'Unsaved changes'}>
                  <AlertTriangle size={12} /> <span className="dirty-badge-text">{saving ? 'Saving…' : 'Unsaved'}</span>
                </span>
              )}
            </div>
          )}
        </div>

        {/* Actions Row: Title (on mobile) + Primary Actions (Compile, Save, PDF) */}
        {activeDoc && (
          <div className="studio-topbar-row-actions">
            {/* Title display on mobile */}
            <div className="studio-title-area studio-title-area-mobile">
              {isEditingTitle ? (
                <input
                  type="text"
                  className="input-base studio-title-input"
                  value={titleDraft}
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onBlur={handleSaveTitle}
                  onKeyDown={(e) => e.key === 'Enter' && handleSaveTitle()}
                  autoFocus
                />
              ) : (
                <span
                  className="studio-title-display"
                  onClick={() => setIsEditingTitle(true)}
                  title="Click to rename"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                >
                  <span className="studio-title-text">{activeDoc.title}</span>
                  <Pencil size={12} style={{ opacity: 0.7, flexShrink: 0 }} />
                </span>
              )}
              {activeDoc.engine && (
                <EngineBadge engine={activeDoc.engine} />
              )}
              {isDirty && (
                <span className="studio-dirty-badge" title={saving ? 'Saving…' : 'Unsaved changes'}>
                  <AlertTriangle size={12} /> <span className="dirty-badge-text">{saving ? 'Saving…' : 'Unsaved'}</span>
                </span>
              )}
            </div>

            <div className="studio-actions-group">
              {/* Zoom Controls in topbar (desktop only) */}
              <div className="studio-preview-zoom-group studio-zoom-desktop">
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => setZoom((z) => Math.max(50, z - 10))}
                  title="Zoom Out"
                >
                  <ZoomOut size={14} />
                </button>
                <span className="studio-zoom-indicator">{zoom}%</span>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => setZoom((z) => Math.min(200, z + 10))}
                  title="Zoom In"
                >
                  <ZoomIn size={14} />
                </button>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => setZoom(100)}
                  title="Reset Zoom (100%)"
                >
                  <Maximize2 size={14} />
                </button>
              </div>

              {activeDoc?.engine === 'typst' ? (
                <span className="studio-page-badge studio-badge-desktop">
                  {livePageCount} {livePageCount === 1 ? 'Page' : 'Pages'}
                </span>
              ) : (
                activeDoc?.preview_urls && activeDoc.preview_urls.length > 0 && (
                  <span className="studio-page-badge studio-badge-desktop">
                    {activeDoc.preview_urls.length} {activeDoc.preview_urls.length === 1 ? 'Page' : 'Pages'}
                  </span>
                )
              )}

              <div className="studio-topbar-divider studio-divider-desktop" />

              <button
                className="btn btn-primary studio-btn-compile"
                onClick={() => compileDocument()}
                disabled={compiling || saving}
                title={activeDoc?.engine === 'typst' ? 'Compile & sync PDF to disk (pure WASM)' : 'Recompile document with pdflatex (Ctrl+Enter)'}
              >
                {compiling ? <RefreshCw className="spinner" size={15} /> : <Play size={15} fill="currentColor" />}
                <span>Compile</span>
              </button>

              <button
                className="btn btn-secondary studio-btn-save"
                onClick={() => saveDocument()}
                disabled={saving || !isDirty}
                title="Save to disk (Ctrl+S)"
              >
                {saving ? <RefreshCw className="spinner" size={15} /> : <Save size={15} />}
                <span className="btn-label-desktop">Save</span>
              </button>

              {activeDoc?.engine === 'typst' ? (
                <button
                  type="button"
                  onClick={() => (downloadTypstPdf ? downloadTypstPdf() : null)}
                  className="btn btn-secondary studio-btn-pdf"
                  title="Instant client-side PDF download (pure WASM)"
                >
                  <Download size={15} /><span className="btn-label-desktop">PDF</span>
                </button>
              ) : (
                activeDoc.has_pdf && activeDoc.pdf_url && (
                  <a
                    href={activeDoc.pdf_url}
                    download={`${activeDoc.title || 'document'}.pdf`}
                    className="btn btn-secondary studio-btn-pdf"
                    title="Download PDF"
                  >
                    <Download size={15} /><span className="btn-label-desktop">PDF</span>
                  </a>
                )
              )}

              <button
                className="btn btn-secondary studio-btn-delete studio-btn-delete-desktop"
                onClick={() => {
                  if (window.confirm(`Delete document "${activeDoc.title}"?`)) {
                    deleteDocument(activeDoc.id);
                  }
                }}
                title="Delete document"
              >
                <Trash2 size={15} />
              </button>
            </div>
          </div>
        )}

        {/* Mobile View Switcher (Editor vs Preview) */}
        <div className="studio-mobile-switcher">
          <button
            className={`studio-mobile-tab-btn ${mobileView === 'editor' ? 'active' : ''}`}
            onClick={() => setMobileView('editor')}
          >
            <Code size={15} />
            <span>Editor</span>
          </button>
          <button
            className={`studio-mobile-tab-btn ${mobileView === 'preview' ? 'active' : ''}`}
            onClick={() => setMobileView('preview')}
          >
            <Eye size={15} />
            <span>Preview</span>
            {activeDoc?.engine === 'typst' ? (
              <span className="studio-mobile-page-pill">{livePageCount}</span>
            ) : (
              activeDoc?.preview_urls && activeDoc.preview_urls.length > 0 && (
                <span className="studio-mobile-page-pill">{activeDoc.preview_urls.length}</span>
              )
            )}
          </button>
        </div>
      </div>

      {/* Main Split View Area */}
      {documents.length === 0 && !loadingDocs ? (
        <div className="studio-empty-state">
          <FileCode2 size={48} style={{ opacity: 0.4, marginBottom: '1rem' }} />
          <h3>Welcome to CV Library</h3>
          <p>Create, edit, compile, and manage standalone Typst & LaTeX CVs with real-time visual feedback.</p>
          <button className="btn btn-primary" onClick={handleOpenNewModal} style={{ marginTop: '1rem' }}>
            <Plus size={16} /> Create Your First CV
          </button>
        </div>
      ) : !activeDoc ? (
        <div className="studio-empty-state" style={{ color: 'var(--text-secondary)' }}>
          <RefreshCw className="spinner" size={32} style={{ marginBottom: '1rem', opacity: 0.7 }} />
          <p>Loading document...</p>
        </div>
      ) : (
        <div className={`studio-split-view mobile-show-${mobileView}`}>
          {/* Left Pane: Code or Simple Form Editor */}
          <div className="studio-editor-pane">
            {/* Mode Switcher Header */}
            <div className="studio-mode-header">
              {activeDoc?.engine === 'typst' ? (
                <div className="studio-segmented-mode">
                  <button
                    type="button"
                    className={`studio-mode-btn ${editorMode === 'simple' ? 'active' : ''}`}
                    onClick={() => handleSwitchMode('simple')}
                    title="Visual form editor: edit fields and bullets without syntax"
                  >
                    <span>Simple</span>
                  </button>
                  <button
                    type="button"
                    className={`studio-mode-btn ${editorMode === 'advanced' ? 'active' : ''}`}
                    onClick={() => handleSwitchMode('advanced')}
                    title="Full Typst code editor with line numbers"
                  >
                    <span>Advanced</span>
                  </button>
                </div>
              ) : (
                <div className="studio-mode-badge-latex" title="LaTeX documents are edited in Advanced code mode">
                  <span>Advanced (LaTeX)</span>
                </div>
              )}

              <div className="studio-mode-meta">
                {editorMode === 'simple' && simpleSectionKeys.length >= 3 && (
                  <button
                    type="button"
                    className="simple-expand-toggle"
                    onClick={toggleSimpleAll}
                    title={allSimpleExpanded ? 'Collapse all sections' : 'Expand all sections'}
                    aria-label={allSimpleExpanded ? 'Collapse all sections' : 'Expand all sections'}
                  >
                    {allSimpleExpanded ? <ChevronsDownUp size={14} /> : <ChevronsUpDown size={14} />}
                  </button>
                )}
                {editorMode === 'simple' && parsedTypst && (
                  <span className="studio-mode-pill">
                    {parsedTypst.kind === 'moderner-cv' ? 'ModernCV Form' : (parsedTypst.kind === 'standard-cv' ? 'Standard CV Form' : 'Cover Letter Form')}
                  </span>
                )}
                {editorMode === 'advanced' && (
                  <span className="studio-mode-pill-muted">
                    {lineCount} lines
                  </span>
                )}
              </div>
            </div>

            {/* Simple Mode vs Advanced Mode View */}
            {editorMode === 'simple' && parsedTypst?.supported ? (
              <TypstSimpleEditor
                data={parsedTypst.data}
                kind={parsedTypst.kind}
                onChange={handleSimpleChange}
                disabled={saving || compiling || aiEditing}
                openSections={simpleOpenSections}
                setOpenSections={setSimpleOpenSections}
              />
            ) : (
              <StudioCodeEditor
                ref={textareaRef}
                value={draftContent}
                onChange={setDraftContent}
                onCompile={compileDocument}
                onSave={saveDocument}
                placeholder={activeDoc?.engine === 'typst' ? '// Type or paste your Typst code here...' : '% Type or paste your LaTeX code here...'}
              />
            )}

            {/* AI Surgical Assistant Bar */}
            <div className="studio-ai-bar">
              <div className="studio-ai-input-row">
                <Sparkles size={16} className="studio-ai-icon" />
                <input
                  type="text"
                  className="input-base studio-ai-input"
                  placeholder="Choose which approved experience to include. Edit wording manually."
                  value={aiPrompt}
                  onChange={(e) => setAiPrompt(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleTriggerAiEdit()}
                  disabled={aiEditing}
                />
                <button
                  className="studio-ai-submit-btn"
                  onClick={handleTriggerAiEdit}
                  disabled={aiEditing || !aiPrompt.trim()}
                >
                  {aiEditing ? <RefreshCw className="spinner" size={14} /> : <Sparkles size={14} />}
                  <span>Apply</span>
                </button>
              </div>

              <div className="studio-ai-chips">
                <span className="studio-chip-label">Quick suggestions:</span>
                <button className="studio-chip" onClick={() => handleAiQuickChip('Select fewer relevant evidence bullets; preserve dates and wording')}>
                  Shorter selection
                </button>
                <button className="studio-chip" onClick={() => handleAiQuickChip('Select evidence relevant to industry Python roles')}>
                  Industry selection
                </button>
                <button className="studio-chip" onClick={() => handleAiQuickChip('Select evidence relevant to research software roles')}>
                  Research selection
                </button>
                {activeDoc?.engine === 'typst' ? (
                  <button className="studio-chip" onClick={() => handleAiQuickChip('Restore all approved evidence bullets')}>
                    Restore evidence
                  </button>
                ) : (
                  <button className="studio-chip" onClick={() => handleAiQuickChip('Restore all approved evidence bullets')}>
                    Restore evidence
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Right Pane: Live PDF / Typst WASM Preview */}
          <div className="studio-preview-pane">
            {(isDirty || activeDoc?.pdf_current === false) && <p role="status">The saved PDF is from an earlier version. Compile the current text before using it.</p>}
            {activeDoc?.engine === 'typst' ? (
              <TypstWasmPreview
                source={draftContent}
                zoom={zoom}
                onPageCountChange={(cnt) => setLivePageCount(cnt)}
              />
            ) : (
              <>
                {/* Mobile-only Preview Toolbar */}
                <div className="studio-preview-mobile-bar">
                  <div className="studio-preview-mobile-zoom">
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={() => setZoom((z) => Math.max(50, z - 10))}
                      title="Zoom Out"
                    >
                      <ZoomOut size={13} />
                    </button>
                    <span className="studio-zoom-indicator">{zoom}%</span>
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={() => setZoom((z) => Math.min(200, z + 10))}
                      title="Zoom In"
                    >
                      <ZoomIn size={13} />
                    </button>
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={() => setZoom(100)}
                      title="Reset Zoom (100%)"
                    >
                      <Maximize2 size={13} />
                    </button>
                  </div>

                  {activeDoc?.preview_urls && activeDoc.preview_urls.length > 0 && (
                    <span className="studio-page-badge">
                      {activeDoc.preview_urls.length} {activeDoc.preview_urls.length === 1 ? 'Page' : 'Pages'}
                    </span>
                  )}
                </div>

                {/* Error Diagnostics Card */}
                {activeDoc?.error && (
                  <div className="studio-error-card">
                    <div className="studio-error-header">
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <AlertTriangle size={18} color="var(--danger-color, #ef4444)" />
                        <strong>Compilation Error</strong>
                      </div>
                      <button
                        className="studio-toggle-log-btn"
                        onClick={() => setShowRawLog((v) => !v)}
                      >
                        {showRawLog ? 'Hide Raw Log' : 'View Raw Log'}
                      </button>
                    </div>
                    <div className="studio-error-body">
                      <p className="studio-error-message">{activeDoc.error.message}</p>
                      {activeDoc.error.snippet && (
                        <code className="studio-error-snippet">{activeDoc.error.snippet}</code>
                      )}
                      {showRawLog && activeDoc.error.raw && (
                        <pre className="studio-error-raw-log">{activeDoc.error.raw}</pre>
                      )}
                    </div>
                  </div>
                )}

                {/* Rendered Page Image Stack */}
                <div className="studio-pages-scroll-container">
                  {compiling && (
                    <div className="studio-compiling-overlay">
                      <RefreshCw className="spinner" size={32} />
                      <span>Compiling LaTeX with pdflatex...</span>
                    </div>
                  )}

                  {activeDoc?.preview_urls && activeDoc.preview_urls.length > 0 ? (
                    <div
                      className="studio-pages-wrapper"
                      style={{ transform: `scale(${zoom / 100})`, transformOrigin: 'top center' }}
                    >
                      {activeDoc.preview_urls.map((url, idx) => (
                        <div key={idx} className="studio-page-card">
                          <img src={url} alt={`Page ${idx + 1}`} className="studio-page-img" />
                          <div className="studio-page-number">Page {idx + 1}</div>
                        </div>
                      ))}
                    </div>
                  ) : !compiling ? (
                    <div className="studio-preview-placeholder">
                      <FileText size={48} style={{ opacity: 0.3, marginBottom: '1rem' }} />
                      <h4>No Preview Available</h4>
                      <p>Click "Compile" in the toolbar above to build the PDF preview.</p>
                      <button className="btn btn-primary" onClick={() => compileDocument()} style={{ marginTop: '0.75rem' }}>
                        <Play size={16} fill="currentColor" /> Compile Now
                      </button>
                    </div>
                  ) : null}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* New Document Modal */}
      {newModalOpen && (
        <div
          className="modal-overlay"
          onClick={(e) => {
            if (e.target === e.currentTarget) setNewModalOpen(false);
          }}
        >
          <div
            className="modal-card studio-new-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="studio-create-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2 id="studio-create-title">Create New CV</h2>
              <button
                className="btn-close"
                onClick={() => setNewModalOpen(false)}
                title="Close (Esc)"
                type="button"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="studio-new-form">
              <div className="form-group">
                <label htmlFor="new-doc-title" className="form-label">CV Title</label>
                <input
                  id="new-doc-title"
                  aria-label="CV Title"
                  type="text"
                  className="input-base"
                  placeholder="e.g. Industry CV (Compact)"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  autoFocus
                  required
                />
              </div>

              <div className="form-group">
                <label htmlFor="new-doc-template" className="form-label">Starting Template</label>
                <select
                  id="new-doc-template"
                  aria-label="Starting Template"
                  className="input-base"
                  value={newTemplate}
                  onChange={(e) => setNewTemplate(e.target.value)}
                >
                  <optgroup label="Typst">
                    {templates
                      .filter((t) => t.doc_type === 'cv' && (t.engine === 'typst' || t.id?.endsWith('.typ')))
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.title}
                        </option>
                      ))}
                    <option value="__blank_typst__">Blank Typst CV</option>
                  </optgroup>
                  <optgroup label="LaTeX">
                    {templates
                      .filter((t) => t.doc_type === 'cv' && t.engine !== 'typst' && !t.id?.endsWith('.typ'))
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.title}
                        </option>
                      ))}
                    <option value="">Blank LaTeX CV</option>
                  </optgroup>
                </select>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.35rem', display: 'block' }}>
                  A copy of this template will be created in your CV library. Your base templates remain protected.
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem' }}>
                <button type="button" className="btn btn-secondary" onClick={() => setNewModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={!newTitle.trim() || saving}>
                  {saving ? <RefreshCw className="spinner" size={16} /> : <Plus size={16} />}
                  <span>Create CV</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
