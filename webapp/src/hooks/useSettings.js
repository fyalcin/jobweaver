import { useState, useCallback } from 'react';
import { api } from '../api/client';

export function useSettings({ addToast }) {
  const [aiModel, setAiModel] = useState('');
  const [aiTone, setAiTone] = useState('');
  const [scraperConfig, setScraperConfig] = useState(null);
  const [savingConfig, setSavingConfig] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await api.get('/config');
      setScraperConfig(res.data);
      if (res.data.openrouter_model) setAiModel(res.data.openrouter_model);
      if (res.data.auto_generate?.tone) setAiTone(res.data.auto_generate.tone);
    } catch {
      addToast('Failed to load scraper config.', 'error');
    }
  }, [addToast]);

  const saveConfig = useCallback(async (patch) => {
    setSavingConfig(true);
    try {
      const updated = { ...scraperConfig, ...patch };
      await api.put('/config', updated);
      setScraperConfig(updated);
      addToast('Configuration saved.', 'success');
    } catch {
      addToast('Failed to save configuration.', 'error');
    } finally {
      setSavingConfig(false);
    }
  }, [scraperConfig, addToast]);

  return {
    aiModel, setAiModel,
    aiTone, setAiTone,
    scraperConfig, setScraperConfig,
    savingConfig, fetchConfig, saveConfig
  };
}
