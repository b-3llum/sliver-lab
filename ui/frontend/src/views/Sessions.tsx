import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronRight, Server } from "lucide-react";
import { api } from "@/api";
import { bus } from "@/ws";
import type { SessionInfo } from "@/types";
import { Card, CardContent } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { CardList, DataCard } from "@/components/ui/DataCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { StateChip } from "@/components/ui/StateChip";
import { Button } from "@/components/ui/Button";

type SortKey = "hostname" | "username" | "os" | "transport" | "last_checkin";

export function Sessions() {
  const [rows, setRows] = useState<SessionInfo[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("hostname");
  const [err, setErr] = useState<string | null>(null);
  const nav = useNavigate();

  // Single source of truth for "attach this implant in the console" — used by
  // the desktop row click, the mobile card body, and the mobile action chip.
  const openConsole = (id: string) => nav(`/console?open=${encodeURIComponent(id)}`);

  async function refresh() {
    try {
      setRows(await api.get<SessionInfo[]>("/api/sessions"));
      setErr(null);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => { refresh(); }, []);
  useEffect(() => bus.subscribe((e) => {
    if (e.type.startsWith("session-")) refresh();
  }), []);

  const sorted = [...rows].sort((a, b) => {
    const va = (a[sortKey] ?? "") as string | number;
    const vb = (b[sortKey] ?? "") as string | number;
    return va < vb ? -1 : va > vb ? 1 : 0;
  });

  return (
    <div>
      <PageHeader
        title="Sessions"
        count={rows.length}
        action={err ? <span className="text-xs text-danger">{err}</span> : undefined}
      />
      <Card>
      <CardContent className="!p-0">
        {sorted.length === 0 && (
          <EmptyState
            icon={Server}
            title="No sessions"
            description="No interactive sessions yet."
            cta={<Link to="/build" className="text-accent2 hover:underline text-xs">build an implant →</Link>}
          />
        )}
        {/* mobile: cards */}
        <CardList>
          {sorted.map((s) => (
            <DataCard
              key={s.ID}
              title={s.hostname || "?"}
              rows={[
                ["user", s.username],
                ["os", `${s.os} / ${s.arch}`],
                ["transport", `${s.transport} ${s.remote_address}`],
                ["last", s.last_checkin ? new Date(s.last_checkin * 1000).toLocaleTimeString() : "—"],
                ["state", <StateChip kind={s.is_dead ? "dead" : "live"} />],
              ]}
              actions={
                <Button
                  size="sm"
                  className="flex-1 rounded-md font-mono"
                  onClick={() => openConsole(s.ID)}
                >
                  Open console
                </Button>
              }
            />
          ))}
        </CardList>
        {/* desktop: table */}
        <Table className="hidden sm:table">
          <THead>
            <TR>
              {(["hostname","username","os","transport","last_checkin"] as SortKey[]).map((k) => (
                <TH key={k} className="cursor-pointer select-none" onClick={() => setSortKey(k)}>
                  {k.replace("_", " ")} {sortKey === k && "▾"}
                </TH>
              ))}
              <TH>state</TH>
              <TH aria-hidden className="w-8" />
            </TR>
          </THead>
          <TBody>
            {sorted.map((s) => (
              <TR
                key={s.ID}
                className="group cursor-pointer transition-colors duration-[80ms] hover:bg-[rgba(56,189,248,0.08)]"
                onClick={() => openConsole(s.ID)}
                title={`session ${s.ID}`}
              >
                <TD>{s.hostname || <span className="text-muted">?</span>}</TD>
                <TD>{s.username}</TD>
                <TD>{s.os} / {s.arch}</TD>
                <TD>{s.transport} <span className="text-muted">{s.remote_address}</span></TD>
                <TD>{s.last_checkin ? new Date(s.last_checkin * 1000).toLocaleTimeString() : "—"}</TD>
                <TD>
                  <StateChip kind={s.is_dead ? "dead" : "live"} />
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
