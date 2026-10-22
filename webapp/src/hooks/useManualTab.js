import { useState, useCallback, useEffect } from 'react';
import { api } from '../api/client';

export function useManualTab({ user, addToast, fetchJobs, startRefining, aiModel, aiTone }) {
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

  // The available CV profiles are per-user (server resolves the logged-in
  // user's profiles/<user>/cv_profiles.py override).
  useEffect(() => {
    if (!user) return;
    let active = true;
    api.get('/cv-profiles')
      .then((res) => { if (active) setCvProfiles(res.data.profiles || []); })
      .catch(() => { if (active) setCvProfiles([]); });
    return () => { active = false; };
  }, [user]);

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
  }, [manualUrl, addToast]);

  const handleAddManualJob = useCallback(async (docType = null) => {
    if (!manualDescription.trim()) {
      addToast('Job description is required for manual entry.', 'warning');
      return;
    }
    setAddingManualJob(true);
    const saveToDb = docType === null;
    try {
      const payload = {
        title: manualTitle, company: manualCompany, description: manualDescription,
        job_url: manualUrl.trim(), location: '', save_to_db: saveToDb, doc_type: docType,
        modelName: aiModel, tone: aiTone, cv_profile_override: manualCvProfile || null,
        compact: manualCompact,
      };
      const res = await api.post('/jobs/manual', payload);
      if (res.data.success) {
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
      addToast(err.response?.data?.detail || 'Failed to process manual job.', 'error');
    } finally {
      setAddingManualJob(false);
    }
  }, [manualDescription, manualTitle, manualCompany, manualUrl, manualCvProfile, manualCompact, aiModel, aiTone, addToast, fetchJobs, startRefining]);

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
    handleFetchJobUrl, handleAddManualJob
  };
}
