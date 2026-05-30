/**
 * C2 topology graph — Cobalt-Strike-style pivot view.
 *
 * Layout is fully deterministic (hierarchical: teamserver → listeners →
 * implants, grouped by hostname with brackets). Rendered to a raw <canvas>;
 * no force simulation. See components/graph/icons.ts for the sprite drawers.
 *
 * Polish pass: auto-scaled spacing when the graph underfills the canvas;
 * listener row wraps; per-group 2-row layout with horizontal scroll when
 * >12 implants under a single listener; right-click context menu; legend.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Info, Maximize2, X } from "lucide-react";
import { api, getGraph } from "@/api";
import { toast } from "@/lib/toast";
import { useLongPress } from "@/hooks/useLongPress";
import { useBreakpoint } from "@/hooks/useBreakpoint";
import { Sheet } from "@/components/chrome/Sheet";
import type { GraphNode, GraphSnapshot, GraphEdge, ImplantInfo } from "@/types";
import { UploadModal, type UploadResult } from "@/components/console/UploadModal";
import { setPendingOp } from "@/lib/pendingOps";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useGraphDirty } from "@/hooks/useGraphDirty";
import { cn } from "@/lib/cn";
import {
  COLORS, SIZES, drawDotGrid, drawGuide, drawHostBracket, drawIcon, drawPolyline,
  sizeOf, type IconKind,
} from "@/components/graph/icons";

// ── Filter state (URL hash, never localStorage) ────────────────────

type FilterState = {
  teamserver: boolean;
  listener: boolean;
  beacon: boolean;
  session: boolean;
  host: boolean;
  grid: boolean;
  legend: boolean;
};

const TOGGLE_KEYS: (keyof FilterState)[] = [
  "teamserver", "listener", "beacon", "session", "host", "grid",
];

function defaultFilters(): FilterState {
  return {
    teamserver: true, listener: true, beacon: true, session: true,
    host: true, grid: false, legend: false,
  };
}

function parseHash(hash: string): FilterState {
  const f = defaultFilters();
  const stripped = hash.replace(/^#/, "");
  for (const part of stripped.split("&")) {
    const [k, v] = part.split("=");
    if (k === "hide") {
      for (const hidden of (v ?? "").split(",")) {
        if (hidden && hidden !== "grid" && hidden !== "legend"
            && (TOGGLE_KEYS as string[]).includes(hidden)) {
          (f as any)[hidden] = false;
        }
      }
    } else if (k === "grid") {
      f.grid = v === "1";
    } else if (k === "legend") {
      f.legend = v === "1";
    }
  }
  return f;
}

function serializeHash(f: FilterState): string {
  const hidden = TOGGLE_KEYS.filter((k) => k !== "grid" && !f[k]);
  const parts: string[] = [];
  if (hidden.length) parts.push(`hide=${hidden.join(",")}`);
  if (f.grid) parts.push("grid=1");
  if (f.legend) parts.push("legend=1");
  return parts.length ? "#" + parts.join("&") : "";
}

// ── Layout ─────────────────────────────────────────────────────────

const TS_Y = 60;
const LISTENER_Y_BASE = 200;
const LISTENER_ROW_DY = 110;
const IMPLANT_Y0_BASE = 340;
const IMPLANT_DX_BASE = 110;
const IMPLANT_DY_BASE = 130;
const COLS_NORMAL = 4;
const COLS_TWO_ROW = 8;          // per row when in 2-row mode
const GROUP_HORIZ_LIMIT = 12;    // beyond this, switch to scrollable strip
const LISTENER_GAP_MIN = 160;
const UNKNOWN_DIVIDER_GAP = 80;

interface Placed {
  node: GraphNode;
  x: number;
  y: number;
  groupId?: string;   // listener id this implant belongs to (used for clipping/scroll)
}

interface Bracket {
  hostname: string;
  leftX: number;
  rightX: number;
  y: number;
  groupId: string;
}

interface Group {
  listenerId: string;
  centerX: number;
  topY: number;
  bottomY: number;
  width: number;       // virtual width (may exceed canvas)
  visibleWidth: number;
  scrollable: boolean;
}

interface Layout {
  placed: Map<string, Placed>;
  brackets: Bracket[];
  edges: GraphEdge[];
  groups: Map<string, Group>;
  hasUnknown: boolean;
  unknownDividerX: number | null;
  contentHeight: number;
  contentWidth: number;
  scale: number;
}

function listenerGlyph(name: string): string {
  const n = name.toLowerCase();
  if (n.startsWith("mtls")) return "M";
  if (n.startsWith("https")) return "H";
  if (n.startsWith("http")) return "H";
  if (n.startsWith("dns")) return "D";
  if (n.startsWith("wg")) return "W";
  return name.slice(0, 1).toUpperCase() || "?";
}

function trunc(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

/** Shrink text to fit maxWidth (px) by dropping middle chars: "WIN10-S…user". */
function middleTruncate(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (maxWidth <= 0) return "…";
  if (ctx.measureText(text).width <= maxWidth) return text;
  let head = Math.ceil(text.length / 2);
  let tail = text.length - head;
  while (head + tail > 0) {
    if (tail >= head && tail > 0) tail--;
    else if (head > 0) head--;
    const cand = text.slice(0, head) + "…" + text.slice(text.length - tail);
    if (ctx.measureText(cand).width <= maxWidth) return cand;
  }
  return "…";
}

