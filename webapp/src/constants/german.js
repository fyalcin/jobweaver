export const GERMAN_LEVELS = ['none', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2', 'native', 'unknown'];

const ranks = Object.fromEntries(GERMAN_LEVELS.slice(0, -1).map((level, index) => [level, index]));

export function normalizeGermanLevel(value) {
  if (typeof value === 'boolean') return value ? 'unknown' : 'none';
  if (value == null) return 'unknown';
  const raw = String(value).trim();
  const lower = raw.toLowerCase();
  if (['false', 'no', 'not required'].includes(lower)) return 'none';
  if (['true', 'yes', 'required', ''].includes(lower)) return 'unknown';
  if (GERMAN_LEVELS.includes(raw)) return raw;
  if (['A1', 'A2', 'B1', 'B2', 'C1', 'C2'].includes(raw.toUpperCase())) return raw.toUpperCase();
  if (lower === 'native') return 'native';
  return 'unknown';
}

export function germanLevelCompatible(value, maxLevel = 'B1') {
  const level = normalizeGermanLevel(value);
  return level !== 'unknown' && ranks[level] !== undefined && ranks[level] <= ranks[maxLevel];
}

export function germanLevelLabel(value) {
  const level = normalizeGermanLevel(value);
  return level === 'none' ? 'Not required' : level === 'unknown' ? 'Unknown' : level;
}
