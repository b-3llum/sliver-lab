import { ReactNode, useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Activity, FileBarChart2, FileCode2, FolderTree, Hammer, Layers,
  Network, ScrollText, Server, Settings2, Share2, ShieldAlert, Spline, Terminal,
} from "lucide-react";
import { AppShell } from "@/components/chrome/AppShell";
import { OperatorsIndicator } from "@/components/OperatorsIndicator";
import { StateChip } from "@/components/ui/StateChip";
import { bus } from "@/ws";
import type { ConnState } from "@/types";
import { cn } from "@/lib/cn";

const NAV = [
  { to: "/sessions", label: "Sessions", icon: Server },
  { to: "/console", label: "Console", icon: Terminal },
  { to: "/tunnels", label: "Tunnels", icon: Spline },
  { to: "/beacons", label: "Beacons", icon: Activity },
  { to: "/graph", label: "Graph", icon: Share2 },
  { to: "/listeners", label: "Listeners", icon: Network },
  { to: "/jobs", label: "Jobs", icon: Layers },
  { to: "/files", label: "Files", icon: FolderTree },
  { to: "/loot", label: "Loot", icon: ShieldAlert },
  { to: "/build", label: "Build", icon: Hammer },
  { to: "/bofs", label: "BOFs", icon: FileCode2 },
  { to: "/profiles", label: "Profiles", icon: Settings2 },
  { to: "/audit", label: "Audit", icon: ScrollText },
  { to: "/report", label: "Report", icon: FileBarChart2 },
];

export function Layout(): ReactNode {
  const [state, setState] = useState<ConnState>({
    connected: false, server_version: null, cfg_path: null, last_error: null,
  });

  useEffect(() => bus.subscribe((e) => {
    if (e.type === "bff:state") setState(e.data as unknown as ConnState);
    if (e.type === "bff:connected")
      setState((s) => ({ ...s, connected: true, server_version: String(e.data.version ?? "") }));
    if (e.type === "bff:disconnected")
      setState((s) => ({ ...s, connected: false, last_error: String(e.data.error ?? "") }));
  }), []);

  return (
    <AppShell sidebar={<SidebarContent state={state} />}>
      <Outlet />
    </AppShell>
  );
}

/** Sidebar body — shared by the desktop column and the mobile hamburger drawer
 *  (AppShell provides the surrounding panel). */
function SidebarContent({ state }: { state: ConnState }) {
  return (
    <>
      <div className="px-3 py-3 border-b border-border">
        <div className="text-sm font-bold tracking-wide">SLIVER</div>
        <div className="text-[10px] text-muted">operator console</div>
      </div>
      <nav className="flex-1 overflow-y-auto py-1">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => cn(
              "relative flex items-center gap-2 px-3 py-1.5 text-xs max-lg:min-h-[44px] max-lg:py-3",
              // 1px→4px accent bar fading in from the left on hover/active.
              "before:absolute before:left-0 before:top-0 before:bottom-0 before:w-1 before:bg-accent",
              "before:opacity-0 before:transition-opacity before:duration-100 hover:before:opacity-100",
              isActive ? "bg-panel2 text-accent before:opacity-100" : "text-text hover:bg-panel2",
            )}
          >
            <Icon size={14} />
            <span className="flex-1">{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-border p-2 text-[10px] space-y-1">
        <StateChip kind={state.connected ? "online" : "offline"} />
        {state.server_version && <div className="text-muted truncate">v{state.server_version}</div>}
        {state.last_error && <div className="text-danger truncate" title={state.last_error}>{state.last_error}</div>}
        <OperatorsIndicator />
      </div>
    </>
  );
}
