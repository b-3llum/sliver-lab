// Mirrors backend/models.py. Keep in sync (or regenerate via openapi-typescript).

export interface SessionInfo {
  ID: string;
  name: string;
  hostname: string;
  username: string;
  uid: string;
  gid: string;
  os: string;
  arch: string;
  transport: string;
  remote_address: string;
  pid: number;
  filename: string;
  last_checkin: number;
  active_c2: string;
  is_dead: boolean;
}

export interface BeaconInfo {
  ID: string;
  name: string;
  hostname: string;
  username: string;
  os: string;
  arch: string;
  transport: string;
  remote_address: string;
  pid: number;
  next_checkin: number;
  interval: number;
  jitter: number;
  tasks_count: number;
  tasks_count_completed: number;
  stale: boolean;
}

export interface NgrokTunnel {
  id: string;
  listener_port: number;
  public_url: string;   // tcp://X.tcp.ngrok.io:NNNNN
  public_host: string;
  public_port: number;
  kind: "tcp";
  started_at: string;
}

export interface JobInfo {
  ID: number;
  name: string;
  description: string;
  protocol: string;
  port: number;
  domains: string[];
  public_exposure?: NgrokTunnel | null;
}

export interface ListenerCreate {
  kind: "http" | "https" | "mtls" | "dns";
  host: string;
  port: number;
  domain?: string;
  website?: string;
  persistent?: boolean;
}

export interface PersistentListener {
  job_id: number;
  kind: string;
  host: string;
  port: number;
  created_at: string | null;
}

export interface ListenerConflict {
  kind: string;
  host: string;
  port: number;
  message: string;
  hint: string;
}

export interface ExecResponse {
  stdout: string;
  stderr: string;
  status: number;
  pid: number;
}

export interface FileEntry {
  name: string;
  size: number;
  mode: string;
  mod_time: number;
  is_dir: boolean;
}

export interface FileListResponse {
  path: string;
  entries: FileEntry[];
}

export interface LootInfo {
  ID: string;
  name: string;
  type: string;
  file_type: string;
  credential_type: string;
}

export interface ConnState {
  connected: boolean;
  server_version: string | null;
  cfg_path: string | null;
  last_error: string | null;
}

export interface AuditEntry {
  timestamp: string;
  operator: string;
  action: string;
  target: string;
  details: Record<string, unknown>;
}

export interface AuditResponse {
  entries: AuditEntry[];
}

export interface OperatorInfo {
  name: string;
  online: boolean;
}

export interface EventEnvelope {
  type: string;
  data: Record<string, unknown>;
}

// ── Build ──────────────────────────────────────────────────────────

export type BuildKind = "string" | "int" | "bool" | "choice";

export interface BuildField {
  name: string;
  flag: string;
  kind: BuildKind;
  default: unknown;
  required: boolean;
  choices: string[] | null;
  metavar: string | null;
  help: string;
}

export interface BuildGroup {
  name: string;
  description: string | null;
  exclusive: boolean;
  fields: BuildField[];
}

export interface BuildSchema {
  avgen_path: string;
  avgen_present: boolean;
  groups: BuildGroup[];
}

// ── Sliver-native build ────────────────────────────────────────────

export interface BuildSliverOptions {
  goos: string[];
  goarch: string[];
  format: string[];
  defaults: {
    goos: string;
    goarch: string;
    format: string;
    beacon: boolean;
    beacon_interval_s: number;
    obfuscate: boolean;
    c2_url: string;
  };
}

export interface BuildSliverRequest {
  goos: string;
  goarch: string;
  format: string;
  c2_url: string;
  name?: string;
  beacon: boolean;
  beacon_interval_s?: number;
  obfuscate: boolean;
}

// ── BOF library ────────────────────────────────────────────────────

export interface BofEntry {
  name: string;
  category: string;
  description: string;
  args_help: string;
  path_env: string;
  path: string | null;
  available: boolean;
}

export interface BofRunCommand {
  name: string;
  session_id: string;
  sliver_command: string;
  note: string;
}

export interface BofLibrary {
  dir: string;
  env_set: boolean;
  exists: boolean;
  count: number;
}

// ── C2 topology graph ──────────────────────────────────────────────

export type GraphNodeKind =
  | "teamserver" | "listener" | "beacon" | "session" | "host" | "unknown-listener";

export type GraphEdgeKind = "structural" | "session" | "beacon";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  meta: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: GraphEdgeKind;
}

export interface GraphSnapshot {
  nodes: GraphNode[];
  edges: GraphEdge[];
  generated_at: string;
}

// ── Implant / console ──────────────────────────────────────────────

export interface ImplantCapabilities {
  exec: boolean; ls: boolean; cat: boolean; ps: boolean;
  screenshot: boolean; download: boolean; kill: boolean;
  interactive: boolean;          // true for sessions
  promote_to_session: boolean;   // true for beacons
  tunneling: boolean;            // true for sessions
}

// ── Tunnels ────────────────────────────────────────────────────────

export type TunnelKind = "portfwd" | "rportfwd" | "socks5";

export interface TunnelRecord {
  id: string;
  kind: TunnelKind;
  session_id: string;
  bind_addr: string;
  bind_port: number;
  remote_addr: string;
  remote_port: number;
  started_at: string;
  marker_seen: boolean;
}

export interface TunnelList {
  portfwds: TunnelRecord[];
  rportfwds: TunnelRecord[];
  socks5: TunnelRecord[];
}

export interface ImplantInfo {
  kind: "session" | "beacon";
  info: Record<string, unknown>;
  capabilities: ImplantCapabilities;
}

export interface SessionExecResponse {
  kind: "session";
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_ms: number;
}

export interface BeaconTaskResponse {
  kind: "beacon";
  task_id: string;
  queued_at: string;
}

/** Discriminated union for /api/implants/{id}/exec.  Renamed to avoid
 *  colliding with the legacy ExecResponse used by /api/sessions exec. */
export type ImplantExecResponse = SessionExecResponse | BeaconTaskResponse;

export type TaskState = "queued" | "running" | "complete" | "error";

export interface TaskStatus {
  task_id: string;
  state: TaskState;
  kind: string;
  implant_id: string;
  implant_kind: "session" | "beacon";
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  result_kind: string | null;
  result: any;
  error: string | null;
}

// ── Malleable C2 profile presets ───────────────────────────────────

export interface ProfilePreset {
  name: string;
  description: string;
  category: string;
  yaml: string;
}
