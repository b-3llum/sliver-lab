import { useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import { taskResultUrl } from "@/api";
import type { TaskState } from "@/types";
import { cn } from "@/lib/cn";

/** One entry in the chat-style log. */
export type LogLine =
  | { kind: "input"; ts: number; text: string }
  | { kind: "output"; ts: number; text: string }
  | { kind: "info"; ts: number; text: string }
  | { kind: "error"; ts: number; text: string }
  | { kind: "queued"; ts: number; task_id: string; label: string }
  | { kind: "screenshot"; ts: number; task_id: string }
  | { kind: "download"; ts: number; task_id: string; filename: string };

/** Drives the live "runs in Xs / checking in…" suffix on queued lines. */
export interface BeaconClock {
  intervalSec: number;
  nextCheckinSec: number;
}

export function Scrollback({
  lines, beaconClock, taskStates, operatorName = null,
}: {
  lines: LogLine[];
  beaconClock: BeaconClock | null;
  /** Map of task_id → current state. Drives the queued-line suffix. */
  taskStates: Record<string, TaskState>;
  /** Non-null only in multi-operator mode → prefixes command lines with it. */
  operatorName?: string | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const [unread, setUnread] = useState(0);

  // Track scroll position; pin to bottom unless user has scrolled up.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
      setPinned(atBottom);
      if (atBottom) setUnread(0);
    };
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Auto-scroll on new content if pinned; else bump unread counter.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (pinned) el.scrollTop = el.scrollHeight;
    else setUnread((n) => n + 1);
  }, [lines, pinned]);

  // Virtual-keyboard awareness (phone): when the on-screen keyboard opens the
  // visualViewport shrinks — re-pin the scrollback to the bottom so the latest
  // line stays visible above the keyboard.
  useEffect(() => {
    const vv = window.visualViewport;
    const el = ref.current;
    if (!vv || !el) return;
    const onResize = () => { if (pinned) el.scrollTop = el.scrollHeight; };
    vv.addEventListener("resize", onResize);
    return () => vv.removeEventListener("resize", onResize);
  }, [pinned]);

  function scrollToBottom() {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    setUnread(0);
  }

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={ref} className="absolute inset-0 overflow-y-auto px-3 py-2 font-mono text-xs max-sm:text-[13px]">
        {lines.map((l, i) => (
          <LineRow
            key={i}
            line={l}
            beaconClock={beaconClock}
            taskState={l.kind === "queued" ? (taskStates[l.task_id] ?? "queued") : null}
            operatorName={operatorName}
          />
        ))}
        {lines.length === 0 && (
          <div className="text-muted text-[11px]">
            type <span className="text-text">help</span> for a list of commands.
            scrollback is in-memory and per-tab.
          </div>
        )}
      </div>
      {!pinned && unread > 0 && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-2 right-3 bg-accent text-black rounded-full px-2 py-1 text-[10px] font-semibold flex items-center gap-1"
        >
          <ArrowDown size={10} /> {unread} new
        </button>
      )}
    </div>
  );
}

function LineRow({
  line, beaconClock, taskState, operatorName = null,
}: {
  line: LogLine;
  beaconClock: BeaconClock | null;
  taskState: TaskState | null;
  operatorName?: string | null;
}) {
  const ts = new Date(line.ts).toLocaleTimeString();
  const tsCell = <span className="text-muted/50 mr-2 select-none">[{ts}]</span>;
  switch (line.kind) {
    case "input":
      return (
        <div className="flex">
          <span>{tsCell}</span>
          <span className="text-accent font-bold">
            {operatorName ? `(${operatorName}) ` : ""}{"> "}{line.text}
          </span>
        </div>
      );
    case "output":
      return (
        <div className="flex">
          <span>{tsCell}</span>
          <pre className="whitespace-pre-wrap break-all flex-1 pl-4">{line.text}</pre>
        </div>
      );
    case "info":
      return <div className="flex"><span>{tsCell}</span><span className="text-accent pl-4">{line.text}</span></div>;
    case "error":
      return <div className="flex"><span>{tsCell}</span><span className="text-danger pl-4">[error] {line.text}</span></div>;
    case "queued":
      return (
        <div className="flex">
          <span>{tsCell}</span>
          <span className="text-amber-500 italic pl-4">
            {line.label} · queued <span className="text-[10px]">({line.task_id.slice(0, 8)}…)</span>
            <LiveQueuedSuffix beaconClock={beaconClock} taskState={taskState} />
          </span>
        </div>
      );
    case "screenshot":
      return (
        <div className="flex">
          <span>{tsCell}</span>
          <div className="pl-4">
            <a href={taskResultUrl(line.task_id)} target="_blank" rel="noreferrer">
              <img
                src={taskResultUrl(line.task_id)}
                alt="screenshot"
                className="border border-border rounded"
                style={{ maxWidth: 480 }}
              />
            </a>
          </div>
        </div>
      );
    case "download":
      return (
        <div className="flex">
          <span>{tsCell}</span>
          <a
            href={taskResultUrl(line.task_id)}
            download={line.filename}
            className="text-accent2 hover:underline pl-4"
          >
            ↓ {line.filename}
          </a>
        </div>
      );
  }
}

/**
 * Suffix appended to amber queued lines. Re-renders itself once per second
 * via a local interval — its parent doesn't re-render the whole scrollback.
 *
 *   taskState === "running"          → "— running on host"  (no countdown)
 *   beaconClock present, remaining>0 → "— runs in 0m 42s"
 *   beaconClock present, overdue     → "— checking in…"
 *   beaconClock absent               → animated dots (sessions etc.)
 */
function LiveQueuedSuffix({
  beaconClock, taskState,
}: {
  beaconClock: BeaconClock | null;
  taskState: TaskState | null;
}) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Server has flipped this task to "running" — the beacon has actually
  // picked it up and is executing on the host. No clock applies here.
  if (taskState === "running") return <span> — running on host</span>;

  if (!beaconClock) return <DotSpinner />;
  const remaining = beaconClock.nextCheckinSec - Math.floor(Date.now() / 1000);
  if (remaining > 0) {
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    return <span> — runs in {m}m {s}s</span>;
  }
  // ~2 s grace before flipping to "checking in…" so the line doesn't flicker
  // right at the boundary if the clock and the result race.
  if (remaining > -2) return <span> — runs in 0m 0s</span>;
  return <span> — checking in…</span>;
}

function DotSpinner() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((x) => (x + 1) % 4), 250);
    return () => clearInterval(t);
  }, []);
  return <span className="ml-1">{".".repeat(i + 1)}</span>;
}
