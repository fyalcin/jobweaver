import React, { useState, useRef, useEffect, useId } from 'react';
import { Palette, Check } from 'lucide-react';

export function ThemeSwitcher({ theme, setTheme, themes }) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);
  const triggerRef = useRef(null);
  const panelId = useId();
  const activeTheme = themes.find(t => t.id === theme) || themes[0];
  const communityThemes = themes.filter(t => !t.id.startsWith('loden-'));
  const communityActive = !activeTheme?.id.startsWith('loden-');

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector('.theme-dropdown-item')?.focus();
    const outside = e => {
      if (!menuRef.current?.contains(e.target)) setOpen(false);
    };
    const escape = e => {
      if (e.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', outside);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', outside);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  return (
    <div className="theme-switcher-wrapper" ref={menuRef}>
      <div className="theme-mode-toggle" role="group" aria-label="Loden appearance">
        {['light', 'dark'].map(mode => (
          <button key={mode} type="button" aria-pressed={theme === `loden-${mode}`}
            onClick={() => { setTheme(`loden-${mode}`); setOpen(false); }}>
            {mode === 'light' ? 'Light' : 'Dark'}
          </button>
        ))}
      </div>
      <button ref={triggerRef} type="button" className="theme-switcher-btn"
        onClick={() => setOpen(value => !value)} aria-expanded={open} aria-controls={panelId}>
        <Palette size={14} aria-hidden="true" />
        <span>{communityActive ? activeTheme.name : 'Community palettes'}</span>
      </button>
      {open && (
        <div className="theme-dropdown-menu" id={panelId} role="group" aria-label="Community palettes">
          {communityThemes.map(t => (
            <button key={t.id} type="button" className={`theme-dropdown-item ${t.id === theme ? 'active' : ''}`}
              aria-pressed={t.id === theme}
              onClick={() => { setTheme(t.id); setOpen(false); triggerRef.current?.focus(); }}>
              <div className="theme-dropdown-info">
                <div className="theme-dropdown-name">
                  {t.name} {t.id === theme && <Check size={13} aria-hidden="true" />}
                </div>
                <div className="theme-dropdown-desc">{t.desc}</div>
              </div>
              <div className="theme-dots-preview" aria-hidden="true">
                {t.colors.map((color, i) => <span key={i} className="theme-dot" style={{ backgroundColor: color }} />)}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