/**
 * Per-implant horizontal label budget (px) so shared-hostname rows don't render
 * overlapping label text. For each session/beacon, the budget is the gap to its
 * nearest same-row neighbour (minus padding); Infinity when it has the row to
 * itself. Drives the pid/middle-truncate fallback in drawLabel — no layout
 * engine change, just a draw-time collision check.
 */
function computeLabelBudget(placed: Map<string, Placed>): Map<string, number> {
  const budget = new Map<string, number>();
  const rows = new Map<number, Placed[]>();
  for (const p of placed.values()) {
    if (p.node.kind !== "session" && p.node.kind !== "beacon") continue;
    const key = Math.round(p.y);
    const arr = rows.get(key);
    if (arr) arr.push(p); else rows.set(key, [p]);
  }
  for (const row of rows.values()) {
    row.sort((a, b) => a.x - b.x);
    for (let i = 0; i < row.length; i++) {
      const left = i > 0 ? row[i].x - row[i - 1].x : Infinity;
      const right = i < row.length - 1 ? row[i + 1].x - row[i].x : Infinity;
      budget.set(row[i].node.id, Math.min(left, right) - 8);
    }
  }
  return budget;
}

function computeLayout(
  snap: GraphSnapshot, filters: FilterState, canvasW: number, canvasH: number,
  groupScroll: Record<string, number>,
): Layout {
  // Partition.
  const ts = snap.nodes.find((n) => n.kind === "teamserver");
  const realListeners = snap.nodes
    .filter((n) => n.kind === "listener")
    .sort((a, b) => Number(a.meta.port ?? 0) - Number(b.meta.port ?? 0));
  const unknownListeners = snap.nodes.filter((n) => n.kind === "unknown-listener");
  const implants = snap.nodes
    .filter((n) => n.kind === "beacon" || n.kind === "session")
    .sort((a, b) => {
      const ha = String(a.meta.hostname ?? "");
      const hb = String(b.meta.hostname ?? "");
      if (ha !== hb) return ha.localeCompare(hb);
      return String(a.meta.username ?? "").localeCompare(String(b.meta.username ?? ""));
    });

  // First pass at scale=1, then auto-scale based on content size.
  let scale = 1;
  for (let pass = 0; pass < 2; pass++) {
    const placed = new Map<string, Placed>();
    const brackets: Bracket[] = [];
    const groups = new Map<string, Group>();
    let hasUnknown = false;
    let unknownDividerX: number | null = null;

    const LISTENER_GAP = LISTENER_GAP_MIN * scale;
    const IMPLANT_DX = IMPLANT_DX_BASE * scale;
    const IMPLANT_DY = IMPLANT_DY_BASE * scale;
    const IMPLANT_Y0 = IMPLANT_Y0_BASE;

    if (ts && filters.teamserver) {
      placed.set(ts.id, { node: ts, x: Math.round(canvasW / 2), y: TS_Y });
    }

    // Listener row, with horizontal wrap.
    const visibleListeners = filters.listener ? realListeners : [];
    const visibleUnknown = filters.listener ? unknownListeners : [];
    const totalCols = visibleListeners.length + (visibleUnknown.length > 0 ? 1 : 0);
    const maxCols = Math.max(1, Math.floor((canvasW - 80) / LISTENER_GAP));
    const colsPerRow = Math.min(maxCols, totalCols || 1);
    const rowCount = Math.ceil(totalCols / colsPerRow);

    let placedIdx = 0;
    const placeAtIndex = (n: GraphNode, idx: number) => {
      const row = Math.floor(idx / colsPerRow);
      const col = idx % colsPerRow;
      const colsThisRow = row === rowCount - 1
        ? totalCols - row * colsPerRow
        : colsPerRow;
      const startX = canvasW / 2 - ((colsThisRow - 1) * LISTENER_GAP) / 2;
      const x = Math.round(startX + col * LISTENER_GAP);
      const y = LISTENER_Y_BASE + row * LISTENER_ROW_DY;
      placed.set(n.id, { node: n, x, y });
    };
    for (const l of visibleListeners) {
      placeAtIndex(l, placedIdx++);
    }
    if (visibleUnknown.length > 0) {
      hasUnknown = true;
      // Divider between last real listener (if same row) and unknown bucket.
      if (visibleListeners.length > 0) {
        const lastListener = placed.get(visibleListeners[visibleListeners.length - 1].id)!;
        const nextRow = Math.floor(placedIdx / colsPerRow);
        const lastRow = Math.floor((placedIdx - 1) / colsPerRow);
        if (lastRow === nextRow) {
          unknownDividerX = Math.round(lastListener.x + LISTENER_GAP / 2 - UNKNOWN_DIVIDER_GAP / 2);
        }
      }
      for (const u of visibleUnknown) {
        placeAtIndex(u, placedIdx++);
      }
    }

    const lastListenerRow = rowCount - 1;
    const implantsStartY = IMPLANT_Y0_BASE + lastListenerRow * LISTENER_ROW_DY - LISTENER_ROW_DY + LISTENER_ROW_DY;
    // (i.e. IMPLANT_Y0_BASE shifted down by the listener-row stack height)
    const effectiveImplantY0 = IMPLANT_Y0_BASE + lastListenerRow * LISTENER_ROW_DY;

    // Implant edges → parent map.
    const implantParent = new Map<string, string>();
    for (const e of snap.edges) {
      if (e.kind === "session" || e.kind === "beacon") implantParent.set(e.target, e.source);
    }

    // Group implants by parent listener.
    const grouped = new Map<string, GraphNode[]>();
    for (const im of implants) {
      if (im.kind === "beacon" && !filters.beacon) continue;
      if (im.kind === "session" && !filters.session) continue;
      const parent = implantParent.get(im.id);
      if (!parent || !placed.has(parent)) continue;
      if (!grouped.has(parent)) grouped.set(parent, []);
      grouped.get(parent)!.push(im);
    }

    for (const [listenerId, list] of grouped) {
      const lp = placed.get(listenerId)!;
      const count = list.length;

      // Decide row/col layout for this group.
      let cols: number, rows: number, scrollable = false;
      if (count <= COLS_NORMAL) {
        cols = count; rows = 1;
      } else if (count <= GROUP_HORIZ_LIMIT) {
        cols = Math.ceil(count / 2); rows = 2;
      } else {
        cols = Math.ceil(count / 2); rows = 2; scrollable = true;
      }

      const groupVisibleCols = scrollable ? COLS_TWO_ROW : cols;
      const groupVisibleWidth = (groupVisibleCols - 1) * IMPLANT_DX + sizeOf("beacon").w;
      const fullWidth = (cols - 1) * IMPLANT_DX + sizeOf("beacon").w;
      const scrollOffset = scrollable ? (groupScroll[listenerId] ?? 0) : 0;

      // Children laid out centered under listener (the group center == listener.x).
      // Position relative to a "group origin" at listener.x.
      list.forEach((im, idx) => {
        const row = Math.floor(idx / cols);
        const col = idx % cols;
        const localX = -((cols - 1) * IMPLANT_DX) / 2 + col * IMPLANT_DX - scrollOffset;
        const x = Math.round(lp.x + localX);
        const y = effectiveImplantY0 + row * IMPLANT_DY;
        placed.set(im.id, { node: im, x, y, groupId: listenerId });
      });

      const topY = effectiveImplantY0 - sizeOf("beacon").h / 2;
      const bottomY = effectiveImplantY0 + (rows - 1) * IMPLANT_DY + sizeOf("beacon").h / 2;
      groups.set(listenerId, {
        listenerId,
        centerX: lp.x,
        topY,
        bottomY,
        width: fullWidth,
        visibleWidth: groupVisibleWidth,
        scrollable,
      });

      if (filters.host) {
        // Build brackets across consecutive same-hostname runs.
        let runStart = 0;
        while (runStart < count) {
          const hostname = String(list[runStart].meta.hostname ?? "");
          let runEnd = runStart;
          while (runEnd + 1 < count
                 && String(list[runEnd + 1].meta.hostname ?? "") === hostname) {
            runEnd++;
          }
          if (hostname) {
            const start = placed.get(list[runStart].id)!;
            const end = placed.get(list[runEnd].id)!;
            // Bracket sits below the *bottom* row's labels.
            const lastRowY = effectiveImplantY0 + (rows - 1) * IMPLANT_DY;
            const labelBottom = lastRowY + sizeOf("beacon").h / 2 + 28; // icon_h/2 + two label lines
            brackets.push({
              groupId: listenerId,
              hostname,
              leftX: Math.min(start.x, end.x) - 26,
              rightX: Math.max(start.x, end.x) + 26,
              y: labelBottom + 8,
            });
          }
          runStart = runEnd + 1;
        }
      }
    }

    // Content extents.
    let maxY = TS_Y + 24;
    let minX = Infinity, maxX = -Infinity;
    for (const p of placed.values()) {
      const s = sizeOf(p.node.kind as IconKind);
      maxY = Math.max(maxY, p.y + s.h / 2);
      minX = Math.min(minX, p.x - s.w / 2);
      maxX = Math.max(maxX, p.x + s.w / 2);
    }
    for (const b of brackets) {
      maxY = Math.max(maxY, b.y + 24);
      minX = Math.min(minX, b.leftX);
      maxX = Math.max(maxX, b.rightX);
    }
    if (!isFinite(minX)) { minX = 0; maxX = canvasW; }

    const occupiedH = (maxY - 40) / canvasH;
    const occupiedW = (maxX - minX) / canvasW;

    // Autoscale on first pass only.
    if (pass === 0) {
      let target = 1;
      if (occupiedH < 0.4) target = Math.min(2.5, 0.7 / Math.max(occupiedH, 0.05));
      if (occupiedW < 0.3) target = Math.min(target, Math.min(2.5, 0.7 / Math.max(occupiedW, 0.05)));
      if (occupiedH > 0.4 && occupiedW > 0.3) target = 1;
      scale = Math.max(1, Math.min(target, 2.5));
      if (Math.abs(scale - 1) < 0.05) {
        // good enough, finish with current placement
        return {
          placed, brackets, edges: snap.edges, groups,
          hasUnknown, unknownDividerX,
          contentHeight: Math.max(maxY + 40, canvasH),
          contentWidth: Math.max(maxX - minX + 80, canvasW),
          scale: 1,
        };
      }
      // else run second pass at the new scale
      continue;
    }

    return {
      placed, brackets, edges: snap.edges, groups,
      hasUnknown, unknownDividerX,
      contentHeight: Math.max(maxY + 40, canvasH),
      contentWidth: Math.max(maxX - minX + 80, canvasW),
      scale,
    };
  }
  // Unreachable
  throw new Error("layout pass exhausted");
}

