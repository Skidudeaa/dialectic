import { useState, type FormEvent } from "react";
import { login } from "../lib/api";

interface Props {
  onLogin: () => void;
}

export default function Login({ onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      onLogin();
    } catch {
      setError("Invalid credentials");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-void">
      <form
        onSubmit={handleSubmit}
        className="bg-surface border border-border rounded-lg p-8 w-full max-w-sm"
      >
        <h1 className="text-xl font-semibold text-amber mb-1 font-mono">tradingDesk</h1>
        <p className="text-text-muted text-sm mb-6">Collaborative macro analysis</p>

        <label className="block text-sm text-text-muted mb-1">Username</label>
        <input
          type="text"
          className="input w-full mb-4"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
          autoComplete="username"
        />

        <label className="block text-sm text-text-muted mb-1">Password</label>
        <input
          type="password"
          className="input w-full mb-4"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />

        {error && <p className="text-danger text-sm mb-3">{error}</p>}

        <button
          type="submit"
          className="btn-primary w-full"
          disabled={loading || !username}
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
