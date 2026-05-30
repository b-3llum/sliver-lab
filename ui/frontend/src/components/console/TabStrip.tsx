import { useEffect, useRef } from "react";
import { Plus, X } from "lucide-react";
import { cn } from "@/lib/cn";

export interface ConsoleTab {
  id: string;
  label: string;
  kind: "session" | "beacon";
  pending: number;     // # of in-flight tasks (drives dot indicator)
}

export function TabStrip({
  tabs, activeId, onSelect, onClose, onAdd,
}: {
  tabs: ConsoleTab[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onAdd: () => void;
}) {
  const activeRef = useRef<HTMLDivElement>(null);
  // Keep the active tab visible when switching (esp. on a scrolled mobile strip).
  useEffect(() => {
    activeRef.current?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [activeId]);

  return (
    <div className="flex items-stretch border-b border-border bg-panel overflow-x-auto">
      {tabs.map((t) => (
        <div
          key={t.id}
          ref={activeId === t.id ? activeRef : undefined}
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 border-r border-border cursor-pointer text-xs",
            "shrink-0 whitespace-nowrap transition-colors duration-100 max-lg:min-h-[44px]",
            activeId === t.id ? "bg-panel2 text-text" : "text-muted hover:text-text",
          )}
          onClick={() => onSelect(t.id)}
        >
          <span className={cn(
            "inline-block w-2 h-2 rounded-full",
            t.kind === "beacon" ? "bg-amber-500" : "bg-accent",
          )} />
          <span className="font-mono">{t.label}</span>
          {t.pending > 0 && (
            <span className="text-[9px] text-amber-500" title={`${t.pending} pending`}>●</span>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onClose(t.id); }}
            className="text-muted hover:text-danger ml-1 max-lg:p-1"
            title="Close tab"
          >
            <X size={11} />
          </button>
        </div>
      ))}
      {/* "+ open" pinned to the right edge over the scrolling tabs. */}
      <button
        onClick={onAdd}
        className="px-3 py-1.5 text-xs text-muted hover:text-text flex items-center gap-1 shrink-0 sticky right-0 bg-panel border-l border-border max-lg:min-h-[44px]"
        title="Attach an implant"
      >
        <Plus size={12} /> open
      </button>
    </div>
  );
}
