import React, { useState, useEffect, useCallback } from 'react';
import { api, advanceSession } from './api/client';
import { useApi } from './api/context';
import { UserApiProvider } from './api/UserApiProvider';
import './index.css';
import { DemoContext } from './demoContext';

// Hooks
import { useToasts } from './hooks/useToasts';
import { useSettings } from './hooks/useSettings';
import { useJobs } from './hooks/useJobs';
import { useScraper } from './hooks/useScraper';
import { useBatchGen } from './hooks/useBatchGen';
import { useRefine } from './hooks/useRefine';
import { useDailyTab } from './hooks/useDailyTab';
import { useManualTab } from './hooks/useManualTab';
import { usePersonalize } from './hooks/usePersonalize';
import { useStudio } from './hooks/useStudio';
import { usePreferences } from './hooks/usePreferences';

// UI Components
import { ToastContainer } from './components/ToastContainer';
import { AppNav } from './components/AppNav';
import { JobDetailPage } from './components/JobDetailPage';
import { EditJobModal } from './components/EditJobModal';
import { StatsTab } from './components/StatsTab';
import { Login } from './components/Login';

// Tabs
import { JobsTab } from './components/tabs/JobsTab';
import { ScraperTab } from './components/tabs/ScraperTab';
import { SettingsTab } from './components/tabs/SettingsTab';
import { ManualTab } from './components/tabs/ManualTab';
import { DailyTab } from './components/tabs/DailyTab';
import { PersonalizeTab } from './components/tabs/PersonalizeTab';
import { CVStudioTab } from './components/tabs/CVStudioTab';

export default function App() {
  // undefined = checking session, null = logged out, object = logged in
  const [user, setUser] = useState(undefined);
  const [demo, setDemo] = useState(null);

  // Session bootstrap + expiry handling
  useEffect(() => {
    api.get('/demo').then(res => setDemo(res.data)).catch(() => setDemo({ demo: false }));
    api.get('/auth/me')
      .then((res) => setUser(res.data))
      .catch(() => setUser(null));
    const onUnauthorized = () => { advanceSession(); setUser(null); };
    window.addEventListener('gj:unauthorized', onUnauthorized);
    return () => window.removeEventListener('gj:unauthorized', onUnauthorized);
  }, []);

  const handleLogout = useCallback(async () => {
    advanceSession();
    try {
      await api.post('/auth/logout');
    } catch { /* ignore */ }
    setUser(null);
  }, []);

  const handleLogin = useCallback((userData) => {
    advanceSession();
    setUser(userData);
  }, []);

  if (user === undefined || demo === null) return null;
  if (user === null) return <Login onLogin={handleLogin} demo={demo} />;
  return <UserApiProvider key={user.username}>
    <UserWorkspace user={user} demo={demo} onLogout={handleLogout} />
  </UserApiProvider>;
}

