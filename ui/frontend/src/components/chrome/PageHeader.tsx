import { ReactNode } from "react";

/**
 * Standard page header — title rhythm shared by every routed view.
 * title = mono-lg semibold, count = mono-base muted in parens, caption =
 * displaySm (the one proportional exception) muted on the line below, action
 * right-aligned at the title baseline. 24px vertical padding, 1px divider.
 */
export function PageHeader({
  title, count, caption, action,
}: {
  title: ReactNode;
  count?: number;
  caption?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border py-6 mb-4">
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <h1 className="font-mono text-base font-semibold text-text truncate">{title}</h1>
          {count !== undefined && (
            <span className="font-mono text-sm text-muted shrink-0">({count})</span>
          )}
        </div>
        {caption && (
          <div className="font-sans text-xs text-muted mt-1">{caption}</div>
        )}
      </div>
      {action && <div className="shrink-0 flex items-center gap-3">{action}</div>}
    </div>
  );
}
