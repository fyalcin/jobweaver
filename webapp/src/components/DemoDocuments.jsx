import React, { useEffect, useState } from 'react';
import { useApi } from '../api/context';

export function DemoDocuments({ job }) {
  const api = useApi();
  const [documents, setDocuments] = useState(null);
  const [kind, setKind] = useState('cl');
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api.get(`/jobs/${job.id}/documents`)
      .then(res => { if (active) setDocuments(res.data); })
      .catch(() => { if (active) setError('Could not load demo documents.'); });
    return () => { active = false; };
  }, [api, job.id]);
  if (error) return <p role="alert">{error}</p>;
  if (!documents) return <p>Loading demo documents…</p>;
  if (!documents.has_cv) return <div className="card">This fictional posting has no prepared documents. Open the Cumulus Research, Brookline Data or Rainfall Commons posting.</div>;
  return (
    <section className="demo-documents card">
      <div className="demo-document-toolbar">
        <h2>Prepared application</h2>
        <button className="btn btn-secondary" aria-pressed={kind === 'cl'} onClick={() => setKind('cl')}>Cover letter</button>
        <button className="btn btn-secondary" aria-pressed={kind === 'cv'} onClick={() => setKind('cv')}>CV</button>
        <a className="btn btn-primary" href={documents[`${kind}_download_url`]} target="_blank" rel="noreferrer">Download PDF</a>
      </div>
      <p>These documents use the fictional career record. The letter and its evidence links were prepared by hand for this demo.</p>
      {kind === 'cl' && documents.demo_evidence && (
        <details open>
          <summary>Evidence behind this letter</summary>
          <ul>{documents.demo_evidence.claims.map(claim => <li key={claim.id}><strong>{claim.id}</strong>: {claim.text}</li>)}</ul>
          <p>No live model or automated verifier ran for these examples. Review generated letters before sending.</p>
        </details>
      )}
      {documents[`${kind}_images`].map(url => <img className="demo-document-page" key={url} src={url} alt={`${kind === 'cv' ? 'CV' : 'Cover letter'} page for Alex Example`} />)}
    </section>
  );
}
