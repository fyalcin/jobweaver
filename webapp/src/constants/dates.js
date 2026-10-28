/**
 * Formats a date string (YYYY-MM-DD...) as DD.MM.YYYY.
 * If input is empty or invalid, returns fallback or original string.
 */
export function formatDateDisplay(dateStr, fallback = '-') {
  if (!dateStr || dateStr === '-' || dateStr === '—') return fallback;
  const m = String(dateStr).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    const [, yyyy, mm, dd] = m;
    return `${dd}.${mm}.${yyyy}`;
  }
  return dateStr;
}

export function formatDateTimeDisplay(ts, fallback = '-') {
  if (!ts || ts === '-' || ts === '—') return fallback;
  const m = String(ts).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (m) {
    const [, yyyy, mm, dd, hh, min] = m;
    return `${dd}.${mm}.${yyyy}, ${hh}:${min}`;
  }
  return formatDateDisplay(ts, fallback);
}
