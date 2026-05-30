import { useEffect, useRef, useState } from "react";
import { subscribeInflight } from "@/lib/inflight";
import { Z } from "@/lib/tokens";

/**
 * Page-top loading bar — the single global network signal (no per-element
 * spinners). Fades in only after 250ms of sustained in-flight work (so fast
 * requests don't flash), fades out 150ms after the counter hits zero.
 */
export function LoadingBar() {
  const [visible, setVisible] = useState(false);
  const showTimer = useRef<number | undefined>(undefined);
  const hideTimer = useRef<number | undefined>(undefined);

  useEffect(() => subscribeInflight((n) => {
    if (n > 0) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = undefined;
      if (showTimer.current === undefined) {
        showTimer.current = window.setTimeout(() => {
          setVisible(true);
          showTimer.current = undefined;
        }, 250);
      }
    } else {
      window.clearTimeout(showTimer.current);
      showTimer.current = undefined;
      hideTimer.current = window.setTimeout(() => setVisible(false), 150);
    }
  }), []);

  return (
    <div
      aria-hidden
      className="chrome-loadbar fixed top-0 left-0 right-0 h-px bg-accent pointer-events-none transition-opacity duration-150"
      style={{ zIndex: Z.toast + 1, opacity: visible ? 1 : 0 }}
    />
  );
}
