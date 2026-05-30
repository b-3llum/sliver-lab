// Tests for the auth token storage helpers.
// Run with: node --test --experimental-strip-types (Node ≥22, no extra deps).
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

// Node has no DOM — provide a minimal sessionStorage before importing auth.ts.
// auth.ts only touches sessionStorage inside its functions (lazily), so a plain
// static import is fine as long as the shim exists by the time they run.
(globalThis as { sessionStorage?: unknown }).sessionStorage = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => { store[k] = String(v); },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { store = {}; },
  };
})();

const { getToken, setToken, clearToken, authHeaders } = await import("./auth.ts");

beforeEach(() => clearToken());

test("getToken returns null when unset", () => {
  assert.equal(getToken(), null);
});

test("setToken then getToken round-trips", () => {
  setToken("abc123");
  assert.equal(getToken(), "abc123");
});

test("clearToken removes it", () => {
  setToken("abc123");
  clearToken();
  assert.equal(getToken(), null);
});

test("authHeaders is empty without a token", () => {
  assert.deepEqual(authHeaders(), {});
});

test("authHeaders carries Bearer when a token is set", () => {
  setToken("tok-xyz");
  assert.deepEqual(authHeaders(), { Authorization: "Bearer tok-xyz" });
});
