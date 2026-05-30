// WebSocket client with reconnect + topic subscription.
//
// Topics are matched against the leading prefix of event.type (e.g. "session"
// matches "session-connected"). The server pushes BFF lifecycle events as
// "bff:*" which always fire regardless of filter.

import type { EventEnvelope } from "./types";
import { getToken, signalNeedAuth, TOKEN_SET_EVENT } from "@/lib/auth";

type Handler = (e: EventEnvelope) => void;

class EventBus {
  private ws: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private reconnectDelay = 500;
  private closed = false;
  private hasEverConnected = false;

  constructor() {
    // After re-auth, reconnect with the fresh token.
    window.addEventListener(TOKEN_SET_EVENT, () => this.connect());
  }

  connect() {
    if (this.ws) return;
    const token = getToken();
    if (!token) return; // no token yet — the AuthGate is up; wait for token-set
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/events?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => {
      this.reconnectDelay = 500;
      // Only announce on a reconnect cycle. On the cold-start connect the
      // server's first pushed bff:state already carries connected:true, so
      // emitting here too would double-fire.
      if (this.hasEverConnected) this.emit({ type: "bff:connected", data: {} });
      this.hasEverConnected = true;
    };
    ws.onmessage = (m) => {
      try {
        const env = JSON.parse(m.data) as EventEnvelope;
        this.emit(env);
      } catch {
        // ignore malformed frames
      }
    };
    ws.onclose = (ev) => {
      this.ws = null;
      if (ev.code === 1008) {
        // Server rejected the token — surface the auth gate; don't reconnect
        // (it would just bounce again). token-set will re-trigger connect().
        signalNeedAuth();
        return;
      }
      // The socket dropped (e.g. BFF process killed). Subscribers reduce a
      // `connected` flag off bff:* events and would otherwise stay green, so
      // synthesize the disconnect before the reconnect timer kicks in. Gated
      // on hasEverConnected so a failed cold-start connect (UI already shows
      // disconnected by default) doesn't fire a redundant event.
      if (this.hasEverConnected) this.emit({ type: "bff:disconnected", data: {} });
      if (!this.closed) setTimeout(() => this.connect(), this.reconnectDelay);
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 10_000);
    };
    ws.onerror = () => ws.close();
  }

  /** Broadcast an envelope to every subscriber — the shared dispatch path
   *  for both server-pushed frames and locally synthesized bff:* events. */
  private emit(env: EventEnvelope) {
    for (const h of this.handlers) h(env);
  }

  subscribe(h: Handler): () => void {
    this.handlers.add(h);
    this.connect();
    return () => { this.handlers.delete(h); };
  }

  close() {
    this.closed = true;
    this.ws?.close();
  }
}

export const bus = new EventBus();
