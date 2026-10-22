import { useDemo } from '../demoContext';
import { DemoDocuments } from './DemoDocuments';
import React, { useState, useEffect, useRef } from 'react';
import {
  ArrowLeft, Sparkles, ExternalLink, Download, Wand2, RefreshCw,
  Save, CheckCircle2, FileText, Globe, Building2, MapPin,
  Calendar, DollarSign, UserCheck, Check, AlertCircle, AlertTriangle,
  Lightbulb, Bot, Briefcase, X, ZoomIn, ZoomOut, Layers, CheckSquare,
  Play, Maximize2, Code, Layout, Undo2, History, ChevronDown
} from 'lucide-react';
import { StatusSelect } from './StatusControls';
import { germanLevelLabel } from '../constants/german';
import { formatDateDisplay } from '../constants/dates';
import { useJobStudio } from '../hooks/useJobStudio';
import { TypstWasmPreview } from './studio/TypstWasmPreview';
import { TypstSimpleEditor } from './studio/TypstSimpleEditor';
import { StudioCodeEditor } from './studio/StudioCodeEditor';
import { EngineBadge } from './studio/EngineBadge';
import { parseTypstDocument } from '../services/typstParser';
import { serializeTypstDocument } from '../services/typstSerializer';

export function JobDetailPage({
  job,
  onBack,
  updateJobStatus,
  getScoreBadgeClass,
  handleJobsGenerateCV,
  handleJobsGenerateLetter,
  handleJobsGenerateBoth,
  generatingJobsDocs = new Set(),
  researching = false,
  onResearch,
  onSaveResearch,
}) {
  const demo = useDemo();
  const [activeSubTab, setActiveSubTab] = useState(job?.initialTab || 'job-fit'); // 'job-fit' | 'studio'
  const [compact, setCompact] = useState(false);
  const [researchText, setResearchText] = useState(job?.company_research || '');
  const [useInDocs, setUseInDocs] = useState(job?.use_research_in_docs !== false);
  const [isDirty, setIsDirty] = useState(false);
  const [savingNotes, setSavingNotes] = useState(false);

  // In-Job Studio states and hook
  const studio = useJobStudio(job?.id, () => {
    // optional callback on finalize
  });

  const [aiPrompt, setAiPrompt] = useState('');
  const [showRawLog, setShowRawLog] = useState(false);
  const [studioPageCount, setStudioPageCount] = useState(1);
  const [selectedEngine, setSelectedEngine] = useState(job?.default_document_engine || 'typst');
  const [editorMode, setEditorMode] = useState('simple');
  const [parsedTypst, setParsedTypst] = useState(null);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const isLocalSimpleEditRef = useRef(false);
  const textareaRef = useRef(null);
  const exportMenuRef = useRef(null);

  // Close export dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event) {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target)) {
        setShowExportMenu(false);
      }
    }
    if (showExportMenu) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showExportMenu]);

  // Parse Typst source for Simple mode (Lazy parse: only parse when in Simple mode)
  useEffect(() => {
    if (isLocalSimpleEditRef.current) {
      isLocalSimpleEditRef.current = false;
      return;
    }
    if (editorMode !== 'simple') return;

    if (studio.docEngine === 'typst' && studio.currentTex) {
      const docKind = studio.activeDocType === 'letter' ? 'cover-letter' : 'cv';
      const res = parseTypstDocument(studio.currentTex, docKind);
      if (res.supported) {
        setParsedTypst(res);
      } else {
        setParsedTypst(null);
        if (editorMode === 'simple') {
          setEditorMode('advanced');
        }
      }
    } else {
      setParsedTypst(null);
      setEditorMode('advanced');
    }
  }, [studio.docEngine, studio.currentTex, studio.activeDocType, editorMode]);

  // Synchronize format selector with active document engine when documents exist
  useEffect(() => {
    if (studio.hasCv || studio.hasLetter) {
      if (studio.docEngine) {
        setSelectedEngine(studio.docEngine);
      }
    }
  }, [studio.docEngine, studio.hasCv, studio.hasLetter]);

  const handleSwitchMode = (mode) => {
    if (mode === 'simple') {
      if (studio.docEngine !== 'typst') return;
      const docKind = studio.activeDocType === 'letter' ? 'cover-letter' : 'cv';
      const res = parseTypstDocument(studio.currentTex, docKind);
      if (res.supported) {
        setParsedTypst(res);
        setEditorMode('simple');
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
      isLocalSimpleEditRef.current = true;
      studio.setCurrentTex(newSource);
    } catch (err) {
      studio.setErrorCard({ message: err.message || 'This change needs Advanced mode.', parsed: null, rawLog: '' });
      setEditorMode('advanced');
      setParsedTypst(parsedTypst);
    }
  };

  // Sync researchText when job prop updates
  useEffect(() => {
    setResearchText(job?.company_research || '');
    setUseInDocs(job?.use_research_in_docs !== false);
    setIsDirty(false);
    if (job?.initialTab) {
      setActiveSubTab(job.initialTab);
    }
  }, [job?.id, job?.company_research, job?.use_research_in_docs, job?.initialTab]);

  // Scroll to top on mount
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [job?.id]);

  const { showCheatSheet, setShowCheatSheet } = studio;
  // Handle escape key to go back or close cheat sheet drawer
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (showCheatSheet) {
          setShowCheatSheet(false);
        } else {
          onBack();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onBack, showCheatSheet, setShowCheatSheet]);

  if (!job) return null;

  const isGeneratingCV = generatingJobsDocs.has(`${job.id}-cv`);
  const isGeneratingCL = generatingJobsDocs.has(`${job.id}-letter`);
  const isGeneratingBoth = isGeneratingCV && isGeneratingCL;

  const handleResearchClick = async () => {
    if (onResearch) {
      const res = await onResearch(job.id);
      if (res?.company_research) {
        setResearchText(res.company_research);
        setIsDirty(false);
      }
    }
  };

  const handleSaveNotesClick = async () => {
    if (onSaveResearch) {
      setSavingNotes(true);
      try {
        await onSaveResearch(job.id, researchText, useInDocs);
        setIsDirty(false);
      } finally {
        setSavingNotes(false);
      }
    }
  };

  const handleToggleUseInDocs = (checked) => {
    setUseInDocs(checked);
    setIsDirty(true);
  };

  const handleAiPromptSubmit = async (e) => {
    e.preventDefault();
    if (!aiPrompt.trim() || studio.aiEditing) return;
    const ok = await studio.aiEdit(aiPrompt.trim());
    if (ok) {
      setAiPrompt('');
    }
  };

  const handleQuickChip = (instruction) => {
    setAiPrompt(instruction);
    studio.aiEdit(instruction);
  };

  const formatTimestamp = (ts) => {
    if (!ts) return null;
    try {
      const d = new Date(ts);
      return d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return ts;
    }
  };

  // Structured extraction data with safe fallbacks
  const matchAnalysis = job.match_analysis || job.data?.match_analysis || null;
  const matchTier = job.match_score == null ? 'Not ranked' : job.match_score >= 80 ? 'Strong Match' : job.match_score >= 65 ? 'Good Match' : job.match_score >= 50 ? 'Moderate Match' : 'Reach';
  const matchSynthesis = matchAnalysis?.synthesis || job.summary || 'AI evaluated this candidate profile against the requirements.';
  const strengths = matchAnalysis?.strengths || [];
  const gaps = matchAnalysis?.gaps || [];
  const tips = matchAnalysis?.tips || [];

  const requirementsList = job.requirements || job.data?.requirements || [];
  const tasksList = job.tasks || job.data?.tasks || [];
  const toolsList = (job.tools_technologies && job.tools_technologies.length > 0)
    ? job.tools_technologies
    : (job.skills ? job.skills.split(',').map(s => s.trim()).filter(s => s && s.toLowerCase() !== 'not specified') : []);

  const workModel = job.work_model || job.data?.work_model || 'Full-time';
  const experienceYears = job.experience_years || job.data?.experience_years || 'Not specified';
  const educationLevel = job.education_level || job.data?.education_level || 'Not specified';

  const editorLines = (studio.currentTex || '').split('\n');

  return (
    <div className={`job-detail-page ${activeSubTab === 'studio' ? 'studio-mode-active' : ''}`}>
      {/* Top sticky navigation bar with View Sub-Tabs */}
      <div className="job-detail-topbar">
        <button className="btn btn-secondary btn-back" onClick={onBack}>
          <ArrowLeft size={18} />
          <span>Back to Jobs</span>
        </button>

        {/* Subtabs Segmented Switcher */}
        <div className="job-subtabs-nav" role="tablist" aria-label="Job views">
          <button
            type="button"
            role="tab"
            aria-selected={activeSubTab === 'job-fit'}
            className={`job-subtab-btn ${activeSubTab === 'job-fit' ? 'active' : ''}`}
            onClick={() => setActiveSubTab('job-fit')}
          >
            <Briefcase size={15} />
            <span>Job & Fit</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeSubTab === 'studio'}
            className={`job-subtab-btn ${activeSubTab === 'studio' ? 'active' : ''}`}
            onClick={() => {
              setActiveSubTab('studio');
              studio.fetchDocuments();
            }}
          >
            <Wand2 size={15} />
            <span>Tailor Studio</span>
          </button>
        </div>

        <div className="job-detail-topbar-actions">
          <StatusSelect
            value={job.status || (job.applied ? 'applied' : 'new')}
            onChange={(newStatus) => updateJobStatus(job.id, newStatus)}
          />
          {job.job_url && (
            <a
              href={job.job_url}
              target="_blank"
              rel="noreferrer"
              className="btn btn-secondary btn-icon-text"
              title="Open original job posting"
            >
              <ExternalLink size={16} />
              <span className="hide-mobile">View Posting</span>
            </a>
          )}
        </div>
      </div>

      {/* Main Container */}
      <div className="job-detail-container">
        {/* TAB 1: JOB COCKPIT (Job & Fit) */}
        {activeSubTab === 'job-fit' && (
          <>
            {/* Header Summary Banner */}
            <header className="job-detail-header-card">
              <div className="job-detail-header-main">
                <div className="job-detail-title-group">
                  <h1 className="job-detail-title">{job.title}</h1>
                  <div className="job-detail-meta-row">
                    <span className="job-detail-company">
                      <Building2 size={16} /> {job.company}
                    </span>
                    {job.location && (
                      <span className="job-detail-location">
                        <MapPin size={16} /> {job.location}
                      </span>
                    )}
                    {job.date_scraped && (
                      <span className="job-detail-date">
                        <Calendar size={15} /> Found {formatDateDisplay(job.date_scraped)}
                      </span>
                    )}
                    {job.source && (
                      <span className="badge badge-source" style={{ textTransform: 'capitalize' }}>
                        <Globe size={13} style={{ marginRight: '4px' }} />
                        {job.source}
                      </span>
                    )}
                    {workModel && workModel !== 'Unknown' && (
                      <span className="badge badge-source">
                        <Briefcase size={13} style={{ marginRight: '4px' }} />
                        {workModel}
                      </span>
                    )}
                  </div>
                </div>

                {/* Match score badge */}
                <div className="job-detail-score-pill">
                  <span className="score-label">Match Score</span>
                  <span className={`badge ${getScoreBadgeClass(job.match_score)} score-value`}>
                    {job.match_score != null ? `${job.match_score}%` : 'N/A'}
                  </span>
                </div>
              </div>

              {/* Quick info badges row */}
              <div className="job-detail-badges-row">
                <div className="info-chip">
                  <span className="info-chip-label">German:</span>
                  <span className="info-chip-val">
                    {germanLevelLabel(job.german_level ?? job.requires_german)}
                  </span>
                </div>
                <div className="info-chip">
                  <span className="info-chip-label">Salary:</span>
                  <span className="info-chip-val" style={{ color: 'var(--success-color)', fontWeight: 600 }}>
                    {job.salary_yearly
                      ? `€${Number(job.salary_yearly).toLocaleString('de-AT')} / year`
                      : (job.salary || 'Not specified')}
                  </span>
                </div>
                {job.company_contact && (
                  <div className="info-chip">
                    <span className="info-chip-label"><UserCheck size={14} /> Contact:</span>
                    <span className="info-chip-val">{job.company_contact}</span>
                  </div>
                )}
                {job.application_date && (
                  <div className="info-chip">
                    <span className="info-chip-label">Applied on:</span>
                    <span className="info-chip-val">{job.application_date}</span>
                  </div>
                )}
              </div>

              {/* Document Generation Action Bar */}
              <div className="job-detail-actions-panel">
                <div className="job-detail-actions-left" style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
                  <label className="compact-toggle-label">
                    <input
                      type="checkbox"
                      checked={compact}
                      onChange={(e) => setCompact(e.target.checked)}
                    />
                    <span>Compact CV</span>
                  </label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Format:</span>
                    <select
                      aria-label="Document engine format"
                      className="input-base"
                      style={{ height: '28px', fontSize: '0.8rem', width: 'auto' }}
                      value={selectedEngine}
                      onChange={(e) => setSelectedEngine(e.target.value)}
                    >
                      <option value="typst">Typst</option>
                      <option value="latex">LaTeX</option>
                    </select>
                  </div>
                </div>

                <div className="job-detail-actions-buttons">
                  {handleJobsGenerateBoth && (
                    <button
                      className="btn btn-primary"
                      onClick={() => handleJobsGenerateBoth(job, { compact, engine: selectedEngine })}
                      disabled={demo || isGeneratingBoth}
                    >
                      <Sparkles size={15} />
                      <span>{isGeneratingBoth ? 'Generating Both…' : 'Generate Both'}</span>
                    </button>
                  )}
                  {handleJobsGenerateCV && (
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleJobsGenerateCV(job, { compact, engine: selectedEngine })}
                      disabled={demo || isGeneratingCV}
                    >
                      {isGeneratingCV ? 'Generating CV…' : 'Generate CV'}
                    </button>
                  )}
                  {handleJobsGenerateLetter && (
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleJobsGenerateLetter(job, { engine: selectedEngine })}
                      disabled={demo || isGeneratingCL}
                    >
                      {isGeneratingCL ? 'Generating Letter…' : 'Generate Letter'}
                    </button>
                  )}
                  {Boolean(studio.cvDownloadUrl || job.cv_url || studio.clDownloadUrl || job.letter_url) && (
                    <div className="cockpit-export-group" ref={exportMenuRef}>
                      <button
                        type="button"
                        className="btn btn-secondary cockpit-export-btn"
                        onClick={() => setShowExportMenu(prev => !prev)}
                        aria-expanded={showExportMenu}
                        title="Export generated PDFs"
                      >
                        <Download size={15} />
                        <span>Export</span>
                        <ChevronDown size={14} style={{ transform: showExportMenu ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s ease' }} />
                      </button>
                      {showExportMenu && (
                        <div className="cockpit-export-menu">
                          {(studio.cvDownloadUrl || job.cv_url) && (
                            <a
                              href={studio.cvDownloadUrl || job.cv_url}
                              target="_blank"
                              rel="noreferrer"
                              className="cockpit-export-item"
                              onClick={() => setShowExportMenu(false)}
                            >
                              <FileText size={15} className="cockpit-export-item-icon" />
                              <div className="cockpit-export-item-text">
                                <span className="cockpit-export-item-title">Curriculum Vitae</span>
                                <span className="cockpit-export-item-sub">PDF Download</span>
                              </div>
                            </a>
                          )}
                          {(studio.clDownloadUrl || job.letter_url) && (
                            <a
                              href={studio.clDownloadUrl || job.letter_url}
                              target="_blank"
                              rel="noreferrer"
                              className="cockpit-export-item"
                              onClick={() => setShowExportMenu(false)}
                            >
                              <FileText size={15} className="cockpit-export-item-icon" />
                              <div className="cockpit-export-item-text">
                                <span className="cockpit-export-item-title">Motivational Letter</span>
                                <span className="cockpit-export-item-sub">PDF Download</span>
                              </div>
                            </a>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </header>

            <div className="cockpit-layout-grid">
            {/* LEFT COLUMN: THE JOB SPEC */}
            <div className="cockpit-left-col">
              {/* AI Summary Card */}
              <section className="cockpit-ai-summary-card">
                <div className="cockpit-summary-badge">
                  <Sparkles size={14} /> AI Summary
                </div>
                <p className="cockpit-summary-text">{job.summary || 'Summary unavailable.'}</p>
                {job.analysis_current === false && <p>Match score needs updating: your CV or scoring model changed.</p>}
                {job.analysis_current == null && <p>This historical score has not been checked against your current CV and scoring model.</p>}
                {job.eligibility && (
                  <div role="status">
                    <strong>Eligibility: {job.eligibility.label}</strong>
                    {[...(job.eligibility.blockers || []), ...(job.eligibility.unknowns || [])].map((reason) => <p key={reason}>{reason}</p>)}
                  </div>
                )}
              </section>

              {/* Requirements */}
              <section className="cockpit-card">
                <div className="cockpit-card-header">
                  <h2 className="cockpit-card-title">
                    <CheckSquare size={17} color="var(--primary-color)" /> Requirements
                  </h2>
                </div>
                {requirementsList.length > 0 ? (
                  <ul className="cockpit-list">
                    {requirementsList.map((req, idx) => (
                      <li key={idx} className="cockpit-list-item">
                        <Check size={16} className="cockpit-list-icon" />
                        <span>{req}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                    {job.skills ? `Requirements extracted from skills: ${job.skills}` : 'No structured requirements parsed.'}
                  </p>
                )}
              </section>

              {/* Metadata Grid (2x2) */}
              <section className="cockpit-meta-grid">
                <div className="cockpit-meta-item">
                  <span className="cockpit-meta-label">Work Experience</span>
                  <span className="cockpit-meta-val">{experienceYears}</span>
                </div>
                <div className="cockpit-meta-item">
                  <span className="cockpit-meta-label">Education</span>
                  <span className="cockpit-meta-val">{educationLevel}</span>
                </div>
                <div className="cockpit-meta-item">
                  <span className="cockpit-meta-label">Work Model</span>
                  <span className="cockpit-meta-val">{workModel}</span>
                </div>
                <div className="cockpit-meta-item">
                  <span className="cockpit-meta-label">Language Level</span>
                  <span className="cockpit-meta-val">{germanLevelLabel(job.german_level ?? job.requires_german)}</span>
                </div>
              </section>

              {/* Tools & Technologies */}
              {toolsList.length > 0 && (
                <section className="cockpit-card">
                  <div className="cockpit-card-header">
                    <h2 className="cockpit-card-title">
                      <Layers size={17} color="var(--primary-color)" /> Tools & Technologies
                    </h2>
                  </div>
                  <div className="cockpit-tools-wrap">
                    {toolsList.map((tool, idx) => (
                      <span key={idx} className="cockpit-tool-pill">
                        {tool}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {/* Tasks & Responsibilities */}
              {tasksList.length > 0 && (
                <section className="cockpit-card">
                  <div className="cockpit-card-header">
                    <h2 className="cockpit-card-title">
                      <FileText size={17} color="var(--primary-color)" /> Tasks & Responsibilities
                    </h2>
                  </div>
                  <ul className="cockpit-list">
                    {tasksList.map((task, idx) => (
                      <li key={idx} className="cockpit-list-item">
                        <span className="cockpit-list-icon" style={{ fontWeight: 'bold' }}>•</span>
                        <span>{task}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/* Collapsible Raw Job Description */}
              <details className="cockpit-accordion">
                <summary>Original Job Posting Description</summary>
                <div className="cockpit-accordion-content">
                  {job.raw_description || job.description || 'No raw description available.'}
                </div>
              </details>
            </div>

            {/* RIGHT COLUMN: CAREER AGENT & RESEARCH */}
            <div className="cockpit-right-col">
              {/* "Your Match Analysis" Card */}
              <section className="cockpit-match-card">
                <div className="cockpit-match-header">
                  <div className="cockpit-match-title-group">
                    <div className="cockpit-agent-avatar">
                      <Bot size={20} />
                    </div>
                    <div className="cockpit-match-headings">
                      <h2>Your Match Analysis</h2>
                      <p>from your Career Agent</p>
                    </div>
                  </div>
                  <span className="cockpit-tier-badge">
                    <span className="cockpit-tier-dot" />
                    {matchTier}
                  </span>
                </div>

                <div className="cockpit-synthesis-box">
                  {matchSynthesis}
                </div>

                {/* Why this fits */}
                <div className="cockpit-analysis-section">
                  <h3 className="cockpit-section-heading">
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--success-color)' }}>
                      <CheckCircle2 size={16} /> Why this fits
                    </span>
                  </h3>
                  {strengths.length > 0 ? (
                    strengths.map((s, idx) => (
                      <div key={idx} className="cockpit-item-card">
                        <span className="cockpit-item-title">
                          <Check size={14} color="var(--success-color)" /> {s.title}
                        </span>
                        <span className="cockpit-item-detail">{s.detail}</span>
                      </div>
                    ))
                  ) : (
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
                      Good alignment with your technical background and experience.
                    </p>
                  )}
                </div>

                {/* Possible gaps */}
                {gaps.length > 0 && (
                  <div className="cockpit-analysis-section">
                    <h3 className="cockpit-section-heading">
                      <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: '#f59e0b' }}>
                        <AlertTriangle size={16} /> Possible gaps
                      </span>
                      <span className="cockpit-count-badge">{gaps.length}</span>
                    </h3>
                    {gaps.map((g, idx) => (
                      <div key={idx} className="cockpit-item-card" style={{ borderColor: 'rgba(245, 158, 11, 0.25)' }}>
                        <span className="cockpit-item-title" style={{ color: '#f59e0b' }}>
                          {g.title}
                        </span>
                        <span className="cockpit-item-detail">{g.detail}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Application tips */}
                {tips.length > 0 && (
                  <div className="cockpit-analysis-section">
                    <h3 className="cockpit-section-heading">
                      <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--primary-color)' }}>
                        <Lightbulb size={16} /> Application tips
                      </span>
                    </h3>
                    {tips.map((t, idx) => (
                      <div key={idx} className="cockpit-item-card" style={{ borderColor: 'color-mix(in srgb, var(--primary-color) 25%, transparent)' }}>
                        <span className="cockpit-item-title" style={{ color: 'var(--primary-light)' }}>
                          <Check size={14} /> {t.title}
                        </span>
                        <span className="cockpit-item-detail">{t.detail}</span>
                      </div>
                    ))}
                  </div>
                )}


              </section>

              {/* Company Intelligence & Research (Perplexity Sonar) */}
              <section className="job-detail-section-card research-section-card">
                <div className="section-card-header">
                  <div className="section-card-title-group">
                    <div className="section-icon-badge research-badge-icon">
                      <Globe size={18} />
                    </div>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                        <h2 className="section-card-title">Company Intelligence</h2>
                        <span className="sonar-brand-badge">
                          <Sparkles size={13} /> Perplexity Sonar
                        </span>
                      </div>
                      <div className="section-card-subtitle">
                        {job.company_research_updated_at ? (
                          <span>Last researched {formatTimestamp(job.company_research_updated_at)}</span>
                        ) : (
                          <span>Live web research on mission, values, news, and tech signals.</span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="section-card-actions">
                    <button
                      className="btn btn-primary btn-sonar"
                      onClick={handleResearchClick}
                      disabled={demo || researching}
                    >
                      <RefreshCw size={15} className={researching ? 'spin' : ''} />
                      <span>{researching ? 'Researching…' : (researchText ? 'Re-run Sonar' : 'Research Sonar')}</span>
                    </button>
                    <button
                      className="btn btn-secondary btn-save-notes"
                      onClick={handleSaveNotesClick}
                      disabled={demo || savingNotes || !isDirty}
                    >
                      <Save size={15} />
                      <span>{savingNotes ? 'Saving…' : (isDirty ? 'Save Notes' : 'Saved')}</span>
                    </button>
                  </div>
                </div>

                <div className="research-content-wrapper">
                  <div className="research-toolbar">
                    <label className="research-toggle-label">
                      <input
                        type="checkbox"
                        checked={useInDocs}
                        onChange={(e) => handleToggleUseInDocs(e.target.checked)}
                      />
                      <span>Inject research into tailored Cover Letters</span>
                    </label>
                    {isDirty && (
                      <span className="research-unsaved-badge">
                        <AlertCircle size={13} /> Unsaved edits
                      </span>
                    )}
                  </div>

                  <textarea readOnly={demo}
                    className="research-textarea"
                    value={researchText}
                    onChange={(e) => {
                      setResearchText(e.target.value);
                      setIsDirty(true);
                    }}
                    placeholder={`Scour the web using Perplexity Sonar for ${job.company}'s core values, recent news, breakthroughs, and tech stack.\n\nYou can also freely type or edit notes here.`}
                    rows={8}
                  />
                </div>
              </section>
            </div>
          </div>
          </>
        )}

        {/* TAB 2: IN-JOB TAILOR STUDIO */}
        {activeSubTab === 'studio' && demo && <DemoDocuments key={job.id} job={job} />}
        {activeSubTab === 'studio' && !demo && (
          <>
            {/* Sleek 1-line Job Context Bar */}
            <div className="studio-job-context-bar">
              <div className="studio-job-context-info">
                <span className="studio-job-context-title">{job.title}</span>
                <span className="studio-job-context-company">
                  <Building2 size={14} /> {job.company}
                </span>
                {job.location && (
                  <span className="studio-job-context-location hide-mobile">
                    <MapPin size={13} /> {job.location}
                  </span>
                )}
                {job.match_score != null && (
                  <span className={`badge ${getScoreBadgeClass(job.match_score)} studio-job-context-match`}>
                    {job.match_score}% Match
                  </span>
                )}
                {job.salary_yearly && (
                  <span className="studio-job-context-salary hide-mobile">
                    €{Number(job.salary_yearly).toLocaleString('de-AT')}/yr
                  </span>
                )}
              </div>
            </div>

            <div className="studio-container job-studio-container">
            {/* Top Action & Navigation Bar */}
            <div className="studio-topbar">
              <div className="studio-topbar-row-main">
                <div className="job-doc-switcher">
                  <button
                    type="button"
                    className={`job-doc-btn ${studio.activeDocType === 'cv' ? 'active' : ''} ${!studio.hasCv && !studio.cvTex ? 'disabled' : ''}`}
                    onClick={() => studio.setActiveDocType('cv')}
                    disabled={!studio.hasCv && !studio.cvTex}
                  >
                    <span>Curriculum Vitae</span>
                    {studio.hasCv && studio.cvEngine && (
                      <EngineBadge engine={studio.cvEngine} size="sm" />
                    )}
                  </button>
                  <button
                    type="button"
                    className={`job-doc-btn ${studio.activeDocType === 'letter' ? 'active' : ''} ${!studio.hasLetter && !studio.clTex ? 'disabled' : ''}`}
                    onClick={() => studio.setActiveDocType('letter')}
                    disabled={!studio.hasLetter && !studio.clTex}
                  >
                    <span>Motivational Letter</span>
                    {studio.hasLetter && studio.clEngine && (
                      <EngineBadge engine={studio.clEngine} size="sm" />
                    )}
                  </button>
                </div>

                <button
                  type="button"
                  className={`btn btn-secondary btn-sm ${studio.showCheatSheet ? 'active' : ''}`}
                  onClick={() => studio.setShowCheatSheet(!studio.showCheatSheet)}
                  title="View job requirements & match tips alongside editor"
                >
                  <Layers size={14} />
                  <span>Job Cheat Sheet</span>
                </button>
              </div>

              {/* Actions Group: Zoom Controls + Compile + Save + PDF */}
              <div className="studio-actions-group">
                {/* Zoom Controls in topbar (desktop only) */}
                <div className="studio-preview-zoom-group studio-zoom-desktop">
                  <button
                    type="button"
                    className="btn btn-sm btn-secondary"
                    onClick={() => studio.setZoom((z) => Math.max(50, z - 10))}
                    title="Zoom Out"
                  >
                    <ZoomOut size={14} />
                  </button>
                  <span className="studio-zoom-indicator">{studio.zoom}%</span>
                  <button
                    type="button"
                    className="btn btn-sm btn-secondary"
                    onClick={() => studio.setZoom((z) => Math.min(200, z + 10))}
                    title="Zoom In"
                  >
                    <ZoomIn size={14} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-secondary"
                    onClick={() => studio.setZoom(100)}
                    title="Reset Zoom (100%)"
                  >
                    <Maximize2 size={14} />
                  </button>
                </div>

                {studio.docEngine === 'typst' ? (
                  <span className="studio-page-badge studio-badge-desktop">
                    {studioPageCount} {studioPageCount === 1 ? 'Page' : 'Pages'}
                  </span>
                ) : (
                  studio.currentImages && studio.currentImages.length > 0 && (
                    <span className="studio-page-badge studio-badge-desktop">
                      {studio.currentImages.length} {studio.currentImages.length === 1 ? 'Page' : 'Pages'}
                    </span>
                  )
                )}

                {/* AI Versions Dropdown & Restore Control */}
                {studio.aiVersions?.[studio.activeDocType]?.length > 0 && (
                  <div className="studio-version-control" title="View and switch between versions before and after AI refinements">
                    <History size={13} className="studio-version-icon" />
                    <select
                      className="studio-version-select"
                      aria-label="Document Version"
                      value={studio.activeVersionId || ""}
                      onChange={(e) => {
                        const vId = e.target.value;
                        if (vId) studio.restoreVersion(vId);
                      }}
                      disabled={studio.compiling || studio.aiEditing}
                    >
                      <option value="" disabled={Boolean(studio.activeVersionId)}>
                        {studio.activeVersionId ? 'Select Version…' : 'Current Draft (Edited)'} ({studio.aiVersions[studio.activeDocType].length})
                      </option>
                      {studio.aiVersions[studio.activeDocType].map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.date_str ? `${v.date_str} – ` : ''}{v.label}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="studio-topbar-divider studio-divider-desktop" />

                <button
                  type="button"
                  className="btn btn-primary studio-btn-compile"
                  onClick={studio.compile}
                  disabled={studio.compiling || studio.loading || !studio.currentTex}
                  title={studio.docEngine === 'typst' ? 'Compile & sync PDF to disk (pure WASM)' : 'Recompile document with pdflatex (Ctrl+Enter)'}
                >
                  {studio.compiling ? <RefreshCw className="spinner" size={15} /> : <Play size={15} fill="currentColor" />}
                  <span>{studio.compiling ? 'Compiling…' : 'Compile'}</span>
                </button>

                <button
                  type="button"
                  className="btn btn-secondary studio-btn-save"
                  onClick={studio.finalize}
                  disabled={studio.saving || studio.compiling}
                  title="Promote draft to official user outputs"
                >
                  {studio.saving ? <RefreshCw className="spinner" size={15} /> : <Save size={15} />}
                  <span className="btn-label-desktop">{studio.saving ? 'Saving…' : 'Save as Final'}</span>
                </button>

                {studio.docEngine === 'typst' ? (
                  <button
                    type="button"
                    onClick={() => studio.downloadClientPdf()}
                    className="btn btn-secondary studio-btn-pdf"
                    title="Instant client-side PDF download (pure WASM)"
                  >
                    <Download size={15} /><span className="btn-label-desktop">PDF</span>
                  </button>
                ) : (
                  ((studio.activeDocType === 'cv' ? studio.cvDownloadUrl : studio.clDownloadUrl) ||
                    (studio.activeDocType === 'cv' ? job.cv_url : job.letter_url)) && (
                    <a
                      href={(studio.activeDocType === 'cv' ? studio.cvDownloadUrl : studio.clDownloadUrl) ||
                            (studio.activeDocType === 'cv' ? job.cv_url : job.letter_url)}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-secondary studio-btn-pdf"
                      title="Download compiled PDF"
                    >
                      <Download size={15} /><span className="btn-label-desktop">PDF</span>
                    </a>
                  )
                )}
              </div>
            </div>

            {/* If no document generated yet */}
            {!studio.pdfCurrent && studio.currentTex && <p role="status">The previous PDF may be out of date. Compile this version before finalizing.</p>}
            {!studio.loading && !studio.hasCv && !studio.hasLetter && !studio.currentTex ? (
              <div className="card" style={{ padding: '3.5rem 2rem', textAlign: 'center', margin: '1rem 0' }}>
                <Wand2 size={44} color="var(--primary-color)" style={{ margin: '0 auto 1rem', display: 'block' }} />
                <h2 style={{ fontSize: '1.2rem', marginBottom: '0.5rem', color: 'var(--text-primary)' }}>
                  No Tailored Documents Generated Yet
                </h2>
                <p style={{ color: 'var(--text-secondary)', maxWidth: '520px', margin: '0 auto 1.5rem', lineHeight: 1.5 }}>
                  Generate a tailored Curriculum Vitae or Motivational Letter for {job.company}.
                </p>

                {/* Engine Selector in Empty State */}
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', background: 'var(--bg-color)', padding: '0.35rem 0.65rem', borderRadius: '8px', border: '1px solid var(--border-color)', marginBottom: '1.5rem' }}>
                  <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)' }}>Format:</span>
                  <button
                    type="button"
                    className={`btn btn-sm ${selectedEngine === 'typst' ? 'btn-primary' : 'btn-secondary'}`}
                    style={{ padding: '0.25rem 0.65rem', fontSize: '0.8rem', height: '28px' }}
                    onClick={() => setSelectedEngine('typst')}
                  >
                    Typst
                  </button>
                  <button
                    type="button"
                    className={`btn btn-sm ${selectedEngine === 'latex' ? 'btn-primary' : 'btn-secondary'}`}
                    style={{ padding: '0.25rem 0.65rem', fontSize: '0.8rem', height: '28px' }}
                    onClick={() => setSelectedEngine('latex')}
                  >
                    LaTeX
                  </button>
                </div>

                <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', flexWrap: 'wrap' }}>
                  {handleJobsGenerateBoth && (
                    <button
                      className="btn btn-primary"
                      onClick={async () => {
                        await handleJobsGenerateBoth(job, { compact, engine: selectedEngine });
                        studio.fetchDocuments();
                      }}
                      disabled={demo || isGeneratingBoth}
                    >
                      <Sparkles size={16} />
                      <span>{isGeneratingBoth ? 'Generating Both…' : 'Generate Both (CV & Letter)'}</span>
                    </button>
                  )}
                  {handleJobsGenerateCV && (
                    <button
                      className="btn btn-secondary"
                      onClick={async () => {
                        await handleJobsGenerateCV(job, { compact, engine: selectedEngine });
                        studio.fetchDocuments();
                      }}
                      disabled={demo || isGeneratingCV}
                    >
                      {isGeneratingCV ? 'Generating CV…' : 'Generate CV Only'}
                    </button>
                  )}
                  {handleJobsGenerateLetter && (
                    <button
                      className="btn btn-secondary"
                      onClick={async () => {
                        await handleJobsGenerateLetter(job, { engine: selectedEngine });
                        studio.fetchDocuments();
                      }}
                      disabled={demo || isGeneratingCL}
                    >
                      {isGeneratingCL ? 'Generating Letter…' : 'Generate Letter Only'}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              /* Studio Split Workspace */
              <div className="studio-split-view">
                {/* Left Pane: Code / Visual Editor */}
                <div className="studio-editor-pane">
                  {/* Segmented Mode Header */}
                  <div className="studio-mode-header">
                    {studio.docEngine === 'typst' ? (
                      <div className="studio-segmented-mode">
                        <button
                          type="button"
                          className={`studio-mode-btn ${editorMode === 'simple' ? 'active' : ''}`}
                          onClick={() => handleSwitchMode('simple')}
                          title="Visual form editor with dynamic bullet controls"
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
                      {editorMode === 'simple' && parsedTypst && (
                        <span className="studio-mode-pill">
                          {parsedTypst.kind === 'moderner-cv' ? 'ModernCV Form' : (parsedTypst.kind === 'standard-cv' ? 'Standard CV Form' : 'Cover Letter Form')}
                        </span>
                      )}
                      {editorMode === 'advanced' && (
                        <span className="studio-mode-pill-muted">
                          {editorLines.length} lines
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
                      disabled={studio.saving || studio.compiling || studio.aiEditing}
                    />
                  ) : (
                    <StudioCodeEditor
                      ref={textareaRef}
                      value={studio.currentTex}
                      onChange={(val) => studio.setCurrentTex(val)}
                      onCompile={studio.compile}
                      placeholder={`% ${studio.activeDocType === 'cv' ? 'Curriculum Vitae' : 'Motivational Letter'} source`}
                    />
                  )}

                  {/* AI Surgical Assistant Prompt Bar */}
                  <div className="studio-ai-bar">
                    <form onSubmit={handleAiPromptSubmit} className="studio-ai-input-row">
                      <Sparkles size={16} className="studio-ai-icon" />
                      <input
                        type="text"
                        className="studio-ai-input"
                        placeholder={studio.aiEditing ? 'AI is selecting approved evidence…' : 'Choose relevant approved evidence. Edit new wording manually.'}
                        value={aiPrompt}
                        onChange={(e) => setAiPrompt(e.target.value)}
                        disabled={studio.aiEditing}
                      />
                      <button
                        type="submit"
                        className="studio-ai-submit-btn"
                        disabled={studio.aiEditing || !aiPrompt.trim()}
                      >
                        {studio.aiEditing ? <RefreshCw size={14} className="spin" /> : <Sparkles size={14} />}
                        <span>{studio.aiEditing ? 'Applying…' : 'Apply'}</span>
                      </button>
                      {studio.aiVersions?.[studio.activeDocType]?.length > 0 && (() => {
                        const list = studio.aiVersions[studio.activeDocType];
                        const currentIndex = list.findIndex((v) => String(v.id) === String(studio.activeVersionId));
                        const isUndo = (currentIndex === 0 || currentIndex === -1);
                        const targetVersion = isUndo ? (list[1] || list[0]) : list[0];
                        return (
                          <button
                            type="button"
                            className="studio-history-revert-btn"
                            onClick={() => {
                              if (targetVersion) studio.restoreVersion(targetVersion.id);
                            }}
                            disabled={studio.aiEditing || studio.compiling}
                            title={isUndo ? `Revert to ${targetVersion.label}` : `Redo to ${targetVersion.label}`}
                          >
                            <Undo2 size={13} style={{ transform: isUndo ? 'none' : 'scaleX(-1)' }} />
                            <span>{isUndo ? 'Undo AI Edit' : 'Redo AI Edit'}</span>
                          </button>
                        );
                      })()}
                    </form>

                    <div className="studio-ai-chips">
                      <span className="studio-chip-label">Suggestions:</span>
                      {tips.length > 0 && (
                        <button
                          type="button"
                          className="studio-chip studio-chip-tip"
                          onClick={() => handleQuickChip(`Apply application tip: ${tips[0].title}`)}
                          disabled={studio.aiEditing}
                        >
                          <Lightbulb size={12} />
                          <span>Tip: {tips[0].title}</span>
                        </button>
                      )}
                      <button
                        type="button"
                        className="studio-chip"
                        onClick={() => handleQuickChip('Select fewer relevant evidence bullets; preserve dates and wording')}
                        disabled={studio.aiEditing}
                      >
                        <FileText size={12} />
                        <span>Shorter selection</span>
                      </button>
                      <button
                        type="button"
                        className="studio-chip"
                        onClick={() => handleQuickChip('Select evidence relevant to scientific computing and automation')}
                        disabled={studio.aiEditing}
                      >
                        <Sparkles size={12} />
                        <span>Scientific computing</span>
                      </button>
                      <button
                        type="button"
                        className="studio-chip"
                        onClick={() => handleQuickChip('Select evidence relevant to industry Python roles')}
                        disabled={studio.aiEditing}
                      >
                        <Globe size={12} />
                        <span>Industry selection</span>
                      </button>
                    </div>
                  </div>
                </div>

                {/* Right Pane: Live PDF Page Preview */}
                <div className="studio-preview-pane">
                  {studio.docEngine === 'typst' ? (
                    <TypstWasmPreview
                      source={studio.currentTex}
                      zoom={studio.zoom}
                      onPageCountChange={(cnt) => setStudioPageCount(cnt)}
                    />
                  ) : (
                    <>
                      {/* Mobile-only Preview Toolbar */}
                      <div className="studio-preview-mobile-bar">
                        <div className="studio-preview-mobile-zoom">
                          <button
                            type="button"
                            className="btn btn-sm btn-secondary"
                            onClick={() => studio.setZoom((z) => Math.max(50, z - 10))}
                            title="Zoom Out"
                          >
                            <ZoomOut size={13} />
                          </button>
                          <span className="studio-zoom-indicator">{studio.zoom}%</span>
                          <button
                            type="button"
                            className="btn btn-sm btn-secondary"
                            onClick={() => studio.setZoom((z) => Math.min(200, z + 10))}
                            title="Zoom In"
                          >
                            <ZoomIn size={13} />
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm btn-secondary"
                            onClick={() => studio.setZoom(100)}
                            title="Reset Zoom (100%)"
                          >
                            <Maximize2 size={13} />
                          </button>
                        </div>

                        {studio.currentImages && studio.currentImages.length > 0 && (
                          <span className="studio-page-badge">
                            {studio.currentImages.length} {studio.currentImages.length === 1 ? 'Page' : 'Pages'}
                          </span>
                        )}
                      </div>

                      {/* Diagnostic Error Card */}
                      {studio.errorCard && (
                        <div className="studio-error-card">
                          <div className="studio-error-header">
                            <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                              <AlertTriangle size={16} /> Compilation Diagnostic
                            </span>
                            {studio.errorCard.rawLog && (
                              <button
                                type="button"
                                className="studio-toggle-log-btn"
                                onClick={() => setShowRawLog(!showRawLog)}
                              >
                                {showRawLog ? 'Hide Raw Log' : 'View Full Log'}
                              </button>
                            )}
                          </div>
                          <div className="studio-error-message">{studio.errorCard.message}</div>
                          {studio.errorCard.parsed && (
                            <div className="studio-error-snippet">
                              {studio.errorCard.parsed.line && (
                                <strong>Line {studio.errorCard.parsed.line}: </strong>
                              )}
                              <span>{studio.errorCard.parsed.error}</span>
                            </div>
                          )}
                          {showRawLog && studio.errorCard.rawLog && (
                            <pre className="studio-error-raw-log">{studio.errorCard.rawLog}</pre>
                          )}
                        </div>
                      )}

                      {/* Stacked Preview Images */}
                      <div className="studio-pages-scroll-container">
                        {studio.compiling && (
                          <div className="studio-compiling-overlay">
                            <RefreshCw size={28} className="spin" />
                            <span>Compiling document…</span>
                          </div>
                        )}
                        {studio.currentImages.length > 0 ? (
                          <div
                            className="studio-pages-wrapper"
                            style={{ transform: `scale(${studio.zoom / 100})`, transformOrigin: 'top center' }}
                          >
                            {studio.currentImages.map((url, idx) => (
                              <div key={idx} className="studio-page-card">
                                <img src={url} alt={`Page ${idx + 1}`} className="studio-page-img" />
                                <span className="studio-page-number">Page {idx + 1}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="studio-preview-placeholder">
                            <FileText size={48} style={{ opacity: 0.3, marginBottom: '0.75rem' }} />
                            <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
                              Click <strong>Compile</strong> to generate live PDF preview pages.
                            </p>
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* Slide-Out Job Cheat Sheet Drawer */}
            {studio.showCheatSheet && (
              <>
                <div
                  className="cheat-sheet-overlay"
                  onClick={() => studio.setShowCheatSheet(false)}
                />
                <aside className="cheat-sheet-drawer" aria-label="Job Requirements Cheat Sheet">
                  <div className="cheat-sheet-header">
                    <h2 className="cheat-sheet-title">Job Cheat Sheet</h2>
                    <button
                      type="button"
                      className="btn-icon"
                      onClick={() => studio.setShowCheatSheet(false)}
                      title="Close drawer (Esc)"
                    >
                      <X size={18} />
                    </button>
                  </div>

                  <div className="cheat-sheet-body">
                    <div>
                      <h3 style={{ margin: '0 0 0.4rem', fontSize: '0.95rem', fontWeight: 600 }}>
                        {job.title}
                      </h3>
                      <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        {job.company} — {job.location}
                      </p>
                    </div>

                    {/* Requirements */}
                    <div>
                      <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
                        Key Requirements
                      </h4>
                      {requirementsList.length > 0 ? (
                        <ul style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.88rem', lineHeight: 1.5 }}>
                          {requirementsList.map((r, i) => (
                            <li key={i} style={{ marginBottom: '0.35rem' }}>{r}</li>
                          ))}
                        </ul>
                      ) : (
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{job.skills}</p>
                      )}
                    </div>

                    {/* Application Tips */}
                    {tips.length > 0 && (
                      <div>
                        <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--primary-light)' }}>
                          Application Tips
                        </h4>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                          {tips.map((t, i) => (
                            <div key={i} style={{ fontSize: '0.85rem', background: 'var(--bg-color)', padding: '0.6rem', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                              <strong style={{ display: 'block', color: 'var(--text-primary)', marginBottom: '0.2rem' }}>{t.title}</strong>
                              <span style={{ color: 'var(--text-secondary)' }}>{t.detail}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Gaps */}
                    {gaps.length > 0 && (
                      <div>
                        <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.85rem', textTransform: 'uppercase', color: '#f59e0b' }}>
                          Gaps to Address
                        </h4>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                          {gaps.map((g, i) => (
                            <div key={i} style={{ fontSize: '0.85rem', background: 'var(--bg-color)', padding: '0.6rem', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                              <strong style={{ display: 'block', color: '#f59e0b', marginBottom: '0.2rem' }}>{g.title}</strong>
                              <span style={{ color: 'var(--text-secondary)' }}>{g.detail}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Company Research Notes */}
                    {researchText && (
                      <div>
                        <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
                          Company Research Notes
                        </h4>
                        <pre style={{ margin: 0, padding: '0.75rem', fontSize: '0.8rem', whiteSpace: 'pre-wrap', background: 'var(--bg-color)', borderRadius: '4px', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>
                          {researchText}
                        </pre>
                      </div>
                    )}
                  </div>
                </aside>
              </>
            )}
          </div>
          </>
        )}
      </div>
    </div>
  );
}
