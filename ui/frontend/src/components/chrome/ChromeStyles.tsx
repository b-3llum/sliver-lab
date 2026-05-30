/**
 * Single component-local <style> for the chrome primitives — the pieces
 * Tailwind utilities can't express: <dialog> ::backdrop, slide-in @keyframes,
 * and the reduced-motion override. styles.css stays untouched. Mounted once by
 * AppShell.
 */
const CSS = `
dialog.chrome-sheet { color: inherit; }
dialog.chrome-sheet::backdrop { background: rgba(0, 0, 0, 0.6); }

@keyframes chrome-fade-scale { from { opacity: 0; transform: scale(.98); } to { opacity: 1; transform: none; } }
@keyframes chrome-slide-right { from { transform: translateX(100%); } to { transform: none; } }
@keyframes chrome-slide-bottom { from { transform: translateY(100%); } to { transform: none; } }
@keyframes chrome-slide-left { from { transform: translateX(-100%); } to { transform: none; } }
@keyframes chrome-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes chrome-toast-in { from { opacity: 0; transform: translateY(-12px); } to { opacity: 1; transform: none; } }

dialog.chrome-sheet[open] { animation: chrome-fade-scale 180ms ease-out; }
dialog.chrome-sheet[open].sheet-right { animation: chrome-slide-right 180ms ease-out; }
dialog.chrome-sheet[open].sheet-bottom { animation: chrome-slide-bottom 180ms ease-out; }
.chrome-drawer { animation: chrome-slide-left 180ms ease-out; }
.chrome-backdrop { animation: chrome-fade 180ms ease-out; }
.chrome-toast { animation: chrome-toast-in 180ms ease-out; }

/* Focus rings (D3.7): a visible 2px accent ring on keyboard focus, for every
   interactive element — dark-bg-safe and consistent across browsers. */
a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible,
textarea:focus-visible, [tabindex]:focus-visible, dialog.chrome-sheet:focus-visible {
  outline: 2px solid #22c55e;
  outline-offset: 2px;
}

/* Respect reduced-motion globally (D3.6): kill animations + transitions. */
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
  dialog.chrome-sheet[open],
  dialog.chrome-sheet[open].sheet-right,
  dialog.chrome-sheet[open].sheet-bottom,
  .chrome-drawer, .chrome-backdrop, .chrome-toast {
    animation-duration: 0ms !important;
  }
}
`;

export function ChromeStyles() {
  return <style>{CSS}</style>;
}
