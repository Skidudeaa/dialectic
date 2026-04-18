// Toast hook + shared types.
//
// Lives in its own file so that Toast.tsx only exports React components —
// fast refresh requires component-only files.

import { createContext, useContext } from "react";

export type ToastType = "success" | "error" | "warning" | "info";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  type?: ToastType;
  /** Override auto-dismiss in milliseconds. Pass 0 (or any non-positive value) to require manual dismiss. */
  duration?: number;
  /** Optional inline action button (e.g. "Retry", "Undo"). */
  action?: ToastAction;
}

export interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
  action?: ToastAction;
}

export interface ToastContextType {
  toast: (message: string, typeOrOpts?: ToastType | ToastOptions) => number;
  dismiss: (id: number) => void;
}

export const ToastContext = createContext<ToastContextType>({
  toast: () => 0,
  dismiss: () => {},
});

export function useToast() {
  return useContext(ToastContext);
}
