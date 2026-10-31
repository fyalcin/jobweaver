import React from 'react';

export function PageHeader({ title, subtitle, badge, actions }) {
  return (
    <header className="page-header">
      <div className="page-header-main">
        <div className="page-title-row">
          <h2 className="page-title">{title}</h2>
          {badge ? <span className="page-count-badge">{badge}</span> : null}
        </div>
        {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </header>
  );
}
