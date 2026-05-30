// Tiny dependency-free toast bus. `toast.success/error/info` push a message;
// the <ToastHost> (mounted once in the app shell) subscribes and renders.

export type ToastKind = "success" | "error" | "info";

export interface ToastItem {
  id: number;
  kind: ToastKind;
  msg: string;
}

type Listener = (t: ToastItem) => void;

let _id = 0;
const listeners = new Set<Listener>();

function emit(kind: ToastKind, msg: string): void {
  const item: ToastItem = { id: ++_id, kind, msg };
  for (const l of listeners) l(item);
}

export const toast = {
  success: (msg: string) => emit("success", msg),
  error: (msg: string) => emit("error", msg),
  info: (msg: string) => emit("info", msg),
};

export function subscribeToasts(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Auto-dismiss timing — errors linger longer so they aren't missed. */
export function toastTTL(kind: ToastKind): number {
  return kind === "error" ? 8000 : 4000;
}
