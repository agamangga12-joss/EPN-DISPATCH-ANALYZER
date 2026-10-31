import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { API_BASE_URL } from "../lib/api";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRightLeft,
  ArrowUp,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Clock3,
  Copy,
  FileClock,
  Filter,
  Gauge,
  Loader2,
  MapPinned,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Truck,
  X,
} from "lucide-react";


const API = "/api/v1/phase8/manual-dispatch";

type DepotOption = { depot_id: string; depot_name: string };
type Json = Record<string, any>;

type Props = { depots: DepotOption[] };

const tabs = [
  { id: "trip-management", label: "Trip Management", icon: Truck },
  { id: "simulation", label: "Simulation Diagram", icon: Gauge },
  { id: "dashboard", label: "Daily Distribution Dashboard", icon: BarChart3 },
  { id: "geographic-map", label: "Geographic Map", icon: MapPinned },
  { id: "audit", label: "History / Audit", icon: FileClock },
] as const;

type TabId = (typeof tabs)[number]["id"];

async function request<T = Json>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${url}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    const message = typeof detail === "string" ? detail : detail?.message || payload.message || `Request failed (${response.status})`;
    const error = new Error(message) as Error & { payload?: Json };
    error.payload = payload;
    throw error;
  }
  return payload as T;
}

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }).format(parsed);
}

function formatTime(value?: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit", hour12: false }).format(parsed);
}