// ── Edge styling derivation ────────────────────────────────────────

function isLateBeacon(meta: Record<string, unknown>): boolean {
  const intervalNs = Number(meta.interval ?? 0);
  const next = Number(meta.next_checkin ?? 0);
  if (intervalNs <= 0 || next <= 0) return false;
  const intervalSec = intervalNs / 1e9;
  const nowSec = Date.now() / 1000;
  return nowSec - next > 2 * intervalSec;
}

function isElevated(meta: Record<string, unknown>): boolean {
  const u = String(meta.username ?? "");
  const integrity = String((meta.integrity as string) ?? "");
  if (/SYSTEM|administrator|root/i.test(u)) return true;
  if (/high|system/i.test(integrity)) return true;
  return false;
}

// ── Canvas renderer ────────────────────────────────────────────────

function render(
  ctx: CanvasRenderingContext2D,
  layout: Layout,
  size: { w: number; h: number },
  filters: FilterState,
  selectedId: string | null,
  dpr: number,
): void {
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, size.w, size.h);
  if (filters.grid) drawDotGrid(ctx, size.w, size.h);

  // Vertical guides under each listener.
  for (const g of layout.groups.values()) {
    drawGuide(ctx, g.centerX, g.topY - 8, g.bottomY + 30);
  }

  // Edges
  for (const e of layout.edges) {
    const a = layout.placed.get(e.source);
    const b = layout.placed.get(e.target);
    if (!a || !b) continue;
    let color = COLORS.fgDim;
    let width = 1;
    let dash: number[] = [];
    if (e.kind === "session") { color = COLORS.accent; width = 2; }
    else if (e.kind === "beacon") {
      const late = isLateBeacon(b.node.meta);
      color = late ? COLORS.danger : COLORS.amber;
      width = 2;
      dash = [6, 4];
    }
    const aSize = sizeOf(a.node.kind as IconKind);
    const bSize = sizeOf(b.node.kind as IconKind);
    drawPolyline(ctx, a.x, a.y + aSize.h / 2, b.x, b.y - bSize.h / 2, { color, width, dash });
  }

  // Unknown-listener divider
  if (layout.unknownDividerX !== null) {
    ctx.save();
    ctx.strokeStyle = COLORS.fgDim;
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(layout.unknownDividerX + 0.5, LISTENER_Y_BASE - 30);
    ctx.lineTo(layout.unknownDividerX + 0.5, IMPLANT_Y0_BASE + 60);
    ctx.stroke();
    ctx.restore();
  }

  // Brackets
  for (const br of layout.brackets) {
    drawHostBracket(ctx, br.leftX, br.rightX, br.y, br.hostname);
  }

  // Nodes
  const labelBudget = computeLabelBudget(layout.placed);
  for (const p of layout.placed.values()) {
    const meta = p.node.meta;
    const elevated = isElevated(meta);
    const selected = selectedId === p.node.id;
    const kind = p.node.kind as IconKind;
    if (kind === "listener" || kind === "unknown-listener") {
      drawIcon(ctx, kind, p.x, p.y, {
        kindGlyph: listenerGlyph(p.node.label.split(":")[0] || String(meta.name ?? "")),
        selected,
      });
    } else if (kind === "session") {
      drawIcon(ctx, "session", p.x, p.y, { realtime: true, elevated, selected });
    } else if (kind === "beacon") {
      drawIcon(ctx, "beacon", p.x, p.y, { elevated, selected });
    } else if (kind === "teamserver") {
      drawIcon(ctx, "teamserver", p.x, p.y, { selected });
    }
    drawLabel(ctx, p, labelBudget.get(p.node.id));
  }

  ctx.restore();
}

