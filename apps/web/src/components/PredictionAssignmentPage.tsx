import ReactECharts from "echarts-for-react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronRight, Database, Download, Eye, FileCheck2, Pencil, Play, Plus, RefreshCw, Sparkles, Split, Trash2, Upload, XCircle } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { apiFile, apiForm, apiGet, apiSend, downloadFormFromApi, downloadFromApi } from "../lib/api";

import UnassignedShipmentDialog from "./UnassignedShipmentDialog";

type Depot = { depot_id: string; depot_name: string };
type Product = { product_id: string; product_name: string; active_status?: string };
type MasterSpbuOption = {
  spbu_id: string;
  spbu_code: string;
  spbu_name: string | null;
  primary_depot_id: string | null;
  active_status: string;
};
type MasterMtOption = {
  mt_id: string;
  vehicle_registration: string | null;
  capacity_label: string | null;
  vehicle_type_tag: number | null;
  number_of_compartments: number | null;
  depot_id: string | null;
  active_status: string;
  phase6_eligible: boolean;
  phase6_failed_rules: string[];
};
type ShiftDefinition = {
  shift_id: string;
  name: string;
  order?: number;
  start_time: string;
  end_time: string;
};
type Model = {
  model_id: string;
  model_name: string;
  model_version: number;
  depot_id: string;
  depot_name: string;
  training_start_date: string;
  training_end_date: string;
  created_at: string | null;
  algorithm: string;
  algorithm_version: string;
  number_of_training_shipments: number;
  number_of_spbu: number;
  number_of_clusters: number;
  model_quality_metrics: Record<string, number>;
  model_status: string;
  shift_definition_snapshot: ShiftDefinition[];
};
type ValidationIssue = { file: string; row: number; field: string; status: string; error_code: string; description: string };
type Validation = {
  file_type: string;
  status: "PASS" | "WARNING" | "ERROR";
  blocking_error_count: number;
  warning_count: number;
  issues: ValidationIssue[];
  normalized_rows: Array<Record<string, string | number | null>>;
  editable_rows?: Array<Record<string, string | number | null>>;
  row_count: number;
  detected_shifts: string[];
};
type Candidate = {
  id: string;
  vehicle_id: string;
  vehicle_registration_no: string;
  prediction_score: number;
  compatibility_status: string;
  candidate_rank: number | null;
  exclusion_reason: string | null;
  explanation: Record<string, unknown>;
  capacity_kl: number | null;
  number_of_compartments: number | null;
};
type Trip = {
  id: string;
  trip_id: string;
  trip_number: number | null;
  vehicle_id: string | null;
  vehicle_registration_no: string | null;
  planned_start_datetime: string;
  predicted_departure_datetime: string | null;
  delay_minutes: number;
  estimated_visit_sequence: string[];
  routing_provider: string | null;
  routing_mode: string | null;
  routing_preference: string | null;
  large_vehicle_used: boolean;
  route_distance_meters: number | null;
  route_duration_seconds: number | null;
  service_duration_seconds: number | null;
  turnaround_buffer_seconds: number | null;
  total_cycle_duration_seconds: number | null;
  estimated_return_datetime: string | null;
  next_available_datetime: string | null;
  routing_confidence: string | null;
  route_estimation_source: string | null;
  assignment_status: string;
  unassigned_reason: string | null;
  fallback_used: boolean;
  warning_codes: string[];
  vehicle_profile_snapshot: { profile_status?: string; missing_fields?: string[] };
};
type Shipment = {
  id: string;
  predicted_shipment_id: string;
  shift_id: string;
  shift: string;
  planned_start_datetime: string;
  shipment_prediction_score: number;
  shipment_confidence_level: string;
  low_confidence: boolean;
  is_manual_override: boolean;
  explanation: Record<string, unknown>;
  total_order_kl: number;
  required_compartments: number;
  compartment_unit_kl: number;
  lines: Array<{
    id: string;
    loading_order_no: string;
    shipment_start_datetime: string;
    spbu_id: string;
    spbu_no: string;
    spbu_name: string | null;
    product_id: string | null;
    product_name: string | null;
    cluster_id: number | null;
    cluster_number: number | null;
    cluster_label: string | null;
    order_quantity_kl: number | null;
    model_predicted_shipment_id: string;
  }>;
  assignment: {
    id: string | null;
    original_vehicle_id: string | null;
    original_prediction_score: number | null;
    assigned_vehicle_id: string | null;
    assigned_vehicle_registration: string | null;
    assigned_vehicle_capacity_kl: number | null;
    assigned_vehicle_compartments: number | null;
    mt_assignment_score: number | null;
    assignment_status: string;
    unassigned_reason: string | null;
    override_reason: string | null;
  };
  trip: Trip | null;
  candidates: Candidate[];
  candidates_loaded: boolean;
};
type HourlyDistribution = {
  hour_start: string;
  timezone: string;
  delivered_kl: number;
  cumulative_kl: number;
  shipment_count: number;
  loading_order_count: number;
};
type CapacityIteration = {
  tier_compartments: number;
  tier_capacity_kl: number;
  loading_orders_considered: number;
  candidate_shipments: number;
  assigned_shipments: number;
  assigned_loading_orders: number;
  carried_forward_loading_orders: number;
};
type GeographicRoutePoint = {
  type: "DEPOT" | "SPBU" | "DEPOT_RETURN";
  code: string;
  name: string;
  sequence?: number;
  latitude: number;
  longitude: number;
};
type GeographicGeometryPoint = { latitude: number; longitude: number };
type GeographicRoute = {
  trip_id: string;
  trip_number: number | null;
  shipment_id: string;
  vehicle_id: string;
  vehicle_registration_no: string;
  predicted_departure_datetime: string;
  total_order_kl: number;
  stops: Array<{
    sequence: number;
    spbu_id: string;
    spbu_code: string;
    spbu_name: string;
    distance_from_depot_meters: number | null;
    latitude: number | null;
    longitude: number | null;
  }>;
  points: GeographicRoutePoint[];
  route_geometry: GeographicGeometryPoint[];
  route_geometry_source: "GOOGLE_ROUTES_GEOJSON" | "MASTER_COORDINATE_FALLBACK" | "MIXED_GEOMETRY" | null;
  original_geometry_point_count: number;
  uses_road_geometry: boolean;
  missing_coordinate_count: number;
  mappable: boolean;
};
type GeographicRoutes = {
  sequence_policy: "NEAREST_TO_FARTHEST_FROM_DEPOT";
  geometry_source: "GOOGLE_ROUTES_WITH_MASTER_FALLBACK";
  marker_coordinate_source: "MASTER_DEPOT_AND_SPBU";
  depot: {
    depot_id: string | null;
    depot_code: string | null;
    depot_name: string | null;
    latitude: number | null;
    longitude: number | null;
  };
  routes: GeographicRoute[];
};
type RouteGeometryRefresh = {
  geographic_routes: GeographicRoutes;
  refreshed_trip_count: number;
  road_geometry_trip_count: number;
  geometry_error_codes?: string[];
};
type PredictionResult = {
  id: string;
  prediction_run_id: string;
  status: string;
  error_code: string | null;
  error_message: string | null;
  depot: string;
  model: Record<string, unknown>;
  created_at: string;
  created_by: string;
  parameters: Record<string, unknown>;
  validation: ValidationIssue[];
  durations_ms: Record<string, number>;
  summary: {
    loading_orders: number;
    total_order_kl: number;
    unique_spbu: number;
    predicted_shipments: number;
    available_mt: number;
    assigned_shipments: number;
    assigned_loading_orders: number;
    assigned_order_kl: number;
    unassigned_shipments: number;
    total_trips: number;
    assigned_with_delay: number;
    multi_trip_mt: number;
    fallback_trips: number;
    average_shipment_confidence: number;
    average_mt_assignment_confidence: number;
  };
  summary_by_shift: Array<Record<string, string | number>>;
  shipment_pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
    shift_id: string | null;
  };
  shipment_options: Array<{
    id: string;
    predicted_shipment_id: string;
    shift_id: string;
    shift: string;
    spbus: Array<{
      spbu_id: string;
      spbu_no: string;
      cluster_id: number | null;
      cluster_number: number | null;
      cluster_label: string | null;
    }>;
  }>;
  shipments: Shipment[];
  trips: Trip[];
  hourly_distribution: HourlyDistribution[];
  geographic_routes: GeographicRoutes;
  mt_timeline: Array<{ vehicle_id: string; vehicle_registration_no: string; trips: Array<{ trip_id: string; trip_number: number; shipment_id: string; start: string; return: string; next_available: string; status: string }> }>;
  routing_configuration: Record<string, unknown>;
  routing_metrics: Record<string, number>;
  original_model_prediction: Array<Record<string, unknown>>;
};
type PredictionTask = {
  id: string;
  prediction_run_id: string;
  status: "QUEUED";
  message: string;
};
type ActivePredictionTask = { id: string; predictionRunId: string; depotId: string };
type ShipmentCandidatesResponse = { shipment_id: string; predicted_shipment_id: string; candidates: Candidate[] };
type PredictionRunStatus = {
  id: string;
  prediction_run_id: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
  created_at: string;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  queue: {
    attempt_count: number;
    max_attempts: number;
    worker_id: string | null;
    heartbeat_at: string | null;
    lease_expires_at: string | null;
    last_error: string | null;
  };
  durations_ms: Record<string, number>;
};
type HistoryRow = {
  id: string;
  prediction_run_id: string;
  date: string;
  depot_id: string;
  depot: string;
  model: string;
  loading_orders: number;
  shipments: number;
  assigned: number;
  unassigned: number;
  user: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  heartbeat_at: string | null;
  queue_error: string | null;
};
type ManagedLoadingOrder = {
  shift: string;
  id: string;
  loading_order_no: string;
  shipment_start_datetime: string;
  spbu_no: string;
  product: string;
  order_quantity_kl: string;
};
type LoadingOrderSortField = Exclude<keyof ManagedLoadingOrder, "id">;
type LoadingOrderFilters = Record<LoadingOrderSortField, string>;
type LoadingOrderEditor = { mode: "ADD" | "EDIT"; row: ManagedLoadingOrder };
type ManagedMtAvailability = {
  id: string;
  vehicle_registration_no: string;
  mt_tag_class: string;
  status: "ACTIVE" | "DEACTIVE";
  eta_on_depot: string;
  eligibility_issues: string[];
};

const EMPTY_LOADING_ORDER_FILTERS: LoadingOrderFilters = {
  loading_order_no: "",
  shift: "",
  shipment_start_datetime: "",
  spbu_no: "",
  product: "",
  order_quantity_kl: "",
};
const LOADING_ORDER_MANAGEMENT_COLUMNS: Array<{ field: LoadingOrderSortField; label: string; filterLabel: string; placeholder: string }> = [
  { field: "loading_order_no", label: "Loading Order No", filterLabel: "Filter nomor LO", placeholder: "Cari nomor LO…" },
  { field: "shipment_start_datetime", label: "Shipment Start", filterLabel: "Filter waktu shipment", placeholder: "Cari tanggal/jam…" },
  { field: "shift", label: "Shift", filterLabel: "Filter shift", placeholder: "Cari shift" },
  { field: "spbu_no", label: "SPBU No", filterLabel: "Filter nomor SPBU", placeholder: "Cari SPBU…" },
  { field: "product", label: "Product", filterLabel: "Filter product", placeholder: "Cari product…" },
  { field: "order_quantity_kl", label: "Order (KL)", filterLabel: "Filter order KL", placeholder: "Cari KL…" },
];

function loadingOrderDateTimeInput(value: string | number | null | undefined) {
  const text = String(value ?? "").trim();
  const isoMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (isoMatch) return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}T${isoMatch[4]}:${isoMatch[5]}`;
  const localMatch = text.match(/^(\d{2})\/(\d{2})\/(\d{4})[ T](\d{2}):(\d{2})/);
  if (localMatch) return `${localMatch[3]}-${localMatch[2]}-${localMatch[1]}T${localMatch[4]}:${localMatch[5]}`;
  return "";
}

function managedLoadingOrdersFromValidation(validation: Validation): ManagedLoadingOrder[] {
  const rows = validation.editable_rows?.length ? validation.editable_rows : validation.normalized_rows;
  const normalizedBySourceRow = new Map(validation.normalized_rows.map((row) => [Number(row.source_row_number), row]));
  return rows.map((row, index) => ({
    id: globalThis.crypto?.randomUUID?.() ?? `loading-order-${Date.now()}-${index}`,
    shift: String(row.shift ?? ""),
    loading_order_no: String(row.loading_order_no ?? ""),
    shipment_start_datetime: loadingOrderDateTimeInput(row.shipment_start_datetime_local ?? row.shipment_start_datetime),
    spbu_no: String(row.spbu_no ?? ""),
    product: String(normalizedBySourceRow.get(Number(row.source_row_number))?.product_name ?? row.product_name ?? row.product ?? ""),
    order_quantity_kl: String(row.order_quantity_kl ?? ""),
  }));
}

function loadingOrderWorkbookRows(rows: ManagedLoadingOrder[]) {
  return rows.map((row) => ({
    shift: row.shift.trim(),
    loading_order_no: row.loading_order_no.trim(),
    shipment_start_datetime: row.shipment_start_datetime.length === 16
      ? `${row.shipment_start_datetime.replace("T", " ")}:00`
      : row.shipment_start_datetime.replace("T", " "),
    spbu_no: row.spbu_no.trim(),
    product: row.product.trim(),
    order_quantity_kl: row.order_quantity_kl,
  }));
}

function managedMtWorkbookRows(rows: ManagedMtAvailability[]) {
  return rows
    .filter((row) => row.status === "ACTIVE")
    .map((row) => ({
      vehicle_registration_no: row.vehicle_registration_no,
      initial_available_datetime: row.eta_on_depot.length === 16
        ? `${row.eta_on_depot.replace("T", " ")}:00`
        : row.eta_on_depot.replace("T", " "),
    }));
}

function localTomorrowDate() {
  const value = new Date();
  value.setDate(value.getDate() + 1);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function defaultMtEta(model: Model | null, loadingOrderValidation: Validation | null) {
  const shifts = [...(model?.shift_definition_snapshot ?? [])].sort((left, right) => (left.order ?? 0) - (right.order ?? 0));
  const shiftOne = shifts.find((shift) => /(^|\D)1(\D|$)/.test(`${shift.shift_id} ${shift.name}`)) ?? shifts[0];
  const startTime = String(shiftOne?.start_time ?? "00:00").slice(0, 5);
  const loadingOrderDate = loadingOrderValidation?.normalized_rows
    .map((row) => String(row.shipment_start_datetime_local ?? row.shipment_start_datetime ?? "").match(/^(\d{4}-\d{2}-\d{2})/)?.[1])
    .find(Boolean);
  return `${loadingOrderDate ?? localTomorrowDate()}T${startTime}`;
}

function pct(value: number | null | undefined) {
  return value === null || value === undefined ? "-" : `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
}

function badgeClass(value: string) {
  if (["PASS", "HIGH", "ASSIGNED", "COMPLETED", "ACTIVE", "READY"].includes(value)) return "border-mint bg-mint/10 text-mint";
  if (["WARNING", "MEDIUM", "MANUAL_OVERRIDE", "ASSIGNED_WITH_DELAY", "SAVED", "ROUTE_FALLBACK", "QUEUED", "RUNNING"].includes(value)) return "border-amber bg-amber/10 text-amber";
  return "border-rust bg-rust/10 text-rust";
}

function Badge({ value }: { value: string }) {
  return <span className={`inline-flex border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide ${badgeClass(value)}`}>{value.replace(/_/g, " ")}</span>;
}

function ExcludedCandidateDropdown({ candidates }: { candidates: Candidate[] }) {
  const excludedCandidates = candidates.filter((candidate) => candidate.compatibility_status === "FAIL");
  if (excludedCandidates.length === 0) return null;
  return (
    <details className="group mt-4 border border-rust/30 bg-rust/5">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-rust [&::-webkit-details-marker]:hidden">
        <span>Excluded Candidate</span>
        <span className="flex items-center gap-2">
          <span className="border border-rust/30 bg-white px-2 py-1 text-[11px] tabular-nums">{excludedCandidates.length}</span>
          <ChevronDown className="transition-transform group-open:rotate-180" size={15} aria-hidden="true" />
        </span>
      </summary>
      <div className="max-h-72 space-y-2 overflow-y-auto border-t border-rust/20 p-3">
        {excludedCandidates.map((candidate) => <div key={candidate.id} className="border border-rust/30 bg-white p-2 text-xs"><span className="font-medium">{candidate.vehicle_registration_no}</span> · {candidate.exclusion_reason}</div>)}
      </div>
    </details>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border border-line bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-petroink">{value}</div>
    </div>
  );
}

