import React, { useState, useEffect } from 'react';
import { useApi } from '../../api/context';
import { Settings, Search, RefreshCw, CheckCircle2, AlertCircle, Palette, Check, Type, Database } from 'lucide-react';

export function SettingsTab({
  aiModel, setAiModel,
  aiTone, setAiTone,
  scraperConfig, setScraperConfig,
  saveConfig, savingConfig,
  handleDeleteUnreviewed, handleNuke,
  preferences,
  demo = false,
}) {
  const api = useApi();
  const [openrouterModels, setOpenrouterModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [docModel, setDocModel] = useState('');
  const [verifierModel, setVerifierModel] = useState('auto');
  const [defaultVerifier, setDefaultVerifier] = useState('hosted default');

  useEffect(() => {
    // Keep the field in sync with the saved config until the user edits it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDocModel(scraperConfig?.document_model || '');
  }, [scraperConfig?.document_model]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVerifierModel(scraperConfig?.letter_verifier_model == null ? 'auto' :
      scraperConfig.letter_verifier_model === '' ? 'disabled' : scraperConfig.letter_verifier_model);
  }, [scraperConfig?.letter_verifier_model]);

  useEffect(() => {
    if (openrouterModels.length === 0) {
      // This effect initializes state from the remote model list.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoadingModels(true);
      api.get('/openrouter/models')
        .then(res => {
          if (res.data.default_verifier_model) setDefaultVerifier(res.data.default_verifier_model);
          if (res.data.success) {
            setOpenrouterModels(res.data.models);
          }
        })
        .catch(err => console.error("Failed to load openrouter models:", err))
        .finally(() => setLoadingModels(false));
    }
  }, [api, openrouterModels.length]);

  return (
    <div style={{ maxWidth: '800px', margin: '0 auto' }}>
      {/* Workspace & Appearance */}
      {preferences && (
        <>
          <div className="settings-section-header">
            <h2 className="settings-section-title">
              <Palette size={20} /> Workspace & Appearance
            </h2>
            <p className="settings-section-desc">
              Personalize your workspace palette and UI typography across sessions.
            </p>
          </div>

          {/* Appearance & Themes */}
          <div className="card settings-card">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
              <h3 className="card-title" style={{ margin: 0 }}>
                <Palette size={18} /> Color Themes
              </h3>
              {preferences.savingTheme && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  <RefreshCw size={12} className="spinner" />
                  <span>Saving...</span>
                </div>
              )}
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
              Choose a workspace palette. Choices are saved per account, or in your browser during the demo.
            </div>

            <div className="theme-grid">
              {preferences.themes.map((t) => {
                const isActive = t.id === preferences.theme;
                return (
                  <button
                    key={t.id}
                    type="button"
                    className={`theme-gallery-card ${isActive ? 'active' : ''}`}
                    onClick={() => preferences.setTheme(t.id)}
                  >
                    {isActive && (
                      <div className="theme-active-indicator" title="Active Theme">
                        <Check size={12} />
                      </div>
                    )}
                    <div className="theme-gallery-header">
                      <span className="theme-gallery-title">{t.name}</span>
                      <span className="theme-type-pill">{t.type}</span>
                    </div>
                    <div className="theme-gallery-desc">{t.desc}</div>
                    <div className="theme-swatches-row">
                      {t.colors.map((c, i) => (
                        <span
                          key={i}
                          className="theme-swatch-large"
                          style={{ backgroundColor: c }}
                          title={`Color: ${c}`}
                        />
                      ))}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Typography & Fonts */}
          {preferences.fonts && (
            <div className="card settings-card">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <h3 className="card-title" style={{ margin: 0 }}>
                  <Type size={18} /> Typography & Fonts
                </h3>
                {preferences.savingFont && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    <RefreshCw size={12} className="spinner" />
                    <span>Saving...</span>
                  </div>
                )}
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem' }}>
                Choose a typeface for reading and interface text. Choices are saved per account, or in your browser during the demo.
              </div>

              <div className="font-grid">
                {preferences.fonts.map((f) => {
                  const isActive = f.id === preferences.font;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      className={`font-card ${isActive ? 'active' : ''}`}
                      onClick={() => preferences.setFont(f.id)}
                    >
                      {isActive && (
                        <div className="theme-active-indicator" title="Active Font">
                          <Check size={12} />
                        </div>
                      )}
                      <div className="font-card-header">
                        <span className={`font-card-name font-preview-${f.id}`}>{f.name}</span>
                      </div>
                      <div className="font-card-creator">by {f.creator}</div>
                      <div className="font-card-desc">{f.desc}</div>
                      <div className={`font-sample-preview font-preview-${f.id}`}>
                        {f.sample}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}

      <fieldset className="demo-fieldset" disabled={demo}>
      {/* AI Generation Preferences */}
      <div className="settings-section-header">
        <h2 className="settings-section-title">
          <Settings size={20} /> AI Generation Preferences
        </h2>
        <p className="settings-section-desc">
          Choose models for requirement checks, document drafting, and quote verification.
        </p>
      </div>

      <div className="card settings-card">
        <h3 className="card-title" style={{ margin: 0, marginBottom: '0.75rem' }}>
          <Settings size={18} /> Model & Generation Settings
        </h3>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          Two separate models. The <strong>automation model</strong> checks the requirements of every scraped posting
          (roughly 50 calls a day), so keep it cheap. The <strong>documents model</strong> writes your
          CVs and cover letters (about 2 calls per application) — spend there if you want better prose.
        </div>
        <div className="form-group">
          <label className="form-label">Automation Model — job scoring &amp; analysis</label>
          {loadingModels ? (
            <div style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>Loading models...</div>
          ) : (() => {
            const selectedCompany = aiModel ? aiModel.split('/')[0] : 'openai';
            const companies = [...new Set(openrouterModels.map(m => m.id.split('/')[0]))].sort();
            const modelsForCompany = openrouterModels.filter(m => m.id.startsWith(`${selectedCompany}/`));
            
            return (
              <div className="model-select-row">
                <select 
                  aria-label="AI Model Provider"
                  className="input-base model-select-company" 
                  value={selectedCompany} 
                  onChange={e => {
                    const newCompany = e.target.value;
                    const newModels = openrouterModels.filter(m => m.id.startsWith(`${newCompany}/`));
                    if (newModels.length > 0) {
                      setAiModel(newModels[0].id);
                    }
                  }}
                >
                  {!companies.includes(selectedCompany) && <option value={selectedCompany}>{selectedCompany}</option>}
                  {companies.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <select 
                  aria-label="AI Model"
                  className="input-base model-select-model" 
                  value={aiModel} 
                  onChange={e => setAiModel(e.target.value)}
                >
                  {!modelsForCompany.find(m => m.id === aiModel) && <option value={aiModel}>{aiModel}</option>}
                  {modelsForCompany.map(m => (
                    <option key={m.id} value={m.id}>{m.id.split('/').slice(1).join('/')} ({m.name})</option>
                  ))}
                </select>
              </div>
            );
          })()}
        </div>
        <div className="form-group">
          <label className="form-label">Documents Model — CVs &amp; cover letters</label>
          {loadingModels ? (
            <div style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>Loading models...</div>
          ) : (() => {
            const docCompany = docModel ? docModel.split('/')[0] : '';
            const docModels = docCompany ? openrouterModels.filter(m => m.id.startsWith(`${docCompany}/`)) : [];
            const docCompanies = [...new Set(openrouterModels.map(m => m.id.split('/')[0]))].sort();

            return (
              <div className="model-select-row">
                <select
                  aria-label="Documents Model Provider"
                  className="input-base model-select-company"
                  value={docCompany}
                  onChange={e => {
                    const newCompany = e.target.value;
                    if (!newCompany) { setDocModel(''); return; }
                    const newModels = openrouterModels.filter(m => m.id.startsWith(`${newCompany}/`));
                    if (newModels.length > 0) setDocModel(newModels[0].id);
                  }}
                >
                  <option value="">Default (z-ai/glm-5.3-flash)</option>
                  {docCompanies.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <select
                  aria-label="Documents Model"
                  className="input-base model-select-model"
                  value={docModel}
                  onChange={e => setDocModel(e.target.value)}
                  disabled={!docModel}
                >
                  {!docModel && <option value="">Same cheap default as scoring</option>}
                  {docModels.map(m => (
                    <option key={m.id} value={m.id}>{m.id.split('/').slice(1).join('/')} ({m.name})</option>
                  ))}
                </select>
              </div>
            );
          })()}
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
            Only affects document generation. Daily scoring keeps using the automation model above.
          </div>
        </div>
        <div className="form-group">
          <label htmlFor="letter-verifier-model" className="form-label">Letter verification model</label>
          <select id="letter-verifier-model" className="input-base" value={verifierModel}
            onChange={event => setVerifierModel(event.target.value)}>
            <option value="auto">Automatic — {docModel.startsWith('custom/') ? docModel : defaultVerifier}</option>
            <option value="disabled">Disabled — letters will not receive a model evidence check</option>
            {!['auto', 'disabled'].includes(verifierModel) && !openrouterModels.some(model => model.id === verifierModel) &&
              <option value={verifierModel}>{verifierModel}</option>}
            {openrouterModels.map(model => <option key={model.id} value={model.id}>{model.id}</option>)}
          </select>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            Automatic verification follows a custom writing model through the same endpoint.
            Hosted writing models use {defaultVerifier}. An explicit selection overrides this choice.
          </p>
          {verifierModel === 'disabled' && <p role="status">Model evidence checking is disabled. Review every claim yourself.</p>}
        </div>
        <div className="form-group">
          <label htmlFor="ai-tone" className="form-label">Generation Tone / Persona</label>
          <textarea id="ai-tone" aria-label="Generation Tone / Persona" className="input-base" style={{ resize: 'vertical', minHeight: '80px', padding: '0.5rem', fontFamily: 'inherit', fontSize: '14px', lineHeight: '1.4' }}
            value={aiTone} onChange={e => setAiTone(e.target.value)} placeholder="e.g. Highly professional, emphasize leadership..." />
        </div>
        <div className="form-group">
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.85rem' }}>
            <input
              type="checkbox"
              checked={scraperConfig?.route_cheapest ?? false}
              onChange={e => setScraperConfig(c => ({ ...c, route_cheapest: e.target.checked }))}
            />
            <span>Always route to the cheapest provider (<code>:floor</code> — admits discounted flex tiers, e.g. OpenAI Flex at half price; falls back to standard when unavailable)</span>
          </label>
        </div>
        <button className="btn btn-primary settings-btn-save" style={{ marginTop: '0.5rem' }} disabled={savingConfig}
          onClick={() => saveConfig({ openrouter_model: aiModel, document_model: docModel,
            letter_verifier_model: verifierModel === 'auto' ? null : verifierModel === 'disabled' ? '' : verifierModel,
            route_cheapest: scraperConfig?.route_cheapest ?? false, auto_generate: { ...scraperConfig?.auto_generate, tone: aiTone } })}>
          {savingConfig ? <RefreshCw className="spinner" size={16} /> : <CheckCircle2 size={16} />}
          <span>Save AI Preferences</span>
        </button>
      </div>

      {/* Scraper Automation & Ingestion */}
      <div className="settings-section-header">
        <h2 className="settings-section-title">
          <Search size={20} /> Scraper Automation & Ingestion
        </h2>
        <p className="settings-section-desc">
          Configure search channels, keyword queries, daily automated scraping, and content denoising.
        </p>
      </div>

      {/* Manual Scraper Defaults */}
      <div className="card settings-card">
        <h3 className="card-title" style={{ margin: 0, marginBottom: '0.75rem' }}>
          <Search size={18} /> Manual Scraper Defaults
        </h3>
        {!scraperConfig ? (
          <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={24} style={{ margin: '0 auto', display: 'block' }} />
          </div>
        ) : (
          <>
            <div>
              <div className="settings-subsection-header">
                <h4 className="settings-subsection-title">LinkedIn</h4>
                <span className="settings-source-pill">Scraper</span>
              </div>
              <div className="form-group">
                <label htmlFor="scraper-linkedin-keywords" className="form-label">Keywords</label>
                <input id="scraper-linkedin-keywords" aria-label="LinkedIn Keywords" type="text" className="input-base"
                  value={scraperConfig.linkedin?.keywords || ''}
                  onChange={e => setScraperConfig(c => ({ ...c, linkedin: { ...c.linkedin, keywords: e.target.value } }))} />
              </div>
              <div className="form-row-responsive">
                <div className="form-group" style={{ flex: 1 }}>
                  <label htmlFor="scraper-linkedin-limit" className="form-label">Results Limit</label>
                  <input id="scraper-linkedin-limit" aria-label="LinkedIn Results Limit" type="number" className="input-base"
                    value={scraperConfig.linkedin?.results_limit ?? 100}
                    onChange={e => setScraperConfig(c => ({ ...c, linkedin: { ...c.linkedin, results_limit: parseInt(e.target.value) || 100 } }))} />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label htmlFor="scraper-linkedin-hours" className="form-label">Hours Old</label>
                  <input id="scraper-linkedin-hours" aria-label="LinkedIn Hours Old" type="number" className="input-base"
                    value={scraperConfig.linkedin?.hours_old ?? 24}
                    onChange={e => setScraperConfig(c => ({ ...c, linkedin: { ...c.linkedin, hours_old: parseInt(e.target.value) || 24 } }))} />
                </div>
              </div>
            </div>

            <div className="settings-card-divider" />

            <div>
              <div className="settings-subsection-header">
                <h4 className="settings-subsection-title">Karriere.at</h4>
                <span className="settings-source-pill">Scraper</span>
              </div>
              <div className="form-group">
                <label htmlFor="scraper-karriere-keywords" className="form-label">Keywords (comma-separated)</label>
                <input id="scraper-karriere-keywords" aria-label="Karriere.at Keywords" type="text" className="input-base"
                  value={Array.isArray(scraperConfig.karriere?.keywords) ? scraperConfig.karriere.keywords.join(', ') : (scraperConfig.karriere?.keywords || '')}
                  onChange={e => setScraperConfig(c => ({ ...c, karriere: { ...c.karriere, keywords: e.target.value.split(',').map(k => k.trim()).filter(Boolean) } }))} />
              </div>
              <div className="form-group">
                <label htmlFor="scraper-karriere-limit" className="form-label">Results Limit</label>
                <input id="scraper-karriere-limit" aria-label="Karriere.at Results Limit" type="number" className="input-base"
                  value={scraperConfig.karriere?.results_limit ?? 10}
                  onChange={e => setScraperConfig(c => ({ ...c, karriere: { ...c.karriere, results_limit: parseInt(e.target.value) || 10 } }))} />
              </div>
            </div>

            <div className="settings-card-divider" />

            <div>
              <div className="settings-subsection-header">
                <h4 className="settings-subsection-title">Search Geography</h4>
              </div>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
                LinkedIn uses a free-text location (passed to jobspy). Karriere.at uses the region slug in the listing URL (e.g. <code style={{ fontSize: '0.75rem' }}>wien-und-umgebung</code>).
              </p>
              <div className="form-group">
                <label htmlFor="scraper-linkedin-location" className="form-label">LinkedIn location</label>
                <input id="scraper-linkedin-location" aria-label="LinkedIn location" type="text" className="input-base" placeholder="Vienna, AT"
                  value={scraperConfig.linkedin_location ?? ''}
                  onChange={e => setScraperConfig(c => ({ ...c, linkedin_location: e.target.value }))} />
              </div>
              <div className="form-group">
                <label htmlFor="scraper-karriere-region" className="form-label">Karriere.at region slug</label>
                <input id="scraper-karriere-region" aria-label="Karriere.at region slug" type="text" className="input-base" placeholder="wien-und-umgebung"
                  value={scraperConfig.karriere_region ?? ''}
                  onChange={e => setScraperConfig(c => ({ ...c, karriere_region: e.target.value }))} />
              </div>
            </div>

            <div className="settings-card-divider" />

            <div>
              <div className="settings-subsection-header">
                <h4 className="settings-subsection-title">Auto-Generate & Engine Defaults</h4>
              </div>
              <div className="form-row-responsive" style={{ alignItems: 'flex-end' }}>
                <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                  <label htmlFor="auto-min-rating" className="form-label">Minimum match rating</label>
                  <select id="auto-min-rating" className="input-base" value={scraperConfig.auto_generate?.min_rating || 'good'}
                    onChange={e => setScraperConfig(c => ({ ...c, auto_generate: { ...c.auto_generate, min_rating: e.target.value } }))}>
                    {['great', 'good', 'decent', 'stretch', 'poor'].map(rating => <option key={rating} value={rating}>{rating[0].toUpperCase() + rating.slice(1)} or better</option>)}
                  </select>
                </div>
                <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                  <label htmlFor="auto-max-german-level" className="form-label">Maximum German Level</label>
                  <select id="auto-max-german-level" aria-label="Maximum German Level" className="input-base"
                    value={scraperConfig.auto_generate?.max_german_level ?? 'B1'}
                    onChange={e => setScraperConfig(c => ({ ...c, auto_generate: { ...c.auto_generate, max_german_level: e.target.value } }))}>
                    <option value="B1">B1</option>
                    <option value="B2">B2</option>
                    <option value="C1">C1</option>
                    <option value="C2">C2</option>
                    <option value="native">Native</option>
                  </select>
                </div>
              </div>
              <div className="form-row-responsive" style={{ alignItems: 'flex-end', marginTop: '0.75rem' }}>
                <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                  <label htmlFor="auto-doc-engine" className="form-label">Default Document Engine</label>
                  <select id="auto-doc-engine" aria-label="Default Document Engine" className="input-base"
                    value={scraperConfig.auto_generate?.document_engine ?? 'typst'}
                    onChange={e => setScraperConfig(c => ({ ...c, auto_generate: { ...c.auto_generate, document_engine: e.target.value } }))}>
                    <option value="typst">Typst</option>
                    <option value="latex">LaTeX</option>
                  </select>
                </div>
                {!scraperConfig.auto_generate?.reviewed_baseline && (scraperConfig.auto_generate?.document_engine ?? 'typst') === 'typst' && (
                  <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                    <label htmlFor="auto-typst-template" className="form-label">Default Typst CV Template</label>
                    <select id="auto-typst-template" aria-label="Default Typst CV Template" className="input-base"
                      value={scraperConfig.auto_generate?.typst_cv_template ?? 'base-cv-moderner.typ'}
                      onChange={e => setScraperConfig(c => ({ ...c, auto_generate: { ...c.auto_generate, typst_cv_template: e.target.value } }))}>
                      <option value="base-cv-moderner.typ">ModernCV (moderner-cv)</option>
                      <option value="base-cv.typ">Standard CV</option>
                    </select>
                  </div>
                )}
              </div>
              <div style={{ marginTop: '0.75rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.85rem' }}>
                  <input
                    type="checkbox"
                    checked={scraperConfig.auto_generate?.compact_cv ?? false}
                    onChange={e => setScraperConfig(c => ({ ...c, auto_generate: { ...c.auto_generate, compact_cv: e.target.checked } }))}
                  />
                  <span>Select fewer CV evidence bullets</span>
                </label>
              </div>
            </div>

            <button className="btn btn-primary settings-btn-save" style={{ marginTop: '1.25rem' }} disabled={savingConfig} onClick={() => saveConfig(scraperConfig)}>
              {savingConfig ? <RefreshCw className="spinner" size={16} /> : <CheckCircle2 size={16} />}
              <span>Save Manual Scraper Configuration</span>
            </button>
          </>
        )}
      </div>

      {/* Daily Scraper Configuration */}
      <div className="card settings-card">
        <h3 className="card-title" style={{ margin: 0, marginBottom: '0.75rem' }}>
          <Search size={18} /> Daily Scraper Configuration
        </h3>
        {!scraperConfig ? (
          <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={24} style={{ margin: '0 auto', display: 'block' }} />
          </div>
        ) : (
          <>
            <div>
              <div className="settings-subsection-header">
                <h4 className="settings-subsection-title">LinkedIn</h4>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                  <input type="checkbox" 
                    checked={scraperConfig.daily_scraper?.enable_linkedin ?? false}
                    onChange={e => setScraperConfig(c => ({ ...c, daily_scraper: { ...c.daily_scraper, enable_linkedin: e.target.checked } }))} />
                  Enable
                </label>
              </div>
              <div className="form-group">
                <label htmlFor="daily-linkedin-keywords" className="form-label">Keywords</label>
                <input id="daily-linkedin-keywords" aria-label="Daily LinkedIn Keywords" type="text" className="input-base"
                  value={scraperConfig.daily_scraper?.linkedin?.keywords || ''}
                  onChange={e => setScraperConfig(c => ({ ...c, daily_scraper: { ...c.daily_scraper, linkedin: { ...c.daily_scraper?.linkedin, keywords: e.target.value } } }))} />
              </div>
              <div style={{ display: 'flex', gap: '1rem' }}>
                <div className="form-group" style={{ flex: 1 }}>
                  <label htmlFor="daily-linkedin-limit" className="form-label">Results Limit</label>
                  <input id="daily-linkedin-limit" aria-label="Daily LinkedIn Results Limit" type="number" className="input-base"
                    value={scraperConfig.daily_scraper?.linkedin?.results_limit ?? 80}
                    onChange={e => setScraperConfig(c => ({ ...c, daily_scraper: { ...c.daily_scraper, linkedin: { ...c.daily_scraper?.linkedin, results_limit: parseInt(e.target.value) || 80 } } }))} />
                </div>
                <div className="form-group" style={{ flex: 1 }}>
                  <label htmlFor="daily-linkedin-hours" className="form-label">Hours Old</label>
                  <input id="daily-linkedin-hours" aria-label="Daily LinkedIn Hours Old" type="number" className="input-base"
                    value={scraperConfig.daily_scraper?.linkedin?.hours_old ?? 24}
                    onChange={e => setScraperConfig(c => ({ ...c, daily_scraper: { ...c.daily_scraper, linkedin: { ...c.daily_scraper?.linkedin, hours_old: parseInt(e.target.value) || 24 } } }))} />
                </div>
              </div>
            </div>

            <div className="settings-card-divider" />

            <div>
              <div className="settings-subsection-header">
                <h4 className="settings-subsection-title">Karriere.at</h4>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                  <input type="checkbox" 
                    checked={scraperConfig.daily_scraper?.enable_karriere ?? false}
                    onChange={e => setScraperConfig(c => ({ ...c, daily_scraper: { ...c.daily_scraper, enable_karriere: e.target.checked } }))} />
                  Enable
                </label>
              </div>
              <div className="form-group">
                <label htmlFor="daily-karriere-keywords" className="form-label">Keywords (comma-separated)</label>
                <input id="daily-karriere-keywords" aria-label="Daily Karriere.at Keywords" type="text" className="input-base"
                  value={Array.isArray(scraperConfig.daily_scraper?.karriere?.keywords) ? scraperConfig.daily_scraper.karriere.keywords.join(', ') : (scraperConfig.daily_scraper?.karriere?.keywords || '')}
                  onChange={e => setScraperConfig(c => ({ ...c, daily_scraper: { ...c.daily_scraper, karriere: { ...c.daily_scraper?.karriere, keywords: e.target.value.split(',').map(k => k.trim()).filter(Boolean) } } }))} />
              </div>
              <div className="form-group">
                <label htmlFor="daily-karriere-limit" className="form-label">Results Limit</label>
                <input id="daily-karriere-limit" aria-label="Daily Karriere.at Results Limit" type="number" className="input-base"
                  value={scraperConfig.daily_scraper?.karriere?.results_limit ?? 10}
                  onChange={e => setScraperConfig(c => ({ ...c, daily_scraper: { ...c.daily_scraper, karriere: { ...c.daily_scraper?.karriere, results_limit: parseInt(e.target.value) || 10 } } }))} />
              </div>
            </div>


            <button className="btn btn-primary settings-btn-save" style={{ marginTop: '1.25rem' }} disabled={savingConfig} onClick={() => saveConfig(scraperConfig)}>
              {savingConfig ? <RefreshCw className="spinner" size={16} /> : <CheckCircle2 size={16} />}
              <span>Save Daily Configuration</span>
            </button>
          </>
        )}
      </div>

      {/* Description Denoising */}
      <div className="card settings-card">
        <h3 className="card-title" style={{ margin: 0, marginBottom: '0.75rem' }}>
          <RefreshCw size={18} /> Description Denoising
        </h3>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          Choose which job sources get their description cleaned (page noise, cookie notices, broken line breaks) before AI analysis.
          Manual additions are denoised by default — scraped sources like LinkedIn (Apify) usually return clean text and can be left off.
        </div>
        {!scraperConfig ? (
          <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <RefreshCw className="spinner" size={24} style={{ margin: '0 auto', display: 'block' }} />
          </div>
        ) : (
          <>
            {[
              { key: 'manual', label: 'Manual additions' },
              { key: 'linkedin', label: 'LinkedIn (Apify)' },
              { key: 'karriere', label: 'Karriere.at (Apify)' },
            ].map(({ key, label }) => {
              const selected = scraperConfig.denoise_sources ?? ['manual'];
              return (
                <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                  <input
                    type="checkbox"
                    checked={selected.includes(key)}
                    onChange={e => setScraperConfig(c => {
                      const current = c.denoise_sources ?? ['manual'];
                      const next = e.target.checked ? [...current, key] : current.filter(s => s !== key);
                      return { ...c, denoise_sources: next };
                    })}
                  />
                  <span>{label}</span>
                </label>
              );
            })}
            <button className="btn btn-primary settings-btn-save" style={{ marginTop: '0.75rem' }} disabled={savingConfig} onClick={() => saveConfig(scraperConfig)}>
              {savingConfig ? <RefreshCw className="spinner" size={16} /> : <CheckCircle2 size={16} />}
              <span>Save Denoising Settings</span>
            </button>
          </>
        )}
      </div>

      {/* Database & Maintenance */}
      <div className="settings-section-header">
        <h2 className="settings-section-title" style={{ color: 'var(--danger-color)' }}>
          <Database size={20} /> Database & Maintenance
        </h2>
        <p className="settings-section-desc">
          Manage local storage, cleanup unreviewed postings, and database operations.
        </p>
      </div>

      {/* Danger Zone */}
      <div className="card settings-card danger-zone-card">
        <h3 className="card-title" style={{ color: 'var(--danger-color)', margin: 0, marginBottom: '1rem' }}>
          <AlertCircle size={18} style={{ marginRight: '8px' }} /> Danger Zone
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="danger-action-row">
            <div className="danger-action-info">
              <div className="danger-action-title">Delete Unreviewed Jobs</div>
              <p className="danger-action-desc">
                Removes all postings with status &ldquo;New&rdquo; or &ldquo;Shortlisted&rdquo;. Preserves your application pipeline.
              </p>
            </div>
            <button className="btn danger-action-btn danger-btn-outline" onClick={handleDeleteUnreviewed}>
              Delete Unreviewed Jobs
            </button>
          </div>

          <div className="settings-card-divider" style={{ margin: '0.25rem 0' }} />

          <div className="danger-action-row">
            <div className="danger-action-info">
              <div className="danger-action-title" style={{ color: '#ef4444' }}>Reset Entire Database</div>
              <p className="danger-action-desc">
                Permanently delete every job posting including all applications and pipeline records. Cannot be undone.
              </p>
            </div>
            <button className="btn danger-action-btn danger-btn-solid" onClick={handleNuke}>
              Reset Database
            </button>
          </div>
        </div>
      </div>
      </fieldset>
    </div>
  );
}