function durationLabel(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return "-";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours}j ${minutes}m` : `${minutes}m`;
}

function statusTone(status: string): string {
  if (["VALID", "READY", "FINALIZED", "ASSIGNED"].includes(status)) return "is-good";
  if (["CONFLICT"].includes(status)) return "is-bad";
  if (["WARNING", "NEEDS_RECALCULATION", "MODIFIED", "CALCULATING"].includes(status)) return "is-warning";
  return "";
}

function currentJobId(): string | null {
  const match = window.location.pathname.match(/^\/phase-8\/manual-dispatch\/([^/]+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function currentTab(): TabId {
  const value = new URLSearchParams(window.location.search).get("tab") as TabId | null;
  return tabs.some((tab) => tab.id === value) ? value! : "trip-management";
}

function validMapPoint(latitude: unknown, longitude: unknown): [number, number] | null {
  const lat = Number(latitude);
  const lng = Number(longitude);
  return Number.isFinite(lat) && Number.isFinite(lng) && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180 ? [lat, lng] : null;
}

function FitPhase8MapBounds({ positions, scopeKey }: { positions: [number, number][]; scopeKey: string }) {
  const map = useMap();
  useEffect(() => {
    const timer = window.setTimeout(() => {
      map.invalidateSize();
      if (positions.length) map.fitBounds(positions, { padding: [28, 28], maxZoom: 13 });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [map, positions, scopeKey]);
  return null;
}

export function ManualDispatchPage({ depots }: Props) {
  const [selectedJobId, setSelectedJobId] = useState<string | null>(() => currentJobId());
  const [activeTab, setActiveTab] = useState<TabId>(() => currentTab());
  const [workspace, setWorkspace] = useState<Json | null>(null);
  const [jobs, setJobs] = useState<Json>({ rows: [], total: 0 });
  const [sources, setSources] = useState<Json>({ jobs: [] });
  const [simulation, setSimulation] = useState<Json | null>(null);
  const [dashboard, setDashboard] = useState<Json | null>(null);
  const [audit, setAudit] = useState<Json | null>(null);
  const [validation, setValidation] = useState<Json | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionKey, setActionKey] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [finalizeOpen, setFinalizeOpen] = useState(false);
  const [acknowledgeUnassigned, setAcknowledgeUnassigned] = useState(false);
  const [expandedVehicles, setExpandedVehicles] = useState<Set<string>>(new Set());
  const [addDialog, setAddDialog] = useState<{ vehicle: Json; trip: Json } | null>(null);
  const [eligible, setEligible] = useState<Json>({ rows: [] });
  const [eligibleSearch, setEligibleSearch] = useState("");
  const [showIneligible, setShowIneligible] = useState(false);
  const [moveDialog, setMoveDialog] = useState<{ lo: Json; sourceTripId?: string } | null>(null);
  const [moveTarget, setMoveTarget] = useState("");
  const [ganttSearch, setGanttSearch] = useState("");
  const [ganttActiveOnly, setGanttActiveOnly] = useState(false);
  const [mapMTSearch, setMapMTSearch] = useState("");
  const [mapVehicleId, setMapVehicleId] = useState("");
  const [mapData, setMapData] = useState<Json | null>(null);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState("");
  const [unassignedFilters, setUnassignedFilters] = useState({ search: "", shift: "ALL", cluster: "ALL", product: "ALL", spbu: "ALL" });
  const [listFilters, setListFilters] = useState({ depot: depots[0]?.depot_id || "", date: "", status: "", search: "", offset: 0 });
  const [createForm, setCreateForm] = useState({ depot_id: depots[0]?.depot_id || "", operational_date: "", source_job_id: "", source_route_id: "", job_name: "" });

  const handleError = useCallback((caught: unknown) => {
    setError(caught instanceof Error ? caught.message : "Unexpected error");
  }, []);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "25", offset: String(listFilters.offset) });
      if (listFilters.depot) params.set("depot_id", listFilters.depot);
      if (listFilters.date) params.set("operational_date", listFilters.date);
      if (listFilters.status) params.set("status", listFilters.status);
      if (listFilters.search) params.set("search", listFilters.search);
      setJobs(await request(`${API}/jobs?${params}`));
      setError("");
    } catch (caught) {
      handleError(caught);
    } finally {
      setLoading(false);
    }
  }, [handleError, listFilters]);

  const loadWorkspace = useCallback(async (jobId: string) => {
    setLoading(true);
    try {
      const payload = await request(`${API}/jobs/${encodeURIComponent(jobId)}`);
      setWorkspace(payload);
      setExpandedVehicles(new Set((payload.vehicles || []).filter((row: Json) => row.trip_count > 0).map((row: Json) => row.id)));
      setError("");
    } catch (caught) {
      handleError(caught);
    } finally {
      setLoading(false);
    }
  }, [handleError]);

  useEffect(() => {
    const onPop = () => {
      setSelectedJobId(currentJobId());
      setActiveTab(currentTab());
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (selectedJobId) loadWorkspace(selectedJobId);
    else loadJobs();
  }, [selectedJobId, loadWorkspace, loadJobs]);

  useEffect(() => {
    if (!selectedJobId) return;
    if (activeTab === "simulation" && !simulation) request(`${API}/jobs/${selectedJobId}/simulation?bucket_minutes=60`).then(setSimulation).catch(handleError);
    if (activeTab === "dashboard" && !dashboard) request(`${API}/jobs/${selectedJobId}/dashboard`).then(setDashboard).catch(handleError);
    if (activeTab === "audit" && !audit) request(`${API}/jobs/${selectedJobId}/audit`).then(setAudit).catch(handleError);
  }, [activeTab, audit, dashboard, handleError, selectedJobId, simulation]);

  useEffect(() => {
    if (!selectedJobId || activeTab !== "geographic-map" || !mapVehicleId) return;
    let cancelled = false;
    setMapLoading(true);
    setMapError("");
    request(`${API}/jobs/${selectedJobId}/map?vehicle_id=${encodeURIComponent(mapVehicleId)}`)
      .then((payload) => { if (!cancelled) setMapData(payload); })
      .catch((caught) => { if (!cancelled) { setMapData(null); setMapError(caught instanceof Error ? caught.message : "Google road geometry could not be loaded."); } })
      .finally(() => { if (!cancelled) setMapLoading(false); });
    return () => { cancelled = true; };
  }, [activeTab, mapVehicleId, selectedJobId, workspace?.job?.job_version]);

  useEffect(() => {
    if (!createForm.depot_id) {
      setSources({ jobs: [] });
      return;
    }
    const params = new URLSearchParams({ depot_id: createForm.depot_id });
    if (createForm.operational_date) params.set("operational_date", createForm.operational_date);
    request(`${API}/sources?${params}`).then(setSources).catch(handleError);
  }, [createForm.depot_id, createForm.operational_date, handleError]);

  const sourceJob = (sources.jobs || []).find((job: Json) => job.job_id === createForm.source_job_id);
  const sourceRoutes = sourceJob?.routes || [];

  function openJob(jobId: string) {
    window.history.pushState({}, "", `/phase-8/manual-dispatch/${encodeURIComponent(jobId)}?tab=trip-management`);
    setSelectedJobId(jobId);
    setActiveTab("trip-management");
  }

  function backToJobs() {
    window.history.pushState({}, "", "/phase-8/manual-dispatch");
    setSelectedJobId(null);
    setWorkspace(null);
    setSimulation(null);
    setDashboard(null);
    setAudit(null);
    setMapMTSearch("");
    setMapVehicleId("");
    setMapData(null);
    setMapError("");
  }

  function changeTab(tab: TabId) {
    if (!selectedJobId) return;
    window.history.pushState({}, "", `/phase-8/manual-dispatch/${encodeURIComponent(selectedJobId)}?tab=${tab}`);
    setActiveTab(tab);
  }

  async function mutate(key: string, url: string, options: RequestInit, success: string) {
    setActionKey(key);
    setError("");
    try {
      const payload = await request(url, options);
      const next = payload.workspace || payload;
      if (next.job && next.vehicles) setWorkspace(next);
      setSimulation(null);
      setDashboard(null);
      setAudit(null);
      setMapData(null);
      setValidation(payload.validation || null);
      setNotice(success);
      return payload;
    } catch (caught) {
      handleError(caught);
      throw caught;
    } finally {
      setActionKey("");
    }
  }

  async function createJob() {
    const payload = await mutate("create", `${API}/jobs`, { method: "POST", body: JSON.stringify(createForm) }, "Manual Dispatch Job created from an immutable source snapshot.");
    setCreateOpen(false);
    openJob(payload.job.id);
  }

  async function createVersion() {
    if (!workspace || !window.confirm(`Create Dispatch V${workspace.job.dispatch_version + 1} as a new working snapshot?`)) return;
    const payload = await mutate("version", `${API}/jobs/${workspace.job.id}/versions`, { method: "POST", body: JSON.stringify({ expected_job_version: workspace.job.job_version }) }, "New dispatch version created.");
    openJob(payload.job.id);
  }

  async function openFinalize() {
    if (!workspace) return;
    try {
      const result = await request(`${API}/jobs/${workspace.job.id}/validation`);
      setValidation(result);
      setAcknowledgeUnassigned(false);
      setFinalizeOpen(true);
    } catch (caught) {
      handleError(caught);
    }
  }

  async function finalize() {
    if (!workspace) return;
    await mutate("finalize", `${API}/jobs/${workspace.job.id}/finalize`, {
      method: "POST",
      body: JSON.stringify({ acknowledge_unassigned: acknowledgeUnassigned, expected_job_version: workspace.job.job_version }),
    }, "Dispatch finalized and is now read-only.");
    setFinalizeOpen(false);
  }

  async function openAddLO(vehicle: Json, trip: Json) {
    setAddDialog({ vehicle, trip });
    setEligibleSearch("");
    setShowIneligible(false);
    setEligible(await request(`${API}/jobs/${workspace!.job.id}/vehicles/${vehicle.id}/eligible-loading-orders?trip_id=${trip.id}`));
  }

  async function loadEligible() {
    if (!addDialog || !workspace) return;
    const params = new URLSearchParams({ trip_id: addDialog.trip.id, include_ineligible: String(showIneligible) });
    if (eligibleSearch) params.set("search", eligibleSearch);
    setEligible(await request(`${API}/jobs/${workspace.job.id}/vehicles/${addDialog.vehicle.id}/eligible-loading-orders?${params}`));
  }

  const allTrips = useMemo(() => (workspace?.vehicles || []).flatMap((vehicle: Json) => (vehicle.trips || []).map((trip: Json) => ({ ...trip, vehicle }))), [workspace]);
  const mapVehicleOptions = useMemo(() => {
    const query = mapMTSearch.trim().toLowerCase();
    return (workspace?.vehicles || []).filter((vehicle: Json) => vehicle.trip_count > 0 && (
      !query
      || vehicle.id === mapVehicleId
      || `${vehicle.vehicle_registration || ""} ${vehicle.mt_id || ""}`.toLowerCase().includes(query)
    ));
  }, [mapMTSearch, mapVehicleId, workspace]);

  const unassignedRows = useMemo(() => {
    const rows = workspace?.unassigned?.rows || [];
    return rows.filter((row: Json) => {
      const token = unassignedFilters.search.toLowerCase();
      const searchable = `${row.lo_number} ${row.spbu_number} ${row.spbu_name}`.toLowerCase();
      return (!token || searchable.includes(token))
        && (unassignedFilters.shift === "ALL" || row.shift_name === unassignedFilters.shift)
        && (unassignedFilters.cluster === "ALL" || row.cluster_name === unassignedFilters.cluster)
        && (unassignedFilters.product === "ALL" || row.product_name === unassignedFilters.product)
        && (unassignedFilters.spbu === "ALL" || row.spbu_id === unassignedFilters.spbu);
    });
  }, [unassignedFilters, workspace]);

  function uniqueUnassigned(field: string): string[] {
    return Array.from(new Set<string>((workspace?.unassigned?.rows || []).map((row: Json) => String(row[field] || "Unknown")))).sort();
  }

  if (!selectedJobId) {
    return (
      <div className="phase8-shell">
        <section className="phase8-toolbar">
          <div>
            <div className="phase8-overline">Phase 8 · Human-in-the-loop operations</div>
            <h2>Manual Dispatch Job List</h2>
            <p>Create an isolated working snapshot from Phase 6 warm start or any available Phase 7 route version.</p>
          </div>
          <button className="phase8-primary" onClick={() => setCreateOpen(true)}><Plus size={17} /> Create New Manual Dispatch Job</button>
        </section>

        {error && <div className="phase8-alert is-bad"><AlertTriangle size={17} />{error}</div>}
        {notice && <div className="phase8-alert is-good"><CheckCircle2 size={17} />{notice}</div>}

        <section className="phase8-card">
          <div className="phase8-filters">
            <label><span>TBBM / Depot</span><select value={listFilters.depot} onChange={(event) => setListFilters({ ...listFilters, depot: event.target.value, offset: 0 })}>{depots.map((depot) => <option key={depot.depot_id} value={depot.depot_id}>{depot.depot_name}</option>)}</select></label>
            <label><span>Operational Date</span><input type="date" value={listFilters.date} onChange={(event) => setListFilters({ ...listFilters, date: event.target.value, offset: 0 })} /></label>
            <label><span>Status</span><select value={listFilters.status} onChange={(event) => setListFilters({ ...listFilters, status: event.target.value, offset: 0 })}><option value="">All Status</option>{["DRAFT", "IN_PROGRESS", "READY", "FINALIZED"].map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="phase8-search"><span>Job ID / Job Name</span><div><Search size={15} /><input value={listFilters.search} onChange={(event) => setListFilters({ ...listFilters, search: event.target.value, offset: 0 })} placeholder="Search job..." /></div></label>
            <button className="phase8-secondary" onClick={loadJobs}><RefreshCw size={16} /> Refresh</button>
          </div>
          <div className="phase8-table-wrap">
            <table className="phase8-table phase8-job-table">
              <thead><tr>{["Job ID / Name", "TBBM", "Operational Date", "Source Phase 7 / Route", "Dispatch Version", "Status", "Assigned / Unassigned LO", "MT / Trips", "Last Updated", "Created By", ""].map((head) => <th key={head}>{head}</th>)}</tr></thead>
              <tbody>
                {(jobs.rows || []).map((job: Json) => (
                  <tr key={job.id}>
                    <td><strong>{job.job_id}</strong><small>{job.job_name}</small></td>
                    <td>{job.depot_name || job.depot_id}</td><td>{job.operational_date}</td>
                    <td><strong>{job.source_job_id}</strong><small>{job.source_phase} · {job.source_route_version}</small></td>
                    <td>Dispatch V{job.dispatch_version}</td><td><span className={`phase8-badge ${statusTone(job.status)}`}>{job.status}</span></td>
                    <td>{job.assigned_lo} / <span className="text-rust">{job.unassigned_lo}</span></td><td>{job.mt_used} MT · {job.total_trips} trips</td>
                    <td>{formatDateTime(job.last_saved)}</td><td>{job.created_by}</td>
                    <td><button className="phase8-link" onClick={() => openJob(job.id)}>Open <ChevronRight size={15} /></button></td>
                  </tr>
                ))}
                {!loading && !(jobs.rows || []).length && <tr><td colSpan={11}><div className="phase8-empty">No Manual Dispatch Jobs match the selected filters.</div></td></tr>}
              </tbody>
            </table>
          </div>
          <div className="phase8-pagination"><span>{jobs.total || 0} jobs</span><div><button disabled={listFilters.offset === 0} onClick={() => setListFilters({ ...listFilters, offset: Math.max(0, listFilters.offset - 25) })}>Previous</button><strong>{Math.floor(listFilters.offset / 25) + 1}</strong><button disabled={listFilters.offset + 25 >= jobs.total} onClick={() => setListFilters({ ...listFilters, offset: listFilters.offset + 25 })}>Next</button></div></div>
        </section>

        {createOpen && (
          <div className="phase8-modal-backdrop">
            <div className="phase8-modal">
              <button className="phase8-modal-close" onClick={() => setCreateOpen(false)}><X size={18} /></button>
              <div className="phase8-overline">New immutable working snapshot</div><h3>Create Manual Dispatch Job</h3>
              <div className="phase8-form-grid">
                <label><span>TBBM / Depot *</span><select value={createForm.depot_id} onChange={(event) => setCreateForm({ ...createForm, depot_id: event.target.value, source_job_id: "", source_route_id: "" })}><option value="">Select depot</option>{depots.map((depot) => <option key={depot.depot_id} value={depot.depot_id}>{depot.depot_name}</option>)}</select></label>
                <label><span>Operational Date *</span><input type="date" value={createForm.operational_date} onChange={(event) => setCreateForm({ ...createForm, operational_date: event.target.value, source_job_id: "", source_route_id: "" })} /></label>
                <label><span>Phase 7 Job *</span><select disabled={!createForm.depot_id} value={createForm.source_job_id} onChange={(event) => setCreateForm({ ...createForm, source_job_id: event.target.value, source_route_id: "" })}><option value="">Select Phase 7 Job</option>{(sources.jobs || []).map((job: Json) => <option key={job.job_id} value={job.job_id}>{job.job_no} · {job.job_name}</option>)}</select></label>
                <label><span>Source Route *</span><select disabled={!createForm.source_job_id} value={createForm.source_route_id} onChange={(event) => setCreateForm({ ...createForm, source_route_id: event.target.value })}><option value="">Select route</option>{sourceRoutes.map((route: Json) => <option key={route.source_route_id} value={route.source_route_id}>{route.source_route_version}</option>)}</select><small>Versions are retrieved dynamically; no maximum is hardcoded.</small></label>
                <label className="phase8-span-2"><span>Manual Dispatch Job Name *</span><input value={createForm.job_name} onChange={(event) => setCreateForm({ ...createForm, job_name: event.target.value })} placeholder="e.g. Dispatch Aceh 31 Aug – Morning Control" /></label>
              </div>
              <div className="phase8-note"><ClipboardCheck size={17} /><span>Creating this job copies vehicle, trip, and LO assignment into Phase 8. Phase 6/7 source records remain unchanged.</span></div>
              <div className="phase8-modal-actions"><button className="phase8-secondary" onClick={() => setCreateOpen(false)}>Cancel</button><button className="phase8-primary" disabled={!createForm.depot_id || !createForm.operational_date || !createForm.source_job_id || !createForm.source_route_id || !createForm.job_name.trim() || actionKey === "create"} onClick={() => createJob().catch(() => undefined)}>{actionKey === "create" ? <Loader2 className="animate-spin" size={16} /> : <Plus size={16} />} Create & Load</button></div>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (!workspace) return <div className="phase8-loading"><Loader2 className="animate-spin" /> Loading Manual Dispatch workspace…</div>;
  const readOnly = workspace.job.status === "FINALIZED";

  return (
    <div className="phase8-shell">
      <button className="phase8-back" onClick={backToJobs}><ArrowLeft size={16} /> Manual Dispatch Job List</button>
      <section className="phase8-job-header">
        <div className="phase8-job-title"><div><div className="phase8-overline">{workspace.job.job_id} · Dispatch V{workspace.job.dispatch_version}</div><h2>{workspace.job.job_name}</h2></div><span className={`phase8-badge ${statusTone(workspace.job.status)}`}>{workspace.job.status}</span></div>
        <div className="phase8-header-meta">
          <div><span>TBBM</span><strong>{workspace.job.depot_name || workspace.job.depot_id}</strong></div><div><span>Operational Date</span><strong>{workspace.job.operational_date}</strong></div><div><span>Source Phase / Job</span><strong>{workspace.job.source_phase} · {workspace.job.source_job_id}</strong></div><div><span>Source Route</span><strong>{workspace.job.source_route_version}</strong></div><div><span>Last Saved</span><strong>{formatDateTime(workspace.job.last_saved)}</strong></div><div><span>Created By</span><strong>{workspace.job.created_by}</strong></div>
        </div>
        <div className="phase8-header-actions"><button className="phase8-secondary" disabled={actionKey === "version"} onClick={() => createVersion().catch(() => undefined)}><Copy size={16} /> Create New Version</button>{!readOnly && <button className="phase8-primary" onClick={openFinalize}><CheckCircle2 size={16} /> Finalize Dispatch</button>}</div>
      </section>

      {readOnly && <div className="phase8-alert is-info"><ClipboardCheck size={17} />This finalized dispatch is read-only. Use Create New Version for further adjustments.</div>}
      {error && <div className="phase8-alert is-bad"><AlertTriangle size={17} />{error}</div>}
      {notice && <div className="phase8-alert is-good"><CheckCircle2 size={17} />{notice}<button onClick={() => setNotice("")}><X size={14} /></button></div>}

      <nav className="phase8-tabs">{tabs.map((tab) => { const Icon = tab.icon; return <button key={tab.id} className={activeTab === tab.id ? "is-active" : ""} onClick={() => changeTab(tab.id)}><Icon size={16} />{tab.label}</button>; })}</nav>

      {activeTab === "trip-management" && (
        <div className="phase8-trip-layout">
          <section className="phase8-vehicle-stack">
            <div className="phase8-section-head"><div><h3>MT → Trip → Loading Order</h3><p>Every edit sets the affected trip to MODIFIED. Apply validates, routes, and updates the timeline.</p></div><span>{workspace.vehicles.length} MT in scope</span></div>
            {workspace.vehicles.map((vehicle: Json) => {
              const expanded = expandedVehicles.has(vehicle.id);
              return (
                <article className="phase8-mt-card" key={vehicle.id} id={`vehicle-${vehicle.id}`}>
                  <button className="phase8-mt-head" onClick={() => setExpandedVehicles((current) => { const next = new Set(current); next.has(vehicle.id) ? next.delete(vehicle.id) : next.add(vehicle.id); return next; })}>
                    {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                    <div className="phase8-mt-identity"><strong>{vehicle.vehicle_registration || vehicle.mt_id}</strong><span>{vehicle.mt_id}</span></div>
                    <div><span>Vehicle Class</span><strong>{vehicle.vehicle_class || "-"} KL</strong></div><div><span>Capacity</span><strong>{vehicle.capacity_kl} KL</strong></div><div><span>Initial Available</span><strong>{formatTime(vehicle.initial_available_datetime)}</strong></div><div><span>Trips</span><strong>{vehicle.trip_count}</strong></div><div><span>Last Return</span><strong>{formatTime(vehicle.last_estimated_return_datetime)}</strong></div><div><span>Last Available</span><strong>{formatTime(vehicle.last_available_datetime)}</strong></div><div><span>Assigned</span><strong>{vehicle.total_assigned_volume_kl} KL</strong></div><span className={`phase8-badge ${statusTone(vehicle.status)}`}>{vehicle.status}</span>
                  </button>
                  {expanded && <div className="phase8-mt-body"><div className="phase8-tag-row"><span>MT Tags</span>{vehicle.mt_tags.length ? vehicle.mt_tags.map((tag: string) => <i key={tag}>{tag}</i>) : <em>No tags</em>}</div>
                    <div className="phase8-trip-stack">
                      {vehicle.trips.map((trip: Json) => <TripCard key={trip.id} trip={trip} vehicle={vehicle} readOnly={readOnly} actionKey={actionKey} workspace={workspace} onMutate={mutate} onAdd={() => openAddLO(vehicle, trip).catch(handleError)} onMove={(lo) => { setMoveDialog({ lo, sourceTripId: trip.id }); setMoveTarget(""); }} />)}
                      {!vehicle.trips.length && <div className="phase8-empty">No trips assigned to this MT.</div>}
                    </div>
                    {!readOnly && <button className="phase8-secondary phase8-add-trip" disabled={!vehicle.can_add_trip || actionKey === `add-trip-${vehicle.id}`} title={!vehicle.can_add_trip ? "Previous trip must be VALID with calculated availability." : "Add next trip"} onClick={() => mutate(`add-trip-${vehicle.id}`, `${API}/jobs/${workspace.job.id}/trips`, { method: "POST", body: JSON.stringify({ vehicle_id: vehicle.id, expected_job_version: workspace.job.job_version }) }, "Trip created at the earliest MT availability.").catch(() => undefined)}><Plus size={15} /> Add Trip</button>}
                  </div>}
                </article>
              );
            })}
          </section>

          <aside className="phase8-unassigned">
            <div className="phase8-section-head"><div><h3>Unassigned LO</h3><p>Removed assignments remain in planning scope.</p></div></div>
            <div className="phase8-mini-kpis"><div><strong>{workspace.unassigned.count}</strong><span>LO</span></div><div><strong>{workspace.unassigned.volume_kl}</strong><span>KL</span></div><div><strong>{workspace.unassigned.spbu_count}</strong><span>SPBU</span></div></div>
            <div className="phase8-unassigned-filters"><div className="phase8-search-line"><Search size={15} /><input placeholder="Search LO / SPBU" value={unassignedFilters.search} onChange={(event) => setUnassignedFilters({ ...unassignedFilters, search: event.target.value })} /></div>
              <select value={unassignedFilters.shift} onChange={(event) => setUnassignedFilters({ ...unassignedFilters, shift: event.target.value })}><option value="ALL">All shifts</option>{uniqueUnassigned("shift_name").map((value) => <option key={value}>{value}</option>)}</select>
              <select value={unassignedFilters.cluster} onChange={(event) => setUnassignedFilters({ ...unassignedFilters, cluster: event.target.value })}><option value="ALL">All clusters</option>{uniqueUnassigned("cluster_name").map((value) => <option key={value}>{value}</option>)}</select>
              <select value={unassignedFilters.product} onChange={(event) => setUnassignedFilters({ ...unassignedFilters, product: event.target.value })}><option value="ALL">All products</option>{uniqueUnassigned("product_name").map((value) => <option key={value}>{value}</option>)}</select>
              <select value={unassignedFilters.spbu} onChange={(event) => setUnassignedFilters({ ...unassignedFilters, spbu: event.target.value })}><option value="ALL">All SPBU</option>{(workspace.unassigned.rows || []).map((row: Json) => <option key={row.spbu_id} value={row.spbu_id}>{row.spbu_number}</option>)}</select>
            </div>
            <div className="phase8-unassigned-list">{unassignedRows.map((lo: Json) => <div key={lo.id} className="phase8-lo-mini"><div><strong>{lo.lo_number}</strong><span>{lo.spbu_number} · {lo.spbu_name}</span></div><div className="phase8-lo-meta"><span>{lo.product_name}</span><b>{lo.volume_kl} KL</b><span>{lo.cluster_name}</span><span>{lo.shift_name}</span></div>{lo.status_reason && <small>{lo.status_reason}</small>}{!readOnly && <button className="phase8-link" onClick={() => { setMoveDialog({ lo }); setMoveTarget(""); }}>Assign <ArrowRightLeft size={14} /></button>}</div>)}{!unassignedRows.length && <div className="phase8-empty">No unassigned LO match the filters.</div>}</div>
          </aside>
        </div>
      )}

      {activeTab === "simulation" && <SimulationTab data={simulation} search={ganttSearch} activeOnly={ganttActiveOnly} onSearch={setGanttSearch} onActiveOnly={setGanttActiveOnly} onOpenTrip={(vehicleId, tripId) => { changeTab("trip-management"); setExpandedVehicles((current) => new Set(current).add(vehicleId)); window.setTimeout(() => document.getElementById(`trip-${tripId}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 80); }} />}
      {activeTab === "dashboard" && <DashboardTab data={dashboard} onRemaining={(type, name) => { changeTab("trip-management"); setUnassignedFilters({ search: "", shift: type === "shift" ? name : "ALL", cluster: type === "cluster" ? name : "ALL", product: type === "product" ? name : "ALL", spbu: "ALL" }); }} />}
      {activeTab === "geographic-map" && <GeographicMapTab vehicles={mapVehicleOptions} search={mapMTSearch} selectedVehicleId={mapVehicleId} data={mapData} loading={mapLoading} error={mapError} onSearch={setMapMTSearch} onSelect={(vehicleId) => { setMapVehicleId(vehicleId); setMapData(null); setMapError(""); }} />}
      {activeTab === "audit" && <AuditTab data={audit} />}

      {addDialog && <div className="phase8-drawer-backdrop"><aside className="phase8-drawer"><div className="phase8-drawer-head"><div><div className="phase8-overline">Eligibility-filtered selection</div><h3>Add LO · {addDialog.vehicle.vehicle_registration} Trip {addDialog.trip.trip_sequence}</h3></div><button onClick={() => setAddDialog(null)}><X size={18} /></button></div><div className="phase8-drawer-search"><div className="phase8-search-line"><Search size={15} /><input value={eligibleSearch} onChange={(event) => setEligibleSearch(event.target.value)} placeholder="LO, SPBU, product..." /></div><label><input type="checkbox" checked={showIneligible} onChange={(event) => setShowIneligible(event.target.checked)} /> Show ineligible reasons</label><button className="phase8-secondary" onClick={() => loadEligible().catch(handleError)}><Filter size={15} /> Apply</button></div><div className="phase8-eligible-list">{(eligible.rows || []).map((lo: Json) => <div key={lo.id} className={`phase8-eligible-row ${lo.eligible ? "" : "is-disabled"}`}><div><strong>{lo.lo_number}</strong><span>{lo.spbu_number} · {lo.spbu_name}</span></div><div><span>{lo.product_name}</span><b>{lo.volume_kl} KL</b><span>{lo.cluster_name}</span><span>{lo.shift_name}</span></div><div className="phase8-tag-row">{lo.spbu_tags.map((tag: string) => <i key={tag}>{tag}</i>)}</div>{lo.rejection_reasons?.map((reason: string) => <small key={reason}>{reason}</small>)}<button className="phase8-primary" disabled={!lo.eligible || actionKey === `add-lo-${lo.id}`} onClick={() => mutate(`add-lo-${lo.id}`, `${API}/jobs/${workspace.job.id}/trips/${addDialog.trip.id}/loading-orders`, { method: "POST", body: JSON.stringify({ lo_scope_id: lo.id, expected_job_version: workspace.job.job_version }) }, `${lo.lo_number} added. Apply the modified trip to validate timing.`).then(() => setAddDialog(null)).catch(() => undefined)}>Add LO</button></div>)}</div></aside></div>}

      {moveDialog && <div className="phase8-modal-backdrop"><div className="phase8-modal phase8-modal-sm"><button className="phase8-modal-close" onClick={() => setMoveDialog(null)}><X size={18} /></button><div className="phase8-overline">Explicit assignment move</div><h3>{moveDialog.sourceTripId ? "Move" : "Assign"} {moveDialog.lo.lo_number}</h3><label className="phase8-field"><span>Destination MT / Trip</span><select value={moveTarget} onChange={(event) => setMoveTarget(event.target.value)}><option value="">Select destination</option>{allTrips.filter((row: Json) => row.id !== moveDialog.sourceTripId).map((row: Json) => <option key={row.id} value={row.id}>{row.vehicle.vehicle_registration} · Trip {row.trip_sequence} · {row.total_volume_kl}/{row.vehicle.capacity_kl} KL</option>)}</select></label><p className="phase8-help">Backend compatibility and capacity rules will be evaluated before the move is committed.</p><div className="phase8-modal-actions"><button className="phase8-secondary" onClick={() => setMoveDialog(null)}>Cancel</button><button className="phase8-primary" disabled={!moveTarget || actionKey === "move-lo"} onClick={() => mutate("move-lo", `${API}/jobs/${workspace.job.id}/loading-orders/${moveDialog.lo.id}/move`, { method: "POST", body: JSON.stringify({ destination_trip_id: moveTarget, expected_job_version: workspace.job.job_version }) }, `${moveDialog.lo.lo_number} moved. Affected trips require Apply.`).then(() => setMoveDialog(null)).catch(() => undefined)}><ArrowRightLeft size={16} /> Move LO</button></div></div></div>}

      {finalizeOpen && validation && <div className="phase8-modal-backdrop"><div className="phase8-modal"><button className="phase8-modal-close" onClick={() => setFinalizeOpen(false)}><X size={18} /></button><div className="phase8-overline">Complete validation</div><h3>Finalize Dispatch</h3><div className="phase8-final-summary">{Object.entries(validation.summary || {}).map(([key, value]) => <div key={key}><span>{key.replace(/_/g, " ")}</span><strong>{String(value)}</strong></div>)}</div>{validation.hard_errors?.length > 0 && <div className="phase8-validation-errors"><strong>Hard errors block finalization</strong>{validation.hard_errors.map((row: Json, index: number) => <span key={`${row.code}-${index}`}>{row.message}</span>)}</div>}{validation.warnings?.map((row: Json) => <div className="phase8-alert is-warning" key={row.code}><AlertTriangle size={17} />{row.message}</div>)}{validation.warnings?.length > 0 && <label className="phase8-ack"><input type="checkbox" checked={acknowledgeUnassigned} onChange={(event) => setAcknowledgeUnassigned(event.target.checked)} /> I acknowledge the explicit unassigned demand warning.</label>}<div className="phase8-modal-actions"><button className="phase8-secondary" onClick={() => setFinalizeOpen(false)}>Cancel</button><button className="phase8-primary" disabled={!validation.valid || (validation.warnings?.length > 0 && !acknowledgeUnassigned) || actionKey === "finalize"} onClick={() => finalize().catch(() => undefined)}><CheckCircle2 size={16} /> Finalize Dispatch</button></div></div></div>}
    </div>
  );
}


