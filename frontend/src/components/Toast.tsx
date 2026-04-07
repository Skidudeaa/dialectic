import { useState, useCallback, createContext, useContext, type ReactNode } from "react";
import { X, AlertTriangle, CheckCircle, Info } from "lucide-react";

interface ToastItem {
  id: number;
  message: string;
  type: "success" | "error" | "info";
}

interface ToastContextType {
  toast: (message: string, type?: "success" | "error" | "info") => void;
}

const ToastContext = createContext<ToastContextType>({ toast: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

let _nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, type: "success" | "error" | "info" = "info") => {
    const id = _nextId++;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {/* Toast container */}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`flex items-start gap-2 px-3 py-2 rounded border text-sm shadow-lg ${
              t.type === "error"
                ? "bg-danger/10 border-danger/30 text-danger"
                : t.type === "success"
                ? "bg-teal/10 border-teal/30 text-teal"
                : "bg-surface border-border text-text-primary"
            }`}
          >
            {t.type === "error" && <AlertTriangle size={14} className="shrink-0 mt-0.5" />}
            {t.type === "success" && <CheckCircle size={14} className="shrink-0 mt-0.5" />}
            {t.type === "info" && <Info size={14} className="shrink-0 mt-0.5" />}
            <span className="flex-1 min-w-0">{t.message}</span>
            <button onClick={() => dismiss(t.id)} className="shrink-0 opacity-60 hover:opacity-100">
              <X size={12} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
