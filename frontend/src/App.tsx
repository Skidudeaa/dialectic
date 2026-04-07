import { useState, useCallback } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { isAuthenticated } from "./lib/api";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";

export default function App() {
  const [authed, setAuthed] = useState(isAuthenticated());

  const onLogin = useCallback(() => setAuthed(true), []);
  const onLogout = useCallback(() => {
    setAuthed(false);
  }, []);

  if (!authed) {
    return <Login onLogin={onLogin} />;
  }

  return (
    <Routes>
      <Route path="/*" element={<Dashboard onLogout={onLogout} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