function TripCard({ trip, vehicle, readOnly, actionKey, workspace, onMutate, onAdd, onMove }: { trip: Json; vehicle: Json; readOnly: boolean; actionKey: string; workspace: Json; onMutate: (key: string, url: string, options: RequestInit, success: string) => Promise<Json>; onAdd: () => void; onMove: (lo: Json) => void }) {
  const [departure, setDeparture] = useState(() => trip.departure_datetime ? new Date(trip.departure_datetime).toISOString().slice(0, 16) : "");
  const loIds = trip.loading_orders.map((row: Json) => row.id);

  async function reorder(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= loIds.length) return;
    const next = [...loIds];
    [next[index], next[target]] = [next[target], next[index]];
    await onMutate(`reorder-${trip.id}`, `${API}/jobs/${workspace.job.id}/trips/${trip.id}/stop-order`, { method: "PUT", body: JSON.stringify({ lo_scope_ids: next, expected_job_version: workspace.job.job_version }) }, "Stop sequence updated. Apply the trip to recalculate route and arrivals.");
  }

  return <article className={`phase8-trip-card ${trip.status === "NEEDS_RECALCULATION" ? "is-stale" : ""}`} id={`trip-${trip.id}`}>
    <header className="phase8-trip-head"><div><span>Trip {trip.trip_sequence}</span><strong>{trip.trip_id}</strong></div><span className={`phase8-badge ${statusTone(trip.status)}`}>{trip.status.replace(/_/g, " ")}</span><div className="phase8-trip-actions">{!readOnly && <><button className="phase8-secondary" onClick={onAdd}><Plus size={14} /> Add LO</button><button className="phase8-danger" onClick={() => { if (window.confirm(`Delete Trip ${trip.trip_sequence}? Its LO will return to Unassigned.`)) onMutate(`delete-${trip.id}`, `${API}/jobs/${workspace.job.id}/trips/${trip.id}?expected_job_version=${workspace.job.job_version}`, { method: "DELETE" }, "Trip deleted; its LO returned to Unassigned.").catch(() => undefined); }}><Trash2 size={14} /></button></>}</div></header>
    {trip.status === "NEEDS_RECALCULATION" && <div className="phase8-stale-note"><AlertTriangle size={15} />Upstream timing changed. Apply this trip again before its timeline is valid.</div>}
    <div className="phase8-trip-timeline"><label><span>Available Before</span><strong>{formatDateTime(trip.available_before_trip_datetime)}</strong></label><label><span>Departure / Start</span>{readOnly ? <strong>{formatDateTime(trip.departure_datetime)}</strong> : <div><input type="datetime-local" value={departure} min={trip.available_before_trip_datetime ? new Date(trip.available_before_trip_datetime).toISOString().slice(0, 16) : undefined} onChange={(event) => setDeparture(event.target.value)} /><button title="Save start time as MODIFIED" disabled={!departure} onClick={() => onMutate(`time-${trip.id}`, `${API}/jobs/${workspace.job.id}/trips/${trip.id}`, { method: "PATCH", body: JSON.stringify({ departure_datetime: new Date(departure).toISOString(), expected_job_version: workspace.job.job_version, expected_trip_version: trip.trip_version }) }, "Trip start updated. Apply to recalculate.").catch(() => undefined)}>Save</button></div>}</label><label><span>Estimated Return</span><strong>{formatDateTime(trip.estimated_return_datetime)}</strong></label><label><span>Available After</span><strong>{formatDateTime(trip.available_after_trip_datetime)}</strong></label></div>
    <div className="phase8-trip-metrics"><div><span>Total LO</span><strong>{trip.total_lo}</strong></div><div><span>SPBU Stops</span><strong>{trip.total_spbu_stops}</strong></div><div><span>Volume</span><strong>{trip.total_volume_kl} KL</strong></div><div><span>Distance</span><strong>{trip.distance_meter ? `${(trip.distance_meter / 1000).toFixed(1)} km` : "-"}</strong></div><div><span>Travel</span><strong>{durationLabel(trip.travel_duration_seconds)}</strong></div><div><span>Service</span><strong>{durationLabel(trip.service_duration_seconds)}</strong></div><div><span>Total Duration</span><strong>{durationLabel(trip.total_duration_seconds)}</strong></div></div>
    {trip.route_error_message && <div className="phase8-alert is-warning"><AlertTriangle size={15} />{trip.route_error_message}</div>}
    <div className="phase8-lo-list">{trip.loading_orders.map((lo: Json, index: number) => <div className="phase8-lo-row" key={lo.id}><div className="phase8-stop-number">{lo.stop_sequence}</div><div><strong>{lo.lo_number}</strong><span>{lo.lo_id}</span></div><div><strong>{lo.spbu_number}</strong><span>{lo.spbu_name}</span></div><div><span>Product</span><strong>{lo.product_name || "-"}</strong></div><div><span>Volume</span><strong>{lo.volume_kl} KL</strong></div><div><span>Cluster</span><strong>{lo.cluster_name}</strong></div><div><span>Shift</span><strong>{lo.shift_name}</strong></div><div><span>ETA SPBU</span><strong>{formatTime(lo.estimated_arrival_datetime)}</strong></div><div className="phase8-lo-actions">{!readOnly && <><button disabled={index === 0} title="Move stop up" onClick={() => reorder(index, -1).catch(() => undefined)}><ArrowUp size={14} /></button><button disabled={index === loIds.length - 1} title="Move stop down" onClick={() => reorder(index, 1).catch(() => undefined)}><ArrowDown size={14} /></button><button title="Move LO" onClick={() => onMove(lo)}><ArrowRightLeft size={14} /></button><button className="is-danger" title="Remove LO" onClick={() => onMutate(`remove-${lo.id}`, `${API}/jobs/${workspace.job.id}/trips/${trip.id}/loading-orders/${lo.id}?expected_job_version=${workspace.job.job_version}`, { method: "DELETE" }, `${lo.lo_number} returned to Unassigned. Apply this trip again.`).catch(() => undefined)}><X size={14} /></button></>}</div></div>)}{!trip.loading_orders.length && <div className="phase8-empty">This trip has no Loading Orders.</div>}</div>
    {!readOnly && <footer className="phase8-apply-row"><div><span>Apply flow</span><small>Validate → Google Routes → service time → return → availability → cascade</small></div><button className="phase8-primary" disabled={actionKey === `apply-${trip.id}` || trip.status === "CALCULATING"} onClick={() => onMutate(`apply-${trip.id}`, `${API}/jobs/${workspace.job.id}/trips/${trip.id}/apply`, { method: "POST", body: JSON.stringify({ expected_job_version: workspace.job.job_version, expected_trip_version: trip.trip_version }) }, "Trip applied; simulation and dashboard refreshed from the current state.").catch(() => undefined)}>{actionKey === `apply-${trip.id}` ? <><Loader2 className="animate-spin" size={15} /> Calculating Route...</> : <><RefreshCw size={15} /> Apply</>}</button></footer>}
  </article>;
}


