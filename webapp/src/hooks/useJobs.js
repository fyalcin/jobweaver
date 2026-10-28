import { useState, useMemo, useCallback, useEffect } from 'react';
import { useApi } from '../api/context';
import { STATUS_CONFIG, STATUS_ORDER } from '../constants/status';
import { compareJobs, matchesRating, matchesStage, normalizeJobsView, APPLIED_STATUSES, jobStatus } from '../constants/ratings';
import { germanLevelCompatible, germanLevelLabel, normalizeGermanLevel } from '../constants/german';

// Keys were prefixed `gimme-jobs.` before the Jobweaver rename (2026-10-04).
// Reads fall back to the old keys so saved views survive; writes use the new ones.
const STORAGE_PREFIX = 'jobweaver';

function getJobsViewStorageKey(username) {
  return `${STORAGE_PREFIX}.jobs-view.${username || 'default'}`;
}

function getSavedViewsStorageKey(username) {
  return `${STORAGE_PREFIX}.saved-views.${username || 'default'}`;
}

function readStoredValue(kind, username) {
  const user = username || 'default';
  return localStorage.getItem(`${STORAGE_PREFIX}.${kind}.${user}`) ?? localStorage.getItem(`gimme-jobs.${kind}.${user}`);
}

function loadJobsView(username) {
  if (typeof localStorage === 'undefined') return {};
  try {
    const raw = readStoredValue('jobs-view', username);
    const saved = JSON.parse(raw || '{}');
    return normalizeJobsView(saved && typeof saved === 'object' ? saved : {});
  } catch {
    return {};
  }
}

function loadSavedViews(username) {
  if (typeof localStorage === 'undefined') return [];
  try {
    const raw = readStoredValue('saved-views', username);
    const saved = JSON.parse(raw || '[]');
    return Array.isArray(saved) ? saved.map(normalizeJobsView) : [];
  } catch {
    return [];
  }
}

