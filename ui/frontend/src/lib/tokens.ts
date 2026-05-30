// Design tokens — the single source of truth the chrome primitives and the
// per-view passes reference. These are plain exported constants (no CSS-in-JS):
// use them in inline styles / className template literals where a Tailwind
// utility doesn't already cover the case (z-index, breakpoint math, etc.).
//
// Colors mirror the existing 5-ish-color operator palette (tailwind.config.js);
// we don't introduce new hues. fgMuted/divider are alpha derivations of fg.

export const COLOR = {
  bg: "#0b0d10",
  panel: "#11151a",
  panel2: "#161b22",
  fg: "#d7dde3",
  fgMuted: "rgba(215, 221, 227, 0.5)", // ~50% alpha fg
  accent: "#22c55e", // green
  accent2: "#38bdf8", // sky (links/secondary, pre-existing)
  amber: "#f59e0b",
  danger: "#ef4444",
  divider: "rgba(215, 221, 227, 0.15)", // ~15% alpha fg
} as const;

// 1..8 → multiples of 4px (with the usual jumps at the top).
export const SPACE = {
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  7: 32,
  8: 48,
} as const;

export const RADIUS = {
  sm: 3,
  md: 6,
  lg: 10,
} as const;

// Monospace throughout. `displaySm` is the ONE proportional exception, for the
// Audit/Help body text where dense numeric/proper-noun mixing reads better.
const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
const SANS = 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
export const TYPE = {
  monoXs: { fontSize: 10, fontFamily: MONO },
  monoSm: { fontSize: 12, fontFamily: MONO },
  monoBase: { fontSize: 14, fontFamily: MONO },
  monoLg: { fontSize: 16, fontFamily: MONO },
  displaySm: { fontSize: 12, fontFamily: SANS },
} as const;

export const Z = {
  drawer: 40,
  popover: 45,
  modal: 50,
  toast: 60,
} as const;

// Explicit pixel breakpoints (NOT tailwind's md/lg naming) so intent is clear.
// In Tailwind classes these map to `sm:` (640) and `lg:` (1024); use `max-lg:`
// for the "below tablet" touch tweaks.
export const BREAKPOINT = {
  phone: 640,
  tablet: 1024,
} as const;