function SimulationTab({ data, search, activeOnly, onSearch, onActiveOnly, onOpenTrip }: { data: Json | null; search: string; activeOnly: boolean; onSearch: (value: string) => void; onActiveOnly: (value: boolean) => void; onOpenTrip: (vehicleId: string, tripId: string) => void }) {
  if (!data) return <div className="phase8-loading"><Loader2 className="animate-spin" /> Aggregating current dispatch simulation…</div>;
  const labels = data.buckets.map((row: Json) => row.label.slice(0, 5));
  const rows = data.gantt.rows.filter((row: Json) => (!search || `${row.vehicle_registration} ${row.mt_id}`.toLowerCase().includes(search.toLowerCase())) && (!activeOnly || row.active));
  const windowStart = new Date(data.gantt.window_start).getTime();
  const windowEnd = new Date(data.gantt.window_end).getTime();
  return <div className="phase8-tab-stack"><div className="phase8-kpi-grid">{Object.entries(data.summary).map(([key, value]) => <div className="phase8-kpi" key={key}><span>{key.replace(/_/g, " ")}</span><strong>{String(value ?? "-")}</strong></div>)}</div>
    <div className="phase8-chart-grid"><section className="phase8-card"><div className="phase8-section-head"><div><h3>LO Gate-Out Demand vs MT Available Capacity</h3><p>Capacity metric is KL; tooltip retains LO/trip/MT counts.</p></div></div><ReactECharts style={{ height: 360 }} option={{ tooltip: { trigger: "axis" }, legend: { data: ["LO Gate-Out Demand (KL)", "Available MT Capacity (KL)"] }, grid: { left: 55, right: 25, bottom: 55 }, xAxis: { type: "category", data: labels }, yAxis: { type: "value", name: "KL" }, series: [{ name: "LO Gate-Out Demand (KL)", type: "bar", data: data.buckets.map((row: Json) => ({ value: row.demand_kl, lo_count: row.lo_count, trip_count: row.trip_count })), itemStyle: { color: "#0b73bf" } }, { name: "Available MT Capacity (KL)", type: "line", smooth: true, data: data.buckets.map((row: Json) => ({ value: row.available_capacity_kl, mt_count: row.available_mt_count })), lineStyle: { color: "#77b82a", width: 3 } }] }} /></section>
      <section className="phase8-card"><div className="phase8-section-head"><div><h3>Capacity Gap</h3><p>Available capacity minus gate-out demand. Negative is a shortage indicator, not definitive infeasibility.</p></div></div><ReactECharts style={{ height: 360 }} option={{ tooltip: { trigger: "axis" }, grid: { left: 55, right: 25, bottom: 55 }, xAxis: { type: "category", data: labels }, yAxis: { type: "value", name: "KL" }, series: [{ type: "bar", data: data.buckets.map((row: Json) => ({ value: row.capacity_gap_kl, itemStyle: { color: row.capacity_gap_kl < 0 ? "#ea4a43" : "#b8d211" } })) }] }} /></section></div>
    <section className="phase8-card"><div className="phase8-section-head"><div><h3>MT Movement Gantt</h3><p>Actual timestamps: AVAILABLE_AT_DEPOT and TRIP. Click a trip to open it in Trip Management.</p></div><div className="phase8-gantt-filters"><div className="phase8-search-line"><Search size={15} /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search MT" /></div><label><input type="checkbox" checked={activeOnly} onChange={(event) => onActiveOnly(event.target.checked)} /> Active MT only</label></div></div><div className="phase8-gantt-legend"><span><i className="is-available" /> Available at depot</span><span><i className="is-trip" /> Trip</span></div><div className="phase8-gantt-scroll"><div className="phase8-gantt-hours">{[0, 4, 8, 12, 16, 20, 24].map((hour) => <span key={hour} style={{ left: `${hour / 24 * 100}%` }}>{String(hour).padStart(2, "0")}:00</span>)}</div>{rows.map((row: Json) => <div className="phase8-gantt-row" key={row.vehicle_id}><div><strong>{row.vehicle_registration}</strong><span>{row.capacity_kl} KL</span></div><div className="phase8-gantt-track">{row.segments.filter((segment: Json) => segment.end).map((segment: Json, index: number) => { const start = Math.max(windowStart, new Date(segment.start).getTime()); const end = Math.min(windowEnd, new Date(segment.end).getTime()); const left = Math.max(0, (start - windowStart) / (windowEnd - windowStart) * 100); const width = Math.max(0.25, (end - start) / (windowEnd - windowStart) * 100); return <button key={`${segment.type}-${index}`} className={segment.type === "TRIP" ? "is-trip" : "is-available"} style={{ left: `${left}%`, width: `${width}%` }} title={segment.type === "TRIP" ? `${row.vehicle_registration} Trip ${segment.trip_sequence}\n${formatTime(segment.start)}–${formatTime(segment.end)}\n${segment.lo_count} LO · ${segment.volume_kl} KL · ${durationLabel(segment.duration_seconds)}` : `Available ${formatTime(segment.start)}–${formatTime(segment.end)}`} onClick={() => segment.trip_id && onOpenTrip(row.vehicle_id, segment.trip_id)}>{segment.type === "TRIP" && `T${segment.trip_sequence}`}</button>; })}</div></div>)}</div></section>
  </div>;
}


