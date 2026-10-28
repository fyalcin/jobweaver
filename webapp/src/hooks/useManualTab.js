import { useState, useCallback, useEffect } from 'react';
import { useApi } from '../api/context';

export function useManualTab({ user, addToast, fetchJobs, fetchUnprocessedJobs, startReprocess, startRefining, aiModel, aiTone }) {
  const api = useApi();
  const [manualUrl, setManualUrl] = useState('');
  const [manualTitle, setManualTitle] = useState('');
  const [manualCompany, setManualCompany] = useState('');
  const [manualDescription, setManualDescription] = useState('');
  const [fetchingUrl, setFetchingUrl] = useState(false);
  const [fetchUrlWarning, setFetchUrlWarning] = useState(null);
  const [addingManualJob, setAddingManualJob] = useState(false);
  const [manualCvProfile, setManualCvProfile] = useState('');
  const [manualCompact, setManualCompact] = useState(false);
  const [cvProfiles, setCvProfiles] = useState([]);
  // A failure that must stay visible after the toast fades: { kind: 'analysis'|'error', message, reason }.
  const [manualNotice, setManualNotice] = useState(null);

  // The available CV profiles are per-user (server resolves the logged-in
  // user's profiles/<user>/cv_profiles.py override).
  useEffect(() => {
    if (!user) return;
    let active = true;
    api.get('/cv-profiles')
      .then((res) => { if (active) setCvProfiles(res.data.profiles || []); })
      .catch(() => { if (active) setCvProfiles([]); });
    return () => { active = false; };
  }, [api, user]);

  const handleFetchJobUrl = useCallback(async () => {
    if (!manualUrl.trim()) return;
    setFetchingUrl(true);
    setFetchUrlWarning(null);
    try {
      const res = await api.post('/fetch-job-url', { url: manualUrl.trim() });
      if (res.data.title) setManualTitle(res.data.title);
      if (res.data.company) setManualCompany(res.data.company);
      if (res.data.description) setManualDescription(res.data.description);
      if (res.data.warning) setFetchUrlWarning(res.data.warning);
      addToast('Job page fetched — review and edit before generating.', 'success');
    } catch (err) {
      addToast(err.response?.data?.detail || 'Failed to fetch URL.', 'error');
    } finally {
      setFetchingUrl(false);
    }
  }, [manualUrl, api, addToast]);

  const handleAddManualJob = useCallback(async (docType = null) => {
    if (!manualDescription.trim()) {
      addToast('Job description is required for manual entry.', 'warning');
      return;
    }
    setAddingManualJob(true);
    setManualNotice(null);
    const saveToDb = docType === null;
    try {
      const payload = {
        title: manualTitle, company: manualCompany, description: manualDescription,
        job_url: manualUrl.trim(), location: '', save_to_db: saveToDb, doc_type: docType,
        modelName: aiModel, tone: aiTone, cv_profile_override: manualCvProfile || null,
        compact: manualCompact,
      };
      const res = await api.post('/jobs/manual', payload);
      if (res.data.saved && !res.data.success) {
        // The posting is stored, but its analysis failed: clear the form (resubmitting would be a
        // duplicate) and keep the reason on screen with a retry.
        const reason = res.data.error || res.data.job?.analysis_error || 'No reason was given.';
        setManualNotice({ kind: 'analysis', message: 'Posting saved, but the analysis failed.', reason });
        addToast(`Posting saved, but the analysis failed: ${reason}`, 'warning');
        setManualTitle('');
        setManualCompany('');
        setManualDescription('');
        setManualUrl('');
        fetchJobs();
        if (fetchUnprocessedJobs) fetchUnprocessedJobs();
      } else if (!res.data.success) {
        const reason = res.data.message || 'The server did not accept the posting.';
        setManualNotice({ kind: 'error', message: 'The posting was not processed.', reason });
        addToast(reason, 'error');
      } else {
        addToast(res.data.message, 'success');
        if (saveToDb) {
          setManualTitle('');
          setManualCompany('');
          setManualDescription('');
          setManualUrl('');
          fetchJobs();
        }
        if (docType && res.data.job && startRefining) {
          startRefining(res.data.job, docType, { compact: manualCompact, cv_profile: manualCvProfile || null });
        }
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      const reason = typeof detail === 'string' ? detail : 'Failed to process manual job.';
      setManualNotice({ kind: 'error', message: saveToDb ? 'The posting was not saved.' : 'The documents were not generated.', reason });
      addToast(reason, 'error');
    } finally {
      setAddingManualJob(false);
    }
  }, [manualDescription, addToast, manualTitle, manualCompany, manualUrl, aiModel, aiTone, manualCvProfile, manualCompact, api, startRefining, fetchJobs, fetchUnprocessedJobs]);

  const retryManualAnalysis = useCallback(async () => {
    // The reprocess queue covers every pending or failed job; its own toast reports progress or refusal.
    if (startReprocess) await startReprocess();
  }, [startReprocess]);

  return {
    manualUrl, setManualUrl,
    manualTitle, setManualTitle,
    manualCompany, setManualCompany,
    manualDescription, setManualDescription,
    fetchingUrl, fetchUrlWarning, setFetchUrlWarning,
    addingManualJob,
    manualCvProfile, setManualCvProfile,
    manualCompact, setManualCompact,
    cvProfiles,
    manualNotice, setManualNotice, retryManualAnalysis,
    handleFetchJobUrl, handleAddManualJob
  };
}
