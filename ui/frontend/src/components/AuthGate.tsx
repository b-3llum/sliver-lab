import { FormEvent, ReactNode, useEffect, useState } from "react";
import {
  getToken, setToken, NEED_AUTH_EVENT, TOKEN_SET_EVENT,
} from "@/lib/auth";
import { Sheet } from "@/components/chrome/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

/**
 * Gates the whole app behind the BFF auth token. While no valid token is held,
 * an inline card prompt renders in place of the routed layout (so the sidebar +
 * chrome don't show). It's NOT a route change — auth state is orthogonal to
 * navigation. A `need-auth` window event (fired by api.ts on a 401, or ws.ts on
 * a 1008 close) drops us back to the prompt mid-session.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(getToken());
  const [value, setValue] = useState("");
  // Bumped on each (re)auth to force the routed subtree to remount + re-fetch.
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const onNeedAuth = () => setTokenState(null);
    window.addEventListener(NEED_AUTH_EVENT, onNeedAuth);
    return () => window.removeEventListener(NEED_AUTH_EVENT, onNeedAuth);
  }, []);

  function connect(e: FormEvent) {
    e.preventDefault();
    const t = value.trim();
    if (!t) return;
    setToken(t);
    setTokenState(t);
    setValue("");
    setNonce((n) => n + 1);
    window.dispatchEvent(new Event(TOKEN_SET_EVENT));
  }

  if (!token) {
    return (
      <Sheet open onClose={() => {}} side="center" dismissable={false} title="UI auth token required">
        <form onSubmit={connect} className="space-y-3 p-4">
          <Input
            autoFocus
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="paste token"
          />
          <Button type="submit" className="w-full">Connect</Button>
          <p className="text-[11px] italic text-muted">
            the token was logged to the BFF's stderr on startup; check the terminal
          </p>
        </form>
      </Sheet>
    );
  }

  return <div key={nonce} className="h-full">{children}</div>;
}
