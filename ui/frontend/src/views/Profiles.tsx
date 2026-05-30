import { useEffect, useState } from "react";
import { api, ApiError } from "@/api";
import type { ProfilePreset } from "@/types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/chrome/PageHeader";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

export function Profiles() {
  const [presets, setPresets] = useState<ProfilePreset[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    api.get<ProfilePreset[]>("/api/profiles/presets")
      .then((p) => {
        setPresets(p);
        if (p.length > 0) setSelected(p[0].name);
      })
      .catch((e: ApiError) => setErr(e.message));
  }, []);

  const current = presets.find((p) => p.name === selected);

  function download() {
    if (!current) return;
    const blob = new Blob([current.yaml], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${current.name}.http-c2.json`; a.click();
    URL.revokeObjectURL(url);
  }

  async function copyYaml() {
    if (!current) return;
    await navigator.clipboard.writeText(current.yaml);
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Profiles" />
      <Card>
        <CardHeader>
          <CardTitle>Malleable C2 Profile Presets</CardTitle>
          <CardDescription>
            Sliver <code>http-c2.json</code> configs. Save into
            <code className="mx-1">~/.sliver/configs/</code> on your server, restart sliver-server,
            then reference per-listener.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {err && <div className="text-xs text-danger">{err}</div>}
          <div className="flex flex-wrap gap-2">
            {presets.map((p) => (
              <button
                key={p.name}
                onClick={() => setSelected(p.name)}
                className={`text-xs px-2 py-1 rounded border max-lg:min-h-[44px] max-lg:px-3 ${
                  selected === p.name
                    ? "border-accent2 bg-panel2"
                    : "border-border hover:border-accent2"
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {current && (
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-sm">{current.name}</CardTitle>
              <CardDescription className="text-xs">
                <Badge tone="ok">{current.category}</Badge>
                <span className="ml-2">{current.description}</span>
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={copyYaml}>copy</Button>
              <Button size="sm" onClick={download}>download</Button>
            </div>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-panel2 border border-border rounded p-2 overflow-auto max-h-[60vh]">
              {current.yaml}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
