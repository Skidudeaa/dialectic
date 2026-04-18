import { useState, useCallback, useRef, createContext, useContext, type ReactNode } from "react";
import { X, AlertTriangle, AlertOctagon, CheckCircle, Info } from "lucide-react";

export type ToastType = "success" | "error" | "warning" | "info";

interface ToastAction {
  label: string;
  onClick: () => void;
}

interface ToastOptions {
  type?: ToastType;
  /** Override auto-dismiss in milliseconds. Pass 0 (or any non-positive value) to require manual dismiss. */
  duration?: number;
  /** Optional inline action button (e.g. "Retry", "Undo"). */
  action?: ToastAction;
}

interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
  action?: ToastAction;
}

interface ToastContextType {
  toast: (message: string, typeOrOpts?: ToastType | ToastOptions) => number;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextType>({
  toast: () => 0,
  dismiss: () => {},
});

export function useToast() {
  return useContext(ToastContext);
}

let _nextId = 0;

// Type-specific TTL: errors persist longer (or until dismissed),
// success/info fade quickly, warnings sit a bit longer than info.
const DEFAULT_DURATION_MS: Record<ToastType, number> = {
  success: 3500,
  info: 5000,
  warning: 7000,
  error: 9000,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    const t = timers.current.get(id);
    if (t) {
      clearTimeout(t);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, typeOrOpts: ToastType | ToastOptions = "info"): number => {
      const opts: ToastOptions =
        typeof typeOrOpts === "string" ? { type: typeOrOpts } : typeOrOpts;
      const type = opts.type ?? "info";
      const id = _nextId++;

      setToasts((prev) => [...prev, { id, message, type, action: opts.action }]);

      const duration = opts.duration ?? DEFAULT_DURATION_MS[type];
      if (duration > 0) {
        const handle = setTimeout(() => {
          timers.current.delete(id);
          setToasts((prev) => prev.filter((t) => t.id !== id));
        }, duration);
        timers.current.set(id, handle);
      }
      return id;
    },
    [],
  );

  return (
    <ToastContext.Provider value={{ toast, dismiss }}>
      {children}
      {/* Toast container — bottom-right, oldest on bottom (top of column),
          so newest sits closest to where the user's attention lands. */}
      <div
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm pointer-events-none"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <ToastRow key={t.id} item={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastRow({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const styles = STYLES[item.type];
  const Icon = styles.Icon;
  // Errors get role="alert" (assertive); the rest are status (polite).
  const role = item.type === "error" ? "alert" : "status";

  return (
    <div
      role={role}
      className={`pointer-events-auto flex items-start gap-2 px-3 py-2 rounded border text-sm shadow-lg animate-fade-in ${styles.cls}`}
    >
      <Icon size={14} className="shrink-0 mt-0.5" aria-hidden="true" />
      <span className="flex-1 min-w-0 break-words">{item.message}</span>
      {item.action && (
        <button
          onClick={() => {
            item.action!.onClick();
            onDismiss();
          }}
          className="shrink-0 text-[11px] font-mono uppercase tracking-wide opacity-90 hover:opacity-100 underline-offset-2 hover:underline"
        >
          {item.action.label}
        </button>
      )}
      <button
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="shrink-0 opacity-60 hover:opacity-100"
      >
        <X size={12} />
      </button>
    </div>
  );
}

const STYLES: Record<ToastType, { cls: string; Icon: typeof Info }> = {
  error: {
    cls: "bg-danger/10 border-danger/30 text-danger",
    Icon: AlertOctagon,
  },
  warning: {
    cls: "bg-warning/10 border-warning/30 text-warning",
    Icon: AlertTriangle,
  },
  success: {
    cls: "bg-teal/10 border-teal/30 text-teal",
    Icon: CheckCircle,
  },
  info: {
    cls: "bg-surface border-border text-text-primary",
    Icon: Info,
  },
};
