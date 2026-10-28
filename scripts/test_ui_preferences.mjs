import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  THEMES, FONTS, normalizeTheme, normalizeFont, applyPreferences,
} from '../webapp/src/preferences.js';

const bootstrap = fs.readFileSync('webapp/index.html', 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const retired = ['aurora', 'ember', 'neon', 'aurora-ember', 'aurora-neon', 'amber-neon'];
const previousDocument = globalThis.document;
const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
const storage = new Map();
const attributes = {};
const root = { style: {}, setAttribute: (key, value) => { attributes[key] = value; } };
globalThis.document = { documentElement: root };
Object.defineProperty(globalThis, 'localStorage', { configurable: true, writable: true, value: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) } });

try {
  assert.equal(normalizeTheme(), 'loden-light');
  assert.equal(normalizeTheme('default'), 'loden-light');
  assert.equal(normalizeTheme('unrecognized'), 'loden-light');
  assert.equal(normalizeFont(), 'fira-sans');
  assert.equal(normalizeFont('inter'), 'inter');
  assert.equal(THEMES.length, 9);
  for (const theme of THEMES) {
    applyPreferences(theme.id, 'geist', 'fictional');
    assert.equal(attributes['data-theme'], theme.id);
    assert.equal(root.style.colorScheme, theme.type);
    assert.equal(storage.get('gj_theme_fictional'), theme.id);
    assert.equal(storage.get('gj_font_fictional'), 'geist');
    new Function('localStorage', 'document', bootstrap)(globalThis.localStorage, globalThis.document);
    assert.equal(attributes['data-theme'], theme.id);
    assert.equal(attributes['data-font'], 'geist');
    assert.equal(root.style.colorScheme, theme.type);
  }
  for (const font of FONTS) assert.equal(normalizeFont(font.id), font.id);
  for (const old of ['default', ...retired, 'unrecognized']) {
    storage.set('gj_active_theme', old);
    new Function('localStorage', 'document', bootstrap)(globalThis.localStorage, globalThis.document);
    assert.equal(attributes['data-theme'], normalizeTheme(old));
  }
  const css = fs.readFileSync('webapp/src/index.css', 'utf8');
  for (const old of retired) {
    assert(!THEMES.some(t => t.id === old));
    assert(!css.includes(`[data-theme="${old}"]`));
  }
  assert(!fs.existsSync('webapp/src/themes.css'));
  assert(!fs.existsSync('scripts/gen_themes.py'));
  assert(css.includes('color-scheme: light'));
  assert(css.includes('color-scheme: dark'));

  // Exercise the real preference hook: demo choices survive reload, account cache
  // stays separate, and a late initial GET cannot undo a newly chosen appearance.
  const hookText = fs.readFileSync('webapp/src/hooks/usePreferences.js', 'utf8')
    .replace(/^import .*;$/gm, '').replace('export function usePreferences', 'function usePreferences');
  function mount({ demo = false, username = 'fictional' } = {}) {
    const slots = []; let cursor = 0, effects = [], resolveGet;
    const writes = [];
    const api = {
      get: () => new Promise(resolve => { resolveGet = resolve; }),
      put: async (_, value) => { writes.push(value); },
    };
    const useState = initial => {
      const n = cursor++;
      if (!(n in slots)) slots[n] = typeof initial === 'function' ? initial() : initial;
      return [slots[n], value => { slots[n] = value; }];
    };
    const useRef = initial => {
      const n = cursor++;
      if (!(n in slots)) slots[n] = { current: initial };
      return slots[n];
    };
    const useEffect = (fn, deps) => {
      const n = cursor++;
      if (!slots[n] || deps.some((dep, i) => dep !== slots[n][i])) effects.push(fn);
      slots[n] = deps;
    };
    const useHook = new Function('useState', 'useEffect', 'useCallback', 'useRef', 'useApi',
      'THEMES', 'FONTS', 'normalizeTheme', 'normalizeFont', 'readPreference', 'applyPreferences',
      hookText + '\nreturn usePreferences;')(
      useState, useEffect, fn => fn, useRef, () => api, THEMES, FONTS,
      normalizeTheme, normalizeFont, key => storage.get(key), applyPreferences);
    return {
      writes,
      resolve: value => resolveGet({ data: value }),
      render: () => {
        cursor = 0; effects = [];
        const result = useHook({ user: { username }, demo });
        effects.forEach(fn => fn());
        return result;
      },
    };
  }
  storage.clear();
  let mounted = mount({ demo: true });
  let prefs = mounted.render();
  assert.equal(prefs.theme, 'loden-light');
  assert.equal(prefs.font, 'fira-sans');
  await prefs.setTheme('loden-dark');
  mounted = mount({ demo: true });
  prefs = mounted.render();
  assert.equal(prefs.theme, 'loden-dark');
  assert.equal(mounted.writes.length, 0);
  storage.set('gj_theme_other', 'kanagawa-lotus');
  assert.equal(mount({ username: 'other', demo: true }).render().theme, 'kanagawa-lotus');
  mounted = mount(); prefs = mounted.render();
  await prefs.setTheme('catppuccin-latte');
  mounted.resolve({ theme: 'kanagawa-wave', font: 'inter' });
  await Promise.resolve();
  assert.equal(mounted.render().theme, 'catppuccin-latte');
  assert.equal(mounted.render().font, 'inter');
  assert.deepEqual(mounted.writes, [{ theme: 'catppuccin-latte' }]);
  mounted = mount(); prefs = mounted.render();
  await prefs.setFont('geist');
  mounted.resolve({ theme: 'kanagawa-wave', font: 'inter' });
  await Promise.resolve();
  assert.equal(mounted.render().theme, 'kanagawa-wave');
  assert.equal(mounted.render().font, 'geist');
  assert.deepEqual(mounted.writes, [{ font: 'geist' }]);
  mounted = mount(); mounted.render();
  mounted.resolve({ theme: 'aurora', font: 'inter' });
  await Promise.resolve();
  prefs = mounted.render();
  assert.equal(prefs.theme, 'loden-dark');
  assert.equal(prefs.font, 'inter');
  await prefs.setTheme('loden-light');
  prefs = mounted.render();
  await prefs.setTheme('loden-dark');
  assert.equal(mounted.render().theme, 'loden-dark');
  assert.equal(storage.get('gj_theme_fictional'), 'loden-dark');
  globalThis.localStorage = { getItem: () => { throw Error('blocked'); }, setItem: () => { throw Error('blocked'); } };
  assert.doesNotThrow(() => applyPreferences('loden-light', 'fira-sans'));
  console.log('Appearance regressions passed: bootstrap, palette/font retention, migration, persistence, toggle, demo reload and load races.');
} finally {
  globalThis.document = previousDocument;
  if (previousStorage) Object.defineProperty(globalThis, 'localStorage', previousStorage);
  else delete globalThis.localStorage;
}
