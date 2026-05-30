import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { subscribeToasts, toastTTL, type ToastItem } from "@/lib/toast";
import { useBreakpoint } from "@/hooks/useBreakpoint";
import { Z } from "@/lib/tokens";
import { cn } from "@/lib/cn";

const MAX_VISIBLE = 3;

const TONE: Record<ToastItem["kind"], { icon: typeof Info; cls: string }> = {
  success: { icon: CheckCircle2, cls: "text-accent border-accent/40" },
  error: { icon: AlertCircle, cls: "text-danger border-danger/40" },
  info: { icon: Info, cls: "text-accent2 border-accent2/40" },
};

/**
 * Toast stack. Top-right on desktop/tablet, top-center on phone (thumb reach).
 * Shows up to 3 at once; older ones coalesce into a "+N more" pill. Tap to
 * dismiss; auto-dismiss after 4s (errors 8s).
 */
export function ToastHost() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const phone = useBreakpoint() === "phone";

  useEffect(() => subscribeToasts((t) => {
    setItems((prev) => [...prev, t]);
    const ttl = toastTTL(t.kind);
    setTimeout(() => setItems((prev) => prev.filter((x) => x.id !== t.id)), ttl);
  }), []);

  function dismiss(id: number) {
    setItems((prev) => prev.filter((x) => x.id !== id));
  }

  if (items.length === 0) return null;

  // Newest first; show the latest MAX_VISIBLE, coalesce the rest.
  const ordered = [...items].reverse();
  const visible = ordered.slice(0, MAX_VISIBLE);
  const overflow = ordered.length - visible.length;

  return (
    <div
      className={cn(
        "fixed top-2 flex flex-col gap-1.5 pointer-events-none",
        phone ? "left-2 right-2 items-center" : "right-2 items-end",
      )}
      style={{ zIndex: Z.toast }}
    >
      {visible.map((t) => {
        const { icon: Icon, cls } = TONE[t.kind];
        return (
          <button
            key={t.id}
            onClick={() => dismiss(t.id)}
            className={cn(
              "chrome-toast pointer-events-auto flex items-start gap-2 rounded border bg-panel",
              "px-3 py-2 text-xs font-mono shadow-xl text-left",
              phone ? "w-full" : "max-w-sm",
              cls,
            )}
          >
            <Icon size={14} className="shrink-0 mt-px" />
            <span className="flex-1 break-words text-text">{t.msg}</span>
            <X size={12} className="shrink-0 mt-px text-muted" />
          </button>
        );
      })}
      {overflow > 0 && (
        <div className="pointer-events-none rounded border border-border bg-panel px-2 py-1 text-[10px] text-muted">
          +{overflow} more
        </div>
      )}
    </div>
  );
}
