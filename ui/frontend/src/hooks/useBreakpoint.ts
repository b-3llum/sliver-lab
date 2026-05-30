import { useEffect, useState } from "react";
import { BREAKPOINT } from "@/lib/tokens";

export type Breakpoint = "phone" | "tablet" | "desktop";

function current(): Breakpoint {
  if (typeof window === "undefined") return "desktop";
  const w = window.innerWidth;
  if (w < BREAKPOINT.phone) return "phone";
  if (w < BREAKPOINT.tablet) return "tablet";
  return "desktop";
}

/** Reactive viewport bucket: phone (<640), tablet (640–1024), desktop (≥1024). */
export function useBreakpoint(): Breakpoint {
  const [bp, setBp] = useState<Breakpoint>(current);
  useEffect(() => {
    const onResize = () => setBp(current());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return bp;
}
