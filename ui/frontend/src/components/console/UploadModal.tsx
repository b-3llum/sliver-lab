/**
 * Reusable file-upload modal — opened from /console (typing `upload`) and
 * from the /graph context menu ("Upload file…"). Submits multipart/form-data
 * to /api/implants/{id}/upload and surfaces either the synchronous result
 * (session) or the queued task_id (beacon) to the caller via `onDone`.
 *
 * No new dependencies — uses native <input type="file"> + the global
 * FormData/fetch APIs.
 */
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input, Label } from "@/components/ui/Input";
import type { ImplantInfo } from "@/types";
import { authHeaders } from "@/lib/auth";
import { Sheet } from "@/components/chrome/Sheet";
import { cn } from "@/lib/cn";

const MAX_BYTES = 100 * 1024 * 1024; // mirror backend cap

export interface UploadSyncResult {
  kind: "session";
  bytes_written: number;
  dest_path: string;
}
export interface UploadQueuedResult {
  kind: "beacon";
  task_id: string;
  queued_at: string;
  /** Front-end-only fields: we know these from the form even though the
   *  server response only carries task_id. They drive the eventual result
   *  line once task_update fires. */
  bytes_written: number;
  dest_path: string;
}
export type UploadResult = UploadSyncResult | UploadQueuedResult;

export function defaultDestPath(info: ImplantInfo, filename: string): string {
  const meta = info.info as { os?: string; username?: string };
  const fn = filename || "upload";
  const osStr = String(meta.os ?? "").toLowerCase();
  if (osStr === "windows") {
    // Username can be "DOMAIN\user"; strip domain for the home-dir guess.
    const userRaw = String(meta.username ?? "");
    const user = userRaw.includes("\\") ? userRaw.split("\\").pop()! : userRaw;
    return `C:\\Users\\${user || "Public"}\\AppData\\Local\\Temp\\${fn}`;
  }
  return `/tmp/${fn}`;
}

export function UploadModal({
  implantId, info, onDone, onClose,
}: {
  implantId: string;
  info: ImplantInfo;
  onDone: (result: UploadResult) => void;
  onClose: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [dest, setDest] = useState<string>(() => defaultDestPath(info, ""));
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Re-default the dest_path when the operator picks a file (preserve manual
  // edits if they've diverged — we only auto-update if the field still
  // matches a prior default for any of the recent filenames they picked).
  const defaultForCurrent = useMemo(
    () => defaultDestPath(info, file?.name ?? ""),
    [info, file],
  );
  useEffect(() => {
    if (!file) return;
    setDest((cur) =>
      cur === "" || cur === defaultDestPath(info, "")
        ? defaultForCurrent
        : cur,
    );
  }, [file, defaultForCurrent, info]);

  function pathLooksAbsolute(p: string): boolean {
    if (!p) return false;
    if (p.startsWith("/") || p.startsWith("\\\\")) return true;
    return p.length >= 3 && /^[A-Za-z]:[\\/]/.test(p);
  }

  async function submit() {
    setErr(null);
    if (!file) { setErr("pick a file first"); return; }
    if (!dest.trim()) { setErr("dest_path is required"); return; }
    if (!pathLooksAbsolute(dest)) {
      setErr("dest_path must be absolute (e.g. C:\\Users\\… or /tmp/…)");
      return;
    }
    if (file.size > MAX_BYTES) {
      setErr(`file too large (max ${(MAX_BYTES / (1024 * 1024)).toFixed(0)} MB)`);
      return;
    }
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("file", file, file.name);
      fd.append("dest_path", dest);
      const res = await fetch(
        `/api/implants/${encodeURIComponent(implantId)}/upload`,
        { method: "POST", body: fd, headers: { ...authHeaders() } },
      );
      if (!res.ok) {
        let detail: string = res.statusText;
        try { detail = (await res.json()).detail ?? res.statusText; } catch { /* keep */ }
        throw new Error(`HTTP ${res.status}: ${detail}`);
      }
      const body = await res.json();
      let result: UploadResult;
      if (body.kind === "session") {
        result = {
          kind: "session",
          bytes_written: Number(body.bytes_written ?? file.size),
          dest_path: String(body.dest_path ?? dest),
        };
      } else {
        result = {
          kind: "beacon",
          task_id: String(body.task_id),
          queued_at: String(body.queued_at),
          bytes_written: file.size,
          dest_path: dest,
        };
      }
      onDone(result);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet
      open
      onClose={onClose}
      side="center"
      title={<>Upload file <span className="text-muted font-mono text-xs">→ {implantId.slice(0, 8)}…</span></>}
    >
      <div className="p-3 space-y-3">
        <div className="space-y-1">
          <Label>file</Label>
          <input
            type="file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className={cn(
              "block w-full text-xs",
              "file:mr-2 file:px-2 file:py-1 file:rounded file:border file:border-border",
              "file:bg-panel2 file:text-text file:cursor-pointer",
            )}
          />
          {file && (
            <div className="text-[10px] text-muted">
              {file.name} · {file.size.toLocaleString()} bytes
              {file.size > MAX_BYTES && <span className="text-danger ml-2">over limit</span>}
            </div>
          )}
        </div>
        <div className="space-y-1">
          <Label>dest_path (absolute)</Label>
          <Input
            value={dest}
            onChange={(e) => setDest(e.target.value)}
            placeholder={defaultDestPath(info, "filename")}
            className="font-mono"
          />
        </div>
        {err && <div className="text-xs text-danger">{err}</div>}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={submit} disabled={submitting || !file}>
            {submitting ? "uploading…" : "Upload"}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}
