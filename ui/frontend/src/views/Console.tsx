/**
 * Per-implant interactive console — the Cobalt-Strike-style beacon shell.
 *
 * One tab per attached implant. Each tab owns its own scrollback, command
 * history, and pending-task set. Sessions answer synchronously; beacons
 * queue a server-side task and the response collapses into the log on
 * next check-in (driven by the `task_update` WS envelope).
 *
 * Scrollback is in-memory and lost when the tab closes — that's by design,
 * sliver doesn't store per-implant history server-side.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Terminal } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/chrome/PageHeader";
import { TabStrip, type ConsoleTab } from "@/components/console/TabStrip";
import { ImplantPicker } from "@/components/console/ImplantPicker";
import { Scrollback, type BeaconClock, type LogLine } from "@/components/console/Scrollback";
import { CommandInput, HELP_TEXT, parseArgv } from "@/components/console/CommandInput";
import {
  UploadModal,
  type UploadResult,
} from "@/components/console/UploadModal";
import { consumePendingOp } from "@/lib/pendingOps";
import {
  api, downloadImplant, execImplant, getImplantInfo, killImplant, listTunnels,
  lsImplant, psImplant, screenshotImplant, taskStatus,
} from "@/api";
import { buildExecArgv, parseDownloadArgs } from "@/lib/commandPlan";
import { useTaskUpdates } from "@/hooks/useTaskUpdates";
import type { ImplantInfo, TaskState } from "@/types";

interface TabState {
  id: string;
  kind: "session" | "beacon";
  label: string;
  os: string;
  info: ImplantInfo;
  lines: LogLine[];
  history: string[];
  /** Map task_id → kind so result handlers know what payload to expect. */
  pending: Record<string, "exec" | "ls" | "ps" | "screenshot" | "download" | "upload" | "kill" | "interactive">;
  /** Current registry state per pending task_id. Drives the queued-line suffix. */
  taskStates: Record<string, TaskState>;
  /** Running synchronous request (sessions only) — disables the input. */
  busy: boolean;
}

function emptyTab(info: ImplantInfo, id: string): TabState {
  const meta = info.info as any;
  return {
    id,
    kind: info.kind,
    label: `${info.kind}: ${meta.username ?? "?"}@${meta.hostname ?? "?"}`,
    os: String(meta.os ?? "windows"),
    info,
    lines: [],
    history: [],
    pending: {},
    taskStates: {},
    busy: false,
  };
}

function beaconClock(info: ImplantInfo | undefined): BeaconClock | null {
  if (!info || info.kind !== "beacon") return null;
  const meta = info.info as any;
  const intervalNs = Number(meta.interval ?? 0);
  const next = Number(meta.next_checkin ?? 0);
  if (intervalNs <= 0 || next <= 0) return null;
  return { intervalSec: intervalNs / 1e9, nextCheckinSec: next };
}

