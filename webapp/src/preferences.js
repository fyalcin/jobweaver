export const THEMES = [
  {
    id: 'loden-light', name: 'Loden Light', desc: 'Loden green on quiet paper',
    type: 'light', colors: ['#fdfdfb', '#f3f3ef', '#3d5a47', '#1f231f'],
  },
  {
    id: 'loden-dark', name: 'Loden Dark', desc: 'Soft green on charcoal',
    type: 'dark', colors: ['#20241f', '#292e28', '#a4bda6', '#e8ece4'],
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
];

export const FONTS = [
  {
    id: 'fira-sans', name: 'Fira Sans', creator: 'Erik Spiekermann / Mozilla',
    desc: 'Humanist type with clear forms for dense screens.',
    sample: 'A considered fit. The quick brown fox jumps over 123.',
  },
  {
    id: 'inter',
    name: 'Inter',
    creator: 'Rasmus Andersson',
    desc: 'Neo-grotesque sans with tall x-height and open apertures for small text.',
    sample: 'Clear forms for dense tables. The quick brown fox jumps over 123.',
  },
  {
    id: 'geist',
    name: 'Geist',
    creator: 'Vercel & Basement Studio',
    desc: 'Straight-sided grotesque designed for code and interface labels.',
    sample: 'Compact labels and steady numbers. The quick brown fox jumps over 123.',
  },
  {
    id: 'plus-jakarta-sans',
    name: 'Plus Jakarta Sans',
    creator: 'Tokotype',
    desc: 'Geometric sans with open counters and warm proportions.',
    sample: 'Balanced headings and body text. The quick brown fox jumps over 123.',
  },
  {
    id: 'dm-sans',
    name: 'DM Sans',
    creator: 'Colophon Foundry',
    desc: 'Low-contrast geometric sans built for small interface sizes.',
    sample: 'Even weight across short lines. The quick brown fox jumps over 123.',
  },
  {
    id: 'ibm-plex-sans',
    name: 'IBM Plex Sans',
    creator: 'IBM / Mike Abbink',
    desc: 'Grotesque with squared stems and distinct character shapes.',
    sample: 'Distinct letterforms in long notes. The quick brown fox jumps over 123.',
  },
  {
    id: 'manrope',
    name: 'Manrope',
    creator: 'Mikhail Sharanda',
    desc: 'Semi-geometric sans with open terminals and wide figures.',
    sample: 'Open rhythm for long reading. The quick brown fox jumps over 123.',
  },
];

export const DEFAULT_THEME = 'loden-light';
export const DEFAULT_FONT = 'fira-sans';
const RETIRED_THEMES = new Set(['aurora', 'ember', 'neon', 'aurora-ember', 'aurora-neon', 'amber-neon']);

export function normalizeTheme(value) {
  const id = typeof value === 'string' ? value.trim().toLowerCase() : '';
  if (RETIRED_THEMES.has(id)) return 'loden-dark';
  return THEMES.some(theme => theme.id === id) ? id : DEFAULT_THEME;
}

export function normalizeFont(value) {
  const id = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return FONTS.some(font => font.id === id) ? id : DEFAULT_FONT;
}

export function readPreference(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

export function applyPreferences(theme, font, username) {
  const themeId = normalizeTheme(theme);
  const fontId = normalizeFont(font);
  document.documentElement.setAttribute('data-theme', themeId);
  document.documentElement.setAttribute('data-font', fontId);
  document.documentElement.style.colorScheme = THEMES.find(t => t.id === themeId).type;
  try {
    localStorage.setItem('gj_active_theme', themeId);
    localStorage.setItem('gj_active_font', fontId);
    if (username) {
      localStorage.setItem(`gj_theme_${username}`, themeId);
      localStorage.setItem(`gj_font_${username}`, fontId);
    }
  } catch { /* Browser storage can be unavailable; the current session still works. */ }
}
