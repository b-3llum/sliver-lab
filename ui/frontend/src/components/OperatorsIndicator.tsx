import { useEffect, useRef, useState } from "react";
import { Users } from "lucide-react";
import { api } from "@/api";
import type { OperatorInfo } from "@/types";
import { cn } from "@/lib/cn";

const POLL_MS = 30_000;

/**
 * Bottom-of-sidebar chip showing the live operator count. Click → popover
 * (right of the sidebar) listing names + online status. sliver-py's Operator
 * proto carries no joined-at, so we show online/offline instead. Polls every
 * 30s — operator changes are rare, so no WS push.
 */
export function OperatorsIndicator() {
  const [ops, setOps] = useState<OperatorInfo[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const load = () => api.get<OperatorInfo[]>("/api/operators").then(setOps).catch(() => {});
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, []);

  // Close on Esc or click outside.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-[10px] text-muted hover:text-text"
        title="connected operators"
      >
        <Users size={12} />
        <span>operators: {ops.length}</span>
      </button>
      {open && (
        <div className="absolute left-full bottom-0 ml-1 z-50 w-48 rounded border border-border bg-panel shadow-xl p-1">
          <div className="px-2 py-1 text-[10px] text-muted border-b border-border">
            connected operators
          </div>
          {ops.map((o) => (
            <div key={o.name} className="flex items-center justify-between px-2 py-1 text-xs">
              <span className="font-mono">{o.name}</span>
              <span className={cn("text-[10px]", o.online ? "text-accent" : "text-muted")}>
                {o.online ? "online" : "offline"}
              </span>
            </div>
          ))}
          {ops.length === 0 && (
            <div className="px-2 py-2 text-[10px] text-muted">none reported</div>
          )}
        </div>
      )}
    </div>
  );
}
