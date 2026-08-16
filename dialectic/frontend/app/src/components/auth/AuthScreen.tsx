import { useEffect, useState } from 'react';
import { useAppStore } from '../../stores/appStore.ts';
import { api } from '../../lib/api.ts';
import { PARTICIPANT_NAME, PRODUCT_NAME } from '../../lib/productIdentity.ts';
import './AuthScreen.css';

type AuthTab = 'signin' | 'create' | 'guest';

/**
 * The first surface anyone sees, and until now the only thing it said about
 * the product was "Collaborative reasoning engine" — four words, then three
 * doors presented as equals.
 *
 * TWO THINGS THIS FIXES, both measured against what a new user actually hits:
 *
 * 1. The screen now states the premise. The load-bearing idea of this product
 *    is that the third participant is a PARTICIPANT — it decides when to speak
 *    rather than waiting to be prompted — and someone who misses that misreads
 *    every other surface. It cost nothing to say and was nowhere.
 *
 * 2. The doors tell the truth, and they ask the SERVER what the truth is.
 *    Registration is gated by SIGNUPS_ENABLED, so the old screen offered a
 *    full three-field form and produced a 403 only after the submit. The
 *    capability is now read from /meta/capabilities, which reports the same
 *    predicate the signup route enforces with — so this screen cannot
 *    advertise a door the server refuses, and it does not hardcode "closed"
 *    either. Unknown is treated as closed: never claim a capability we have
 *    not heard back about.
 *
 * The guest path is NOT broken and is not removed — `useRoomNavigation`
 * deliberately handles a tokenless identity, and an invite code carries such a
 * user into their room. But a guest holds no JWT, so every endpoint behind
 * `get_current_user` refuses them. Saying "no account needed" without saying
 * that was the actual lie, and the limits are now stated on the door.
 */
