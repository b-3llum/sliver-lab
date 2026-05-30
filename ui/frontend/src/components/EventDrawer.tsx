import { useEffect, useMemo, useRef, useState } from "react";
import { bus } from "@/ws";
import type { EventEnvelope } from "@/types";
import { cn } from "@/lib/cn";

const MAX_EVENTS = 500;

const FILTERS = [
  { key: "all", label: "all" },
  { key: "session", label: "sessions" },
  { key: "beacon", label: "beacons" },
  { key: "job", label: "jobs" },
  { key: "bff", label: "bff" },
] as const;

function toneOf(type: string): string {
  if (type.startsWith("bff:disconnected") || type.includes("error")) return "text-danger";
  if (type.startsWith("session-connected") || type === "bff:connected") return "text-accent";
  if (type.startsWith("session-disconnected")) return "text-warn";
  if (type.startsWith("beacon")) return "text-accent2";
  return "text-text";
}

export function EventDrawer({ bare = false }: { bare?: boolean }) {
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => bus.subscribe((e) => {
    setEvents((prev) => {
      const next = [...prev, { ...e, _t: Date.now() } as any];
      if (next.length > MAX_EVENTS) next.shift();
      return next;
    });
  }), []);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [events]);

  const filtered = useMemo(
    () => events.filter((e) => filter === "all" || e.type.startsWith(filter)),
    [events, filter],
  );

  // `bare` drops the column chrome so AppShell can place the body inside a
  // mobile Sheet (which already provides the "Events" title bar).
  const body = (
    <>
      {!bare && (
        <div className="px-3 py-2 border-b border-border">
          <div className="text-xs font-semibold mb-1.5">Events</div>
          <Filters filter={filter} setFilter={setFilter} />
        </div>
      )}
      {bare && (
        <div className="px-3 py-2 border-b border-border">
          <Filters filter={filter} setFilter={setFilter} />
        </div>
      )}
      <div ref={ref} className="flex-1 overflow-y-auto text-[10px] font-mono">
        {filtered.length === 0 && (
          <div className="p-3 text-muted">No events yet.</div>
        )}
        {filtered.map((e, i) => (
          <div key={i} className="border-b border-border/50 px-2 py-1">
            <div className={cn("font-semibold", toneOf(e.type))}>{e.type}</div>
            <pre className="text-muted whitespace-pre-wrap break-all">
              {summarize(e)}
            </pre>
          </div>
        ))}
      </div>
    </>
  );

  if (bare) return <div className="flex h-full flex-col">{body}</div>;
  return (
    <aside className="w-80 shrink-0 border-l border-border bg-panel flex flex-col">
      {body}
    </aside>
  );
}

function Filters({ filter, setFilter }: { filter: string; setFilter: (f: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1">
      {FILTERS.map((f) => (
        <button
          key={f.key}
          onClick={() => setFilter(f.key)}
          className={cn(
            "px-1.5 py-0.5 rounded text-[10px] border max-lg:min-h-[44px] max-lg:px-3",
            filter === f.key
              ? "border-accent2 text-accent2"
              : "border-border text-muted hover:text-text",
          )}
        >
          {f.label}
        </button>
      ))}
    </div>
  );
}

function summarize(e: EventEnvelope): string {
  const d = e.data || {};
  const bits: string[] = [];
  for (const k of ["session", "beacon", "job"]) {
    const v: any = d[k];
    if (v && typeof v === "object") {
      const id = v.ID || v.id;
      const host = v.Hostname || v.hostname;
      if (id || host) bits.push(`${k}: ${[id, host].filter(Boolean).join(" / ")}`);
    }
  }
  if ((d as any).err) bits.push(`err: ${(d as any).err}`);
  if ((d as any).version) bits.push(`version: ${(d as any).version}`);
  return bits.join("\n");
}
