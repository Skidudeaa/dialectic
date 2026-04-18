import { useState, useCallback, lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { isAuthenticated } from "./lib/api";
import { ToastProvider } from "./components/Toast";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";

// Builder is a separate, large feature (graph canvas + validation + sub-editors).
// Lazy-load it so the main chunk stays small for users who only chat / view
// theses and never visit /builder.
const BuilderRoute = lazy(() => import("./components/builder/BuilderRoute"));

function BuilderFallback() {
  return (
    <div className="h-screen flex items-center justify-center bg-void text-text-muted text-xs font-mono">
      loading builder…
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(isAuthenticated());

  const onLogin = useCallback(() => setAuthed(true), []);
  const onLogout = useCallback(() => {
    setAuthed(false);
  }, []);

  return (
    <ToastProvider>
      {!authed ? (
        <Login onLogin={onLogin} />
      ) : (
        <Routes>
          <Route
            path="/builder"
            element={
              <Suspense fallback={<BuilderFallback />}>
                <BuilderRoute />
              </Suspense>
            }
          />
          <Route path="/*" element={<Dashboard onLogout={onLogout} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      )}
    </ToastProvider>
  );
}
