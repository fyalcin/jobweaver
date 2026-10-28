import { checksFor, conflictsFor, ratingClass, ratingLabel, ratingSummary, sortedChecks } from '../constants/ratings';

export function MatchRating({ job }) {
  return <span className={ratingClass(job)}>{ratingLabel(job)}</span>;
}

export function MatchEvidence({ job }) {
  const label = ratingLabel(job);
  const checks = sortedChecks(job);
  const conflicts = conflictsFor(job);
  const current = !['Unrated', 'Needs re-rating'].includes(label);
  const historical = label === 'Needs re-rating';
  const tally = ['missing', 'related', 'shown'].map(status => `${checks.filter(c => c.coverage === status).length} ${status}`).join(' · ');
  return <section className="match-evidence" aria-label="Match evidence">
    <h2>Match evidence <MatchRating job={job} /></h2>
    <p>{ratingSummary(job)}</p>
    {current && job.analysis_current == null && <p>Current CV and model have not been verified for this analysis. Re-rate to check them.</p>}
    {checks.length > 0 ? <>
      <p>{historical && 'Historical evidence · '}{tally}</p>
      {!checksFor(job).some(c => c.importance === 'must') && <p>Posting lists no firm requirements. The rating uses optional requirements and is capped at Good before preference conflicts.</p>}
      <div className="evidence-table-scroll"><table className="evidence-table">
        <thead><tr><th scope="col">Requirement and posting evidence</th><th scope="col">Your CV evidence</th><th scope="col">Coverage</th></tr></thead>
        <tbody>{checks.map((check, index) => <tr key={index}>
          <td><strong>{check.requirement}</strong><div>{check.importance === 'must' ? 'Must-have' : 'Nice-to-have'}</div><blockquote>{check.posting_quote}</blockquote></td>
          <td>{check.cv_quote ? <blockquote>{check.cv_quote}</blockquote> : 'No supporting CV quote.'}</td>
          <td>{check.coverage}</td>
        </tr>)}</tbody>
      </table></div>
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
