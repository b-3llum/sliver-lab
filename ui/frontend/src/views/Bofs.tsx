import { useEffect, useState } from "react";
import { api, ApiError } from "@/api";
import type { BofEntry, BofLibrary, BofRunCommand, SessionInfo } from "@/types";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { Button } from "@/components/ui/Button";
import { Input, Select, Label } from "@/components/ui/Input";

export function Bofs() {
  const [bofs, setBofs] = useState<BofEntry[]>([]);
  const [library, setLibrary] = useState<BofLibrary | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [target, setTarget] = useState<string>("");
  const [argInputs, setArgInputs] = useState<Record<string, string>>({});
  const [out, setOut] = useState<BofRunCommand | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<BofEntry[]>("/api/bofs"),
      api.get<BofLibrary>("/api/bofs/library"),
      api.get<SessionInfo[]>("/api/sessions").catch(() => [] as SessionInfo[]),
    ]).then(([b, lib, s]) => {
      setBofs(b);
      setLibrary(lib);
      setSessions(s);
      if (s.length > 0) setTarget(s[0].ID);
    }).catch((e: ApiError) => setErr(e.message));
  }, []);

  async function buildCmd(bof: BofEntry) {
    setOut(null);
    if (!target) { setErr("pick a session first"); return; }
    const argStr = (argInputs[bof.name] ?? "").trim();
    const args = argStr ? argStr.split(/\s+/) : [];
    try {
      const r = await api.post<BofRunCommand>(
        `/api/bofs/${bof.name}/build_command?session_id=${encodeURIComponent(target)}`,
        args,
      );
      setOut(r);
      setErr(null);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function copyCmd() {
    if (!out) return;
    await navigator.clipboard.writeText(out.sliver_command);
  }

  const grouped = bofs.reduce<Record<string, BofEntry[]>>((acc, b) => {
    (acc[b.category] ??= []).push(b);
    return acc;
  }, {});

  const emptyLib = library && bofs.length === 0;

  return (
    <div className="space-y-4">
      <PageHeader title="BOFs" />
      <Card>
        <CardHeader>
          <CardTitle>BOF Library</CardTitle>
          <CardDescription>
            Operator drops <code>.o</code> files under <code>$BOF_DIR</code>. Build a Sliver
            <code className="mx-1">inline-execute</code> command, paste into your console.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {library && (
            <div className="text-xs text-muted">
              scanning <code>{library.dir}</code>{library.env_set ? "" : " (default)"} —
              {" "}<span className="text-text">{library.count}</span> on disk
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label>target session</Label>
              <Select value={target} onChange={(e) => setTarget(e.target.value)}>
                {sessions.length === 0 && <option value="">(no sessions)</option>}
                {sessions.map((s) => (
                  <option key={s.ID} value={s.ID}>
                    {s.hostname || s.ID} — {s.username} ({s.os})
                  </option>
                ))}
              </Select>
            </div>
          </div>
          {err && <div className="text-xs text-danger">{err}</div>}
        </CardContent>
      </Card>

      {emptyLib && <EmptyLibrary lib={library!} />}

      {Object.entries(grouped).map(([cat, entries]) => (
        <Card key={cat}>
          <CardHeader>
            <CardTitle className="text-sm capitalize">{cat.replace(/-/g, " ")}</CardTitle>
          </CardHeader>
          <CardContent className="!p-0">
            {/* mobile: cards */}
            <div className="sm:hidden divide-y divide-border">
              {entries.map((b) => (
                <div key={b.name} className="p-3 space-y-2">
                  <div className="font-mono text-xs font-semibold break-all">{b.name}</div>
                  <div className="text-[10px] text-muted break-all">{b.path}</div>
                  <Input
                    placeholder="(args, space-separated)"
                    value={argInputs[b.name] ?? ""}
                    onChange={(e) => setArgInputs({ ...argInputs, [b.name]: e.target.value })}
                  />
                  <Button size="sm" className="w-full" disabled={!target} onClick={() => buildCmd(b)}>
                    build cmd
                  </Button>
                </div>
              ))}
            </div>
            {/* desktop: table */}
            <Table className="hidden sm:table">
              <THead>
                <TR><TH>name</TH><TH>path</TH><TH>args</TH><TH></TH></TR>
              </THead>
              <TBody>
                {entries.map((b) => (
                  <TR key={b.name}>
                    <TD className="font-mono">{b.name}</TD>
                    <TD className="text-muted text-[10px]" title={b.path ?? ""}>{b.path}</TD>
                    <TD>
                      <Input
                        placeholder="(args, space-separated)"
                        value={argInputs[b.name] ?? ""}
                        onChange={(e) => setArgInputs({ ...argInputs, [b.name]: e.target.value })}
                      />
                    </TD>
                    <TD className="text-right">
                      <Button size="sm" disabled={!target} onClick={() => buildCmd(b)}>
                        build cmd
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      ))}

      {out && (
        <Card>
          <CardHeader className="flex items-center justify-between">
            <CardTitle className="text-sm">Sliver console command</CardTitle>
            <Button size="sm" onClick={copyCmd}>copy</Button>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-panel2 border border-border rounded p-2 overflow-auto">
              {out.sliver_command}
            </pre>
            <p className="mt-2 text-xs text-muted">{out.note}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function EmptyLibrary({ lib }: { lib: BofLibrary }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">No BOFs found</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        {!lib.exists ? (
          <p>The directory <code>{lib.dir}</code> doesn't exist yet.</p>
        ) : (
          <p>The directory <code>{lib.dir}</code> exists but has no <code>.o</code> files.</p>
        )}
        <p>To populate it:</p>
        <pre className="bg-panel2 border border-border rounded p-2 overflow-auto">
{`mkdir -p ${lib.dir}/credential-access ${lib.dir}/discovery
# drop .o files into category subdirs, e.g.:
cp /path/to/mimikatz.x64.o ${lib.dir}/credential-access/
cp /path/to/netuser.x64.o  ${lib.dir}/discovery/`}
        </pre>
        {!lib.env_set && (
          <p className="text-muted">
            Or point <code>$BOF_DIR</code> at an existing directory and restart the BFF.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