function DashboardTab({ data, onRemaining }: { data: Json | null; onRemaining: (type: string, name: string) => void }) {
  if (!data) return <div className="phase8-loading"><Loader2 className="animate-spin" /> Building daily distribution dashboard…</div>;
  const hourly = data.hourly_gate_out;
  return <div className="phase8-tab-stack"><div className="phase8-kpi-grid is-dashboard">{Object.entries(data.kpis).map(([key, value]) => <div className="phase8-kpi" key={key}><span>{key.replace(/_/g, " ")}</span><strong>{String(value ?? "-")}</strong></div>)}</div><div className="phase8-chart-grid"><section className="phase8-card"><div className="phase8-section-head"><div><h3>Planned Gate-Out Volume by Hour</h3><p>Current manual dispatch departure timing, measured in KL.</p></div></div><ReactECharts style={{ height: 330 }} option={{ tooltip: { trigger: "axis" }, xAxis: { type: "category", data: hourly.map((row: Json) => row.label.slice(0, 5)) }, yAxis: { type: "value", name: "KL" }, series: [{ type: "bar", data: hourly.map((row: Json) => row.demand_kl), itemStyle: { color: "#0b73bf" } }] }} /></section><section className="phase8-card"><div className="phase8-section-head"><div><h3>Cumulative Planned Distribution</h3><p>Cumulative assigned volume with total demand target.</p></div></div><ReactECharts style={{ height: 330 }} option={{ tooltip: { trigger: "axis" }, legend: { data: ["Cumulative Assigned", "Demand Target"] }, xAxis: { type: "category", data: data.cumulative_distribution.map((row: Json) => row.label.slice(0, 5)) }, yAxis: { type: "value", name: "KL" }, series: [{ name: "Cumulative Assigned", type: "line", areaStyle: {}, data: data.cumulative_distribution.map((row: Json) => row.cumulative_assigned_kl), itemStyle: { color: "#77b82a" } }, { name: "Demand Target", type: "line", symbol: "none", data: data.cumulative_distribution.map((row: Json) => row.total_demand_kl), lineStyle: { type: "dashed", color: "#ea4a43" } }] }} /></section></div>
    <DistributionTable title="Distribution by Saved Shift" rows={data.distribution_by_shift} first="Shift" />
    <DistributionTable title="Distribution by Saved Cluster" rows={data.distribution_by_cluster} first="Cluster" />
    <section className="phase8-card"><div className="phase8-section-head"><div><h3>Fleet Utilization</h3><p>Time utilization = active trip time / available operating window. Volume utilization is named separately.</p></div></div><div className="phase8-table-wrap"><table className="phase8-table"><thead><tr>{["MT", "Class", "Capacity", "Trips", "Assigned KL", "First Departure", "Last Return", "Active", "Idle", "Time Utilization", "Volume Capacity Utilization"].map((head) => <th key={head}>{head}</th>)}</tr></thead><tbody>{data.fleet_utilization.rows.map((row: Json) => <tr key={row.vehicle_id}><td><strong>{row.vehicle_registration}</strong><small>{row.mt_id}</small></td><td>{row.vehicle_class || "-"}</td><td>{row.capacity_kl} KL</td><td>{row.trips}</td><td>{row.assigned_volume_kl}</td><td>{formatDateTime(row.first_departure)}</td><td>{formatDateTime(row.last_return)}</td><td>{durationLabel(row.active_time_seconds)}</td><td>{durationLabel(row.idle_time_seconds)}</td><td>{row.utilization_time_pct}%</td><td>{row.volume_capacity_utilization_pct}%</td></tr>)}</tbody></table></div></section>
    <section className="phase8-card"><div className="phase8-section-head"><div><h3>Remaining / Unassigned Demand</h3><p>Click a segment to open the filtered Unassigned LO panel.</p></div><div className="phase8-mini-kpis"><div><strong>{data.remaining_demand.unassigned_lo}</strong><span>LO</span></div><div><strong>{data.remaining_demand.unassigned_volume_kl}</strong><span>KL</span></div><div><strong>{data.remaining_demand.affected_spbu}</strong><span>SPBU</span></div></div></div><div className="phase8-remaining-grid">{[["shift", "By Shift", data.remaining_demand.by_shift], ["cluster", "By Cluster", data.remaining_demand.by_cluster], ["product", "By Product", data.remaining_demand.by_product], ["spbu", "By SPBU", data.remaining_demand.by_spbu]].map(([type, label, rows]: any[]) => <div key={type}><h4>{label}</h4>{rows.map((row: Json) => <button key={row.name} onClick={() => onRemaining(type, row.name)}><span>{row.name}</span><strong>{row.volume_kl} KL · {row.lo_count} LO</strong></button>)}</div>)}</div></section>
  </div>;
}


