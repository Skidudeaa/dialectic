import { useState } from 'react'
import { useAppStore } from '../../stores/appStore.ts'
import { api } from '../../lib/api.ts'
import './AuthScreen.css'

type AuthTab = 'signin' | 'create' | 'quick';

export function AuthScreen() {
  const [activeTab, setActiveTab] = useState<AuthTab>('signin');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Sign In
  const [signInEmail, setSignInEmail] = useState('');
  const [signInPassword, setSignInPassword] = useState('');

  // Create Account
  const [createName, setCreateName] = useState('');
  const [createEmail, setCreateEmail] = useState('');
  const [createPassword, setCreatePassword] = useState('');

  // Quick Join
  const [quickName, setQuickName] = useState('');

  const setUser = useAppStore((s) => s.setUser);

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.login(signInEmail, signInPassword) as {
        access_token: string;
        refresh_token: string;
        user_id: string;
      };
      setUser(
        { id: res.user_id, display_name: signInEmail.split('@')[0] },
        res.access_token,
        res.refresh_token,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed');
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.signup(createEmail, createPassword, createName) as {
        access_token: string;
        refresh_token: string;
        user_id: string;
      };
      setUser(
        { id: res.user_id, display_name: createName },
        res.access_token,
        res.refresh_token,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Account creation failed');
    } finally {
      setLoading(false);
    }
  };

  const handleQuickJoin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch('/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: quickName }),
      });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const data = await res.json() as { id: string; display_name: string };
      // Quick join has no auth tokens — just a user identity
      setUser({ id: data.id, display_name: data.display_name }, '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Quick join failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-header">
          <h1 className="auth-logo">&#9671; Dialectic</h1>
          <p className="auth-subtitle">Collaborative reasoning engine</p>
        </div>

        <div className="auth-tabs">
          <button
            className={`auth-tab ${activeTab === 'signin' ? 'active' : ''}`}
            onClick={() => { setActiveTab('signin'); setError(''); }}
          >
            Sign In
          </button>
          <button
            className={`auth-tab ${activeTab === 'create' ? 'active' : ''}`}
            onClick={() => { setActiveTab('create'); setError(''); }}
          >
            Create Account
          </button>
          <button
            className={`auth-tab ${activeTab === 'quick' ? 'active' : ''}`}
            onClick={() => { setActiveTab('quick'); setError(''); }}
          >
            Quick Join
          </button>
        </div>

        {error && <div className="auth-error">{error}</div>}

        {activeTab === 'signin' && (
          <form className="auth-form" onSubmit={handleSignIn}>
            <label className="auth-label">
              Email
              <input
                className="form-input"
                type="email"
                value={signInEmail}
                onChange={(e) => setSignInEmail(e.target.value)}
                placeholder="you@example.com"
                required
                autoComplete="email"
              />
            </label>
            <label className="auth-label">
              Password
              <input
                className="form-input"
                type="password"
                value={signInPassword}
                onChange={(e) => setSignInPassword(e.target.value)}
                placeholder="Enter password"
                required
                autoComplete="current-password"
              />
            </label>
            <button className="btn btn-primary btn-full" type="submit" disabled={loading}>
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>
        )}

        {activeTab === 'create' && (
          <form className="auth-form" onSubmit={handleCreate}>
            <label className="auth-label">
              Display Name
              <input
                className="form-input"
                type="text"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                placeholder="How you appear in rooms"
                required
                autoComplete="name"
              />
            </label>
            <label className="auth-label">
              Email
              <input
                className="form-input"
                type="email"
                value={createEmail}
                onChange={(e) => setCreateEmail(e.target.value)}
                placeholder="you@example.com"
                required
                autoComplete="email"
              />
            </label>
            <label className="auth-label">
              Password
              <input
                className="form-input"
                type="password"
                value={createPassword}
                onChange={(e) => setCreatePassword(e.target.value)}
                placeholder="Choose a password"
                required
                minLength={8}
                autoComplete="new-password"
              />
            </label>
            <button className="btn btn-primary btn-full" type="submit" disabled={loading}>
              {loading ? 'Creating...' : 'Create Account'}
            </button>
          </form>
        )}

        {activeTab === 'quick' && (
          <form className="auth-form" onSubmit={handleQuickJoin}>
            <label className="auth-label">
              Display Name
              <input
                className="form-input"
                type="text"
                value={quickName}
                onChange={(e) => setQuickName(e.target.value)}
                placeholder="Pick a name to join"
                required
                autoComplete="name"
              />
            </label>
            <p className="auth-hint">
              No account needed. Jump into a room with just a name.
            </p>
            <button className="btn btn-primary btn-full" type="submit" disabled={loading}>
              {loading ? 'Joining...' : 'Quick Join'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
