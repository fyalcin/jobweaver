import { useState, useRef, useCallback, useEffect } from 'react';
import { useApi } from '../api/context';

export function useBatchGen({ user, aiTone, addToast, filteredJobs, fetchJobs }) {
  const api = useApi();
  const [batchGenTaskId, setBatchGenTaskId] = useState(null);
  const [batchGenProgress, setBatchGenProgress] = useState(null);
  const [batchGenSubmitting, setBatchGenSubmitting] = useState(false);
  const [batchCompact, setBatchCompact] = useState(null);
  const batchGenPollInterval = useRef(null);

  const pollBatchGenStatus = useCallback(async (taskId) => {
    try {
      const res = await api.get(`/generate/batch/status/${taskId}`);
      const { status, stage, processed, total, failed, result } = res.data;
      setBatchGenProgress({ status, stage, processed, total, failed });
      if (['completed', 'failed', 'cancelled', 'interrupted'].includes(status)) {
        clearInterval(batchGenPollInterval.current);
        batchGenPollInterval.current = null;
        setBatchGenTaskId(null);
        setBatchGenProgress(null);
        fetchJobs({ clearSelection: true });
        if (status === 'completed') {
          addToast(
            failed > 0
              ? `Batch complete: ${processed} generated, ${failed} failed.`
              : `Batch complete: ${processed} job${processed !== 1 ? 's' : ''} generated successfully.`,
            failed > 0 ? 'warning' : 'success'
          );
        } else if (status === 'cancelled') {
          addToast('Batch document generation cancelled.', 'info');
        } else {
          addToast(result?.message || 'Batch document generation failed.', 'error');
        }
      }
    } catch (err) {
      if (err.response?.status === 404) {
        clearInterval(batchGenPollInterval.current);
        batchGenPollInterval.current = null;
        setBatchGenTaskId(null);
        setBatchGenProgress(null);
      }
    }
  }, [api, fetchJobs, addToast]);

  const checkActiveBatchGenerate = useCallback(async () => {
    try {
      const res = await api.get('/generate/batch/active');
      if (res.data.active && res.data.task_id) {
        setBatchGenTaskId(res.data.task_id);
        setBatchGenProgress({
          status: res.data.status,
          stage: res.data.stage,
          processed: res.data.processed,
          total: res.data.total,
          failed: res.data.failed,
        });
        if (batchGenPollInterval.current) clearInterval(batchGenPollInterval.current);
        batchGenPollInterval.current = setInterval(() => pollBatchGenStatus(res.data.task_id), 2000);
      }
    } catch (err) {
      console.error('Failed to check active batch generate', err);
    }
  }, [api, pollBatchGenStatus]);

  useEffect(() => {
    if (!user) return;
    checkActiveBatchGenerate();
    return () => {
      if (batchGenPollInterval.current) clearInterval(batchGenPollInterval.current);
    };
  }, [user, checkActiveBatchGenerate]);

  const startBatch = useCallback(async (targets, toastLabel, force = false, options = {}) => {
    if (targets.length === 0) {
      addToast('No jobs to generate documents for.', 'info');
      return;
    }
    setBatchGenSubmitting(true);
    try {
      const payload = {
        job_ids: targets.map(j => j.id),
        tone: aiTone,
        force,
        compact: batchCompact,
      };
      if (options.engine) payload.engine = options.engine;
      const res = await api.post('/generate/batch', payload);
      if (res.data.task_id) {
        setBatchGenTaskId(res.data.task_id);
        setBatchGenProgress({ status: res.data.status, stage: res.data.stage, processed: 0, total: res.data.total, failed: 0 });
        if (batchGenPollInterval.current) clearInterval(batchGenPollInterval.current);
        batchGenPollInterval.current = setInterval(() => pollBatchGenStatus(res.data.task_id), 2000);
        addToast(`${toastLabel} ${res.data.status === 'queued' ? 'queued' : 'started'} for ${res.data.total} job${res.data.total !== 1 ? 's' : ''}…`, 'info');
      }
    } catch (err) {
      const d = err.response?.data?.detail;
      addToast(typeof d === 'string' ? d : 'Failed to start batch generation.', 'error');
    } finally {
      setBatchGenSubmitting(false);
    }
  }, [addToast, aiTone, batchCompact, api, pollBatchGenStatus]);

  const handleBatchGenerate = useCallback(async (selectedTargets = null, options = {}) => {
    // Guard against being used as a raw onClick handler (React passes the
    // click event as first arg — a MouseEvent has no .filter).
    const pool = Array.isArray(selectedTargets) ? selectedTargets : filteredJobs;
    const targets = pool.filter(j => !j.cv_url || !j.letter_url);
    if (targets.length === 0) {
      addToast(selectedTargets ? 'All selected jobs already have documents generated.' : 'All matching jobs already have documents generated.', 'info');
      return;
    }
    await startBatch(targets, selectedTargets ? 'Selected document generation' : 'Batch generation', false, options);
  }, [filteredJobs, addToast, startBatch]);

  const handleBatchGenerateForce = useCallback(async (selectedTargets = null, options = {}) => {
    const pool = Array.isArray(selectedTargets) ? selectedTargets : filteredJobs;
    await startBatch(pool, selectedTargets ? 'Selected regeneration' : 'Force-regeneration', true, options);
  }, [filteredJobs, startBatch]);

  const handleBatchGenerateCancel = useCallback(async () => {
    try {
      await api.post('/generate/batch/cancel');
      addToast('Stopping after the current job finishes…', 'info');
    } catch {
      addToast('Failed to cancel batch.', 'error');
    }
  }, [addToast, api]);

  return {
    batchGenTaskId,
    batchGenProgress,
    batchGenSubmitting,
    batchCompact,
    setBatchCompact,
    handleBatchGenerate,
    handleBatchGenerateForce,
    handleBatchGenerateCancel
  };
}