export function AuthScreen() {
  const [activeTab, setActiveTab] = useState<AuthTab>('signin');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // null = not heard back yet. Deliberately distinct from "closed" in the
  // type, and treated as closed in the UI.
  const [capabilities, setCapabilities] = useState<
    { signups_enabled: boolean; guest_access_enabled: boolean } | null
  >(null);

  // Sign In
  const [signInEmail, setSignInEmail] = useState('');
  const [signInPassword, setSignInPassword] = useState('');

  // Create Account
  const [createName, setCreateName] = useState('');
  const [createEmail, setCreateEmail] = useState('');
  const [createPassword, setCreatePassword] = useState('');

  // Guest identity (invite link)
  const [guestName, setGuestName] = useState('');

  const setUser = useAppStore((s) => s.setUser);
  // Set when the server ended the session for a reason it can name — e.g. this
  // device was evicted by a sign-in elsewhere. Distinct from `error`, which is
  // about the form the user is currently filling in.
  const signedOutReason = useAppStore((s) => s.signedOutReason);

  useEffect(() => {
    let live = true;
    // A failure leaves capabilities null, i.e. closed. The screen degrades to
    // "ask for an invite", which is the correct answer in this deployment
    // anyway — it never degrades to offering a form that cannot work.
    void api.getCapabilities()
      .then((caps) => { if (live) setCapabilities(caps); })
      .catch(() => undefined);
    return () => { live = false; };
  }, []);

  const signupsOpen = capabilities?.signups_enabled === true
  // Owner ruling 2026-08-13: guests are closed. Read rather than hardcoded, so
  // re-opening is a flag flip; unknown counts as closed, so the tab never
  // appears while the answer is still in flight.
  const guestsOpen = capabilities?.guest_access_enabled === true;

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await api.login(signInEmail, signInPassword) as {
        access_token: string;
        refresh_token: string;
        user_id: string;
        display_name?: string;
      };
      api.setAccessToken(res.access_token);
      setUser(
        { id: res.user_id, display_name: res.display_name ?? signInEmail.split('@')[0] },
        res.access_token,
        res.refresh_token,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed');
    } finally {
      setLoading(false);
    }
  };

  const handleForgotPassword = async () => {
    setError('');
    setLoading(true);
    try {
      await api.forgotPassword(signInEmail);
      setError('Password recovery is unavailable because email delivery is not configured');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Password recovery is unavailable');
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
        display_name?: string;
      };
      api.setAccessToken(res.access_token);
      setUser(
        { id: res.user_id, display_name: res.display_name ?? createName },
        res.access_token,
        res.refresh_token,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Account creation failed');
    } finally {
      setLoading(false);
    }
  };

  const handleGuestJoin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch('/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: guestName }),
      });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const data = await res.json() as { id: string; display_name: string };
      // A guest identity carries no tokens — useRoomNavigation knows this and
      // skips the JWT-backed room list rather than calling it and failing.
      api.setAccessToken('');
      setUser({ id: data.id, display_name: data.display_name }, '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create a guest identity');
    } finally {
      setLoading(false);
    }
  };

  const tab = (id: AuthTab, label: string) => (
    <button
      role="tab"
      id={`auth-tab-${id}`}
      aria-selected={activeTab === id}
      aria-controls={`auth-panel-${id}`}
      className={`auth-tab ${activeTab === id ? 'active' : ''}`}
      onClick={() => { setActiveTab(id); setError(''); }}
    >
      {label}
    </button>
  );

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-header">
          <h1 className="auth-logo">&#9671; {PRODUCT_NAME}</h1>
          <p className="auth-subtitle">Where two people and {PARTICIPANT_NAME} think about one thing together</p>
        </div>

        <div className="auth-premise" data-testid="auth-premise">
          <p>
            {PARTICIPANT_NAME} is a <strong>participant, not an assistant</strong>. It
            decides for itself when to speak, checks live data before it answers,
            remembers what was said and who said it, and follows up when a
            question goes unanswered.
          </p>
          <p>
            It can prepare a change — a prediction, a thesis, a saved source —
            but your tap is the only thing that makes one real.
          </p>
        </div>

        <div className="auth-tabs" role="tablist" aria-label="How to get in">
          {tab('signin', 'Sign In')}
          {tab('create', 'Create Account')}
          {guestsOpen && tab('guest', 'Invite link')}
        </div>

        {signedOutReason && !error && (
          <div className="auth-notice" role="status">{signedOutReason}</div>
        )}

        {error && <div className="auth-error" role="alert">{error}</div>}

        {activeTab === 'signin' && (
          <form className="auth-form" id="auth-panel-signin" role="tabpanel" aria-labelledby="auth-tab-signin" onSubmit={handleSignIn}>
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
            <button
              className="btn btn-ghost btn-full"
              type="button"
              disabled={loading || !signInEmail}
              onClick={() => { void handleForgotPassword(); }}
            >
              Forgot password?
            </button>
          </form>
        )}

        {activeTab === 'create' && !signupsOpen && (
          <div
            className="auth-closed"
            id="auth-panel-create"
            role="tabpanel"
            aria-labelledby="auth-tab-create"
            data-testid="signup-closed-notice"
          >
            <p className="auth-closed-headline">{PRODUCT_NAME} is invite-only.</p>
            <p>
              New accounts are closed on this deployment, so there is no form
              here to fill in. Ask Amo for an invite — you will get a link that
              opens one room, and you can sign in properly from there.
            </p>
          </div>
        )}

        {activeTab === 'create' && signupsOpen && (
          <form className="auth-form" id="auth-panel-create" role="tabpanel" aria-labelledby="auth-tab-create" onSubmit={handleCreate}>
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

        {activeTab === 'guest' && guestsOpen && (
          <form className="auth-form" id="auth-panel-guest" role="tabpanel" aria-labelledby="auth-tab-guest" onSubmit={handleGuestJoin}>
            <label className="auth-label">
              Display Name
              <input
                className="form-input"
                type="text"
                value={guestName}
                onChange={(e) => setGuestName(e.target.value)}
                placeholder="Pick a name to join as"
                required
                autoComplete="name"
              />
            </label>
            <div className="auth-limits" data-testid="guest-limits">
              <p>
                For when someone has sent you an invite code. You get a name and
                that one room — the conversation, its branches, and {PARTICIPANT_NAME} in it.
              </p>
              <p className="auth-limits-caveat">
                A guest has no account, so the House, saved rooms, and anything
                that remembers you across visits stay closed. Sign in instead if
                you have an account.
              </p>
            </div>
            <button className="btn btn-primary btn-full" type="submit" disabled={loading}>
              {loading ? 'Joining...' : 'Continue as guest'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
