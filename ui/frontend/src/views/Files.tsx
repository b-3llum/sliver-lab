import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ArrowLeft, FolderTree } from "lucide-react";
import {
  api, downloadImplant, lsImplant, pollTask, taskResultUrl,
} from "@/api";
import type { BeaconInfo, FileEntry, SessionInfo } from "@/types";
import { cn } from "@/lib/cn";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { EmptyState } from "@/components/ui/EmptyState";

interface Pick { id: string; kind: "session" | "beacon"; label: string; sub: string }
interface Listing { path: string; entries: FileEntry[] }

export function Files() {
  const { sessionId: paramSid } = useParams<{ sessionId?: string }>();
  const [picks, setPicks] = useState<Pick[]>([]);
  const [selId, setSelId] = useState<string | undefined>(paramSid);
  const [path, setPath] = useState(".");
  const [listing, setListing] = useState<Listing | null>(null);
  const [loading, setLoading] = useState(false);
  const [waiting, setWaiting] = useState(false);   // beacon ls awaiting check-in
  const [downloading, setDownloading] = useState<Record<string, boolean>>({});
  const [err, setErr] = useState<string | null>(null);

  // Implant list: sessions + beacons (every implant advertises capabilities.ls
  // in this build, so the picker shows all of them — both can ls).
  useEffect(() => {
    Promise.all([
      api.get<SessionInfo[]>("/api/sessions").catch(() => [] as SessionInfo[]),
      api.get<BeaconInfo[]>("/api/beacons").catch(() => [] as BeaconInfo[]),
    ]).then(([ss, bs]) => {
      const out: Pick[] = [];
      for (const s of ss) out.push({
        id: s.ID, kind: "session",
        label: `${s.username || "?"}@${s.hostname || "?"}`,
        sub: `${s.os}/${s.arch} · ${s.transport}`,
      });
      for (const b of bs) out.push({
        id: b.ID, kind: "beacon",
        label: `${b.username || "?"}@${b.hostname || "?"}`,
        sub: `${b.os}/${b.arch} · ${b.transport} · ${Math.round(b.interval / 1e9)}s`,
      });
      setPicks(out);
    }).catch((e: any) => setErr(e.message));
  }, []);

  const sel = picks.find((p) => p.id === selId);
  // Backward-compat /files/:sessionId — treat an unknown param id as a session.
  const selKind: "session" | "beacon" = sel?.kind ?? "session";

  function select(p: Pick) {
    setSelId(p.id);
    setPath(".");
    setListing(null);
    setErr(null);
  }

  function back() {
    setSelId(undefined);
    setListing(null);
    setErr(null);
  }

  useEffect(() => {
    if (!selId) return;
    let cancelled = false;
    setLoading(true); setWaiting(false); setErr(null);
    (async () => {
      try {
        const res = await lsImplant(selId, path);
        if (cancelled) return;
        if (res?.kind === "beacon" && res.task_id) {
          // Async: queued on the beacon; resolves on next check-in.
          setWaiting(true);
          const st = await pollTask(res.task_id, { cancelled: () => cancelled });
          if (cancelled) return;
          if (st.state === "error") throw new Error(st.error ?? "ls failed");
          setListing({ path: st.result?.path ?? path, entries: st.result?.entries ?? [] });
        } else {
          setListing({ path: res?.path ?? path, entries: res?.entries ?? [] });
        }
      } catch (e: any) {
        if (!cancelled) { setErr(e.message ?? String(e)); setListing(null); }
      } finally {
        if (!cancelled) { setLoading(false); setWaiting(false); }
      }
    })();
    return () => { cancelled = true; };
  }, [selId, path]);

  async function download(p: string) {
    if (!selId) return;
    const name = p.split(/[\\/]/).pop() || "download";
    setDownloading((d) => ({ ...d, [p]: true }));
    setErr(null);
    try {
      const res = await downloadImplant(selId, p);
      const st = await pollTask(res.task_id);
      if (st.state === "error") throw new Error(st.error ?? "download failed");
      // Bytes land in the task registry; pull them and save to disk.
      const r = await fetch(taskResultUrl(res.task_id));
      if (!r.ok) throw new Error(`result fetch failed (${r.status})`);
      const blob = await r.blob();
      const cd = r.headers.get("content-disposition") ?? "";
      const fname = /filename="?([^"]+)"?/.exec(cd)?.[1] || name;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = fname;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setErr(e.message ?? String(e));
    } finally {
      setDownloading((d) => { const n = { ...d }; delete n[p]; return n; });
    }
  }

  // ── Picker (no implant selected) ──────────────────────────────────
  if (!selId) {
    return (
      <div>
        <PageHeader title="Files" />
        <Card>
        <CardContent className="space-y-1">
          {picks.map((p) => (
            <Button key={p.id} variant="ghost" size="sm"
                    className="w-full justify-start gap-2" onClick={() => select(p)}>
              <span className={cn(
                "inline-block w-2 h-2 rounded-full",
                p.kind === "beacon" ? "bg-amber-500" : "bg-accent",
              )} />
              <span className="font-mono">{p.label}</span>
              <span className="text-muted text-[10px]">{p.sub}</span>
              <span className="text-[10px] text-muted ml-auto">{p.kind}</span>
            </Button>
          ))}
          {picks.length === 0 ? (
            <p className="text-xs text-muted">No active implants. Start a listener and deploy one.</p>
          ) : (
            <EmptyState
              icon={FolderTree}
              title="No target selected"
              description="Pick a target above to browse its filesystem."
            />
          )}
          {err && <p className="text-xs text-danger">{err}</p>}
        </CardContent>
        </Card>
      </div>
    );
  }

  // ── Listing (implant selected) ────────────────────────────────────
  const entries = listing?.entries ?? [];
  return (
    <div>
      <PageHeader
        title="Files"
        caption={<>{selKind} · <span className="font-mono">{sel?.label ?? selId}</span></>}
        action={err ? <span className="text-xs text-danger">{err}</span> : undefined}
      />
      <Card>
      <CardHeader className="space-y-2">
        <div className="flex gap-2 flex-wrap items-center">
          {/* phone: ← back when not at root */}
          {pathDepth(listing?.path ?? path) > 0 && (
            <Button
              variant="outline" size="sm" aria-label="up one level"
              className="sm:hidden px-2"
              onClick={() => setPath(joinPath(listing?.path ?? path, ".."))}
            >
              <ArrowLeft size={14} />
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={back}>change implant</Button>
          <Input className="flex-1 min-w-[8rem]" value={path} onChange={(e) => setPath(e.target.value)} placeholder="path" />
          <Button onClick={() => setPath(listing?.path ?? path)}>refresh</Button>
          <Button variant="outline" className="hidden sm:inline-flex"
                  onClick={() => setPath(joinPath(listing?.path ?? path, ".."))}>up</Button>
        </div>
      </CardHeader>
      <CardContent className="!p-0">
        {/* mobile: tappable list */}
        <div className="sm:hidden divide-y divide-border">
          {entries.map((f) => {
            const full = joinPath(listing!.path, f.name);
            return (
              <button
                key={f.name}
                className="w-full text-left px-3 py-3 flex items-center justify-between gap-2 active:bg-panel2"
                disabled={!!downloading[full]}
                onClick={() => f.is_dir ? setPath(full) : download(full)}
              >
                <span className="font-mono text-xs break-all">
                  {f.is_dir ? <span className="text-accent2">{f.name}/</span> : f.name}
                </span>
                <span className="text-[10px] text-muted shrink-0">
                  {downloading[full] ? "downloading…" : f.is_dir ? "open ›" : `${f.size} ↓`}
                </span>
              </button>
            );
          })}
          {entries.length === 0 && (
            <div className="text-center text-muted py-6 text-xs">
              {loading ? (waiting ? "waiting for beacon check-in…" : "loading…") : "empty directory"}
            </div>
          )}
        </div>
        {/* desktop: table */}
        <Table className="hidden sm:table">
          <THead><TR><TH>name</TH><TH>size</TH><TH>mode</TH><TH>mtime</TH><TH></TH></TR></THead>
          <TBody>
            {entries.map((f) => (
              <TR key={f.name}>
                <TD>
                  {f.is_dir ? (
                    <button className="text-accent2 hover:underline"
                            onClick={() => setPath(joinPath(listing!.path, f.name))}>
                      {f.name}/
                    </button>
                  ) : f.name}
                </TD>
                <TD>{f.is_dir ? "—" : f.size}</TD>
                <TD className="text-muted">{f.mode}</TD>
                <TD className="text-muted">
                  {f.mod_time ? new Date(f.mod_time * 1000).toLocaleString() : "—"}
                </TD>
                <TD className="text-right">
                  {!f.is_dir && (
                    <Button size="sm" variant="outline" disabled={!!downloading[joinPath(listing!.path, f.name)]}
                            onClick={() => download(joinPath(listing!.path, f.name))}>
                      {downloading[joinPath(listing!.path, f.name)] ? "downloading…" : "download"}
                    </Button>
                  )}
                </TD>
              </TR>
            ))}
            {entries.length === 0 && (
              <TR>
                <TD colSpan={5} className="text-center text-muted py-6">
                  {loading
                    ? (waiting ? "waiting for beacon check-in…" : "loading…")
                    : "empty directory"}
                </TD>
              </TR>
            )}
          </TBody>
        </Table>
      </CardContent>
      </Card>
    </div>
  );
}

function pathDepth(p: string): number {
  if (!p || p === ".") return 0;
  return p.split(/[\\/]/).filter(Boolean).length;
}

function joinPath(base: string, name: string): string {
  if (name === "..") return base.replace(/\/[^/]+\/?$/, "") || "/";
  if (!base || base === ".") return name;
  return base.replace(/\/$/, "") + "/" + name;
}