function drawLabel(ctx: CanvasRenderingContext2D, p: Placed, budget?: number): void {
  ctx.fillStyle = COLORS.fg;
  ctx.font = "12px ui-monospace, Menlo, monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const kind = p.node.kind as IconKind;
  const half = sizeOf(kind).h / 2;
  const baseY = p.y + half + 6;
  switch (kind) {
    case "teamserver":
      ctx.fillText("teamserver", p.x, baseY);
      break;
    case "listener":
    case "unknown-listener":
      ctx.fillText(p.node.label, p.x, baseY);
      break;
    case "beacon":
    case "session": {
      const avail = budget ?? Infinity;
      // Username line (12px). If it overflows the row budget, fall back to the
      // PID; if even that overflows (rare), middle-truncate it. Full username +
      // hostname remain available via the hover tooltip and tap-drawer.
      let userLine = trunc(String(p.node.meta.username ?? "?"), 18);
      if (Number.isFinite(avail) && ctx.measureText(userLine).width > avail) {
        userLine = `pid ${p.node.meta.pid ?? "?"}`;
        if (ctx.measureText(userLine).width > avail) {
          userLine = middleTruncate(ctx, userLine, avail);
        }
      }
      ctx.fillText(userLine, p.x, baseY);
      // Hostname line (10px, grey) — middle-truncate if it still overflows.
      ctx.fillStyle = "#94a3b8";
      ctx.font = "10px ui-monospace, Menlo, monospace";
      let hostLine = trunc(String(p.node.meta.hostname ?? "?"), 18);
      if (Number.isFinite(avail) && ctx.measureText(hostLine).width > avail) {
        hostLine = middleTruncate(ctx, hostLine, avail);
      }
      ctx.fillText(hostLine, p.x, baseY + 14);
      break;
    }
  }
}

