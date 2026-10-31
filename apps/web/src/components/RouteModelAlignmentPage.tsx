import ReactECharts from "echarts-for-react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Eye,
  GitCompareArrows,
  Info,
  Layers3,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiGet, apiSend } from "../lib/api";


type Depot = {
  depot_id: string;
  depot_code: string | null;
  depot_name: string;
};

type RouteOption = {
  route_version_id: string;
  version_number: number;
  version_label: string;
  job_no: string;
  job_name: string;
  operating_date: string;
  created_at: string | null;
  solver_status: string;
  is_current: boolean;
  source_prediction_run_no: string | null;
  source_model_name: string | null;
  source_model_version: number | null;
  trip_count: number;
  lo_count: number;
  routed_lo_count: number;
  dropped_lo_count: number;
  lineage_status: "READY" | "DISABLED";
  lineage_reason: string | null;
};

type Metric = {
  score_pct: number | null;
  status: string;
  evaluated_observations: number;
  total_relevant_observations: number;
  coverage_pct: number;
  source: string;
  resolution_method: string;
  distribution: Array<{ label: string; count: number }>;
};

type MetricKey = "cluster_cohesion" | "shift_alignment" | "historical_spbu_pairing" | "historical_mt_affinity";

type Evaluation = {
  evaluation_run_id: string;
  evaluation_run_no: string;
  depot_id: string;
  job_id: string;
  route_version_id: string;
  operating_date: string;
  status: string;
  source_bundle_checksum: string;
  algorithm_version: string;
  created_at: string | null;
  completed_at: string | null;
  source_bundle: {
    status?: string;
    lineage?: Record<string, string | number | null>;
    historical_scope?: Record<string, string | null>;
    components?: Record<string, { source: string; resolution_method: string; record_count: number }>;
    saved_analysis_links?: Record<string, string | null>;
  };
  summary: {
    note?: string;
    metrics?: Record<MetricKey, Metric>;
    scope?: {
      total_lo: number;
      routed_lo: number;
      dropped_or_unassigned_lo: number;
      trip_count: number;
      unique_spbu_count: number;
      assigned_mt_count: number;
      unique_trip_spbu_observations: number;
      unique_spbu_pairs: number;
    };
  };
  data_quality: {
    assignment_status_counts?: Record<string, number>;
    cluster?: { evaluable_pairs: number; same_cluster_pairs: number; total_pairs: number };
    bundle_status?: string;
    component_resolution?: Record<string, string>;
  };
};

type EvaluationRow = {
  evaluation_row_id: string;
  loading_order_id: string;
  shipment_id: string | null;
  trip_number: number | null;
  stop_sequence: number | null;
  assignment_status: string;
  planned_gate_out: string | null;
  spbu_code: string | null;
  spbu_name: string | null;
  product_name: string | null;
  volume_kl: number;
  vehicle_registration: string | null;
  cluster_label: string | null;
  route_shift_name: string | null;
  cluster_cohesion_score: number | null;
  cluster_cohesion_status: string;
  shift_alignment_score: number | null;
  shift_alignment_status: string;
  spbu_pairing_score: number | null;
  spbu_pairing_status: string;
  mt_affinity_score: number | null;
  mt_affinity_status: string;
  evaluable_category_count: number;
};

type EvaluationRowDetail = EvaluationRow & {
  cluster_evidence: Record<string, unknown>;
  shift_evidence: Record<string, unknown>;
  pairing_evidence: Record<string, unknown>;
  mt_affinity_evidence: Record<string, unknown>;
};

type RowsResponse = {
  total: number;
  page: number;
  page_size: number;
  page_count: number;
  search: string;
  sort_by: string;
  sort_direction: "asc" | "desc";
  rows: EvaluationRow[];
};

type TripRow = {
  route_version_trip_id: string;
  shipment_id: string;
  vehicle_registration: string | null;
  trip_number: number;
  gate_out: string | null;
  route_shift: string | null;
  loading_order_numbers: string[];
  spbu_numbers: string[];
  spbu_names: string[];
  unique_spbu_count: number;
  lo_count: number;
  cluster_cohesion_score: number | null;
  shift_alignment_score: number | null;
  spbu_pairing_score: number | null;
  mt_affinity_score: number | null;
  evaluable_category_count: number;
};

type TripsResponse = {
  total: number;
  page: number;
  page_size: number;
  page_count: number;
  search: string;
  sort_by: string;
  sort_direction: "asc" | "desc";
  rows: TripRow[];
};

