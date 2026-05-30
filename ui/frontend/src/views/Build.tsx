import { useEffect, useMemo, useState } from "react";
import { api, ApiError, buildSliver, buildSliverOptions } from "@/api";
import { authHeaders } from "@/lib/auth";
import type {
  BuildField, BuildGroup, BuildSchema, BuildSliverOptions, BuildSliverRequest,
  JobInfo, NgrokTunnel,
} from "@/types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Input";

type Values = Record<string, unknown>;

function initialValues(schema: BuildSchema): Values {
  const v: Values = {};
  for (const g of schema.groups) {
    for (const f of g.fields) {
      if (f.kind === "bool") v[f.name] = !!f.default;
      else if (f.default !== null && f.default !== undefined) v[f.name] = f.default;
      // Required choice with no default: lock the visible option to React state
      // so the controlled <select> can't drift from the DOM.
      else if (f.kind === "choice" && f.required && f.choices?.length) v[f.name] = f.choices[0];
      else v[f.name] = "";
    }
  }
  return v;
}

function FieldInput({
  field, value, onChange, exclusive, onExclusiveSelect,
}: {
  field: BuildField;
  value: unknown;
  onChange: (v: unknown) => void;
  exclusive?: boolean;
  onExclusiveSelect?: () => void;
}) {
  const placeholder = field.metavar ?? field.default?.toString() ?? "";

  if (field.kind === "bool") {
    return (
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="h-3 w-3 accent-accent2"
        />
        <span className="text-xs">{field.flag}</span>
      </label>
    );
  }
  if (field.kind === "choice" && field.choices) {
    return (
      <Select
        value={value as string | number | undefined ?? field.default as string ?? ""}
        onChange={(e) => onChange(e.target.value)}
        onFocus={exclusive ? onExclusiveSelect : undefined}
      >
        {!field.required && <option value="">—</option>}
        {field.choices.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </Select>
    );
  }
  return (
    <Input
      type={field.kind === "int" ? "number" : "text"}
      value={(value as string | number | undefined) ?? ""}
      placeholder={placeholder}
      onChange={(e) =>
        onChange(field.kind === "int"
          ? (e.target.value === "" ? "" : Number(e.target.value))
          : e.target.value)}
      onFocus={exclusive ? onExclusiveSelect : undefined}
    />
  );
}

function GroupSection({
  group, values, setValues,
}: {
  group: BuildGroup;
  values: Values;
  setValues: (v: Values) => void;
}) {
  // For exclusive groups, when one field gets a non-empty value, clear the others.
  const setField = (name: string, v: unknown) => {
    if (group.exclusive && v !== "" && v !== false && v != null) {
      const next: Values = { ...values, [name]: v };
      for (const f of group.fields) {
        if (f.name !== name) next[f.name] = f.kind === "bool" ? false : "";
      }
      setValues(next);
    } else {
      setValues({ ...values, [name]: v });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          {group.name}
          {group.exclusive && <span className="ml-2 text-xs text-muted">(one of)</span>}
        </CardTitle>
        {group.description && (
          <CardDescription className="text-xs">{group.description}</CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {group.fields.map((f) => (
            <div key={f.name} className="space-y-1">
              <Label className="flex items-baseline justify-between gap-2">
                <span className="font-mono text-xs text-fg">{f.flag}</span>
                {f.required && <span className="text-xs text-danger">required</span>}
              </Label>
              <FieldInput
                field={f}
                value={values[f.name]}
                onChange={(v) => setField(f.name, v)}
                exclusive={group.exclusive}
              />
              {f.help && <div className="text-xs text-muted leading-snug">{f.help}</div>}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Sliver-native build card ───────────────────────────────────────

function SliverNativeCard({ opts }: { opts: BuildSliverOptions }) {
  const d = opts.defaults;
  const [goos, setGoos] = useState(d.goos);
  const [goarch, setGoarch] = useState(d.goarch);
  const [format, setFormat] = useState(d.format);
  const [c2Url, setC2Url] = useState(d.c2_url);
  const [name, setName] = useState("");
  const [beacon, setBeacon] = useState(d.beacon);
  const [intervalS, setIntervalS] = useState(d.beacon_interval_s);
  const [obfuscate, setObfuscate] = useState(d.obfuscate);
  const [building, setBuilding] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [last, setLast] = useState<string | null>(null);
  // ngrok exposures available to point the implant at a public address.
  const [exposures, setExposures] = useState<NgrokTunnel[]>([]);
  useEffect(() => {
    api.get<JobInfo[]>("/api/listeners")
      .then((js) => setExposures(
        js.map((j) => j.public_exposure).filter(Boolean) as NgrokTunnel[],
      ))
      .catch(() => {});
  }, []);

  async function submit() {
    setErr(null); setLast(null); setBuilding(true);
    const req: BuildSliverRequest = {
      goos, goarch, format,
      c2_url: c2Url.trim(),
      name: name.trim() || undefined,
      beacon,
      beacon_interval_s: beacon ? intervalS : undefined,
      obfuscate,
    };
    try {
      const { blob, filename } = await buildSliver(req);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
      setLast(`${filename} — ${blob.size.toLocaleString()} bytes`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBuilding(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sliver implant (native mTLS/HTTPS)</CardTitle>
        <CardDescription>
          Connects back to the listeners on the server. Builds take 30-90 s typical, 300 s cap.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
          <div className="space-y-1">
            <Label>goos</Label>
            <Select value={goos} onChange={(e) => setGoos(e.target.value)}>
              {opts.goos.map((v) => <option key={v} value={v}>{v}</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label>goarch</Label>
            <Select value={goarch} onChange={(e) => setGoarch(e.target.value)}>
              {opts.goarch.map((v) => <option key={v} value={v}>{v}</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label>format</Label>
            <Select value={format} onChange={(e) => setFormat(e.target.value)}>
              {opts.format.map((v) => <option key={v} value={v}>{v}</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label>name (optional)</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="leave blank for auto-name"
            />
          </div>

          <div className="space-y-1 col-span-2">
            <Label>C2 URL</Label>
            <Input
              value={c2Url}
              onChange={(e) => setC2Url(e.target.value)}
              placeholder="mtls://10.1.0.7:8443"
              className="font-mono"
            />
            <div className="text-[10px] text-muted">e.g. mtls://10.1.0.7:8443</div>
            {exposures.length > 0 && (
              <div className="space-y-1 pt-1">
                <Select
                  defaultValue=""
                  onChange={(e) => {
                    const ex = exposures.find((x) => x.id === e.target.value);
                    if (ex) setC2Url(`mtls://${ex.public_host}:${ex.public_port}`);
                  }}
                >
                  <option value="">use local listener URL</option>
                  {exposures.map((ex) => (
                    <option key={ex.id} value={ex.id}>
                      use ngrok: {ex.public_host}:{ex.public_port}
                    </option>
                  ))}
                </Select>
                <div className="text-[10px] text-muted italic">
                  ngrok-built implants are tied to that public address — if you stop the tunnel, they can't call back.
                </div>
              </div>
            )}
          </div>
          <div className="space-y-1">
            <label className="flex items-center gap-2 text-xs cursor-pointer mt-5">
              <input
                type="checkbox"
                checked={beacon}
                onChange={(e) => setBeacon(e.target.checked)}
                className="h-3 w-3 accent-accent2"
              />
              <span>beacon (vs. always-on session)</span>
            </label>
          </div>
          <div className="space-y-1">
            <Label>beacon interval (seconds)</Label>
            <Input
              type="number"
              value={intervalS}
              disabled={!beacon}
              onChange={(e) => setIntervalS(Number(e.target.value) || 0)}
            />
          </div>
          <div className="space-y-1">
            <label className="flex items-center gap-2 text-xs cursor-pointer mt-5">
              <input
                type="checkbox"
                checked={obfuscate}
                onChange={(e) => setObfuscate(e.target.checked)}
                className="h-3 w-3 accent-accent2"
              />
              <span>obfuscate symbols</span>
            </label>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-end gap-3">
          {last && <span className="text-xs text-ok">{last}</span>}
          {err && <span className="text-xs text-danger max-w-xl truncate" title={err}>{err}</span>}
          {building && <span className="text-xs text-muted animate-pulse">building…</span>}
          <Button onClick={submit} disabled={building || !c2Url.trim()}>
            {building ? "building…" : "Build"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function Build() {
  const [schema, setSchema] = useState<BuildSchema | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [values, setValues] = useState<Values>({});
  const [building, setBuilding] = useState(false);
  const [buildErr, setBuildErr] = useState<string | null>(null);
  const [lastBuild, setLastBuild] = useState<string | null>(null);
  const [sliverOpts, setSliverOpts] = useState<BuildSliverOptions | null>(null);

  useEffect(() => {
    api.get<BuildSchema>("/api/build/options")
      .then((s) => { setSchema(s); setValues(initialValues(s)); })
      .catch((e: ApiError) => setLoadErr(`HTTP ${e.status}: ${e.message}`));
    buildSliverOptions()
      .then((o) => setSliverOpts(o))
      .catch(() => setSliverOpts(null));
  }, []);

  // Send only set/non-default values so avgen's own defaults stay authoritative.
  const submitPayload = useMemo<Values>(() => {
    if (!schema) return {};
    const out: Values = {};
    for (const g of schema.groups) {
      for (const f of g.fields) {
        const v = values[f.name];
        if (v === "" || v === null || v === undefined) continue;
        if (f.kind === "bool" && !v) continue;       // false → don't send
        if (v === f.default && !f.required) continue; // matches default → skip
        out[f.name] = v;
      }
    }
    return out;
  }, [schema, values]);

  async function submit() {
    setBuilding(true); setBuildErr(null); setLastBuild(null);
    try {
      const res = await fetch("/api/build", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ options: submitPayload }),
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({}))).detail ?? res.statusText;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      const cd = res.headers.get("Content-Disposition") || "";
      const m = /filename="?([^"]+)"?/.exec(cd);
      const fname = m?.[1] ?? "impl.bin";
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = fname; a.click();
      URL.revokeObjectURL(url);
      setLastBuild(`${fname} — ${blob.size.toLocaleString()} bytes`);
    } catch (e) {
      setBuildErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBuilding(false);
    }
  }

  if (loadErr) {
    return (
      <Card>
        <CardHeader><CardTitle>Implant Builder</CardTitle></CardHeader>
        <CardContent>
          <pre className="text-xs text-danger">{loadErr}</pre>
        </CardContent>
      </Card>
    );
  }
  if (!schema) {
    return <div className="text-xs text-muted">loading schema…</div>;
  }
  if (!schema.avgen_present) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>avgen not found</CardTitle>
          <CardDescription>
            Expected at <code>{schema.avgen_path}</code>. Set <code>AVGEN_PATH</code> and restart the BFF.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Build"
        caption={<>avgen.py at <code>{schema.avgen_path}</code></>}
        action={
          <>
            {lastBuild && <span className="text-xs text-ok">{lastBuild}</span>}
            {buildErr && <span className="text-xs text-danger max-w-xl truncate" title={buildErr}>{buildErr}</span>}
            <Button onClick={submit} disabled={building}>
              {building ? "building…" : "build"}
            </Button>
          </>
        }
      />

      {sliverOpts && <SliverNativeCard opts={sliverOpts} />}

      <div className="rounded border border-warn/50 bg-warn/10 p-3 text-xs">
        <div className="font-semibold text-warn">avgen builds Metasploit-compatible payloads.</div>
        <p className="mt-1 text-muted leading-snug">
          {sliverOpts
            ? "Sliver-native builds are available in the card above."
            : <>
                The binary produced here calls back to a <strong>Metasploit / msfvenom</strong> handler,
                not to Sliver listeners. For an implant that connects to the mTLS/HTTPS listeners
                above, use <code>sliver-client</code>'s <code>generate</code> command — the BFF cannot
                generate Sliver implants correctly today (sliver-py's <code>generate_implant</code>
                does not perform the server-side cert template injection that the CLI does, producing
                binaries with empty caCertPEM/keyPEM/certPEM that fail TLS handshake).
              </>}
        </p>
      </div>

      {schema.groups.map((g) => (
        <GroupSection key={g.name} group={g} values={values} setValues={setValues} />
      ))}

      <details className="text-xs">
        <summary className="cursor-pointer text-muted">payload preview</summary>
        <pre className="bg-panel2 border border-border rounded p-2 mt-2 overflow-auto">
          {JSON.stringify(submitPayload, null, 2)}
        </pre>
      </details>
    </div>
  );
}
