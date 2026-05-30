import { useRef } from "react";

interface Opts {
  /** Fired after a stationary press of `ms`. Gets the touch point. */
  onLongPress: (pt: { clientX: number; clientY: number }) => void;
  ms?: number;
  /** px of movement that cancels the press (treated as a scroll/drag). */
  moveTolerance?: number;
}

/**
 * Touch long-press → context menu, mirroring desktop right-click. Returns
 * touch handlers to spread onto the target. Movement past the tolerance
 * cancels (so scrolling doesn't trigger it); a small haptic fires on trigger.
 * Desktop mouse/right-click is untouched.
 */
export function useLongPress({ onLongPress, ms = 500, moveTolerance = 10 }: Opts) {
  const timer = useRef<number | undefined>(undefined);
  const start = useRef<{ x: number; y: number } | null>(null);

  function clear() {
    if (timer.current !== undefined) {
      window.clearTimeout(timer.current);
      timer.current = undefined;
    }
  }

  function onTouchStart(e: React.TouchEvent) {
    const t = e.touches[0];
    if (!t) return;
    start.current = { x: t.clientX, y: t.clientY };
    clear();
    timer.current = window.setTimeout(() => {
      navigator.vibrate?.(8);
      onLongPress({ clientX: start.current!.x, clientY: start.current!.y });
      timer.current = undefined;
    }, ms);
  }

  function onTouchMove(e: React.TouchEvent) {
    const t = e.touches[0];
    if (!t || !start.current) return;
    if (Math.abs(t.clientX - start.current.x) > moveTolerance
        || Math.abs(t.clientY - start.current.y) > moveTolerance) {
      clear();
    }
  }

  function onTouchEnd() { clear(); }

  return { onTouchStart, onTouchMove, onTouchEnd };
}