type TripSortKey =
  | "shipment_id"
  | "trip_number"
  | "gate_out"
  | "vehicle_registration"
  | "route_shift"
  | "loading_order_number"
  | "spbu_number"
  | "lo_count"
  | "unique_spbu_count"
  | "cluster_cohesion"
  | "shift_alignment"
  | "spbu_pairing"
  | "mt_affinity"
  | "evidence_coverage";

type SortKey =
  | "loading_order_id"
  | "status"
  | "shipment_id"
  | "trip_number"
  | "planned_gate_out"
  | "spbu"
  | "product"
  | "volume_kl"
  | "assigned_mt"
  | "cluster"
  | "cluster_cohesion"
  | "shift_alignment"
  | "spbu_pairing"
  | "mt_affinity"
  | "evidence_coverage";


const metricDefinitions: Array<{ key: MetricKey; label: string; shortLabel: string; description: string }> = [
  {
    key: "cluster_cohesion",
    label: "Cluster Cohesion",
    shortLabel: "Cluster",
    description: "Proporsi pasangan SPBU dalam trip yang berada pada cluster model Fase 5 yang sama.",
  },
  {
    key: "shift_alignment",
    label: "Shift Alignment",
    shortLabel: "Shift",
    description: "Porsi historis keberangkatan SPBU pada shift yang sama dengan gate-out route.",
  },
  {
    key: "historical_spbu_pairing",
    label: "Historical SPBU Pairing",
    shortLabel: "SPBU Pairing",
    description: "Rata-rata probabilitas dua arah pasangan SPBU yang ditempatkan dalam shipment yang sama.",
  },
  {
    key: "historical_mt_affinity",
    label: "Historical MT Affinity",
    shortLabel: "MT Affinity",
    description: "Porsi shipment historis SPBU yang pernah dilayani MT route yang sama.",
  },
];

