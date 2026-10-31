export function sectionOpenKey(section, idx) {
  return `sec-${idx}-${section?.title || ''}`;
}

export function allSectionsOpen(data, kind) {
  if (!data) return { basics: true };
  const isLetter = kind === 'cover-letter' || data.kind === 'letter' || (!data.sections && Array.isArray(data.paragraphs));
  if (isLetter) {
    return { basics: true, recipient: true, paragraphs: true };
  }
  const next = { basics: true };
  (data.sections || []).forEach((sec, idx) => {
    next[sectionOpenKey(sec, idx)] = true;
  });
  return next;
}