export function useJobs({ user, addToast, aiTone }) {
  const api = useApi();
  const username = user?.username || 'default';
  const defaultGerman = 'All';
  const defaultStatus = 'new';

  const savedView = loadJobsView(username);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(false);

  // Edit Job Modal
  const [editingJob, setEditingJob] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [editCompany, setEditCompany] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);

  // Job Detail Page & Research
  const [selectedJobDetails, setSelectedJobDetails] = useState(null);
  const [researchingJobId, setResearchingJobId] = useState(null);

  // Filters
  const [germanFilter, setGermanFilter] = useState(savedView.germanFilter || defaultGerman);
  const initialStatus = (!savedView.statusFilter || savedView.statusFilter === 'active') ? defaultStatus : savedView.statusFilter;
  const [statusFilter, setStatusFilter] = useState(initialStatus);
  const initialDateFilter = (savedView.scrapeDateFilter && savedView.scrapeDateFilter !== '')
    ? savedView.scrapeDateFilter
    : '__recent21';
  const [scrapeDateFilter, setScrapeDateFilter] = useState(initialDateFilter);
  const [sourceFilter, setSourceFilter] = useState(savedView.sourceFilter || 'All');
  const [minimumRating, setMinimumRating] = useState(savedView.minimumRating || '');
  const [searchQuery, setSearchQuery] = useState(savedView.searchQuery || '');

  // Pagination & Sorting
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(savedView.itemsPerPage || 25);
  const [sortConfig, setSortConfig] = useState(savedView.sortConfig || { key: 'match_rating', direction: 'desc' });
  const [viewMode, setViewMode] = useState(savedView.viewMode || 'cards');

  // Batch actions
  const [batchMarkStatus, setBatchMarkStatus] = useState('not_interested');
  const [batchMarkActive, setBatchMarkActive] = useState(false);

  // Daily Results
  const [dailyDates, setDailyDates] = useState([]);
  const [selectedDailyDate, setSelectedDailyDate] = useState(null);
  const [dailyJobs, setDailyJobs] = useState([]);
  const [dailyLoading, setDailyLoading] = useState(false);
  const [generatingDocs, setGeneratingDocs] = useState(new Set());
  const [generatingJobsDocs, setGeneratingJobsDocs] = useState(new Set());

  const [selectedJobIds, setSelectedJobIds] = useState(() => new Set());
  const [savedViews, setSavedViews] = useState(() => loadSavedViews(username));

  // Switch views when user changes
  useEffect(() => {
    if (!user?.username) return;
    const view = loadJobsView(user.username);
    setGermanFilter(view.germanFilter || defaultGerman);
    setStatusFilter((!view.statusFilter || view.statusFilter === 'active') ? defaultStatus : view.statusFilter);
    setScrapeDateFilter(view.scrapeDateFilter || '__recent21');
    setSourceFilter(view.sourceFilter || 'All');
    setMinimumRating(view.minimumRating || '');
    setSearchQuery(view.searchQuery || '');
    if (view.itemsPerPage) setItemsPerPage(view.itemsPerPage);
    if (view.sortConfig) setSortConfig(view.sortConfig);
    if (view.viewMode) setViewMode(view.viewMode);
    setSavedViews(loadSavedViews(user.username));
  }, [user?.username]);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/jobs');
      setJobs(res.data);
      setSelectedJobDetails(previous => previous ? res.data.find(job => job.id === previous.id) || previous : previous);
      setSelectedJobIds(new Set());
    } catch {
      addToast('Failed to connect to backend API.', 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast, api]);

  const fetchDailyDates = useCallback(async () => {
    try {
      const res = await api.get('/daily-results');
      const dates = res.data.dates || [];
      setDailyDates(dates);
      if (dates.length > 0) {
        const today = new Date().toISOString().slice(0, 10);
        setSelectedDailyDate(current => current || (dates.includes(today) ? today : dates[0]));
      }
    } catch (err) {
      console.error('Failed to fetch daily dates', err);
    }
  }, [api]);

  const fetchDailyResults = useCallback(async (date) => {
    if (!date) return;
    setDailyLoading(true);
    setDailyJobs([]);
    try {
      const res = await api.get(`/daily-results/${date}`);
      setDailyJobs(res.data.jobs || []);
    } catch {
      addToast('Failed to load daily results.', 'error');
    } finally {
      setDailyLoading(false);
    }
  }, [addToast, api]);

  useEffect(() => {
    if (selectedDailyDate) fetchDailyResults(selectedDailyDate);
  }, [selectedDailyDate, fetchDailyResults]);

  const updateJobStatus = useCallback(async (jobId, newStatus) => {
    try {
      const payload = { status: newStatus };
      if (newStatus === 'applied') {
        payload.application_date = new Date().toISOString().slice(0, 10);
      } else if (newStatus === 'new') {
        payload.application_date = null;
      }
      await api.put(`/jobs/${jobId}`, payload);
      setJobs(prevJobs => prevJobs.map(j => j.id === jobId ? { ...j, status: newStatus, applied: newStatus === 'applied' } : j));
      setDailyJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: newStatus } : j));
      addToast(`Status updated to "${STATUS_CONFIG[newStatus]?.label || newStatus}"`, 'success');
    } catch {
      addToast('Failed to update status', 'error');
    }
  }, [addToast, api]);

  const handleBatchMark = useCallback(async (filteredJobsThisTab) => {
    const targets = filteredJobsThisTab.filter(j => j.status !== batchMarkStatus);
    if (targets.length === 0) { addToast('All matching jobs already have that status.', 'info'); return; }
    if (!window.confirm(`Mark ${targets.length} job${targets.length !== 1 ? 's' : ''} as "${STATUS_CONFIG[batchMarkStatus]?.label}"?`)) return;
    setBatchMarkActive(true);
    let done = 0;
    for (const job of targets) {
      try {
        const payload = { status: batchMarkStatus };
        if (batchMarkStatus === 'applied') payload.application_date = new Date().toISOString().slice(0, 10);
        else if (batchMarkStatus === 'new') payload.application_date = null;
        await api.put(`/jobs/${job.id}`, payload);
        done++;
        setJobs(prev => prev.map(j => j.id === job.id ? { ...j, status: batchMarkStatus, applied: batchMarkStatus === 'applied' } : j));
      } catch {
        // continue on individual failures
      }
    }
    setBatchMarkActive(false);
    addToast(`Marked ${done} job${done !== 1 ? 's' : ''} as "${STATUS_CONFIG[batchMarkStatus]?.label}".`, 'success');
  }, [batchMarkStatus, addToast, api]);

  const handleSaveEdit = useCallback(async () => {
    if (!editingJob) return;
    setSavingEdit(true);
    try {
      await api.put(`/jobs/${editingJob.id}`, { title: editTitle, company: editCompany });
      setJobs(prevJobs => prevJobs.map(j => j.id === editingJob.id ? { ...j, title: editTitle, company: editCompany } : j));
      addToast('Job updated successfully', 'success');
      setEditingJob(null);
    } catch {
      addToast('Failed to update job', 'error');
    } finally {
      setSavingEdit(false);
    }
  }, [editingJob, api, editTitle, editCompany, addToast]);

  const handleDeleteUnreviewed = useCallback(async () => {
    if (window.confirm("Delete all 'new' and 'interested' jobs? This preserves your pipeline (applied, interview, offer, rejected) and cannot be undone.")) {
      try {
        const res = await api.delete('/jobs');
        setJobs(prev => prev.filter(j => ['applied', 'interview', 'offer', 'rejected'].includes(j.status)));
        addToast(`Deleted ${res.data.deleted ?? 'unreviewed'} unreviewed jobs.`, "success");
      } catch {
        addToast("Failed to delete unreviewed jobs.", "error");
      }
    }
  }, [addToast, api]);

  const handleDeleteJob = useCallback(async (job) => {
    const label = `${job.title || job.id}${job.company ? ` @ ${job.company}` : ''}`;
    if (!window.confirm(`Delete "${label}"? This cannot be undone.`)) return;
    try {
      await api.delete(`/jobs/${encodeURIComponent(job.id)}`);
      setJobs(prev => prev.filter(j => j.id !== job.id));
      addToast("Job deleted.", "success");
    } catch {
      addToast("Failed to delete job.", "error");
    }
  }, [addToast, api]);

  const handleNuke = useCallback(async () => {
    if (window.confirm("DANGER ZONE: This will delete EVERY job including your pipeline (applied, interview, offer). This action cannot be undone. Are you sure?")) {
      try {
        await api.delete('/jobs/all');
        setJobs([]);
        addToast("Database completely cleared!", "success");
      } catch {
        addToast("Failed to clear database.", "error");
      }
    }
  }, [addToast, api]);

  const handleJobsGenerateCV = useCallback(async (job, options = {}) => {
    const key = `${job.id}-cv`;
    setGeneratingJobsDocs(prev => new Set(prev).add(key));
    addToast(`Generating CV for ${job.company}…`, 'info');
    try {
      const payload = {
        job_id: job.id,
        tone: aiTone,
        cv_profile: options.cv_profile || job.cv_profile_override || null,
        compact: options.compact ?? null,
      };
      if (options.engine) payload.engine = options.engine;
      const res = await api.post('/generate/cv', payload);
      const cvUrl = res.data.download_url;
      if (cvUrl) {
        setJobs(prev => prev.map(j => j.id === job.id ? { ...j, cv_url: cvUrl } : j));
        addToast(`CV ready for ${job.company}!`, 'success');
      }
    } catch (err) {
      addToast(`CV generation failed: ${err.response?.data?.detail || err.message}`, 'error');
    } finally {
      setGeneratingJobsDocs(prev => { const s = new Set(prev); s.delete(key); return s; });
    }
  }, [addToast, aiTone, api]);

  const handleJobsGenerateLetter = useCallback(async (job, options = {}) => {
    const key = `${job.id}-letter`;
    setGeneratingJobsDocs(prev => new Set(prev).add(key));
    addToast(`Generating Cover Letter for ${job.company}…`, 'info');
    try {
      const payload = { job_id: job.id, tone: aiTone };
      if (options.engine) payload.engine = options.engine;
      const res = await api.post('/generate/letter', payload);
      const clUrl = res.data.download_url;
      if (clUrl) {
        setJobs(prev => prev.map(j => j.id === job.id ? { ...j, letter_url: clUrl } : j));
        addToast(`Cover Letter ready for ${job.company}!`, 'success');
      }
    } catch (err) {
      addToast(`Letter generation failed: ${err.response?.data?.detail || err.message}`, 'error');
    } finally {
      setGeneratingJobsDocs(prev => { const s = new Set(prev); s.delete(key); return s; });
    }
  }, [addToast, aiTone, api]);

  const handleJobsGenerateBoth = useCallback(async (job, options = {}) => {
    const cvKey = `${job.id}-cv`;
    const clKey = `${job.id}-letter`;
    setGeneratingJobsDocs(prev => { const s = new Set(prev); s.add(cvKey); s.add(clKey); return s; });
    addToast(`Generating CV & Letter for ${job.company}…`, 'info');
    try {
      const cvPayload = {
        job_id: job.id,
        tone: aiTone,
        cv_profile: options.cv_profile || job.cv_profile_override || null,
        compact: options.compact ?? null,
      };
      const letterPayload = {
        job_id: job.id,
        tone: aiTone,
      };
      if (options.engine) {
        cvPayload.engine = options.engine;
        letterPayload.engine = options.engine;
      }
      const [cvRes, clRes] = await Promise.allSettled([
        api.post('/generate/cv', cvPayload),
        api.post('/generate/letter', letterPayload),
      ]);
      const cvUrl = cvRes.status === 'fulfilled' ? cvRes.value.data.download_url : null;
      const clUrl = clRes.status === 'fulfilled' ? clRes.value.data.download_url : null;
      if (cvUrl || clUrl) {
        setJobs(prev => prev.map(j =>
          j.id === job.id ? { ...j, cv_url: cvUrl ?? j.cv_url, letter_url: clUrl ?? j.letter_url } : j
        ));
        addToast(`Docs ready for ${job.company}!`, 'success');
      }
      if (cvRes.status === 'rejected') addToast(`CV failed: ${cvRes.reason?.response?.data?.detail || cvRes.reason}`, 'error');
      if (clRes.status === 'rejected') addToast(`Letter failed: ${clRes.reason?.response?.data?.detail || clRes.reason}`, 'error');
    } catch {
      addToast(`Doc generation failed for ${job.company}.`, 'error');
    } finally {
      setGeneratingJobsDocs(prev => { const s = new Set(prev); s.delete(cvKey); s.delete(clKey); return s; });
    }
  }, [addToast, aiTone, api]);

  const handleResearchCompany = useCallback(async (jobId, modelName = null) => {
    setResearchingJobId(jobId);
    addToast('Researching company with Perplexity Sonar…', 'info');
    try {
      const payload = modelName ? { model_name: modelName } : {};
      const res = await api.post(`/jobs/${jobId}/research`, payload);
      const { company_research, company_research_updated_at, use_research_in_docs } = res.data;
      setJobs(prev => prev.map(j =>
        j.id === jobId ? { ...j, company_research, company_research_updated_at, use_research_in_docs } : j
      ));
      setSelectedJobDetails(prev =>
        prev && prev.id === jobId ? { ...prev, company_research, company_research_updated_at, use_research_in_docs } : prev
      );
      addToast('Perplexity Sonar research complete!', 'success');
      return res.data;
    } catch (err) {
      addToast(`Sonar research failed: ${err.response?.data?.detail || err.message}`, 'error');
      return null;
    } finally {
      setResearchingJobId(null);
    }
  }, [addToast, api]);

  const handleSaveCompanyResearch = useCallback(async (jobId, researchText, useInDocs = true) => {
    try {
      await api.put(`/jobs/${jobId}`, {
        company_research: researchText,
        company_research_updated_at: new Date().toISOString(),
        use_research_in_docs: useInDocs,
      });
      setJobs(prev => prev.map(j =>
        j.id === jobId ? { ...j, company_research: researchText, use_research_in_docs: useInDocs } : j
      ));
      setSelectedJobDetails(prev =>
        prev && prev.id === jobId ? { ...prev, company_research: researchText, use_research_in_docs: useInDocs } : prev
      );
      addToast('Research notes saved!', 'success');
      return true;
    } catch (err) {
      addToast(`Failed to save research notes: ${err.response?.data?.detail || err.message}`, 'error');
      return false;
    }
  }, [addToast, api]);

  const handleGenerateDocs = useCallback(async (job, options = {}) => { // Daily docs generator
    const jobId = job.id;
    setGeneratingDocs(prev => new Set(prev).add(jobId));
    addToast(`Generating CV & Letter for ${job.company}…`, 'info');
    try {
      const cvPayload = {
        job_id: jobId,
        tone: aiTone,
        cv_profile: options.cv_profile || job.cv_profile_override || null,
        compact: options.compact ?? null,
      };
      const letterPayload = {
        job_id: jobId,
        tone: aiTone,
      };
      const [cvRes, clRes] = await Promise.allSettled([
        api.post('/generate/cv', cvPayload),
        api.post('/generate/letter', letterPayload),
      ]);
      const cvUrl = cvRes.status === 'fulfilled' ? cvRes.value.data.download_url : null;
      const clUrl = clRes.status === 'fulfilled' ? clRes.value.data.download_url : null;
      if (cvUrl || clUrl) {
        setDailyJobs(prev => prev.map(j =>
          j.id === jobId ? { ...j, cv_url: cvUrl ?? j.cv_url, letter_url: clUrl ?? j.letter_url } : j
        ));
        // Also update main jobs store
        setJobs(prev => prev.map(j =>
          j.id === jobId ? { ...j, cv_url: cvUrl ?? j.cv_url, letter_url: clUrl ?? j.letter_url } : j
        ));
        addToast(`Docs ready for ${job.company}!`, 'success');
      }
      if (cvRes.status === 'rejected') addToast(`CV generation failed: ${cvRes.reason?.response?.data?.detail || cvRes.reason}`, 'error');
      if (clRes.status === 'rejected') addToast(`Letter generation failed: ${clRes.reason?.response?.data?.detail || clRes.reason}`, 'error');
    } catch {
      addToast(`Doc generation failed for ${job.company}.`, 'error');
    } finally {
      setGeneratingDocs(prev => { const s = new Set(prev); s.delete(jobId); return s; });
    }
  }, [addToast, aiTone, api]);

  // Derived state
  const appliedCount = useMemo(() => jobs.filter(j => APPLIED_STATUSES.includes(jobStatus(j))).length, [jobs]);
  const actionableCount = useMemo(() =>
    jobs.filter(j => {
      const jobStatus = j.status || (j.applied ? 'applied' : 'new');
      if (jobStatus !== 'new' || !j.qualifies) {
        return false;
      }
      if (!j.date_scraped) return false;
      const age = (Date.now() - new Date(`${j.date_scraped}T00:00:00`).getTime()) / 86400000;
      return age >= 0 && age <= 21;
    }).length,
  [jobs]);

  const uniqueSources = useMemo(() => [...new Set(jobs.map(j => j.source).filter(Boolean))].sort(), [jobs]);

  const uniqueScrapeDates = useMemo(() => [...new Set(jobs.map(j => j.date_scraped).filter(Boolean))].sort().reverse(), [jobs]);

  const filteredJobs = useMemo(() => jobs.filter(job => {
    const germanLevel = normalizeGermanLevel(job.german_level ?? job.requires_german);
    if (germanFilter !== 'All' && germanFilter === 'B1' && !germanLevelCompatible(germanLevel, 'B1')) return false;
    if (germanFilter !== 'All' && germanFilter !== 'B1' && germanLevel !== germanFilter) return false;

    if (!matchesStage(job, statusFilter)) return false;

    const isPipelineJob = ['applied', 'interview', 'offer', 'rejected', 'interested'].includes(jobStatus(job));
    const effectiveDateFilter = scrapeDateFilter || '__recent21';

    if (effectiveDateFilter === '__recent21') {
      if (!isPipelineJob) {
        if (!job.date_scraped) return false;
        const age = (Date.now() - new Date(`${job.date_scraped}T00:00:00`).getTime()) / 86400000;
        if (age < 0 || age > 21) return false;
      }
    } else if (effectiveDateFilter === '__last7') {
      if (!isPipelineJob) {
        if (!job.date_scraped) return false;
        const age = (Date.now() - new Date(`${job.date_scraped}T00:00:00`).getTime()) / 86400000;
        if (age < 0 || age > 7) return false;
      }
    } else if (effectiveDateFilter === '__last30') {
      if (!isPipelineJob) {
        if (!job.date_scraped) return false;
        const age = (Date.now() - new Date(`${job.date_scraped}T00:00:00`).getTime()) / 86400000;
        if (age < 0 || age > 30) return false;
      }
    } else if (effectiveDateFilter === '__today') {
      if (job.date_scraped !== new Date().toISOString().slice(0, 10)) return false;
    } else if (effectiveDateFilter !== '__all' && job.date_scraped !== effectiveDateFilter) {
      return false;
    }

    if (sourceFilter !== 'All' && job.source !== sourceFilter) return false;
    if (!matchesRating(job, minimumRating)) return false;

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      if (!job.title?.toLowerCase().includes(q) &&
          !job.company?.toLowerCase().includes(q) &&
          !job.skills?.toLowerCase().includes(q)) return false;
    }
    return true;
  }), [jobs, germanFilter, statusFilter, scrapeDateFilter, sourceFilter, minimumRating, searchQuery]);

  // Reset pagination on filter change
  useEffect(() => { setCurrentPage(1); }, [germanFilter, statusFilter, scrapeDateFilter, sourceFilter, minimumRating, searchQuery]);

  useEffect(() => {
    try {
      const key = getJobsViewStorageKey(user?.username);
      localStorage.setItem(key, JSON.stringify({
        germanFilter, statusFilter, scrapeDateFilter, sourceFilter,
        minimumRating, searchQuery, itemsPerPage, sortConfig, viewMode,
      }));
    } catch {
      // View preferences are optional and should never block the app.
    }
  }, [user?.username, germanFilter, statusFilter, scrapeDateFilter, sourceFilter, minimumRating, searchQuery, itemsPerPage, sortConfig, viewMode]);

  const activeFilters = useMemo(() => {
    const filters = [];
    if (searchQuery.trim()) filters.push({ key: 'search', label: `Search: ${searchQuery.trim()}` });
    if (defaultGerman === 'B1') {
      if (germanFilter !== 'B1') {
        const label = germanFilter === 'All' ? 'All German levels' : germanFilter === 'none' ? 'German not required' : germanLevelLabel(germanFilter);
        filters.push({ key: 'german', label });
      } else {
        filters.push({ key: 'german', label: 'German: B1 or below' });
      }
    } else {
      if (germanFilter !== 'All') {
        filters.push({ key: 'german', label: `German: ${germanLevelLabel(germanFilter)}` });
      }
    }
    if (statusFilter === 'active') {
      filters.push({ key: 'status', label: 'Status: Active (Unapplied)' });
    } else if (statusFilter !== 'All') {
      filters.push({ key: 'status', label: `Status: ${statusFilter === 'pipeline' ? 'Applied pipeline' : STATUS_CONFIG[statusFilter]?.label || statusFilter}` });
    }
    if (sourceFilter !== 'All') filters.push({ key: 'source', label: `Source: ${sourceFilter}` });
    if (scrapeDateFilter === '__today') filters.push({ key: 'date', label: 'Scraped: Today' });
    else if (scrapeDateFilter === '__last7') filters.push({ key: 'date', label: 'Scraped: Last 7 days' });
    else if (scrapeDateFilter === '__recent21' || !scrapeDateFilter) filters.push({ key: 'date', label: 'Recent (≤21 days)' });
    else if (scrapeDateFilter === '__last30') filters.push({ key: 'date', label: 'Scraped: Last 30 days' });
    else if (scrapeDateFilter !== '__all') filters.push({ key: 'date', label: `Scraped: ${scrapeDateFilter}` });
    if (minimumRating !== '') filters.push({ key: 'rating', label: `Rating: ${minimumRating} or better` });
    return filters;
  }, [defaultGerman, germanFilter, statusFilter, sourceFilter, scrapeDateFilter, minimumRating, searchQuery]);

  const clearFilters = useCallback(() => {
    setGermanFilter(defaultGerman);
    setStatusFilter('All');
    setScrapeDateFilter('__all');
    setSourceFilter('All');
    setMinimumRating('');
    setSearchQuery('');
  }, [defaultGerman]);

  const clearFilter = useCallback((key) => {
    if (key === 'search') setSearchQuery('');
    if (key === 'german') setGermanFilter(defaultGerman);
    if (key === 'status') setStatusFilter('All');
    if (key === 'source') setSourceFilter('All');
    if (key === 'date') setScrapeDateFilter('__all');
    if (key === 'rating') setMinimumRating('');
  }, [defaultGerman]);

  const applyView = useCallback((saved) => {
    const view = normalizeJobsView(saved);
    setGermanFilter(view.germanFilter || defaultGerman);
    setStatusFilter(view.statusFilter || defaultStatus);
    setScrapeDateFilter(view.scrapeDateFilter || '__recent21');
    setSourceFilter(view.sourceFilter || 'All');
    setMinimumRating(view.minimumRating || '');
    setSearchQuery(view.searchQuery || '');
    if (view.sortConfig) setSortConfig(view.sortConfig);
    if (view.viewMode) setViewMode(view.viewMode);
  }, [defaultGerman, defaultStatus]);

  const quickViews = useMemo(() => ({
    inbox: { germanFilter: defaultGerman, statusFilter: 'new', minimumRating: 'Good', scrapeDateFilter: '__recent21' },
    highMatches: { germanFilter: defaultGerman, statusFilter: 'new', minimumRating: 'Great', scrapeDateFilter: '__recent21' },
    last7: { germanFilter: defaultGerman, statusFilter: 'new', minimumRating: '', scrapeDateFilter: '__last7' },
    all: { germanFilter: 'All', statusFilter: 'All', minimumRating: '', scrapeDateFilter: '__all' },
  }), [defaultGerman]);

  const saveCurrentView = useCallback((name) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const view = { name: trimmed, germanFilter, statusFilter, scrapeDateFilter, sourceFilter, minimumRating, searchQuery, sortConfig, viewMode };
    setSavedViews(prev => {
      const next = [...prev.filter(item => item.name !== trimmed), view].slice(-12);
      try {
        localStorage.setItem(getSavedViewsStorageKey(user?.username), JSON.stringify(next));
      } catch { /* Local storage can be unavailable. Keep the current in-memory views. */ }
      return next;
    });
  }, [user?.username, germanFilter, statusFilter, scrapeDateFilter, sourceFilter, minimumRating, searchQuery, sortConfig, viewMode]);

  const deleteSavedView = useCallback((name) => {
    setSavedViews(prev => {
      const next = prev.filter(item => item.name !== name);
      try {
        localStorage.setItem(getSavedViewsStorageKey(user?.username), JSON.stringify(next));
      } catch { /* Local storage can be unavailable. Keep the current in-memory views. */ }
      return next;
    });
  }, [user?.username]);

  const toggleSelectedJob = useCallback((jobId) => {
    setSelectedJobIds(prev => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId); else next.add(jobId);
      return next;
    });
  }, []);

  const setVisibleSelection = useCallback((visibleJobs, selected) => {
    setSelectedJobIds(prev => {
      const next = new Set(prev);
      visibleJobs.forEach(job => selected ? next.add(job.id) : next.delete(job.id));
      return next;
    });
  }, []);

  const selectedJobs = useMemo(() => jobs.filter(job => selectedJobIds.has(job.id)), [jobs, selectedJobIds]);

  const handleSort = useCallback((key) => {
    setSortConfig(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }));
  }, []);

  const sortedJobs = useMemo(() => {
    return [...filteredJobs].sort((a, b) => compareJobs(a, b, sortConfig));
  }, [filteredJobs, sortConfig]);

  const totalPages = Math.max(1, Math.ceil(sortedJobs.length / itemsPerPage));
  useEffect(() => { setCurrentPage(page => Math.min(page, totalPages)); }, [totalPages]);
  const paginatedJobs = useMemo(() => {
    const start = (currentPage - 1) * itemsPerPage;
    return sortedJobs.slice(start, start + itemsPerPage);
  }, [sortedJobs, currentPage, itemsPerPage]);

  return {
    jobs, setJobs, loading,
    editingJob, setEditingJob,
    editTitle, setEditTitle,
    editCompany, setEditCompany,
    savingEdit, setSavingEdit,
    selectedJobDetails, setSelectedJobDetails,
    selectedJobIds, selectedJobs, selectedCount: selectedJobs.length, toggleSelectedJob, setVisibleSelection,
    germanFilter, setGermanFilter,
    statusFilter, setStatusFilter,
    scrapeDateFilter, setScrapeDateFilter,
    sourceFilter, setSourceFilter,
    minimumRating, setMinimumRating,
    searchQuery, setSearchQuery,
    currentPage, setCurrentPage,
    itemsPerPage, setItemsPerPage,
    sortConfig, setSortConfig,
    viewMode, setViewMode,
    batchMarkStatus, setBatchMarkStatus,
    batchMarkActive,
    dailyDates, selectedDailyDate, setSelectedDailyDate,
    dailyJobs, dailyLoading, generatingDocs, generatingJobsDocs,
    
    // Derived
    filteredJobs, sortedJobs, paginatedJobs,
    appliedCount, actionableCount, uniqueSources, uniqueScrapeDates, totalPages,
    activeFilters, filteredOutCount: jobs.length - filteredJobs.length,
    clearFilters, clearFilter, applyView, quickViews, savedViews, saveCurrentView, deleteSavedView,
    
    // Handlers
    fetchJobs, fetchDailyDates, updateJobStatus, handleBatchMark,
    handleSaveEdit, handleDeleteUnreviewed, handleNuke, handleDeleteJob,
    handleJobsGenerateCV, handleJobsGenerateLetter, handleJobsGenerateBoth,
    handleGenerateDocs,
    handleSort,
    researchingJobId, handleResearchCompany, handleSaveCompanyResearch
  };
}
