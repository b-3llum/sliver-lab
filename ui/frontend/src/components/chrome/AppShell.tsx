import { ReactNode, useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { EventDrawer } from "@/components/EventDrawer";
import { Sheet } from "@/components/chrome/Sheet";
import { useBreakpoint } from "@/hooks/useBreakpoint";
import { useWsConnected } from "@/hooks/useWsConnected";
import { COLOR, Z } from "@/lib/tokens";
import { cn } from "@/lib/cn";

// 50%-darker ring for the WS dot, derived from its fill (no darken helper in tokens).
function darken(hex: string, factor = 0.5): string {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n >> 16) & 0xff) * factor);
  const g = Math.round(((n >> 8) & 0xff) * factor);
  const b = Math.round((n & 0xff) * factor);
  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Responsive chrome around the routed area.
 *   ≥1024 (desktop): fixed left sidebar + right Events column (unchanged).
 *   640–1024 (tablet): sidebar behind a hamburger drawer; Events as a
 *     right-edge tab opening a right sheet.
 *   <640 (phone): hamburger drawer; Events as a bottom handle opening a
 *     bottom sheet.
 */
export function AppShell({ sidebar, children }: { sidebar: ReactNode; children: ReactNode }) {
  const bp = useBreakpoint();
  const desktop = bp === "desktop";
  const phone = bp === "phone";
  const wsConnected = useWsConnected();
  const dotBg = wsConnected ? COLOR.accent : COLOR.danger;
  const [navOpen, setNavOpen] = useState(false);
  const [eventsOpen, setEventsOpen] = useState(false);

  // Close the nav drawer if we resize up to desktop.
  useEffect(() => { if (desktop) { setNavOpen(false); setEventsOpen(false); } }, [desktop]);

  return (
    <div className="h-full flex">
      {/* Sidebar — fixed column on desktop, hamburger drawer otherwise. */}
      {desktop ? (
        <aside className="w-52 shrink-0 border-r border-border bg-panel flex flex-col">
          {sidebar}
        </aside>
      ) : (
        <>
          <button
            onClick={() => setNavOpen(true)}
            aria-label={`Open menu — WS ${wsConnected ? "connected" : "disconnected"}`}
            className="fixed top-2 left-2 flex h-10 w-10 items-center justify-center rounded border border-border bg-panel text-text"
            style={{ zIndex: Z.drawer }}
          >
            <Menu size={18} />
            {/* WS liveness dot — glanceable while the sidebar (and its StateChip) is in the drawer. */}
            <span
              aria-hidden
              className="absolute top-0 right-0 h-2 w-2 translate-x-1 -translate-y-1 rounded-full"
              style={{ background: dotBg, border: `1px solid ${darken(dotBg)}` }}
            />
          </button>
          {navOpen && <NavDrawer onClose={() => setNavOpen(false)}>{sidebar}</NavDrawer>}
        </>
      )}

      {/* Main content. */}
      <main className={cn(
        "flex-1 min-w-0 overflow-y-auto p-4",
        !desktop && "max-lg:pt-14",
        phone && "max-sm:pb-12",
      )}>
        {children}
      </main>

      {/* Events — right column on desktop; tab/handle + sheet otherwise. */}
      {desktop ? (
        <EventDrawer />
      ) : (
        <>
          <EventsHandle phone={phone} onClick={() => setEventsOpen(true)} />
          <Sheet
            open={eventsOpen}
            onClose={() => setEventsOpen(false)}
            side={phone ? "bottom" : "right"}
            title="Events"
          >
            <EventDrawer bare />
          </Sheet>
        </>
      )}
    </div>
  );
}

function NavDrawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0" style={{ zIndex: Z.drawer }}>
      <div className="chrome-backdrop absolute inset-0 bg-black/60" onClick={onClose} />
      <div
        className="chrome-drawer absolute left-0 top-0 h-full w-[340px] max-w-[85vw] border-r border-border bg-panel flex flex-col"
        // Close when a nav link inside is tapped.
        onClick={(e) => { if ((e.target as HTMLElement).closest("a")) onClose(); }}
      >
        {children}
      </div>
    </div>
  );
}

function EventsHandle({ phone, onClick }: { phone: boolean; onClick: () => void }) {
  if (phone) {
    return (
      <button
        onClick={onClick}
        className="fixed bottom-0 left-1/2 -translate-x-1/2 rounded-t border border-b-0 border-border bg-panel px-4 py-1 text-[10px] text-muted"
        style={{ zIndex: Z.drawer }}
      >
        events ▲
      </button>
    );
  }
  return (
    <button
      onClick={onClick}
      className="fixed right-0 top-1/2 -translate-y-1/2 rounded-l border border-r-0 border-border bg-panel px-1 py-3 text-[10px] text-muted [writing-mode:vertical-rl]"
      style={{ zIndex: Z.drawer }}
    >
      events
    </button>
  );
}