function GeographicMapTab({ vehicles, search, selectedVehicleId, data, loading, error, onSearch, onSelect }: { vehicles: Json[]; search: string; selectedVehicleId: string; data: Json | null; loading: boolean; error: string; onSearch: (value: string) => void; onSelect: (value: string) => void }) {
  const colors = ["#0b73bf", "#ea4a43", "#77b82a", "#7c3aed", "#0f766e", "#b45309"];
  const depotPosition = data ? validMapPoint(data.depot?.latitude, data.depot?.longitude) : null;
  const mappedTrips = (data?.trips || []).map((trip: Json, index: number) => ({
    trip,
    color: colors[index % colors.length],
    positions: (trip.route_geometry || []).map((point: Json) => validMapPoint(point.latitude, point.longitude)).filter(Boolean) as [number, number][],
  }));
  const bounds = [
    ...(depotPosition ? [depotPosition] : []),
    ...mappedTrips.flatMap((row: Json) => row.positions),
    ...(data?.trips || []).flatMap((trip: Json) => (trip.stops || []).map((stop: Json) => validMapPoint(stop.latitude, stop.longitude)).filter(Boolean)),
  ] as [number, number][];
  const selectedLabel = data?.vehicle?.vehicle_registration || data?.vehicle?.mt_id || "selected MT";

  return <section className="phase8-card phase8-map-card">
    <div className="phase8-section-head"><div><h3>Geographic Route Map</h3><p>Select one MT. Every solid route uses Google Routes road geometry for Depot → ordered SPBU stops → Depot.</p></div><div className="phase8-map-controls"><div className="phase8-search-line"><Search size={15} /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search MT number or ID" /></div><select value={selectedVehicleId} onChange={(event) => onSelect(event.target.value)}><option value="">Select No. MT</option>{vehicles.map((vehicle: Json) => <option key={vehicle.id} value={vehicle.id}>{vehicle.vehicle_registration || vehicle.mt_id} · {vehicle.trip_count} trip</option>)}</select></div></div>
    {!selectedVehicleId && <div className="phase8-empty">Search and select an MT to load its road-following routes.</div>}
    {selectedVehicleId && loading && <div className="phase8-loading"><Loader2 className="animate-spin" /> Loading Google road geometry for {selectedLabel}…</div>}
    {error && <div className="phase8-alert is-bad"><AlertTriangle size={17} />{error}</div>}
    {data && !loading && <>
      <div className={data.status === "READY" ? "phase8-alert is-good" : "phase8-alert is-warning"}><MapPinned size={17} /><span>{data.road_geometry_trip_count}/{data.trip_count} trip mengikuti jalan Google · {data.stored_google_geometry_count} geometry snapshot · {data.historical_google_geometry_count || 0} geometry historis · {data.live_google_requests} request Google baru.</span></div>
      {(data.errors || []).map((row: Json, index: number) => <div className="phase8-alert is-warning" key={`${row.trip_id}-${row.code}-${index}`}><AlertTriangle size={16} /><span>Trip {data.trips.find((trip: Json) => trip.trip_id === row.trip_id)?.trip_sequence || "-"}: {row.message}</span></div>)}
      {!mappedTrips.some((row: Json) => row.positions.length > 1) ? <div className="phase8-empty">No Google road geometry is available for this MT. Review the Google Routes configuration and Apply status of its trips.</div> : <div className="phase8-map-grid">
        <div className="phase8-map-shell"><MapContainer key={`${data.job_id}-${data.vehicle.id}`} center={depotPosition || [-6.2, 106.8]} zoom={9} scrollWheelZoom preferCanvas className="phase8-map"><TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" updateWhenIdle keepBuffer={2} /><FitPhase8MapBounds positions={bounds} scopeKey={`${data.job_id}-${data.vehicle.id}-${data.road_geometry_trip_count}`} />{depotPosition && <CircleMarker center={depotPosition} radius={9} pathOptions={{ color: "#15385b", fillColor: "#fff", fillOpacity: 1, weight: 3 }}><Popup><strong>{data.depot.depot_name}</strong><br />Depot start and return</Popup></CircleMarker>}{mappedTrips.map(({ trip, positions, color }: Json) => <Fragment key={trip.trip_id}>{positions.length > 1 && <Polyline positions={positions} smoothFactor={1.2} pathOptions={{ color, weight: 5, opacity: 0.88 }} />}{(trip.stops || []).map((stop: Json) => { const point = validMapPoint(stop.latitude, stop.longitude); return point ? <CircleMarker key={`${trip.trip_id}-${stop.sequence}`} center={point} radius={7} pathOptions={{ color, fillColor: color, fillOpacity: .92, weight: 2 }}><Popup><strong>{selectedLabel} · Trip {trip.trip_sequence}</strong><br />Stop {stop.sequence} · {stop.spbu_number || stop.spbu_id}<br />{stop.spbu_name || ""}<br />LO {stop.loading_order_ids.join(", ")}<br />ETA {formatDateTime(stop.estimated_arrival_datetime)}</Popup></CircleMarker> : null; })}</Fragment>)}</MapContainer></div>
        <div className="phase8-map-legend">{mappedTrips.map(({ trip, color, positions }: Json) => <article key={trip.trip_id} style={{ borderLeftColor: color }}><strong>{selectedLabel} · Trip {trip.trip_sequence}</strong><span>{(trip.stops || []).map((stop: Json) => `${stop.sequence}. ${stop.spbu_number || stop.spbu_id}`).join(" → ") || "No SPBU stop"}</span><small>{trip.distance_meter ? `${(trip.distance_meter / 1000).toFixed(1)} km · ` : ""}{trip.geometry_status.replace(/_/g, " ")} · {positions.length} geometry points</small></article>)}</div>
      </div>}
    </>}
  </section>;
}