const scoreFields: Record<MetricKey, keyof EvaluationRow> = {
  cluster_cohesion: "cluster_cohesion_score",
  shift_alignment: "shift_alignment_score",
  historical_spbu_pairing: "spbu_pairing_score",
  historical_mt_affinity: "mt_affinity_score",
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("id-ID", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("id-ID", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
}

function formatScore(value: number | null | undefined): string {
  return value == null ? "N/A" : `${value.toFixed(2)}%`;
}

function humanize(value: string | null | undefined): string {
  return value ? value.replace(/_/g, " ") : "—";
}

function ScoreValue({ value, status }: { value: number | null; status?: string }) {
  return (
    <div title={humanize(status)}>
      <div className="font-semibold tabular-nums text-petroink">{formatScore(value)}</div>
      <div className="mt-0.5 max-w-[150px] truncate text-[10px] uppercase tracking-wide text-slate-400">
        {humanize(status)}
      </div>
    </div>
  );
}

function SortHeader<T extends string>({
  label,
  column,
  activeColumn,
  direction,
  onSort,
}: {
  label: string;
  column: T;
  activeColumn: T;
  direction: "asc" | "desc";
  onSort: (column: T) => void;
}) {
  const Icon = activeColumn !== column ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 whitespace-nowrap text-left"
      onClick={() => onSort(column)}
      title={`Sort by ${label}`}
    >
      {label}
      <Icon size={13} className={activeColumn === column ? "text-petroblue" : "text-slate-300"} />
    </button>
  );
}

function EvidenceBlock({ title, payload }: { title: string; payload: Record<string, unknown> }) {
  return (
    <section className="border border-line bg-slate-50 p-3">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">{title}</div>
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-5 text-slate-600">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </section>
  );
}


export function RouteModelAlignmentPage({ depots }: { depots: Depot[] }) {
  const [depotId, setDepotId] = useState(depots[0]?.depot_id || "");
  const [routes, setRoutes] = useState<RouteOption[]>([]);
  const [routeVersionId, setRouteVersionId] = useState("");
  const [routesLoading, setRoutesLoading] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [rows, setRows] = useState<RowsResponse | null>(null);
  const [trips, setTrips] = useState<TripsResponse | null>(null);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [tripsLoading, setTripsLoading] = useState(false);
  const [tripSearch, setTripSearch] = useState("");
  const [appliedTripSearch, setAppliedTripSearch] = useState("");
  const [tripSortBy, setTripSortBy] = useState<TripSortKey>("gate_out");
  const [tripSortDirection, setTripSortDirection] = useState<"asc" | "desc">("asc");
  const [tripPage, setTripPage] = useState(1);
  const [tripPageSize, setTripPageSize] = useState(10);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("planned_gate_out");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [detail, setDetail] = useState<EvaluationRowDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!depotId && depots.length > 0) setDepotId(depots[0].depot_id);
  }, [depotId, depots]);

  useEffect(() => {
    if (!depotId) {
      setRoutes([]);
      setRouteVersionId("");
      return;
    }
    let cancelled = false;
    setRoutesLoading(true);
    setError("");
    apiGet<{ rows: RouteOption[] }>(`/api/v1/phase9/route-model-alignment/routes?depot_id=${encodeURIComponent(depotId)}`)
      .then((payload) => {
        if (cancelled) return;
        setRoutes(payload.rows);
        const preferred = payload.rows.find((row) => row.is_current && row.lineage_status === "READY" && row.routed_lo_count > 0)
          ?? payload.rows.find((row) => row.lineage_status === "READY" && row.routed_lo_count > 0)
          ?? payload.rows.find((row) => row.is_current && row.lineage_status === "READY")
          ?? payload.rows.find((row) => row.lineage_status === "READY")
          ?? payload.rows[0];
        setRouteVersionId(preferred?.route_version_id ?? "");
      })
      .catch((cause: Error) => {
        if (!cancelled) setError(cause.message);
      })
      .finally(() => {
        if (!cancelled) setRoutesLoading(false);
      });
    return () => { cancelled = true; };
  }, [depotId]);

  useEffect(() => {
    setEvaluation(null);
    setRows(null);
    setTrips(null);
    setDetail(null);
    setTripSearch("");
    setAppliedTripSearch("");
    setTripPage(1);
    setSearch("");
    setAppliedSearch("");
    setPage(1);
  }, [routeVersionId]);

  useEffect(() => {
    if (!evaluation?.evaluation_run_id) return;
    let cancelled = false;
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      search: appliedSearch,
      sort_by: sortBy,
      sort_direction: sortDirection,
    });
    setRowsLoading(true);
    apiGet<RowsResponse>(`/api/v1/phase9/route-model-alignment/evaluations/${evaluation.evaluation_run_id}/rows?${params}`)
      .then((payload) => {
        if (!cancelled) setRows(payload);
      })
      .catch((cause: Error) => {
        if (!cancelled) setError(cause.message);
      })
      .finally(() => {
        if (!cancelled) setRowsLoading(false);
      });
    return () => { cancelled = true; };
  }, [evaluation?.evaluation_run_id, page, pageSize, appliedSearch, sortBy, sortDirection]);

  useEffect(() => {
    if (!evaluation?.evaluation_run_id) return;
    let cancelled = false;
    const params = new URLSearchParams({
      page: String(tripPage),
      page_size: String(tripPageSize),
      search: appliedTripSearch,
      sort_by: tripSortBy,
      sort_direction: tripSortDirection,
    });
    setTripsLoading(true);
    apiGet<TripsResponse>(`/api/v1/phase9/route-model-alignment/evaluations/${evaluation.evaluation_run_id}/trips?${params}`)
      .then((payload) => {
        if (!cancelled) setTrips(payload);
      })
      .catch((cause: Error) => {
        if (!cancelled) setError(cause.message);
      })
      .finally(() => {
        if (!cancelled) setTripsLoading(false);
      });
    return () => { cancelled = true; };
  }, [evaluation?.evaluation_run_id, tripPage, tripPageSize, appliedTripSearch, tripSortBy, tripSortDirection]);

  const selectedRoute = routes.find((route) => route.route_version_id === routeVersionId) ?? null;
  const metrics = evaluation?.summary.metrics;
  const scope = evaluation?.summary.scope;

  const overviewChart = useMemo(() => ({
    tooltip: { trigger: "axis" },
    legend: { bottom: 0, data: ["Alignment score", "Evidence coverage"] },
    grid: { top: 28, right: 18, bottom: 62, left: 48 },
    xAxis: { type: "category", data: metricDefinitions.map((metric) => metric.shortLabel), axisLabel: { interval: 0 } },
    yAxis: { type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%" } },
    series: [
      {
        name: "Alignment score",
        type: "bar",
        data: metricDefinitions.map((metric) => metrics?.[metric.key]?.score_pct ?? null),
        itemStyle: { color: "#0b73bf" },
      },
      {
        name: "Evidence coverage",
        type: "bar",
        data: metricDefinitions.map((metric) => metrics?.[metric.key]?.coverage_pct ?? 0),
        itemStyle: { color: "#7895a8" },
      },
    ],
  }), [metrics]);

  const distributionChart = useMemo(() => {
    const labels = metrics?.cluster_cohesion?.distribution.map((bucket) => bucket.label) ?? [];
    return {
      tooltip: { trigger: "axis" },
      legend: { bottom: 0, data: metricDefinitions.map((metric) => metric.shortLabel) },
      grid: { top: 22, right: 16, bottom: 68, left: 48 },
      xAxis: { type: "category", data: labels },
      yAxis: { type: "value", minInterval: 1 },
      series: metricDefinitions.map((definition, index) => ({
        name: definition.shortLabel,
        type: "bar",
        data: metrics?.[definition.key]?.distribution.map((bucket) => bucket.count) ?? [],
        itemStyle: { color: ["#0b73bf", "#2f7d6d", "#7c6f64", "#64748b"][index] },
      })),
    };
  }, [metrics]);

  async function evaluateRoute() {
    if (!depotId || !routeVersionId) return;
    setEvaluating(true);
    setError("");
    setDetail(null);
    try {
      const result = await apiSend<Evaluation>(
        "/api/v1/phase9/route-model-alignment/evaluations",
        "POST",
        { depot_id: depotId, route_version_id: routeVersionId },
      );
      setEvaluation(result);
      setPage(1);
      setTripPage(1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Route alignment evaluation failed.");
    } finally {
      setEvaluating(false);
    }
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setAppliedSearch(search.trim());
  }

  function submitTripSearch(event: FormEvent) {
    event.preventDefault();
    setTripPage(1);
    setAppliedTripSearch(tripSearch.trim());
  }

  function changeTripSort(column: TripSortKey) {
    if (column === tripSortBy) setTripSortDirection((current) => current === "asc" ? "desc" : "asc");
    else {
      setTripSortBy(column);
      setTripSortDirection("asc");
    }
    setTripPage(1);
  }

  function changeSort(column: SortKey) {
    if (column === sortBy) setSortDirection((current) => current === "asc" ? "desc" : "asc");
    else {
      setSortBy(column);
      setSortDirection("asc");
    }
    setPage(1);
  }

  async function openDetail(rowId: string) {
    if (!evaluation) return;
    setDetailLoading(true);
    setError("");
    try {
      setDetail(await apiGet<EvaluationRowDetail>(
        `/api/v1/phase9/route-model-alignment/evaluations/${evaluation.evaluation_run_id}/rows/${rowId}`,
      ));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "LO evidence could not be loaded.");
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <>
      <section className="mb-5 border border-line bg-white p-4">
        <div className="mb-4 flex items-start gap-3 border-b border-line pb-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center bg-petroblue/10 text-petroblue">
            <GitCompareArrows size={20} />
          </div>
          <div>
            <div className="text-sm font-semibold uppercase tracking-wide text-slate-700">Route–Model Alignment Evaluation</div>
            <p className="mt-1 max-w-4xl text-xs leading-5 text-slate-500">
              Pilih TBBM dan satu Route Version Fase 7. Sistem membentuk Source-Aligned Bundle secara otomatis dari lineage route dan hanya menjelaskan tingkat keselarasan terhadap pola historis—bukan menilai route baik atau buruk.
            </p>
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-[minmax(220px,0.8fr)_minmax(360px,1.6fr)_auto] lg:items-end">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            TBBM
            <select
              className="mt-2 w-full border border-line bg-white px-3 py-2 text-sm normal-case tracking-normal"
              value={depotId}
              onChange={(event) => setDepotId(event.target.value)}
            >
              {depots.map((depot) => (
                <option key={depot.depot_id} value={depot.depot_id}>
                  {depot.depot_code ? `${depot.depot_code} · ` : ""}{depot.depot_name}
                </option>
              ))}
            </select>
          </label>

          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Route Version Fase 7
            <select
              className="mt-2 w-full border border-line bg-white px-3 py-2 text-sm normal-case tracking-normal disabled:bg-slate-100"
              value={routeVersionId}
              disabled={routesLoading || routes.length === 0}
              onChange={(event) => setRouteVersionId(event.target.value)}
            >
              {routes.length === 0 && <option value="">Tidak ada route tersedia</option>}
              {routes.map((route) => (
                <option key={route.route_version_id} value={route.route_version_id}>
                  {route.job_no} · {route.version_label} · {formatDate(route.operating_date)} · {route.lo_count} LO{route.is_current ? " · Current" : ""}{route.lineage_status !== "READY" ? " · Lineage unavailable" : ""}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            className="inline-flex items-center justify-center gap-2 bg-petroblue px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!selectedRoute || selectedRoute.lineage_status !== "READY" || evaluating}
            onClick={() => void evaluateRoute()}
          >
            <RefreshCw size={16} className={evaluating ? "animate-spin" : ""} />
            {evaluating ? "Mengevaluasi" : "Evaluate Alignment"}
          </button>
        </div>

        {selectedRoute && (
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
            <span>{selectedRoute.job_name}</span>
            <span>{selectedRoute.trip_count.toLocaleString()} trip</span>
            <span>{selectedRoute.routed_lo_count.toLocaleString()} routed LO</span>
            <span>{selectedRoute.dropped_lo_count.toLocaleString()} dropped LO</span>
            <span>Model: {selectedRoute.source_model_name ?? "—"} v{selectedRoute.source_model_version ?? "—"}</span>
            {selectedRoute.lineage_reason && <span className="font-medium text-rust">{humanize(selectedRoute.lineage_reason)}</span>}
          </div>
        )}
        {error && <div className="mt-4 border border-rust/30 bg-rust/5 px-3 py-2 text-sm text-rust">{error}</div>}
      </section>

      {!evaluation && (
        <section className="border border-line bg-white px-6 py-16 text-center">
          <Layers3 className="mx-auto text-slate-300" size={34} />
          <div className="mt-4 text-sm font-semibold text-slate-700">Belum ada hasil evaluasi</div>
          <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            Hasil tetap kosong sampai Evaluate Alignment dijalankan. Saved analysis Fase 2–4 tidak perlu dipilih manual karena bundle mengikuti periode, shift definition, model, dan TBBM dari source route.
          </p>
        </section>
      )}

      {evaluation && metrics && scope && (
        <>
          <section className="mb-5 border border-petroblue/20 bg-petroblue/5 p-4">
            <div className="flex items-start gap-3">
              <Info className="mt-0.5 shrink-0 text-petroblue" size={18} />
              <div>
                <div className="text-sm font-semibold text-petroink">Interpretasi netral</div>
                <p className="mt-1 text-sm leading-6 text-slate-600">
                  Nilai yang lebih tinggi berarti route lebih sering menyerupai pola historis pada kategori tersebut. Nilai ini tidak menyatakan kualitas, kelayakan operasional, atau rekomendasi perubahan route.
                </p>
              </div>
            </div>
          </section>

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {metricDefinitions.map((definition) => {
              const metric = metrics[definition.key];
              return (
                <article key={definition.key} className="border border-line bg-white p-4">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{definition.label}</div>
                  <div className="mt-3 text-3xl font-semibold tabular-nums text-petroink">{formatScore(metric.score_pct)}</div>
                  <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                    <span>Evidence coverage</span>
                    <span className="font-semibold tabular-nums">{metric.coverage_pct.toFixed(2)}%</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden bg-slate-100">
                    <div className="h-full bg-slate-500" style={{ width: `${Math.min(100, metric.coverage_pct)}%` }} />
                  </div>
                  <p className="mt-3 text-xs leading-5 text-slate-500">{definition.description}</p>
                  <div className="mt-3 text-[10px] uppercase tracking-wide text-slate-400">{humanize(metric.resolution_method)}</div>
                </article>
              );
            })}
          </section>

          <section className="mt-5 grid gap-4 xl:grid-cols-2">
            <article className="min-h-[330px] border border-line bg-white p-4">
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Alignment & Evidence Coverage</div>
              <ReactECharts option={overviewChart} style={{ height: 280 }} />
            </article>
            <article className="min-h-[330px] border border-line bg-white p-4">
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Score Distribution</div>
              <ReactECharts option={distributionChart} style={{ height: 280 }} />
            </article>
          </section>

          <section className="mt-5 grid gap-4 xl:grid-cols-[1.1fr_1.9fr]">
            <article className="border border-line bg-white p-4">
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Evaluation Scope</div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                {[
                  ["Total LO", scope.total_lo],
                  ["Routed LO", scope.routed_lo],
                  ["Dropped / Unassigned", scope.dropped_or_unassigned_lo],
                  ["Route Trips", scope.trip_count],
                  ["Unique SPBU", scope.unique_spbu_count],
                  ["Assigned MT", scope.assigned_mt_count],
                  ["Trip–SPBU observations", scope.unique_trip_spbu_observations],
                  ["SPBU pairs", scope.unique_spbu_pairs],
                ].map(([label, value]) => (
                  <div key={String(label)} className="border border-line p-3">
                    <div className="text-xs text-slate-500">{label}</div>
                    <div className="mt-1 text-lg font-semibold tabular-nums">{Number(value).toLocaleString()}</div>
                  </div>
                ))}
              </div>
            </article>

            <article className="border border-line bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Source-Aligned Bundle</div>
                  <div className="mt-1 text-xs text-slate-500">Immutable source lineage used by this evaluation run.</div>
                </div>
                <span className="border border-line bg-slate-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  {evaluation.source_bundle.status ?? "PARTIAL"}
                </span>
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <div className="border border-line p-3 text-xs leading-6 text-slate-600">
                  <div><span className="text-slate-400">Evaluation:</span> {evaluation.evaluation_run_no}</div>
                  <div><span className="text-slate-400">Route:</span> {String(evaluation.source_bundle.lineage?.route_version_label ?? evaluation.route_version_id)}</div>
                  <div><span className="text-slate-400">Prediction:</span> {String(evaluation.source_bundle.lineage?.source_prediction_run_no ?? "—")}</div>
                  <div><span className="text-slate-400">Model:</span> {String(evaluation.source_bundle.lineage?.phase5_model_name ?? "—")} v{String(evaluation.source_bundle.lineage?.phase5_model_version ?? "—")}</div>
                  <div><span className="text-slate-400">Historical period:</span> {formatDate(String(evaluation.source_bundle.historical_scope?.start_date ?? ""))} – {formatDate(String(evaluation.source_bundle.historical_scope?.end_date ?? ""))}</div>
                  <div><span className="text-slate-400">Completed:</span> {formatDateTime(evaluation.completed_at)}</div>
                </div>
                <div className="grid gap-2">
                  {metricDefinitions.map((definition) => {
                    const component = evaluation.source_bundle.components?.[definition.key];
                    return (
                      <div key={definition.key} className="flex items-center justify-between gap-3 border border-line px-3 py-2 text-xs">
                        <div>
                          <div className="font-medium text-slate-700">{definition.label}</div>
                          <div className="mt-0.5 text-[10px] uppercase tracking-wide text-slate-400">{humanize(component?.resolution_method)}</div>
                        </div>
                        <span className="tabular-nums text-slate-500">{component?.record_count?.toLocaleString() ?? 0} records</span>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="mt-3 break-all border-t border-line pt-3 text-[10px] text-slate-400">
                Bundle checksum: {evaluation.source_bundle_checksum}
              </div>
            </article>
          </section>

          <section className="mt-5 border border-line bg-white">
            <div className="flex flex-col gap-3 border-b border-line p-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Trip Alignment Matrix</div>
                <div className="mt-1 text-xs text-slate-500">Ringkasan per trip; No. LO dan No. SPBU dapat dicari dan diurutkan tanpa mengubah metric route.</div>
              </div>
              <form className="flex w-full max-w-xl gap-2" onSubmit={submitTripSearch}>
                <div className="relative min-w-0 flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={15} />
                  <input
                    className="w-full border border-line py-2 pl-9 pr-3 text-sm"
                    value={tripSearch}
                    onChange={(event) => setTripSearch(event.target.value)}
                    placeholder="Search shipment, trip, MT, shift, No. LO, No. SPBU"
                  />
                </div>
                <button type="submit" className="border border-line px-3 py-2 text-sm font-medium">Search</button>
              </form>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1800px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2"><SortHeader label="Shipment" column="shipment_id" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Trip" column="trip_number" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Gate Out" column="gate_out" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="MT" column="vehicle_registration" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Shift" column="route_shift" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="No. LO" column="loading_order_number" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="No. SPBU" column="spbu_number" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Jumlah LO" column="lo_count" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Jumlah SPBU" column="unique_spbu_count" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Cluster" column="cluster_cohesion" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Shift Alignment" column="shift_alignment" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="SPBU Pairing" column="spbu_pairing" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="MT Affinity" column="mt_affinity" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Coverage" column="evidence_coverage" activeColumn={tripSortBy} direction={tripSortDirection} onSort={changeTripSort} /></th>
                  </tr>
                </thead>
                <tbody className={tripsLoading ? "opacity-50" : ""}>
                  {(trips?.rows ?? []).map((trip) => (
                    <tr key={trip.route_version_trip_id} className="border-b border-line align-top last:border-b-0 hover:bg-slate-50">
                      <td className="whitespace-nowrap px-3 py-3 font-medium">{trip.shipment_id}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{trip.trip_number}</td>
                      <td className="whitespace-nowrap px-3 py-3 text-slate-600">{formatDateTime(trip.gate_out)}</td>
                      <td className="whitespace-nowrap px-3 py-3">{trip.vehicle_registration ?? "—"}</td>
                      <td className="whitespace-nowrap px-3 py-3">{trip.route_shift ?? "—"}</td>
                      <td className="max-w-[320px] whitespace-normal break-words px-3 py-3 text-xs leading-5">{trip.loading_order_numbers.join(", ") || "—"}</td>
                      <td className="max-w-[260px] whitespace-normal break-words px-3 py-3 text-xs leading-5" title={trip.spbu_names.join(", ")}>{trip.spbu_numbers.join(", ") || "—"}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{trip.lo_count}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{trip.unique_spbu_count}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{formatScore(trip.cluster_cohesion_score)}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{formatScore(trip.shift_alignment_score)}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{formatScore(trip.spbu_pairing_score)}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{formatScore(trip.mt_affinity_score)}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{trip.evaluable_category_count} / 4</td>
                    </tr>
                  ))}
                  {!tripsLoading && (trips?.rows.length ?? 0) === 0 && <tr><td colSpan={14} className="px-3 py-8 text-center text-slate-500">No trip matches the active search.</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col gap-3 border-t border-line px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <div className="text-slate-500">
                {trips?.total
                  ? `Showing ${((trips.page - 1) * trips.page_size + 1).toLocaleString()}–${Math.min(trips.page * trips.page_size, trips.total).toLocaleString()} of ${trips.total.toLocaleString()} trips`
                  : "0 trips"}
              </div>
              <div className="flex items-center gap-2">
                <select
                  className="border border-line bg-white px-2 py-1.5 text-sm"
                  value={tripPageSize}
                  onChange={(event) => { setTripPageSize(Number(event.target.value)); setTripPage(1); }}
                  title="Trips per page"
                >
                  {[10, 25, 50, 100].map((size) => <option key={size} value={size}>{size} rows</option>)}
                </select>
                <button type="button" className="border border-line p-2 disabled:opacity-40" disabled={(trips?.page ?? 1) <= 1 || tripsLoading} onClick={() => setTripPage((current) => Math.max(1, current - 1))} title="Previous trip page"><ChevronLeft size={15} /></button>
                <span className="min-w-24 text-center text-slate-500">Page {trips?.page ?? tripPage} of {trips?.page_count ?? 1}</span>
                <button type="button" className="border border-line p-2 disabled:opacity-40" disabled={(trips?.page ?? 1) >= (trips?.page_count ?? 1) || tripsLoading} onClick={() => setTripPage((current) => current + 1)} title="Next trip page"><ChevronRight size={15} /></button>
              </div>
            </div>
          </section>

          <section className="mt-5 border border-line bg-white">
            <div className="flex flex-col gap-3 border-b border-line p-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Loading Order Alignment Detail</div>
                <div className="mt-1 text-xs text-slate-500">Setiap LO tetap tampil; nilai N/A menunjukkan bukti tidak cukup atau LO tidak memiliki route assignment.</div>
              </div>
              <form className="flex w-full max-w-lg gap-2" onSubmit={submitSearch}>
                <div className="relative min-w-0 flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={15} />
                  <input
                    className="w-full border border-line py-2 pl-9 pr-3 text-sm"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search LO, shipment, SPBU, product, MT, cluster, status"
                  />
                </div>
                <button type="submit" className="border border-line px-3 py-2 text-sm font-medium">Search</button>
              </form>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[1650px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2"><SortHeader label="LO" column="loading_order_id" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Status" column="status" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Shipment" column="shipment_id" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Trip" column="trip_number" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Gate Out" column="planned_gate_out" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="SPBU" column="spbu" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Product" column="product" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="KL" column="volume_kl" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Assigned MT" column="assigned_mt" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Cluster" column="cluster" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Cluster Cohesion" column="cluster_cohesion" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Shift Alignment" column="shift_alignment" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="SPBU Pairing" column="spbu_pairing" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="MT Affinity" column="mt_affinity" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2"><SortHeader label="Coverage" column="evidence_coverage" activeColumn={sortBy} direction={sortDirection} onSort={changeSort} /></th>
                    <th className="px-3 py-2">Evidence</th>
                  </tr>
                </thead>
                <tbody className={rowsLoading ? "opacity-50" : ""}>
                  {(rows?.rows ?? []).map((row) => (
                    <tr key={row.evaluation_row_id} className="border-b border-line align-top hover:bg-slate-50">
                      <td className="whitespace-nowrap px-3 py-3 font-medium">{row.loading_order_id}</td>
                      <td className="whitespace-nowrap px-3 py-3 text-xs">{humanize(row.assignment_status)}</td>
                      <td className="whitespace-nowrap px-3 py-3">{row.shipment_id ?? "—"}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{row.trip_number ?? "—"}</td>
                      <td className="whitespace-nowrap px-3 py-3 text-xs">{formatDateTime(row.planned_gate_out)}</td>
                      <td className="px-3 py-3"><div className="font-medium">{row.spbu_code ?? "—"}</div><div className="max-w-[190px] truncate text-xs text-slate-500">{row.spbu_name ?? "—"}</div></td>
                      <td className="whitespace-nowrap px-3 py-3">{row.product_name ?? "—"}</td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{row.volume_kl.toLocaleString()}</td>
                      <td className="whitespace-nowrap px-3 py-3">{row.vehicle_registration ?? "—"}</td>
                      <td className="whitespace-nowrap px-3 py-3"><div>{row.cluster_label ?? "N/A"}</div><div className="text-[10px] text-slate-400">{row.route_shift_name ?? "No shift"}</div></td>
                      <td className="px-3 py-3"><ScoreValue value={row.cluster_cohesion_score} status={row.cluster_cohesion_status} /></td>
                      <td className="px-3 py-3"><ScoreValue value={row.shift_alignment_score} status={row.shift_alignment_status} /></td>
                      <td className="px-3 py-3"><ScoreValue value={row.spbu_pairing_score} status={row.spbu_pairing_status} /></td>
                      <td className="px-3 py-3"><ScoreValue value={row.mt_affinity_score} status={row.mt_affinity_status} /></td>
                      <td className="whitespace-nowrap px-3 py-3 tabular-nums">{row.evaluable_category_count} / 4</td>
                      <td className="px-3 py-3">
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 border border-line px-2 py-1 text-xs text-petroblue disabled:opacity-50"
                          disabled={detailLoading}
                          onClick={() => void openDetail(row.evaluation_row_id)}
                        >
                          <Eye size={13} /> Detail
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!rowsLoading && (rows?.rows.length ?? 0) === 0 && (
                    <tr><td colSpan={16} className="px-3 py-10 text-center text-slate-500">No Loading Order matches the active search.</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex flex-col gap-3 border-t border-line px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <div className="text-slate-500">
                {rows?.total
                  ? `Showing ${((rows.page - 1) * rows.page_size + 1).toLocaleString()}–${Math.min(rows.page * rows.page_size, rows.total).toLocaleString()} of ${rows.total.toLocaleString()} LO`
                  : "0 LO"}
              </div>
              <div className="flex items-center gap-2">
                <select
                  className="border border-line bg-white px-2 py-1.5 text-sm"
                  value={pageSize}
                  onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}
                  title="Rows per page"
                >
                  {[10, 25, 50, 100].map((size) => <option key={size} value={size}>{size} rows</option>)}
                </select>
                <button type="button" className="border border-line p-2 disabled:opacity-40" disabled={(rows?.page ?? 1) <= 1 || rowsLoading} onClick={() => setPage((current) => Math.max(1, current - 1))} title="Previous page"><ChevronLeft size={15} /></button>
                <span className="min-w-24 text-center text-slate-500">Page {rows?.page ?? page} of {rows?.page_count ?? 1}</span>
                <button type="button" className="border border-line p-2 disabled:opacity-40" disabled={(rows?.page ?? 1) >= (rows?.page_count ?? 1) || rowsLoading} onClick={() => setPage((current) => current + 1)} title="Next page"><ChevronRight size={15} /></button>
              </div>
            </div>
          </section>
        </>
      )}

      {detail && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30" role="dialog" aria-modal="true" aria-label="Loading Order alignment evidence">
          <button type="button" className="min-w-0 flex-1 cursor-default" onClick={() => setDetail(null)} aria-label="Close evidence drawer" />
          <aside className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-2xl">
            <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-line bg-white px-5 py-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">LO Evidence</div>
                <div className="mt-1 text-xl font-semibold">{detail.loading_order_id}</div>
                <div className="mt-1 text-xs text-slate-500">{detail.spbu_code} · {detail.spbu_name} · {detail.vehicle_registration ?? "Unassigned MT"}</div>
              </div>
              <button type="button" className="border border-line p-2" onClick={() => setDetail(null)} title="Close"><X size={17} /></button>
            </div>
            <div className="grid gap-4 p-5">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {metricDefinitions.map((definition) => {
                  const value = detail[scoreFields[definition.key]] as number | null;
                  return (
                    <div key={definition.key} className="border border-line p-3">
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{definition.shortLabel}</div>
                      <div className="mt-2 text-lg font-semibold tabular-nums">{formatScore(value)}</div>
                    </div>
                  );
                })}
              </div>
              <EvidenceBlock title="Cluster Cohesion Evidence" payload={detail.cluster_evidence} />
              <EvidenceBlock title="Shift Alignment Evidence" payload={detail.shift_evidence} />
              <EvidenceBlock title="Historical SPBU Pairing Evidence" payload={detail.pairing_evidence} />
              <EvidenceBlock title="Historical MT Affinity Evidence" payload={detail.mt_affinity_evidence} />
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
