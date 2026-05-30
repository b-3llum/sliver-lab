import { ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/cn";

type Variant = "default" | "ghost" | "danger" | "outline";
type Size = "sm" | "md";

const variants: Record<Variant, string> = {
  default: "bg-accent text-black hover:bg-accent/90",
  ghost: "bg-transparent hover:bg-panel2 text-text",
  outline: "border border-border bg-transparent hover:bg-panel2 text-text",
  danger: "bg-danger text-white hover:bg-danger/90",
};
const sizes: Record<Size, string> = {
  sm: "h-7 px-2 text-xs",
  md: "h-9 px-3 text-sm",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        // Touch-target floor on phone/tablet; desktop keeps its dense sizing.
        "inline-flex items-center justify-center rounded font-medium transition-colors duration-[80ms] disabled:opacity-50 disabled:pointer-events-none max-lg:min-h-[44px]",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
