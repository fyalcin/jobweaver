import React, { useState } from 'react';
import { Briefcase, LogIn } from 'lucide-react';
import { api } from '../api/client';

export function Login({ onLogin, demo }) {
  const [username, setUsername] = useState(demo?.demo ? demo.username : '');
  const [password, setPassword] = useState(demo?.demo ? demo.password : '');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.post('/auth/login', { username, password });
      onLogin(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed. Check your credentials.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-screen" style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      minHeight: '100vh', padding: '1rem'
    }}>
      <form onSubmit={handleSubmit} style={{
        display: 'flex', flexDirection: 'column', gap: '0.9rem',
        width: '100%', maxWidth: '340px', padding: '2rem',
        background: 'var(--surface-color)',
        border: '1px solid var(--border-color)',
        color: 'var(--text-primary)',
        borderRadius: '12px',
        boxShadow: '0 4px 24px rgba(0,0,0,0.15)'
      }}>
        <h1 className="app-title" style={{ justifyContent: 'center', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <div className="brand-logo-badge">
            <Briefcase size={18} color="#ffffff" />
          </div>
          <span>Jobweaver</span>
        </h1>
        {demo?.demo && <p className="demo-login-note">Explore a fictional job search. Scores and documents are prepared examples. Sign in with <strong>demo / demo</strong>.</p>}
        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', fontSize: '0.85rem' }}>
          Username
          <input
            className="input-base"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            autoComplete="username"
            required
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', fontSize: '0.85rem' }}>
          Password
          <input
            className="input-base"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <div style={{ color: '#ef4444', fontSize: '0.82rem' }}>{error}</div>}
        <button type="submit" className="input-base" disabled={submitting}
          style={{ cursor: submitting ? 'wait' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.4rem' }}>
          <LogIn size={16} />
          {submitting ? 'Signing in…' : demo?.demo ? 'Explore the demo' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
