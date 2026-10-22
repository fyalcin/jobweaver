import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';

export const THEMES = [
  {
    id: 'default',
    name: 'Modern Dark',
    desc: 'Deep zinc & indigo default',
    type: 'dark',
    colors: ['#09090b', '#18181b', '#6366f1', '#fafafa'],
  },
  {
    id: 'kanagawa-wave',
    name: 'Kanagawa Wave',
    desc: 'Sumi ink & crystal blue',
    type: 'dark',
    colors: ['#1f1f28', '#2a2a37', '#7e9cd8', '#dcd7ba'],
  },
  {
    id: 'kanagawa-dragon',
    name: 'Kanagawa Dragon',
    desc: 'Dark earthy moss & dragon aqua',
    type: 'dark',
    colors: ['#181616', '#221f1f', '#8ba4b0', '#c5c9c5'],
  },
  {
    id: 'kanagawa-lotus',
    name: 'Kanagawa Lotus',
    desc: 'Warm paper & soft lotus violet',
    type: 'light',
    colors: ['#f2ecde', '#e7dece', '#5d57a0', '#545464'],
  },
  {
    id: 'catppuccin-mocha',
    name: 'Catppuccin Mocha',
    desc: 'Soothing dark pastel with mauve',
    type: 'dark',
    colors: ['#1e1e2e', '#25253a', '#cba6f7', '#cdd6f4'],
  },
  {
    id: 'catppuccin-latte',
    name: 'Catppuccin Latte',
    desc: 'Warm soothing light pastel',
    type: 'light',
    colors: ['#eff1f5', '#e6e9ef', '#8839ef', '#4c4f69'],
  },
  {
    id: 'rose-pine',
    name: 'Rosé Pine',
    desc: 'Warm dusky night & pastel rose',
    type: 'dark',
    colors: ['#191724', '#26233a', '#ebbcba', '#e0def4'],
  },
  {
    id: 'nord',
    name: 'Nord Frost',
    desc: 'Arctic polar night & ice cyan',
    type: 'dark',
    colors: ['#242933', '#3b4252', '#88c0d0', '#eceff4'],
  },
  {
    id: 'aurora',
    name: 'Aurora',
    desc: 'Frosted indigo glass with violet glow',
    type: 'dark',
    colors: ['#08080f', '#13131f', '#6366f1', '#a5b4fc'],
  },
  {
    id: 'ember',
    name: 'Ember',
    desc: 'Toasted charcoal with amber & rose warmth',
    type: 'dark',
    colors: ['#100c09', '#1d1712', '#f59e0b', '#fb7185'],
  },
  {
    id: 'neon',
    name: 'Neon',
    desc: 'Cyber cyan & magenta on a near-black grid',
    type: 'dark',
    colors: ['#05070b', '#0a1017', '#22d3ee', '#d946ef'],
  },
  {
    id: 'aurora-ember',
    name: 'Aurora Ember',
    desc: 'Aurora glass with warm ember accents',
    type: 'dark',
    colors: ['#0b0a10', '#17141f', '#f59e0b', '#fb7185'],
  },
  {
    id: 'aurora-neon',
    name: 'Aurora Neon',
    desc: 'Aurora glass with cyan neon accents',
    type: 'dark',
    colors: ['#07070f', '#12121f', '#22d3ee', '#d946ef'],
  },
  {
    id: 'amber-neon',
    name: 'Amber Neon',
    desc: 'Amber warmth fused with cyan neon',
    type: 'dark',
    colors: ['#08090b', '#121316', '#f59e0b', '#22d3ee'],
  },
];

export const FONTS = [
  {
    id: 'inter',
    name: 'Inter',
    creator: 'Rasmus Andersson',
    desc: 'The gold standard of UI typography — crisp legibility and balanced screen rhythm.',
    sample: 'Designed for computer screens. The quick brown fox jumps over 123.',
  },
  {
    id: 'geist',
    name: 'Geist',
    creator: 'Vercel & Basement Studio',
    desc: 'Precision engineered for developer tools, technical dashboards, and sharp modern UI.',
    sample: 'Precision engineered for builders. The quick brown fox jumps over 123.',
  },
  {
    id: 'plus-jakarta-sans',
    name: 'Plus Jakarta Sans',
    creator: 'Tokotype',
    desc: 'Contemporary geometric sans with warm humanist curves and engaging character.',
    sample: 'Friendly yet authoritative. The quick brown fox jumps over 123.',
  },
  {
    id: 'dm-sans',
    name: 'DM Sans',
    creator: 'Colophon Foundry',
    desc: 'Low-contrast geometric grotesque crafted for exceptional clarity at compact sizes.',
    sample: 'Geometric clarity at every size. The quick brown fox jumps over 123.',
  },
  {
    id: 'ibm-plex-sans',
    name: 'IBM Plex Sans',
    creator: 'IBM / Mike Abbink',
    desc: 'Distinctive industrial grotesque balancing Swiss rationality with humanist warmth.',
    sample: 'Engineered corporate precision. The quick brown fox jumps over 123.',
  },
  {
    id: 'manrope',
    name: 'Manrope',
    creator: 'Mikhail Sharanda',
    desc: 'Modern semi-geometric sans with rounded elegance, widely favored in fintech and SaaS.',
    sample: 'Sleek, rounded modern rhythm. The quick brown fox jumps over 123.',
  },
];

