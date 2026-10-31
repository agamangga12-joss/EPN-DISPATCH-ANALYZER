import {
  Activity,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Clock3,
  Eye,
  EyeOff,
  FileJson,
  KeyRound,
  Play,
  RefreshCw,
  RotateCcw,
  Server,
  ShieldCheck,
  TerminalSquare,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { apiGet, apiSend } from "../lib/api";


type Depot = { depot_id: string; depot_code: string | null; depot_name: string };
type Tab = "overview" | "access" | "endpoints" | "logs";
type DatasetState = { data_version: string; last_updated_at: string | null; data_until?: string | null };
type Overview = {
  connector_status: string;
  api_version: string;
  base_url: string;
  authentication_mode: string;
  datasets: Record<string, DatasetState>;
  last_api_request: string | null;
  last_successful_request: string | null;
  requests_today: number;
  success_rate: number;
  average_response_time_ms: number;
};
type Access = {
  base_url: string;
  authentication_type: string;
  client_id: string;
  client_name: string;
  client_code: string;
  active: boolean;
  has_credential: boolean;
  token_masked: string;
  token_hint: string | null;
  token_created_at: string | null;
  last_used_at: string | null;
  permissions: string[];
};
type LogRow = {
  id: string;
  request_id: string;
  client: string;
  timestamp: string;
  method: string;
  endpoint: string;
  response_status: number;
  response_time_ms: number;
  record_count: number | null;
  error_code: string | null;
};
type Logs = { page: number; page_size: number; total_records: number; total_pages: number; records: LogRow[] };
type ApiResult = { status: number; responseTimeMs: number; requestId: string | null; recordCount: number | null; payload: unknown };
type Field = {
  key: string;
  label: string;
  location: "path" | "query";
  required?: boolean;
  type?: "text" | "date" | "datetime" | "select";
  options?: Array<{ value: string; label: string }>;
  placeholder?: string;
};
type EndpointDefinition = {
  id: string;
  group: "SYSTEM" | "MASTER DATA" | "HISTORICAL DATA" | "ROUTE RESULTS" | "SHIFT CONFIGURATION";
  path: string;
  description: string;
  authenticated: boolean;
  fields: Field[];
  example: unknown;
};


const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Jakarta", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const localDateTime = `${today}T08:00`;
const endpointDefinitions: EndpointDefinition[] = [
  { id: "health", group: "SYSTEM", path: "/health", description: "Connector liveness and server time. Safe for unauthenticated connection tests.", authenticated: false, fields: [], example: { status: "ok", service: "amt-scheduler-connector", api_version: "v1", server_time: "2026-09-07T08:00:00+07:00" } },
  { id: "metadata", group: "SYSTEM", path: "/metadata", description: "Logical dataset versions and freshness for incremental synchronization decisions.", authenticated: true, fields: [], example: { system: "dispatcher-optimizer", integration: "amt-scheduler", api_version: "v1", datasets: { terminals: { data_version: "20260907-00001-AB12", last_updated_at: "..." } } } },
  { id: "terminals", group: "MASTER DATA", path: "/terminals", description: "Paginated canonical Terminal / Depot master data, including inactive records.", authenticated: true, fields: [
    { key: "active", label: "Active", location: "query", type: "select", options: [{ value: "", label: "All" }, { value: "true", label: "Active" }, { value: "false", label: "Inactive" }] },
    { key: "updated_since", label: "Updated Since", location: "query", type: "datetime" },
    { key: "page_size", label: "Page Size", location: "query", placeholder: "100" },
  ], example: { data_version: "...", page: 1, page_size: 100, total_records: 1, records: [{ terminal_id: "TBBM-001", terminal_name: "Integrated Terminal" }] } },
  { id: "terminal-detail", group: "MASTER DATA", path: "/terminals/{terminal_id}", description: "One terminal resolved by stable terminal ID.", authenticated: true, fields: [{ key: "terminal_id", label: "Terminal", location: "path", required: true, type: "select" }], example: { terminal_id: "TBBM-001", terminal_code: "PLUMPANG", active: true } },
  { id: "vehicles", group: "MASTER DATA", path: "/vehicles", description: "Paginated canonical Mobil Tangki master data with server-side filters.", authenticated: true, fields: [
    { key: "terminal_id", label: "Terminal", location: "query", type: "select" },
    { key: "active", label: "Active", location: "query", type: "select", options: [{ value: "", label: "All" }, { value: "true", label: "Active" }, { value: "false", label: "Inactive" }] },
    { key: "vehicle_status", label: "Vehicle Status", location: "query", placeholder: "ACTIVE" },
    { key: "updated_since", label: "Updated Since", location: "query", type: "datetime" },
    { key: "page_size", label: "Page Size", location: "query", placeholder: "100" },
  ], example: { page: 1, total_records: 1, records: [{ mt_id: "MT-001", terminal_id: "TBBM-001", operational_status: "UNKNOWN" }] } },
  { id: "vehicle-detail", group: "MASTER DATA", path: "/vehicles/{mt_id}", description: "One Mobil Tangki resolved by stable MT ID.", authenticated: true, fields: [{ key: "mt_id", label: "MT ID", location: "path", required: true, placeholder: "MT-001" }], example: { mt_id: "MT-001", active: true, compartments: [] } },
  { id: "history", group: "HISTORICAL DATA", path: "/historical-operations", description: "Historical operation records at TRIP grain. Multiple LO lines never duplicate a trip.", authenticated: true, fields: [
    { key: "terminal_id", label: "Terminal", location: "query", required: true, type: "select" },
    { key: "date_from", label: "Date From", location: "query", required: true, type: "date" },
    { key: "date_to", label: "Date To", location: "query", required: true, type: "date" },
    { key: "mt_id", label: "MT ID", location: "query", placeholder: "Optional" },
    { key: "updated_since", label: "Updated Since", location: "query", type: "datetime" },
    { key: "page_size", label: "Page Size", location: "query", placeholder: "500" },
  ], example: { page: 1, records: [{ trip_id: "TRIP:SHP-001", loading_orders: ["LO-001", "LO-002"], amt1_id: null, amt2_id: null }] } },
  { id: "routes", group: "ROUTE RESULTS", path: "/routes", description: "Every Phase 7 and Phase 8 route version for one operation date—not only the latest route.", authenticated: true, fields: [
    { key: "operation_date", label: "Operation Date", location: "query", required: true, type: "date" },
    { key: "terminal_id", label: "Terminal", location: "query", type: "select" },
    { key: "route_source", label: "Route Source", location: "query", type: "select", options: [{ value: "", label: "All" }, { value: "PHASE_7", label: "Phase 7" }, { value: "PHASE_8", label: "Phase 8" }] },
    { key: "status", label: "Status", location: "query", placeholder: "Optional" },
  ], example: { records: [{ route_id: "P7:stable-id", route_source: "PHASE_7", route_version: "V2", status: "COMPLETED" }] } },
  { id: "route-detail", group: "ROUTE RESULTS", path: "/routes/{route_id}", description: "Canonical route timeline grouped by physical MT and trip.", authenticated: true, fields: [{ key: "route_id", label: "Route", location: "path", required: true, type: "select" }], example: { route_id: "P8:stable-id", vehicles: [{ mt_id: "MT-001", trips: [] }] } },
  { id: "route-vehicles", group: "ROUTE RESULTS", path: "/routes/{route_id}/vehicles", description: "Paginated vehicle projection for the selected route.", authenticated: true, fields: [{ key: "route_id", label: "Route", location: "path", required: true, type: "select" }, { key: "page_size", label: "Page Size", location: "query", placeholder: "100" }], example: { route_id: "P7:stable-id", records: [{ mt_id: "MT-001", trip_count: 3 }] } },
  { id: "shift-availability", group: "ROUTE RESULTS", path: "/routes/{route_id}/shift-availability", description: "MT availability at authoritative shift starts, scoped to the selected route.", authenticated: true, fields: [{ key: "route_id", label: "Route", location: "path", required: true, type: "select" }, { key: "shift_id", label: "Shift ID", location: "query", placeholder: "Optional" }], example: { shifts: [{ shift_id: "SHIFT-2", available_mt_count: 31, available_capacity_kl: 744, vehicles: [] }] } },
  { id: "availability-after", group: "ROUTE RESULTS", path: "/routes/{route_id}/availability-after", description: "For every MT, report availability on or after a timezone-aware reference timestamp.", authenticated: true, fields: [{ key: "route_id", label: "Route", location: "path", required: true, type: "select" }, { key: "timestamp", label: "Reference Date/Time", location: "query", required: true, type: "datetime" }], example: { reference_at: "2026-09-07T08:00:00+07:00", records: [{ mt_id: "MT-002", availability_status: "ON_TRIP", next_available_at: "2026-09-07T08:45:00+07:00" }] } },
  { id: "shifts", group: "SHIFT CONFIGURATION", path: "/shifts", description: "User-defined authoritative shifts from saved Phase 2 configuration or the source Phase 5 model snapshot.", authenticated: true, fields: [{ key: "terminal_id", label: "Terminal", location: "query", required: true, type: "select" }, { key: "operation_date", label: "Operation Date", location: "query", required: true, type: "date" }], example: { records: [{ shift_id: "SHIFT-2", start_at: "2026-09-07T08:00:00+07:00", end_at: "2026-09-07T15:59:59+07:00" }] } },
];


function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "medium", timeZone: "Asia/Jakarta" }).format(parsed);
}

