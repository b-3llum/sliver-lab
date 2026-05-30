/**
 * Tunnels — manage portfwd / rportfwd / socks5 per active session.
 *
 * Beacons can't carry real-time tunnels (no bidirectional stream); we hide
 * them here and surface the "promote first" hint in the empty state.
 *
 * Each session gets a card with three sub-sections, an inline "+ Add"
 * form per kind, and a per-row Stop button. Started-at is rendered as a
 * compact "Ns/Nm ago" relative time.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { ApiError, createPortfwd, createRportfwd, createSocks5,
  deleteTunnel, listTunnels } from "@/api";
import type {
  SessionInfo, TunnelKind, TunnelList, TunnelRecord,
} from "@/types";
import { api } from "@/api";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Input, Label } from "@/components/ui/Input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { Sheet } from "@/components/chrome/Sheet";
import { useBreakpoint } from "@/hooks/useBreakpoint";
import { cn } from "@/lib/cn";

const KIND_LABEL: Record<TunnelKind, string> = {
  portfwd: "Port forwards",
  rportfwd: "Reverse port forwards",
  socks5: "SOCKS5 proxies",
};

const KIND_HELP: Record<TunnelKind, string> = {
  portfwd: "local listen → through session → remote endpoint on target side",
  rportfwd: "target listens → through session → back to this operator",
  socks5: "local SOCKS5 proxy → all traffic egresses through the session",
};

function relTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (!t) return "—";
  const secs = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ${mins % 60}m ago`;
}

export function Tunnels() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [tunnelsBySession, setTunnelsBySession] = useState<Record<string, TunnelList>>({});
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const ss = await api.get<SessionInfo[]>("/api/sessions");
      const alive = ss.filter((s) => !s.is_dead);
      setSessions(alive);
      const next: Record<string, TunnelList> = {};
      await Promise.all(alive.map(async (s) => {
        try {
          next[s.ID] = await listTunnels(s.ID);
        } catch {
          next[s.ID] = { portfwds: [], rportfwds: [], socks5: [] };
        }
      }));
      setTunnelsBySession(next);
      setErr(null);
    } catch (e: any) {
      setErr(e.message ?? String(e));
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  // Light polling — the registry doesn't push state changes; 5 s keeps
  // started_at fresh and shows newly added/removed tunnels even when
  // multiple operators are on this BFF.
  useEffect(() => {
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Tunnels"
        caption="Session-only. Each tunnel runs as a long-lived sliver-client subprocess on this host; restarting the BFF tears them all down."
        action={err ? <span className="text-xs text-danger">{err}</span> : undefined}
      />

      {sessions.length === 0 && (
        <Card>
          <CardContent className="p-4 text-xs text-muted italic">
            no active sessions; tunneling requires a session. promote a beacon from the Graph
            or Console (<code>interactive</code>) to enable.
          </CardContent>
        </Card>
      )}

      {sessions.map((s) => (
        <SessionTunnelsCard
          key={s.ID}
          session={s}
          list={tunnelsBySession[s.ID] ?? { portfwds: [], rportfwds: [], socks5: [] }}
          onChanged={refresh}
        />
      ))}
    </div>
  );
}

// ── per-session card ─────────────────────────────────────────────

function SessionTunnelsCard({
  session, list, onChanged,
}: {
  session: SessionInfo;
  list: TunnelList;
  onChanged: () => void;
}) {
  const phone = useBreakpoint() === "phone";
  const [open, setOpen] = useState(false);
  const expanded = !phone || open;
  const count = list.portfwds.length + list.rportfwds.length + list.socks5.length;
  return (
    <Card>
      <CardHeader
        className={cn(phone && "cursor-pointer select-none")}
        onClick={phone ? () => setOpen((o) => !o) : undefined}
      >
        <CardTitle className="text-sm">
          {session.username || "?"}@{session.hostname || "?"}
          <span className="text-muted ml-2 text-xs">
            · {session.transport} · pid {session.pid} · {session.ID.slice(0, 8)}…
          </span>
          {phone && <span className="ml-2 text-xs text-muted">({count}) {open ? "▾" : "▸"}</span>}
        </CardTitle>
      </CardHeader>
      {expanded && (
        <CardContent className="space-y-4">
          <TunnelSection sessionId={session.ID} kind="portfwd" rows={list.portfwds} onChanged={onChanged} />
          <TunnelSection sessionId={session.ID} kind="rportfwd" rows={list.rportfwds} onChanged={onChanged} />
          <TunnelSection sessionId={session.ID} kind="socks5" rows={list.socks5} onChanged={onChanged} />
        </CardContent>
      )}
    </Card>
  );
}

// ── per-kind sub-section ─────────────────────────────────────────

function TunnelSection({
  sessionId, kind, rows, onChanged,
}: {
  sessionId: string;
  kind: TunnelKind;
  rows: TunnelRecord[];
  onChanged: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const phone = useBreakpoint() === "phone";

  async function stop(id: string) {
    try {
      await deleteTunnel(sessionId, kind, id);
      onChanged();
    } catch {
      // refresh anyway — the next poll might already reflect the change.
      onChanged();
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <div>
          <div className="text-xs font-semibold">{KIND_LABEL[kind]}</div>
          <div className="text-[10px] text-muted">{KIND_HELP[kind]}</div>
        </div>
        <Button size="sm" variant="outline" onClick={() => setAdding((a) => !a)}>
          {adding ? "Cancel" : <><Plus size={12} className="mr-1" /> Add</>}
        </Button>
      </div>
      {/* desktop: inline form; phone: bottom-sheet (keeps content from jumping) */}
      {adding && !phone && (
        <AddForm
          kind={kind}
          sessionId={sessionId}
          onDone={() => { setAdding(false); onChanged(); }}
        />
      )}
      {phone && (
        <Sheet open={adding} onClose={() => setAdding(false)} side="bottom" title={`Add ${KIND_LABEL[kind]}`}>
          <div className="p-3">
            <AddForm
              kind={kind}
              sessionId={sessionId}
              onDone={() => { setAdding(false); onChanged(); }}
            />
          </div>
        </Sheet>
      )}
      <div className="overflow-x-auto">
      <Table>
        <THead>
          <TR>
            <TH>bind</TH>
            {kind !== "socks5" && <TH>remote</TH>}
            <TH>started</TH>
            <TH></TH>
          </TR>
        </THead>
        <TBody>
          {rows.map((t) => (
            <TR key={t.id}>
              <TD className="font-mono">{t.bind_addr}:{t.bind_port}</TD>
              {kind !== "socks5" && (
                <TD className="font-mono">{t.remote_addr}:{t.remote_port}</TD>
              )}
              <TD className={cn("text-muted", !t.marker_seen && "italic text-amber-500")}>
                {t.marker_seen ? relTime(t.started_at) : "starting…"}
              </TD>
              <TD className="text-right">
                {t.marker_seen ? (
                  <Button size="sm" variant="danger" onClick={() => stop(t.id)}>
                    <X size={11} className="mr-1" /> Stop
                  </Button>
                ) : (
                  <span className="text-[10px] text-amber-500 italic">awaiting marker</span>
                )}
              </TD>
            </TR>
          ))}
          {rows.length === 0 && (
            <TR>
              <TD colSpan={kind === "socks5" ? 3 : 4} className="text-center text-muted italic py-3 text-xs">
                no {kind === "socks5" ? "socks5 proxies" : kind + "s"}
              </TD>
            </TR>
          )}
        </TBody>
      </Table>
      </div>
    </div>
  );
}