export function usePreferences({ user, addToast, demo = false }) {
  const [theme, setThemeState] = useState(() => {
    if (user?.username) {
      return localStorage.getItem(`gj_theme_${user.username}`) || localStorage.getItem('gj_active_theme') || 'default';
    }
    return localStorage.getItem('gj_active_theme') || 'default';
  });

  const [font, setFontState] = useState(() => {
    if (user?.username) {
      return localStorage.getItem(`gj_font_${user.username}`) || localStorage.getItem('gj_active_font') || 'inter';
    }
    return localStorage.getItem('gj_active_font') || 'inter';
  });

  const [savingTheme, setSavingTheme] = useState(false);
  const [savingFont, setSavingFont] = useState(false);

  // Apply theme to DOM and localStorage
  const applyTheme = useCallback((themeId) => {
    if (themeId && themeId !== 'default') {
      document.documentElement.setAttribute('data-theme', themeId);
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('gj_active_theme', themeId || 'default');
    if (user?.username) {
      localStorage.setItem(`gj_theme_${user.username}`, themeId || 'default');
    }
  }, [user?.username]);

  // Apply font to DOM and localStorage
  const applyFont = useCallback((fontId) => {
    if (fontId && fontId !== 'inter') {
      document.documentElement.setAttribute('data-font', fontId);
    } else {
      document.documentElement.removeAttribute('data-font');
    }
    localStorage.setItem('gj_active_font', fontId || 'inter');
    if (user?.username) {
      localStorage.setItem(`gj_font_${user.username}`, fontId || 'inter');
    }
  }, [user?.username]);

  // Load preferences from server when user changes
  useEffect(() => {
    if (!user?.username) return;

    // Apply local cache immediately
    const cachedTheme = localStorage.getItem(`gj_theme_${user.username}`);
    if (cachedTheme) {
      setThemeState(cachedTheme);
      applyTheme(cachedTheme);
    }
    const cachedFont = localStorage.getItem(`gj_font_${user.username}`);
    if (cachedFont) {
      setFontState(cachedFont);
      applyFont(cachedFont);
    }

    // Then fetch persisted preferences from server
    api.get('/preferences')
      .then((res) => {
        const serverTheme = res.data?.theme || 'default';
        const serverFont = res.data?.font || 'inter';
        setThemeState(serverTheme);
        applyTheme(serverTheme);
        setFontState(serverFont);
        applyFont(serverFont);
      })
      .catch((err) => {
        console.warn('Failed to load UI preferences:', err);
      });
  }, [user?.username, applyTheme, applyFont]);

  // Save new theme
  const setTheme = useCallback(async (newTheme) => {
    if (!THEMES.some((t) => t.id === newTheme)) {
      newTheme = 'default';
    }

    setThemeState(newTheme);
    applyTheme(newTheme);

    if (!user?.username) return;

    setSavingTheme(true);
    try {
      if (!demo) await api.put('/preferences', { theme: newTheme, font });
      if (addToast) {
        const themeObj = THEMES.find((t) => t.id === newTheme);
        addToast(`Theme set to ${themeObj?.name || newTheme}`, 'success');
      }
    } catch (err) {
      console.error('Failed to save UI preferences:', err);
      if (addToast) {
        addToast('Failed to save theme preference to server.', 'error');
      }
    } finally {
      setSavingTheme(false);
    }
  }, [user?.username, font, applyTheme, addToast, demo]);

  // Save new font
  const setFont = useCallback(async (newFont) => {
    if (!FONTS.some((f) => f.id === newFont)) {
      newFont = 'inter';
    }

    setFontState(newFont);
    applyFont(newFont);

    if (!user?.username) return;

    setSavingFont(true);
    try {
      if (!demo) await api.put('/preferences', { theme, font: newFont });
      if (addToast) {
        const fontObj = FONTS.find((f) => f.id === newFont);
        addToast(`Font set to ${fontObj?.name || newFont}`, 'success');
      }
    } catch (err) {
      console.error('Failed to save font preference:', err);
      if (addToast) {
        addToast('Failed to save font preference to server.', 'error');
      }
    } finally {
      setSavingFont(false);
    }
  }, [user?.username, theme, applyFont, addToast, demo]);

  return {
    theme,
    setTheme,
    savingTheme,
    themes: THEMES,
    font,
    setFont,
    savingFont,
    fonts: FONTS,
  };
}
