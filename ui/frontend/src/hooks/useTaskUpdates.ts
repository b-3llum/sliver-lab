import { useEffect } from "react";
import { bus } from "@/ws";

/**
 * Subscribes to `task_update` envelopes on the events WS. Invokes `onUpdate`
 * with the task_id and new state whenever one matching the (optional) ids
 * filter arrives. If `ids` is undefined, listens to every task_update.
 */
export function useTaskUpdates(
  onUpdate: (taskId: string, state: string) => void,
  ids?: Set<string>,
): void {
  useEffect(() => {
    return bus.subscribe((e) => {
      if (e.type !== "task_update") return;
      const tid = (e as any).task_id ?? (e.data as any)?.task_id;
      const state = (e as any).state ?? (e.data as any)?.state;
      if (!tid || !state) return;
      if (ids && !ids.has(tid)) return;
      onUpdate(tid, state);
    });
  }, [onUpdate, ids]);
}
