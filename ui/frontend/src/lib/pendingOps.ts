/**
 * Module-level handoff used when an upload (or future op) is initiated from
 * one route (e.g. /graph) and the result has to surface in another (/console
 * tab). Lives only in JS memory — cleared on consume — so no storage rule
 * violation and no risk of stale data after a refresh.
 */
import type { UploadQueuedResult, UploadSyncResult } from "@/components/console/UploadModal";

export type PendingOp =
  | { kind: "upload-sync"; result: UploadSyncResult }
  | { kind: "upload-queued"; result: UploadQueuedResult };

const ops = new Map<string, PendingOp>();

/** Push an op for `implantId`. Last-write-wins if called repeatedly. */
export function setPendingOp(implantId: string, op: PendingOp): void {
  ops.set(implantId, op);
}

/** Pull and clear in one step — caller is expected to render it. */
export function consumePendingOp(implantId: string): PendingOp | null {
  const op = ops.get(implantId) ?? null;
  if (op) ops.delete(implantId);
  return op;
}