function explanationRows(value: Record<string, unknown>) {
  return Object.entries(value).filter(([, item]) => item !== null && item !== undefined && typeof item !== "object");
}

function dateTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("id-ID") : "—";
}

function clusterText(item: { cluster_number: number | null; cluster_label: string | null }) {
  if (item.cluster_number !== null) return `Cluster ${item.cluster_number}`;
  return item.cluster_label?.trim() || "Cluster —";
}

function spbuClusterText(lines: Array<{
  spbu_id: string;
  spbu_no: string;
  cluster_number: number | null;
  cluster_label: string | null;
}>) {
  const uniqueSpbus = [...new Map(lines.map((line) => [line.spbu_id, line])).values()];
  return uniqueSpbus.map((line) => `SPBU ${line.spbu_no} · ${clusterText(line)}`).join(" → ");
}

function durationMinutes(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${Math.round(value / 60).toLocaleString("id-ID")} min`;
}

const ROUTE_COLORS = ["#0b73bf", "#b45309", "#15803d", "#7e22ce", "#be123c", "#0369a1", "#4d7c0f", "#c2410c"];

function FitRouteBounds({ routes }: { routes: GeographicRoute[] }) {
  const map = useMap();
  useEffect(() => {
    const bounds = routes.flatMap((route) => route.points
      .filter((point) => point.type !== "DEPOT_RETURN")
      .map((point) => [point.latitude, point.longitude] as [number, number]));
    if (bounds.length > 0) map.fitBounds(bounds, { padding: [28, 28], maxZoom: 12 });
  }, [map, routes]);
  return null;
}

function GeographicMTRouteMap({ payload, runId }: { payload: GeographicRoutes; runId: string }) {
  const [displayPayload, setDisplayPayload] = useState(payload);
  const [routeLoadingVehicle, setRouteLoadingVehicle] = useState<string | null>(null);
  const [requestedVehicles, setRequestedVehicles] = useState<Set<string>>(() => new Set());
  const [routeFeedback, setRouteFeedback] = useState<{ status: "SUCCESS" | "WARNING" | "ERROR"; message: string } | null>(null);
  const [vehicleSearch, setVehicleSearch] = useState("");
  useEffect(() => {
    setDisplayPayload(payload);
    setRequestedVehicles(new Set());
    setRouteFeedback(null);
    setVehicleSearch("");
  }, [payload, runId]);
  const vehicleOptions = useMemo(
    () => [...new Map(displayPayload.routes.filter((route) => route.mappable).map((route) => [route.vehicle_id, route.vehicle_registration_no || route.vehicle_id])).entries()],
    [displayPayload.routes],
  );
  const filteredVehicleOptions = useMemo(() => {
    const query = vehicleSearch.trim().toLocaleUpperCase("id-ID");
    if (!query) return vehicleOptions;
    return vehicleOptions.filter(([vehicleId, registration]) =>
      vehicleId.toLocaleUpperCase("id-ID").includes(query)
      || registration.toLocaleUpperCase("id-ID").includes(query));
  }, [vehicleOptions, vehicleSearch]);
  const [selectedVehicle, setSelectedVehicle] = useState(vehicleOptions[0]?.[0] ?? "ALL");
  useEffect(() => {
    if (selectedVehicle !== "ALL" && !vehicleOptions.some(([vehicleId]) => vehicleId === selectedVehicle)) {
      setSelectedVehicle(vehicleOptions[0]?.[0] ?? "ALL");
    }
  }, [selectedVehicle, vehicleOptions]);
  useEffect(() => {
    if (selectedVehicle !== "ALL" && !filteredVehicleOptions.some(([vehicleId]) => vehicleId === selectedVehicle)) {
      setSelectedVehicle("ALL");
    }
  }, [filteredVehicleOptions, selectedVehicle]);
  const visibleRoutes = useMemo(
    () => displayPayload.routes.filter((route) => route.mappable && (selectedVehicle === "ALL" || route.vehicle_id === selectedVehicle)),
    [displayPayload.routes, selectedVehicle],
  );
  const mappedStops = useMemo(() => [...new Map(visibleRoutes.flatMap((route) => route.points
    .filter((point) => point.type === "SPBU")
    .map((point) => [point.code, { ...point, vehicleId: route.vehicle_id, tripId: route.trip_id }]))).values()], [visibleRoutes]);
  const roadRouteCount = visibleRoutes.filter((route) => route.uses_road_geometry).length;
  const missingCoordinateCount = visibleRoutes.reduce((total, route) => total + route.missing_coordinate_count, 0);
  const vehicleColor = (vehicleId: string) => {
    const index = Math.max(0, vehicleOptions.findIndex(([id]) => id === vehicleId));
    return ROUTE_COLORS[index % ROUTE_COLORS.length];
  };
  const defaultCenter: [number, number] = displayPayload.depot.latitude !== null && displayPayload.depot.longitude !== null
    ? [displayPayload.depot.latitude, displayPayload.depot.longitude]
    : visibleRoutes[0]?.points[0]
      ? [visibleRoutes[0].points[0].latitude, visibleRoutes[0].points[0].longitude]
      : [3.5952, 98.6722];

  async function loadRoadGeometry(vehicleId: string) {
    if (vehicleId === "ALL" || routeLoadingVehicle) return;
    setRouteLoadingVehicle(vehicleId);
    setRequestedVehicles((current) => new Set(current).add(vehicleId));
    setRouteFeedback(null);
    try {
      const response = await apiSend<RouteGeometryRefresh>(`/api/v1/phase6/predictions/${runId}/route-geometry`, "POST", { vehicle_id: vehicleId });
      setDisplayPayload((current) => {
        const refreshedByTrip = new Map(response.geographic_routes.routes.map((route) => [route.trip_id, route]));
        return {
          ...current,
          routes: current.routes.map((route) => refreshedByTrip.get(route.trip_id) ?? route),
        };
      });
      setRouteFeedback(response.road_geometry_trip_count > 0
        ? { status: "SUCCESS", message: `${response.road_geometry_trip_count} trip memakai geometri jalan Google Routes.` }
        : { status: "WARNING", message: `Google Routes tidak menghasilkan geometri jalan. Penyebab: ${response.geometry_error_codes?.length ? response.geometry_error_codes.join(", ") : response.geometry_error_codes === undefined ? "Backend belum mengirim diagnostik; restart atau rebuild API ke versi terbaru" : "Geometri lengkap seluruh ruas trip belum tersedia"}. Garis fallback ditampilkan putus-putus.` });
    } catch (reason) {
      setRouteFeedback({ status: "ERROR", message: reason instanceof Error ? reason.message : "Geometri jalan gagal dimuat." });
    } finally {
      setRouteLoadingVehicle(null);
    }
  }

  useEffect(() => {
    if (selectedVehicle === "ALL" || requestedVehicles.has(selectedVehicle) || routeLoadingVehicle) return;
    if (visibleRoutes.some((route) => !route.uses_road_geometry)) void loadRoadGeometry(selectedVehicle);
  }, [requestedVehicles, routeLoadingVehicle, selectedVehicle, visibleRoutes]);

  return (
    <div className="border border-line bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">10B. Geographic Route per MT</div>
          <p className="mt-1 max-w-4xl text-xs text-slate-500">Marker memakai Master Depot dan Master SPBU latitude/longitude yang sama dengan Geographic Cluster Map Fase 5. Garis solid memakai geometri jalan Google Routes; marker tetap berada di koordinat master meskipun Google melakukan road snapping.</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <label htmlFor={`geographic-mt-search-${runId}`}>Cari No. MT</label>
            <input
              id={`geographic-mt-search-${runId}`}
              type="search"
              className="min-w-52 border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink placeholder:text-slate-400"
              placeholder="Ketik nomor MT…"
              value={vehicleSearch}
              onChange={(event) => setVehicleSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && filteredVehicleOptions.length > 0) {
                  event.preventDefault();
                  setSelectedVehicle(filteredVehicleOptions[0][0]);
                }
              }}
            />
            <span className="font-normal normal-case tracking-normal text-slate-400">{filteredVehicleOptions.length.toLocaleString("id-ID")} dari {vehicleOptions.length.toLocaleString("id-ID")} MT</span>
          </div>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Tampilkan MT
            <select className="min-w-52 border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={selectedVehicle} onChange={(event) => setSelectedVehicle(event.target.value)}>
              <option value="ALL">Semua MT ({vehicleOptions.length})</option>
              {filteredVehicleOptions.map(([vehicleId, registration]) => <option key={vehicleId} value={vehicleId}>{registration}</option>)}
              {filteredVehicleOptions.length === 0 && <option value="NO_RESULT" disabled>MT tidak ditemukan</option>}
            </select>
          </label>
          <button className="inline-flex items-center gap-2 border border-petroblue px-3 py-2 text-sm text-petroblue disabled:cursor-wait disabled:opacity-40" disabled={selectedVehicle === "ALL" || routeLoadingVehicle !== null} onClick={() => void loadRoadGeometry(selectedVehicle)}><RefreshCw className={routeLoadingVehicle ? "animate-spin" : ""} size={15} />{routeLoadingVehicle ? "Memuat jalan…" : "Perbarui rute jalan"}</button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500"><span>{mappedStops.length.toLocaleString("id-ID")} SPBU mapped</span><span>{missingCoordinateCount.toLocaleString("id-ID")} koordinat missing</span><span>{roadRouteCount.toLocaleString("id-ID")}/{visibleRoutes.length.toLocaleString("id-ID")} trip memakai jalan Google</span></div>
      {routeFeedback && <div className={`mt-3 border px-3 py-2 text-xs ${routeFeedback.status === "SUCCESS" ? "border-mint bg-mint/5 text-mint" : routeFeedback.status === "WARNING" ? "border-amber bg-amber/5 text-amber" : "border-rust bg-rust/5 text-rust"}`} role="status">{routeFeedback.message}</div>}
      {visibleRoutes.length > 0 ? (
        <>
          <div className="relative z-0 mt-4 overflow-hidden rounded-2xl border border-line" role="region" aria-label="Geographic MT route map using Master SPBU and Master Depot coordinates">
            <MapContainer center={defaultCenter} zoom={8} scrollWheelZoom preferCanvas className="h-[500px] w-full bg-slate-100">
              <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              <FitRouteBounds routes={visibleRoutes} />
              {visibleRoutes.map((route) => {
                const color = vehicleColor(route.vehicle_id);
                const geometry = route.route_geometry.length >= 2 ? route.route_geometry : route.points;
                const positions = geometry.map((point) => [point.latitude, point.longitude] as [number, number]);
                return (
                  <Polyline key={route.trip_id} positions={positions} pathOptions={{ color, weight: route.uses_road_geometry ? 5 : 3, opacity: 0.82, dashArray: route.uses_road_geometry ? undefined : "8 8" }}>
                    <Tooltip sticky>{route.vehicle_registration_no} · {route.trip_id}<br />{route.shipment_id} · {route.total_order_kl} KL<br />Berangkat {dateTime(route.predicted_departure_datetime)}<br />{route.uses_road_geometry ? "Google road geometry" : "Straight fallback — bukan rute jalan"}</Tooltip>
                  </Polyline>
                );
              })}
              {mappedStops.map((point) => (
                <CircleMarker key={point.code} center={[point.latitude, point.longitude]} radius={6} pathOptions={{ color: "#ffffff", fillColor: vehicleColor(point.vehicleId), fillOpacity: 0.88, weight: 1.5 }}>
                  <Tooltip direction="top" opacity={1}><div className="min-w-48 text-sm text-petroink"><div className="font-semibold">{point.name || point.code}</div><div className="text-xs text-slate-500">SPBU {point.code} · {point.tripId}</div><div className="mt-1">Master: {point.latitude.toFixed(5)}, {point.longitude.toFixed(5)}</div></div></Tooltip>
                  <Popup><strong>{point.name || point.code}</strong><br />SPBU {point.code}<br />Trip {point.tripId}<br />Master coordinate: {point.latitude.toFixed(5)}, {point.longitude.toFixed(5)}</Popup>
                </CircleMarker>
              ))}
              {displayPayload.depot.latitude !== null && displayPayload.depot.longitude !== null && (
                <CircleMarker center={[displayPayload.depot.latitude, displayPayload.depot.longitude]} radius={11} pathOptions={{ color: "#facc15", fillColor: "#0f2942", fillOpacity: 1, weight: 4 }}>
                  <Tooltip direction="top" opacity={1}><div className="min-w-48 text-sm text-petroink"><div className="font-semibold">Depot · {displayPayload.depot.depot_name}</div><div className="mt-1 text-xs text-slate-500">Master Depot position</div><div className="mt-1">{displayPayload.depot.latitude.toFixed(5)}, {displayPayload.depot.longitude.toFixed(5)}</div></div></Tooltip>
                  <Popup><strong>Depot · {displayPayload.depot.depot_name}</strong><br />Master coordinate: {displayPayload.depot.latitude.toFixed(5)}, {displayPayload.depot.longitude.toFixed(5)}</Popup>
                </CircleMarker>
              )}
            </MapContainer>
          </div>
          <div className="mt-4 grid max-h-44 gap-2 overflow-auto text-xs sm:grid-cols-2 xl:grid-cols-3">
            {visibleRoutes.map((route) => <div key={`legend-${route.trip_id}`} className="border border-line p-2"><span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: vehicleColor(route.vehicle_id) }} /><strong>{route.vehicle_registration_no}</strong> · Trip #{route.trip_number ?? "—"} · {route.uses_road_geometry ? "Google road" : "fallback"}<div className="mt-1 text-slate-500">{route.shipment_id} · {route.total_order_kl} KL · Depot → {route.stops.map((stop) => stop.spbu_code).join(" → ")} → Depot</div></div>)}
          </div>
        </>
      ) : <div className="mt-4 border border-dashed border-line p-6 text-center text-sm text-slate-500">Belum ada assigned shipment dengan koordinat depot dan SPBU yang lengkap.</div>}
    </div>
  );
}

export function PredictionAssignmentPage({ depots, products }: { depots: Depot[]; products: Product[] }) {
  const [depotId, setDepotId] = useState(depots[0]?.depot_id || "");
  const [models, setModels] = useState<Model[]>([]);
  const [masterSpbus, setMasterSpbus] = useState<MasterSpbuOption[]>([]);
  const [modelId, setModelId] = useState("");
  const [loadingOrderFile, setLoadingOrderFile] = useState<File | null>(null);
  const [mtFile, setMtFile] = useState<File | null>(null);
  const [loValidation, setLoValidation] = useState<Validation | null>(null);
  const [mtValidation, setMtValidation] = useState<Validation | null>(null);
  const [result, setResult] = useState<PredictionResult | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [historyRefreshing, setHistoryRefreshing] = useState(false);
  const [historyFeedback, setHistoryFeedback] = useState<{ status: "SUCCESS" | "ERROR"; message: string } | null>(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPerPage, setHistoryPerPage] = useState(10);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runFeedback, setRunFeedback] = useState<{ status: "RUNNING" | "SUCCESS" | "ERROR"; message: string } | null>(null);
  const [activeRuns, setActiveRuns] = useState<ActivePredictionTask[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [unassignedShipment, setUnassignedShipment] = useState<Shipment | null>(null);
  useEffect(() => { setUnassignedShipment(null); }, [result?.id]);
  const [candidateLoadingShipment, setCandidateLoadingShipment] = useState<string | null>(null);
  const [shiftTab, setShiftTab] = useState("ALL");
  const [shipmentPage, setShipmentPage] = useState(1);
  const [shipmentsPerPage, setShipmentsPerPage] = useState(25);
  const [resultPageLoading, setResultPageLoading] = useState(false);
  const [timelinePage, setTimelinePage] = useState(1);
  const [mtPerTimelinePage, setMtPerTimelinePage] = useState(10);
  const [overrideReason, setOverrideReason] = useState<Record<string, string>>({});
  const [moveTargets, setMoveTargets] = useState<Record<string, string>>({});
  const [minimumConfidence, setMinimumConfidence] = useState("0.40");
  const [maximumPairingGap, setMaximumPairingGap] = useState("90");
  const [assignmentMode, setAssignmentMode] = useState("STRICT_START");
  const [maximumDelay, setMaximumDelay] = useState("30");
  const [demoDialogOpen, setDemoDialogOpen] = useState(false);
  const [demoTotalKl, setDemoTotalKl] = useState("80");
  const [demoLoadingOrderDate, setDemoLoadingOrderDate] = useState(localTomorrowDate);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoNotice, setDemoNotice] = useState<string | null>(null);
  const [loadingOrderManagementReady, setLoadingOrderManagementReady] = useState(false);
  const [managedLoadingOrders, setManagedLoadingOrders] = useState<ManagedLoadingOrder[]>([]);
  const [loadingOrderEditor, setLoadingOrderEditor] = useState<LoadingOrderEditor | null>(null);
  const [loadingOrderEditorError, setLoadingOrderEditorError] = useState<string | null>(null);
  const [loadingOrderSaving, setLoadingOrderSaving] = useState(false);
  const [loadingOrderManagementNotice, setLoadingOrderManagementNotice] = useState<string | null>(null);
  const [loadingOrderFilters, setLoadingOrderFilters] = useState<LoadingOrderFilters>(EMPTY_LOADING_ORDER_FILTERS);
  const [loadingOrderSort, setLoadingOrderSort] = useState<{ field: LoadingOrderSortField; direction: "ASC" | "DESC" }>({ field: "shipment_start_datetime", direction: "ASC" });
  const [loadingOrderPage, setLoadingOrderPage] = useState(1);
  const [loadingOrdersPerPage, setLoadingOrdersPerPage] = useState(10);
  const [mtManagementReady, setMtManagementReady] = useState(false);
  const [managedMts, setManagedMts] = useState<ManagedMtAvailability[]>([]);
  const [mtManagementLoading, setMtManagementLoading] = useState(false);
  const [mtManagementNotice, setMtManagementNotice] = useState<string | null>(null);
  const [mtSearch, setMtSearch] = useState("");
  const [mtPage, setMtPage] = useState(1);
  const [mtsPerPage, setMtsPerPage] = useState(25);
  const [selectedMtIds, setSelectedMtIds] = useState<Set<string>>(new Set());
  const [mtBulkAction, setMtBulkAction] = useState<"STATUS" | "ETA" | null>(null);
  const [mtBulkScope, setMtBulkScope] = useState<"SELECTED" | "FILTERED">("FILTERED");
  const [mtBulkStatus, setMtBulkStatus] = useState<ManagedMtAvailability["status"]>("ACTIVE");
  const [mtBulkEta, setMtBulkEta] = useState("");

  const selectedModel = models.find((model) => model.model_id === modelId) ?? null;
  const activeProducts = useMemo(
    () => products.filter((product) => !product.active_status || product.active_status === "ACTIVE"),
    [products],
  );
  const issues = [...(loValidation?.issues ?? []), ...(mtValidation?.issues ?? [])];
  const blockingErrors = (loValidation?.blocking_error_count ?? 0) + (mtValidation?.blocking_error_count ?? 0);
  const warnings = (loValidation?.warning_count ?? 0) + (mtValidation?.warning_count ?? 0);
  const validatedOrderKl = (loValidation?.normalized_rows ?? []).reduce(
    (total, row) => total + (typeof row.order_quantity_kl === "number" ? row.order_quantity_kl : Number(row.order_quantity_kl ?? 0)),
    0,
  );
  const validatedMtCapacityKl = (mtValidation?.normalized_rows ?? []).reduce(
    (total, row) => total + (typeof row.capacity_kl === "number" ? row.capacity_kl : Number(row.capacity_kl ?? 0)),
    0,
  );
  const canRun = Boolean(
    depotId
    && modelId
    && loadingOrderFile
    && mtFile
    && loValidation
    && mtValidation
    && mtValidation.row_count > 0
    && blockingErrors === 0
    && !loadingOrderSaving
    && !mtManagementLoading,
  );
  const filteredLoadingOrders = useMemo(() => {
    const rows = managedLoadingOrders.filter((row) => (
      (Object.keys(EMPTY_LOADING_ORDER_FILTERS) as LoadingOrderSortField[]).every((field) => (
        row[field].toLocaleLowerCase().includes(loadingOrderFilters[field].trim().toLocaleLowerCase())
      ))
    ));
    return [...rows].sort((left, right) => {
      let comparison: number;
      if (loadingOrderSort.field === "order_quantity_kl") {
        comparison = Number(left.order_quantity_kl) - Number(right.order_quantity_kl);
      } else {
        comparison = left[loadingOrderSort.field].localeCompare(right[loadingOrderSort.field], "id", { numeric: true, sensitivity: "base" });
      }
      if (!Number.isFinite(comparison)) comparison = 0;
      return loadingOrderSort.direction === "ASC" ? comparison : -comparison;
    });
  }, [loadingOrderFilters, loadingOrderSort, managedLoadingOrders]);
  const loadingOrderPageCount = Math.max(1, Math.ceil(filteredLoadingOrders.length / loadingOrdersPerPage));
  const currentLoadingOrderPage = Math.min(loadingOrderPage, loadingOrderPageCount);
  const paginatedLoadingOrders = filteredLoadingOrders.slice(
    (currentLoadingOrderPage - 1) * loadingOrdersPerPage,
    currentLoadingOrderPage * loadingOrdersPerPage,
  );
  const filteredManagedMts = useMemo(() => {
    const search = mtSearch.trim().toLocaleLowerCase();
    if (!search) return managedMts;
    return managedMts.filter((row) => (
      row.vehicle_registration_no.toLocaleLowerCase().includes(search)
      || row.mt_tag_class.toLocaleLowerCase().includes(search)
      || row.status.toLocaleLowerCase().includes(search)
      || row.eta_on_depot.toLocaleLowerCase().includes(search)
      || row.eligibility_issues.some((issue) => issue.toLocaleLowerCase().includes(search))
    ));
  }, [managedMts, mtSearch]);
  const mtPageCount = Math.max(1, Math.ceil(filteredManagedMts.length / mtsPerPage));
  const currentMtPage = Math.min(mtPage, mtPageCount);
  const paginatedManagedMts = filteredManagedMts.slice(
    (currentMtPage - 1) * mtsPerPage,
    currentMtPage * mtsPerPage,
  );
  const activeManagedMtCount = managedMts.filter((row) => row.status === "ACTIVE").length;
  const selectedManagedMts = managedMts.filter((row) => selectedMtIds.has(row.id));
  const mtBulkTargets = mtBulkScope === "SELECTED" ? selectedManagedMts : filteredManagedMts;
  const allFilteredMtsSelected = filteredManagedMts.length > 0 && filteredManagedMts.every((row) => selectedMtIds.has(row.id));

  useEffect(() => {
    setSelectedMtIds(new Set());
    setMtBulkAction(null);
  }, [depotId, modelId]);

  useEffect(() => {
    setLoadingOrderPage(1);
  }, [loadingOrderFilters, loadingOrdersPerPage]);

  useEffect(() => {
    if (loadingOrderPage > loadingOrderPageCount) setLoadingOrderPage(loadingOrderPageCount);
  }, [loadingOrderPage, loadingOrderPageCount]);

  useEffect(() => {
    setMtPage(1);
  }, [mtSearch, mtsPerPage]);

  useEffect(() => {
    if (mtPage > mtPageCount) setMtPage(mtPageCount);
  }, [mtPage, mtPageCount]);

  useEffect(() => {
    setActiveRuns([]);
    setHistoryPage(1);
    setModelId("");
    setModels([]);
    setMasterSpbus([]);
    setLoadingOrderFile(null);
    setMtFile(null);
    setLoValidation(null);
    setMtValidation(null);
    setResult(null);
    setRunFeedback(null);
    setDemoDialogOpen(false);
    setDemoNotice(null);
    setLoadingOrderManagementReady(false);
    setManagedLoadingOrders([]);
    setLoadingOrderEditor(null);
    setLoadingOrderEditorError(null);
    setLoadingOrderManagementNotice(null);
    setLoadingOrderFilters(EMPTY_LOADING_ORDER_FILTERS);
    setLoadingOrderPage(1);
    setMtManagementReady(false);
    setManagedMts([]);
    setMtManagementNotice(null);
    setMtSearch("");
    setMtPage(1);
    if (!depotId) {
      setHistory([]);
      return;
    }
    Promise.all([
      apiGet<Model[]>(`/api/v1/phase6/models?depot_id=${encodeURIComponent(depotId)}`),
      apiGet<HistoryRow[]>(`/api/v1/phase6/predictions?depot_id=${encodeURIComponent(depotId)}`),
      apiGet<MasterSpbuOption[]>(`/api/v1/master/spbu?depot_id=${encodeURIComponent(depotId)}&active_only=true&limit=10000`),
    ]).then(([modelRows, historyRows, spbuRows]) => {
      setModels(modelRows);
      setHistory(historyRows);
      setMasterSpbus(spbuRows);
      const pendingRuns = historyRows.filter((row) => row.status === "QUEUED" || row.status === "RUNNING");
      if (pendingRuns.length > 0) {
        setActiveRuns(pendingRuns.map((row) => ({ id: row.id, predictionRunId: row.prediction_run_id, depotId: row.depot_id })));
        setRunFeedback({
          status: "RUNNING",
          message: `${pendingRuns.length.toLocaleString("id-ID")} task prediction sedang berada di antrean atau diproses worker. Anda tetap dapat mengirim task baru.`,
        });
      }
    }).catch((reason: Error) => setError(reason.message));
  }, [depotId]);

  useEffect(() => {
    setLoadingOrderFile(null);
    setMtFile(null);
    setLoValidation(null);
    setMtValidation(null);
    setResult(null);
    setRunFeedback(null);
    setDemoDialogOpen(false);
    setDemoNotice(null);
    setLoadingOrderManagementReady(false);
    setManagedLoadingOrders([]);
    setLoadingOrderEditor(null);
    setLoadingOrderEditorError(null);
    setLoadingOrderManagementNotice(null);
    setLoadingOrderFilters(EMPTY_LOADING_ORDER_FILTERS);
    setLoadingOrderPage(1);
    setMtManagementReady(false);
    setManagedMts([]);
    setMtManagementNotice(null);
    setMtSearch("");
    setMtPage(1);
  }, [modelId]);

  useEffect(() => {
    if (activeRuns.length === 0) return;
    const tasks = activeRuns;
    let cancelled = false;
    let timer: number | undefined;

    async function pollPredictionStatuses() {
      try {
        const statuses = await Promise.all(tasks.map(async (task) => {
          try {
            return await apiGet<PredictionRunStatus>(`/api/v1/phase6/predictions/${task.id}/status`);
          } catch {
            return null;
          }
        }));
        if (cancelled) return;
        const completed = statuses.filter((status): status is PredictionRunStatus => status?.status === "COMPLETED");
        const failed = statuses.filter((status): status is PredictionRunStatus => status?.status === "FAILED");
        const terminalIds = new Set([...completed, ...failed].map((status) => status.id));
        if (completed.length > 0) {
          const latest = completed[completed.length - 1];
          const payload = await apiGet<PredictionResult>(`/api/v1/phase6/predictions/${latest.id}?shipment_page=1&shipment_page_size=${shipmentsPerPage}`);
          if (cancelled) return;
          setResult(payload);
          setShipmentPage(1);
          setExpanded(null);
          setShiftTab("ALL");
        }
        if (failed.length > 0) {
          const failedStatus = failed[failed.length - 1];
          const message = `${failedStatus.error_code ? `[${failedStatus.error_code}] ` : ""}${failedStatus.error_message ?? "Prediction gagal diproses."}`;
          setError(message);
        }
        if (terminalIds.size > 0) {
          setActiveRuns((current) => current.filter((task) => !terminalIds.has(task.id)));
          if (depotId) setHistory(await apiGet<HistoryRow[]>(`/api/v1/phase6/predictions?depot_id=${encodeURIComponent(depotId)}`));
          const remaining = tasks.length - terminalIds.size;
          setRunFeedback(failed.length > 0
            ? { status: "ERROR", message: `${failed.length} task gagal. ${remaining} task lain masih berada di antrean atau diproses.` }
            : { status: "SUCCESS", message: `${completed.length} prediction selesai dan hasil terbaru ditampilkan. ${remaining > 0 ? `${remaining} task masih berada di antrean.` : "Antrean aktif telah selesai."}` });
          return;
        }
        const runningCount = statuses.filter((status) => status?.status === "RUNNING").length;
        const queuedCount = statuses.filter((status) => status?.status === "QUEUED").length;
        setRunFeedback({ status: "RUNNING", message: `${runningCount} task sedang diproses worker · ${queuedCount} task menunggu antrean. Anda tetap dapat mengirim prediction baru.` });
      } catch {
        if (cancelled) return;
        setRunFeedback({ status: "RUNNING", message: `${tasks.length} task tetap berjalan di belakang layar. Koneksi status akan dicoba kembali otomatis.` });
      }
      timer = window.setTimeout(() => void pollPredictionStatuses(), 1500);
    }

    void pollPredictionStatuses();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeRuns, depotId, shipmentsPerPage]);

  async function validateFile(kind: "loading-order" | "mt-availability", file: File) {
    if (!depotId || !modelId) return null;
    setError(null);
    const body = new FormData();
    body.append("depot_id", depotId);
    body.append("model_id", modelId);
    body.append("file", file);
    try {
      const validation = await apiForm<Validation>(`/api/v1/phase6/validate/${kind}`, body);
      if (kind === "loading-order") setLoValidation(validation);
      else setMtValidation(validation);
      return validation;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Validation failed.");
      return null;
    }
  }

  function initializeLoadingOrderManagement(validation: Validation) {
    const rows = managedLoadingOrdersFromValidation(validation);
    setManagedLoadingOrders(rows);
    setLoadingOrderManagementReady(true);
    setLoadingOrderFilters(EMPTY_LOADING_ORDER_FILTERS);
    setLoadingOrderPage(1);
    setLoadingOrderEditor(null);
    setLoadingOrderEditorError(null);
    setLoadingOrderManagementNotice(
      `${rows.length.toLocaleString("id-ID")} Loading Order dimuat. Perubahan pada tabel akan divalidasi ulang dan menjadi input Run Prediction.`,
    );
  }

  async function loadLoadingOrderFile(file: File) {
    setLoadingOrderSaving(true);
    setLoadingOrderFile(file);
    setLoValidation(null);
    setResult(null);
    setDemoNotice(null);
    setLoadingOrderManagementReady(false);
    setLoadingOrderManagementNotice(null);
    try {
      const validation = await validateFile("loading-order", file);
      if (validation) initializeLoadingOrderManagement(validation);
      return validation;
    } finally {
      setLoadingOrderSaving(false);
    }
  }

  async function persistManagedLoadingOrders(rows: ManagedLoadingOrder[], message: string) {
    setLoadingOrderSaving(true);
    setError(null);
    setLoadingOrderManagementNotice(null);
    try {
      const file = await apiFile(
        "/api/v1/phase6/loading-orders/workbook",
        "POST",
        { rows: loadingOrderWorkbookRows(rows) },
        "phase6-managed-loading-orders.xlsx",
      );
      setLoadingOrderFile(file);
      setLoValidation(null);
      setResult(null);
      const validation = await validateFile("loading-order", file);
      setManagedLoadingOrders(rows);
      setLoadingOrderPage(1);
      if (validation) {
        setLoadingOrderManagementNotice(message);
        return true;
      }
      return false;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Loading Order gagal diperbarui.");
      return false;
    } finally {
      setLoadingOrderSaving(false);
    }
  }

  function openNewLoadingOrderEditor() {
    setLoadingOrderEditorError(null);
    setLoadingOrderEditor({
      mode: "ADD",
      row: {
        id: globalThis.crypto?.randomUUID?.() ?? `loading-order-${Date.now()}`,
        loading_order_no: "",
        shift: managedLoadingOrders[0]?.shift ?? "",
        shipment_start_datetime: managedLoadingOrders[0]?.shipment_start_datetime ?? "",
        spbu_no: "",
        product: activeProducts[0]?.product_name ?? "",
        order_quantity_kl: "8",
      },
    });
  }

  function openEditLoadingOrderEditor(row: ManagedLoadingOrder) {
    setLoadingOrderEditorError(null);
    setLoadingOrderEditor({ mode: "EDIT", row: { ...row } });
  }

  async function saveLoadingOrderEditor() {
    if (!loadingOrderEditor) return;
    const row = {
      ...loadingOrderEditor.row,
      loading_order_no: loadingOrderEditor.row.loading_order_no.trim(),
      spbu_no: loadingOrderEditor.row.spbu_no.trim(),
      product: loadingOrderEditor.row.product.trim(),
      order_quantity_kl: loadingOrderEditor.row.order_quantity_kl.trim(),
    };
    if (!row.loading_order_no || !row.shipment_start_datetime || !row.spbu_no || !row.product) {
      setLoadingOrderEditorError("Nomor LO, waktu shipment, nomor SPBU, dan product wajib diisi.");
      return;
    }
    if (!masterSpbus.some((spbu) => spbu.spbu_code === row.spbu_no)) {
      setLoadingOrderEditorError("Pilih SPBU aktif dari Master SPBU pada depot yang sedang digunakan.");
      return;
    }
    if (!activeProducts.some((product) => product.product_name === row.product)) {
      setLoadingOrderEditorError("Pilih Product aktif dari Master Product.");
      return;
    }
    if (Number(row.order_quantity_kl) !== 8) {
      setLoadingOrderEditorError("Setiap Loading Order wajib bernilai tepat 8 KL.");
      return;
    }
    const duplicate = managedLoadingOrders.some((item) => (
      item.id !== row.id && item.loading_order_no.trim().toLocaleLowerCase() === row.loading_order_no.toLocaleLowerCase()
    ));
    if (duplicate) {
      setLoadingOrderEditorError("Nomor Loading Order sudah digunakan pada baris lain.");
      return;
    }
    const rows = loadingOrderEditor.mode === "ADD"
      ? [...managedLoadingOrders, row]
      : managedLoadingOrders.map((item) => item.id === row.id ? row : item);
    const saved = await persistManagedLoadingOrders(
      rows,
      loadingOrderEditor.mode === "ADD" ? `Loading Order ${row.loading_order_no} ditambahkan dan validasi diperbarui.` : `Loading Order ${row.loading_order_no} diperbarui dan divalidasi ulang.`,
    );
    if (saved) {
      setLoadingOrderEditor(null);
      setLoadingOrderEditorError(null);
    }
  }

  async function deleteManagedLoadingOrder(row: ManagedLoadingOrder) {
    if (!window.confirm(`Hapus Loading Order ${row.loading_order_no}?`)) return;
    await persistManagedLoadingOrders(
      managedLoadingOrders.filter((item) => item.id !== row.id),
      `Loading Order ${row.loading_order_no} dihapus dan validasi diperbarui.`,
    );
  }

  function toggleLoadingOrderSort(field: LoadingOrderSortField) {
    setLoadingOrderSort((current) => (
      current.field === field
        ? { field, direction: current.direction === "ASC" ? "DESC" : "ASC" }
        : { field, direction: "ASC" }
    ));
    setLoadingOrderPage(1);
  }

  async function runPrediction() {
    if (!canRun || !loadingOrderFile || !mtFile) return;
    setLoading(true);
    setError(null);
    setRunFeedback({
      status: "RUNNING",
      message: "Mengirim task prediction ke backend…",
    });
    const body = new FormData();
    body.append("depot_id", depotId);
    body.append("model_id", modelId);
    body.append("loading_order_file", loadingOrderFile);
    body.append("mt_availability_file", mtFile);
    body.append("parameters", JSON.stringify({
      minimum_prediction_confidence: Number(minimumConfidence),
      maximum_pairing_time_gap_minutes: Number(maximumPairingGap),
      assignment_mode: assignmentMode,
      maximum_allowed_delay_minutes: Number(maximumDelay),
    }));
    try {
      const queued = await apiForm<PredictionTask>("/api/v1/phase6/predictions", body);
      setActiveRuns((current) => current.some((task) => task.id === queued.id)
        ? current
        : [...current, { id: queued.id, predictionRunId: queued.prediction_run_id, depotId }]);
      setRunFeedback({
        status: "RUNNING",
        message: `Prediction ${queued.prediction_run_id} telah masuk antrean. Anda dapat langsung mengirim prediction berikutnya tanpa menunggu task ini selesai.`,
      });
      setHistory(await apiGet<HistoryRow[]>(`/api/v1/phase6/predictions?depot_id=${encodeURIComponent(depotId)}`));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Prediction failed.";
      setError(message);
      setRunFeedback({ status: "ERROR", message: `Prediction gagal: ${message}` });
    } finally {
      setLoading(false);
    }
  }

  async function generateDemoLoadingOrders(selectedLoadingOrderDate = demoLoadingOrderDate) {
    const totalOrderKl = Number(demoTotalKl);
    if (!depotId || !modelId || !selectedLoadingOrderDate || !/^\d{4}-\d{2}-\d{2}$/.test(selectedLoadingOrderDate)) {
      setError("Tanggal Loading Order wajib dipilih.");
      return;
    }
    if (!Number.isFinite(totalOrderKl) || totalOrderKl <= 0 || totalOrderKl > 40000 || totalOrderKl % 8 !== 0) {
      setError("Total order harus kelipatan 8 KL, lebih dari 0, dan maksimum 40.000 KL.");
      return;
    }
    setDemoLoading(true);
    setError(null);
    try {
      const file = await apiFile(
        "/api/v1/phase6/demo/loading-order",
        "POST",
        { depot_id: depotId, model_id: modelId, total_order_kl: totalOrderKl, loading_order_date: selectedLoadingOrderDate },
        "phase6-demo-loading-order.xlsx",
      );
      setDemoDialogOpen(false);
      const validation = await loadLoadingOrderFile(file);
      if (validation) {
        setDemoNotice(`Data demo ${totalOrderKl.toLocaleString("id-ID", { maximumFractionDigits: 3 })} KL untuk tanggal ${selectedLoadingOrderDate} berhasil dibuat dan divalidasi.`);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Data demo gagal dibuat.");
    } finally {
      setDemoLoading(false);
    }
  }

  async function persistManagedMtAvailability(rows: ManagedMtAvailability[], message: string) {
    setMtManagementLoading(true);
    setError(null);
    setMtManagementNotice(null);
    try {
      const file = await apiFile(
        "/api/v1/phase6/mt-availability/workbook",
        "POST",
        { rows: managedMtWorkbookRows(rows) },
        "phase6-managed-mt-availability.xlsx",
      );
      setManagedMts(rows);
      setMtFile(file);
      setMtValidation(null);
      setResult(null);
      const validation = await validateFile("mt-availability", file);
      if (validation) {
        setMtManagementNotice(message);
        return true;
      }
      return false;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "MT Availability gagal diperbarui.");
      return false;
    } finally {
      setMtManagementLoading(false);
    }
  }

  async function importMtFromMasterData() {
    if (!depotId || !modelId) return;
    setMtManagementLoading(true);
    setError(null);
    setMtManagementNotice(null);
    try {
      const masterRows = await apiGet<MasterMtOption[]>(
        `/api/v1/phase6/master-mt-availability?depot_id=${encodeURIComponent(depotId)}`,
      );
      const eta = defaultMtEta(selectedModel, loValidation);
      const rows = masterRows
        .filter((row) => Boolean(row.vehicle_registration))
        .map((row) => ({
          id: row.mt_id,
          vehicle_registration_no: row.vehicle_registration as string,
          mt_tag_class: String(row.vehicle_type_tag ?? row.capacity_label ?? "—"),
          status: row.phase6_eligible ? "ACTIVE" as const : "DEACTIVE" as const,
          eta_on_depot: eta,
          eligibility_issues: row.phase6_failed_rules,
        }));
      if (rows.length === 0) {
        setError("Tidak ada MT canonical aktif untuk depot terpilih.");
        return;
      }
      setMtManagementReady(true);
      setSelectedMtIds(new Set());
      setMtBulkAction(null);
      setMtSearch("");
      setMtPage(1);
      const eligibleCount = rows.filter((row) => row.status === "ACTIVE").length;
      await persistManagedMtAvailability(
        rows,
        `${rows.length.toLocaleString("id-ID")} MT canonical aktif diimpor dari Master Data. ${eligibleCount.toLocaleString("id-ID")} MT eligible default Active; ${(rows.length - eligibleCount).toLocaleString("id-ID")} MT dengan profil kapasitas tidak valid default Deactive. ETA default ${eta.replace("T", " ")} mengikuti awal Shift 1.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Import MT dari Master Data gagal.");
    } finally {
      setMtManagementLoading(false);
    }
  }

  async function changeManagedMtStatus(rowId: string, status: ManagedMtAvailability["status"]) {
    const rows = managedMts.map((row) => row.id === rowId ? { ...row, status } : row);
    setManagedMts(rows);
    const activeCount = rows.filter((row) => row.status === "ACTIVE").length;
    await persistManagedMtAvailability(
      rows,
      `Status operasional diperbarui. ${activeCount.toLocaleString("id-ID")} MT Active masuk ke input prediction; Master Data tidak diubah.`,
    );
  }

  async function saveManagedMtEta(rowId: string) {
    const row = managedMts.find((item) => item.id === rowId);
    if (!row || row.status !== "ACTIVE") return;
    await persistManagedMtAvailability(
      managedMts,
      `ETA on Depot ${row.vehicle_registration_no} disimpan sebagai waktu MT available di depot.`,
    );
  }

  function openMtBulkAction(action: "STATUS" | "ETA") {
    setError(null);
    setMtBulkScope(selectedManagedMts.length > 0 ? "SELECTED" : "FILTERED");
    setMtBulkStatus("ACTIVE");
    setMtBulkEta(defaultMtEta(selectedModel, loValidation));
    setMtBulkAction(action);
  }

  async function applyMtBulkAction() {
    if (!mtBulkAction || mtManagementLoading || mtBulkTargets.length === 0) return;
    if (mtBulkAction === "ETA" && !mtBulkEta) return;
    const targetIds = new Set(mtBulkTargets.map((row) => row.id));
    const rows = managedMts.map((row) => !targetIds.has(row.id) ? row : (
      mtBulkAction === "STATUS" ? { ...row, status: mtBulkStatus } : { ...row, eta_on_depot: mtBulkEta }
    ));
    const count = targetIds.size.toLocaleString("id-ID");
    const message = mtBulkAction === "STATUS"
      ? `${count} MT diperbarui menjadi ${mtBulkStatus === "ACTIVE" ? "Active" : "Deactive"}.`
      : `ETA on Depot untuk ${count} MT diset ke ${mtBulkEta.replace("T", " ")}.`;
    if (await persistManagedMtAvailability(rows, message)) setMtBulkAction(null);
  }

  async function downloadValidation() {
    if (!loadingOrderFile || !mtFile) return;
    const body = new FormData();
    body.append("depot_id", depotId);
    body.append("model_id", modelId);
    body.append("loading_order_file", loadingOrderFile);
    body.append("mt_availability_file", mtFile);
    await downloadFormFromApi("/api/v1/phase6/validation-report", body, "phase6-validation-report.xlsx");
  }

  function predictionResultUrl(runId: string, page: number, pageSize: number, shift: string) {
    const query = new URLSearchParams({ shipment_page: String(page), shipment_page_size: String(pageSize) });
    if (shift !== "ALL") query.set("shift_id", shift);
    return `/api/v1/phase6/predictions/${runId}?${query.toString()}`;
  }

  async function loadPredictionPage(runId: string, page: number, pageSize: number, shift: string) {
    setResultPageLoading(true);
    try {
      const payload = await apiGet<PredictionResult>(predictionResultUrl(runId, page, pageSize, shift));
      setResult(payload);
      setShipmentPage(payload.shipment_pagination.page);
      setShipmentsPerPage(payload.shipment_pagination.page_size);
      setShiftTab(payload.shipment_pagination.shift_id ?? "ALL");
      setExpanded(null);
      return payload;
    } finally {
      setResultPageLoading(false);
    }
  }

  async function toggleShipmentDetail(shipment: Shipment) {
    if (!result) return;
    if (expanded === shipment.id) {
      setExpanded(null);
      return;
    }
    setExpanded(shipment.id);
    if (shipment.candidates_loaded) return;
    setCandidateLoadingShipment(shipment.id);
    try {
      const payload = await apiGet<ShipmentCandidatesResponse>(`/api/v1/phase6/predictions/${result.id}/shipments/${shipment.id}/candidates`);
      setResult((current) => current ? {
        ...current,
        shipments: current.shipments.map((row) => row.id === shipment.id
          ? { ...row, candidates: payload.candidates, candidates_loaded: true }
          : row),
      } : current);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Kandidat MT gagal dimuat.");
    } finally {
      setCandidateLoadingShipment(null);
    }
  }

  async function applyAssignmentOverride(shipment: Shipment, vehicleId: string) {
    if (!result || !shipment.assignment.id) return;
    setLoading(true);
    try {
      await apiSend<PredictionResult>(
        `/api/v1/phase6/predictions/${result.id}/assignments/${shipment.assignment.id}`,
        "PATCH",
        { vehicle_id: vehicleId, override_reason: overrideReason[shipment.id] || null },
      );
      await loadPredictionPage(result.id, shipmentPage, shipmentsPerPage, shiftTab);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Override failed.");
    } finally {
      setLoading(false);
    }
  }

  async function adjustShipment(shipment: Shipment, action: string, lineIds: string[], targetShipmentId?: string) {
    if (!result) return;
    setLoading(true);
    try {
      await apiSend<PredictionResult>(
        `/api/v1/phase6/predictions/${result.id}/shipments/${shipment.id}`,
        "PATCH",
        { action, line_ids: lineIds, target_shipment_id: targetShipmentId || null },
      );
      await loadPredictionPage(result.id, shipmentPage, shipmentsPerPage, shiftTab);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Shipment adjustment failed.");
    } finally {
      setLoading(false);
    }
  }

  async function openHistory(runId: string) {
    const historyRow = history.find((row) => row.id === runId);
    if (historyRow && (historyRow.status === "QUEUED" || historyRow.status === "RUNNING")) {
      setActiveRuns((current) => current.some((task) => task.id === historyRow.id)
        ? current
        : [...current, { id: historyRow.id, predictionRunId: historyRow.prediction_run_id, depotId: historyRow.depot_id }]);
      setRunFeedback({
        status: "RUNNING",
        message: `Prediction ${historyRow.prediction_run_id} masih berjalan di belakang layar. Hasil akan ditampilkan otomatis.`,
      });
      return;
    }
    setLoading(true);
    try {
      await loadPredictionPage(runId, 1, shipmentsPerPage, "ALL");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run could not be opened.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshHistory(silent = false) {
    if (!depotId || historyRefreshing) return;
    setHistoryRefreshing(true);
    if (!silent) setHistoryFeedback(null);
    try {
      const rows = await apiGet<HistoryRow[]>(`/api/v1/phase6/predictions?depot_id=${encodeURIComponent(depotId)}`);
      setHistory(rows);
      if (!silent) {
        setHistoryPage(1);
        setHistoryFeedback({
          status: "SUCCESS",
          message: `History diperbarui pada ${new Date().toLocaleTimeString("id-ID")}.`,
        });
      }
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "History prediction gagal diperbarui.";
      setHistoryFeedback({ status: "ERROR", message });
      setError(message);
    } finally {
      setHistoryRefreshing(false);
    }
  }

  async function rerun(runId: string) {
    setLoading(true);
    setError(null);
    try {
      const queued = await apiSend<PredictionTask>(`/api/v1/phase6/predictions/${runId}/recalculate`, "POST", { model_id: modelId || null });
      setActiveRuns((current) => current.some((task) => task.id === queued.id)
        ? current
        : [...current, { id: queued.id, predictionRunId: queued.prediction_run_id, depotId }]);
      setRunFeedback({
        status: "RUNNING",
        message: `Prediction ${queued.prediction_run_id} telah masuk antrean retry/re-run dan akan diproses worker terpisah.`,
      });
      await refreshHistory(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Re-run failed.");
    } finally {
      setLoading(false);
    }
  }

  const visibleShipments = result?.shipments ?? [];
  const shipmentPageCount = result?.shipment_pagination.total_pages ?? 1;
  const currentShipmentPage = result?.shipment_pagination.page ?? shipmentPage;
  const paginatedShipments = visibleShipments;
  const shipmentPaginationPages = useMemo(
    () => [...new Set([1, currentShipmentPage - 1, currentShipmentPage, currentShipmentPage + 1, shipmentPageCount])]
      .filter((page) => page >= 1 && page <= shipmentPageCount)
      .sort((left, right) => left - right),
    [currentShipmentPage, shipmentPageCount],
  );
  const shipmentRangeStart = (result?.shipment_pagination.total ?? 0) === 0 ? 0 : (currentShipmentPage - 1) * shipmentsPerPage + 1;
  const shipmentRangeEnd = Math.min(currentShipmentPage * shipmentsPerPage, result?.shipment_pagination.total ?? 0);
  const historyPageCount = Math.max(1, Math.ceil(history.length / historyPerPage));
  const currentHistoryPage = Math.min(historyPage, historyPageCount);
  const paginatedHistory = useMemo(() => {
    const start = (currentHistoryPage - 1) * historyPerPage;
    return history.slice(start, start + historyPerPage);
  }, [currentHistoryPage, history, historyPerPage]);
  const historyPaginationPages = useMemo(
    () => [...new Set([1, currentHistoryPage - 1, currentHistoryPage, currentHistoryPage + 1, historyPageCount])]
      .filter((page) => page >= 1 && page <= historyPageCount)
      .sort((left, right) => left - right),
    [currentHistoryPage, historyPageCount],
  );
  const historyRangeStart = history.length === 0 ? 0 : (currentHistoryPage - 1) * historyPerPage + 1;
  const historyRangeEnd = Math.min(currentHistoryPage * historyPerPage, history.length);

  function goToHistoryPage(page: number) {
    setHistoryPage(Math.min(Math.max(1, page), historyPageCount));
  }

  function changeHistoryPerPage(nextSize: number) {
    setHistoryPerPage(nextSize);
    setHistoryPage(1);
  }

  function goToShipmentPage(page: number) {
    if (!result || resultPageLoading) return;
    const target = Math.min(Math.max(1, page), shipmentPageCount);
    void loadPredictionPage(result.id, target, shipmentsPerPage, shiftTab).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Halaman shipment gagal dimuat.");
    });
  }

  function changeShipmentShift(nextShift: string) {
    if (!result || resultPageLoading) return;
    void loadPredictionPage(result.id, 1, shipmentsPerPage, nextShift).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Filter shift gagal dimuat.");
    });
  }

  function changeShipmentsPerPage(nextSize: number) {
    if (!result || resultPageLoading) return;
    void loadPredictionPage(result.id, 1, nextSize, shiftTab).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Ukuran halaman gagal diterapkan.");
    });
  }
  const shifts = result?.summary_by_shift ?? [];
  const networkOption = useMemo(() => {
    const nodeMap = new Map<string, { id: string; name: string; value: string; category: number }>();
    const links: Array<{ source: string; target: string; value: number; lineStyle: { width: number } }> = [];
    visibleShipments.forEach((shipment, shipmentIndex) => {
      shipment.lines.forEach((line) => nodeMap.set(line.id, { id: line.id, name: line.spbu_no, value: shipment.predicted_shipment_id, category: shipmentIndex }));
      for (let left = 0; left < shipment.lines.length; left += 1) {
        for (let right = left + 1; right < shipment.lines.length; right += 1) {
          links.push({
            source: shipment.lines[left].id,
            target: shipment.lines[right].id,
            value: shipment.shipment_prediction_score,
            lineStyle: { width: Math.max(1, shipment.shipment_prediction_score * 7) },
          });
        }
      }
    });
    return {
      tooltip: { formatter: (item: { data: { name?: string; value?: string | number } }) => `${item.data.name ?? "Pair"}<br/>${item.data.value ?? ""}` },
      series: [{
        type: "graph",
        layout: "force",
        roam: true,
        label: { show: true },
        force: { repulsion: 220, edgeLength: 100 },
        data: [...nodeMap.values()],
        links,
        lineStyle: { color: "#0b73bf", opacity: 0.65 },
        itemStyle: { color: "#b8d211", borderColor: "#15385b", borderWidth: 1 },
      }],
    };
  }, [visibleShipments]);

  const matrixVehicles = useMemo(() => [...new Map(visibleShipments.flatMap((shipment) => {
    const rows = shipment.candidates.map((candidate) => [candidate.vehicle_id, candidate.vehicle_registration_no] as [string, string]);
    if (shipment.assignment.assigned_vehicle_id && shipment.assignment.assigned_vehicle_registration) {
      rows.push([shipment.assignment.assigned_vehicle_id, shipment.assignment.assigned_vehicle_registration]);
    }
    return rows;
  })).entries()], [visibleShipments]);
  const timelineRows = result?.mt_timeline ?? [];
  const timelinePageCount = Math.max(1, Math.ceil(timelineRows.length / mtPerTimelinePage));
  const currentTimelinePage = Math.min(timelinePage, timelinePageCount);
  const paginatedTimelineRows = useMemo(() => {
    const start = (currentTimelinePage - 1) * mtPerTimelinePage;
    return timelineRows.slice(start, start + mtPerTimelinePage);
  }, [currentTimelinePage, mtPerTimelinePage, timelineRows]);
  const timelinePaginationPages = useMemo(
    () => [...new Set([1, currentTimelinePage - 1, currentTimelinePage, currentTimelinePage + 1, timelinePageCount])]
      .filter((page) => page >= 1 && page <= timelinePageCount)
      .sort((left, right) => left - right),
    [currentTimelinePage, timelinePageCount],
  );
  const timelineRangeStart = timelineRows.length === 0 ? 0 : (currentTimelinePage - 1) * mtPerTimelinePage + 1;
  const timelineRangeEnd = Math.min(currentTimelinePage * mtPerTimelinePage, timelineRows.length);

  useEffect(() => {
    setTimelinePage(1);
  }, [result?.id, mtPerTimelinePage]);

  function goToTimelinePage(page: number) {
    setTimelinePage(Math.min(Math.max(1, page), timelinePageCount));
  }

  const timelineOption = useMemo(() => {
    const vehicles = paginatedTimelineRows.map((row) => row.vehicle_registration_no);
    const data = paginatedTimelineRows.flatMap((row, vehicleIndex) => row.trips.map((trip) => ({
      value: [new Date(trip.start).getTime(), new Date(trip.next_available).getTime(), vehicleIndex],
      name: `${trip.trip_id} · ${trip.shipment_id}`,
      status: trip.status,
      returnTime: trip.return,
    })));
    return {
      tooltip: { formatter: (item: { data: { name: string; status: string; value: number[]; returnTime: string } }) => `${item.data.name}<br/>${dateTime(new Date(item.data.value[0]).toISOString())} → ${dateTime(new Date(item.data.value[1]).toISOString())}<br/>Return: ${dateTime(item.data.returnTime)}<br/>${item.data.status.replace(/_/g, " ")}` },
      grid: { left: 120, right: 24, top: 24, bottom: 48 },
      xAxis: { type: "time", axisLabel: { hideOverlap: true } },
      yAxis: { type: "category", data: vehicles },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18 }],
      series: [{
        type: "custom",
        renderItem: (_params: unknown, api: { value: (index: number) => number; coord: (value: number[]) => number[]; size: (value: number[]) => number[] }) => {
          const start = api.coord([api.value(0), api.value(2)]);
          const end = api.coord([api.value(1), api.value(2)]);
          const height = Math.max(10, api.size([0, 1])[1] * 0.55);
          return { type: "rect", shape: { x: start[0], y: start[1] - height / 2, width: Math.max(2, end[0] - start[0]), height }, style: { fill: "#0b73bf" } };
        },
        encode: { x: [0, 1], y: 2 },
        data,
      }],
    };
  }, [paginatedTimelineRows]);

  const hourlyDistributionOption = useMemo(() => {
    const rows = result?.hourly_distribution ?? [];
    return {
      color: ["#0b73bf", "#b8d211"],
      tooltip: {
        trigger: "axis",
        valueFormatter: (value: number) => `${Number(value).toLocaleString("id-ID", { maximumFractionDigits: 3 })} KL`,
      },
      legend: { data: ["KL tersalurkan per jam", "Kumulatif penyaluran"] },
      grid: { left: 72, right: 72, top: 56, bottom: rows.length > 24 ? 78 : 48 },
      xAxis: {
        type: "category",
        data: rows.map((row) => new Date(row.hour_start).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })),
        axisLabel: { hideOverlap: true, rotate: rows.length > 12 ? 35 : 0 },
      },
      yAxis: [
        { type: "value", name: "KL / jam", min: 0 },
        { type: "value", name: "Kumulatif KL", min: 0 },
      ],
      dataZoom: rows.length > 24 ? [{ type: "inside" }, { type: "slider", height: 18 }] : [],
      series: [
        {
          name: "KL tersalurkan per jam",
          type: "bar",
          barMaxWidth: 42,
          data: rows.map((row) => row.delivered_kl),
        },
        {
          name: "Kumulatif penyaluran",
          type: "line",
          yAxisIndex: 1,
          smooth: true,
          showSymbol: rows.length <= 48,
          symbolSize: 7,
          lineStyle: { width: 3 },
          data: rows.map((row) => row.cumulative_kl),
        },
      ],
    };
  }, [result]);

  return (
    <div className="space-y-5">
      {unassignedShipment && result && <UnassignedShipmentDialog key={`${result.id}-${unassignedShipment.id}`} runId={result.id} shipment={unassignedShipment} onClose={() => setUnassignedShipment(null)} />}
      {error && <div className="flex items-start justify-between border border-rust bg-rust/5 px-4 py-3 text-sm text-rust"><span>{error}</span><button onClick={() => setError(null)}><XCircle size={17} /></button></div>}

      {demoDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-petroink/50 p-4" role="dialog" aria-modal="true" aria-labelledby="demo-loading-order-title">
          <form className="w-full max-w-md border border-line bg-white p-5 shadow-xl" onSubmit={(event) => {
            event.preventDefault();
            const selectedDate = String(new FormData(event.currentTarget).get("loading_order_date") ?? "");
            setDemoLoadingOrderDate(selectedDate);
            void generateDemoLoadingOrders(selectedDate);
          }}>
            <div id="demo-loading-order-title" className="text-base font-semibold text-petroink">Buat Data Demo Loading Order</div>
            <p className="mt-2 text-sm text-slate-500">Pilih tanggal Loading Order dan masukkan total order kelipatan 8 KL. Sistem membuat satu Loading Order 8 KL per kompartemen dan hanya memilih SPBU aktif yang memiliki histori shipment cukup pada model Fase 5 terpilih. Jam LO tetap dibentuk berdasarkan shift model agar data demo dapat menguji shipment multi-SPBU tanpa UNSEEN_SPBU.</p>
            <label className="mt-5 grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Tanggal Loading Order
              <input autoFocus required className="border border-line px-3 py-2 text-base font-normal normal-case tracking-normal text-petroink" type="date" name="loading_order_date" defaultValue={demoLoadingOrderDate} />
            </label>
            <label className="mt-4 grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Total Order (KL)
              <input required className="border border-line px-3 py-2 text-base font-normal normal-case tracking-normal text-petroink" type="number" min="8" max="40000" step="8" value={demoTotalKl} onChange={(event) => setDemoTotalKl(event.target.value)} />
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="border border-line px-4 py-2 text-sm" disabled={demoLoading} onClick={() => setDemoDialogOpen(false)}>Batal</button>
              <button type="submit" className="inline-flex items-center gap-2 bg-petroblue px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={demoLoading}><Sparkles size={15} /> {demoLoading ? "Membuat…" : "Buat Data Demo"}</button>
            </div>
          </form>
        </div>
      )}

      {loadingOrderEditor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-petroink/50 p-4" role="dialog" aria-modal="true" aria-labelledby="loading-order-editor-title">
          <form className="w-full max-w-xl border border-line bg-white p-5 shadow-xl" onSubmit={(event) => { event.preventDefault(); void saveLoadingOrderEditor(); }}>
            <div id="loading-order-editor-title" className="text-base font-semibold text-petroink">
              {loadingOrderEditor.mode === "ADD" ? "Tambah Loading Order" : "Edit Loading Order"}
            </div>
            <p className="mt-2 text-sm text-slate-500">Setiap LO mewakili satu kompartemen dan wajib tepat 8 KL. Setelah disimpan, workbook aktif akan dibentuk ulang dan divalidasi backend.</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Nomor Loading Order
                <input autoFocus required className="border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={loadingOrderEditor.row.loading_order_no} onChange={(event) => setLoadingOrderEditor((current) => current ? { ...current, row: { ...current.row, loading_order_no: event.target.value } } : null)} />
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Shift ID / Nama
                <input className="border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={loadingOrderEditor.row.shift} onChange={(event) => setLoadingOrderEditor((current) => current ? { ...current, row: { ...current.row, shift: event.target.value } } : null)} />
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Shipment Start
                <input required className="border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" type="datetime-local" value={loadingOrderEditor.row.shipment_start_datetime} onChange={(event) => setLoadingOrderEditor((current) => current ? { ...current, row: { ...current.row, shipment_start_datetime: event.target.value } } : null)} />
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Nomor SPBU
                <select required className="border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={loadingOrderEditor.row.spbu_no} onChange={(event) => setLoadingOrderEditor((current) => current ? { ...current, row: { ...current.row, spbu_no: event.target.value } } : null)}>
                  <option value="">Pilih SPBU</option>
                  {loadingOrderEditor.row.spbu_no && !masterSpbus.some((spbu) => spbu.spbu_code === loadingOrderEditor.row.spbu_no) && <option value={loadingOrderEditor.row.spbu_no} disabled>{loadingOrderEditor.row.spbu_no} · Tidak tersedia pada master aktif</option>}
                  {masterSpbus.map((spbu) => <option key={spbu.spbu_id} value={spbu.spbu_code}>{spbu.spbu_code}{spbu.spbu_name ? ` · ${spbu.spbu_name}` : ""}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Product
                <select required className="border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={loadingOrderEditor.row.product} onChange={(event) => setLoadingOrderEditor((current) => current ? { ...current, row: { ...current.row, product: event.target.value } } : null)}>
                  <option value="">Pilih Product</option>
                  {loadingOrderEditor.row.product && !activeProducts.some((product) => product.product_name === loadingOrderEditor.row.product) && <option value={loadingOrderEditor.row.product} disabled>{loadingOrderEditor.row.product} · Tidak tersedia pada master aktif</option>}
                  {activeProducts.map((product) => <option key={product.product_id} value={product.product_name}>{product.product_name}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Order Quantity (KL)
                <input required className="border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" type="number" min="8" max="8" step="8" value={loadingOrderEditor.row.order_quantity_kl} onChange={(event) => setLoadingOrderEditor((current) => current ? { ...current, row: { ...current.row, order_quantity_kl: event.target.value } } : null)} />
              </label>
            </div>
            {loadingOrderEditorError && <div className="mt-4 border border-rust bg-rust/5 p-3 text-sm text-rust">{loadingOrderEditorError}</div>}
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="border border-line px-4 py-2 text-sm disabled:opacity-40" disabled={loadingOrderSaving} onClick={() => { setLoadingOrderEditor(null); setLoadingOrderEditorError(null); }}>Batal</button>
              <button type="submit" className="inline-flex items-center gap-2 bg-petroblue px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={loadingOrderSaving}>
                {loadingOrderSaving && <RefreshCw className="animate-spin" size={15} />}
                {loadingOrderSaving ? "Menyimpan…" : "Simpan Loading Order"}
              </button>
            </div>
          </form>
        </div>
      )}

      <section className="border border-line bg-white p-5">
        <div className="mb-4">
          <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">1. Prediction Setup</div>
          <p className="mt-1 text-xs text-slate-500">One depot and one saved Phase 5 model per auditable run. Phase 6 does not train models or optimize routes.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Depot
            <select className="border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={depotId} onChange={(event) => setDepotId(event.target.value)}>

              {depots.map((depot) => <option key={depot.depot_id} value={depot.depot_id}>{depot.depot_name}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Max Pairing Gap (min)
            <input className="border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" type="number" min="0" max="1440" step="15" value={maximumPairingGap} onChange={(event) => setMaximumPairingGap(event.target.value)} title="Default 90 menit; grup tetap harus lolos kapasitas, confidence, dan kelayakan rute." />
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Assignment Mode
            <select className="border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={assignmentMode} onChange={(event) => setAssignmentMode(event.target.value)}><option value="STRICT_START">Strict Start</option><option value="ALLOW_DELAY">Allow Delay</option></select>
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Max Delay (min)
            <input className="border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink disabled:bg-slate-50" type="number" min="0" max="1440" disabled={assignmentMode === "STRICT_START"} value={maximumDelay} onChange={(event) => setMaximumDelay(event.target.value)} />
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Prediction Model
            <select className="border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={modelId} onChange={(event) => setModelId(event.target.value)} disabled={!depotId}>
              <option value="">Select READY / ACTIVE Model</option>
              {models.map((model) => <option key={model.model_id} value={model.model_id}>{model.model_name} · v{model.model_version} · {model.model_status}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Minimum Pairing Confidence
            <input className="border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" type="number" min="0" max="1" step="0.05" value={minimumConfidence} onChange={(event) => setMinimumConfidence(event.target.value)} />
          </label>
        </div>
        {depotId && models.length === 0 && <div className="mt-4 border border-amber bg-amber/5 p-3 text-sm text-amber">No saved or active Phase 5 models are compatible with this depot.</div>}
      </section>

      {selectedModel && (
        <section className="border border-line bg-white p-5">
          <div className="mb-3 flex items-center justify-between"><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">2. Model Information</div><Badge value={selectedModel.model_status} /></div>
          <div className="grid gap-3 text-sm md:grid-cols-2 lg:grid-cols-4">
            {[
              ["Model ID", selectedModel.model_id], ["Model", `${selectedModel.model_name} v${selectedModel.model_version}`], ["Depot", selectedModel.depot_name],
              ["Training Period", `${selectedModel.training_start_date} — ${selectedModel.training_end_date}`], ["Created", selectedModel.created_at ?? "-"],
              ["Algorithm", selectedModel.algorithm], ["Training Shipments", selectedModel.number_of_training_shipments], ["SPBU", selectedModel.number_of_spbu],
              ["Clusters", selectedModel.number_of_clusters], ["Average Membership", pct(selectedModel.model_quality_metrics.average_membership_probability)],
            ].map(([label, value]) => <div key={String(label)}><div className="text-xs uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 break-words font-medium text-petroink">{value}</div></div>)}
          </div>
        </section>
      )}

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="border border-line bg-white p-5">
          <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">3. Loading Order Upload</div>
          <p className="mt-1 text-xs text-slate-500">Required: loading_order_no, shipment_start_datetime, spbu_no, product, dan order_quantity_kl. Tambahkan kolom shift sesuai Shift ID/nama di Master Depot. Shift wajib jika master shift depot sudah dikonfigurasi. Tanpa master shift, file lama tetap memakai shift snapshot model dan belum memiliki deadline operasional.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm" onClick={() => downloadFromApi("/api/v1/phase6/templates/loading-order", "phase6-loading-order-template.xlsx")}><Download size={15} /> Download Template</button>
            <button type="button" className="inline-flex items-center gap-2 border border-petroblue px-3 py-2 text-sm text-petroblue disabled:border-line disabled:text-slate-400" disabled={!modelId || demoLoading} onClick={() => setDemoDialogOpen(true)}><Sparkles size={15} /> Data Demo</button>
            <label className={`inline-flex cursor-pointer items-center gap-2 border px-3 py-2 text-sm ${modelId ? "border-petroblue text-petroblue" : "pointer-events-none border-line text-slate-400"}`}>
              <Upload size={15} /> {loadingOrderFile?.name ?? "Upload Excel"}
              <input className="hidden" type="file" accept=".xlsx" disabled={!modelId} onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                if (file) void loadLoadingOrderFile(file);
                event.currentTarget.value = "";
              }} />
            </label>
            {loValidation && <Badge value={loValidation.status} />}
          </div>
          {demoNotice && <div className="mt-3 text-xs text-mint">{demoNotice}</div>}
        </div>
        <div className="border border-line bg-white p-5">
          <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">4. MT Availability</div>
          <p className="mt-1 text-xs text-slate-500">Import MT aktif dari Master Data depot. ETA default mengikuti jam awal Shift 1 dan dapat diedit di MT Management.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="inline-flex items-center gap-2 border border-petroblue px-3 py-2 text-sm font-semibold text-petroblue disabled:border-line disabled:text-slate-400" disabled={!modelId || mtManagementLoading} onClick={() => void importMtFromMasterData()}>
              {mtManagementLoading ? <RefreshCw className="animate-spin" size={15} /> : <Database size={15} />}
              {mtManagementLoading ? "Mengimpor…" : "Import Data from Master Data"}
            </button>
            {mtValidation && <Badge value={mtValidation.status} />}
          </div>
          {mtManagementReady && <div className="mt-3 text-xs text-slate-500">{activeManagedMtCount.toLocaleString("id-ID")} dari {managedMts.length.toLocaleString("id-ID")} MT berstatus Active untuk prediction saat ini.</div>}
        </div>
      </section>

      {loadingOrderManagementReady && (
        <section className="border border-line bg-white p-5" aria-labelledby="loading-order-management-title">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div id="loading-order-management-title" className="text-sm font-semibold uppercase tracking-wide text-slate-600">3A. Loading Order Management</div>
              <p className="mt-1 text-xs text-slate-500">Edit, tambah, atau hapus LO sebelum prediction. Filter tersedia di setiap kolom; klik nama kolom untuk mengubah urutan sort.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {loValidation && <Badge value={loValidation.status} />}
              {loadingOrderSaving && <span className="inline-flex items-center gap-2 text-xs text-petroblue"><RefreshCw className="animate-spin" size={14} /> Memperbarui workbook…</span>}
              <button type="button" className="inline-flex items-center gap-2 bg-petroblue px-3 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={loadingOrderSaving} onClick={openNewLoadingOrderEditor}><Plus size={15} /> Add Loading Order</button>
            </div>
          </div>
          {loadingOrderManagementNotice && <div className="mt-4 border border-mint bg-mint/5 p-3 text-sm text-mint" aria-live="polite">{loadingOrderManagementNotice}</div>}
          <div className="mt-4 overflow-x-auto border border-line">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  {LOADING_ORDER_MANAGEMENT_COLUMNS.map((column) => (
                    <th key={column.field} className="min-w-48 px-3 py-2 align-top">
                      <button type="button" className="flex w-full items-center justify-between gap-2 text-left font-semibold hover:text-petroblue" onClick={() => toggleLoadingOrderSort(column.field)}>
                        <span>{column.label}</span>
                        {loadingOrderSort.field === column.field
                          ? loadingOrderSort.direction === "ASC" ? <ArrowUp size={14} aria-label="Urut naik" /> : <ArrowDown size={14} aria-label="Urut turun" />
                          : <ArrowUpDown size={14} aria-label="Belum diurutkan" />}
                      </button>
                      <input
                        aria-label={column.filterLabel}
                        className="mt-2 w-full border border-line bg-white px-2 py-1.5 text-xs font-normal normal-case tracking-normal text-petroink placeholder:text-slate-400"
                        placeholder={column.placeholder}
                        value={loadingOrderFilters[column.field]}
                        onChange={(event) => setLoadingOrderFilters((current) => ({ ...current, [column.field]: event.target.value }))}
                        onClick={(event) => event.stopPropagation()}
                      />
                    </th>
                  ))}
                  <th className="min-w-40 px-3 py-2 align-top"><span className="inline-flex h-6 items-center font-semibold">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {paginatedLoadingOrders.map((row) => (
                  <tr key={row.id} className="border-t border-line">
                    <td className="px-3 py-3 font-medium text-petroink">{row.loading_order_no || "—"}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-petroink">{row.shipment_start_datetime ? row.shipment_start_datetime.replace("T", " ") : "—"}</td>
                    <td className="px-3 py-3 text-petroink">{row.shift || "-"}</td>
                    <td className="px-3 py-3 text-petroink">{row.spbu_no || "—"}</td>
                    <td className="px-3 py-3 text-petroink">{row.product || "—"}</td>
                    <td className="px-3 py-3 tabular-nums text-petroink">{row.order_quantity_kl || "—"}</td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <button type="button" className="inline-flex items-center gap-1 border border-petroblue px-2 py-1 text-xs text-petroblue disabled:opacity-40" disabled={loadingOrderSaving} onClick={() => openEditLoadingOrderEditor(row)}><Pencil size={13} /> Edit</button>
                        <button type="button" className="inline-flex items-center gap-1 border border-rust px-2 py-1 text-xs text-rust disabled:opacity-40" disabled={loadingOrderSaving} onClick={() => void deleteManagedLoadingOrder(row)}><Trash2 size={13} /> Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {paginatedLoadingOrders.length === 0 && (
                  <tr><td colSpan={LOADING_ORDER_MANAGEMENT_COLUMNS.length + 1} className="px-4 py-10 text-center text-sm text-slate-500">Tidak ada Loading Order yang cocok dengan filter saat ini.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
            <div className="text-slate-500">
              {filteredLoadingOrders.length.toLocaleString("id-ID")} dari {managedLoadingOrders.length.toLocaleString("id-ID")} LO · Halaman {currentLoadingOrderPage} dari {loadingOrderPageCount}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-xs text-slate-500">
                Baris per halaman
                <select className="border border-line bg-white px-2 py-1.5 text-sm text-petroink" value={loadingOrdersPerPage} onChange={(event) => setLoadingOrdersPerPage(Number(event.target.value))}>
                  {[10, 25, 50, 100].map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
              <button type="button" className="border border-line px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-40" disabled={currentLoadingOrderPage <= 1} onClick={() => setLoadingOrderPage((page) => Math.max(1, page - 1))}>Sebelumnya</button>
              <button type="button" className="border border-line px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-40" disabled={currentLoadingOrderPage >= loadingOrderPageCount} onClick={() => setLoadingOrderPage((page) => Math.min(loadingOrderPageCount, page + 1))}>Berikutnya</button>
            </div>
          </div>
        </section>
      )}

      {mtManagementReady && (
        <section className="border border-line bg-white p-5" aria-labelledby="mt-management-title">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div id="mt-management-title" className="text-sm font-semibold uppercase tracking-wide text-slate-600">4A. MT Management</div>
              <p className="mt-1 text-xs text-slate-500">Status Active/Deactive hanya berlaku untuk input prediction ini dan tidak mengubah Master MT. ETA on Depot adalah waktu MT mulai available di depot.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {mtValidation && <Badge value={mtValidation.status} />}
              {mtManagementLoading && <span className="inline-flex items-center gap-2 text-xs text-petroblue"><RefreshCw className="animate-spin" size={14} /> Memperbarui MT availability…</span>}
            </div>
          </div>
          {mtManagementNotice && <div className="mt-4 border border-mint bg-mint/5 p-3 text-sm text-mint" aria-live="polite">{mtManagementNotice}</div>}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <label className="grid w-full max-w-sm gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Search MT
              <input className="border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink placeholder:text-slate-400" placeholder="Cari no MT, tag class, status, atau ETA…" value={mtSearch} onChange={(event) => setMtSearch(event.target.value)} />
            </label>
            <div className="text-sm text-slate-500"><strong className="text-petroink">{activeManagedMtCount.toLocaleString("id-ID")}</strong> Active · {(managedMts.length - activeManagedMtCount).toLocaleString("id-ID")} Deactive
              {selectedManagedMts.length > 0 && <span className="ml-3">{selectedManagedMts.length.toLocaleString("id-ID")} MT dipilih <button type="button" className="ml-2 text-petroblue underline disabled:opacity-40" disabled={mtManagementLoading} onClick={() => setSelectedMtIds(new Set())}>Hapus pilihan</button></span>}
            </div>
          </div>
          <div className="mt-4 overflow-x-auto border border-line">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-3"><input type="checkbox" aria-label="Pilih semua MT hasil pencarian, seluruh halaman" title="Pilih semua MT hasil pencarian, seluruh halaman" checked={allFilteredMtsSelected} disabled={mtManagementLoading || filteredManagedMts.length === 0} onChange={(event) => {
                    const checked = event.target.checked;
                    setSelectedMtIds((current) => {
                      const next = new Set(current);
                      filteredManagedMts.forEach((row) => checked ? next.add(row.id) : next.delete(row.id));
                      return next;
                    });
                  }} /></th>
                  <th className="px-3 py-3 font-semibold">No MT</th>
                  <th className="px-3 py-3 font-semibold">MT Tag Class</th>
                  <th className="px-3 py-3 font-semibold"><div className="flex items-center gap-2"><span>Status</span><button type="button" className="inline-flex items-center gap-1 whitespace-nowrap border border-line bg-white px-2 py-1 text-xs normal-case text-petroblue disabled:opacity-40" disabled={mtManagementLoading || managedMts.length === 0} onClick={() => openMtBulkAction("STATUS")}><Pencil size={12} /> Bulk Action</button></div></th>
                  <th className="min-w-64 px-3 py-3 font-semibold"><div className="flex items-center gap-2"><span>ETA on Depot</span><button type="button" className="inline-flex items-center gap-1 whitespace-nowrap border border-line bg-white px-2 py-1 text-xs normal-case text-petroblue disabled:opacity-40" disabled={mtManagementLoading || managedMts.length === 0} onClick={() => openMtBulkAction("ETA")}><Pencil size={12} /> Bulk Action</button></div></th>
                </tr>
              </thead>
              <tbody>
                {paginatedManagedMts.map((row) => (
                  <tr key={row.id} className="border-t border-line">
                    <td className="px-3 py-3"><input type="checkbox" aria-label={`Pilih MT ${row.vehicle_registration_no}`} checked={selectedMtIds.has(row.id)} disabled={mtManagementLoading} onChange={(event) => {
                      const checked = event.target.checked;
                      setSelectedMtIds((current) => {
                        const next = new Set(current);
                        if (checked) next.add(row.id); else next.delete(row.id);
                        return next;
                      });
                    }} /></td>
                    <td className="px-3 py-3 font-medium text-petroink">{row.vehicle_registration_no}</td>
                    <td className="px-3 py-3 text-petroink">
                      <div>{row.mt_tag_class}</div>
                      {row.eligibility_issues.length > 0 && <div className="mt-1 text-[11px] text-rust">{row.eligibility_issues.map((issue) => issue.replace(/_/g, " ")).join(" · ")}</div>}
                    </td>
                    <td className="px-3 py-3">
                      <select
                        aria-label={`Status ${row.vehicle_registration_no}`}
                        className={`border px-3 py-2 text-sm font-semibold ${row.status === "ACTIVE" ? "border-mint bg-mint/5 text-mint" : "border-rust bg-rust/5 text-rust"}`}
                        disabled={mtManagementLoading}
                        value={row.status}
                        onChange={(event) => void changeManagedMtStatus(row.id, event.target.value as ManagedMtAvailability["status"])}
                      >
                        <option value="ACTIVE">Active</option>
                        <option value="DEACTIVE">Deactive</option>
                      </select>
                    </td>
                    <td className="px-3 py-3">
                      <input
                        aria-label={`ETA on Depot ${row.vehicle_registration_no}`}
                        className="w-full border border-line px-3 py-2 text-sm text-petroink disabled:bg-slate-50 disabled:text-slate-400"
                        type="datetime-local"
                        disabled={mtManagementLoading}
                        value={row.eta_on_depot}
                        onChange={(event) => setManagedMts((current) => current.map((item) => item.id === row.id ? { ...item, eta_on_depot: event.target.value } : item))}
                        onBlur={() => void saveManagedMtEta(row.id)}
                      />
                    </td>
                  </tr>
                ))}
                {paginatedManagedMts.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-10 text-center text-sm text-slate-500">Tidak ada MT yang cocok dengan pencarian saat ini.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
            <div className="text-slate-500">
              {filteredManagedMts.length.toLocaleString("id-ID")} dari {managedMts.length.toLocaleString("id-ID")} MT · Halaman {currentMtPage} dari {mtPageCount}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-xs text-slate-500">
                Baris per halaman
                <select className="border border-line bg-white px-2 py-1.5 text-sm text-petroink" value={mtsPerPage} onChange={(event) => setMtsPerPage(Number(event.target.value))}>
                  {[10, 25, 50, 100].map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
              <button type="button" className="border border-line px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-40" disabled={currentMtPage <= 1} onClick={() => setMtPage((page) => Math.max(1, page - 1))}>Sebelumnya</button>
              <button type="button" className="border border-line px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-40" disabled={currentMtPage >= mtPageCount} onClick={() => setMtPage((page) => Math.min(mtPageCount, page + 1))}>Berikutnya</button>
            </div>
          </div>
        </section>
      )}

      {mtBulkAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-petroink/50 p-4" role="dialog" aria-modal="true" aria-labelledby="mt-bulk-action-title">
          <form className="w-full max-w-lg border border-line bg-white p-5 shadow-xl" onSubmit={(event) => { event.preventDefault(); void applyMtBulkAction(); }}>
            <h2 id="mt-bulk-action-title" className="text-lg font-semibold text-petroink">{mtBulkAction === "STATUS" ? "Bulk Status MT" : "Bulk ETA on Depot"}</h2>
            {error && <div className="mt-3 border border-rust bg-rust/5 p-3 text-sm text-rust" role="alert">{error}</div>}
            <label className="mt-4 grid gap-1 text-sm text-slate-600">Terapkan pada
              <select className="border border-line px-3 py-2 text-petroink" value={mtBulkScope} disabled={mtManagementLoading} onChange={(event) => setMtBulkScope(event.target.value as "SELECTED" | "FILTERED")}>
                <option value="SELECTED" disabled={selectedManagedMts.length === 0}>MT yang dipilih ({selectedManagedMts.length.toLocaleString("id-ID")})</option>
                <option value="FILTERED">Semua hasil pencarian ({filteredManagedMts.length.toLocaleString("id-ID")}) — seluruh halaman</option>
              </select>
            </label>
            {mtBulkAction === "STATUS" ? (
              <label className="mt-4 grid gap-1 text-sm text-slate-600">Status
                <select className="border border-line px-3 py-2 text-petroink" value={mtBulkStatus} disabled={mtManagementLoading} onChange={(event) => setMtBulkStatus(event.target.value as ManagedMtAvailability["status"])}>
                  <option value="ACTIVE">Active</option><option value="DEACTIVE">Deactive</option>
                </select>
              </label>
            ) : (
              <label className="mt-4 grid gap-1 text-sm text-slate-600">ETA on Depot
                <input className="border border-line px-3 py-2 text-petroink" type="datetime-local" required value={mtBulkEta} disabled={mtManagementLoading} onChange={(event) => setMtBulkEta(event.target.value)} />
              </label>
            )}
            <p className="mt-4 text-sm text-slate-500">{mtBulkTargets.length.toLocaleString("id-ID")} MT akan diperbarui dan input prediction akan divalidasi ulang.</p>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className="border border-line px-3 py-2 text-sm disabled:opacity-40" disabled={mtManagementLoading} onClick={() => setMtBulkAction(null)}>Batal</button>
              <button type="submit" className="bg-mint px-3 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={mtManagementLoading || mtBulkTargets.length === 0 || (mtBulkAction === "ETA" && !mtBulkEta)}>{mtManagementLoading ? "Menyimpan…" : "Terapkan"}</button>
            </div>
          </form>
        </div>
      )}

      {(loValidation || mtValidation) && (
        <section className="border border-line bg-white p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">5. Validation Result</div><p className="mt-1 text-xs text-slate-500">Prediction is blocked only by ERROR. WARNING remains reviewable.</p></div>
            <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-40" disabled={!loadingOrderFile || !mtFile} onClick={() => void downloadValidation()}><FileCheck2 size={15} /> Download Validation Report</button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <Metric label="Loading Orders" value={loValidation?.row_count ?? 0} />
            <Metric label="Order Volume" value={`${validatedOrderKl.toLocaleString("id-ID", { maximumFractionDigits: 3 })} KL`} />
            <Metric label="Unique SPBU" value={new Set((loValidation?.normalized_rows ?? []).map((row) => row.spbu_id)).size} />
            <Metric label="Available MT" value={mtValidation?.row_count ?? 0} />
            <Metric label="MT Capacity" value={`${validatedMtCapacityKl.toLocaleString("id-ID", { maximumFractionDigits: 3 })} KL`} />
            <Metric label="Derived Shifts" value={new Set(loValidation?.detected_shifts ?? []).size} />
            <Metric label="Errors" value={blockingErrors} />
            <Metric label="Warnings" value={warnings} />
          </div>
          {issues.length > 0 ? (
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr>{["File", "Row", "Field", "Status", "Error Code", "Description"].map((item) => <th key={item} className="px-3 py-2">{item}</th>)}</tr></thead>
                <tbody>{issues.map((issue, index) => <tr key={`${issue.file}-${issue.row}-${issue.error_code}-${index}`} className="border-t border-line"><td className="px-3 py-2">{issue.file}</td><td className="px-3 py-2">{issue.row}</td><td className="px-3 py-2">{issue.field}</td><td className="px-3 py-2"><Badge value={issue.status} /></td><td className="px-3 py-2 font-mono text-xs">{issue.error_code}</td><td className="px-3 py-2">{issue.description}</td></tr>)}</tbody>
              </table>
            </div>
          ) : <div className="mt-4 border border-mint bg-mint/5 p-3 text-sm text-mint">Both input files passed validation.</div>}
          <div className="mt-5">
            <div className="flex justify-end">
              <button className="inline-flex items-center gap-2 bg-petroblue px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40" disabled={!canRun || loading} onClick={() => void runPrediction()}>{loading ? <RefreshCw className="animate-spin" size={16} /> : <Play size={16} />} {loading ? "Mengirim Task…" : activeRuns.length > 0 ? `Kirim Prediction Baru (${activeRuns.length} aktif)` : "Run Prediction"}</button>
            </div>
            {runFeedback && (
              <div
                aria-live="polite"
                className={`mt-3 border p-3 text-sm ${
                  runFeedback.status === "SUCCESS"
                    ? "border-mint bg-mint/5 text-mint"
                    : runFeedback.status === "ERROR"
                      ? "border-rust bg-rust/5 text-rust"
                      : "border-amber bg-amber/5 text-amber"
                }`}
              >
                {runFeedback.message}
              </div>
            )}
          </div>
        </section>
      )}

      {!result && (
        <section className="border border-dashed border-line bg-white p-10 text-center">
          <div className="text-lg font-semibold text-petroink">Prediction workspace is empty</div>
          <p className="mx-auto mt-2 max-w-2xl text-sm text-slate-500">Select depot and prediction model, prepare Loading Orders, then import MT Availability from Master Data to start prediction.</p>
        </section>
      )}

      {result && (
        <>
          <section className="border border-line bg-white p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">6. Prediction Summary · {result.prediction_run_id}</div><p className="mt-1 text-xs text-slate-500">Completed in {result.durations_ms.total} ms · model and input snapshots retained.</p></div><Badge value={result.status} /></div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
              <Metric label="Loading Orders" value={result.summary.loading_orders} /><Metric label="Order Volume" value={`${result.summary.total_order_kl.toLocaleString("id-ID", { maximumFractionDigits: 3 })} KL`} /><Metric label="Unique SPBU" value={result.summary.unique_spbu} /><Metric label="Shipments" value={result.summary.predicted_shipments} /><Metric label="Available MT" value={result.summary.available_mt} />
              <Metric label="Assigned Shipments" value={result.summary.assigned_shipments} /><Metric label="Assigned LO" value={result.summary.assigned_loading_orders} /><Metric label="Assigned Volume" value={`${result.summary.assigned_order_kl.toLocaleString("id-ID")} KL`} /><Metric label="Delayed" value={result.summary.assigned_with_delay} /><Metric label="Unassigned Shipments" value={result.summary.unassigned_shipments} /><Metric label="Multi-Trip MT" value={result.summary.multi_trip_mt} /><Metric label="Drive Fallback" value={result.summary.fallback_trips} /><Metric label="Avg MT" value={pct(result.summary.average_mt_assignment_confidence)} />
            </div>
            {Array.isArray(result.model.capacity_iteration_summary) && (
              <div className="mt-4 border border-petroblue/30 bg-petroblue/5 p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-petroblue">Iterasi Kapasitas 32 → 24 → 16 → 8 KL</div>
                <div className="mt-1 text-xs text-slate-500">Exact full-load wajib: kapasitas shipment harus sama dengan kapasitas MT. Partial load tidak digunakan.</div>
                <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  {(result.model.capacity_iteration_summary as CapacityIteration[]).map((row) => (
                    <div key={row.tier_capacity_kl} className="border border-petroblue/20 bg-white p-3 text-xs">
                      <div className="font-semibold text-petroink">{row.tier_capacity_kl} KL · {row.tier_compartments} LO</div>
                      <div className="mt-1 text-slate-500">Assigned {row.assigned_shipments} shipment / {row.assigned_loading_orders} LO</div>
                      <div className="mt-1 text-slate-400">Diteruskan ke tier berikutnya: {row.carried_forward_loading_orders} LO</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="mt-4 overflow-x-auto"><table className="min-w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr>{["Derived Shift", "LO", "Volume (KL)", "SPBU", "Predicted Shipment", "Assigned", "Unassigned"].map((item) => <th key={item} className="px-3 py-2">{item}</th>)}</tr></thead><tbody>{result.summary_by_shift.map((row) => <tr key={String(row.shift_id)} className="border-t border-line"><td className="px-3 py-2 font-medium">{row.shift}</td><td className="px-3 py-2">{row.loading_orders}</td><td className="px-3 py-2">{row.total_order_kl}</td><td className="px-3 py-2">{row.unique_spbu}</td><td className="px-3 py-2">{row.predicted_shipments}</td><td className="px-3 py-2">{row.assigned}</td><td className="px-3 py-2">{row.unassigned}</td></tr>)}</tbody></table></div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500"><span>Routes calls: {result.routing_metrics.google_routes_request_count ?? 0}</span><span>· Cache hits: {result.routing_metrics.google_routes_cache_hit_count ?? 0}</span><span>· Cache misses: {result.routing_metrics.google_routes_cache_miss_count ?? 0}</span></div>
          </section>

          <section className="border border-line bg-white p-5">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
              <div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">7–8. Predicted Shipment & MT Assignment Result</div><div className="mt-3 flex flex-wrap gap-2"><button className={`border px-3 py-1 text-sm ${shiftTab === "ALL" ? "border-petroblue bg-petroblue text-white" : "border-line"}`} disabled={resultPageLoading} onClick={() => changeShipmentShift("ALL")}>All</button>{shifts.map((shift) => <button key={String(shift.shift_id)} className={`border px-3 py-1 text-sm ${shiftTab === shift.shift_id ? "border-petroblue bg-petroblue text-white" : "border-line"}`} disabled={resultPageLoading} onClick={() => changeShipmentShift(String(shift.shift_id))}>{shift.shift}</button>)}</div></div>
              <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Rows per page
                <select className="border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={shipmentsPerPage} disabled={resultPageLoading} onChange={(event) => changeShipmentsPerPage(Number(event.target.value))}>
                  {[25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
                </select>
              </label>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr>{["", "Trip", "MT", "Shipment / SPBU", "Planned Start", "Predicted Departure", "Estimated Return", "Next Available", "Confidence", "Status"].map((item, index) => <th key={`${item}-${index}`} className="px-3 py-2">{item}</th>)}</tr></thead>
                <tbody>{paginatedShipments.map((shipment) => (
                  <Fragment key={shipment.id}>
                    <tr className="border-t border-line align-top">
                      <td className="px-3 py-3"><button aria-label={`${expanded === shipment.id ? "Tutup" : "Buka"} detail ${shipment.predicted_shipment_id}`} onClick={() => void toggleShipmentDetail(shipment)}>{expanded === shipment.id ? <ChevronDown size={17} /> : <ChevronRight size={17} />}</button></td>
                      <td className="px-3 py-3 font-mono text-xs">{shipment.trip?.trip_id ?? "—"}<div className="mt-1 text-slate-400">#{shipment.trip?.trip_number ?? "—"}</div></td><td className="px-3 py-3">{shipment.assignment.assigned_vehicle_registration ?? "—"}{shipment.assignment.assigned_vehicle_capacity_kl !== null && <div className="mt-1 text-xs text-slate-400">{shipment.assignment.assigned_vehicle_capacity_kl} KL · {shipment.assignment.assigned_vehicle_compartments} compartment</div>}</td><td className="px-3 py-3"><div className="font-mono text-xs">{shipment.predicted_shipment_id}</div><div className="mt-1">{shipment.lines.map((line) => line.spbu_no).join(" → ")}</div><div className="mt-1 text-xs text-slate-400">{shipment.lines.length} LO · {shipment.total_order_kl} KL · {shipment.required_compartments} compartment</div></td><td className="whitespace-nowrap px-3 py-3">{dateTime(shipment.planned_start_datetime)}<div className="mt-1 text-xs text-slate-400">{shipment.shift}</div></td><td className="whitespace-nowrap px-3 py-3">{dateTime(shipment.trip?.predicted_departure_datetime)}{Boolean(shipment.trip?.delay_minutes) && <div className="mt-1 text-xs text-amber">+{shipment.trip?.delay_minutes} min</div>}</td><td className="whitespace-nowrap px-3 py-3">{dateTime(shipment.trip?.estimated_return_datetime)}</td><td className="whitespace-nowrap px-3 py-3">{dateTime(shipment.trip?.next_available_datetime)}</td><td className="px-3 py-3"><div>{pct(shipment.shipment_prediction_score)} / {pct(shipment.assignment.mt_assignment_score)}</div>{shipment.trip?.routing_confidence && <Badge value={shipment.trip.routing_confidence} />}</td><td className="px-3 py-3">{shipment.assignment.assignment_status === "UNASSIGNED" ? <button type="button" aria-haspopup="dialog" title="Klik untuk melihat alasan unassigned" className="rounded focus:ring-2 focus:ring-petroblue" onClick={() => setUnassignedShipment(shipment)}><Badge value={shipment.assignment.assignment_status} /><span className="mt-1 block text-xs text-petroblue underline">Lihat alasan</span></button> : <Badge value={shipment.assignment.assignment_status} />}{shipment.trip?.fallback_used && <div className="mt-1"><Badge value="ROUTE_FALLBACK" /></div>}{shipment.assignment.unassigned_reason && <div className="mt-1 text-xs text-rust">{shipment.assignment.unassigned_reason.replace(/_/g, " ")}</div>}</td>
                    </tr>
                    {expanded === shipment.id && (
                      <tr key={`${shipment.id}-detail`} className="border-t border-line bg-slate-50/60"><td colSpan={10} className="p-4">
                        <div className="grid gap-5 xl:grid-cols-2">
                          <div>
                            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Loading Orders & Shipment Override</div>
                            <div className="mt-2 border border-petroblue/30 bg-petroblue/5 p-3 text-xs text-petroblue"><strong>{shipment.predicted_shipment_id}</strong> · {shipment.total_order_kl} KL · {shipment.required_compartments} × {shipment.compartment_unit_kl} KL compartment · {spbuClusterText(shipment.lines)}</div>
                            <div className="mt-2 space-y-2">{shipment.lines.map((line) => (
                              <div key={line.id} className="flex flex-wrap items-center justify-between gap-2 border border-line bg-white p-3 text-sm"><div><span className="font-medium">{line.loading_order_no}</span> · SPBU {line.spbu_no} · {clusterText(line)} {line.spbu_name && `· ${line.spbu_name}`} {line.product_name && `· Product ${line.product_name}`} {line.order_quantity_kl !== null && `· ${line.order_quantity_kl} KL`}<div className="mt-1 text-[11px] text-slate-400">Ready: {dateTime(line.shipment_start_datetime)} · Model layer: {line.model_predicted_shipment_id}</div></div><div className="flex flex-wrap gap-2"><button className="inline-flex items-center gap-1 border border-line px-2 py-1 text-xs" disabled={shipment.lines.length === 1 || loading} onClick={() => void adjustShipment(shipment, "SPLIT_SINGLE", [line.id])}><Split size={13} /> New single</button><select className="max-w-[30rem] border border-line bg-white px-2 py-1 text-xs" value={moveTargets[line.id] ?? ""} onChange={(event) => setMoveTargets((current) => ({ ...current, [line.id]: event.target.value }))}><option value="">Move to…</option>{result.shipment_options.filter((item) => item.shift_id === shipment.shift_id && item.id !== shipment.id).map((item) => <option key={item.id} value={item.id}>{item.predicted_shipment_id} · {spbuClusterText(item.spbus)}</option>)}</select><button className="border border-line px-2 py-1 text-xs disabled:opacity-40" disabled={!moveTargets[line.id] || loading} onClick={() => void adjustShipment(shipment, "MOVE_LINES", [line.id], moveTargets[line.id])}>Move</button></div></div>
                            ))}</div>
                            <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Structured Shipment Explanation</div>
                            <dl className="mt-2 grid gap-2 sm:grid-cols-2">{explanationRows(shipment.explanation).map(([key, value]) => <div key={key} className="border border-line bg-white p-2"><dt className="text-[11px] uppercase text-slate-400">{key.replace(/_/g, " ")}</dt><dd className="mt-1 text-xs">{String(value)}</dd></div>)}</dl>
                            {shipment.trip && <div className="mt-4 border border-line bg-white p-3 text-xs"><div className="font-semibold uppercase tracking-wide text-slate-500">Preliminary Route Estimate</div><div className="mt-2 grid gap-2 sm:grid-cols-2"><span>Sequence: {shipment.trip.estimated_visit_sequence.join(" → ") || "—"}</span><span>Mode: {shipment.trip.routing_mode ?? "—"}</span><span>Distance: {shipment.trip.route_distance_meters === null ? "—" : `${(shipment.trip.route_distance_meters / 1000).toFixed(1)} km`}</span><span>Travel: {durationMinutes(shipment.trip.route_duration_seconds)}</span><span>Service: {durationMinutes(shipment.trip.service_duration_seconds)}</span><span>Cycle: {durationMinutes(shipment.trip.total_cycle_duration_seconds)}</span><span>Source: {shipment.trip.route_estimation_source ?? "—"}</span></div>{shipment.trip.fallback_used && <div className="mt-3 border border-amber bg-amber/5 p-2 text-amber"><strong>ROUTE ESTIMATE FALLBACK.</strong> Google Routes was unavailable, so historical or configured travel estimates were used.</div>}</div>}
                          </div>
                          <div>
                            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recommended MT & Change MT</div>
                            <input className="mt-2 w-full border border-line bg-white px-3 py-2 text-sm" placeholder="Optional override reason" value={overrideReason[shipment.id] ?? ""} onChange={(event) => setOverrideReason((current) => ({ ...current, [shipment.id]: event.target.value }))} />
                            {candidateLoadingShipment === shipment.id && <div className="mt-2 flex items-center gap-2 border border-petroblue/30 bg-petroblue/5 p-3 text-xs text-petroblue" role="status"><RefreshCw className="animate-spin" size={14} /> Memuat kandidat MT saat detail dibuka…</div>}
                            <div className="mt-2 overflow-x-auto"><table className="min-w-full bg-white text-left text-xs"><thead><tr className="border-b border-line text-slate-500"><th className="p-2">Rank</th><th className="p-2">MT</th><th className="p-2">Capacity</th><th className="p-2">Score</th><th className="p-2">Compatibility</th><th className="p-2">Action</th></tr></thead><tbody>{shipment.candidates.filter((candidate) => candidate.compatibility_status === "PASS").map((candidate) => <tr key={candidate.id} className="border-b border-line"><td className="p-2">{candidate.candidate_rank}</td><td className="p-2">{candidate.vehicle_registration_no}</td><td className="p-2">{candidate.capacity_kl ?? "—"} KL · {candidate.number_of_compartments ?? "—"} compartment</td><td className="p-2">{pct(candidate.prediction_score)}</td><td className="p-2"><Badge value="PASS" /></td><td className="p-2"><button className="border border-petroblue px-2 py-1 text-petroblue disabled:opacity-40" disabled={candidate.vehicle_id === shipment.assignment.assigned_vehicle_id || loading} onClick={() => void applyAssignmentOverride(shipment, candidate.vehicle_id)}>Change MT</button></td></tr>)}</tbody></table></div>
                            <ExcludedCandidateDropdown candidates={shipment.candidates} />
                          </div>
                        </div>
                      </td></tr>
                    )}
                  </Fragment>
                ))}</tbody>
              </table>
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 text-sm">
              <div className="text-slate-500">Showing {shipmentRangeStart.toLocaleString("id-ID")}–{shipmentRangeEnd.toLocaleString("id-ID")} of {(result?.shipment_pagination.total ?? 0).toLocaleString("id-ID")} shipments {resultPageLoading && "· memuat halaman…"}</div>
              <div className="flex items-center gap-1">
                <button className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-40" disabled={currentShipmentPage === 1 || resultPageLoading} onClick={() => goToShipmentPage(currentShipmentPage - 1)}>Previous</button>
                {shipmentPaginationPages.map((page, index) => (
                  <span key={page} className="contents">
                    {index > 0 && page - shipmentPaginationPages[index - 1] > 1 && <span className="px-1 text-slate-400">…</span>}
                    <button className={`min-w-9 border px-3 py-2 disabled:opacity-40 ${page === currentShipmentPage ? "border-petroblue bg-petroblue text-white" : "border-line"}`} disabled={resultPageLoading} aria-current={page === currentShipmentPage ? "page" : undefined} onClick={() => goToShipmentPage(page)}>{page}</button>
                  </span>
                ))}
                <button className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-40" disabled={currentShipmentPage === shipmentPageCount || resultPageLoading} onClick={() => goToShipmentPage(currentShipmentPage + 1)}>Next</button>
              </div>
            </div>
          </section>

          <section className="grid gap-5 xl:grid-cols-2">
            <div className="border border-line bg-white p-5 xl:col-span-2">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">MT Multi-Trip Timeline</div><p className="mt-1 text-xs text-slate-500">Each bar runs from predicted departure through the turnaround buffer. Bars for one MT must not overlap.</p></div>
                <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  MT per page
                  <select className="border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={mtPerTimelinePage} onChange={(event) => setMtPerTimelinePage(Number(event.target.value))}>
                    {[10, 25, 50].map((size) => <option key={size} value={size}>{size}</option>)}
                  </select>
                </label>
              </div>
              {timelineRows.length ? (
                <>
                  <ReactECharts option={timelineOption} style={{ height: Math.max(280, paginatedTimelineRows.length * 64) }} />
                  <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 text-sm">
                    <div className="text-slate-500">Showing {timelineRangeStart.toLocaleString("id-ID")}–{timelineRangeEnd.toLocaleString("id-ID")} of {timelineRows.length.toLocaleString("id-ID")} MT</div>
                    <div className="flex items-center gap-1">
                      <button className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-40" disabled={currentTimelinePage === 1} onClick={() => goToTimelinePage(currentTimelinePage - 1)}>Previous MT</button>
                      {timelinePaginationPages.map((page, index) => (
                        <span key={page} className="contents">
                          {index > 0 && page - timelinePaginationPages[index - 1] > 1 && <span className="px-1 text-slate-400">…</span>}
                          <button className={`min-w-9 border px-3 py-2 ${page === currentTimelinePage ? "border-petroblue bg-petroblue text-white" : "border-line"}`} aria-label={`MT timeline page ${page}`} aria-current={page === currentTimelinePage ? "page" : undefined} onClick={() => goToTimelinePage(page)}>{page}</button>
                        </span>
                      ))}
                      <button className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-40" disabled={currentTimelinePage === timelinePageCount} onClick={() => goToTimelinePage(currentTimelinePage + 1)}>Next MT</button>
                    </div>
                  </div>
                </>
              ) : <div className="mt-5 border border-dashed border-line p-6 text-center text-sm text-slate-500">No assigned trip timeline.</div>}
            </div>
            <div className="border border-line bg-white p-5"><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">9A. Shipment Prediction Network</div><p className="mt-1 text-xs text-slate-500">Nodes are SPBU; edges mean predicted same shipment; thickness is model confidence. This is not a route map.</p><ReactECharts option={networkOption} style={{ height: 360 }} /></div>
            <div className="border border-line bg-white p-5"><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">9B. MT Assignment Matrix</div><p className="mt-1 text-xs text-slate-500">Scores are Phase 4 affinity evidence before rolling-time eligibility; X is master-incompatible; outlined cell is assigned.</p><div className="mt-4 max-h-[360px] overflow-auto"><table className="min-w-full text-center text-xs"><thead className="sticky top-0 bg-white"><tr><th className="p-2 text-left">Shipment</th>{matrixVehicles.map(([id, registration]) => <th key={id} className="p-2">{registration}</th>)}</tr></thead><tbody>{visibleShipments.map((shipment) => <tr key={shipment.id} className="border-t border-line"><th className="whitespace-nowrap p-2 text-left">{shipment.predicted_shipment_id}</th>{matrixVehicles.map(([vehicleId]) => {
              const candidate = shipment.candidates.find((item) => item.vehicle_id === vehicleId);
              const assigned = shipment.assignment.assigned_vehicle_id === vehicleId;
              return <td key={vehicleId} className={`p-2 ${assigned ? "outline outline-2 outline-petroblue" : ""}`} style={{ backgroundColor: candidate?.compatibility_status === "PASS" ? `rgba(184,210,17,${Math.max(0.08, candidate.prediction_score)})` : undefined }}>{candidate ? candidate.compatibility_status === "FAIL" ? "X" : pct(candidate.prediction_score) : "—"}</td>;
            })}</tr>)}</tbody></table></div></div>
          </section>

          <section className="grid gap-5">
            <div className="border border-line bg-white p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">10A. Penyaluran KL per Jam & Kumulatif</div>
                  <p className="mt-1 text-xs text-slate-500">Hanya assigned shipment, dikelompokkan berdasarkan predicted departure pada zona waktu depot. Manual assignment dan perubahan shipment menghitung ulang grafik ini bersama jadwal multi-trip.</p>
                </div>
                <div className="border border-line bg-slate-50 px-4 py-2 text-right text-xs text-slate-500"><span className="block uppercase tracking-wide">Total assigned</span><strong className="mt-1 block text-lg text-petroink">{result.summary.assigned_order_kl.toLocaleString("id-ID", { maximumFractionDigits: 3 })} KL</strong></div>
              </div>
              {result.hourly_distribution.length > 0
                ? <ReactECharts option={hourlyDistributionOption} style={{ height: 430 }} />
                : <div className="mt-4 border border-dashed border-line p-6 text-center text-sm text-slate-500">Belum ada assigned shipment untuk dihitung.</div>}
            </div>
            <GeographicMTRouteMap payload={result.geographic_routes} runId={result.id} />
          </section>
        </>
      )}

      <section className="border border-line bg-white p-5">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">11. Prediction Run History</div><p className="mt-1 text-xs text-slate-500">View and export immutable runs, or create a new run from an input snapshot.</p>{historyFeedback && <p className={`mt-2 text-xs ${historyFeedback.status === "SUCCESS" ? "text-mint" : "text-rust"}`} role="status" aria-live="polite">{historyFeedback.message}</p>}</div>
          <div className="flex flex-wrap items-center gap-3">
            {history.length > 0 && <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Rows per page<select aria-label="History rows per page" className="border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-petroink" value={historyPerPage} onChange={(event) => changeHistoryPerPage(Number(event.target.value))}>{[10, 25, 50].map((size) => <option key={size} value={size}>{size}</option>)}</select></label>}
            {depotId && <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:cursor-wait disabled:opacity-50" disabled={historyRefreshing} onClick={() => void refreshHistory()}><RefreshCw className={historyRefreshing ? "animate-spin" : ""} size={14} /> {historyRefreshing ? "Memperbarui…" : "Refresh"}</button>}
          </div>
        </div>
        {history.length === 0 ? <div className="border border-dashed border-line p-6 text-center text-sm text-slate-500">No prediction runs for the selected depot.</div> : <>
          <div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr>{["Run ID", "Date", "Status", "Depot", "Model", "LO", "Shipment", "Assigned", "Unassigned", "User", "Actions"].map((item) => <th key={item} className="px-3 py-2">{item}</th>)}</tr></thead><tbody>{paginatedHistory.map((row) => <tr key={row.id} className="border-t border-line"><td className="px-3 py-2 font-mono text-xs">{row.prediction_run_id}</td><td className="px-3 py-2">{new Date(row.date).toLocaleString()}</td><td className="px-3 py-2"><Badge value={row.status} />{["QUEUED", "RUNNING"].includes(row.status) && <div className="mt-1 whitespace-nowrap text-[11px] text-slate-500">Attempt {Math.max(1, row.attempt_count)}/{Math.max(1, row.max_attempts)}{row.heartbeat_at ? ` · heartbeat ${new Date(row.heartbeat_at).toLocaleTimeString("id-ID")}` : ""}</div>}</td><td className="px-3 py-2">{row.depot}</td><td className="px-3 py-2">{row.model}</td><td className="px-3 py-2">{row.loading_orders}</td><td className="px-3 py-2">{row.shipments}</td><td className="px-3 py-2">{row.assigned}</td><td className="px-3 py-2">{row.unassigned}</td><td className="px-3 py-2">{row.user}</td><td className="px-3 py-2"><div className="flex gap-2"><button title="View" className="border border-line p-2" onClick={() => void openHistory(row.id)}><Eye size={14} /></button><button title="Download" className="border border-line p-2 disabled:opacity-40" disabled={row.status !== "COMPLETED"} onClick={() => downloadFromApi(`/api/v1/phase6/predictions/${row.id}/export`, `${row.prediction_run_id}.xlsx`)}><Download size={14} /></button><button title={row.status === "FAILED" ? "Retry from saved input" : "Duplicate / Re-run"} className="border border-line p-2 disabled:opacity-40" disabled={!(["COMPLETED", "FAILED"].includes(row.status)) || loading} onClick={() => void rerun(row.id)}><RefreshCw size={14} /></button></div></td></tr>)}</tbody></table></div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 text-sm">
            <div className="text-slate-500">Showing {historyRangeStart.toLocaleString("id-ID")}–{historyRangeEnd.toLocaleString("id-ID")} of {history.length.toLocaleString("id-ID")} runs</div>
            <div className="flex items-center gap-1">
              <button className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-40" disabled={currentHistoryPage === 1} onClick={() => goToHistoryPage(currentHistoryPage - 1)}>Previous</button>
              {historyPaginationPages.map((page, index) => <span key={page} className="contents">{index > 0 && page - historyPaginationPages[index - 1] > 1 && <span className="px-1 text-slate-400">…</span>}<button className={`min-w-9 border px-3 py-2 ${page === currentHistoryPage ? "border-petroblue bg-petroblue text-white" : "border-line"}`} aria-label={`Prediction history page ${page}`} aria-current={page === currentHistoryPage ? "page" : undefined} onClick={() => goToHistoryPage(page)}>{page}</button></span>)}
              <button className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-40" disabled={currentHistoryPage === historyPageCount} onClick={() => goToHistoryPage(currentHistoryPage + 1)}>Next</button>
            </div>
          </div>
        </>}
      </section>

      <section className="border border-line bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">12. Export Result</div><p className="mt-1 text-xs text-slate-500">Summary, Shipment Result, MT Assignment, MT Candidates, and Validation sheets.</p></div><button className="inline-flex items-center gap-2 bg-petroblue px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" disabled={!result} onClick={() => result && downloadFromApi(`/api/v1/phase6/predictions/${result.id}/export`, `${result.prediction_run_id}.xlsx`)}><Download size={16} /> Export Prediction Result</button></div>
      </section>
    </div>
  );
}
