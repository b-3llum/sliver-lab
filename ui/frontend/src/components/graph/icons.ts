/**
 * Pixel-art sprite drawers for the C2 topology graph.
 *
 * Each kind has its own bounding box (returned by SIZES). Sprites use
 * integer pixel coords; callers must `ctx.imageSmoothingEnabled = false`
 * once at canvas setup. Half-pixel offsets keep 1-px strokes crisp.
 *
 * Aesthetic target: Cobalt-Strike-style flat operator UI — readable from
 * across the room, no detail bloat. No assets are imported; every glyph
 * is a few dozen Canvas2D calls.
 */

export type IconKind = "teamserver" | "listener" | "beacon" | "session" | "unknown-listener" | "host";

export interface IconSize { w: number; h: number }

/** Per-kind bounding box. Implants are square, infrastructure is wider. */
export const SIZES: Record<IconKind, IconSize> = {
  teamserver: { w: 64, h: 40 },
  listener:   { w: 56, h: 40 },
  "unknown-listener": { w: 56, h: 40 },
  beacon:     { w: 48, h: 48 },
  session:    { w: 48, h: 48 },
  host:       { w: 48, h: 48 },
};

export function sizeOf(kind: IconKind): IconSize { return SIZES[kind]; }

export const COLORS = {
  bg: "#0d0d0d",
  fg: "#d7dde3",
  fgDim: "rgba(215,221,227,0.30)",
  fgFaint: "rgba(215,221,227,0.15)",
  accent: "#22c55e",
  amber: "#f59e0b",
  danger: "#ef4444",
  panel: "#11151a",
};

export interface IconOpts {
  kindGlyph?: string;       // letter inside listener base
  elevated?: boolean;       // red lightning overlay
  selected?: boolean;       // 2-px outline frame
  realtime?: boolean;       // session corner dot
}

export function drawIcon(
  ctx: CanvasRenderingContext2D,
  kind: IconKind,
  x: number, y: number,
  opts: IconOpts = {},
): void {
  const cx = Math.round(x);
  const cy = Math.round(y);
  ctx.save();
  ctx.lineJoin = "miter";
  ctx.lineCap = "butt";
  ctx.lineWidth = 1;

  switch (kind) {
    case "teamserver": drawServerRack(ctx, cx, cy); break;
    case "listener": drawAntenna(ctx, cx, cy, opts.kindGlyph, false); break;
    case "unknown-listener": drawAntenna(ctx, cx, cy, opts.kindGlyph ?? "?", true); break;
    case "beacon": drawDesktop(ctx, cx, cy, COLORS.amber, false); break;
    case "session": drawDesktop(ctx, cx, cy, COLORS.accent, !!opts.realtime); break;
    case "host": drawHostPlatform(ctx, cx, cy); break;
  }

  if (opts.elevated) drawLightning(ctx, cx, cy, kind);
  if (opts.selected) drawSelectionFrame(ctx, cx, cy, kind);
  ctx.restore();
}

/** Bracket caption under a group of implants sharing a hostname. */
export function drawHostBracket(
  ctx: CanvasRenderingContext2D,
  leftX: number, rightX: number, y: number, hostname: string,
): void {
  ctx.save();
  ctx.strokeStyle = COLORS.fgDim;
  ctx.lineWidth = 1;
  const lx = Math.round(leftX) + 0.5;
  const rx = Math.round(rightX) + 0.5;
  const yy = Math.round(y) + 0.5;
  ctx.beginPath();
  ctx.moveTo(lx, yy);
  ctx.lineTo(lx, yy + 4);
  ctx.lineTo(rx, yy + 4);
  ctx.lineTo(rx, yy);
  ctx.stroke();
  ctx.fillStyle = COLORS.fg;
  ctx.font = "11px ui-monospace, Menlo, monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText(hostname, (leftX + rightX) / 2, y + 8);
  ctx.restore();
}

/** Right-angle polyline. Vertical → horizontal → vertical. */
export function drawPolyline(
  ctx: CanvasRenderingContext2D,
  x1: number, y1: number, x2: number, y2: number,
  opts: { color: string; width?: number; dash?: number[] } = { color: COLORS.fgDim },
): void {
  ctx.save();
  ctx.strokeStyle = opts.color;
  ctx.lineWidth = opts.width ?? 1;
  ctx.setLineDash(opts.dash ?? []);
  ctx.lineJoin = "miter";
  const midY = Math.round((y1 + y2) / 2);
  const off = (ctx.lineWidth % 2) / 2;
  ctx.beginPath();
  ctx.moveTo(Math.round(x1) + off, Math.round(y1) + off);
  ctx.lineTo(Math.round(x1) + off, midY + off);
  ctx.lineTo(Math.round(x2) + off, midY + off);
  ctx.lineTo(Math.round(x2) + off, Math.round(y2) + off);
  ctx.stroke();
  ctx.restore();
}

/** Faint vertical guide from listener through its group center. */
export function drawGuide(
  ctx: CanvasRenderingContext2D, x: number, y1: number, y2: number,
): void {
  ctx.save();
  ctx.strokeStyle = COLORS.fgFaint;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(Math.round(x) + 0.5, Math.round(y1));
  ctx.lineTo(Math.round(x) + 0.5, Math.round(y2));
  ctx.stroke();
  ctx.restore();
}

// ── Sprites ────────────────────────────────────────────────────────

