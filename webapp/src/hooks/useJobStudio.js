import { useState, useCallback, useEffect, useRef } from 'react';
import { api } from '../api/client';
import { compileTypstClient, uint8ArrayToBase64, downloadPdfBlob } from '../services/typstWorkerClient';

export function useJobStudio(jobId, onJobUpdated) {
  const [activeDocType, setActiveDocType] = useState('cv'); // 'cv' | 'letter'
  const [cvTex, setCvTex] = useState('');
  const [clTex, setClTex] = useState('');
  const [cvEngine, setCvEngine] = useState('latex');
  const [clEngine, setClEngine] = useState('latex');
  const [cvImages, setCvImages] = useState([]);
  const [clImages, setClImages] = useState([]);
  const [cvDownloadUrl, setCvDownloadUrl] = useState(null);
  const [clDownloadUrl, setClDownloadUrl] = useState(null);
  const [hasCv, setHasCv] = useState(false);
  const [hasLetter, setHasLetter] = useState(false);
  const [compiledSources, setCompiledSources] = useState({ cv: null, letter: null });
  const [loading, setLoading] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [aiEditing, setAiEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [aiVersions, setAiVersions] = useState({ cv: [], letter: [] });
  const [errorCard, setErrorCard] = useState(null);
  const [showCheatSheet, setShowCheatSheet] = useState(false);

  const currentRef = useRef({});
  currentRef.current = { jobId, activeDocType, cvTex, clTex };
  const loadSequence = useRef(0);
  const operationSequence = useRef(0);
  const isCurrent = (job, type, source) => currentRef.current.jobId === job &&
    currentRef.current.activeDocType === type &&
    currentRef.current[type === 'cv' ? 'cvTex' : 'clTex'] === source;

  const isTypstCode = (text) =>
    Boolean(text && (text.includes('#set ') || text.includes('#let ') || text.includes('@preview/') || text.trim().startsWith('//')));

  const docEngine =
    activeDocType === 'cv'
      ? (cvEngine === 'typst' || isTypstCode(cvTex) ? 'typst' : 'latex')
      : (clEngine === 'typst' || isTypstCode(clTex) ? 'typst' : 'latex');

  // Fetch documents for the current job
  const fetchDocuments = useCallback(async () => {
    if (!jobId) return;
    const sequence = ++loadSequence.current;
    setLoading(true);
    try {
      const res = await api.get(`/jobs/${jobId}/documents`);
      if (currentRef.current.jobId !== jobId || sequence !== loadSequence.current) return;
      if (res.data?.success) {
        setCvTex(res.data.cv_tex || '');
        setClTex(res.data.cl_tex || '');
        setCvEngine(res.data.cv_engine || (isTypstCode(res.data.cv_tex) ? 'typst' : 'latex'));
        setClEngine(res.data.cl_engine || (isTypstCode(res.data.cl_tex) ? 'typst' : 'latex'));
        setCvImages(res.data.cv_images || []);
        setClImages(res.data.cl_images || []);
        setCvDownloadUrl(res.data.cv_download_url || null);
        setClDownloadUrl(res.data.cl_download_url || null);
        setHasCv(Boolean(res.data.has_cv));
        setHasLetter(Boolean(res.data.has_letter));
        setCompiledSources({ cv: res.data.cv_pdf_current ? res.data.cv_tex : null,
          letter: res.data.cl_pdf_current ? res.data.cl_tex : null });
        if (res.data.ai_versions) {
          setAiVersions(res.data.ai_versions);
        }

        // Auto-select letter if only letter exists
        if (!res.data.has_cv && res.data.has_letter) {
          setActiveDocType('letter');
        } else {
          setActiveDocType('cv');
        }
      }
    } catch (err) {
      console.error('Failed to load job documents:', err);
    } finally {
      if (currentRef.current.jobId === jobId && sequence === loadSequence.current) setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Compile current active document
  const compile = useCallback(async () => {
    if (!jobId) return false;
    setCompiling(true);
    setErrorCard(null);
    const tex = activeDocType === 'cv' ? cvTex : clTex;
    const sequence = ++operationSequence.current;
    try {
      let pdfBase64 = null;
      if (docEngine === 'typst') {
        try {
          const pdfRes = await compileTypstClient(tex, 'pdf');
          if (pdfRes?.result) {
            pdfBase64 = uint8ArrayToBase64(pdfRes.result);
          }
        } catch (wasmErr) {
          const rawMsg = wasmErr?.message || String(wasmErr);
          const cleanMsg = rawMsg.replace(/\[SourceDiagnostic\s*\{[^}]*message:\s*"([^"]+)"[^}]*\}\]/g, '$1');
          if (!isCurrent(jobId, activeDocType, tex)) return false;
          setErrorCard({
            message: cleanMsg || 'Typst compilation error',
            parsed: null,
            rawLog: rawMsg,
          });
          return false;
        }
      }

      if (!isCurrent(jobId, activeDocType, tex) || sequence !== operationSequence.current) return false;
      const res = await api.post(`/jobs/${jobId}/documents/compile`, {
        document_type: activeDocType,
        tex,
        pdf_base64: pdfBase64,
      });
      if (!isCurrent(jobId, activeDocType, tex) || sequence !== operationSequence.current) return false;
      if (res.data?.success) {
        setCompiledSources((previous) => ({ ...previous, [activeDocType]: tex }));
        if (activeDocType === 'cv') {
          if (res.data.image_urls) setCvImages(res.data.image_urls);
          if (res.data.pdf_url) setCvDownloadUrl(res.data.pdf_url);
          setHasCv(true);
        } else {
          if (res.data.image_urls) setClImages(res.data.image_urls);
          if (res.data.pdf_url) setClDownloadUrl(res.data.pdf_url);
          setHasLetter(true);
        }
        return true;
      } else {
        setErrorCard({
          message: res.data?.error || 'Compilation failed',
          parsed: res.data?.parsed_error || null,
          rawLog: res.data?.raw_log || '',
        });
        return false;
      }
    } catch (err) {
      if (!isCurrent(jobId, activeDocType, tex) || sequence !== operationSequence.current) return false;
      const msg = err.response?.data?.detail || err.message || 'Compilation error';
      setErrorCard({ message: msg, parsed: null, rawLog: '' });
      return false;
    } finally {
      if (currentRef.current.jobId === jobId && sequence === operationSequence.current) setCompiling(false);
    }
  }, [jobId, activeDocType, cvTex, clTex, docEngine]);

  // AI Surgical Edit
  const aiEdit = useCallback(async (instruction, selection = null, modelName = null) => {
    if (!jobId || !instruction.trim()) return false;
    setAiEditing(true);
    setErrorCard(null);
    const tex = activeDocType === 'cv' ? cvTex : clTex;
    const sequence = ++operationSequence.current;

    try {
      const res = await api.post(`/jobs/${jobId}/documents/ai-edit`, {
        document_type: activeDocType,
        tex,
        instruction,
        selection,
        model_name: modelName,
      });
      if (!isCurrent(jobId, activeDocType, tex) || sequence !== operationSequence.current) return false;
      if (res.data?.success) {
        const modified = res.data.modified_tex || tex;
        setCompiledSources((previous) => ({ ...previous, [activeDocType]: res.data.compile_success ? modified : null }));
        if (activeDocType === 'cv') {
          setCvTex(modified);
          if (res.data.image_urls?.length) {
            setCvImages(res.data.image_urls);
            setHasCv(true);
          }
        } else {
          setClTex(modified);
          if (res.data.image_urls?.length) {
            setClImages(res.data.image_urls);
            setHasLetter(true);
          }
        }
        if (res.data.ai_versions) {
          setAiVersions(res.data.ai_versions);
        }
        if (!res.data.compile_success) {
          setErrorCard({
            message: 'The text changed, but compilation failed. The previous PDF is out of date.',
            parsed: res.data.parsed_error || null,
            rawLog: '',
          });
        }
        return true;
      }
      return false;
    } catch (err) {
      if (!isCurrent(jobId, activeDocType, tex) || sequence !== operationSequence.current) return false;
      const msg = err.response?.data?.detail || err.message || 'AI edit failed';
      setErrorCard({ message: msg, parsed: null, rawLog: '' });
      return false;
    } finally {
      if (currentRef.current.jobId === jobId && sequence === operationSequence.current) setAiEditing(false);
    }
  }, [jobId, activeDocType, cvTex, clTex]);

  // Revert/restore to an AI snapshot by versionId
  const restoreVersion = useCallback(async (versionId) => {
    if (!jobId || !versionId) return false;
    setCompiling(true);
    setErrorCard(null);
    const tex = activeDocType === 'cv' ? cvTex : clTex;
    const sequence = ++operationSequence.current;
    try {
      const res = await api.post(`/jobs/${jobId}/documents/restore-version`, {
        document_type: activeDocType,
        version_id: String(versionId),
      });
      if (!isCurrent(jobId, activeDocType, tex) || sequence !== operationSequence.current) return false;
      if (res.data?.success) {
        const restored = res.data.restored_tex;
        setCompiledSources((previous) => ({ ...previous, [activeDocType]: res.data.compile_success ? restored : null }));
        if (activeDocType === 'cv') {
          setCvTex(restored);
          if (res.data.image_urls?.length) {
            setCvImages(res.data.image_urls);
            setHasCv(true);
          }
        } else {
          setClTex(restored);
          if (res.data.image_urls?.length) {
            setClImages(res.data.image_urls);
            setHasLetter(true);
          }
        }
        if (res.data.ai_versions) {
          setAiVersions(res.data.ai_versions);
        }
        return true;
      }
      return false;
    } catch (err) {
      if (!isCurrent(jobId, activeDocType, tex) || sequence !== operationSequence.current) return false;
      const msg = err.response?.data?.detail || err.message || 'Failed to restore version';
      setErrorCard({ message: msg, parsed: null, rawLog: '' });
      return false;
    } finally {
      if (currentRef.current.jobId === jobId && sequence === operationSequence.current) setCompiling(false);
    }
  }, [jobId, activeDocType, cvTex, clTex]);

  // Finalize & Save PDFs
  const finalize = useCallback(async () => {
    if (!jobId) return false;
    setSaving(true);
    try {
      setErrorCard(null);
      const res = await api.post(`/jobs/${jobId}/documents/finalize`, {
        document_type: 'all',
        cv_source: cvTex || null,
        letter_source: clTex || null,
      });
      if (currentRef.current.jobId !== jobId || currentRef.current.cvTex !== cvTex || currentRef.current.clTex !== clTex) return false;
      if (res.data?.success) {
        if (res.data.cv_url) setCvDownloadUrl(res.data.cv_url);
        if (res.data.letter_url) setClDownloadUrl(res.data.letter_url);
        if (onJobUpdated) onJobUpdated();
        return true;
      }
      return false;
    } catch (err) {
      setErrorCard({ message: err.response?.data?.detail || 'Finalization failed. Compile the current version first.', parsed: null, rawLog: '' });
      return false;
    } finally {
      if (currentRef.current.jobId === jobId) setSaving(false);
    }
  }, [jobId, cvTex, clTex, onJobUpdated]);

  const downloadClientPdf = useCallback(async (type = null) => {
    const targetType = type || activeDocType;
    const tex = targetType === 'cv' ? cvTex : clTex;
    if (!tex) return;
    try {
      const pdfRes = await compileTypstClient(tex, 'pdf');
      if (pdfRes?.result) {
        downloadPdfBlob(pdfRes.result, `${targetType.toUpperCase()}.pdf`);
      }
    } catch (err) {
      console.error('Failed to download instant PDF:', err);
    }
  }, [activeDocType, cvTex, clTex]);

  const currentTex = activeDocType === 'cv' ? cvTex : clTex;
  const docVersions = aiVersions?.[activeDocType] || [];
  const matchedVersion = docVersions.find((v) => v.tex?.trim() === currentTex?.trim());
  const activeVersionId = matchedVersion ? String(matchedVersion.id) : null;

  return {
    pdfCurrent: activeDocType === 'cv' ? compiledSources.cv === cvTex : compiledSources.letter === clTex,
    activeDocType,
    setActiveDocType,
    docEngine,
    cvEngine,
    clEngine,
    currentTex,
    setCurrentTex: (val) => (activeDocType === 'cv' ? setCvTex(val) : setClTex(val)),
    activeVersionId,
    cvTex,
    setCvTex,
    clTex,
    setClTex,
    currentImages: activeDocType === 'cv' ? cvImages : clImages,
    cvImages,
    clImages,
    cvDownloadUrl,
    clDownloadUrl,
    hasCv,
    hasLetter,
    loading,
    compiling,
    aiEditing,
    saving,
    zoom,
    setZoom,
    errorCard,
    setErrorCard,
    showCheatSheet,
    setShowCheatSheet,
    fetchDocuments,
    compile,
    aiEdit,
    restoreVersion,
    aiVersions,
    finalize,
    downloadClientPdf,
  };
}
