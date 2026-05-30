import { KeyboardEvent, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

const STATIC_COMMANDS = [
  "whoami", "pwd", "ls", "cat", "ps", "screenshot",
  "download", "upload", "interactive", "portfwd", "rportfwd", "socks5",
  "kill", "help", "clear",
];

export const HELP_TEXT = [
  "Supported commands (per-tab, scrollback is in-memory only):",
  "  whoami           — print current user",
  "  pwd              — print working directory",
  "  ls [path]        — list directory",
  "  cat <path>       — print file (uses exec under the hood)",
  "  ps               — process list",
  "  screenshot       — capture target screen (PNG embedded inline)",
  "  download <path>  — pull a file; link appears when ready",
  "  upload           — open file-upload modal for the active implant",
  "  interactive      — beacon only: promote to an interactive session",
  "  portfwd          — list active portfwds (use the Tunnels tab to create)",
  "  rportfwd         — list active reverse portfwds (Tunnels tab to create)",
  "  socks5           — list active SOCKS5 proxies (Tunnels tab to create)",
  "  kill             — tell implant to exit (confirmation)",
  "  help             — this message",
  "  clear            — clear scrollback (Ctrl+L)",
  "Anything else is sent through /exec verbatim.",
  "",
  "Shortcuts:",
  "  Ctrl+1 .. Ctrl+9 — switch to tab N (Ctrl+0 = tab 10)",
  "  Ctrl+W           — close active tab (confirms if tasks are pending)",
  "  Ctrl+T           — open the implant picker",
  "  Ctrl+K           — clear scrollback (alias of `clear`; Ctrl+L also works)",
  "  Esc              — close the picker",
  "  Ctrl+W is Ctrl-only on every platform — no Cmd+W binding on macOS,",
  "    so the same muscle memory works everywhere.",
].join("\n");

export interface CommandInputProps {
  onSubmit: (line: string) => void;
  /** Disabled while a sync session command is in flight. */
  busy?: boolean;
  /** Persistent history for ↑/↓ recall, owned by the parent so each tab has its own. */
  history: string[];
  setHistory: (h: string[]) => void;
}

export function CommandInput({ onSubmit, busy, history, setHistory }: CommandInputProps) {
  const [value, setValue] = useState("");
  const histIdx = useRef<number>(history.length);
  const inputRef = useRef<HTMLInputElement>(null);
  const [helpOpen, setHelpOpen] = useState(false);

  // Sync React state from the *native* input event as well as React's onChange.
  // React's synthetic onChange is skipped when the value is set programmatically
  // (`el.value = "..."` + dispatched `input` event) because of its internal
  // value tracker; a native listener has no such dedup, so DOM-level value sets
  // (browser automation, paste helpers) reliably reach state. (Bug 4a.)
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const sync = () => setValue(el.value);
    el.addEventListener("input", sync);
    return () => el.removeEventListener("input", sync);
  }, []);

  function submit() {
    // Prefer the live DOM value so a programmatic set (`el.value = …` + a
    // dispatched input event) still submits the right text even if React's
    // controlled state hasn't flushed in the same tick. (Bug 4a.)
    const v = (inputRef.current?.value ?? value).trim();
    if (!v) return;
    onSubmit(v);
    setHistory([...history, v]);
    histIdx.current = history.length + 1;
    setValue("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (history.length === 0) return;
      histIdx.current = Math.max(0, histIdx.current - 1);
      setValue(history[histIdx.current] ?? "");
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (history.length === 0) return;
      histIdx.current = Math.min(history.length, histIdx.current + 1);
      setValue(history[histIdx.current] ?? "");
    } else if (e.key === "Tab") {
      e.preventDefault();
      const tok = value.trim();
      if (!tok) return;
      const matches = STATIC_COMMANDS.filter((c) => c.startsWith(tok));
      if (matches.length === 1) setValue(matches[0] + " ");
    } else if (e.key === "l" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      onSubmit("clear");
    }
  }

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); submit(); }}
      className="border-t border-border p-2 flex gap-2 items-center bg-panel"
    >
      <span className="text-accent font-mono text-xs">{">"}</span>
      <input
        ref={inputRef}
        autoFocus
        disabled={busy}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={busy ? "running…" : "command"}
        className={cn(
          "flex-1 bg-transparent outline-none border-0 text-xs font-mono",
          busy && "opacity-50",
        )}
      />
      <Button type="submit" size="sm" disabled={busy}>send</Button>
      <div className="relative">
        <Button type="button" size="sm" variant="outline" aria-label="help"
                onClick={() => setHelpOpen((o) => !o)}>
          <span className="hidden sm:inline">help ▾</span>
          <span className="sm:hidden">?</span>
        </Button>
        {helpOpen && (
          <div
            onMouseLeave={() => setHelpOpen(false)}
            className="absolute bottom-full right-0 mb-1 w-[440px] bg-panel border border-border rounded p-2 text-[10px] font-mono whitespace-pre"
          >
            {HELP_TEXT}
          </div>
        )}
      </div>
    </form>
  );
}

/** Cheap shell-style argv splitter — handles "double quoted" and 'single quoted' atoms. */
export function parseArgv(input: string): string[] {
  const out: string[] = [];
  let cur = "";
  let q: '"' | "'" | null = null;
  for (let i = 0; i < input.length; i++) {
    const c = input[i];
    if (q) {
      if (c === q) q = null; else cur += c;
    } else if (c === '"' || c === "'") {
      q = c as '"' | "'";
    } else if (/\s/.test(c)) {
      if (cur) { out.push(cur); cur = ""; }
    } else cur += c;
  }
  if (cur) out.push(cur);
  return out;
}
