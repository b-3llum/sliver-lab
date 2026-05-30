import { TYPE, COLOR, RADIUS } from "@/lib/tokens";

// Unified status chip for a list item's connection/health state. One vocabulary,
// one look — replaces the bespoke conn pill (Layout), live/dead badge (Sessions),
// and stale row styling (Beacons).

export type StateKind =
  | "live"
  | "stale"
  | "dead"
  | "promoting"
  | "online"
  | "offline";

// Each kind maps to one semantic color token from lib/tokens.ts. The 15%-alpha
// background is derived from that same token, so no color literals live here.
const KIND_COLOR: Record<StateKind, string> = {
  live: COLOR.accent,
  online: COLOR.accent,
  stale: COLOR.amber,
  dead: COLOR.danger,
  offline: COLOR.danger,
  promoting: COLOR.amber,
};

function withAlpha(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function StateChip({ kind }: { kind: StateKind }) {
  const color = KIND_COLOR[kind];
  const pulsing = kind === "promoting";

  return (
    <>
      {pulsing && (
        <style>{`@keyframes statechip-pulse{0%,100%{opacity:1}50%{opacity:0.4}}`}</style>
      )}
      <span
        className="inline-block uppercase"
        style={{
          ...TYPE.monoXs,
          color,
          border: `1px solid ${color}`,
          borderRadius: RADIUS.sm,
          background: withAlpha(color, 0.15),
          padding: "1px 4px",
          transition: "color 80ms, background-color 80ms, border-color 80ms",
          animation: pulsing ? "statechip-pulse 1s ease-in-out infinite" : undefined,
        }}
      >
        {kind}
      </span>
    </>
  );
}
