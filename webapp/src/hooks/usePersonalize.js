import { useState, useCallback } from 'react';
import { api } from '../api/client';

export function usePersonalize({ addToast }) {
  const [cv, setCv] = useState(null); // { content, exists, loaded_from, save_path }
  const [cvVersion, setCvVersion] = useState(0); // increments whenever disk truth changes
  const [cvLoaded, setCvLoaded] = useState(false);
  const [loadingCv, setLoadingCv] = useState(false);
  const [savingCv, setSavingCv] = useState(false);

  const fetchCv = useCallback(async () => {
    setLoadingCv(true);
    try {
      const res = await api.get('/cv');
      setCv(res.data);
      setCvVersion((v) => v + 1);
      setCvLoaded(true);
    } catch {
      addToast('Failed to load your CV from disk.', 'error');
    } finally {
      setLoadingCv(false);
    }
  }, [addToast]);

  const saveCv = useCallback(async (content) => {
    setSavingCv(true);
    try {
      const res = await api.put('/cv', { content });
      setCv((c) => ({
        ...(c || {}),
        content,
        exists: true,
        loaded_from: res.data?.save_path || c?.save_path,
        save_path: res.data?.save_path || c?.save_path,
      }));
      setCvVersion((v) => v + 1);
      addToast('CV saved to disk.', 'success');
      return true;
    } catch (err) {
      addToast(err?.response?.data?.detail || 'Failed to save your CV.', 'error');
      return false;
    } finally {
      setSavingCv(false);
    }
  }, [addToast]);

  const [notes, setNotes] = useState(null); // { notes, exists, loaded_from, save_path }
  const [notesVersion, setNotesVersion] = useState(0);
  const [notesLoaded, setNotesLoaded] = useState(false);
  const [loadingNotes, setLoadingNotes] = useState(false);
  const [savingNotes, setSavingNotes] = useState(false);

  const fetchNotes = useCallback(async () => {
    setLoadingNotes(true);
    try {
      const res = await api.get('/profile/notes');
      setNotes(res.data);
      setNotesVersion((v) => v + 1);
      setNotesLoaded(true);
    } catch {
      addToast('Failed to load standing notes.', 'error');
    } finally {
      setLoadingNotes(false);
    }
  }, [addToast]);

  const saveNotes = useCallback(async (notesText) => {
    setSavingNotes(true);
    try {
      const res = await api.put('/profile/notes', { notes: notesText });
      setNotes((prev) => ({
        ...(prev || {}),
        notes: notesText,
        exists: true,
        loaded_from: res.data?.save_path || prev?.save_path,
        save_path: res.data?.save_path || prev?.save_path,
      }));
      setNotesVersion((v) => v + 1);
      addToast('Standing notes saved to disk.', 'success');
      return true;
    } catch {
      addToast('Failed to save standing notes.', 'error');
      return false;
    } finally {
      setSavingNotes(false);
    }
  }, [addToast]);

  return {
    cv,
    cvVersion,
    cvLoaded,
    loadingCv,
    savingCv,
    fetchCv,
    saveCv,
    notes,
    notesVersion,
    notesLoaded,
    loadingNotes,
    savingNotes,
    fetchNotes,
    saveNotes,
  };
}
