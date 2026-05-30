// Tiny fetch wrapper. The Vite dev proxy forwards /api to the BFF.
import { authHeaders, getToken, signalNeedAuth } from "@/lib/auth";
import { inflightStart, inflightEnd } from "@/lib/inflight";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  inflightStart();
  let res: Response;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...authHeaders(), ...(init?.headers || {}) },
      ...init,
    });
  } finally {
    inflightEnd();
  }
  if (res.status === 401) {
    // Token missing/expired/corrupt — drop it and surface the auth gate.
    signalNeedAuth();
    throw new ApiError(401, "unauthorized — paste the UI token");
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail ?? res.statusText;
    } catch {
      /* keep statusText */
    }
    const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new ApiError(res.status, msg, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

export const api = {
  get: <T,>(p: string) => request<T>(p),
  post: <T,>(p: string, body?: unknown) =>
    request<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  del: <T,>(p: string) => request<T>(p, { method: "DELETE" }),
};

import type {
  BuildSliverOptions, BuildSliverRequest, GraphSnapshot,
  ImplantExecResponse, ImplantInfo, NgrokTunnel, TaskStatus, TunnelList, TunnelRecord,
} from "./types";

// ── ngrok public exposure ──────────────────────────────────────────
export const listNgrok = () => api.get<NgrokTunnel[]>("/api/ngrok");
export const startNgrok = (listenerPort: number) =>
  api.post<NgrokTunnel>("/api/ngrok", { listener_port: listenerPort });
export const stopNgrok = (tunnelId: string) =>
  api.del(`/api/ngrok/${encodeURIComponent(tunnelId)}`);

export const getGraph = () => api.get<GraphSnapshot>("/api/graph");

export const getImplantInfo = (id: string) =>
  api.get<ImplantInfo>(`/api/implants/${encodeURIComponent(id)}/info`);

export const execImplant = (id: string, argv: string[]) =>
  api.post<ImplantExecResponse>(`/api/implants/${encodeURIComponent(id)}/exec`, { argv });

export const lsImplant = (id: string, path: string) =>
  api.post<any>(`/api/implants/${encodeURIComponent(id)}/ls`, { path });

export const psImplant = (id: string) =>
  api.post<any>(`/api/implants/${encodeURIComponent(id)}/ps`, {});

export const screenshotImplant = (id: string) =>
  api.post<{ task_id: string; queued_at: string }>(
    `/api/implants/${encodeURIComponent(id)}/screenshot`, {},
  );

export const downloadImplant = (id: string, path: string) =>
  api.post<{ task_id: string; queued_at: string }>(
    `/api/implants/${encodeURIComponent(id)}/download`, { path },
  );

export const killImplant = (id: string) =>
  api.post<any>(`/api/implants/${encodeURIComponent(id)}/kill`, {});

export const taskStatus = (taskId: string) =>
  api.get<TaskStatus>(`/api/tasks/${encodeURIComponent(taskId)}`);

export const taskResultUrl = (taskId: string) => {
  // <img src> and <a href download> can't send an Authorization header, so the
  // token rides as a query param for these GETs (the BFF accepts either).
  const t = getToken();
  const q = t ? `?token=${encodeURIComponent(t)}` : "";
  return `/api/tasks/${encodeURIComponent(taskId)}/result${q}`;
};

/** Poll a task until it reaches a terminal state. `cancelled` lets a caller
 *  (e.g. a React effect cleanup) abort the loop — useful for beacon tasks
 *  that may never complete (dead beacon). Throws ApiError(0) when cancelled. */
export async function pollTask(
  taskId: string,
  opts: { intervalMs?: number; cancelled?: () => boolean } = {},
): Promise<TaskStatus> {
  const intervalMs = opts.intervalMs ?? 1200;
  for (;;) {
    if (opts.cancelled?.()) throw new ApiError(0, "cancelled");
    const st = await taskStatus(taskId);
    if (st.state === "complete" || st.state === "error") return st;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export const buildSliverOptions = () =>
  api.get<BuildSliverOptions>("/api/build/sliver/options");

// ── tunnels ────────────────────────────────────────────────────────

export const listTunnels = (sessionId: string) =>
  api.get<TunnelList>(`/api/implants/${encodeURIComponent(sessionId)}/tunnels`);

export const createPortfwd = (sessionId: string, body: {
  bind_addr: string; bind_port: number; remote_addr: string; remote_port: number;
}) =>
  api.post<TunnelRecord>(`/api/implants/${encodeURIComponent(sessionId)}/portfwd`, body);

export const createRportfwd = (sessionId: string, body: {
  bind_addr: string; bind_port: number; remote_addr: string; remote_port: number;
}) =>
  api.post<TunnelRecord>(`/api/implants/${encodeURIComponent(sessionId)}/rportfwd`, body);

export const createSocks5 = (sessionId: string, body: {
  bind_addr: string; bind_port: number;
}) =>
  api.post<TunnelRecord>(`/api/implants/${encodeURIComponent(sessionId)}/socks5`, body);

export const deleteTunnel = (
  sessionId: string, kind: "portfwd" | "rportfwd" | "socks5", tunnelId: string,
) =>
  api.del(`/api/implants/${encodeURIComponent(sessionId)}/${kind}/${encodeURIComponent(tunnelId)}`);

/** POSTs a build request and returns the binary as a Blob plus its
 *  server-provided filename (parsed from Content-Disposition). */
export async function buildSliver(req: BuildSliverRequest): Promise<{ blob: Blob; filename: string }> {
  inflightStart();
  let res: Response;
  try {
    res = await fetch("/api/build/sliver", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(req),
    });
  } finally {
    inflightEnd();
  }
  if (!res.ok) {
    let detail: string = res.statusText;
    try { detail = (await res.json()).detail ?? res.statusText; } catch { /* keep */ }
    throw new ApiError(res.status, detail);
  }
  const cd = res.headers.get("content-disposition") ?? "";
  const m = /filename="?([^"]+)"?/.exec(cd);
  const filename = m?.[1] ?? "implant.bin";
  const blob = await res.blob();
  return { blob, filename };
}
