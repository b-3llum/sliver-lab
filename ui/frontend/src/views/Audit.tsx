import { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import type { AuditEntry, AuditResponse } from "@/types";
import { ChevronRight, ScrollText } from "lucide-react";
import { cn } from "@/lib/cn";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

const POLL_MS = 10_000;

export function Audit() {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [operator, setOperator] = useState("");
  const [action, setAction] = useState("");
  const [paused, setPaused] = useState(false);
  const [showPolling, setShowPolling] = useState(false);
  const [now, setNow] = useState(Date.now());

  async function refresh() {
    try {
      const r = await api.get<AuditResponse>(`/api/audit?limit=200&include_polling=${showPolling}`);
      setRows(r.entries);
      setErr(null);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  // Re-fetch on mount and whenever the polling toggle flips.
  useEffect(() => { refresh(); }, [showPolling]);

  // 10s poller — disabled while paused; cleared on unmount.
  useEffect(() => {
    if (paused) return;
    const t = setInterval(() => { refresh(); setNow(Date.now()); }, POLL_MS);
    return () => clearInterval(t);
  }, [paused, showPolling]);

  // Client-side substring filter (case-insensitive) — no API roundtrip.
  const filtered = useMemo(() => {
    const op = operator.trim().toLowerCase();
    const ac = action.trim().toLowerCase();
    return rows.filter((r) =>
      (!op || r.operator.toLowerCase().includes(op)) &&
      (!ac || r.action.toLowerCase().includes(ac)),
    );
  }, [rows, operator, action]);

  return (
    <div>
      <PageHeader
        title="Audit log"
        count={filtered.length}
        caption="read from $AUDIT_LOG_PATH; refresh every 10s; polling actions hidden by default"
        action={err ? <span className="text-xs text-danger">{err}</span> : undefined}
      />
      <Card>
      <CardHeader className="space-y-2">
        <div className="flex gap-2 items-center">
          <Input
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
            placeholder="operator (contains)"
          />
          <Input
            value={action}
            onChange={(e) => setAction(e.target.value)}
            placeholder="action (contains)"
          />
          <label className="ml-auto shrink-0 flex items-center gap-1.5 text-xs text-muted cursor-pointer whitespace-nowrap">
            <input
              type="checkbox"
              checked={showPolling}
              onChange={(e) => setShowPolling(e.target.checked)}
              className="h-3 w-3 accent-accent2"
            />
            show polling
          </label>
          <Button
            variant={paused ? "default" : "outline"}
            size="sm"
            className="shrink-0"
            onClick={() => setPaused((p) => !p)}
          >
            {paused ? "paused" : "pause"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="!p-0">
        {filtered.length === 0 && (
          <EmptyState
            icon={ScrollText}
            title="no audit entries yet"
            description="sliver-server may not be writing audit logs in this configuration."
          />
        )}
        {/* mobile: cards with tap-to-expand details */}
        <div className="sm:hidden divide-y divide-border">
          {filtered.map((r, i) => (
            <AuditCard key={`${r.timestamp}-${i}`} row={r} now={now} />
          ))}
        </div>
        {/* desktop: table */}
        <Table className="hidden sm:table">
          <THead>
            <TR>
              <TH className="w-6"></TH><TH>time</TH><TH>operator</TH><TH>action</TH>
            </TR>
          </THead>
          <TBody>
            {filtered.map((r, i) => (
              <AuditRow key={`${r.timestamp}-${i}`} row={r} now={now} />
            ))}
          </TBody>
        </Table>
      </CardContent>
      </Card>
    </div>
  );
}

function AuditRow({ row, now }: { row: AuditEntry; now: number }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <TR className="cursor-pointer hover:bg-accent2/[0.06]" onClick={() => setOpen((o) => !o)}>
        <TD className="text-muted">
          <ChevronRight size={12} className={cn("transition-transform", open && "rotate-90")} />
        </TD>
        <TD className="text-muted whitespace-nowrap" title={row.timestamp}>
          {relativeTime(row.timestamp, now)}
        </TD>
        <TD>{row.operator || "—"}</TD>
        <TD className="font-mono text-[11px]">{row.action || "—"}</TD>
      </TR>
      {open && (
        <TR>
          <TD colSpan={4} className="!py-2">
            <pre className="text-[10px] font-mono whitespace-pre-wrap break-all bg-panel2 rounded p-2">
              {JSON.stringify(row.details, null, 2)}
            </pre>
          </TD>
        </TR>
      )}
    </>
  );
}

function AuditCard({ row, now }: { row: AuditEntry; now: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="p-3 space-y-1.5">
      <div className="font-mono text-[11px] font-semibold break-all">{row.action || "—"}</div>
      <dl className="space-y-0.5 text-[11px] font-mono">
        <div className="flex gap-2"><dt className="text-muted w-20 shrink-0">time</dt><dd title={row.timestamp}>{relativeTime(row.timestamp, now)}</dd></div>
        <div className="flex gap-2"><dt className="text-muted w-20 shrink-0">operator</dt><dd>{row.operator || "—"}</dd></div>
      </dl>
      <button
        className="text-accent2 hover:underline text-[11px]"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "hide details" : "show details"}
      </button>
      {open && (
        <pre className="text-[10px] font-mono whitespace-pre-wrap break-all bg-panel2 rounded p-2">
          {JSON.stringify(row.details, null, 2)}
        </pre>
      )}
    </div>
  );
}

function relativeTime(iso: string, now: number): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso || "—";
  const s = Math.max(0, Math.floor((now - t) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
