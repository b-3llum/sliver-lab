import { InputHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-8 w-full rounded border border-border bg-panel2 px-2 text-xs max-lg:min-h-[44px]",
        "focus:outline-none focus:border-accent2",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export function Select({ className, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-8 w-full rounded border border-border bg-panel2 px-2 text-xs max-lg:min-h-[44px]",
        "focus:outline-none focus:border-accent2",
        className,
      )}
      {...p}
    />
  );
}

export function Label({ className, ...p }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("text-xs text-muted", className)} {...p} />;
}
