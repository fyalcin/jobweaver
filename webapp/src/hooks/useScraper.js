import { useState, useRef, useCallback, useEffect } from 'react';
import { api } from '../api/client';

export function useScraper({ user, addToast, fetchJobs, scraperConfig }) {
  const [scraping, setScraping] = useState(false);
  const [scrapeLogs, setScrapingLogs] = useState([]);
  const [activeScrapeTaskId, setActiveScrapeTaskId] = useState(null);
  const [scrapeAiProgress, setScrapeAiProgress] = useState(null);
  const scrapePollInterval = useRef(null);

  // Scrape Params
  const [keywords, setKeywords] = useState("");
  const [karriereKeyword, setKarriereKeyword] = useState("");
  const [resultsLimit, setResultsLimit] = useState(7);
  const [hoursOld, setHoursOld] = useState(48);
  const [distance, setDistance] = useState(10);
  const [source, setSource] = useState('linkedin-apify');
  
  const lastSource = useRef(null);
  useEffect(() => {
    if (scraperConfig && lastSource.current !== source) {
      if (source.startsWith('karriere')) {
        // This effect intentionally hydrates editable scraper fields from persisted config.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setKarriereKeyword(scraperConfig.karriere?.keywords?.join(', ') || "Python, Data Science, Software Developer, Backend Developer");
        setResultsLimit(scraperConfig.karriere?.results_limit || 10);
        setHoursOld(scraperConfig.karriere?.hours_old || 24);
        setDistance(scraperConfig.karriere?.distance || 10);
      } else {
        setKeywords(scraperConfig.linkedin?.keywords || "data science OR python OR backend developer OR software developer");
        setResultsLimit(scraperConfig.linkedin?.results_limit || 50);
        setHoursOld(scraperConfig.linkedin?.hours_old || 24);
        setDistance(scraperConfig.linkedin?.distance || 10);
      }
      lastSource.current = source;
    }
  }, [scraperConfig, source]);

  // Reprocess Queue
  const [unprocessedJobs, setUnprocessedJobs] = useState([]);
  const [reprocessTaskId, setReprocessTaskId] = useState(null);
  const [reprocessProgress, setReprocessProgress] = useState(null);
  const reprocessPollInterval = useRef(null);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await api.get('/logs');
      setScrapingLogs(res.data);
    } catch (err) {
      console.error("Failed to fetch logs", err);
    }
  }, []);

  const fetchUnprocessedJobs = useCallback(async () => {
    try {
      const res = await api.get('/jobs/unprocessed');
      setUnprocessedJobs(res.data.jobs || []);
    } catch (err) {
      console.error('Failed to fetch unprocessed jobs', err);
    }
  }, []);

  const pollScrapeStatus = useCallback(async (taskId) => {
    try {
      const res = await api.get(`/scrape/status/${taskId}`);
      const { status, logs, result, total, processed, failed } = res.data;
      setScrapingLogs([...logs].reverse());
      if (total != null && total > 0) {
        setScrapeAiProgress({ processed: processed ?? 0, total, failed: failed ?? 0 });
      } else {
        setScrapeAiProgress(null);
      }
      if (status === 'completed' || status === 'failed') {
        clearInterval(scrapePollInterval.current);
        scrapePollInterval.current = null;
        setActiveScrapeTaskId(null);
        setScraping(false);
        setScrapeAiProgress(null);
        if (status === 'completed' && result?.success) {
          addToast(result.message || 'Scraping completed.', 'success');
        } else {
          addToast(result?.message || 'Scraping failed.', 'error');
        }
        fetchJobs();
        fetchLogs();
        fetchUnprocessedJobs();
      }
    } catch (err) {
      console.error('Failed to poll status', err);
      if (err.response?.status === 404) {
        clearInterval(scrapePollInterval.current);
        scrapePollInterval.current = null;
        setActiveScrapeTaskId(null);
        setScraping(false);
      setScrapeAiProgress(null);
      }
    }
  }, [addToast, fetchJobs, fetchLogs, fetchUnprocessedJobs]);

  const checkActiveScrape = useCallback(async () => {
    try {
      const res = await api.get('/scrape/active');
      if (res.data.active && res.data.task_id) {
        setActiveScrapeTaskId(res.data.task_id);
        setScraping(true);
        const logs = res.data.logs || [];
        setScrapingLogs([...logs].reverse());
        const { total, processed, failed } = res.data;
        if (total != null && total > 0) {
          setScrapeAiProgress({ processed: processed ?? 0, total, failed: failed ?? 0 });
        }
        if (scrapePollInterval.current) clearInterval(scrapePollInterval.current);
        scrapePollInterval.current = setInterval(() => pollScrapeStatus(res.data.task_id), 1500);
      }
    } catch (err) {
      console.error('Failed to check active scrape', err);
    }
  }, [pollScrapeStatus]);

  const handleScrape = useCallback(async () => {
    setScraping(true);
    setScrapingLogs([]);
    setScrapeAiProgress(null);
    addToast('Scraping started in background. Logs will stream live...', 'info');
    try {
      const payload = {
        keywords: source.startsWith('karriere') ? karriereKeyword : keywords,
        results_limit: resultsLimit,
        hours_old: hoursOld,
        distance,
        source
      };
      const res = await api.post('/scrape', payload);
      if (res.data.success && res.data.task_id) {
        setActiveScrapeTaskId(res.data.task_id);
        if (scrapePollInterval.current) clearInterval(scrapePollInterval.current);
        scrapePollInterval.current = setInterval(() => pollScrapeStatus(res.data.task_id), 1500);
      } else {
        setScraping(false);
        addToast('Failed to start scrape.', 'error');
        fetchLogs();
      }
    } catch {
      addToast('Scraping submission failed.', 'error');
      setScraping(false);
      fetchLogs();
    }
  }, [source, karriereKeyword, keywords, resultsLimit, hoursOld, distance, addToast, fetchLogs, pollScrapeStatus]);

  const pollReprocessStatus = useCallback(async (taskId) => {
    try {
      const res = await api.get(`/reprocess/status/${taskId}`);
      const { status, processed, total, failed } = res.data;
      setReprocessProgress({ status, processed, total, failed });
      if (status === 'completed' || status === 'failed' || status === 'cancelled') {
        clearInterval(reprocessPollInterval.current);
        reprocessPollInterval.current = null;
        setReprocessTaskId(null);
        setReprocessProgress(null);
        fetchJobs();
        fetchUnprocessedJobs();
        if (status === 'completed') {
          addToast(`Processing complete: ${processed} jobs analysed${failed ? `, ${failed} failed` : ''}.`, failed ? 'warning' : 'success');
        } else if (status === 'cancelled') {
          addToast('Job analysis cancelled.', 'info');
        } else {
          addToast('Job analysis task failed.', 'error');
        }
      }
    } catch (err) {
      if (err.response?.status === 404) {
        clearInterval(reprocessPollInterval.current);
        reprocessPollInterval.current = null;
        setReprocessTaskId(null);
        setReprocessProgress(null);
      }
    }
  }, [fetchJobs, fetchUnprocessedJobs, addToast]);

  const checkActiveReprocess = useCallback(async () => {
    try {
      const res = await api.get('/reprocess/active');
      if (res.data.active && res.data.task_id) {
        setReprocessTaskId(res.data.task_id);
        setReprocessProgress({ status: res.data.status, processed: res.data.processed, total: res.data.total, failed: res.data.failed });
        if (reprocessPollInterval.current) clearInterval(reprocessPollInterval.current);
        reprocessPollInterval.current = setInterval(() => pollReprocessStatus(res.data.task_id), 2000);
      }
    } catch (err) {
      console.error('Failed to check active reprocess', err);
    }
  }, [pollReprocessStatus]);

  const handleStartReprocess = useCallback(async () => {
    try {
      const res = await api.post('/reprocess');
      if (res.data.task_id) {
        setReprocessTaskId(res.data.task_id);
        setReprocessProgress({ status: 'running', processed: 0, total: res.data.total, failed: 0 });
        if (reprocessPollInterval.current) clearInterval(reprocessPollInterval.current);
        reprocessPollInterval.current = setInterval(() => pollReprocessStatus(res.data.task_id), 2000);
        addToast(`AI analysis started for ${res.data.total} jobs…`, 'info');
      } else {
        addToast(res.data.message || 'No unprocessed jobs.', 'info');
      }
    } catch {
      addToast('Failed to start reprocessing.', 'error');
    }
  }, [addToast, pollReprocessStatus]);

  // These callbacks perform the initial remote-state synchronization for this hook.
  useEffect(() => {
    if (!user) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchLogs();
    fetchUnprocessedJobs();
    checkActiveScrape();
    checkActiveReprocess();
    return () => {
      if (scrapePollInterval.current) clearInterval(scrapePollInterval.current);
      if (reprocessPollInterval.current) clearInterval(reprocessPollInterval.current);
    };
  }, [user, fetchLogs, fetchUnprocessedJobs, checkActiveScrape, checkActiveReprocess]);

  return {
    scraping,
    scrapeLogs,
    activeScrapeTaskId,
    scrapeAiProgress,
    keywords, setKeywords,
    karriereKeyword, setKarriereKeyword,
    resultsLimit, setResultsLimit,
    hoursOld, setHoursOld,
    distance, setDistance,
    source, setSource,
    unprocessedJobs,
    reprocessTaskId,
    reprocessProgress,
    fetchLogs,
    fetchUnprocessedJobs,
    handleScrape,
    handleStartReprocess
  };
}
