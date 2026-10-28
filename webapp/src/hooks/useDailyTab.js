import { useState, useCallback, useEffect } from 'react';
import { useApi } from '../api/context';

export function useDailyTab({ addToast, aiTone }) {
  const api = useApi();
  const [dailyDates, setDailyDates] = useState([]);
  const [selectedDailyDate, setSelectedDailyDate] = useState('');
  const [dailyJobs, setDailyJobs] = useState([]);
  const [dailyLoading, setDailyLoading] = useState(false);
  const [generatingDocs, setGeneratingDocs] = useState(new Set());

  const fetchDailyDates = useCallback(async () => {
    try {
      const res = await api.get('/daily-results');
      const dates = res.data.dates || [];
      setDailyDates(dates);
      if (dates.length > 0 && !selectedDailyDate) {
        setSelectedDailyDate(dates[0]);
      }
    } catch {
      addToast('Failed to load daily scrape dates.', 'error');
    }
  }, [addToast, api, selectedDailyDate]);

  const fetchDailyJobs = useCallback(async (dateStr) => {
    if (!dateStr) return;
    setDailyLoading(true);
    try {
      const res = await api.get(`/daily-results/${dateStr}`);
      setDailyJobs(res.data.jobs || []);
    } catch {
      addToast(`Failed to load jobs for ${dateStr}.`, 'error');
    } finally {
      setDailyLoading(false);
    }
  }, [addToast, api]);

  useEffect(() => {
    if (selectedDailyDate) {
      fetchDailyJobs(selectedDailyDate);
    }
  }, [selectedDailyDate, fetchDailyJobs]);

  const handleGenerateDocs = useCallback(async (job, options = {}) => {
    setGeneratingDocs(prev => new Set(prev).add(job.id));
    const payload = {
      job_id: job.id,
      tone: aiTone,
      cv_profile: options.cv_profile || job.cv_profile_override || null,
      compact: options.compact ?? null,
    };
    try {
      if (!job.cv_url) await api.post('/generate/cv', payload);
      if (!job.letter_url) await api.post('/generate/letter', payload);
      addToast(`Documents generated for: ${job.company}`, 'success');
      fetchDailyJobs(selectedDailyDate);
    } catch {
      addToast(`Failed generating docs for ${job.company}`, 'error');
    } finally {
      setGeneratingDocs(prev => {
        const next = new Set(prev);
        next.delete(job.id);
        return next;
      });
    }
  }, [aiTone, api, addToast, fetchDailyJobs, selectedDailyDate]);

  return {
    dailyDates,
    selectedDailyDate, setSelectedDailyDate,
    dailyJobs, setDailyJobs,
    dailyLoading,
    generatingDocs,
    fetchDailyDates, fetchDailyJobs,
    handleGenerateDocs
  };
}
