import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";
import { bus } from "@/ws";
import { toast } from "@/lib/toast";
import type { BeaconInfo } from "@/types";
import { Activity, ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { CardList, DataCard } from "@/components/ui/DataCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { StateChip } from "@/components/ui/StateChip";

export function Beacons() {
  const [rows, setRows] = useState<BeaconInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const nav = useNavigate();

  // Single source of truth for "attach this beacon in the console" — used by
  // the desktop row click and both mobile action chips.
  const openConsole = (id: string) => nav(`/console?open=${encodeURIComponent(id)}`);

  // Promote a beacon to an interactive session, then drop the operator into
  // its console to watch the task collapse (mirrors the Graph context menu).
  async function promote(b: BeaconInfo) {
    try {
      await api.post(`/api/implants/${encodeURIComponent(b.ID)}/interactive`, {});
      openConsole(b.ID);
    } catch (e: any) {
      toast.error(`Promote failed: ${e?.message ?? String(e)}`);
    }
  }

  async function refresh() {
    try {
      setRows(await api.get<BeaconInfo[]>("/api/beacons"));
      setErr(null);
    } catch (e: any) { setErr(e.message); }
  }

  useEffect(() => { refresh(); }, []);
  useEffect(() => bus.subscribe((e) => {
    if (e.type.startsWith("beacon")) refresh();
  }), []);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const staleCount = rows.filter((b) => b.stale).length;

  async function forget(b: BeaconInfo) {
    if (!confirm(
      `Forget beacon ${b.hostname || b.ID}? This removes the server-side row; it does not affect a live implant.`,
    )) return;
    setRows((prev) => prev.filter((r) => r.ID !== b.ID));
    try { await api.del(`/api/beacons/${encodeURIComponent(b.ID)}`); await refresh(); }
    catch (e: any) { setErr(e.message); await refresh(); }
  }

  async function forgetStale() {
    if (!confirm(
      `Forget ${staleCount} stale beacons? This removes the server-side rows; live implants are not affected.`,
    )) return;
    try { await api.del(`/api/beacons/stale`); await refresh(); }
    catch (e: any) { setErr(e.message); await refresh(); }
  }

  return (
    <div>
      <PageHeader
        title="Beacons"
        count={rows.length}
        action={
          <>
            {err && <span className="text-xs text-danger">{err}</span>}
            {staleCount > 0 && (
              <Button variant="danger" size="sm" onClick={forgetStale}>
                Forget stale ({staleCount})
              </Button>
            )}
          </>
        }
      />
      <Card>
      <CardContent className="!p-0">
        {rows.length === 0 && (
          <EmptyState icon={Activity} title="No beacons" description="No beacons have called back yet." />
        )}
        {/* mobile: cards */}
        <CardList>
          {rows.map((b) => (
            <DataCard
              key={b.ID}
              title={b.hostname || "?"}
              rows={[
                ["status", <StateChip kind={b.stale ? "stale" : "live"} />],
                ["user", b.username],
                ["os", `${b.os}/${b.arch}`],
                ["transport", `${b.transport} ${b.remote_address}`],
                ["next", countdown(b.next_checkin, now)],
                ["pending", b.tasks_count - b.tasks_count_completed],
              ]}
              actions={
                <>
                  <Button
                    size="sm"
                    className="flex-1 rounded-md font-mono"
                    onClick={() => openConsole(b.ID)}
                  >
                    Open console
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1 rounded-md font-mono"
                    disabled={b.stale}
                    title={b.stale ? "stale; can't promote" : undefined}
                    onClick={() => promote(b)}
                  >
                    Promote
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-md font-mono"
                    onClick={() => forget(b)}
                  >
                    forget
                  </Button>
                </>
              }
            />
          ))}
        </CardList>
        {/* desktop: table */}
        <Table className="hidden sm:table">
          <THead>
            <TR>
              <TH>hostname</TH><TH>user</TH><TH>os</TH><TH>transport</TH>
              <TH>next check-in</TH><TH>pending</TH><TH>status</TH><TH></TH>
              <TH aria-hidden className="w-8" />
            </TR>
          </THead>
          <TBody>
            {rows.map((b) => (
              <TR
                key={b.ID}
                className="group cursor-pointer transition-colors duration-[80ms] hover:bg-[rgba(56,189,248,0.08)]"
                onClick={() => openConsole(b.ID)}
                title={`beacon ${b.ID}`}
              >
                <TD>{b.hostname || "?"}</TD>
                <TD>{b.username}</TD>
                <TD>{b.os}/{b.arch}</TD>
                <TD>{b.transport} <span className="text-muted">{b.remote_address}</span></TD>
                <TD>{countdown(b.next_checkin, now)}</TD>
                <TD>{b.tasks_count - b.tasks_count_completed}</TD>
                <TD>
                  <StateChip kind={b.stale ? "stale" : "live"} />
                </TD>
                {/* stopPropagation: the forget button is a row-local action and
                    must not also fire the row's open-console navigation. */}
                <TD className="text-right" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    onClick={() => forget(b)}
                    className="text-xs text-muted hover:text-danger"
                    title="Forget this beacon (remove the server-side row)"
                  >
                    forget
                  </button>
                </TD>
                <TD className="text-right">
                  {/* resting = COLOR.fgMuted (tokens.ts), shifting to accent
                      (green) on row hover as the interaction cue. */}
                  <ChevronRight
                    size={14}
                    className="inline text-[rgba(215,221,227,0.5)] transition-colors duration-[80ms] group-hover:text-accent"
                  />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </CardContent>
      </Card>
    </div>
  );
}

function countdown(ts: number, now: number): string {
  if (!ts) return "—";
  const remaining = ts * 1000 - now;
  if (remaining < 0) return "due";
  const s = Math.floor(remaining / 1000);
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}
