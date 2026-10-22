import { useState, useCallback } from 'react';
import { api } from '../api/client';

export function useRefine({ aiTone, addToast, onJobsUpdated, onRefineFinished }) {
  const [refiningJob, setRefiningJob] = useState(null);
  const [refiningStatus, setRefiningStatus] = useState('idle');
  const [draftDocs, setDraftDocs] = useState({
    cv_image_urls: [], cl_image_urls: [], cv_tex: '', cl_tex: '',
    cv_versions: [], cl_versions: []
  });
  const [selectedCvVersion, setSelectedCvVersion] = useState(null);
  const [selectedClVersion, setSelectedClVersion] = useState(null);
  const [feedbackCv, setFeedbackCv] = useState('');
  const [feedbackLetter, setFeedbackLetter] = useState('');

  const stampImageUrls = useCallback((urls) => {
    const t = Date.now();
    return (urls || []).map(u => `${u}?t=${t}`);
  }, []);

  const startRefining = useCallback(async (job, docType = 'all', options = {}) => {
    setRefiningJob(job);
    setRefiningStatus('starting');
    setDraftDocs({ cv_image_urls: [], cl_image_urls: [], cv_tex: '', cl_tex: '', cv_versions: [], cl_versions: [], doc_type: docType });
    setFeedbackCv('');
    setFeedbackLetter('');
    try {
      addToast('Initializing AI Refinement Dashboard...', 'info');
      const res = await api.post('/refine/start', {
        job_id: job.id,
        doc_type: docType,
        tone: aiTone,
        cv_profile: options.cv_profile || job.cv_profile_override || null,
        compact: Boolean(options.compact),
      });
      if (res.data.success) {
        setDraftDocs({
          cv_image_urls: stampImageUrls(res.data.cv_image_urls),
          cl_image_urls: stampImageUrls(res.data.cl_image_urls),
          cv_tex: res.data.cv_tex, cl_tex: res.data.cl_tex,
          cv_versions: res.data.cv_versions || [0], cl_versions: res.data.cl_versions || [0],
          doc_type: docType
        });
        if (res.data.cv_versions?.length > 0) setSelectedCvVersion(res.data.cv_versions[res.data.cv_versions.length - 1]);
        if (res.data.cl_versions?.length > 0) setSelectedClVersion(res.data.cl_versions[res.data.cl_versions.length - 1]);
        if (res.data.cv_url || res.data.letter_url) {
          if (onJobsUpdated) onJobsUpdated(job.id, res.data.cv_url, res.data.letter_url);
        }
        setRefiningStatus('idle');
        addToast('Drafts generated! Ready for your feedback.', 'success');
      }
    } catch (err) {
      addToast(err.response?.data?.detail || 'Error starting refinement session', 'error');
      setRefiningStatus('idle');
      setRefiningJob(null);
    }
  }, [aiTone, addToast, onJobsUpdated, stampImageUrls]);

  const iterateDocument = useCallback(async (docType) => {
    const feedback = docType === 'cv' ? feedbackCv : feedbackLetter;
    if (!feedback.trim()) { addToast(`Please provide feedback for the ${docType.toUpperCase()}`, 'warning'); return; }
    setRefiningStatus(`iterating_${docType}`);
    addToast(`Refining ${docType.toUpperCase()} with AI...`, 'info');
    try {
      const res = await api.post('/refine/iterate', {
        job_id: refiningJob.id, document_type: docType,
        current_tex: docType === 'cv' ? draftDocs.cv_tex : draftDocs.cl_tex,
        feedback, tone: aiTone
      });
      if (res.data.success) {
        const stateKey = docType === 'letter' ? 'cl' : docType;
        setDraftDocs(prev => ({
          ...prev,
          [`${stateKey}_image_urls`]: stampImageUrls(res.data.image_urls),
          [`${stateKey}_tex`]: res.data.new_tex,
          [`${stateKey}_versions`]: res.data.versions || prev[`${stateKey}_versions`]
        }));
        if (res.data.versions?.length > 0) {
          const newest = res.data.versions[res.data.versions.length - 1];
          if (docType === 'cv') setSelectedCvVersion(newest); else setSelectedClVersion(newest);
        }
        if (docType === 'cv') setFeedbackCv(''); else setFeedbackLetter('');
        addToast(`${docType.toUpperCase()} successfully updated!`, 'success');
      }
    } catch (err) {
      addToast(err.response?.data?.detail || `Error refining ${docType}`, 'error');
    } finally {
      setRefiningStatus('idle');
    }
  }, [refiningJob, feedbackCv, feedbackLetter, draftDocs, aiTone, addToast, stampImageUrls]);

  const generateDiffOriginal = useCallback(async (docType) => {
    const targetVersion = docType === 'cv' ? selectedCvVersion : selectedClVersion;
    if (targetVersion === null || targetVersion === 0) { addToast("Cannot diff against itself or invalid version", "warning"); return; }
    setRefiningStatus(`diffing_${docType}`);
    addToast(`Compiling latexdiff for v0 vs v${targetVersion}...`, 'info');
    try {
      const res = await api.post('/refine/diff', { job_id: refiningJob.id, document_type: docType, target_version: targetVersion });
      if (res.data.success) {
        const stateKey = docType === 'letter' ? 'cl' : docType;
        setDraftDocs(prev => ({ ...prev, [`${stateKey}_image_urls`]: stampImageUrls(res.data.diff_image_urls) }));
        addToast("Diff generated and displayed!", "success");
      }
    } catch (err) {
      addToast(err.response?.data?.detail || "Failed to generate original diff", "error");
    } finally {
      setRefiningStatus('idle');
    }
  }, [refiningJob, selectedCvVersion, selectedClVersion, addToast, stampImageUrls]);

  const finalizeRefinements = useCallback(async () => {
    setRefiningStatus('finalizing');
    addToast('Saving final documents...', 'info');
    try {
      const res = await api.post('/refine/finalize', { job_id: refiningJob.id, cv_tex: draftDocs.cv_tex, letter_tex: draftDocs.cl_tex });
      if (res.data.success) {
        addToast('Documents successfully finalized and saved!', 'success');
        setRefiningJob(null);
        if (onRefineFinished) onRefineFinished();
      }
    } catch (err) {
      addToast(err.response?.data?.detail || 'Error finalizing documents', 'error');
    } finally {
      setRefiningStatus('idle');
    }
  }, [refiningJob, draftDocs, addToast, onRefineFinished]);

  return {
    refiningJob, setRefiningJob,
    refiningStatus, setRefiningStatus,
    draftDocs, setDraftDocs,
    selectedCvVersion, setSelectedCvVersion,
    selectedClVersion, setSelectedClVersion,
    feedbackCv, setFeedbackCv,
    feedbackLetter, setFeedbackLetter,
    startRefining,
    iterateDocument,
    generateDiffOriginal,
    finalizeRefinements
  };
}
