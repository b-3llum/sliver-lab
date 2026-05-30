// Global in-flight request counter. api.ts brackets every fetch with
// start()/end(); <LoadingBar> subscribes and shows the page-top bar.

type Listener = (n: number) => void;

let count = 0;
const listeners = new Set<Listener>();

function emit() {
  for (const l of listeners) l(count);
}

export function inflightStart(): void {
  count += 1;
  emit();
}

export function inflightEnd(): void {
  count = Math.max(0, count - 1);
  emit();
}

export function subscribeInflight(fn: Listener): () => void {
  listeners.add(fn);
  fn(count);
  return () => listeners.delete(fn);
}
