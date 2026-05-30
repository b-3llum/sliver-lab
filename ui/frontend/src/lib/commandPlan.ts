/**
 * Pure helpers behind the console command dispatcher (views/Console.tsx).
 *
 * Factored out so the OS-dependent argv build and the `download` arg parse are
 * unit-testable without React. Console.tsx imports these directly, so the code
 * under test IS the production code (not a parallel reimplementation).
 */

export type DownloadArgs = { path: string } | { error: string };

/** `download <path>` → the path, or an inline error if the path is missing. */
export function parseDownloadArgs(argv: string[]): DownloadArgs {
  const path = argv[1];
  if (!path) return { error: "download: path required" };
  return { path };
}

/**
 * Build the /exec argv for `pwd`, `cat`, and the verbatim fallthrough,
 * branching on the implant OS.
 *
 * On Windows, `type` (cat) and `cd` (pwd) are cmd.exe *builtins* — they don't
 * exist as executables on PATH, so a bare exec of them fails with
 * FAILED_PRECONDITION. They must be run via `cmd /c`. On POSIX, `cat`/`pwd`
 * are real binaries and run directly.
 */
export function buildExecArgv(head: string, argv: string[], os: string): string[] {
  const win = os === "windows";
  if (head === "pwd") return win ? ["cmd", "/c", "cd"] : ["pwd"];
  if (head === "cat") {
    const rest = argv.slice(1);
    return win ? ["cmd", "/c", "type", ...rest] : ["cat", ...rest];
  }
  return argv;
}
