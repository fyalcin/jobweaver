import { normalizeGermanLevel } from './german.js';

// Labels come only from the evidence-based API contract. Legacy scores are never converted.
export const RATINGS = ['Great', 'Good', 'Decent', 'Stretch', 'Poor', 'Blocked'];
export const RATING_GROUPS = [...RATINGS, 'Needs re-rating', 'Unrated'];
export const RATING_DEFINITIONS = {
  Great: 'All must-haves supported, at most one indirectly; optional requirements also supported.',
  Good: 'Base: all must-haves supported, directly or through related experience.',
  Decent: 'Base: one missing must-have, at most a third of the requirements.',
  Stretch: 'Base: up to half of the must-haves missing.',
  Poor: 'More than half of the must-haves missing, or preference conflicts lowered the rating.',
  Blocked: 'An eligibility blocker or a firm preference prevents a match.',
  'Needs re-rating': 'Historical analysis or changed inputs. Re-rate to get current evidence.',
  Unrated: 'No checkable requirements, or analysis is pending or failed. Each row explains why.',
};
export const jobStatus = job => job.status || (job.applied ? 'applied' : 'new');
export const APPLIED_STATUSES = ['applied', 'interview', 'offer', 'rejected'];
export function matchesStage(job, stage) {
  if (stage === 'pipeline') return APPLIED_STATUSES.includes(jobStatus(job));
  if (stage === 'active') return ['new', 'interested'].includes(jobStatus(job));
  return stage === 'All' || jobStatus(job) === stage;
}
export function ratingLabel(job) {
  if (job.analysis_current === false) return 'Needs re-rating';
  if (job.match_rating === 'Unrated') return 'Unrated';
  if (RATINGS.includes(job.match_rating)) return job.match_rating;
  if (job.match_score != null || job.match_analysis || job.analysis_state === 'complete' || job.analysis_state === 'completed') return 'Needs re-rating';
  return 'Unrated';
}
export const ratingClass = job => `match-rating rating-${ratingLabel(job).toLowerCase().replaceAll(' ', '-')}`;
export const checksFor = job => Array.isArray(job.match_checks) ? job.match_checks : [];
export const conflictsFor = job => Array.isArray(job.preference_conflicts) ? job.preference_conflicts : [];
export function missingMustCount(job) {
  return checksFor(job).filter(c => c.importance === 'must' && c.coverage === 'missing').length;
}
export function compareBestFit(a, b) {
  return RATING_GROUPS.indexOf(ratingLabel(a)) - RATING_GROUPS.indexOf(ratingLabel(b)) ||
    missingMustCount(a) - missingMustCount(b) ||
    String(b.date_scraped || '').localeCompare(String(a.date_scraped || ''));
}
export function compareJobs(a, b, sort = { key: 'match_rating', direction: 'desc' }) {
  const group = RATING_GROUPS.indexOf(ratingLabel(a)) - RATING_GROUPS.indexOf(ratingLabel(b));
  if (group) return group;
  if (!sort.key || sort.key === 'match_rating') return compareBestFit(a, b);
  let av = a[sort.key], bv = b[sort.key];
  if (sort.key === 'salary_yearly') {
    const aKnown = av != null && Number.isFinite(Number(av));
    const bKnown = bv != null && Number.isFinite(Number(bv));
    if (aKnown !== bKnown) return aKnown ? -1 : 1;
    av = aKnown ? Number(av) : 0;
    bv = bKnown ? Number(bv) : 0;
  } else if (sort.key === 'german_level') {
    av = normalizeGermanLevel(av); bv = normalizeGermanLevel(bv);
  } else if (sort.key === 'date_scraped') {
    av = Date.parse(av) || 0; bv = Date.parse(bv) || 0;
  } else {
    av ??= ''; bv ??= '';
  }
  const order = av < bv ? -1 : av > bv ? 1 : 0;
  return (sort.direction === 'asc' ? order : -order) || compareBestFit(a, b);
}
export function matchesRating(job, minimum) {
  if (!minimum) return true;
  const rank = RATINGS.indexOf(ratingLabel(job));
  const threshold = RATINGS.indexOf(minimum);
  return threshold >= 0 && rank >= 0 && rank <= threshold;
}
export function ratingSummary(job) {
  const label = ratingLabel(job);
  if (label === 'Needs re-rating') return 'Re-rate: this analysis is historical or your inputs changed.';
  if (label === 'Unrated' && job.match_rating === 'Unrated') return 'Posting has no checkable requirements.';
  if (label === 'Unrated') return job.analysis_state === 'failed' ? `Analysis failed${job.analysis_error ? `: ${job.analysis_error}` : '. Retry analysis.'}` : 'Analysis pending.';
  const checks = checksFor(job);
  const must = checks.filter(c => c.importance === 'must');
  const missing = must.filter(c => c.coverage === 'missing');
  const related = must.filter(c => c.coverage === 'related');
  const parts = [];
  if (!must.length) parts.push('Posting lists no firm requirements');
  else if (missing.length) {
    const names = missing.slice(0, 2).map(c => c.requirement).join('; ');
    parts.push(`Missing: ${names}${missing.length > 2 ? `; ${missing.length - 2} more` : ''}`);
  } else parts.push(related.length ? `All must-haves supported, ${related.length} indirectly` : 'All must-haves shown in your CV');
  const conflicts = conflictsFor(job);
  const soft = conflicts.filter(c => c.severity === 'soft');
  if (soft.length) parts.push(`Preference conflict${soft.length > 1 ? 's' : ''}: ${soft.map(c => c.preference).join('; ')}`);
  if (label === 'Blocked') {
    const reasons = [...conflicts.filter(c => c.severity === 'hard').map(c => c.preference), ...(job.eligibility?.blockers || [])];
    if (reasons.length) parts.push(`Blocked: ${reasons.join('; ')}`);
  }
  return parts.join(' · ');
}
export function sortedChecks(job) {
  const order = ['missing', 'related', 'shown'];
  return [...checksFor(job)].sort((a, b) => order.indexOf(a.coverage) - order.indexOf(b.coverage));
}
export function normalizeJobsView(view = {}) {
  // Numeric thresholds have no rating equivalent. Preserve the other saved filters.
  const minimumRating = RATINGS.includes(view.minimumRating) ? view.minimumRating : '';
  const sortConfig = !view.sortConfig?.key || view.sortConfig.key === 'match_score'
    ? { key: 'match_rating', direction: 'desc' } : view.sortConfig;
  const { minMatchFilter: retiredThreshold, ...rest } = view;
  void retiredThreshold;
  return { ...rest, minimumRating, sortConfig };
}
export function sourceLabel(source) {
  if (!source) return 'Unknown source';
  if (/^karriere/i.test(source)) return 'Karriere.at';
  if (/^company[- ]feeds?$/i.test(source)) return 'Company feed';
  if (/^linkedin/i.test(source)) return 'LinkedIn';
  if (/^manual$/i.test(source)) return 'Added by hand';
  return source;
}