// ── Component ─────────────────────────────────────────────────────

type CtxMenu = {
  x: number;
  y: number;
  target: GraphNode | null;  // null = empty canvas
};

export function Graph() {
  const [snapshot, setSnapshot] = useState<GraphSnapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterState>(() => parseHash(location.hash));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hover, setHover] = useState<{ node: GraphNode; x: number; y: number } | null>(null);
  const [menu, setMenu] = useState<CtxMenu | null>(null);
  const [uploadFor, setUploadFor] = useState<{ id: string; info: ImplantInfo } | null>(null);
  const [groupScroll, setGroupScroll] = useState<Record<string, number>>({});
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 1000, h: 700 });
  const navigate = useNavigate();
  const phone = useBreakpoint() === "phone";

  // Resize observer
  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      setSize({ w: Math.max(400, r.width), h: Math.max(400, r.height) });
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const refetch = useCallback(() => {
    getGraph().then(setSnapshot).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => { refetch(); }, [refetch]);
  useGraphDirty(refetch);

  // Hash sync
  useEffect(() => {
    const next = serializeHash(filters);
    if (next !== location.hash) {
      history.replaceState(null, "", next || location.pathname + location.search);
    }
  }, [filters]);

  const layout = useMemo<Layout | null>(() => {
    if (!snapshot) return null;
    return computeLayout(snapshot, filters, size.w, size.h, groupScroll);
  }, [snapshot, filters, size, groupScroll]);

  // Draw
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !layout) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size.w * dpr;
    canvas.height = size.h * dpr;
    canvas.style.width = `${size.w}px`;
    canvas.style.height = `${size.h}px`;
    const ctx = canvas.getContext("2d")!;
    ctx.imageSmoothingEnabled = false;
    render(ctx, layout, size, filters, selectedId, dpr);
  }, [layout, size, filters, selectedId]);

  // Hit-test
  const hitNode = useCallback((mx: number, my: number): GraphNode | null => {
    if (!layout) return null;
    for (const p of layout.placed.values()) {
      const s = sizeOf(p.node.kind as IconKind);
      if (mx >= p.x - s.w / 2 && mx <= p.x + s.w / 2
          && my >= p.y - s.h / 2 && my <= p.y + s.h / 2) {
        return p.node;
      }
    }
    return null;
  }, [layout]);

  function canvasPos(e: React.MouseEvent<HTMLCanvasElement>) {
    const r = (e.target as HTMLCanvasElement).getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top, gx: e.clientX, gy: e.clientY };
  }

  function onMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const { x, y } = canvasPos(e);
    const n = hitNode(x, y);
    setHover(n ? { node: n, x, y } : null);
  }
  function onClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const { x, y } = canvasPos(e);
    setMenu(null);
    const n = hitNode(x, y);
    setSelectedId(n ? n.id : null);
  }
  function onContextMenu(e: React.MouseEvent<HTMLCanvasElement>) {
    e.preventDefault();
    const { x, y, gx, gy } = canvasPos(e);
    const n = hitNode(x, y);
    setMenu({ x: gx, y: gy, target: n });
  }
  // Touch: 500ms long-press opens the same context menu at the touch point.
  const longPress = useLongPress({
    onLongPress: ({ clientX, clientY }) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const r = canvas.getBoundingClientRect();
      const n = hitNode(clientX - r.left, clientY - r.top);
      setSelectedId(n ? n.id : null);
      setMenu({ x: clientX, y: clientY, target: n });
    },
  });
  function onWheel(e: React.WheelEvent<HTMLCanvasElement>) {
    if (!layout) return;
    const { x, y } = canvasPos(e);
    // Find the group whose region (band) covers this y.
    let target: Group | null = null;
    for (const g of layout.groups.values()) {
      if (!g.scrollable) continue;
      if (y >= g.topY - 12 && y <= g.bottomY + 30
          && x >= g.centerX - g.visibleWidth / 2 - 12
          && x <= g.centerX + g.visibleWidth / 2 + 12) {
        target = g; break;
      }
    }
    if (!target) return;
    e.preventDefault();
    const delta = e.deltaX || e.deltaY;
    const max = target.width - target.visibleWidth;
    setGroupScroll((prev) => {
      const cur = prev[target!.listenerId] ?? 0;
      const next = Math.max(0, Math.min(max, cur + delta));
      if (next === cur) return prev;
      return { ...prev, [target!.listenerId]: next };
    });
  }

  // Dismiss menu on escape / click-elsewhere
  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenu(null); };
    const onDown = (e: MouseEvent) => {
      const el = e.target as HTMLElement;
      if (!el.closest("[data-ctxmenu]")) setMenu(null);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [menu]);

  function selected(): GraphNode | null {
    if (!snapshot || !selectedId) return null;
    return snapshot.nodes.find((n) => n.id === selectedId) ?? null;
  }
  const sel = selected();

  function jumpToTab(n: GraphNode) {
    if (n.kind === "session" || n.kind === "beacon") {
      const implantId = String((n.meta as any).ID);
      navigate(`/console?open=${encodeURIComponent(implantId)}`);
    } else if (n.kind === "listener" || n.kind === "unknown-listener") {
      navigate("/listeners");
    } else if (n.kind === "host") {
      navigate("/sessions");
    }
  }

  function zoomToFit() { refetch(); }

  const implantCount = snapshot?.nodes.filter(
    (n) => n.kind === "beacon" || n.kind === "session",
  ).length ?? 0;
  const listenerCount = snapshot?.nodes.filter((n) => n.kind === "listener").length ?? 0;
  const staleCount = snapshot?.nodes.filter(
    (n) => n.kind === "beacon" && isLateBeacon(n.meta as any),
  ).length ?? 0;
  const lastUpdate = snapshot ? new Date(snapshot.generated_at).toLocaleTimeString() : "—";
  const shortUpdate = snapshot
    ? new Date(snapshot.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "—";

  return (
    <div className="h-[calc(100vh-2rem)] flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">C2 topology</h2>
        {err && <span className="text-xs text-danger">{err}</span>}
      </div>

      <Card className="flex-1 flex relative !p-0 overflow-hidden">
        <div ref={wrapRef} className="flex-1 relative" style={{ background: COLORS.bg }}>
          <canvas
            ref={canvasRef}
            onMouseMove={onMouseMove}
            onMouseLeave={() => setHover(null)}
            onClick={onClick}
            onContextMenu={onContextMenu}
            onWheel={onWheel}
            {...longPress}
            style={{ display: "block", cursor: hover ? "pointer" : "default", touchAction: "pan-y" }}
          />

          {snapshot && implantCount === 0 && (
            <div className="absolute inset-x-0 bottom-12 flex justify-center pointer-events-none">
              <div className="text-xs text-muted bg-panel2/80 px-3 py-1.5 rounded border border-border">
                No implants connected. Start a listener and deploy an implant to see the topology.
              </div>
            </div>
          )}
          {!snapshot && !err && (
            <div className="absolute inset-0 flex items-center justify-center text-xs text-muted">
              loading…
            </div>
          )}

          {/* Controls */}
          <div className="absolute top-2 right-2 flex flex-col gap-1 text-xs">
            <div className="flex gap-1 justify-end">
              <Button size="sm" variant="outline" onClick={zoomToFit} title="Zoom to fit">
                <Maximize2 size={12} />
              </Button>
              <Button size="sm" variant="outline"
                      onClick={() => setFilters((f) => ({ ...f, legend: !f.legend }))}
                      title="Toggle legend">
                <Info size={12} />
              </Button>
            </div>
            <div className="bg-panel/90 border border-border rounded p-2 space-y-1">
              <div className="text-[10px] text-muted uppercase tracking-wide">Filters</div>
              {TOGGLE_KEYS.map((k) => (
                <label key={k} className="flex items-center gap-2 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={filters[k]}
                    onChange={(e) => setFilters({ ...filters, [k]: e.target.checked })}
                    className="h-3 w-3 accent-accent2"
                  />
                  <span className={cn("font-mono", !filters[k] && "text-muted line-through")}>
                    {k === "listener" ? "listeners"
                      : k === "host" ? "hosts"
                      : k === "grid" ? "grid"
                      : k + "s"}
                  </span>
                </label>
              ))}
            </div>
            {filters.legend && <Legend />}
          </div>

          {hover && !menu && <HoverTip n={hover.node} x={hover.x} y={hover.y} />}
        </div>

        {sel && !phone && (
          <NodeDrawer node={sel} onClose={() => setSelectedId(null)} onJump={() => jumpToTab(sel)} />
        )}
      </Card>

      {/* phone: node details as a bottom sheet so the canvas stays visible */}
      {phone && (
        <Sheet
          open={!!sel}
          onClose={() => setSelectedId(null)}
          side="bottom"
          title={sel ? `${sel.label} · ${sel.kind}` : ""}
        >
          {sel && (
            <NodeDrawer node={sel} onClose={() => setSelectedId(null)} onJump={() => jumpToTab(sel)} bare />
          )}
        </Sheet>
      )}

      {/* Status strip — single line; shorter on phone (HH:MM, no prefix). */}
      <div className="text-[10px] font-mono text-muted px-1 truncate whitespace-nowrap">
        {implantCount} implants · {listenerCount} listeners
        <span className="hidden sm:inline"> · last update {lastUpdate}</span>
        <span className="sm:hidden"> · {shortUpdate}</span>
        {staleCount > 0 && (
          <span className="text-danger"> · {staleCount} stale<span className="hidden sm:inline"> beacons</span></span>
        )}
      </div>

      {menu && (
        <ContextMenu
          menu={menu}
          onAction={(act) => { setMenu(null); handleContextAction(act, menu, navigate, refetch, setSelectedId, setUploadFor); }}
          onClose={() => setMenu(null)}
        />
      )}
      {uploadFor && (
        <UploadModal
          implantId={uploadFor.id}
          info={uploadFor.info}
          onDone={(res: UploadResult) => {
            // Stash for /console to consume on mount; then navigate so the
            // operator sees the result line where command output normally
            // lives. (sync result inlines; queued result drives task_update.)
            setPendingOp(uploadFor.id, res.kind === "session"
              ? { kind: "upload-sync", result: res }
              : { kind: "upload-queued", result: res });
            const dest = uploadFor.id;
            setUploadFor(null);
            navigate(`/console?open=${encodeURIComponent(dest)}`);
          }}
          onClose={() => setUploadFor(null)}
        />
      )}
    </div>
  );
}

