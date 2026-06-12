import { useEffect, useState } from "react";
import { getReport, reportMarkdownUrl } from "@/api";
import type { ReportData } from "@/types";
import { Crosshair, Download, FileBarChart2, Server, Target } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

export function Report() {
  const [report, setReport] = useState<ReportData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [engagement, setEngagement] = useState("");
  const [since, setSince] = useState("");
  const [includePolling, setIncludePolling] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const r = await getReport({
        engagement: engagement.trim() || undefined,
        since: since.trim() || undefined,
        includePolling,
      });
      setReport(r);
      setErr(null);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }

  // Initial fetch only; subsequent refreshes are explicit via "Generate" so the
  // report is a stable snapshot the operator chooses to take, not a live poll.
  useEffect(() => { load(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const mdUrl = reportMarkdownUrl({
    engagement: engagement.trim() || undefined,
    since: since.trim() || undefined,
    includePolling,
  });
  const s = report?.summary;

  return (
    <div>
      <PageHeader
        title="Engagement report"
        count={s?.operator_action_count ?? 0}
        caption="compiled from the audit log + live implant state; ATT&CK mapping aids blue-team detection"
        action={err ? <span className="text-xs text-danger">{err}</span> : undefined}
      />

      <Card>
        <CardHeader className="space-y-2">
          <div className="flex flex-wrap gap-2 items-center">
            <Input
              value={engagement}
              onChange={(e) => setEngagement(e.target.value)}
              placeholder="engagement name"
            />
            <Input
              value={since}
              onChange={(e) => setSince(e.target.value)}
              placeholder="since (ISO-8601, optional)"
            />
            <label className="shrink-0 flex items-center gap-1.5 text-xs text-muted cursor-pointer whitespace-nowrap">
              <input
                type="checkbox"
                checked={includePolling}
                onChange={(e) => setIncludePolling(e.target.checked)}
                className="h-3 w-3 accent-accent2"
              />
              include polling
            </label>
            <Button size="sm" className="ml-auto shrink-0" onClick={load} disabled={loading}>
              {loading ? "generating…" : "generate"}
            </Button>
            <a
              href={mdUrl}
              download
              className="shrink-0 inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs text-text hover:bg-panel2"
            >
              <Download size={13} /> Markdown
            </a>
          </div>
        </CardHeader>
        <CardContent>
          {s && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Stat icon={Target} label="actions" value={s.operator_action_count} />
              <Stat icon={Crosshair} label="techniques" value={s.distinct_technique_count} />
              <Stat icon={Server} label="sessions" value={s.session_count} />
              <Stat icon={FileBarChart2} label="beacons" value={s.beacon_count} />
            </div>
          )}
          {s && s.operators.length > 0 && (
            <div className="mt-2 text-[11px] text-muted">
              operators: <span className="text-text">{s.operators.join(", ")}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── ATT&CK techniques ── */}
      <Card className="mt-3">
        <CardHeader><h2 className="text-xs font-semibold tracking-wide text-muted">ATT&CK TECHNIQUES OBSERVED</h2></CardHeader>
        <CardContent className="!p-0">
          {!report?.techniques.length ? (
            <EmptyState icon={Crosshair} title="no mapped techniques" description="no recorded actions mapped to an ATT&CK technique in this window." />
          ) : (
            <Table>
              <THead><TR><TH>technique</TH><TH>id</TH><TH>tactic</TH><TH className="text-right">count</TH></TR></THead>
              <TBody>
                {report.techniques.map((t) => (
                  <TR key={t.id}>
                    <TD>{t.name}</TD>
                    <TD className="font-mono text-[11px] text-accent2">{t.id}</TD>
                    <TD className="text-muted">{t.tactic}</TD>
                    <TD className="text-right tabular-nums">{t.count}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* ── footholds ── */}
      <Card className="mt-3">
        <CardHeader><h2 className="text-xs font-semibold tracking-wide text-muted">FOOTHOLDS</h2></CardHeader>
        <CardContent className="!p-0">
          {!report?.footholds.length ? (
            <EmptyState icon={Server} title="no live footholds" description="teamserver offline or no active sessions/beacons at report time." />
          ) : (
            <Table>
              <THead><TR><TH>kind</TH><TH>host</TH><TH>user</TH><TH>os/arch</TH><TH>transport</TH><TH>remote</TH></TR></THead>
              <TBody>
                {report.footholds.map((f, i) => (
                  <TR key={`${f.identifier}-${i}`}>
                    <TD className="font-mono text-[11px]">{f.kind}</TD>
                    <TD>{f.host || "—"}</TD>
                    <TD>{f.user || "—"}</TD>
                    <TD className="text-muted">{[f.os, f.arch].filter(Boolean).join("/") || "—"}</TD>
                    <TD className="text-muted">{f.transport || "—"}</TD>
                    <TD className="font-mono text-[11px] text-muted">{f.remote_address || "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* ── timeline ── */}
      <Card className="mt-3">
        <CardHeader><h2 className="text-xs font-semibold tracking-wide text-muted">OPERATOR ACTIVITY TIMELINE</h2></CardHeader>
        <CardContent className="!p-0">
          {!report?.timeline.length ? (
            <EmptyState icon={Target} title="no operator actions" description="no operator actions recorded in this window." />
          ) : (
            <Table>
              <THead><TR><TH>time</TH><TH>operator</TH><TH>action</TH><TH>technique</TH><TH>target</TH></TR></THead>
              <TBody>
                {report.timeline.map((t, i) => (
                  <TR key={`${t.timestamp}-${i}`}>
                    <TD className="text-muted whitespace-nowrap font-mono text-[11px]">{t.timestamp}</TD>
                    <TD>{t.operator || "—"}</TD>
                    <TD className="font-mono text-[11px]">{t.action}</TD>
                    <TD className="text-[11px]">
                      {t.technique
                        ? <span><span className="font-mono text-accent2">{t.technique.id}</span> <span className="text-muted">{t.technique.name}</span></span>
                        : <span className="text-muted">—</span>}
                    </TD>
                    <TD className="font-mono text-[11px] text-muted">{t.target || "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ icon: Icon, label, value }: { icon: any; label: string; value: number }) {
  return (
    <div className="rounded border border-border bg-panel2 p-2.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted">
        <Icon size={12} /> {label}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-text">{value}</div>
    </div>
  );
}
