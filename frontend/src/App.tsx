import { useState, useCallback, lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { isAuthenticated } from "./lib/api";
import { ToastProvider } from "./components/Toast";
import { OnboardingProvider } from "./components/onboarding/OnboardingProvider";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";

// Builder is a separate, large feature (graph canvas + validation + sub-editors).
// Lazy-load it so the main chunk stays small for users who only chat / view
// theses and never visit /builder.
const BuilderRoute = lazy(() => import("./components/builder/BuilderRoute"));

// Welcome is a marketing-grade evergreen guide. Lazy-load: most sessions don't
// visit it, no reason to pay for the SVG diagrams + prose on every page load.
const Welcome = lazy(() => import("./pages/Welcome"));

// Dialectic — the "Field Desk" reimagining (dossier aesthetic, room-as-hero).
// A self-contained alternate surface; lazy so its bespoke CSS + fonts only
// load for sessions that open it.
const DialecticRoute = lazy(() => import("./components/dialectic/DialecticRoute"));

function RouteFallback({ label }: { label: string }) {
  return (
    <div className="h-screen flex items-center justify-center bg-void text-text-muted text-xs font-mono">
      loading {label}…
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
        <OnboardingProvider>
          <Routes>
            <Route
              path="/builder"
              element={
                <Suspense fallback={<RouteFallback label="builder" />}>
                  <BuilderRoute />
                </Suspense>
              }
            />
            <Route
              path="/welcome"
              element={
                <Suspense fallback={<RouteFallback label="welcome" />}>
                  <Welcome />
                </Suspense>
              }
            />
            <Route
              path="/dialectic"
              element={
                <Suspense fallback={<RouteFallback label="dialectic" />}>
                  <DialecticRoute />
                </Suspense>
              }
            />
            <Route path="/*" element={<Dashboard onLogout={onLogout} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </OnboardingProvider>
      )}
    </ToastProvider>
  );
}