function DistributionTable({ title, rows, first }: { title: string; rows: Json[]; first: string }) {
  return <section className="phase8-card"><div className="phase8-section-head"><div><h3>{title}</h3><p>Definitions are copied from the selected prediction/model context; no fixed shift or cluster set is invented.</p></div></div><div className="phase8-table-wrap"><table className="phase8-table"><thead><tr>{[first, "Required / Total KL", "Assigned KL", "Unassigned KL", "Gap KL", "LO", "SPBU", "Trips"].map((head) => <th key={head}>{head}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td><strong>{row.name}</strong></td><td>{row.required_volume_kl ?? row.total_volume_kl}</td><td>{row.assigned_volume_kl}</td><td>{row.unassigned_volume_kl}</td><td>{row.gap_kl}</td><td>{row.lo_count}</td><td>{row.spbu_count}</td><td>{row.trips}</td></tr>)}</tbody></table></div></section>;
}


function AuditTab({ data }: { data: Json | null }) {
  if (!data) return <div className="phase8-loading"><Loader2 className="animate-spin" /> Loading audit history…</div>;
  return <section className="phase8-card"><div className="phase8-section-head"><div><h3>Human-readable Dispatch Audit</h3><p>{data.total} immutable events across job, route, trip, LO, availability, version, and finalization changes.</p></div></div><div className="phase8-audit-list">{data.rows.map((row: Json) => <article key={row.id}><div className="phase8-audit-time"><strong>{formatTime(row.timestamp)}</strong><span>{formatDateTime(row.timestamp)}</span></div><div><span className="phase8-overline">{row.action.replace(/_/g, " ")} · {row.entity_type}</span><h4>{row.summary}</h4>{row.reason && <p>Reason: {row.reason}</p>}<details><summary>Evidence</summary><pre>{JSON.stringify({ previous: row.previous_value, next: row.new_value, metadata: row.metadata }, null, 2)}</pre></details></div></article>)}</div></section>;
}
