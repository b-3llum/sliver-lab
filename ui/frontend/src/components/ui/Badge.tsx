import { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Tone = "default" | "ok" | "warn" | "danger" | "info";
const tones: Record<Tone, string> = {
  default: "bg-panel2 text-text",
  ok: "bg-accent/15 text-accent",
  warn: "bg-warn/15 text-warn",
  danger: "bg-danger/15 text-danger",
  info: "bg-accent2/15 text-accent2",
};

export function Badge({
  tone = "default",
  className,
  ...p
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        tones[tone],
        className,
      )}
      {...p}
    />
  );
}
