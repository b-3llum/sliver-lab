import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { api, ApiError, startNgrok, stopNgrok } from "@/api";
import { toast } from "@/lib/toast";
import { bus } from "@/ws";
import type {
  JobInfo,
  ListenerConflict,
  ListenerCreate,
  PersistentListener,
} from "@/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { CardList, DataCard } from "@/components/ui/DataCard";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Input";

export function Listeners() {
  const [rows, setRows] = useState<JobInfo[]>([]);
  const [persistent, setPersistent] = useState<PersistentListener[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ListenerConflict | null>(null);
  const [form, setForm] = useState<ListenerCreate>({ kind: "http", host: "0.0.0.0", port: 80 });
  const [submitting, setSubmitting] = useState(false);

  async function refresh() {
    try {
      setRows(await api.get<JobInfo[]>("/api/listeners"));
      setErr(null);
    } catch (e: any) { setErr(e.message); }
  }

  async function refreshPersistent() {
    try {
      setPersistent(await api.get<PersistentListener[]>("/api/listeners/persistent"));
    } catch {
      // 503 means no sliver.db (e.g. fresh install) — keep section hidden.
      setPersistent([]);
    }
  }

  useEffect(() => { refresh(); refreshPersistent(); }, []);
  useEffect(() => bus.subscribe((e) => {
    if (e.type.startsWith("job")) refresh();
  }), []);

  async function start() {
    setSubmitting(true);
    setConflict(null);
    try {
      await api.post<JobInfo>("/api/listeners", form);
      // sliver-py's start_*_listener returns an under-populated Job; the
      // canonical row comes from the GET that follows.
      setErr(null);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && isConflict(e.detail)) {
        setConflict(e.detail);
        await refreshPersistent();
      } else {
        setErr(e instanceof ApiError ? e.message : String(e));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function stop(id: number) {
    setRows((prev) => prev.filter((r) => r.ID !== id));
    try { await api.del(`/api/listeners/${id}`); await refresh(); }
    catch (e: any) { setErr(e.message); await refresh(); }
  }

  async function forget(jobId: number) {
    try {
      await api.del(`/api/listeners/persistent/${jobId}`);
      await refreshPersistent();
      // Re-list live listeners too — the conflict may resolve as a side effect.
      await refresh();
      // Clear the conflict banner so the user knows they can retry.
      setConflict(null);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function expose(port: number) {
    try {
      await startNgrok(port);
      toast.success("ngrok tunnel started");
      await refresh();
    } catch (e: any) {
      toast.error(`ngrok: ${e.message}`);
    }
  }

  async function stopExposure(tunnelId: string) {
    try {
      await stopNgrok(tunnelId);
      toast.success("ngrok tunnel stopped");
      await refresh();
    } catch (e: any) {
      toast.error(`ngrok: ${e.message}`);
    }
  }

  async function forgetAll() {
    const n = persistent.length;
    if (!confirm(
      `Forget ${n} orphan listeners? This deletes the persisted DB rows; live listeners are not affected.`,
    )) return;
    try {
      await api.del(`/api/listeners/persistent`);
      await refreshPersistent();
      await refresh();
      setConflict(null);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Listeners" />
      <Card>
        <CardHeader><CardTitle>Start listener</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-5 gap-2 sm:items-end">
            <div>
              <Label>kind</Label>
              <Select
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value as ListenerCreate["kind"] })}
              >
                <option value="http">http</option>
                <option value="https">https</option>
                <option value="mtls">mtls</option>
                <option value="dns">dns</option>
              </Select>
            </div>
            <div>
              <Label>host</Label>
              <Input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} />
            </div>
            <div>
              <Label>port</Label>
              <Input
                type="number"
                inputMode="numeric"
                value={form.port}
                onChange={(e) => setForm({ ...form, port: +e.target.value })}
              />
            </div>
            <div>
              <Label>{form.kind === "dns" ? "domain*" : "website (http/https)"}</Label>
              <Input
                placeholder={form.kind === "dns" ? "example.com" : "(optional)"}
                value={form.kind === "dns" ? (form.domain ?? "") : (form.website ?? "")}
                onChange={(e) =>
                  form.kind === "dns"
                    ? setForm({ ...form, domain: e.target.value })
                    : setForm({ ...form, website: e.target.value })
                }
              />
            </div>
            <Button className="max-sm:w-full" onClick={start} disabled={submitting}>
              {submitting ? "starting…" : "start"}
            </Button>
          </div>
          {err && <div className="mt-2 text-xs text-danger">{err}</div>}
          {conflict && (
            <div className="mt-3 rounded border border-warn/50 bg-warn/10 p-2 text-xs text-warn">
              <div className="font-semibold">{conflict.message}</div>
              <div className="mt-1 text-muted">{conflict.hint}</div>
              <div className="mt-1 text-muted">
                kind <code>{conflict.kind}</code> on <code>{conflict.host}:{conflict.port}</code>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Active listeners ({rows.length})</CardTitle></CardHeader>
        <CardContent className="!p-0">
          {/* mobile: cards */}
          <CardList>
            {rows.map((j) => (
              <DataCard
                key={j.ID}
                title={`${j.name} (#${j.ID})`}
                rows={[
                  ["protocol", j.protocol],
                  ["port", j.port],
                  ["domains", j.domains.join(", ") || "—"],
                ]}
                actions={
                  <>
                    <Button variant="danger" size="sm" onClick={() => stop(j.ID)}>stop</Button>
                    <ExposureCell job={j} onExpose={() => expose(j.port)}
                                  onStop={(id) => stopExposure(id)} />
                  </>
                }
              />
            ))}
            {rows.length === 0 && <div className="p-4 text-center text-muted text-xs">No listeners.</div>}
          </CardList>
          {/* desktop: table */}
          <Table className="hidden sm:table">
            <THead><TR><TH>id</TH><TH>name</TH><TH>protocol</TH><TH>port</TH><TH>domains</TH><TH>public exposure</TH><TH></TH></TR></THead>
            <TBody>
              {rows.map((j) => (
                <TR key={j.ID}>
                  <TD>{j.ID}</TD>
                  <TD>{j.name}</TD>
                  <TD>{j.protocol}</TD>
                  <TD>{j.port}</TD>
                  <TD>{j.domains.join(", ")}</TD>
                  <TD>
                    <ExposureCell job={j} onExpose={() => expose(j.port)}
                                  onStop={(id) => stopExposure(id)} />
                  </TD>
                  <TD className="text-right">
                    <Button variant="danger" size="sm" onClick={() => stop(j.ID)}>stop</Button>
                  </TD>
                </TR>
              ))}
              {rows.length === 0 && (
                <TR><TD colSpan={6} className="text-center text-muted py-6">No listeners.</TD></TR>
              )}
            </TBody>
          </Table>
        </CardContent>
      </Card>

      {persistent.length > 0 && (
        <PersistentSection rows={persistent} onForget={forget} onForgetAll={forgetAll} />
      )}
    </div>
  );
}

function PersistentSection({
  rows, onForget, onForgetAll,
}: {
  rows: PersistentListener[];
  onForget: (id: number) => void;
  onForgetAll: () => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none"
        onClick={() => setOpen((o) => !o)}
        title="Click to collapse"
      >
        <div className="flex items-center justify-between">
          <CardTitle>
            Persistent (orphaned) ({rows.length}) <span className="ml-2 text-xs text-muted">{open ? "▾" : "▸"}</span>
          </CardTitle>
          {rows.length > 1 && (
            <Button
              variant="danger" size="sm"
              onClick={(e) => { e.stopPropagation(); onForgetAll(); }}
            >
              Forget all ({rows.length})
            </Button>
          )}
        </div>
        <div className="text-xs text-muted">
          Rows in <code>sliver.db</code> with no live job. Forget to free the port.
        </div>
      </CardHeader>
      {open && (
        <CardContent className="!p-0">
          {/* mobile: cards */}
          <CardList>
            {rows.map((p) => (
              <DataCard
                key={p.job_id}
                title={`${p.kind} :${p.port} (job ${p.job_id})`}
                rows={[
                  ["host", p.host],
                  ["created", p.created_at ?? "—"],
                ]}
                actions={<Button size="sm" variant="outline" onClick={() => onForget(p.job_id)}>forget</Button>}
              />
            ))}
          </CardList>
          {/* desktop: table */}
          <Table className="hidden sm:table">
            <THead>
              <TR><TH>job_id</TH><TH>kind</TH><TH>host</TH><TH>port</TH><TH>created</TH><TH></TH></TR>
            </THead>
            <TBody>
              {rows.map((p) => (
                <TR key={p.job_id}>
                  <TD>{p.job_id}</TD>
                  <TD>{p.kind}</TD>
                  <TD>{p.host}</TD>
                  <TD>{p.port}</TD>
                  <TD className="text-muted">{p.created_at ?? "—"}</TD>
                  <TD className="text-right">
                    <Button size="sm" variant="outline" onClick={() => onForget(p.job_id)}>forget</Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      )}
    </Card>
  );
}

function ExposureCell({
  job, onExpose, onStop,
}: {
  job: JobInfo;
  onExpose: () => void;
  onStop: (tunnelId: string) => void;
}) {
  const ex = job.public_exposure;
  if (!ex) {
    // No "—" placeholder: the actionable button IS the empty state.
    return <Button size="sm" variant="outline" onClick={onExpose}>Expose via ngrok</Button>;
  }
  const addr = `${ex.public_host}:${ex.public_port}`;
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => { navigator.clipboard.writeText(addr); toast.info("public address copied"); }}
        className="font-mono text-[10px] text-accent2 hover:underline break-all"
        title="click to copy the public address"
      >
        {addr}
      </button>
      <Button size="sm" variant="danger" onClick={() => onStop(ex.id)}>Stop exposure</Button>
      <span
        className="text-warn shrink-0 cursor-help ml-auto"
        title="Public exposure: this ngrok address is internet-reachable while the tunnel is open. The mtls cert chain still gates real implants, but anyone who reaches it can attempt a handshake. Stop the tunnel when done — implants built against this address can't call back once it's closed."
      >
        <AlertTriangle size={13} />
      </span>
    </div>
  );
}

function isConflict(d: unknown): d is ListenerConflict {
  return !!d && typeof d === "object"
    && "kind" in d && "host" in d && "port" in d && "message" in d && "hint" in d;
}
