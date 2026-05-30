import { useEffect } from "react";
import { bus } from "@/ws";

/**
 * Subscribes to the events WS and invokes `refetch` (debounced) whenever the
 * backend sends a `graph_dirty` envelope. Multiple events arriving in quick
 * succession collapse into one refetch.
 */
export function useGraphDirty(refetch: () => void, debounceMs = 250): void {
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsub = bus.subscribe((e) => {
      if (e.type !== "graph_dirty") return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => { refetch(); timer = null; }, debounceMs);
    });
    return () => {
      if (timer) clearTimeout(timer);
      unsub();
    };
  }, [refetch, debounceMs]);
}
