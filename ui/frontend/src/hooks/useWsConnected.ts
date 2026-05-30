import { useEffect, useState } from "react";
import { bus } from "@/ws";
import type { ConnState, EventEnvelope } from "@/types";

/**
 * WS connection liveness, read from the same source as the sidebar's
 * StateChip (Layout.tsx): the singleton `bus` and its bff:* lifecycle
 * events. Subscribing here mirrors Layout's reducer exactly, so this
 * boolean tracks `state.connected` in lockstep on the same event stream.
 */
export function useWsConnected(): boolean {
  const [connected, setConnected] = useState(false);

  useEffect(() => bus.subscribe((e: EventEnvelope) => {
    if (e.type === "bff:state") setConnected(Boolean((e.data as unknown as ConnState).connected));
    if (e.type === "bff:connected") setConnected(true);
    if (e.type === "bff:disconnected") setConnected(false);
  }), []);

  return connected;
}
