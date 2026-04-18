import { useState, useCallback } from "react";
import { Routes, Route, Navigate, useSearchParams } from "react-router-dom";
import { isAuthenticated } from "./lib/api";
import { ToastProvider } from "./components/Toast";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ThesisBuilder from "./components/builder/ThesisBuilder";
import BuilderList from "./components/builder/BuilderList";

// /builder dispatches: with ?edit (even if empty for new) → editor;
// without it → library list page.
function BuilderRoute() {
  const [params] = useSearchParams();
  const hasEdit = params.has("edit") || params.get("import") === "session";
  return hasEdit ? <ThesisBuilder /> : <BuilderList />;
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
          <Route path="/builder" element={<BuilderRoute />} />
          <Route path="/*" element={<Dashboard onLogout={onLogout} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      )}
    </ToastProvider>
  );
}
