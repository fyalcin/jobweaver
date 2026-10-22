import React from 'react';

export function EngineBadge({ engine = 'typst', size = 'sm', className = '' }) {
  const isTypst = engine === 'typst';
  const label = isTypst ? 'Typst' : 'LaTeX';

  return (
    <span
      className={`engine-badge ${isTypst ? 'engine-badge-typst' : 'engine-badge-latex'} engine-badge-${size} ${className}`}
      title={`Engine: ${label}`}
    >
      {label}
    </span>
  );
}
