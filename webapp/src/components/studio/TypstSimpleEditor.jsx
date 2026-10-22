import React, { useRef, useCallback, useLayoutEffect } from 'react';
import {
  User, Briefcase, GraduationCap, Wrench, FileText, Plus, Trash2,
  ChevronDown, ChevronRight, Layers, Sparkles, Building2
} from 'lucide-react';

/**
 * Auto-expanding textarea that dynamically grows with content,
 * eliminating inner scrollbars completely.
 */
function AutoResizeTextarea({
  value = '',
  onChange,
  minRows = 2,
  className = '',
  style = {},
  placeholder = '',
  disabled = false,
  ...props
}) {
  const textareaRef = useRef(null);

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const minH = minRows * 22 + 14;
    el.style.height = `${Math.max(el.scrollHeight, minH)}px`;
  }, [minRows]);

  useLayoutEffect(() => {
    adjustHeight();
    window.addEventListener('resize', adjustHeight);
    return () => window.removeEventListener('resize', adjustHeight);
  }, [value, adjustHeight]);

  const handleChange = (e) => {
    if (onChange) onChange(e);
    adjustHeight();
  };

  return (
    <textarea
      ref={textareaRef}
      value={value || ''}
      onChange={handleChange}
      className={className}
      rows={minRows}
      style={{
        resize: 'none',
        overflow: 'hidden',
        ...style,
      }}
      placeholder={placeholder}
      disabled={disabled}
      {...props}
    />
  );
}