function UserWorkspace({ user, demo, onLogout }) {
  const api = useApi();
  const [activeTab, setActiveTab] = useState('jobs');
  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [skillsStats, setSkillsStats] = useState(null);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsError, setSkillsError] = useState(null);
  const [skillsLoaded, setSkillsLoaded] = useState(false);

  // 1. Base Utilities
  const { toasts, addToast, removeToast } = useToasts();
  const settingsProps = useSettings({ addToast });

  // 2. Data Hooks
  const jobsProps = useJobs({ user, addToast, aiTone: settingsProps.aiTone });
  const scraperProps = useScraper({ user, addToast, fetchJobs: jobsProps.fetchJobs, scraperConfig: settingsProps.scraperConfig });
  const batchGenProps = useBatchGen({ user, addToast, fetchJobs: jobsProps.fetchJobs, filteredJobs: jobsProps.filteredJobs, aiTone: settingsProps.aiTone });
  const refineProps = useRefine({ addToast, fetchJobs: jobsProps.fetchJobs, aiTone: settingsProps.aiTone });
  const dailyProps = useDailyTab({ addToast, aiTone: settingsProps.aiTone });
  const manualProps = useManualTab({ user, addToast, fetchJobs: jobsProps.fetchJobs, fetchUnprocessedJobs: scraperProps.fetchUnprocessedJobs, startReprocess: scraperProps.handleStartReprocess, startRefining: refineProps.startRefining, aiModel: settingsProps.aiModel, aiTone: settingsProps.aiTone });
  const personalizeProps = usePersonalize({ addToast });
  const studioProps = useStudio({ user, activeTab, addToast });
  const preferencesProps = usePreferences({ user, addToast, demo: demo?.demo });

  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const res = await api.get('/stats');
      setStats(res.data);
    } catch {
      addToast('Failed to load statistics.', 'error');
    } finally {
      setStatsLoading(false);
    }
  }, [addToast, api]);

  const fetchSkillsStats = useCallback(async () => {
    setSkillsLoading(true);
    setSkillsError(null);
    try {
      const res = await api.get('/stats/skills?limit=100');
      setSkillsStats(res.data);
      setSkillsLoaded(true);
    } catch {
      setSkillsError('Failed to load skills data. Check the server logs.');
    } finally {
      setSkillsLoading(false);
    }
  }, [api]);

  // Application mount initialization
  const { fetchJobs } = jobsProps;
  const { fetchUnprocessedJobs, fetchLogs } = scraperProps;
  const { fetchDailyDates } = dailyProps;
  const { fetchConfig } = settingsProps;
  const { fetchCv, fetchNotes } = personalizeProps;
  const { fetchDocuments, fetchTemplates } = studioProps;

  useEffect(() => {
    if (!user) return;
    fetchJobs();
    fetchUnprocessedJobs();
    fetchLogs();
    fetchDailyDates();
    fetchConfig();
    fetchCv();
    fetchNotes();
    fetchDocuments();
    fetchTemplates();
  }, [user, fetchJobs, fetchUnprocessedJobs, fetchLogs, fetchDailyDates, fetchConfig, fetchCv, fetchNotes, fetchDocuments, fetchTemplates]);

  // Tab-based lazy loads
  useEffect(() => {
    if (!user) return;
    if (activeTab === 'stats' && !stats) fetchStats();
    if (activeTab === 'stats' && !skillsLoaded && !skillsLoading) fetchSkillsStats();
    if (activeTab === 'studio') {
      fetchDocuments();
      fetchTemplates();
    }
  }, [user, activeTab, stats, fetchStats, skillsLoaded, skillsLoading, fetchSkillsStats, fetchDocuments, fetchTemplates]);

  return (
    <DemoContext.Provider value={demo.demo}>
    <div className={`app-container ${demo.demo ? 'demo-mode' : ''}`}>
      <div className="main-layout" style={{ display: 'flex', flexDirection: 'row' }}>
        <AppNav
          activeTab={activeTab}
          setActiveTab={(tab) => {
            jobsProps.setSelectedJobDetails(null);
            setActiveTab(tab);
          }}
          user={user}
          onLogout={onLogout}
          theme={preferencesProps.theme}
          setTheme={preferencesProps.setTheme}
          themes={preferencesProps.themes}
        />

        <main className="tab-content">
          <h1 className="sr-only">Jobweaver</h1>
          {!demo.demo && personalizeProps.cv?.missing_message && activeTab !== 'personalize' && !jobsProps.selectedJobDetails && (
            <aside className="getting-started-banner" role="status" style={{ margin: '0 0 1rem', padding: '0.75rem 1rem', borderRadius: '10px', border: '1px solid rgba(245,158,11,0.35)', backgroundColor: 'rgba(245,158,11,0.07)', display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap', fontSize: '0.85rem' }}>
              <span style={{ flex: 1, minWidth: '12rem' }}>
                <strong>Getting started:</strong> {personalizeProps.cv.missing_message} Job analysis and document generation need your own CV.
              </span>
              <button type="button" className="btn btn-primary" onClick={() => setActiveTab('personalize')} style={{ fontSize: '0.8rem', padding: '0.35rem 0.8rem' }}>
                Open Personalize
              </button>
            </aside>
          )}
          {demo.demo && <aside className="demo-banner"><strong>Read-only demo</strong><span>Alex Example and all companies are fictional. Ratings and documents are hand-prepared examples. No live model or verifier ran. No API keys needed.</span></aside>}
          {jobsProps.selectedJobDetails ? (
            <JobDetailPage
              job={jobsProps.selectedJobDetails}
              onBack={() => jobsProps.setSelectedJobDetails(null)}
              updateJobStatus={jobsProps.updateJobStatus}
              handleStartReprocess={scraperProps.handleStartReprocess}
              reprocessTaskId={scraperProps.reprocessTaskId}
              startRefining={refineProps.startRefining}
              handleJobsGenerateCV={jobsProps.handleJobsGenerateCV}
              handleJobsGenerateLetter={jobsProps.handleJobsGenerateLetter}
              handleJobsGenerateBoth={jobsProps.handleJobsGenerateBoth}
              generatingJobsDocs={jobsProps.generatingJobsDocs}
              researching={jobsProps.researchingJobId === jobsProps.selectedJobDetails.id}
              onResearch={jobsProps.handleResearchCompany}
              onSaveResearch={jobsProps.handleSaveCompanyResearch}
            />
          ) : (
            <>
              {activeTab === 'jobs' && (
                <JobsTab
                  user={user}
                  onAddPosting={() => setActiveTab('manual')}
                  {...jobsProps}
                  {...scraperProps}
                  {...batchGenProps}
                  {...refineProps}
                />
              )}

              {activeTab === 'scraper' && (
                <ScraperTab {...scraperProps} />
              )}

              {activeTab === 'manual' && (
                <ManualTab {...manualProps} />
              )}

              {activeTab === 'stats' && (
                <StatsTab
                  stats={stats}
                  statsLoading={statsLoading}
                  fetchStats={fetchStats}
                  skillsStats={skillsStats}
                  skillsLoading={skillsLoading}
                  skillsError={skillsError}
                  fetchSkillsStats={fetchSkillsStats}
                />
              )}

              {activeTab === 'personalize' && (
                <fieldset className="demo-fieldset" disabled={demo.demo}><PersonalizeTab
                  {...personalizeProps}
                  scraperConfig={settingsProps.scraperConfig}
                  saveConfig={settingsProps.saveConfig}
                  savingConfig={settingsProps.savingConfig}
                /></fieldset>
              )}

              {activeTab === 'settings' && (
                <SettingsTab
                  {...settingsProps}
                  demo={demo.demo}
                  preferences={preferencesProps}
                  handleDeleteUnreviewed={jobsProps.handleDeleteUnreviewed}
                  handleNuke={jobsProps.handleNuke}
                />
              )}

              {activeTab === 'daily' && (
                <DailyTab
                  {...dailyProps}
                  updateJobStatus={jobsProps.updateJobStatus}
                  setSelectedJobDetails={jobsProps.setSelectedJobDetails}
                />
              )}

              {activeTab === 'studio' && (
                <CVStudioTab {...studioProps} />
              )}
            </>
          )}
        </main>
      </div>

      {jobsProps.editingJob && (
        <EditJobModal
          editingJob={jobsProps.editingJob}
          setEditingJob={jobsProps.setEditingJob}
          editTitle={jobsProps.editTitle} setEditTitle={jobsProps.setEditTitle}
          editCompany={jobsProps.editCompany} setEditCompany={jobsProps.setEditCompany}
          savingEdit={jobsProps.savingEdit} handleSaveEdit={jobsProps.handleSaveEdit}
        />
      )}


      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </div>
    </DemoContext.Provider>
  );
}