// ── Context menu ───────────────────────────────────────────────────

type CtxAction =
  | "open-console" | "promote-to-session" | "upload-file" | "screenshot" | "ps"
  | "kill-implant" | "copy-id"
  | "stop-listener" | "copy-port"
  | "refetch" | "reset-view";

interface CtxItem {
  label: string;
  act: CtxAction;
  danger?: boolean;
  disabled?: boolean;
  title?: string;
}

function ContextMenu({
  menu, onAction, onClose,
}: { menu: CtxMenu; onAction: (a: CtxAction) => void; onClose: () => void }) {
  const target = menu.target;
  let items: CtxItem[];
  if (target && (target.kind === "beacon" || target.kind === "session")) {
    const isSession = target.kind === "session";
    items = [
      { label: "Open console", act: "open-console" },
      {
        label: "Promote to session",
        act: "promote-to-session",
        disabled: isSession,
        title: isSession ? "already interactive" : undefined,
      },
      { label: "Upload file…", act: "upload-file" },
      { label: "Screenshot", act: "screenshot" },
      { label: "Process list", act: "ps" },
      { label: "Kill implant", act: "kill-implant", danger: true },
      { label: "Copy ID", act: "copy-id" },
    ];
  } else if (target && (target.kind === "listener" || target.kind === "unknown-listener")) {
    items = [
      { label: "Stop listener", act: "stop-listener", danger: true },
      { label: "Copy port", act: "copy-port" },
    ];
  } else {
    items = [
      { label: "Refetch graph", act: "refetch" },
      { label: "Reset view", act: "reset-view" },
    ];
  }
  // Clamp menu to viewport
  const x = Math.min(menu.x, window.innerWidth - 180);
  const y = Math.min(menu.y, window.innerHeight - items.length * 28 - 16);
  return (
    <div
      data-ctxmenu
      className="fixed z-50 bg-panel border border-border rounded shadow-xl py-1 min-w-[160px] text-xs"
      style={{ left: x, top: y }}
    >
      {items.map((it, i) => (
        <button
          key={i}
          onClick={() => { if (!it.disabled) onAction(it.act); }}
          disabled={it.disabled}
          title={it.title}
          className={cn(
            "w-full text-left px-3 py-1.5 max-lg:min-h-[44px]",
            it.disabled
              ? "text-muted cursor-not-allowed"
              : it.danger
                ? "text-danger hover:bg-panel2"
                : "text-text hover:bg-panel2",
          )}
        >
          {it.label}
        </button>
      ))}
      <div className="border-t border-border my-1" />
      <button onClick={onClose} className="w-full text-left px-3 py-1 text-muted hover:bg-panel2">
        cancel
      </button>
    </div>
  );
}

