import { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Mobile card list — the <640px counterpart to a dense desktop table. Each view
 * renders its table inside `hidden sm:block` and a <CardList> alongside marked
 * `sm:hidden`, so the breakpoint switch is pure CSS (no logic fork; same data).
 */
export function CardList({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("sm:hidden divide-y divide-border", className)}>{children}</div>;
}

/** One row rendered as a card: primary label, key/value body, optional actions. */
export function DataCard({
  title, rows, actions, dim,
}: {
  title: ReactNode;
  rows: Array<[string, ReactNode]>;
  actions?: ReactNode;
  /** Visually de-emphasize (e.g. stale beacon). */
  dim?: boolean;
}) {
  return (
    <div className={cn("p-3 space-y-1.5", dim && "italic opacity-50")}>
      <div className="font-mono text-xs font-semibold break-all">{title}</div>
      <dl className="space-y-0.5 text-[11px] font-mono">
        {rows.map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <dt className="text-muted w-24 shrink-0">{k}</dt>
            <dd className="flex-1 break-all">{v}</dd>
          </div>
        ))}
      </dl>
      {actions && <div className="flex flex-wrap gap-2 pt-1">{actions}</div>}
    </div>
  );
}