export function TypstSimpleEditor({ data, kind, onChange, disabled = false, openSections = { basics: true }, setOpenSections }) {
  if (!data) return null;

  const toggleSection = (id) => {
    setOpenSections((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const isCoverLetter = kind === 'cover-letter';

  // --- Handlers for Basics ---
  const handleBasicsChange = (field, value) => {
    const updated = {
      ...data,
      basics: {
        ...data.basics,
        [field]: value,
      },
    };
    onChange(updated);
  };

  // --- Handlers for CV Sections ---
  const handleSummaryChange = (secIdx, value) => {
    const newSections = [...data.sections];
    newSections[secIdx] = { ...newSections[secIdx], text: value };
    onChange({ ...data, sections: newSections });
  };

  const handleSkillGroupChange = (secIdx, grpIdx, field, value) => {
    const newSections = [...data.sections];
    const newGroups = [...(newSections[secIdx].groups || [])];
    newGroups[grpIdx] = { ...newGroups[grpIdx], [field]: value };
    newSections[secIdx] = { ...newSections[secIdx], groups: newGroups };
    onChange({ ...data, sections: newSections });
  };

  const handleAddSkillGroup = (secIdx) => {
    const newSections = [...data.sections];
    const newGroups = [...(newSections[secIdx].groups || []), { category: 'New Category', skills: 'Skill 1, Skill 2' }];
    newSections[secIdx] = { ...newSections[secIdx], groups: newGroups };
    onChange({ ...data, sections: newSections });
  };

  const handleDeleteSkillGroup = (secIdx, grpIdx) => {
    const newSections = [...data.sections];
    const newGroups = (newSections[secIdx].groups || []).filter((_, i) => i !== grpIdx);
    newSections[secIdx] = { ...newSections[secIdx], groups: newGroups };
    onChange({ ...data, sections: newSections });
  };

  const handleEntryChange = (secIdx, entIdx, field, value) => {
    const newSections = [...data.sections];
    const newEntries = [...(newSections[secIdx].entries || [])];
    newEntries[entIdx] = { ...newEntries[entIdx], [field]: value };
    newSections[secIdx] = { ...newSections[secIdx], entries: newEntries };
    onChange({ ...data, sections: newSections });
  };

  const handleBulletChange = (secIdx, entIdx, bIdx, value) => {
    const newSections = [...data.sections];
    const newEntries = [...(newSections[secIdx].entries || [])];
    const newBullets = [...(newEntries[entIdx].bullets || [])];
    newBullets[bIdx] = value;
    newEntries[entIdx] = { ...newEntries[entIdx], bullets: newBullets };
    newSections[secIdx] = { ...newSections[secIdx], entries: newEntries };
    onChange({ ...data, sections: newSections });
  };

  const handleAddBullet = (secIdx, entIdx) => {
    const newSections = [...data.sections];
    const newEntries = [...(newSections[secIdx].entries || [])];
    const newBullets = [...(newEntries[entIdx].bullets || []), 'New accomplishment or project highlight'];
    newEntries[entIdx] = { ...newEntries[entIdx], bullets: newBullets };
    newSections[secIdx] = { ...newSections[secIdx], entries: newEntries };
    onChange({ ...data, sections: newSections });
  };

  const handleDeleteBullet = (secIdx, entIdx, bIdx) => {
    const newSections = [...data.sections];
    const newEntries = [...(newSections[secIdx].entries || [])];
    const newBullets = (newEntries[entIdx].bullets || []).filter((_, i) => i !== bIdx);
    newEntries[entIdx] = { ...newEntries[entIdx], bullets: newBullets };
    newSections[secIdx] = { ...newSections[secIdx], entries: newEntries };
    onChange({ ...data, sections: newSections });
  };

  const handleAddEntry = (secIdx) => {
    const newSections = [...data.sections];
    const newEntries = [
      ...(newSections[secIdx].entries || []),
      {
        title: 'New Position',
        employer: 'Company / Organization',
        date: '2024 – Present',
        location: 'Vienna, Austria',
        bullets: ['Key achievement or responsibility'],
        note: '',
      },
    ];
    newSections[secIdx] = { ...newSections[secIdx], entries: newEntries };
    onChange({ ...data, sections: newSections });
  };

  const handleDeleteEntry = (secIdx, entIdx) => {
    const newSections = [...data.sections];
    const newEntries = (newSections[secIdx].entries || []).filter((_, i) => i !== entIdx);
    newSections[secIdx] = { ...newSections[secIdx], entries: newEntries };
    onChange({ ...data, sections: newSections });
  };

  const handleLineItemChange = (secIdx, itIdx, field, value) => {
    const newSections = [...data.sections];
    const newItems = [...(newSections[secIdx].items || [])];
    newItems[itIdx] = { ...newItems[itIdx], [field]: value };
    newSections[secIdx] = { ...newSections[secIdx], items: newItems };
    onChange({ ...data, sections: newSections });
  };

  const handleAddLineItem = (secIdx) => {
    const newSections = [...data.sections];
    const newItems = [...(newSections[secIdx].items || []), { category: 'Project', content: 'Description of technical project or interest.' }];
    newSections[secIdx] = { ...newSections[secIdx], items: newItems };
    onChange({ ...data, sections: newSections });
  };

  const handleDeleteLineItem = (secIdx, itIdx) => {
    const newSections = [...data.sections];
    const newItems = (newSections[secIdx].items || []).filter((_, i) => i !== itIdx);
    newSections[secIdx] = { ...newSections[secIdx], items: newItems };
    onChange({ ...data, sections: newSections });
  };

  // --- Handlers for Cover Letter ---
  const handleRecipientChange = (field, value) => {
    onChange({
      ...data,
      recipient: {
        ...data.recipient,
        [field]: value,
      },
    });
  };

  const handleParagraphChange = (pIdx, value) => {
    const newParas = [...(data.paragraphs || [])];
    newParas[pIdx] = value;
    onChange({ ...data, paragraphs: newParas });
  };

  const handleAddParagraph = () => {
    const newParas = [...(data.paragraphs || []), 'New paragraph elaborating on your motivation and qualifications.'];
    onChange({ ...data, paragraphs: newParas });
  };

  const handleDeleteParagraph = (pIdx) => {
    const newParas = (data.paragraphs || []).filter((_, i) => i !== pIdx);
    onChange({ ...data, paragraphs: newParas });
  };

  const getSectionIcon = (title) => {
    const t = (title || '').toLowerCase();
    if (t.includes('summary') || t.includes('profile')) return <FileText size={16} className="simple-sec-icon" />;
    if (t.includes('skill')) return <Wrench size={16} className="simple-sec-icon" />;
    if (t.includes('experience') || t.includes('work')) return <Briefcase size={16} className="simple-sec-icon" />;
    if (t.includes('education')) return <GraduationCap size={16} className="simple-sec-icon" />;
    if (t.includes('project') || t.includes('interest')) return <Layers size={16} className="simple-sec-icon" />;
    return <Sparkles size={16} className="simple-sec-icon" />;
  };

  return (
    <div className="simple-editor-container">
      {/* 1. Header & Personal Info Card */}
      <div className="simple-section-card">
        <div className="simple-section-header" onClick={() => toggleSection('basics')}>
          <div className="simple-section-title">
            <User size={16} className="simple-sec-icon" />
            <span>Personal Information</span>
            {data.basics?.name && (
              <span className="simple-badge-count">{data.basics.name}</span>
            )}
          </div>
          {openSections['basics'] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </div>

        {openSections['basics'] && (
          <div className="simple-section-body">
            <div className="simple-grid-2">
              <div className="form-group">
                <label className="simple-label">Full Name</label>
                <input
                  type="text"
                  className="input-base"
                  value={data.basics?.name || ''}
                  onChange={(e) => handleBasicsChange('name', e.target.value)}
                  disabled={disabled}
                  placeholder="e.g. Alex Muster, BSc"
                />
              </div>

              {!isCoverLetter && (
                <div className="form-group">
                  <label className="simple-label">Professional Title / Subtitle</label>
                  <input
                    type="text"
                    className="input-base"
                    value={data.basics?.subtitle || ''}
                    onChange={(e) => handleBasicsChange('subtitle', e.target.value)}
                    disabled={disabled}
                    placeholder="e.g. Senior Python Developer"
                  />
                </div>
              )}
            </div>

            <div className="simple-grid-2">
              <div className="form-group">
                <label className="simple-label">Email</label>
                <input
                  type="email"
                  className="input-base"
                  value={data.basics?.email || ''}
                  onChange={(e) => handleBasicsChange('email', e.target.value)}
                  disabled={disabled}
                  placeholder="name@example.com"
                />
              </div>
              <div className="form-group">
                <label className="simple-label">Phone</label>
                <input
                  type="text"
                  className="input-base"
                  value={data.basics?.phone || ''}
                  onChange={(e) => handleBasicsChange('phone', e.target.value)}
                  disabled={disabled}
                  placeholder="+43 123 456789"
                />
              </div>
            </div>

            <div className="simple-grid-2">
              <div className="form-group">
                <label className="simple-label">Location / Address</label>
                <input
                  type="text"
                  className="input-base"
                  value={data.basics?.address || ''}
                  onChange={(e) => handleBasicsChange('address', e.target.value)}
                  disabled={disabled}
                  placeholder="Vienna, Austria"
                />
              </div>
              <div className="form-group">
                <label className="simple-label">LinkedIn Username / URL</label>
                <input
                  type="text"
                  className="input-base"
                  value={data.basics?.linkedin || ''}
                  onChange={(e) => handleBasicsChange('linkedin', e.target.value)}
                  disabled={disabled}
                  placeholder="alex-muster"
                />
              </div>
            </div>

            <div className="simple-grid-2">
              {!isCoverLetter && (
                <div className="form-group">
                  <label className="simple-label">GitHub Username</label>
                  <input
                    type="text"
                    className="input-base"
                    value={data.basics?.github || ''}
                    onChange={(e) => handleBasicsChange('github', e.target.value)}
                    disabled={disabled}
                    placeholder="alexmuster"
                  />
                </div>
              )}
              <div className="form-group">
                <label className="simple-label">Work Authorization / Residence</label>
                <input
                  type="text"
                  className="input-base"
                  value={data.basics?.residence || ''}
                  onChange={(e) => handleBasicsChange('residence', e.target.value)}
                  disabled={disabled}
                  placeholder="e.g. Daueraufenthalt EU"
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 2. Cover Letter Specific Form */}
      {isCoverLetter && (
        <>
          {/* Recipient Card */}
          <div className="simple-section-card">
            <div className="simple-section-header" onClick={() => toggleSection('recipient')}>
              <div className="simple-section-title">
                <Building2 size={16} className="simple-sec-icon" />
                <span>Recipient & Letter Details</span>
                {data.recipient?.company && (
                  <span className="simple-badge-count">{data.recipient.company}</span>
                )}
              </div>
              {openSections['recipient'] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </div>

            {openSections['recipient'] && (
              <div className="simple-section-body">
                <div className="simple-grid-2">
                  <div className="form-group">
                    <label className="simple-label">Contact Person / Department</label>
                    <input
                      type="text"
                      className="input-base"
                      value={data.recipient?.contact || ''}
                      onChange={(e) => handleRecipientChange('contact', e.target.value)}
                      disabled={disabled}
                      placeholder="e.g. Hiring Team / Engineering Leadership"
                    />
                  </div>
                  <div className="form-group">
                    <label className="simple-label">Company Name</label>
                    <input
                      type="text"
                      className="input-base"
                      value={data.recipient?.company || ''}
                      onChange={(e) => handleRecipientChange('company', e.target.value)}
                      disabled={disabled}
                      placeholder="e.g. Example Tech GmbH"
                    />
                  </div>
                </div>

                <div className="simple-grid-2">
                  <div className="form-group">
                    <label className="simple-label">Company Address</label>
                    <input
                      type="text"
                      className="input-base"
                      value={data.recipient?.address || ''}
                      onChange={(e) => handleRecipientChange('address', e.target.value)}
                      disabled={disabled}
                      placeholder="e.g. Musterstraße 123, 1010 Vienna"
                    />
                  </div>
                  <div className="form-group">
                    <label className="simple-label">Date Display</label>
                    <input
                      type="text"
                      className="input-base"
                      value={data.recipient?.date || 'Today'}
                      onChange={(e) => handleRecipientChange('date', e.target.value)}
                      disabled={disabled}
                      placeholder="Today"
                    />
                  </div>
                </div>

                <div className="simple-grid-2">
                  <div className="form-group">
                    <label className="simple-label">Subject Line</label>
                    <input
                      type="text"
                      className="input-base"
                      value={data.subject || ''}
                      onChange={(e) => onChange({ ...data, subject: e.target.value })}
                      disabled={disabled}
                      placeholder="Application for Software Developer"
                    />
                  </div>
                  <div className="form-group">
                    <label className="simple-label">Salutation</label>
                    <input
                      type="text"
                      className="input-base"
                      value={data.salutation || ''}
                      onChange={(e) => onChange({ ...data, salutation: e.target.value })}
                      disabled={disabled}
                      placeholder="Dear Hiring Team,"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Letter Body Paragraphs */}
          <div className="simple-section-card">
            <div className="simple-section-header" onClick={() => toggleSection('paragraphs')}>
              <div className="simple-section-title">
                <FileText size={16} className="simple-sec-icon" />
                <span>Letter Body</span>
                <span className="simple-badge-count">
                  {(data.paragraphs || []).length} {data.paragraphs?.length === 1 ? 'paragraph' : 'paragraphs'}
                </span>
              </div>
              {openSections['paragraphs'] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </div>

            {openSections['paragraphs'] && (
              <div className="simple-section-body">
                {(data.paragraphs || []).map((para, pIdx) => (
                  <div key={pIdx} className="simple-paragraph-block">
                    <div className="simple-paragraph-header">
                      <span className="simple-paragraph-badge">Paragraph {pIdx + 1}</span>
                      <button
                        type="button"
                        className="btn-icon btn-icon-danger"
                        onClick={() => handleDeleteParagraph(pIdx)}
                        title="Delete paragraph"
                        disabled={disabled}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                    <AutoResizeTextarea
                      className="input-base auto-resize-textarea"
                      minRows={3}
                      value={para}
                      onChange={(e) => handleParagraphChange(pIdx, e.target.value)}
                      disabled={disabled}
                      placeholder="Write paragraph content..."
                    />
                  </div>
                ))}

                <button
                  type="button"
                  className="btn btn-secondary btn-sm simple-btn-add"
                  onClick={handleAddParagraph}
                  disabled={disabled}
                >
                  <Plus size={14} /> Add Paragraph
                </button>

                <div className="simple-grid-2" style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid var(--border-color)' }}>
                  <div className="form-group">
                    <label className="simple-label">Closing Sign-off</label>
                    <input
                      type="text"
                      className="input-base"
                      value={data.closing || ''}
                      onChange={(e) => onChange({ ...data, closing: e.target.value })}
                      disabled={disabled}
                      placeholder="Sincerely,"
                    />
                  </div>
                  <div className="form-group">
                    <label className="simple-label">Signer Name</label>
                    <input
                      type="text"
                      className="input-base"
                      value={data.signer || data.basics?.name || ''}
                      onChange={(e) => onChange({ ...data, signer: e.target.value })}
                      disabled={disabled}
                      placeholder="Alex Muster, BSc"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* 3. CV Sections (Summary, Skills, Experience, Education, Projects) */}
      {!isCoverLetter &&
        (data.sections || []).map((section, secIdx) => {
          const secKey = `sec-${secIdx}-${section.title}`;
          const isOpen = Boolean(openSections[secKey]);
          const isEdu = (section.title || '').toLowerCase().includes('edu');
          const isExp = (section.title || '').toLowerCase().includes('exp') || (section.title || '').toLowerCase().includes('work');
          const isSkills = section.type === 'skills';
          const isLines = section.type === 'lines';

          return (
            <div key={secIdx} className="simple-section-card">
              <div className="simple-section-header" onClick={() => toggleSection(secKey)}>
                <div className="simple-section-title">
                  {getSectionIcon(section.title)}
                  <span>{section.title}</span>
                  {isSkills && (section.groups || []).length > 0 && (
                    <span className="simple-badge-count">{section.groups.length} categories</span>
                  )}
                  {isExp && (section.entries || []).length > 0 && (
                    <span className="simple-badge-count">
                      {section.entries.length} {section.entries.length === 1 ? 'position' : 'positions'}
                    </span>
                  )}
                  {isEdu && (section.entries || []).length > 0 && (
                    <span className="simple-badge-count">
                      {section.entries.length} {section.entries.length === 1 ? 'degree' : 'degrees'}
                    </span>
                  )}
                  {isLines && (section.items || []).length > 0 && (
                    <span className="simple-badge-count">{section.items.length} items</span>
                  )}
                </div>
                {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </div>

              {isOpen && (
                <div className="simple-section-body">
                  {/* Summary Type */}
                  {section.type === 'summary' && (
                    <div className="form-group">
                      <label className="simple-label">Professional Summary / Bio</label>
                      <AutoResizeTextarea
                        className="input-base auto-resize-textarea"
                        minRows={4}
                        value={section.text || ''}
                        onChange={(e) => handleSummaryChange(secIdx, e.target.value)}
                        disabled={disabled}
                        placeholder="Highlight your key expertise, years of experience, and career trajectory..."
                      />
                    </div>
                  )}

                  {/* Skills Type */}
                  {section.type === 'skills' && (
                    <div className="simple-skills-list">
                      {(section.groups || []).map((grp, grpIdx) => (
                        <div key={grpIdx} className="simple-skill-row">
                          <div className="form-group simple-skill-cat">
                            <label className="simple-label">Category</label>
                            <input
                              type="text"
                              className="input-base"
                              value={grp.category}
                              onChange={(e) => handleSkillGroupChange(secIdx, grpIdx, 'category', e.target.value)}
                              disabled={disabled}
                              placeholder="e.g. Languages"
                            />
                          </div>
                          <div className="form-group simple-skill-val">
                            <label className="simple-label">Skills (comma-separated)</label>
                            <AutoResizeTextarea
                              className="input-base auto-resize-textarea"
                              minRows={2}
                              value={grp.skills}
                              onChange={(e) => handleSkillGroupChange(secIdx, grpIdx, 'skills', e.target.value)}
                              disabled={disabled}
                              placeholder="e.g. Python, Bash, SQL, Docker"
                            />
                          </div>
                          <button
                            type="button"
                            className="btn-icon btn-icon-danger simple-delete-row-btn"
                            onClick={() => handleDeleteSkillGroup(secIdx, grpIdx)}
                            title="Delete category"
                            disabled={disabled}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      ))}

                      <button
                        type="button"
                        className="btn btn-secondary btn-sm simple-btn-add"
                        onClick={() => handleAddSkillGroup(secIdx)}
                        disabled={disabled}
                      >
                        <Plus size={14} /> Add Skill Category
                      </button>
                    </div>
                  )}

                  {/* Entries Type (Experience / Education) */}
                  {section.type === 'entries' && (
                    <div className="simple-entries-list">
                      {(section.entries || []).map((entry, entIdx) => (
                        <div key={entIdx} className="simple-entry-item">
                          <div className="simple-entry-header">
                            <div className="simple-entry-title-preview">
                              <span className="simple-entry-main-title">
                                {entry.title || (isEdu ? 'New Degree' : 'New Position')}
                              </span>
                              {entry.employer && (
                                <span className="simple-entry-sub-title"> • {entry.employer}</span>
                              )}
                              {entry.date && (
                                <span className="simple-entry-date-tag">{entry.date}</span>
                              )}
                            </div>
                            <button
                              type="button"
                              className="btn-icon btn-icon-danger simple-delete-entry-btn"
                              onClick={() => handleDeleteEntry(secIdx, entIdx)}
                              title={isEdu ? 'Delete degree' : 'Delete position'}
                              disabled={disabled}
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>

                          <div className="simple-grid-2">
                            <div className="form-group">
                              <label className="simple-label">{isEdu ? 'Degree / Field of Study' : 'Job Title'}</label>
                              <input
                                type="text"
                                className="input-base"
                                value={entry.title || ''}
                                onChange={(e) => handleEntryChange(secIdx, entIdx, 'title', e.target.value)}
                                disabled={disabled}
                                placeholder={isEdu ? 'PhD in Physics' : 'Senior Developer'}
                              />
                            </div>
                            <div className="form-group">
                              <label className="simple-label">{isEdu ? 'University / Institution' : 'Company / Employer'}</label>
                              <input
                                type="text"
                                className="input-base"
                                value={entry.employer || ''}
                                onChange={(e) => handleEntryChange(secIdx, entIdx, 'employer', e.target.value)}
                                disabled={disabled}
                                placeholder={isEdu ? 'University of Vienna' : 'Example Tech GmbH'}
                              />
                            </div>
                          </div>

                          <div className="simple-grid-2">
                            <div className="form-group">
                              <label className="simple-label">Dates / Period</label>
                              <input
                                type="text"
                                className="input-base"
                                value={entry.date || ''}
                                onChange={(e) => handleEntryChange(secIdx, entIdx, 'date', e.target.value)}
                                disabled={disabled}
                                placeholder={isEdu ? '2021 – 2026 (exp.)' : '2022 – Present'}
                              />
                            </div>
                            <div className="form-group">
                              <label className="simple-label">{isEdu ? 'Location / Honours (optional)' : 'Location (optional)'}</label>
                              <input
                                type="text"
                                className="input-base"
                                value={entry.location || ''}
                                onChange={(e) => handleEntryChange(secIdx, entIdx, 'location', e.target.value)}
                                disabled={disabled}
                                placeholder="Vienna, Austria"
                              />
                            </div>
                          </div>

                          {/* Bullets List (show for experience or if education has bullets) */}
                          {(!isEdu || (entry.bullets && entry.bullets.length > 0)) && (
                            <div className="simple-bullets-container">
                              <label className="simple-label">
                                Highlights & Accomplishments ({entry.bullets?.length || 0})
                              </label>

                              {(entry.bullets || []).map((bullet, bIdx) => (
                                <div key={bIdx} className="simple-bullet-row">
                                  <span className="simple-bullet-dot">•</span>
                                  <AutoResizeTextarea
                                    className="input-base simple-bullet-input auto-resize-textarea"
                                    minRows={2}
                                    value={bullet}
                                    onChange={(e) => handleBulletChange(secIdx, entIdx, bIdx, e.target.value)}
                                    disabled={disabled}
                                    placeholder="Describe an accomplishment with measurable results..."
                                  />
                                  <button
                                    type="button"
                                    className="btn-icon btn-icon-danger simple-bullet-del-btn"
                                    onClick={() => handleDeleteBullet(secIdx, entIdx, bIdx)}
                                    title="Delete bullet"
                                    disabled={disabled}
                                  >
                                    <Trash2 size={14} />
                                  </button>
                                </div>
                              ))}

                              <button
                                type="button"
                                className="btn btn-secondary btn-sm simple-btn-add-bullet"
                                onClick={() => handleAddBullet(secIdx, entIdx)}
                                disabled={disabled}
                              >
                                <Plus size={13} /> Add Bullet
                              </button>
                            </div>
                          )}

                          {/* Extra Note / Thesis / GPA */}
                          <div className="form-group" style={{ marginTop: '0.4rem' }}>
                            <label className="simple-label">{isEdu ? 'Focus / GPA / Thesis' : 'Additional Note / Context (optional)'}</label>
                            <input
                              type="text"
                              className="input-base"
                              value={entry.note || ''}
                              onChange={(e) => handleEntryChange(secIdx, entIdx, 'note', e.target.value)}
                              disabled={disabled}
                              placeholder={isEdu ? 'e.g. Focus: Computational Materials Science | GPA: 3.90/4.00' : 'e.g. Promoted from Mid-level Developer'}
                            />
                          </div>
                        </div>
                      ))}

                      <button
                        type="button"
                        className="btn btn-secondary btn-sm simple-btn-add"
                        onClick={() => handleAddEntry(secIdx)}
                        disabled={disabled}
                      >
                        <Plus size={14} /> {isEdu ? 'Add Degree' : 'Add Position'}
                      </button>
                    </div>
                  )}

                  {/* Lines Type (Projects & Interests) */}
                  {section.type === 'lines' && (
                    <div className="simple-skills-list">
                      {(section.items || []).map((item, itIdx) => (
                        <div key={itIdx} className="simple-skill-row">
                          <div className="form-group simple-skill-cat">
                            <label className="simple-label">Category</label>
                            <input
                              type="text"
                              className="input-base"
                              value={item.category}
                              onChange={(e) => handleLineItemChange(secIdx, itIdx, 'category', e.target.value)}
                              disabled={disabled}
                              placeholder="e.g. App Platform"
                            />
                          </div>
                          <div className="form-group simple-skill-val">
                            <label className="simple-label">Description</label>
                            <AutoResizeTextarea
                              className="input-base auto-resize-textarea"
                              minRows={2}
                              value={item.content}
                              onChange={(e) => handleLineItemChange(secIdx, itIdx, 'content', e.target.value)}
                              disabled={disabled}
                              placeholder="Project description..."
                            />
                          </div>
                          <button
                            type="button"
                            className="btn-icon btn-icon-danger simple-delete-row-btn"
                            onClick={() => handleDeleteLineItem(secIdx, itIdx)}
                            title="Delete item"
                            disabled={disabled}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      ))}

                      <button
                        type="button"
                        className="btn btn-secondary btn-sm simple-btn-add"
                        onClick={() => handleAddLineItem(secIdx)}
                        disabled={disabled}
                      >
                        <Plus size={14} /> Add Project / Line
                      </button>
                    </div>
                  )}

                  {/* Plain Text Fallback */}
                  {section.type === 'text' && (
                    <div className="form-group">
                      <AutoResizeTextarea
                        className="input-base auto-resize-textarea"
                        minRows={3}
                        value={section.text || ''}
                        onChange={(e) => handleSummaryChange(secIdx, e.target.value)}
                        disabled={disabled}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
    </div>
  );
}
