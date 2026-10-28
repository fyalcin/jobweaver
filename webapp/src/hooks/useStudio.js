import { useState, useCallback, useEffect, useRef } from 'react';
import { useApi } from '../api/context';
import { compileTypstClient, uint8ArrayToBase64, downloadPdfBlob } from '../services/typstWorkerClient';

export function useStudio({ user, activeTab, addToast }) {
  const api = useApi();
  const [documents, setDocuments] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [activeDocId, setActiveDocId] = useState(null);
  const [activeDoc, setActiveDoc] = useState(null);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [draftContent, setDraftContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [aiEditing, setAiEditing] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [autosaveError, setAutosaveError] = useState(false);

  const activeIdRef = useRef(null);
  const draftRef = useRef('');
  draftRef.current = draftContent;
  const loadSequenceRef = useRef(0);
  const autosaveTimerRef = useRef(null);
  const autosaveInFlightRef = useRef(false);
  const autosavePendingRef = useRef(null);
  const [autosaveTick, setAutosaveTick] = useState(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeIdRef.current = null;
      loadSequenceRef.current += 1;
      autosavePendingRef.current = null;
      clearTimeout(autosaveTimerRef.current);
    };
  }, []);

  const isDirty = activeDoc ? draftContent !== activeDoc.content : false;

  const fetchDocuments = useCallback(async () => {
    if (!user?.username) return [];
    setLoadingDocs(true);
    try {
      const res = await api.get('/documents');
      const docs = res.data?.documents || [];
      setDocuments(docs);
      return docs;
    } catch {
      addToast('Failed to load documents library.', 'error');
      return [];
    } finally {
      setLoadingDocs(false);
    }
  }, [user?.username, api, addToast]);

  const fetchTemplates = useCallback(async () => {
    if (!user?.username) return [];
    try {
      const res = await api.get('/documents/templates');
      const tmpls = res.data?.templates || [];
      setTemplates(tmpls);
      return tmpls;
    } catch {
      return [];
    }
  }, [api, user?.username]);

  const selectDocument = useCallback(async (id) => {
    if (!mountedRef.current) return;
    const pending = autosavePendingRef.current;
    if (pending && pending.id !== id) {
      try {
        await api.put(`/documents/${pending.id}`, { content: pending.content, expected_source_hash: pending.expected_source_hash });
        autosavePendingRef.current = null;
      } catch {
        setAutosaveError(true);
        addToast('The current draft could not be saved. Stay here and save or reload before switching.', 'error');
        return;
      }
    }
    const sequence = ++loadSequenceRef.current;
    activeIdRef.current = id;
    if (!id) {
      setActiveDocId(null);
      setActiveDoc(null);
      setDraftContent('');
      return;
    }
    setLoadingDoc(true);
    try {
      const res = await api.get(`/documents/${id}`);
      if (sequence !== loadSequenceRef.current) return;
      setActiveDocId(id);
      setActiveDoc(res.data);
      setDraftContent(res.data.content || '');
    } catch {
      addToast('Failed to load document.', 'error');
    } finally {
      if (sequence === loadSequenceRef.current) setLoadingDoc(false);
    }
  }, [addToast, api]);

  const createDocument = useCallback(async ({ title, doc_type = 'cv', engine = null, template_source = null, content = null }) => {
    setSaving(true);
    try {
      const res = await api.post('/documents', { title, doc_type, engine, template_source, content });
      if (!mountedRef.current) return null;
      addToast(`Created "${title}".`, 'success');
      await fetchDocuments();
      if (!mountedRef.current) return null;
      activeIdRef.current = res.data.id;
      setActiveDocId(res.data.id);
      setActiveDoc(res.data);
      setDraftContent(res.data.content || '');
      return res.data;
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to create document.';
      addToast(msg, 'error');
      return null;
    } finally {
      setSaving(false);
    }
  }, [addToast, api, fetchDocuments]);

  const saveDocument = useCallback(async (newTitle = null, opts = {}) => {
    if (!activeDocId) return false;
    setSaving(true);
    try {
      const savedId = activeDocId;
      const payload = { content: draftContent, expected_source_hash: activeDoc?.source_hash };
      let compilationError = null;
      if (newTitle) payload.title = newTitle;

      // If Typst, compile PDF in WebAssembly client-side to sync fresh PDF to disk
      if (activeDoc?.engine === 'typst') {
        try {
          const pdfRes = await compileTypstClient(draftContent, 'pdf');
          if (pdfRes?.result) {
            payload.pdf_base64 = uint8ArrayToBase64(pdfRes.result);
          }
        } catch (pdfErr) {
          compilationError = pdfErr;
        }
      }

      if (activeIdRef.current !== savedId) return false;
      const res = await api.put(`/documents/${activeDocId}`, payload);
      if (activeIdRef.current !== savedId) return true;
      setActiveDoc((prev) => ({
        ...prev,
        source_hash: res.data.source_hash,
        pdf_current: res.data.pdf_current,
        error: compilationError ? { message: compilationError.message } : null,
        content: draftContent,
        title: newTitle || prev.title,
        updated_at: res.data?.updated_at || prev.updated_at,
        has_pdf: payload.pdf_base64 ? true : prev?.has_pdf,
        pdf_url: payload.pdf_base64
          ? `/api/download/documents/${activeDocId}/document.pdf?v=${Date.now()}`
          : prev?.pdf_url,
      }));
      setAutosaveError(Boolean(compilationError));
      if (!opts.silent) addToast('Document saved to disk.', 'success');
      fetchDocuments();
      return true;
    } catch {
      setAutosaveError(true);
      addToast('Failed to save document.', 'error');
      return false;
    } finally {
      setSaving(false);
    }
  }, [activeDocId, draftContent, activeDoc?.source_hash, activeDoc?.engine, api, addToast, fetchDocuments]);

  // Debounced auto-save for Typst documents: the client-side WASM already keeps the
  // preview live, so persisting the content + PDF ~1.2s after the last keystroke lets
  // us drop the manual Compile/Save buttons. Falls back to showing them if saving fails.
  useEffect(() => {
    if (activeDoc?.engine !== 'typst') return;
    if (!activeDocId || !activeDoc || aiEditing) return;
    if (draftContent === activeDoc.content) return;
    if (autosaveInFlightRef.current) return;
    clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(async () => {
      autosaveInFlightRef.current = true;
      try {
        const ok = await saveDocument(null, { silent: true });
        if (ok) setAutosaveTick((t) => t + 1);
      } finally {
        autosaveInFlightRef.current = false;
      }
    }, 1200);
    return () => clearTimeout(autosaveTimerRef.current);
  }, [draftContent, activeDoc, activeDocId, aiEditing, saveDocument, autosaveTick]);

  // Remember unsaved Typst content so a document switch can flush it before the draft is replaced.
  useEffect(() => {
    if (activeDoc?.engine === 'typst' && activeDocId && draftContent !== activeDoc.content) {
      autosavePendingRef.current = { id: activeDocId, content: draftContent, expected_source_hash: activeDoc.source_hash };
    } else if (autosavePendingRef.current?.id === activeDocId) {
      autosavePendingRef.current = null;
    }
  }, [activeDoc, activeDocId, draftContent]);

  const compileDocument = useCallback(async () => {
    if (!activeDocId) return false;
    setCompiling(true);
    try {
      let pdfBase64 = null;
      if (activeDoc?.engine === 'typst') {
        try {
          const pdfRes = await compileTypstClient(draftContent, 'pdf');
          if (pdfRes?.result) {
            pdfBase64 = uint8ArrayToBase64(pdfRes.result);
          }
        } catch (wasmErr) {
          const rawMsg = wasmErr?.message || String(wasmErr);
          const cleanMsg = rawMsg.replace(/\[SourceDiagnostic\s*\{[^}]*message:\s*"([^"]+)"[^}]*\}\]/g, '$1');
          setActiveDoc((prev) => ({
            ...prev,
            error: { message: cleanMsg, raw: rawMsg },
          }));
          addToast(cleanMsg || 'Typst compilation error.', 'error');
          return false;
        }
      }

      const requestId = activeDocId;
      if (activeIdRef.current !== requestId) return false;
      const res = await api.post(`/documents/${requestId}/compile`, {
        expected_source_hash: activeDoc?.source_hash,
        content: draftContent,
        pdf_base64: pdfBase64,
      });

      if (activeIdRef.current !== requestId || draftRef.current !== draftContent) return false;
      if (res.data.success) {
        setActiveDoc((prev) => ({
          ...prev,
          source_hash: res.data.source_hash,
          pdf_current: res.data.pdf_current,
          content: draftContent,
          has_pdf: true,
          pdf_url: res.data.pdf_url,
          preview_urls: res.data.preview_urls,
          error: null,
        }));
        addToast(
          activeDoc?.engine === 'typst'
            ? 'Document compiled with Typst WASM!'
            : 'Document compiled successfully!',
          'success'
        );
        fetchDocuments();
        return true;
      } else {
        setActiveDoc((prev) => ({
          ...prev,
          error: res.data.error,
        }));
        addToast(res.data.error?.message || 'Compilation failed.', 'error');
        return false;
      }
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to compile document.';
      addToast(msg, 'error');
      return false;
    } finally {
      setCompiling(false);
    }
  }, [activeDocId, activeDoc?.engine, activeDoc?.source_hash, api, draftContent, addToast, fetchDocuments]);

  const downloadTypstPdf = useCallback(async (title = null) => {
    if (!draftContent) return;
    try {
      const pdfRes = await compileTypstClient(draftContent, 'pdf');
      if (pdfRes?.result) {
        const fn = (title || activeDoc?.title || 'document').replace(/[/\\?%*:|"<>]/g, '_');
        downloadPdfBlob(pdfRes.result, fn);
        addToast('Downloaded instant Typst PDF.', 'success');
      }
    } catch (err) {
      addToast('Failed to compile client-side PDF: ' + (err.message || err), 'error');
    }
  }, [draftContent, activeDoc?.title, addToast]);

  const aiEditDocument = useCallback(async (instruction, selection = null) => {
    if (!activeDocId || !instruction?.trim()) return false;
    setAiEditing(true);
    try {
      const requestId = activeDocId;
      const res = await api.post(`/documents/${requestId}/ai-edit`, {
        instruction,
        selection,
        content: draftContent,
        expected_source_hash: activeDoc?.source_hash,
      });
      if (activeIdRef.current !== requestId || draftRef.current !== draftContent) return false;
      if (res.data.success) {
        setDraftContent(res.data.content);
        setActiveDoc((prev) => ({
          ...prev,
          content: res.data.content,
          source_hash: res.data.source_hash,
          pdf_current: res.data.pdf_current,
          has_pdf: res.data.has_pdf,
          pdf_url: res.data.pdf_url,
          preview_urls: res.data.preview_urls,
          error: res.data.error,
        }));
        if (res.data.error) {
          addToast('AI applied edits, but compilation had warnings/errors.', 'warning');
        } else {
          addToast('AI edits applied and compiled!', 'success');
        }
        fetchDocuments();
        return true;
      } else {
        addToast(res.data.message || 'AI edit failed.', 'error');
        return false;
      }
    } catch (err) {
      const msg = err.response?.data?.detail || 'AI edit failed.';
      addToast(msg, 'error');
      return false;
    } finally {
      setAiEditing(false);
    }
  }, [activeDocId, api, draftContent, activeDoc?.source_hash, fetchDocuments, addToast]);

  const deleteDocument = useCallback(async (id) => {
    if (!id) return false;
    try {
      await api.delete(`/documents/${id}`);
      addToast('Document deleted.', 'info');
      const docs = await fetchDocuments();
      if (activeDocId === id) {
        if (docs && docs.length > 0) {
          await selectDocument(docs[0].id);
        } else {
          setActiveDocId(null);
          setActiveDoc(null);
          setDraftContent('');
        }
      }
      return true;
    } catch {
      addToast('Failed to delete document.', 'error');
      return false;
    }
  }, [activeDocId, addToast, api, fetchDocuments, selectDocument]);

  // Load documents and templates on auth or when navigating to studio
  useEffect(() => {
    if (!user?.username) return;
    fetchTemplates();
    fetchDocuments().then((docs) => {
      if (mountedRef.current && docs && docs.length > 0) {
        setActiveDocId((currId) => {
          if (!currId) {
            selectDocument(docs[0].id);
          }
          return currId;
        });
      }
    });
  }, [user?.username, activeTab, fetchDocuments, fetchTemplates, selectDocument]);

  return {
    documents,
    loadingDocs,
    templates,
    fetchTemplates,
    activeDocId,
    activeDoc,
    loadingDoc,
    draftContent,
    setDraftContent,
    isDirty,
    saving,
    autosaveError,
    compiling,
    aiEditing,
    zoom,
    setZoom,
    fetchDocuments,
    selectDocument,
    createDocument,
    saveDocument,
    compileDocument,
    downloadTypstPdf,
    aiEditDocument,
    deleteDocument,
    addToast,
  };
}