async function handleContextAction(
  act: CtxAction, menu: CtxMenu,
  navigate: (to: string) => void, refetch: () => void,
  setSelectedId: (id: string | null) => void,
  setUploadFor: (v: { id: string; info: ImplantInfo } | null) => void,
): Promise<void> {
  const t = menu.target;
  switch (act) {
    case "open-console":
      if (t && (t.kind === "beacon" || t.kind === "session")) {
        navigate(`/console?open=${encodeURIComponent(String((t.meta as any).ID))}`);
      }
      break;
    case "upload-file":
      if (t && (t.kind === "beacon" || t.kind === "session")) {
        const id = String((t.meta as any).ID);
        // The modal only consumes info.info.os + info.info.username; capabilities
        // and `kind` are placeholders. Fetching live info would round-trip the
        // server for fields we already have on the node.
        setUploadFor({
          id,
          info: {
            kind: t.kind,
            info: t.meta,
            capabilities: {
              exec: true, ls: true, cat: true, ps: true, screenshot: true,
              download: true, kill: true, interactive: t.kind === "session",
              promote_to_session: t.kind === "beacon",
              tunneling: t.kind === "session",
            },
          },
        });
      }
      break;
    case "promote-to-session":
      if (t && t.kind === "beacon") {
        const id = String((t.meta as any).ID);
        try {
          await api.post(`/api/implants/${encodeURIComponent(id)}/interactive`, {});
          // Land the operator in the beacon's console so they can watch
          // the task collapse + the green "session opened" info line.
          navigate(`/console?open=${encodeURIComponent(id)}`);
        } catch (e: any) {
          toast.error(`Promote failed: ${e?.message ?? String(e)}`);
        }
      }
      break;
    case "screenshot":
    case "ps":
      // Open the side drawer with the source node selected; the drawer
      // hosts these actions via deep buttons (kept minimal here — the
      // primary surface for these is /console).
      if (t) setSelectedId(t.id);
      break;
    case "kill-implant":
      if (t && (t.kind === "beacon" || t.kind === "session")) {
        if (!confirm(`Kill ${t.label}? This tells the implant to exit.`)) return;
        await api.post(`/api/implants/${(t.meta as any).ID}/kill`, {});
        refetch();
      }
      break;
    case "copy-id":
      if (t) navigator.clipboard.writeText(String((t.meta as any).ID ?? t.id));
      break;
    case "stop-listener":
      if (t) {
        const id = (t.meta as any).ID;
        if (typeof id === "number") {
          await api.del(`/api/listeners/${id}`);
          refetch();
        }
      }
      break;
    case "copy-port":
      if (t) navigator.clipboard.writeText(String((t.meta as any).port ?? ""));
      break;
    case "refetch":
      refetch();
      break;
    case "reset-view":
      history.replaceState(null, "", location.pathname);
      location.reload();
      break;
  }
}