function drawServerRack(ctx: CanvasRenderingContext2D, x: number, y: number): void {
  const w = 56, h = 32;
  const lx = x - w / 2, ty = y - h / 2;
  ctx.strokeStyle = COLORS.accent;
  ctx.fillStyle = COLORS.panel;
  ctx.beginPath();
  ctx.rect(lx + 0.5, ty + 0.5, w, h);
  ctx.fill(); ctx.stroke();
  // 3 shelves
  for (const ry of [-10, 0, 10]) {
    ctx.beginPath();
    ctx.moveTo(lx + 4 + 0.5, y + ry + 0.5);
    ctx.lineTo(lx + w - 4 + 0.5, y + ry + 0.5);
    ctx.stroke();
    // 3 LED dots per shelf
    ctx.fillStyle = COLORS.accent;
    for (let dx = 0; dx < 3; dx++) ctx.fillRect(lx + w - 16 + dx * 4, y + ry - 3, 2, 2);
  }
}

function drawAntenna(
  ctx: CanvasRenderingContext2D, x: number, y: number,
  glyph: string | undefined, unknown: boolean,
): void {
  const color = unknown ? COLORS.danger : COLORS.accent;
  const dash = unknown ? [3, 2] : [];
  ctx.strokeStyle = color;
  ctx.fillStyle = COLORS.panel;
  ctx.setLineDash(dash);
  // Mast
  ctx.beginPath();
  ctx.moveTo(x + 0.5, y - 18 + 0.5);
  ctx.lineTo(x + 0.5, y + 2 + 0.5);
  ctx.stroke();
  // Signal ticks
  for (let i = 0; i < 3; i++) {
    const wi = 4 + i * 3;
    const ty = y - 18 + i * 3;
    ctx.beginPath();
    ctx.moveTo(x - wi + 0.5, ty + 0.5);
    ctx.lineTo(x + wi + 0.5, ty + 0.5);
    ctx.stroke();
  }
  // Base box
  ctx.setLineDash(dash);
  ctx.beginPath();
  ctx.rect(x - 10 + 0.5, y + 2 + 0.5, 20, 14);
  ctx.fill(); ctx.stroke();
  ctx.setLineDash([]);
  // Glyph
  if (glyph) {
    ctx.fillStyle = color;
    ctx.font = "bold 12px ui-monospace, Menlo, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(glyph.slice(0, 1).toUpperCase(), x + 0.5, y + 10);
  }
}

function drawDesktop(
  ctx: CanvasRenderingContext2D, x: number, y: number, color: string, withDot: boolean,
): void {
  ctx.strokeStyle = color;
  ctx.fillStyle = COLORS.panel;
  // Monitor
  ctx.beginPath();
  ctx.rect(x - 18 + 0.5, y - 20 + 0.5, 36, 24);
  ctx.fill(); ctx.stroke();
  // Screen inset
  ctx.beginPath();
  ctx.rect(x - 15 + 0.5, y - 17 + 0.5, 30, 18);
  ctx.stroke();
  // Stand
  ctx.beginPath();
  ctx.moveTo(x - 5 + 0.5, y + 4 + 0.5);
  ctx.lineTo(x + 5 + 0.5, y + 4 + 0.5);
  ctx.lineTo(x + 8 + 0.5, y + 10 + 0.5);
  ctx.lineTo(x - 8 + 0.5, y + 10 + 0.5);
  ctx.closePath();
  ctx.stroke();
  // Base bar
  ctx.beginPath();
  ctx.moveTo(x - 14 + 0.5, y + 14 + 0.5);
  ctx.lineTo(x + 14 + 0.5, y + 14 + 0.5);
  ctx.stroke();
  // Real-time dot
  if (withDot) {
    ctx.fillStyle = color;
    ctx.fillRect(x + 11, y - 16, 4, 4);
  }
}

function drawHostPlatform(ctx: CanvasRenderingContext2D, x: number, y: number): void {
  // Flat "platform" — drawn when host nodes are surfaced as standalone
  // (rare; primary host treatment is the bracket caption).
  ctx.strokeStyle = COLORS.fgDim;
  ctx.fillStyle = COLORS.panel;
  ctx.beginPath();
  ctx.rect(x - 22 + 0.5, y - 6 + 0.5, 44, 12);
  ctx.fill(); ctx.stroke();
}

function drawLightning(ctx: CanvasRenderingContext2D, cx: number, cy: number, kind: IconKind): void {
  const s = SIZES[kind];
  const x = cx + s.w / 2 - 4;
  const y = cy - s.h / 2 + 1;
  ctx.fillStyle = COLORS.danger;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x - 3, y + 4);
  ctx.lineTo(x - 1, y + 4);
  ctx.lineTo(x - 3, y + 8);
  ctx.lineTo(x + 2, y + 3);
  ctx.lineTo(x, y + 3);
  ctx.lineTo(x + 3, y);
  ctx.closePath();
  ctx.fill();
}

function drawSelectionFrame(ctx: CanvasRenderingContext2D, cx: number, cy: number, kind: IconKind): void {
  const s = SIZES[kind];
  ctx.strokeStyle = COLORS.fg;
  ctx.lineWidth = 2;
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.rect(cx - s.w / 2 - 1, cy - s.h / 2 - 1, s.w + 2, s.h + 2);
  ctx.stroke();
}

// ── Background grid ────────────────────────────────────────────────

export function drawDotGrid(ctx: CanvasRenderingContext2D, w: number, h: number, spacing = 24): void {
  ctx.fillStyle = "rgba(215,221,227,0.08)";
  for (let yy = spacing; yy < h; yy += spacing) {
    for (let xx = spacing; xx < w; xx += spacing) {
      ctx.fillRect(xx, yy, 1, 1);
    }
  }
}
