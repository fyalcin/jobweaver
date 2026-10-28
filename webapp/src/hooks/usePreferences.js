import { useState, useEffect, useCallback, useRef } from 'react';
import { useApi } from '../api/context';
import { THEMES, FONTS, normalizeTheme, normalizeFont, readPreference, applyPreferences } from '../preferences';

export function usePreferences({ user, addToast, demo = false }) {
  const api = useApi();
  const username = user?.username;
  const [theme, setThemeState] = useState(() => normalizeTheme(
    (username && readPreference(`gj_theme_${username}`)) || readPreference('gj_active_theme')));
  const [font, setFontState] = useState(() => normalizeFont(
    (username && readPreference(`gj_font_${username}`)) || readPreference('gj_active_font')));
  const [savingTheme, setSavingTheme] = useState(false);
  const [savingFont, setSavingFont] = useState(false);
  // A late server response must not replace a choice made while it was loading.
  const revision = useRef({ theme: 0, font: 0 });

  useEffect(() => {
    applyPreferences(theme, font, username);
  }, [theme, font, username]);

  useEffect(() => {
    if (!username || demo) return;
    let active = true;
    const started = { ...revision.current };
    api.get('/preferences').then(res => {
      if (!active) return;
      if (revision.current.theme === started.theme) setThemeState(normalizeTheme(res.data?.theme));
      if (revision.current.font === started.font) setFontState(normalizeFont(res.data?.font));
    }).catch(err => { console.warn('Failed to load UI preferences:', err); });
    return () => { active = false; };
  }, [username, demo, api]);

  const setTheme = useCallback(async value => {
    const next = normalizeTheme(value);
    revision.current.theme += 1;
    setThemeState(next);
    applyPreferences(next, font, username);
    if (!username || demo) return;
    setSavingTheme(true);
    try {
      await api.put('/preferences', { theme: next });
    } catch {
      addToast?.('Failed to save theme preference to server.', 'error');
    } finally { setSavingTheme(false); }
  }, [username, demo, api, font, addToast]);

  const setFont = useCallback(async value => {
    const next = normalizeFont(value);
    revision.current.font += 1;
    setFontState(next);
    applyPreferences(theme, next, username);
    if (!username || demo) return;
    setSavingFont(true);
    try {
      await api.put('/preferences', { font: next });
    } catch {
      addToast?.('Failed to save font preference to server.', 'error');
    } finally { setSavingFont(false); }
  }, [username, demo, api, theme, addToast]);

  return { theme, setTheme, savingTheme, themes: THEMES, font, setFont, savingFont, fonts: FONTS };
}