// ── inline add form ─────────────────────────────────────────────

function AddForm({
  kind, sessionId, onDone,
}: {
  kind: TunnelKind;
  sessionId: string;
  onDone: () => void;
}) {
  const [bindAddr, setBindAddr] = useState(kind === "rportfwd" ? "0.0.0.0" : "127.0.0.1");
  const [bindPort, setBindPort] = useState(kind === "socks5" ? 1080 : 0);
  const [remoteAddr, setRemoteAddr] = useState("127.0.0.1");
  const [remotePort, setRemotePort] = useState(80);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true); setErr(null);
    try {
      if (kind === "socks5") {
        await createSocks5(sessionId, { bind_addr: bindAddr, bind_port: bindPort });
      } else if (kind === "portfwd") {
        await createPortfwd(sessionId, {
          bind_addr: bindAddr, bind_port: bindPort,
          remote_addr: remoteAddr, remote_port: remotePort,
        });
      } else {
        await createRportfwd(sessionId, {
          bind_addr: bindAddr, bind_port: bindPort,
          remote_addr: remoteAddr, remote_port: remotePort,
        });
      }
      onDone();
    } catch (e: unknown) {
      setErr(e instanceof ApiError ? `[${e.status}] ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-panel2/40 border border-border rounded p-2 mb-2">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:items-end">
        <div className="space-y-1">
          <Label>bind_addr</Label>
          <Input
            value={bindAddr}
            onChange={(e) => setBindAddr(e.target.value)}
            placeholder="127.0.0.1"
            className="font-mono"
          />
        </div>
        <div className="space-y-1">
          <Label>bind_port</Label>
          <Input
            type="number"
            value={bindPort || ""}
            onChange={(e) => setBindPort(Number(e.target.value) || 0)}
          />
        </div>
        {kind !== "socks5" && (
          <>
            <div className="space-y-1">
              <Label>remote_addr</Label>
              <Input
                value={remoteAddr}
                onChange={(e) => setRemoteAddr(e.target.value)}
                placeholder="127.0.0.1"
                className="font-mono"
              />
            </div>
            <div className="space-y-1">
              <Label>remote_port</Label>
              <Input
                type="number"
                value={remotePort || ""}
                onChange={(e) => setRemotePort(Number(e.target.value) || 0)}
              />
            </div>
          </>
        )}
      </div>
      <div className="flex items-center justify-end mt-2 gap-2">
        {err && <span className="text-[10px] text-danger max-w-md truncate" title={err}>{err}</span>}
        <Button size="sm" onClick={submit} disabled={busy || !bindPort}>
          {busy ? "starting…" : "Start"}
        </Button>
      </div>
    </div>
  );
}
