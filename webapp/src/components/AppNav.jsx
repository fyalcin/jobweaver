import React, { useState } from 'react';
import {
  Briefcase, Search, FileText,
  BarChart2, Settings, CalendarDays, MoreHorizontal, User, FileCode2,
  LogOut
} from 'lucide-react';
import { useDemo } from '../demoContext';
import { ThemeSwitcher } from './ThemeSwitcher';

export function AppNav({
  activeTab,
  setActiveTab,
  user,
  onLogout,
  theme,
  setTheme,
  themes = [],
}) {
  const demo = useDemo();
  const tabs = [
    { id: 'jobs', icon: <Briefcase size={20} />, label: 'Jobs', mobilePrimary: true },
    { id: 'daily', icon: <CalendarDays size={20} />, label: 'Daily Matches', mobilePrimary: true },
    { id: 'studio', icon: <FileCode2 size={20} />, label: 'CV Library', mobilePrimary: true },
    { id: 'personalize', icon: <User size={20} />, label: 'Personalize' },
    { id: 'manual', icon: <FileText size={20} />, label: 'Add Job', mobilePrimary: true },
    { id: 'scraper', icon: <Search size={20} />, label: 'Scraper' },
    { id: 'stats', icon: <BarChart2 size={20} />, label: 'Analytics' },
    { id: 'settings', icon: <Settings size={20} />, label: 'Settings', utility: true },
  ].filter(tab => !demo || !['studio', 'manual', 'scraper'].includes(tab.id));
  const [moreOpen, setMoreOpen] = useState(false);
  const moreTabs = tabs.filter((tab) => !tab.mobilePrimary);
  const selectTab = (id) => {
    setActiveTab(id);
    setMoreOpen(false);
  };

  const displayName = user?.display_name || user?.username || 'User';
  const initial = displayName.charAt(0).toUpperCase();

  return (
    <nav className="app-nav">
      {/* Brand Header at top of sidebar */}
      <div className="nav-brand">
        <div className="brand-logo-badge">
          <Briefcase size={16} aria-hidden="true" />
        </div>
        <span className="nav-brand-title">Job<span>weaver</span></span>
      </div>

      <div className="nav-tabs-list">
        {tabs.map((tab) => (
          <React.Fragment key={tab.id}>
            {tab.utility && <div className="nav-divider" />}
            <button
              className={`nav-tab ${tab.mobilePrimary ? '' : 'mobile-nav-secondary'} ${activeTab === tab.id ? 'active' : ''}`}
              aria-current={activeTab === tab.id ? 'page' : undefined}
              onClick={() => selectTab(tab.id)}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          </React.Fragment>
        ))}
      </div>

      <button
        className={`nav-tab mobile-more-trigger ${moreOpen ? 'active' : ''}`}
        onClick={() => setMoreOpen((v) => !v)}
        aria-expanded={moreOpen}
      >
        <MoreHorizontal size={20} />
        <span>More</span>
      </button>

      {/* Desktop footer: Theme switcher + User info & logout */}
      <div className="nav-footer">
        <div className="nav-divider" />
        <div className="nav-theme-container">
          <ThemeSwitcher theme={theme} setTheme={setTheme} themes={themes} />
        </div>
        {user && (
          <div className="nav-user-row">
            <div className="nav-user-info" title={displayName}>
              <div className="nav-user-avatar" aria-hidden="true">
                {initial}
              </div>
              <span className="nav-user-name">{displayName}</span>
            </div>
            {onLogout && (
              <button
                type="button"
                onClick={onLogout}
                className="nav-logout-btn"
                title="Sign out"
                aria-label="Sign out"
              >
                <LogOut size={14} />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Mobile more popup menu */}
      {moreOpen && (
        <div className="mobile-more-menu">
          {moreTabs.map((tab) => (
            <button
              key={tab.id}
              className={activeTab === tab.id ? 'active' : ''}
              onClick={() => selectTab(tab.id)}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
          <div className="nav-divider" />
          <div className="mobile-more-footer">
            <div className="nav-theme-container">
              <ThemeSwitcher theme={theme} setTheme={setTheme} themes={themes} />
            </div>
            {user && (
              <div className="nav-user-row">
                <div className="nav-user-info" title={displayName}>
                  <div className="nav-user-avatar" aria-hidden="true">
                    {initial}
                  </div>
                  <span className="nav-user-name">{displayName}</span>
                </div>
                {onLogout && (
                  <button
                    type="button"
                    onClick={onLogout}
                    className="nav-logout-btn"
                    title="Sign out"
                    aria-label="Sign out"
                  >
                    <LogOut size={14} />
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </nav>
  );
}
