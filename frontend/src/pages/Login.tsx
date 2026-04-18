import { useState, useRef, useEffect, type FormEvent } from "react";
import { Eye, EyeOff, AlertOctagon, Activity } from "lucide-react";
import { login } from "../lib/api";

interface Props {
  onLogin: () => void;
}

export default function Login({ onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const userRef = useRef<HTMLInputElement>(null);

  // Focus username field on mount; if username pre-filled, focus password instead.
  useEffect(() => {
    userRef.current?.focus();
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (loading) return; // belt-and-suspenders: prevent double-submit
    setError("");
    setLoading(true);
    try {
      await login(username.trim(), password);
      onLogin();
    } catch {
      setError("Invalid username or password");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-void p-4">
      {/* Background grain — subtle radial vignette */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse at center, rgba(212,168,67,0.04) 0%, transparent 60%)",
        }}
        aria-hidden="true"
      />

      <form
        onSubmit={handleSubmit}
        noValidate
        className="relative bg-surface border border-border rounded-lg p-8 w-full max-w-sm shadow-2xl animate-fade-in"
      >
        {/* Brand */}
        <div className="flex items-center gap-2 mb-1">
          <Activity size={18} className="text-amber" aria-hidden="true" />
          <h1 className="text-xl font-semibold text-amber font-mono leading-none">
            tradingDesk
          </h1>
        </div>
        <p className="text-text-muted text-xs font-mono mb-6">
          Causal reasoning engine for macro trading
        </p>

        <label
          htmlFor="login-user"
          className="block text-[11px] uppercase tracking-widest text-text-dim font-mono mb-1"
        >
          Username
        </label>
        <input
          id="login-user"
          ref={userRef}
          type="text"
          className={`input w-full mb-3 ${error ? "border-danger/50" : ""}`}
          value={username}
          onChange={(e) => {
            setUsername(e.target.value);
            if (error) setError("");
          }}
          autoComplete="username"
          spellCheck={false}
          disabled={loading}
        />

        <label
          htmlFor="login-pw"
          className="block text-[11px] uppercase tracking-widest text-text-dim font-mono mb-1"
        >
          Password
        </label>
        <div className="relative mb-2">
          <input
            id="login-pw"
            type={showPassword ? "text" : "password"}
            className={`input w-full pr-7 ${error ? "border-danger/50" : ""}`}
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (error) setError("");
            }}
            autoComplete="current-password"
            disabled={loading}
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-text-dim hover:text-text-primary"
            aria-label={showPassword ? "Hide password" : "Show password"}
            tabIndex={-1}
          >
            {showPassword ? <EyeOff size={13} /> : <Eye size={13} />}
          </button>
        </div>

        {error && (
          <div
            role="alert"
            className="flex items-center gap-1.5 mb-3 text-danger text-xs font-mono"
          >
            <AlertOctagon size={12} aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}
        {!error && <div className="mb-3" />}

        <button
          type="submit"
          className="btn-primary w-full"
          disabled={loading || !username || !password}
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>

        <p className="mt-4 pt-3 border-t border-border text-[10px] text-text-dim font-mono leading-relaxed">
          Two-analyst workspace. Dev users: <span className="text-text-muted">amo</span>,{" "}
          <span className="text-text-muted">dan</span>.
        </p>
      </form>
    </div>
  );
}
