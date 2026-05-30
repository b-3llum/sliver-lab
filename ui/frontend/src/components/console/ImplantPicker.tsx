import { useEffect, useState } from "react";
import { api } from "@/api";
import type { BeaconInfo, SessionInfo } from "@/types";
import { Sheet } from "@/components/chrome/Sheet";
import { cn } from "@/lib/cn";

interface Pick { id: string; kind: "session" | "beacon"; label: string; sub: string }

export function ImplantPicker({
  openIds, onPick, onClose,
}: {
  openIds: Set<string>;
  onPick: (id: string, kind: "session" | "beacon") => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<Pick[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<SessionInfo[]>("/api/sessions").catch(() => [] as SessionInfo[]),
      api.get<BeaconInfo[]>("/api/beacons").catch(() => [] as BeaconInfo[]),
    ]).then(([ss, bs]) => {
      const out: Pick[] = [];
      for (const s of ss) {
        out.push({
          id: s.ID, kind: "session",
          label: `${s.username || "?"}@${s.hostname || "?"}`,
          sub: `${s.os}/${s.arch} · ${s.transport}`,
        });
      }
      for (const b of bs) {
        out.push({
          id: b.ID, kind: "beacon",
          label: `${b.username || "?"}@${b.hostname || "?"}`,
          sub: `${b.os}/${b.arch} · ${b.transport} · ${Math.round(b.interval / 1e9)}s`,
        });
      }
      setItems(out);
    }).catch((e: any) => setErr(e.message));
  }, []);

  return (
    <Sheet open onClose={onClose} side="center" title="Attach implant" className="p-1">
      {err && <div className="text-xs text-danger p-2">{err}</div>}
      {items.length === 0 && !err && (
        <div className="text-xs text-muted p-3">No active implants. Start a listener and deploy one.</div>
      )}
      {items.map((it) => {
        const already = openIds.has(it.id);
        return (
          <button
            key={it.id}
            disabled={already}
            onClick={() => { onPick(it.id, it.kind); onClose(); }}
            className={cn(
              "w-full text-left px-3 py-2 rounded flex items-center gap-2 text-xs max-lg:min-h-[44px]",
              already ? "opacity-40 cursor-not-allowed" : "hover:bg-panel2 cursor-pointer",
            )}
          >
            <span className={cn(
              "inline-block w-2 h-2 rounded-full",
              it.kind === "beacon" ? "bg-amber-500" : "bg-accent",
            )} />
            <div className="flex-1">
              <div className="font-mono">{it.label}</div>
              <div className="text-[10px] text-muted">{it.sub}</div>
            </div>
            <span className="text-[10px] text-muted">{it.kind}</span>
            {already && <span className="text-[10px] text-muted">· open</span>}
          </button>
        );
      })}
    </Sheet>
  );
}
