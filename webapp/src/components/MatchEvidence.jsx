import { checksFor, conflictsFor, ratingClass, ratingLabel, ratingSummary, sortedChecks } from '../constants/ratings';

export function MatchRating({ job }) {
  return <span className={ratingClass(job)}>{ratingLabel(job)}</span>;
}

function formatGroupTally(items) {
  const parts = [
    ['shown', 'shown'],
    ['related', 'related'],
    ['missing', 'missing'],
  ]
    .map(([key, word]) => {
      const count = items.filter(c => c.coverage === key).length;
      return count > 0 ? `${count} ${word}` : null;
    })
    .filter(Boolean);
  return parts.join(' · ');
}

function coverageBadgeText(coverage) {
  if (coverage === 'shown') return 'shown in CV';
  if (coverage === 'related') return 'related in CV';
  return 'missing';
}

export function MatchEvidence({ job }) {
  const label = ratingLabel(job);
  const checks = sortedChecks(job);
  const conflicts = conflictsFor(job);
  const current = !['Unrated', 'Needs re-rating'].includes(label);
  const historical = label === 'Needs re-rating';

  const mustChecks = checks.filter(c => c.importance === 'must');
  const niceChecks = checks.filter(c => c.importance !== 'must');
  const groups = [
    { key: 'must', title: 'Must-have', items: mustChecks },
    { key: 'nice', title: 'Nice-to-have', items: niceChecks },
  ].filter(group => group.items.length > 0);

  return <section className="match-evidence" aria-label="Match evidence">
    <h2>Match evidence <MatchRating job={job} /></h2>
    <p>{ratingSummary(job)}</p>
    {current && job.analysis_current == null && <p>Current CV and model have not been verified for this analysis. Re-rate to check them.</p>}
    {checks.length > 0 ? <>
      {historical && <p className="evidence-historical-note">Historical evidence</p>}
      {!checksFor(job).some(c => c.importance === 'must') && <p>Posting lists no firm requirements. The rating uses optional requirements and is capped at Good before preference conflicts.</p>}
      <div className="evidence-groups">
        {groups.map(group => (
          <div className="evidence-umbrella-group" key={group.key}>
            <div className="evidence-umbrella-header">
              <span className="evidence-umbrella-title">{group.title}</span>
              <span className="evidence-umbrella-count">{formatGroupTally(group.items)}</span>
            </div>
            <div className="evidence-checklist">
              {group.items.map((check, index) => (
                <div className="evidence-item" key={index}>
                  <div className="evidence-item-top">
                    <strong className="evidence-item-name">{check.requirement}</strong>
                    <span className={`evidence-coverage-pill cov-${check.coverage}`} data-coverage={check.coverage}>
                      {coverageBadgeText(check.coverage)}
                    </span>
                  </div>
                  {check.cv_quote && check.coverage !== 'missing' && (
                    <blockquote className="evidence-cv-quote">{check.cv_quote}</blockquote>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </> : <p>{job.match_rating === 'Unrated' ? 'No checkable requirements were found. This posting remains unrated.' : current ? 'No checkable requirements were extracted from the posting.' : 'No evidence checklist is available. Re-rate to compare the posting with your CV.'}</p>}
    {conflicts.length > 0 && <div className="preference-evidence"><h3>Preference conflicts{historical && ' (historical)'}</h3>
      {conflicts.map((conflict, index) => <div key={index}>
        <h4>{conflict.preference} · {conflict.severity === 'hard' ? 'Firm constraint' : 'Soft preference'}</h4>
        <p>{conflict.severity === 'hard' ? 'This conflict blocks a match.' : 'This conflict lowers the rating by one step.'}</p>
        <p>Your notes:</p><blockquote>{conflict.notes_quote}</blockquote>
        <p>Posting:</p><blockquote>{conflict.posting_quote}</blockquote>
      </div>)}
    </div>}
    {Array.isArray(job.judgement_calls) && job.judgement_calls.length > 0 && <div><h3>Judgement calls{historical && ' (historical)'}</h3>
      <p>Related experience needs interpretation. The rating changes if these items count as missing:</p>
      <ul>{job.judgement_calls.map((call, index) => <li key={index}>If “{call.requirement}” counted as missing, this would be {call.if_missing}.</li>)}</ul>
    </div>}
  </section>;
}