export function Console() {
  const [params, setParams] = useSearchParams();
  const pathParams = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();
  const [tabs, setTabs] = useState<TabState[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [uploadTabId, setUploadTabId] = useState<string | null>(null);
  // Multi-operator awareness: prefix command lines with the operator name only
  // when more than one operator is connected (matches the graph/Phase 7c rule).
  const [myName, setMyName] = useState("");
  const [opCount, setOpCount] = useState(1);
  // Stable ref so callbacks don't recompute every render.
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;

  // Mount: if ?open=<id> or legacy /console/:sessionId, attach that tab.
  useEffect(() => {
    const id = params.get("open") ?? pathParams.sessionId;
    if (id && !tabsRef.current.find((t) => t.id === id)) {
      attachImplant(id);
      if (params.get("open")) {
        const next = new URLSearchParams(params);
        next.delete("open");
        setParams(next, { replace: true });
      } else if (pathParams.sessionId) {
        navigate("/console", { replace: true });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function attachImplant(implantId: string) {
    try {
      const info = await getImplantInfo(implantId);
      setTabs((prev) => {
        if (prev.find((t) => t.id === implantId)) return prev;
        return [...prev, emptyTab(info, implantId)];
      });
      setActiveId(implantId);
      // If we arrived here because /graph kicked off an upload, render the
      // matching scrollback line now that the tab exists.
      const op = consumePendingOp(implantId);
      if (op) handleUploadResult(implantId, op.result);
    } catch (e: any) {
      console.error("attach failed", e);
    }
  }

  function closeTab(implantId: string) {
    setTabs((prev) => prev.filter((t) => t.id !== implantId));
    if (activeId === implantId) {
      const remaining = tabsRef.current.filter((t) => t.id !== implantId);
      setActiveId(remaining.length ? remaining[remaining.length - 1].id : null);
    }
  }

  function updateTab(id: string, fn: (t: TabState) => TabState) {
    setTabs((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));
  }

  function appendLines(id: string, ...add: LogLine[]) {
    updateTab(id, (t) => ({ ...t, lines: [...t.lines, ...add] }));
  }

  /** Render an upload result into the scrollback — sync = single output
   *  line; queued = amber queued line + pending entry so the WS task_update
   *  collapses it to "uploaded N bytes to <path>" when the result lands. */
  function handleUploadResult(tabId: string, result: UploadResult) {
    if (result.kind === "session") {
      appendLines(tabId, {
        kind: "output", ts: Date.now(),
        text: `uploaded ${result.bytes_written.toLocaleString()} bytes to ${result.dest_path}`,
      });
      return;
    }
    // Beacon: register the task in pending/taskStates and emit a queued
    // line. handleTaskUpdate will swap it for the "uploaded N bytes" output
    // when complete (it reads bytes_written + dest_path from task.result,
    // which the backend extract closure populates).
    updateTab(tabId, (t) => ({
      ...t,
      pending: { ...t.pending, [result.task_id]: "upload" },
      taskStates: { ...t.taskStates, [result.task_id]: "queued" },
    }));
    appendLines(tabId, {
      kind: "queued", ts: Date.now(), task_id: result.task_id,
      label: `upload → ${result.dest_path}`,
    });
  }

  /** Replace the queued line for `taskId` with `replacement` in-place,
   *  preserving the queued line's timestamp slot.  Falls back to append
   *  if no queued line is present (e.g. result raced the queue render). */
  function replaceQueued(id: string, taskId: string, replacement: LogLine) {
    updateTab(id, (t) => {
      const idx = t.lines.findIndex(
        (l) => l.kind === "queued" && l.task_id === taskId,
      );
      if (idx === -1) return { ...t, lines: [...t.lines, replacement] };
      const queued = t.lines[idx];
      // Inherit the queued line's timestamp so the slot looks unchanged.
      const stamped: LogLine = { ...replacement, ts: queued.ts } as LogLine;
      const next = [...t.lines];
      next.splice(idx, 1, stamped);
      return { ...t, lines: next };
    });
  }

  // ── Task-update subscription ─────────────────────────────────────
  const pendingIds = useMemo(() => {
    const s = new Set<string>();
    for (const t of tabs) for (const tid of Object.keys(t.pending)) s.add(tid);
    return s;
  }, [tabs]);

  const handleTaskUpdate = useCallback(async (taskId: string, state: string) => {
    // Intermediate transition: server tells us the beacon picked up the
    // task. Just flip the per-tab state — the queued line stays put with
    // its suffix flipping from "runs in Xs" to "running on host".
    if (state === "running") {
      const owner = tabsRef.current.find((t) => taskId in t.pending);
      if (!owner) return;
      updateTab(owner.id, (t) => ({
        ...t,
        taskStates: { ...t.taskStates, [taskId]: "running" },
      }));
      return;
    }
    if (state !== "complete" && state !== "error") return;
    // Find the tab that owns this task.
    const owner = tabsRef.current.find((t) => taskId in t.pending);
    if (!owner) return;
    const action = owner.pending[taskId];
    try {
      const status = await taskStatus(taskId);
      let replacement: LogLine;
      if (status.state === "error") {
        replacement = { kind: "error", ts: Date.now(), text: status.error ?? "task error" };
      } else if (action === "exec" || action === "ls" || action === "ps") {
        replacement = formatTaskResult(status);
      } else if (action === "screenshot") {
        replacement = { kind: "screenshot", ts: Date.now(), task_id: taskId };
      } else if (action === "download") {
        const filename = (status.result as any)?.filename
          ?? `download-${taskId.slice(0, 8)}.bin`;
        replacement = { kind: "download", ts: Date.now(), task_id: taskId, filename };
      } else if (action === "kill") {
        replacement = { kind: "output", ts: Date.now(), text: "implant exit acknowledged" };
      } else if (action === "upload") {
        const r = (status.result ?? {}) as { bytes_written?: number; dest_path?: string };
        replacement = {
          kind: "output", ts: Date.now(),
          text: `uploaded ${(r.bytes_written ?? 0).toLocaleString()} bytes to ${r.dest_path ?? "?"}`,
        };
      } else if (action === "interactive") {
        const err = String((status.result as any)?.err ?? "");
        replacement = err
          ? { kind: "error", ts: Date.now(), text: `interactive failed: ${err}` }
          : { kind: "output", ts: Date.now(), text: "session opened" };
      } else {
        replacement = { kind: "output", ts: Date.now(), text: JSON.stringify(status.result ?? {}) };
      }
      replaceQueued(owner.id, taskId, replacement);
      if (action === "interactive" && status.state === "complete"
          && !((status.result as any)?.err)) {
        // Append a green info line below the result identifying the new
        // session — best-effort: match by hostname against /api/sessions.
        try {
          const sessions = await api.get<{ ID: string; hostname: string }[]>("/api/sessions");
          const beaconHost = String((owner.info.info as any).hostname ?? "");
          const candidate = sessions.find((s) => s.hostname === beaconHost);
          const idHint = candidate ? candidate.ID.slice(0, 8) : "see + open picker";
          appendLines(owner.id, {
            kind: "info", ts: Date.now(),
            text: `session opened — switch tab to operate interactively (id=${idHint})`,
          });
        } catch {
          appendLines(owner.id, {
            kind: "info", ts: Date.now(),
            text: "session opened — switch tab to operate interactively",
          });
        }
      }
    } catch (e: any) {
      replaceQueued(owner.id, taskId, {
        kind: "error", ts: Date.now(), text: e.message ?? String(e),
      });
    }
    updateTab(owner.id, (t) => {
      const nextPending = { ...t.pending };
      delete nextPending[taskId];
      const nextStates = { ...t.taskStates };
      delete nextStates[taskId];
      return { ...t, pending: nextPending, taskStates: nextStates };
    });
  }, []);
  useTaskUpdates(handleTaskUpdate, pendingIds);

  // ── Command dispatch ─────────────────────────────────────────────

  async function dispatch(tabId: string, raw: string) {
    const tab = tabsRef.current.find((t) => t.id === tabId);
    if (!tab) return;
    const now = Date.now();
    appendLines(tabId, { kind: "input", ts: now, text: raw });
    const argv = parseArgv(raw);
    const head = argv[0]?.toLowerCase();

    if (head === "help") {
      appendLines(tabId, { kind: "output", ts: Date.now(), text: HELP_TEXT });
      return;
    }
    if (head === "clear") {
      updateTab(tabId, (t) => ({ ...t, lines: [] }));
      return;
    }
    if (head === "kill") {
      if (!confirm("Tell the implant to exit?")) return;
      try {
        const res = await killImplant(tabId);
        handleQueueOrSync(tabId, res, "kill", "kill");
      } catch (e: any) {
        appendLines(tabId, { kind: "error", ts: Date.now(), text: e.message ?? String(e) });
      }
      return;
    }
    if (head === "upload") {
      if (argv.length > 1) {
        appendLines(tabId, {
          kind: "error", ts: Date.now(),
          text: "upload: type the bare command to open the file-picker modal (browser can't read local paths)",
        });
        return;
      }
      setUploadTabId(tabId);
      return;
    }
    if (head === "portfwd" || head === "rportfwd" || head === "socks5") {
      if (tab.kind !== "session") {
        appendLines(tabId, {
          kind: "error", ts: Date.now(),
          text: "tunnels require an interactive session; promote first",
        });
        return;
      }
      try {
        const list = await listTunnels(tabId);
        const rows = head === "portfwd" ? list.portfwds
          : head === "rportfwd" ? list.rportfwds
          : list.socks5;
        if (rows.length === 0) {
          appendLines(tabId, {
            kind: "output", ts: Date.now(),
            text: `no ${head}s active (use the Tunnels tab to create/delete)`,
          });
        } else {
          const lines = rows.map((r) =>
            head === "socks5"
              ? `  ${r.bind_addr}:${r.bind_port}  id=${r.id.slice(0, 8)}`
              : `  ${r.bind_addr}:${r.bind_port} -> ${r.remote_addr}:${r.remote_port}  id=${r.id.slice(0, 8)}`,
          );
          appendLines(tabId, {
            kind: "output", ts: Date.now(),
            text: `${head} (${rows.length}):\n${lines.join("\n")}\n(use the Tunnels tab to create/delete)`,
          });
        }
      } catch (e: any) {
        appendLines(tabId, { kind: "error", ts: Date.now(), text: e.message ?? String(e) });
      }
      return;
    }
    if (head === "interactive") {
      if (tab.kind !== "beacon") {
        appendLines(tabId, {
          kind: "error", ts: Date.now(),
          text: "interactive: target is already a session",
        });
        return;
      }
      try {
        const res = await api.post<{ kind: "beacon"; task_id: string; queued_at: string }>(
          `/api/implants/${encodeURIComponent(tabId)}/interactive`, {},
        );
        handleQueueOrSync(tabId, res, "interactive", "interactive");
      } catch (e: any) {
        appendLines(tabId, { kind: "error", ts: Date.now(), text: e.message ?? String(e) });
      }
      return;
    }
    if (head === "screenshot") {
      try {
        const res = await screenshotImplant(tabId);
        handleQueueOrSync(tabId, res, "screenshot", "screenshot");
      } catch (e: any) {
        appendLines(tabId, { kind: "error", ts: Date.now(), text: e.message ?? String(e) });
      }
      return;
    }
    if (head === "ls") {
      const path = argv[1] ?? ".";
      try {
        const res = await lsImplant(tabId, path);
        handleQueueOrSync(tabId, res, "ls", `ls ${path}`);
      } catch (e: any) {
        appendLines(tabId, { kind: "error", ts: Date.now(), text: e.message ?? String(e) });
      }
      return;
    }
    if (head === "ps") {
      try {
        const res = await psImplant(tabId);
        handleQueueOrSync(tabId, res, "ps", "ps");
      } catch (e: any) {
        appendLines(tabId, { kind: "error", ts: Date.now(), text: e.message ?? String(e) });
      }
      return;
    }
    if (head === "download") {
      const parsed = parseDownloadArgs(argv);
      if ("error" in parsed) {
        appendLines(tabId, { kind: "error", ts: Date.now(), text: parsed.error });
        return;
      }
      try {
        const res = await downloadImplant(tabId, parsed.path);
        handleQueueOrSync(tabId, res, "download", `download ${parsed.path}`);
      } catch (e: any) {
        appendLines(tabId, { kind: "error", ts: Date.now(), text: e.message ?? String(e) });
      }
      return;
    }
    // pwd / cat / fallthrough → /exec (cat/pwd are cmd builtins on Windows)
    const execArgv = buildExecArgv(head, argv, tab.os);
    // sessions get busy-flag; beacons return queued
    if (tab.kind === "session") {
      updateTab(tabId, (t) => ({ ...t, busy: true }));
    }
    try {
      const res = await execImplant(tabId, execArgv);
      handleQueueOrSync(tabId, res, "exec", raw);
    } catch (e: any) {
      appendLines(tabId, { kind: "error", ts: Date.now(), text: e.message ?? String(e) });
    } finally {
      if (tab.kind === "session") updateTab(tabId, (t) => ({ ...t, busy: false }));
    }
  }

  function handleQueueOrSync(
    tabId: string,
    res: any,
    action: TabState["pending"][string],
    label: string,
  ) {
    if (res && res.kind === "beacon" && res.task_id) {
      updateTab(tabId, (t) => ({
        ...t,
        pending: { ...t.pending, [res.task_id]: action },
        taskStates: { ...t.taskStates, [res.task_id]: "queued" },
      }));
      appendLines(tabId, {
        kind: "queued", ts: Date.now(), task_id: res.task_id, label,
      });
      return;
    }
    if (res && res.task_id) {
      // session-as-task (screenshot/download) — no beacon clock, no
      // intermediate running state, just queue then complete.
      updateTab(tabId, (t) => ({
        ...t,
        pending: { ...t.pending, [res.task_id]: action },
        taskStates: { ...t.taskStates, [res.task_id]: "queued" },
      }));
      appendLines(tabId, {
        kind: "queued", ts: Date.now(), task_id: res.task_id, label,
      });
      return;
    }
    // synchronous response
    if (action === "exec") {
      const stdout = String(res?.stdout ?? "");
      const stderr = String(res?.stderr ?? "");
      const text = (stdout + (stderr ? `\n${stderr}` : "")).trim() || "(no output)";
      appendLines(tabId, { kind: "output", ts: Date.now(), text });
    } else if (action === "ls") {
      const entries = (res?.entries ?? []) as Array<{ name: string; size: number; is_dir: boolean }>;
      const text = entries.length
        ? entries.map((e) => (e.is_dir ? `${e.name}/` : `${e.name}  ${e.size}`)).join("\n")
        : "(empty)";
      appendLines(tabId, { kind: "output", ts: Date.now(), text });
    } else if (action === "ps") {
      const procs = (res?.processes ?? []) as Array<{ pid: number; name: string; owner: string }>;
      const text = procs.length
        ? procs.map((p) => `${String(p.pid).padStart(6)}  ${p.name}  ${p.owner}`).join("\n")
        : "(none)";
      appendLines(tabId, { kind: "output", ts: Date.now(), text });
    } else if (action === "kill") {
      appendLines(tabId, { kind: "output", ts: Date.now(), text: "implant exit acknowledged" });
    }
  }

  const active = tabs.find((t) => t.id === activeId) ?? null;
  const stripTabs: ConsoleTab[] = tabs.map((t) => ({
    id: t.id, label: t.label, kind: t.kind,
    pending: Object.keys(t.pending).length,
  }));

  function setActiveTabHistory(h: string[]) {
    if (!active) return;
    updateTab(active.id, (t) => ({ ...t, history: h }));
  }

  // Slow-cadence ImplantInfo refresh so interval / next_checkin stay
  // approximately current when a tab is left open. One poller per active
  // tab; cancelled when the active tab changes or unmounts.
  useEffect(() => {
    if (!active) return;
    const id = active.id;
    const i = setInterval(async () => {
      try {
        const info = await getImplantInfo(id);
        updateTab(id, (t) => ({ ...t, info }));
      } catch { /* transient — try again next tick */ }
    }, 30_000);
    return () => clearInterval(i);
  }, [active?.id]);

  // ── Keyboard shortcuts ───────────────────────────────────────────
  // One window-level handler (capture phase) so Ctrl+W can pre-empt the
  // browser's own tab-close. Ctrl-only on all platforms — we deliberately do
  // NOT also bind Cmd on macOS, so the muscle memory is identical everywhere
  // (documented in HELP_TEXT). Plain keys fall through to the command input.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // Esc: close the picker if open, otherwise no-op (let it bubble).
      if (e.key === "Escape") {
        if (pickerOpen) { e.preventDefault(); setPickerOpen(false); }
        return;
      }
      const ctrl = e.ctrlKey && !e.metaKey && !e.altKey;
      if (!ctrl) return;

      const k = e.key.toLowerCase();
      if (k === "t") {                       // open the "+ open" picker
        e.preventDefault();
        setPickerOpen(true);
      } else if (k === "w") {                // close active tab
        e.preventDefault();
        if (!activeId) return;
        const tab = tabsRef.current.find((t) => t.id === activeId);
        const pending = tab ? Object.keys(tab.pending).length : 0;
        if (pending > 0 &&
            !confirm(`${pending} task${pending === 1 ? "" : "s"} pending; close anyway?`)) {
          return;
        }
        closeTab(activeId);
      } else if (k === "k") {                // clear scrollback (alias of `clear`)
        e.preventDefault();
        if (activeId) updateTab(activeId, (t) => ({ ...t, lines: [] }));
      } else if (/^[0-9]$/.test(e.key)) {    // Ctrl+1..9 / Ctrl+0 → tab N / 10
        const n = e.key === "0" ? 10 : parseInt(e.key, 10);
        const target = tabsRef.current[n - 1];
        if (target) {
          e.preventDefault();
          setActiveId(target.id);
        }
      }
    }
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
    // Re-bind when activeId/pickerOpen change so closeTab's closure stays fresh.
  }, [activeId, pickerOpen]);

  // Operator roster: who am I, and how many are connected (30s cadence).
  useEffect(() => {
    api.get<{ name: string }>("/api/operators/me")
      .then((r) => setMyName(r.name)).catch(() => {});
    const load = () => api.get<{ name: string; online: boolean }[]>("/api/operators")
      .then((o) => setOpCount(o.length)).catch(() => {});
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, []);
  const operatorName = opCount > 1 ? myName : null;

  const activeBeaconClock = beaconClock(active?.info);

  return (
    <div className="h-[calc(100vh-2rem)] flex flex-col">
      {/* Anchor the floating tab strip with a title at desktop. */}
      <div className="hidden lg:block"><PageHeader title="Console" /></div>
      <Card className="flex-1 flex flex-col !p-0 overflow-hidden">
        <TabStrip
          tabs={stripTabs}
          activeId={activeId}
          onSelect={setActiveId}
          onClose={closeTab}
          onAdd={() => setPickerOpen(true)}
        />
        {active ? (
          <>
            <TabHeader tab={active} />
            <Scrollback
              lines={active.lines}
              beaconClock={activeBeaconClock}
              taskStates={active.taskStates}
              operatorName={operatorName}
            />
            <CommandInput
              onSubmit={(line) => dispatch(active.id, line)}
              busy={active.busy}
              history={active.history}
              setHistory={setActiveTabHistory}
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <EmptyState
              icon={Terminal}
              title="No tabs attached"
              description="Attach a remote target from the picker to start driving it."
              cta={
                <Button variant="outline" size="sm" onClick={() => setPickerOpen(true)}>
                  + open
                </Button>
              }
            />
          </div>
        )}
      </Card>
      {pickerOpen && (
        <ImplantPicker
          openIds={new Set(tabs.map((t) => t.id))}
          onPick={(id) => attachImplant(id)}
          onClose={() => setPickerOpen(false)}
        />
      )}
      {uploadTabId && (() => {
        const t = tabs.find((x) => x.id === uploadTabId);
        if (!t) return null;
        return (
          <UploadModal
            implantId={t.id}
            info={t.info}
            onDone={(res) => handleUploadResult(t.id, res)}
            onClose={() => setUploadTabId(null)}
          />
        );
      })()}
    </div>
  );
}

// ── Per-tab header strip ───────────────────────────────────────────

function TabHeader({ tab }: { tab: TabState }) {
  // Single-line strip with kind-specific content. Beacon's countdown ticks
  // every second via a local interval — only this strip re-renders, not
  // the whole tab.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (tab.kind !== "beacon") return;
    const id = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, [tab.kind]);

  const meta = tab.info.info as any;
  const pendingCount = Object.keys(tab.pending).length;

  if (tab.kind === "beacon") {
    const intervalSec = Math.round(Number(meta.interval ?? 0) / 1e9);
    const next = Number(meta.next_checkin ?? 0);
    const nowSec = Math.floor(Date.now() / 1000);
    const remaining = next - nowSec;
    return (
      <div className="px-3 py-1 border-b border-border text-[10px] font-mono text-muted bg-panel2/40 flex flex-wrap gap-x-3 gap-y-0.5">
        <span className="text-amber-500">beacon</span>
        <span>interval {intervalSec}s</span>
        {remaining >= 0 ? (
          <span>next check-in in {Math.floor(remaining / 60)}m {remaining % 60}s</span>
        ) : (
          <span className="text-danger">next check-in overdue by {-remaining}s</span>
        )}
        <span>{pendingCount} task{pendingCount === 1 ? "" : "s"} pending</span>
      </div>
    );
  }
  // Session: static descriptor.
  return (
    <div className="px-3 py-1 border-b border-border text-[10px] font-mono text-muted bg-panel2/40 flex flex-wrap gap-x-3 gap-y-0.5">
      <span className="text-accent">session</span>
      {meta.pid ? <span>pid {meta.pid}</span> : null}
      <span>transport {String(meta.transport ?? "?")}</span>
      {meta.remote_address ? <span>{String(meta.remote_address)}</span> : null}
      {pendingCount > 0 && (
        <span>{pendingCount} task{pendingCount === 1 ? "" : "s"} pending</span>
      )}
    </div>
  );
}

function formatTaskResult(status: { kind: string; result: any }): LogLine {
  const r = status.result ?? {};
  const action = status.kind;
  if (action === "exec") {
    const stdout = String(r.stdout ?? "");
    const stderr = String(r.stderr ?? "");
    const text = (stdout + (stderr ? `\n${stderr}` : "")).trim() || "(no output)";
    return { kind: "output", ts: Date.now(), text };
  }
  if (action === "ls") {
    const entries = (r.entries ?? []) as Array<{ name: string; size: number; is_dir: boolean }>;
    const text = entries.length
      ? entries.map((e) => (e.is_dir ? `${e.name}/` : `${e.name}  ${e.size}`)).join("\n")
      : "(empty)";
    return { kind: "output", ts: Date.now(), text };
  }
  if (action === "ps") {
    const procs = (r.processes ?? []) as Array<{ pid: number; name: string; owner: string }>;
    const text = procs.length
      ? procs.map((p) => `${String(p.pid).padStart(6)}  ${p.name}  ${p.owner}`).join("\n")
      : "(none)";
    return { kind: "output", ts: Date.now(), text };
  }
  return { kind: "output", ts: Date.now(), text: JSON.stringify(r) };
}
