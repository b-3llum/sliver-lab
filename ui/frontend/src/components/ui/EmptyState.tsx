import { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/**
 * Standardized empty state: greyscale icon, mono-base title, mono-sm muted
 * description, optional CTA. Operator-direct copy — no cute.
 */
export function EmptyState({
  icon: Icon, title, description, cta,
}: {
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
  cta?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center gap-2 py-12 px-4">
      <Icon size={32} strokeWidth={1.5} className="text-muted" />
      <div className="text-sm font-mono">{title}</div>
      {description && <div className="text-xs font-mono text-muted max-w-md">{description}</div>}
      {cta && <div className="pt-1">{cta}</div>}
    </div>
  );
}