// ── Legend overlay ─────────────────────────────────────────────────

function Legend() {
  return (
    <div className="bg-panel/95 border border-border rounded p-2 text-[10px] space-y-1 max-w-[200px]">
      <div className="font-semibold text-text mb-1">Legend</div>
      <Row color={COLORS.accent} label="teamserver / session" />
      <Row color="#38bdf8" label="listener (M/H/D/W)" />
      <Row color={COLORS.amber} label="beacon" />
      <Row color={COLORS.danger} label="unknown listener · stale beacon · elevated (⚡)" />
      <div className="border-t border-border my-1" />
      <div className="font-mono">— solid: session edge</div>
      <div className="font-mono">- - dashed amber: beacon edge</div>
      <div className="font-mono">- - dashed red: late beacon</div>
      <div className="font-mono">— dim: structural</div>
    </div>
  );
}
function Row({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="inline-block w-3 h-3 rounded" style={{ background: color }} />
      <span>{label}</span>
    </div>
  );
}

// ── Tooltip + drawer (unchanged from previous pass) ────────────────

function HoverTip({ n, x, y }: { n: GraphNode; x: number; y: number }) {
  const meta = n.meta as Record<string, unknown>;
  const fields: [string, string][] = [];
  for (const k of ["username", "hostname", "transport", "remote_address",
                   "last_checkin", "next_checkin", "pid", "port", "protocol"]) {
    const v = meta[k];
    if (v !== undefined && v !== "" && v !== 0) fields.push([k, String(v)]);
  }
  const tipStyle: React.CSSProperties = {
    position: "absolute",
    left: Math.max(4, x - 120),
    top: Math.max(4, y - 120),
    pointerEvents: "none",
  };
  return (
    <div style={tipStyle} className="max-w-xs bg-panel border border-border rounded px-2 py-1.5 text-[11px]">
      <div className="font-semibold mb-1">{n.label} <span className="text-muted">· {n.kind}</span></div>
      {fields.length === 0 ? <div className="text-muted">no extra fields</div> : (
        <table className="text-[10px]"><tbody>
          {fields.map(([k, v]) => (
            <tr key={k}><td className="text-muted pr-2">{k}</td><td className="font-mono">{v}</td></tr>
          ))}
        </tbody></table>
      )}
    </div>
  );
}

function NodeDrawer({
  node, onClose, onJump, bare = false,
}: { node: GraphNode; onClose: () => void; onJump: () => void; bare?: boolean }) {
  const showJump = node.kind === "session" || node.kind === "beacon"
    || node.kind === "listener" || node.kind === "unknown-listener" || node.kind === "host";
  const jumpLabel = node.kind === "session" || node.kind === "beacon" ? "Open console"
    : node.kind === "host" ? "Sessions tab" : "Listeners tab";
  const body = (
    <CardContent className="flex-1 overflow-y-auto space-y-2">
      {showJump && (
        <Button size="sm" variant="outline" onClick={onJump} className="w-full">
          {jumpLabel}
        </Button>
      )}
      <details open className="text-xs">
        <summary className="cursor-pointer text-muted">meta</summary>
        <pre className="bg-panel2 border border-border rounded p-2 mt-1 overflow-auto text-[10px]">
          {JSON.stringify(node.meta, null, 2)}
        </pre>
      </details>
    </CardContent>
  );
  // bare: the phone bottom-sheet provides its own title bar + close.
  if (bare) return <div className="flex flex-col">{body}</div>;
  return (
    <div className="w-80 shrink-0 border-l border-border bg-panel flex flex-col">
      <CardHeader className="flex items-start justify-between">
        <div>
          <CardTitle className="text-sm">{node.label}</CardTitle>
          <div className="text-[10px] text-muted">{node.kind} · {node.id}</div>
        </div>
        <button onClick={onClose} className="text-muted hover:text-text" title="Close">
          <X size={14} />
        </button>
      </CardHeader>
      {body}
    </div>
  );
}
