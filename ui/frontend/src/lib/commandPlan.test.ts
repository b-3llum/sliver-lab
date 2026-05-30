// Pure-logic tests for the console command dispatcher helpers.
// Run with: node --test --experimental-strip-types (no extra deps; Node ≥22).
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildExecArgv, parseDownloadArgs } from "./commandPlan.ts";

// ── Bug 1: download routing/parse ──────────────────────────────────

test("download <path> parses the first token as the path", () => {
  assert.deepEqual(
    parseDownloadArgs(["download", "C:\\Users\\user\\Desktop\\flag.txt"]),
    { path: "C:\\Users\\user\\Desktop\\flag.txt" },
  );
});

test("download with no path yields an error (no API call)", () => {
  assert.deepEqual(parseDownloadArgs(["download"]), { error: "download: path required" });
});

// ── Bug 2: cat/pwd argv build branches on OS ───────────────────────

test("cat on windows uses cmd /c type", () => {
  assert.deepEqual(
    buildExecArgv("cat", ["cat", "C:\\Users\\user\\Desktop\\flag.txt"], "windows"),
    ["cmd", "/c", "type", "C:\\Users\\user\\Desktop\\flag.txt"],
  );
});

test("cat on linux uses the cat binary directly", () => {
  assert.deepEqual(
    buildExecArgv("cat", ["cat", "/etc/hostname"], "linux"),
    ["cat", "/etc/hostname"],
  );
});

test("pwd on windows uses cmd /c cd", () => {
  assert.deepEqual(buildExecArgv("pwd", ["pwd"], "windows"), ["cmd", "/c", "cd"]);
});

test("pwd on darwin uses the pwd binary directly", () => {
  assert.deepEqual(buildExecArgv("pwd", ["pwd"], "darwin"), ["pwd"]);
});

test("a non cat/pwd command passes its argv through verbatim", () => {
  assert.deepEqual(buildExecArgv("whoami", ["whoami"], "windows"), ["whoami"]);
});