function statusTone(value: string | number) {
  const good = value === "READY" || value === "ok" || (typeof value === "number" && value >= 200 && value < 300);
  const warning = value === "CREDENTIAL_REQUIRED" || value === "UNKNOWN";
  return good ? "border-mint bg-mint/10 text-mint" : warning ? "border-amber bg-amber/10 text-amber" : "border-rust bg-rust/10 text-rust";
}

function Badge({ value }: { value: string | number }) {
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${statusTone(value)}`}>{String(value).replace(/_/g, " ")}</span>;
}

function countRecords(payload: unknown): number | null {
  if (!payload || typeof payload !== "object") return null;
  const value = payload as Record<string, unknown>;
  if (Array.isArray(value.records)) return value.records.length;
  if (Array.isArray(value.vehicles)) return value.vehicles.length;
  if (Array.isArray(value.shifts)) return value.shifts.length;
  return null;
}

export function AmtSchedulerConnectorPage({ depots }: { depots: Depot[] }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [access, setAccess] = useState<Access | null>(null);
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [expandedEndpoint, setExpandedEndpoint] = useState("routes");
  const [values, setValues] = useState<Record<string, Record<string, string>>>({
    routes: { operation_date: today },
    history: { date_from: today, date_to: today },
    "availability-after": { timestamp: localDateTime },
    shifts: { operation_date: today },
  });
  const [results, setResults] = useState<Record<string, ApiResult>>({});
  const [routeOptions, setRouteOptions] = useState<Array<{ route_id: string; route_source: string; route_version: string; route_name: string }>>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [logs, setLogs] = useState<Logs | null>(null);
  const [logDateFrom, setLogDateFrom] = useState("");
  const [logDateTo, setLogDateTo] = useState("");
  const [logStatus, setLogStatus] = useState("");
  const [logEndpoint, setLogEndpoint] = useState("");
  const [logClient, setLogClient] = useState("");
  const [selectedLog, setSelectedLog] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadSummary() {
    setError(null);
    try {
      const [overviewPayload, accessPayload] = await Promise.all([
        apiGet<Overview>("/api/v1/integration/amt-scheduler/console/overview"),
        apiGet<Access>("/api/v1/integration/amt-scheduler/console/access"),
      ]);
      setOverview(overviewPayload);
      setAccess(accessPayload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Connector console could not be loaded.");
    }
  }

  async function loadLogs() {
    try {
      const params = new URLSearchParams({ page: "1", page_size: "100" });
      if (logDateFrom) params.set("date_from", new Date(logDateFrom).toISOString());
      if (logDateTo) params.set("date_to", new Date(logDateTo).toISOString());
      if (logStatus) params.set("response_status", logStatus);
      if (logEndpoint.trim()) params.set("endpoint", logEndpoint.trim());
      if (logClient) params.set("client_id", logClient);
      setLogs(await apiGet<Logs>(`/api/v1/integration/amt-scheduler/console/logs?${params.toString()}`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "API logs could not be loaded.");
    }
  }

  useEffect(() => { void loadSummary(); }, []);
  useEffect(() => { if (tab === "logs") void loadLogs(); }, [tab]);

  const baseUrl = access?.base_url ?? overview?.base_url ?? "";
  const datasetLabels: Record<string, string> = {
    terminals: "Terminal Master",
    vehicles: "MT Master",
    historical_operations: "Historical Operations",
    route_results: "Route Results",
    shift_configuration: "Shift Configuration",
  };

  function fieldValue(endpointId: string, key: string): string {
    const existing = values[endpointId]?.[key];
    if (existing !== undefined) return existing;
    if (key === "operation_date" || key === "date_from" || key === "date_to") return today;
    if (key === "timestamp") return localDateTime;
    if (key === "terminal_id") return depots[0]?.depot_id ?? "";
    if (key === "route_id") return routeOptions[0]?.route_id ?? "";
    return "";
  }

  function updateField(endpointId: string, key: string, value: string) {
    setValues((current) => ({ ...current, [endpointId]: { ...(current[endpointId] ?? {}), [key]: value } }));
  }

  function buildRequest(definition: EndpointDefinition): { url: string; pathAndQuery: string } {
    let path = definition.path;
    const query = new URLSearchParams();
    for (const field of definition.fields) {
      let value = fieldValue(definition.id, field.key).trim();
      if (field.required && !value) throw new Error(`${field.label} is required.`);
      if (!value) continue;
      if (field.type === "datetime") {
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) throw new Error(`${field.label} must be a valid date/time.`);
        value = parsed.toISOString();
      }
      if (field.location === "path") path = path.replace(`{${field.key}}`, encodeURIComponent(value));
      else query.set(field.key, value);
    }
    const pathAndQuery = `${path}${query.size ? `?${query.toString()}` : ""}`;
    return { url: `${baseUrl}${pathAndQuery}`, pathAndQuery };
  }

  function curlFor(definition: EndpointDefinition): string {
    try {
      const { url } = buildRequest(definition);
      return [`curl -X GET '${url}'`, ...(definition.authenticated ? ["  -H 'Authorization: Bearer YOUR_API_TOKEN'"] : []), "  -H 'Accept: application/json'"].join(" \\\n");
    } catch {
      return `curl -X GET '${baseUrl}${definition.path}'`;
    }
  }

  async function copy(value: string, message: string) {
    await navigator.clipboard.writeText(value);
    setNotice(message);
  }

  async function regenerate() {
    if (!window.confirm("Regenerate the AMT Scheduler token? The previous token will stop working immediately.")) return;
    setRunning("regenerate");
    setError(null);
    try {
      const payload = await apiSend<{ bearer_token: string }>("/api/v1/integration/amt-scheduler/console/access/regenerate", "POST");
      setToken(payload.bearer_token);
      setShowToken(false);
      setNotice("New token generated. Copy it now; only its hash is persisted and the full value cannot be recovered after reload.");
      await loadSummary();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Credential could not be regenerated.");
    } finally {
      setRunning(null);
    }
  }

  async function sendRequest(definition: EndpointDefinition) {
    if (definition.authenticated && !token) {
      setError("A full bearer token is not retained by the server. Regenerate a token in API Access, then use Try API in this browser session.");
      return;
    }
    setRunning(definition.id);
    setError(null);
    try {
      await apiGet<{ allowed: boolean }>("/api/v1/integration/amt-scheduler/console/try-permission");
      const { url } = buildRequest(definition);
      const started = performance.now();
      const response = await fetch(url, { headers: { Accept: "application/json", ...(definition.authenticated ? { Authorization: `Bearer ${token}` } : {}) } });
      const payload = await response.json() as unknown;
      const result = { status: response.status, responseTimeMs: Math.round(performance.now() - started), requestId: response.headers.get("X-Request-ID"), recordCount: countRecords(payload), payload };
      setResults((current) => ({ ...current, [definition.id]: result }));
      if (definition.id === "routes" && payload && typeof payload === "object" && Array.isArray((payload as { records?: unknown[] }).records)) {
        const options = (payload as { records: Array<Record<string, unknown>> }).records.map((row) => ({ route_id: String(row.route_id), route_source: String(row.route_source), route_version: String(row.route_version), route_name: String(row.route_name) }));
        setRouteOptions(options);
      }
      if (!response.ok) {
        const message = payload && typeof payload === "object" ? (payload as { error?: { message?: string } }).error?.message : null;
        setError(message ?? `API returned HTTP ${response.status}.`);
      }
      await loadSummary();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Try API request failed.");
    } finally {
      setRunning(null);
    }
  }

  async function testConnector() {
    const definition = endpointDefinitions[0];
    setRunning("test-connector");
    try {
      await apiGet<{ allowed: boolean }>("/api/v1/integration/amt-scheduler/console/try-permission");
      const { url } = buildRequest(definition);
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`Connector returned HTTP ${response.status}.`);
      setNotice("Connector health check succeeded.");
      await loadSummary();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Connector test failed.");
    } finally {
      setRunning(null);
    }
  }

  const availabilitySummary = useMemo(() => {
    const result = results["availability-after"]?.payload;
    if (!result || typeof result !== "object" || !Array.isArray((result as { records?: unknown[] }).records)) return null;
    const records = (result as { records: Array<Record<string, unknown>> }).records;
    return {
      reference: String((result as Record<string, unknown>).reference_at ?? ""),
      available: records.filter((row) => row.availability_status === "AVAILABLE").length,
      onTrip: records.filter((row) => row.availability_status === "ON_TRIP").length,
      records,
    };
  }, [results]);

  return (
    <div className="space-y-5">
      {error && <div className="flex items-start justify-between rounded-xl border border-rust bg-rust/5 px-4 py-3 text-sm text-rust"><span>{error}</span><button onClick={() => setError(null)} aria-label="Dismiss error"><XCircle size={17} /></button></div>}
      {notice && <div className="flex items-start justify-between rounded-xl border border-mint bg-mint/5 px-4 py-3 text-sm text-mint"><span>{notice}</span><button onClick={() => setNotice(null)} aria-label="Dismiss notice"><CheckCircle2 size={17} /></button></div>}

      <section className="rounded-2xl border border-line bg-white p-2 shadow-sm">
        <div className="grid gap-2 sm:grid-cols-4">
          {([
            ["overview", "Overview", Activity],
            ["access", "API Access", KeyRound],
            ["endpoints", "Endpoints", BookOpen],
            ["logs", "API Logs", FileJson],
          ] as Array<[Tab, string, typeof Activity]>).map(([value, label, Icon]) => (
            <button key={value} type="button" className={`flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold ${tab === value ? "bg-mint text-white shadow-sm" : "text-slate-600 hover:bg-slate-50"}`} onClick={() => setTab(value)}>
              <Icon size={17} /> {label}
            </button>
          ))}
        </div>
      </section>

      {tab === "overview" && (
        <div className="space-y-5">
          <section className="grid gap-4 lg:grid-cols-[1.25fr_0.75fr]">
            <div className="rounded-2xl border border-line bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Connector Status</div>
                  <div className="mt-3 flex items-center gap-3"><Server className="text-mint" size={30} /><Badge value={overview?.connector_status ?? "LOADING"} /></div>
                  <div className="mt-4 break-all font-mono text-sm text-slate-600">{overview?.base_url ?? "Loading…"}</div>
                  <div className="mt-2 text-xs text-slate-500">API {overview?.api_version ?? "—"} · {overview?.authentication_mode ?? "—"}</div>
                </div>
                <button type="button" className="inline-flex items-center gap-2 rounded-xl bg-mint px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60" disabled={running === "test-connector"} onClick={() => void testConnector()}><Play size={16} /> Test Connector</button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                ["Requests Today", String(overview?.requests_today ?? 0)],
                ["Success Rate", `${overview?.success_rate ?? 0}%`],
                ["Average Response", `${overview?.average_response_time_ms ?? 0} ms`],
                ["Last Successful", formatDateTime(overview?.last_successful_request)],
              ].map(([label, value]) => <div key={label} className="rounded-2xl border border-line bg-white p-4"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-2 text-lg font-semibold text-petroink">{value}</div></div>)}
            </div>
          </section>
          <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center justify-between"><div><h2 className="text-base font-semibold">Available Datasets</h2><p className="mt-1 text-xs text-slate-500">Logical versions are derived from canonical source freshness and record counts.</p></div><button className="rounded-lg border border-line p-2 text-slate-500" onClick={() => void loadSummary()} title="Refresh"><RefreshCw size={16} /></button></div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
              {Object.entries(datasetLabels).map(([key, label]) => {
                const dataset = overview?.datasets[key];
                return <div key={key} className="rounded-xl border border-line bg-slate-50/60 p-4"><div className="text-sm font-semibold text-petroink">{label}</div><div className="mt-3 break-all font-mono text-[11px] text-slate-600">{dataset?.data_version ?? "—"}</div><div className="mt-2 text-xs text-slate-500">{formatDateTime(dataset?.last_updated_at)}</div></div>;
              })}
            </div>
          </section>
        </div>
      )}

      {tab === "access" && (
        <div className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
          <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
            <div className="flex items-start justify-between gap-4"><div><h2 className="flex items-center gap-2 text-base font-semibold"><ShieldCheck className="text-mint" size={19} /> Credential Management</h2><p className="mt-1 text-xs text-slate-500">The full token is returned once; only a SHA-256 hash is stored.</p></div><Badge value={access?.active ? "ACTIVE" : "INACTIVE"} /></div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <div><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Client Name</div><div className="mt-1 text-sm font-medium">{access?.client_name ?? "—"}</div></div>
              <div><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Client Code</div><div className="mt-1 font-mono text-sm">{access?.client_code ?? "—"}</div></div>
              <div className="sm:col-span-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Base URL</div><div className="mt-1 break-all rounded-xl bg-slate-50 px-3 py-2 font-mono text-xs">{baseUrl || "—"}</div></div>
              <div className="sm:col-span-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Bearer Token</div><div className="mt-1 flex gap-2"><div className="min-w-0 flex-1 overflow-hidden rounded-xl border border-line bg-slate-50 px-3 py-2 font-mono text-sm">{token ? (showToken ? token : "••••••••••••••••••••••••") : access?.token_masked ?? "Not generated"}</div><button className="rounded-xl border border-line px-3" disabled={!token} onClick={() => setShowToken((value) => !value)} title={showToken ? "Hide" : "Show"}>{showToken ? <EyeOff size={17} /> : <Eye size={17} />}</button><button className="rounded-xl border border-line px-3" disabled={!token} onClick={() => void copy(token, "Bearer token copied.")} title="Copy token"><Clipboard size={17} /></button></div>{access?.token_hint && <div className="mt-2 text-xs text-slate-500">Stored hint: {access.token_hint} · rotated {formatDateTime(access.token_created_at)}</div>}</div>
            </div>
            <button type="button" className="mt-5 inline-flex items-center gap-2 rounded-xl bg-rust px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60" disabled={running === "regenerate"} onClick={() => void regenerate()}><RotateCcw size={16} /> Regenerate Token</button>
          </section>
          <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
            <h2 className="flex items-center gap-2 text-base font-semibold"><TerminalSquare className="text-ocean" size={19} /> Request Header</h2>
            <pre className="mt-4 overflow-x-auto rounded-xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">Authorization: Bearer YOUR_API_TOKEN{"\n"}Accept: application/json{"\n"}Content-Type: application/json</pre>
            <button className="mt-3 inline-flex items-center gap-2 rounded-xl border border-line px-3 py-2 text-sm" onClick={() => void copy("Authorization: Bearer YOUR_API_TOKEN\nAccept: application/json\nContent-Type: application/json", "Header example copied.")}><Clipboard size={15} /> Copy Header</button>
            <div className="mt-5 rounded-xl border border-amber/30 bg-amber/5 p-4 text-xs leading-5 text-slate-600">Regenerating invalidates the previous token immediately. The token is never written to request logs, browser storage, or API responses after initial generation.</div>
          </section>
        </div>
      )}

      {tab === "endpoints" && (
        <div className="space-y-5">
          {!token && <div className="rounded-xl border border-amber/30 bg-amber/5 p-4 text-sm text-slate-600">Authenticated Try API calls require the full token from this session. Open <button className="font-semibold text-ocean underline" onClick={() => setTab("access")}>API Access</button> and regenerate it first.</div>}
          {["SYSTEM", "MASTER DATA", "HISTORICAL DATA", "ROUTE RESULTS", "SHIFT CONFIGURATION"].map((group) => (
            <section key={group} className="space-y-3">
              <div className="px-1 text-xs font-bold tracking-[0.18em] text-slate-500">{group}</div>
              {endpointDefinitions.filter((definition) => definition.group === group).map((definition) => {
                const expanded = expandedEndpoint === definition.id;
                const result = results[definition.id];
                return <article key={definition.id} className="overflow-hidden rounded-2xl border border-line bg-white shadow-sm">
                  <button type="button" className="flex w-full items-center gap-3 p-4 text-left" onClick={() => setExpandedEndpoint(expanded ? "" : definition.id)}>
                    <span className="rounded-lg bg-mint/10 px-2.5 py-1 font-mono text-xs font-bold text-mint">GET</span><span className="min-w-0 flex-1"><span className="block break-all font-mono text-sm font-semibold text-petroink">{definition.path}</span><span className="mt-1 block text-xs text-slate-500">{definition.description}</span></span>{definition.authenticated && <ShieldCheck className="hidden text-slate-400 sm:block" size={17} />}{expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                  </button>
                  {expanded && <div className="border-t border-line p-4 lg:p-5">
                    <div className="grid gap-5 xl:grid-cols-2">
                      <div>
                        <div className="grid gap-3 sm:grid-cols-2">
                          {definition.fields.map((field) => <label key={field.key} className="text-xs font-semibold uppercase tracking-wide text-slate-500">{field.label}{field.required && <span className="text-rust"> *</span>}{field.type === "select" && field.key === "terminal_id" ? <select className="mt-2 w-full border border-line px-3 py-2 text-sm normal-case tracking-normal" value={fieldValue(definition.id, field.key)} onChange={(event) => updateField(definition.id, field.key, event.target.value)}>{depots.map((depot) => <option key={depot.depot_id} value={depot.depot_id}>{depot.depot_name}</option>)}</select> : field.type === "select" && field.key === "route_id" ? <select className="mt-2 w-full border border-line px-3 py-2 text-sm normal-case tracking-normal" value={fieldValue(definition.id, field.key)} onChange={(event) => updateField(definition.id, field.key, event.target.value)}><option value="">Select route</option>{routeOptions.map((route) => <option key={route.route_id} value={route.route_id}>{route.route_source.replace("PHASE_", "Phase ")} {route.route_version} · {route.route_name}</option>)}</select> : field.options ? <select className="mt-2 w-full border border-line px-3 py-2 text-sm normal-case tracking-normal" value={fieldValue(definition.id, field.key)} onChange={(event) => updateField(definition.id, field.key, event.target.value)}>{field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <input className="mt-2 w-full border border-line px-3 py-2 text-sm normal-case tracking-normal" type={field.type === "date" ? "date" : field.type === "datetime" ? "datetime-local" : "text"} value={fieldValue(definition.id, field.key)} placeholder={field.placeholder} onChange={(event) => updateField(definition.id, field.key, event.target.value)} />}</label>)}
                        </div>
                        <div className="mt-4 flex flex-wrap gap-2"><button className="inline-flex items-center gap-2 rounded-xl bg-mint px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60" disabled={running === definition.id} onClick={() => void sendRequest(definition)}><Play size={15} /> Send Request</button><button className="inline-flex items-center gap-2 rounded-xl border border-line px-4 py-2.5 text-sm" onClick={() => void copy(curlFor(definition), "cURL copied.")}><Clipboard size={15} /> Copy cURL</button></div>
                        <div className="mt-5"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Authentication</div><div className="mt-1 text-sm">{definition.authenticated ? "Bearer integration token" : "Not required"}</div></div>
                        <div className="mt-4"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Status Codes</div><div className="mt-2 flex flex-wrap gap-2"><Badge value={200} />{definition.authenticated && <Badge value={401} />}<Badge value={422} /><Badge value={429} /><Badge value={500} /></div></div>
                        <div className="mt-4"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Example Request / cURL</div><pre className="mt-2 overflow-x-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">{curlFor(definition)}</pre></div>
                      </div>
                      <div><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Example Response</div><pre className="mt-2 max-h-72 overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">{JSON.stringify(definition.example, null, 2)}</pre></div>
                    </div>
                    {result && <div className="mt-5 border-t border-line pt-5"><div className="mb-3 flex flex-wrap gap-2"><Badge value={result.status} /><span className="rounded-full border border-line px-2.5 py-1 text-[11px] text-slate-600">{result.responseTimeMs} ms</span><span className="rounded-full border border-line px-2.5 py-1 text-[11px] text-slate-600">{result.recordCount ?? "—"} records</span><span className="rounded-full border border-line px-2.5 py-1 font-mono text-[11px] text-slate-600">{result.requestId ?? "No request ID"}</span></div><pre className="max-h-[32rem] overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">{JSON.stringify(result.payload, null, 2)}</pre></div>}
                  </div>}
                </article>;
              })}
            </section>
          ))}
          {availabilitySummary && <section className="rounded-2xl border border-line bg-white p-5 shadow-sm"><h2 className="text-base font-semibold">Availability-after Summary</h2><div className="mt-4 grid gap-3 sm:grid-cols-3"><div className="rounded-xl bg-slate-50 p-4"><div className="text-xs text-slate-500">Reference Time</div><div className="mt-1 font-semibold">{formatDateTime(availabilitySummary.reference)}</div></div><div className="rounded-xl bg-mint/5 p-4"><div className="text-xs text-slate-500">Available Now</div><div className="mt-1 text-2xl font-semibold text-mint">{availabilitySummary.available} MT</div></div><div className="rounded-xl bg-amber/5 p-4"><div className="text-xs text-slate-500">Still On Trip</div><div className="mt-1 text-2xl font-semibold text-amber">{availabilitySummary.onTrip} MT</div></div></div><div className="mt-4 overflow-x-auto"><table className="w-full min-w-[850px] text-left text-xs"><thead className="border-b border-line text-slate-500"><tr>{["MT", "Capacity", "Status", "Active Trip", "Next Available", "Next Departure", "Handover Window"].map((item) => <th key={item} className="px-3 py-2">{item}</th>)}</tr></thead><tbody>{availabilitySummary.records.map((row) => <tr key={String(row.mt_id)} className="border-b border-line/60"><td className="px-3 py-3 font-semibold">{String(row.vehicle_number ?? row.mt_id)}</td><td className="px-3 py-3">{String(row.capacity_kl ?? "—")} KL</td><td className="px-3 py-3"><Badge value={String(row.availability_status)} /></td><td className="px-3 py-3 font-mono">{String(row.active_trip_id ?? "—")}</td><td className="px-3 py-3">{formatDateTime(row.next_available_at as string | null)}</td><td className="px-3 py-3">{formatDateTime(row.next_departure_at as string | null)}</td><td className="px-3 py-3">{row.handover_window_minutes == null ? "—" : `${String(row.handover_window_minutes)} min`}</td></tr>)}</tbody></table></div></section>}
        </div>
      )}

      {tab === "logs" && (
        <section className="rounded-2xl border border-line bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-end justify-between gap-4"><div><h2 className="flex items-center gap-2 text-base font-semibold"><Clock3 className="text-ocean" size={19} /> API Request Logs</h2><p className="mt-1 text-xs text-slate-500">Sanitized external connector traffic. Authorization headers and tokens are never logged.</p></div><div className="flex flex-wrap gap-2"><label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">From<input type="datetime-local" className="mt-1 block border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal" value={logDateFrom} onChange={(event) => setLogDateFrom(event.target.value)} /></label><label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">To<input type="datetime-local" className="mt-1 block border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal" value={logDateTo} onChange={(event) => setLogDateTo(event.target.value)} /></label><input className="self-end border border-line px-3 py-2 text-sm" value={logEndpoint} onChange={(event) => setLogEndpoint(event.target.value)} placeholder="Filter endpoint" /><select className="self-end border border-line px-3 py-2 text-sm" value={logStatus} onChange={(event) => setLogStatus(event.target.value)}><option value="">All statuses</option><option value="200">200</option><option value="400">400</option><option value="401">401</option><option value="403">403</option><option value="404">404</option><option value="422">422</option><option value="429">429</option><option value="500">500</option></select><select className="self-end border border-line px-3 py-2 text-sm" value={logClient} onChange={(event) => setLogClient(event.target.value)}><option value="">All clients</option>{access && <option value={access.client_id}>{access.client_name}</option>}</select><button className="inline-flex items-center gap-2 self-end rounded-xl bg-mint px-3 py-2 text-sm font-semibold text-white" onClick={() => void loadLogs()}><RefreshCw size={15} /> Apply</button></div></div>
          <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[980px] text-left text-xs"><thead className="border-b border-line text-slate-500"><tr>{["Date/Time", "Client", "Method", "Endpoint", "Status", "Duration", "Records", "Request ID"].map((item) => <th key={item} className="px-3 py-2">{item}</th>)}</tr></thead><tbody>{logs?.records.map((row) => <tr key={row.id} className="cursor-pointer border-b border-line/60 hover:bg-slate-50" onClick={async () => setSelectedLog(await apiGet<Record<string, unknown>>(`/api/v1/integration/amt-scheduler/console/logs/${row.id}`))}><td className="px-3 py-3">{formatDateTime(row.timestamp)}</td><td className="px-3 py-3">{row.client}</td><td className="px-3 py-3 font-mono font-semibold text-mint">{row.method}</td><td className="max-w-sm truncate px-3 py-3 font-mono">{row.endpoint}</td><td className="px-3 py-3"><Badge value={row.response_status} /></td><td className="px-3 py-3">{row.response_time_ms} ms</td><td className="px-3 py-3">{row.record_count ?? "—"}</td><td className="px-3 py-3 font-mono">{row.request_id}</td></tr>)}</tbody></table>{logs?.records.length === 0 && <div className="py-10 text-center text-sm text-slate-500">No API requests match the current filters.</div>}</div>
          {selectedLog && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" onClick={() => setSelectedLog(null)}><div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-2xl bg-white p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}><div className="flex items-center justify-between"><h3 className="font-semibold">API Log Detail</h3><button className="rounded-lg border border-line p-2" onClick={() => setSelectedLog(null)}><XCircle size={17} /></button></div><pre className="mt-4 overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">{JSON.stringify(selectedLog, null, 2)}</pre></div></div>}
        </section>
      )}
    </div>
  );
}
