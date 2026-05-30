import { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Table({ className, ...p }: HTMLAttributes<HTMLTableElement>) {
  return <table className={cn("w-full text-xs", className)} {...p} />;
}
export function THead({ className, ...p }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("text-muted bg-panel2", className)} {...p} />;
}
export function TBody({ className, ...p }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={className} {...p} />;
}
export function TR({ className, ...p }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("border-b border-border hover:bg-panel2/60", className)} {...p} />;
}
export function TH({ className, ...p }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("text-left font-medium px-2 py-1.5", className)} {...p} />;
}
export function TD({ className, ...p }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-2 py-1.5", className)} {...p} />;
}
