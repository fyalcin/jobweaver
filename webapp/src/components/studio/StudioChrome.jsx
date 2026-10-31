import React from 'react';
import { ZoomIn, ZoomOut, RotateCcw } from 'lucide-react';
import { allSectionsOpen, sectionOpenKey } from './studioSections';

function shortJumpLabel(title) {
  const raw = String(title || 'Section').trim();
  const lower = raw.toLowerCase();
  if (lower.includes('summary') || lower.includes('profile')) return 'Profile';
  if (lower.includes('skill') || lower.includes('competenc')) return 'Skills';
  if (lower.includes('experience') || lower.includes('employment') || lower.includes('work')) return 'Experience';
  if (lower.includes('project')) return 'Projects';
  if (lower.includes('education') || lower.includes('academic')) return 'Education';
  if (lower.includes('publication')) return 'Publications';
  if (lower.includes('award') || lower.includes('honor')) return 'Awards';
  if (lower.includes('language')) return 'Languages';
  return raw.length > 18 ? `${raw.slice(0, 16)}…` : raw;
}

export function StudioJumpBar({ data, kind, openSections, setOpenSections }) {
  if (!data) return null;

  const isLetter = kind === 'cover-letter' || data.kind === 'letter' || (!data.sections && Array.isArray(data.paragraphs));
  const items = isLetter
    ? [
        { key: 'basics', anchor: 'sec-anchor-basics', label: 'Personal' },
        { key: 'recipient', anchor: 'sec-anchor-recipient', label: 'Recipient' },
        { key: 'paragraphs', anchor: 'sec-anchor-paragraphs', label: 'Letter Body' },
      ]
    : [
        { key: 'basics', anchor: 'sec-anchor-basics', label: 'Personal' },
        ...(data.sections || []).map((sec, idx) => ({
          key: sectionOpenKey(sec, idx),
          anchor: `sec-anchor-${idx}`,
          label: shortJumpLabel(sec.title),
        })),
      ];

  const anyOpen = items.some((it) => Boolean(openSections?.[it.key]));

  const handleJump = (item) => {
    if (setOpenSections) {
      setOpenSections((prev) => ({ ...(prev || {}), [item.key]: true }));
    }
    requestAnimationFrame(() => {
      const el = document.getElementById(item.anchor);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  };

  const handleToggleAll = () => {
    if (!setOpenSections) return;
    if (anyOpen) {
      setOpenSections({});
    } else {
      setOpenSections(allSectionsOpen(data, kind));
    }
  };

  return (
    <div className="studio-jumpbar" role="navigation" aria-label="Document section jump links">
      <span className="studio-jumpbar-kicker">Jump</span>
      <div className="studio-jumpbar-links">
        {items.map((item, idx) => (
          <React.Fragment key={item.key}>
            {idx > 0 && <span className="studio-jumpbar-dot" aria-hidden="true">·</span>}
            <button
              type="button"
              className={`studio-jumpbar-link ${openSections?.[item.key] ? 'is-open' : ''}`}
              onClick={() => handleJump(item)}
            >
              {item.label}
            </button>
          </React.Fragment>
        ))}
      </div>
      <button
        type="button"
        className="studio-jumpbar-fold"
        onClick={handleToggleAll}
      >
        {anyOpen ? 'Fold all' : 'Expand all'}
      </button>
    </div>
  );
}

export function FloatingPreviewHud({ pageCount = 0, zoom = 100, setZoom }) {
  return (
    <div className="studio-floating-hud" role="toolbar" aria-label="PDF preview zoom and pages">
      {pageCount > 0 && (
        <>
          <span className="hud-pages">
            {pageCount} {pageCount === 1 ? 'page' : 'pages'}
          </span>
          <span className="hud-sep" aria-hidden="true" />
        </>
      )}
      <button
        type="button"
        className="hud-btn"
        onClick={() => setZoom && setZoom((z) => Math.max(50, z - 15))}
        title="Zoom out"
        aria-label="Zoom out"
      >
        <ZoomOut size={12} />
      </button>
      <span className="hud-zoom-val">{zoom}%</span>
      <button
        type="button"
        className="hud-btn"
        onClick={() => setZoom && setZoom((z) => Math.min(200, z + 15))}
        title="Zoom in"
        aria-label="Zoom in"
      >
        <ZoomIn size={12} />
      </button>
      {zoom !== 100 && (
        <button
          type="button"
          className="hud-btn hud-reset"
          onClick={() => setZoom && setZoom(100)}
          title="Reset zoom to 100%"
          aria-label="Reset zoom"
        >
          <RotateCcw size={11} />
        </button>
      )}
    </div>
  );
}
