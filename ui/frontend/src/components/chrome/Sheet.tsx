import { ReactNode, useEffect, useId, useRef, useState } from "react";
import { X } from "lucide-react";
import { useBreakpoint } from "@/hooks/useBreakpoint";
import { cn } from "@/lib/cn";

export type SheetSide = "right" | "bottom" | "center";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  side?: SheetSide;
  title?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  /** Extra classes for the content body wrapper. */
  className?: string;
  /** When false: no close affordance (no X, no backdrop/Esc close). For the
   *  auth gate, which the operator can't dismiss without authenticating. */
  dismissable?: boolean;
}

/**
 * Modal/sheet built on the native <dialog> (showModal): top-layer rendering,
 * focus trap, focus restore, and Esc handling come for free. Backdrop click
 * closes. On phone every variant is a full-screen sheet for max touch area;
 * on desktop: center → modal, right → 480px side sheet, bottom → 60vh sheet
 * with drag-to-dismiss on the handle.
 */
export function Sheet({
  open, onClose, side = "center", title, footer, children, className,
  dismissable = true,
}: SheetProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const phone = useBreakpoint() === "phone";
  const titleId = useId();
  const [dragY, setDragY] = useState(0);

  // Drive the native dialog from the `open` prop.
  useEffect(() => {
    const dlg = ref.current;
    if (!dlg) return;
    if (open && !dlg.open) dlg.showModal();
    else if (!open && dlg.open) dlg.close();
  }, [open]);

  // Esc fires the dialog's `cancel` event — route it through onClose.
  useEffect(() => {
    const dlg = ref.current;
    if (!dlg) return;
    const onCancel = (e: Event) => { e.preventDefault(); if (dismissable) onClose(); };
    dlg.addEventListener("cancel", onCancel);
    return () => dlg.removeEventListener("cancel", onCancel);
  }, [onClose, dismissable]);

  useEffect(() => { if (!open) setDragY(0); }, [open]);

  // Bottom-sheet drag-to-dismiss (desktop). Pointer events cover mouse+touch.
  function onHandleDown(e: React.PointerEvent) {
    if (side !== "bottom" || phone) return;
    const startY = e.clientY;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    const move = (ev: PointerEvent) => setDragY(Math.max(0, ev.clientY - startY));
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (ev.clientY - startY > 80) onClose();
      else setDragY(0);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  const isBottom = side === "bottom";
  const dialogCls = phone
    ? "fixed inset-0 m-0 h-screen w-screen max-w-none max-h-none rounded-none border-0"
    : side === "right"
      ? "fixed top-0 right-0 m-0 h-screen w-[480px] max-w-[92vw] rounded-none border-l border-border sheet-right"
      : side === "bottom"
        ? "fixed bottom-0 inset-x-0 m-0 w-screen h-[60vh] rounded-t-lg border-t border-border sheet-bottom"
        : "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 m-0 w-[min(92vw,480px)] max-h-[85vh] rounded-md border border-border";

  const showBar = phone || !!title;

  return (
    <dialog
      ref={ref}
      aria-modal="true"
      aria-labelledby={title ? titleId : undefined}
      onClick={(e) => { if (dismissable && e.target === ref.current) onClose(); }}
      className={cn("chrome-sheet bg-panel p-0 text-text overflow-hidden", dialogCls)}
      style={dragY ? { transform: `translateY(${dragY}px)`, transition: "none" } : undefined}
    >
      <div className="flex h-full max-h-full flex-col">
        {isBottom && !phone && (
          <div
            onPointerDown={onHandleDown}
            className="flex justify-center py-2 cursor-grab active:cursor-grabbing touch-none"
          >
            <div className="h-1 w-10 rounded-full bg-border" />
          </div>
        )}
        {showBar && (
          <div className="flex items-center justify-between border-b border-border px-3 py-2 shrink-0">
            <div id={titleId} className="text-sm font-semibold">{title}</div>
            {dismissable && (
              <button
                onClick={onClose}
                aria-label="close"
                className="text-muted hover:text-text max-lg:min-h-[44px] max-lg:min-w-[44px] flex items-center justify-center"
              >
                <X size={16} />
              </button>
            )}
          </div>
        )}
        <div className={cn("flex-1 overflow-y-auto", className)}>{children}</div>
        {footer && <div className="border-t border-border p-3 shrink-0">{footer}</div>}
      </div>
    </dialog>
  );
}
