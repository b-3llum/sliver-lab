// Single shared-token auth state for the BFF.
//
// sessionStorage is the right home for this — and the ONLY place this app uses
// web storage. The project's no-storage rule is about not persisting user
// content; an auth token is a short-lived secret tied to the tab's lifecycle.
// sessionStorage clears on tab close (matching that lifecycle); localStorage
// would wrongly persist the secret across tab closes. So: sessionStorage only,
// for the token only.

const KEY = "ui_token";

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(v: string): void {
  try {
    sessionStorage.setItem(KEY, v);
  } catch {
    /* storage unavailable (private mode, SSR) — auth simply won't persist */
  }
}

export function clearToken(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/** Authorization header for fetch, or {} when no token is set. */
export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** Fired (on `window`) when the BFF rejects the token — the AuthGate listens. */
export const NEED_AUTH_EVENT = "need-auth";
/** Fired (on `window`) once a fresh token is accepted, to re-mount the app. */
export const TOKEN_SET_EVENT = "token-set";

export function signalNeedAuth(): void {
  clearToken();
  window.dispatchEvent(new Event(NEED_AUTH_EVENT));
}
