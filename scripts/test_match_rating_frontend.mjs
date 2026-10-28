import assert from 'node:assert/strict';
import { RATINGS, ratingLabel, ratingSummary, compareBestFit, compareJobs, matchesRating, matchesStage, sortedChecks, normalizeJobsView, sourceLabel } from '../webapp/src/constants/ratings.js';
import { formatDateDisplay, formatDateTimeDisplay } from '../webapp/src/constants/dates.js';

const check = (requirement, coverage, importance = 'must') => ({ requirement, coverage, importance, posting_quote: `${requirement} required`, cv_quote: coverage === 'missing' ? '' : `${requirement} experience` });
const rated = (rating, extra = {}) => ({ match_rating: rating, analysis_current: true, match_checks: [], ...extra });
assert.equal(ratingLabel({ match_score: 99, analysis_current: true }), 'Needs re-rating');
assert.equal(ratingLabel({ match_score: 0 }), 'Needs re-rating');
assert.equal(ratingLabel(rated('Great', { analysis_current: false })), 'Needs re-rating');
assert.equal(ratingLabel({ analysis_state: 'failed' }), 'Unrated');
assert.equal(ratingLabel(rated('Unrated', { analysis_state: 'complete', match_analysis: {} })), 'Unrated');
assert.match(ratingSummary(rated('Unrated')), /no checkable requirements/i);
assert.match(ratingSummary({ analysis_state: 'failed', analysis_error: 'Add your CV' }), /Analysis failed: Add your CV/);
assert.match(ratingSummary(rated('Good', { match_checks: [check('Python', 'shown', 'nice')] })), /no firm requirements/i);
assert.match(ratingSummary(rated('Good', { match_checks: [check('Git', 'related')] })), /1 indirectly/);
const summary = ratingSummary(rated('Stretch', { match_checks: [check('SQL', 'missing'), check('Git', 'missing'), check('Docker', 'missing')], preference_conflicts: [{ preference: 'Work location', severity: 'soft' }] }));
assert.match(summary, /Missing: SQL; Git; 1 more/);
assert(!summary.includes('Docker'));
assert.match(summary, /Preference conflict: Work location/);
assert.match(ratingSummary(rated('Blocked', { eligibility: { blockers: ['Work authorization'] } })), /Blocked: Work authorization/);
const list = [rated('Good', { id: 'gap', match_checks: [check('SQL', 'missing')], date_scraped: '2026-10-28' }), rated('Great', { id: 'great' }), rated('Good', { id: 'older', date_scraped: '2026-10-22' }), rated('Good', { id: 'newer', date_scraped: '2026-10-28' }), { id: 'legacy', match_score: 100 }];
assert.deepEqual(list.sort(compareBestFit).map(job => job.id), ['great', 'newer', 'older', 'gap', 'legacy']);
// Group order must survive alternate sorting BEFORE pages are sliced.
const crowded = Array.from({ length: 30 }, (_, index) => rated('Poor', {
  id: `poor-${index}`, date_scraped: '2026-10-28', salary_yearly: 100000, title: 'A new posting',
}));
crowded.push(rated('Great', { id: 'older-great', date_scraped: '2026-09-01', salary_yearly: 40000, title: 'Z older posting' }));
for (const sort of [{ key: 'date_scraped', direction: 'desc' }, { key: 'salary_yearly', direction: 'desc' }, { key: 'title', direction: 'asc' }]) {
  const firstPage = [...crowded].sort((a, b) => compareJobs(a, b, sort)).slice(0, 25);
  assert.equal(firstPage[0].id, 'older-great', `Rating groups must be primary for ${sort.key}`);
}
for (const direction of ['asc', 'desc']) {
  const salaries = [rated('Good', { id: 'unknown' }), rated('Good', { id: 'low', salary_yearly: 40000 }), rated('Good', { id: 'high', salary_yearly: 60000 })];
  assert.deepEqual(salaries.sort((a, b) => compareJobs(a, b, { key: 'salary_yearly', direction })).map(job => job.id),
    direction === 'asc' ? ['low', 'high', 'unknown'] : ['high', 'low', 'unknown']);
}
for (const rating of RATINGS.slice(0, 2)) assert(matchesRating(rated(rating), 'Good'));
assert(!matchesRating(rated('Decent'), 'Good'));
assert(!matchesRating({ match_score: 100 }, 'Good'));
assert(!matchesRating(rated('Great', { analysis_current: false }), 'Good'));
assert(!matchesRating(rated('Unrated'), 'Poor'));
for (const status of ['applied', 'interview', 'offer', 'rejected']) assert(matchesStage({ status }, 'pipeline'));
assert(!matchesStage({ status: 'interested' }, 'pipeline'));
assert(matchesStage({ status: 'not_interested' }, 'All'));
assert(matchesStage({ applied: true }, 'pipeline'));
assert.deepEqual(sortedChecks({ match_checks: [check('shown', 'shown'), check('missing', 'missing'), check('related', 'related')] }).map(c => c.coverage), ['missing', 'related', 'shown']);
const legacy = { minMatchFilter: '85', searchQuery: 'Python', statusFilter: 'interested', itemsPerPage: 50, sortConfig: { key: 'match_score', direction: 'asc' } };
const migrated = normalizeJobsView(legacy);
assert.equal(migrated.minimumRating, '');
assert.equal(migrated.minMatchFilter, undefined);
assert.equal(migrated.searchQuery, 'Python');
assert.equal(migrated.itemsPerPage, 50);
assert.deepEqual(migrated.sortConfig, { key: 'match_rating', direction: 'desc' });
assert.equal(legacy.minMatchFilter, '85');
assert.equal(normalizeJobsView({ minimumRating: 'Good' }).minimumRating, 'Good');
assert.equal(sourceLabel('company-feeds'), 'Company feed');
assert.equal(sourceLabel('manual'), 'Added by hand');
assert.equal(sourceLabel('karriere-apify'), 'Karriere.at');
assert.equal(formatDateDisplay('2026-10-28'), '28.10.2026');
assert.equal(formatDateTimeDisplay('2026-10-28T15:04:18'), '28.10.2026, 15:04');
console.log('Rating regressions passed: legacy/no-requirement distinctions, gap/conflict summaries, rating sort/filter, stages and stored-view migration.');
