import React, { useState, useRef, useEffect } from 'react';
import { Palette, Check } from 'lucide-react';

export function ThemeSwitcher({ theme, setTheme, themes }) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);

  const activeTheme = themes.find((t) => t.id === theme) || themes[0];

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  return (
    <div className="theme-switcher-wrapper" ref={menuRef}>
      <button
        type="button"
        className="theme-switcher-btn"
        onClick={() => setOpen((prev) => !prev)}
        title="Switch theme"
        aria-label="Switch theme"
        aria-expanded={open}
      >
        <Palette size={14} style={{ color: 'var(--primary-color)' }} />
        <span>{activeTheme.name}</span>
      </button>

      {open && (
        <div className="theme-dropdown-menu" role="menu">
          {themes.map((t) => {
            const isActive = t.id === theme;
            return (
              <button
                key={t.id}
                type="button"
                className={`theme-dropdown-item ${isActive ? 'active' : ''}`}
                onClick={() => {
                  setTheme(t.id);
                  setOpen(false);
                }}
                role="menuitem"
              >
                <div className="theme-dropdown-info">
                  <div className="theme-dropdown-name" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    {t.name}
                    {isActive && <Check size={13} style={{ color: 'var(--primary-color)' }} />}
                  </div>
                  <div className="theme-dropdown-desc">{t.desc}</div>
                </div>
                <div className="theme-dots-preview">
                  {t.colors.map((c, i) => (
                    <span
                      key={i}
                      className="theme-dot"
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
