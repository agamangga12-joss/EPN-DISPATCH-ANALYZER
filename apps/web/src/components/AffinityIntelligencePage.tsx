import ReactECharts from "echarts-for-react";
import { ArrowDown, ArrowUp, ArrowUpDown, Hand, Maximize2, Network, RefreshCw, Save, Trash2, X, ZoomIn } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiSend } from "../lib/api";

type Depot = { depot_id: string; depot_name: string };
type Product = { product_id: string; product_name: string };
type SpbuOption = { spbu_id: string; spbu_code: string; spbu_name: string | null; primary_depot_id?: string | null };
type DateAvailability = { min_date: string | null; max_date: string | null };
type Filters = {
  depotId: string;
  spbuId: string;
  startDate: string;
  endDate: string;
  productId: string;
  minimumObservations: string;
  confidence: string;
  temporalBucket: string;
  recentDays: string;
  topN: string;
  edgeMetric: string;
};
type Pair = {
  spbu_id: string;
  spbu_code: string;
  spbu_tags: string[];
  mt_id: string;
  mt_label: string;
  mt_tags: string[];
  shipment_count: number;
  total_spbu_shipment_count: number;
  total_mt_shipment_count: number;
  probability_mt_given_spbu: number;
  probability_spbu_given_mt: number;
  first_observed: string;
  last_observed: string;
  operating_day_count: number;
  confidence_score: number;
  confidence_level: string;
};
type Profile = {
  spbu_id: string;
  spbu_code: string;
  spbu_name: string | null;
  spbu_tags: string[];
  shipment_count: number;
  operating_day_count: number;
  unique_mt_count: number;
  dominant_mt_id: string;
  dominant_mt_label: string;
  dominant_mt_probability: number;
  top3_mt_share: number;
  hhi: number;
  normalized_hhi: number;
  normalized_entropy: number;
  consistency_score: number;
  variability_score: number;
  consistency_classification: string;
  historical_pattern: string;
  dominant_mt_persistence: number;
  temporal_stability_score: number;
  pattern_shift_distance: number;
  pattern_shift_level: string;
  previous_dominant_label: string | null;
  recent_dominant_label: string | null;
  confidence_score: number;
  confidence_level: string;
};
type TemporalRow = {
  mt_id: string;
  mt_label: string;
  period_start: string;
  probability_mt_given_spbu: number;
};
type DistributionRow = { mt_id: string; mt_label: string; shipment_count: number; probability: number };
type ReverseDetail = {
  mt_id: string;
  mt_label: string;
  historical_shipments: number;
  unique_spbu_count: number;
  operating_day_count: number;
  consistency_score: number;
  variability_score: number;
  dominant_spbu_persistence: number;
  temporal_stability_score: number;
  pattern_shift_level: string;
  previous_dominant_spbu_code: string | null;
  recent_dominant_spbu_code: string | null;
  distribution: Array<{ spbu_id: string; spbu_code: string; spbu_name: string | null; shipment_count: number; probability_spbu_given_mt: number }>;
};
type EvidenceRow = {
  shipment_id: string;
  source_shipment_id: string;
  date: string;
  depot: string;
  gate_out: string | null;
  mt_id: string;
  spbu_id: string;
  products: string[];
  quantity: number;
  other_spbu_ids: string[];
};
type Analysis = {
  algorithm_version: string;
  effective_filters: Record<string, string | number | null>;
  summary: Record<string, number>;
  data_quality: {
    source_shipments: number;
    eligible_shipments: number;
    excluded_shipments: number;
    eligible_pct: number;
    duplicate_observations_removed: number;
    exclusion_reasons: Array<{ reason: string; count: number }>;
  };
  profiles: Profile[];
  rankings: { most_consistent: Array<Profile & { rank: number }>; most_variable: Array<Profile & { rank: number }>; least_stable: Array<Profile & { rank: number }> };
  scatter: Array<Profile & { value: [number, number, number] }>;
  pattern_matrix: { unique_mt_split: number; affinity_split: number; points: Array<{ spbu_id: string; spbu_code: string; spbu_tags: string[]; value: [number, number]; quadrant: string; shipment_count: number }> };
  selected_spbu_profile: Profile | null;
  affinity_distribution: Pair[];
  temporal_profile: TemporalRow[];
  recent_comparison: { recent_start_date: string | null; full_period: DistributionRow[]; recent_period: DistributionRow[] };
  reverse_detail: ReverseDetail | null;
  network: {
    nodes: Array<{ id: string; entity_id: string; entity_type: "SPBU" | "MT"; name: string; tags: string[]; category: number; symbolSize: number; selected: boolean }>;
    edges: Array<Pair & { source: string; target: string; value: number; highlighted: boolean }>;
    categories: Array<{ name: string }>;
    edge_metric: string;
  };
  evidence: { relationship: { spbu_id: string; mt_id: string } | null; distinct_shipment_count: number; rows: EvidenceRow[] };
  methodology: Record<string, string | Record<string, unknown>>;
};
type SavedAffinityAnalysisConfig = {
  id: string;
  name: string;
  depot_id: string;
  depot_name: string | null;
  start_date: string;
  end_date: string;
  product_id: string | null;
  product_name: string;
  minimum_observations: number;
  confidence: string;
  temporal_bucket: string;
  recent_days: number;
  top_n: number;
  edge_metric: string;
  selected_spbu_id: string | null;
  selected_mt_id: string | null;
  spbu_analyzed: number;
  mt_observed: number;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  ui_state?: Record<string, unknown>;
  affinity_analysis_snapshot?: Analysis;
};
type SavedAffinityAnalysisConfigResponse = { total: number; limit: number; offset: number; rows: SavedAffinityAnalysisConfig[] };

function addDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00`);
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function percent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

function number(value: number, digits = 0): string {
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function dateLabel(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(`${value.slice(0, 10)}T00:00:00`));
}

function dateTimeLabel(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function formatTags(tags: string[] | null | undefined): string {
  return tags?.length ? tags.join(", ") : "-";
}

function confidenceClass(level: string): string {
  if (level === "HIGH") return "border-mint bg-mint/10 text-mint";
  if (level === "MEDIUM") return "border-amber bg-amber/10 text-amber";
  return "border-rust bg-rust/10 text-rust";
}

function shiftClass(level: string): string {
  if (level === "STABLE") return "border-mint bg-mint/10 text-mint";
  if (level === "MINOR SHIFT") return "border-sun bg-sun/10 text-petroink";
  return "border-rust bg-rust/10 text-rust";
}

function MetricTrack({ label, value, color = "#0b73bf" }: { label: string; value: number; color?: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500"><span>{label}</span><span>{number(value, 1)} / 100</span></div>
      <div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, value))}%`, backgroundColor: color }} /></div>
    </div>
  );
}

type ChartInteractionMode = "zoom" | "pan";
type ChartViewport = { start: number; end: number };

function ChartInteractionToolbar({ mode, onModeChange, onZoom, onFit }: { mode: ChartInteractionMode; onModeChange: (mode: ChartInteractionMode) => void; onZoom: () => void; onFit: () => void }) {
  const buttonClass = (active: boolean) => `inline-flex h-8 w-8 items-center justify-center rounded-lg border transition ${active ? "border-petroblue bg-petroblue text-white" : "border-line bg-white text-slate-500 hover:border-petroblue hover:text-petroblue"}`;
  return (
    <div className="flex items-center gap-1" aria-label="Chart navigation controls">
      <button type="button" className={buttonClass(mode === "zoom")} aria-label="Zoom titik SPBU" aria-pressed={mode === "zoom"} title="Zoom: klik untuk memperbesar titik SPBU dan skala X/Y" onClick={() => { onModeChange("zoom"); onZoom(); }}><ZoomIn size={16} /></button>
      <button type="button" className={buttonClass(mode === "pan")} aria-label="Drag grafik" aria-pressed={mode === "pan"} title="Pan: drag grafik untuk menggeser area zoom" onClick={() => onModeChange("pan")}><Hand size={16} /></button>
      <button type="button" className={buttonClass(false)} aria-label="Fit grafik" title="Fit: kembali ke skala X/Y awal" onClick={onFit}><Maximize2 size={16} /></button>
    </div>
  );
}

type RankingVariant = "consistent" | "variable" | "stable";

function RankingTable({ title, rows, variant, onSelect }: { title: string; rows: Array<Profile & { rank: number }>; variant: RankingVariant; onSelect: (spbuId: string) => void }) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<keyof Profile>(variant === "consistent" ? "consistency_score" : variant === "variable" ? "variability_score" : "temporal_stability_score");
  const [direction, setDirection] = useState<"asc" | "desc">(variant === "stable" ? "asc" : "desc");
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return rows
      .filter((row) => !needle || row.spbu_code.toLowerCase().includes(needle) || (row.spbu_name ?? "").toLowerCase().includes(needle))
      .sort((left, right) => {
        const a = left[sortKey] ?? "";
        const b = right[sortKey] ?? "";
        const result = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
        return direction === "asc" ? result : -result;
      });
  }, [direction, rows, search, sortKey]);
  const metricKey: keyof Profile = variant === "consistent" ? "consistency_score" : variant === "variable" ? "variability_score" : "temporal_stability_score";

  function changeSort(key: keyof Profile) {
    if (sortKey === key) setDirection((value) => value === "asc" ? "desc" : "asc");
    else { setSortKey(key); setDirection(key === "spbu_code" ? "asc" : "desc"); }
  }

  function SortIcon({ column }: { column: keyof Profile }) {
    return sortKey === column ? (direction === "asc" ? <ArrowUp size={13} /> : <ArrowDown size={13} />) : <ArrowUpDown size={13} className="text-slate-300" />;
  }

  return (
    <section className="border border-line bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">{title}</div>
        <input className="w-40 border border-line px-3 py-2 text-xs" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter SPBU" />
      </div>
      <div className="max-h-[360px] overflow-auto border border-line">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-slate-50 text-left uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2"><button className="inline-flex items-center gap-1" onClick={() => changeSort("spbu_code")}>SPBU <SortIcon column="spbu_code" /></button></th>
              <th className="px-3 py-2"><button className="inline-flex items-center gap-1" onClick={() => changeSort("shipment_count")}>Shipments <SortIcon column="shipment_count" /></button></th>
              <th className="px-3 py-2">Dominant MT</th>
              <th className="px-3 py-2"><button className="inline-flex items-center gap-1" onClick={() => changeSort("dominant_mt_probability")}>Dominant % <SortIcon column="dominant_mt_probability" /></button></th>
              {variant !== "stable" && <th className="px-3 py-2"><button className="inline-flex items-center gap-1" onClick={() => changeSort("unique_mt_count")}>Unique MT <SortIcon column="unique_mt_count" /></button></th>}
              {variant === "consistent" && <th className="px-3 py-2"><button className="inline-flex items-center gap-1" onClick={() => changeSort("top3_mt_share")}>Top-3 <SortIcon column="top3_mt_share" /></button></th>}
              <th className="px-3 py-2"><button className="inline-flex items-center gap-1" onClick={() => changeSort(metricKey)}>{variant === "consistent" ? "Consistency" : variant === "variable" ? "Variability" : "Stability"} <SortIcon column={metricKey} /></button></th>
              {variant === "variable" && <th className="px-3 py-2"><button className="inline-flex items-center gap-1" onClick={() => changeSort("temporal_stability_score")}>Stability <SortIcon column="temporal_stability_score" /></button></th>}
              {variant === "stable" && <><th className="px-3 py-2">Pattern Shift</th><th className="px-3 py-2">Previous MT</th><th className="px-3 py-2">Recent MT</th></>}
              <th className="px-3 py-2">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row, index) => (
              <tr key={row.spbu_id} className="cursor-pointer border-t border-line hover:bg-petrocloud/60" onClick={() => onSelect(row.spbu_id)}>
                <td className="px-3 py-2">{index + 1}</td><td className="whitespace-nowrap px-3 py-2 font-semibold">{row.spbu_code}</td><td className="px-3 py-2">{number(row.shipment_count)}</td><td className="whitespace-nowrap px-3 py-2">{row.dominant_mt_label}</td><td className="px-3 py-2">{percent(row.dominant_mt_probability)}</td>
                {variant !== "stable" && <td className="px-3 py-2">{number(row.unique_mt_count)}</td>}
                {variant === "consistent" && <td className="px-3 py-2">{percent(row.top3_mt_share)}</td>}
                <td className="px-3 py-2 font-semibold">{number(Number(row[metricKey]), 1)}</td>
                {variant === "variable" && <td className="px-3 py-2">{number(row.temporal_stability_score, 1)}</td>}
                {variant === "stable" && <><td className="whitespace-nowrap px-3 py-2"><span className={`border px-2 py-1 font-semibold ${shiftClass(row.pattern_shift_level)}`}>{row.pattern_shift_level}</span></td><td className="whitespace-nowrap px-3 py-2">{row.previous_dominant_label ?? "-"}</td><td className="whitespace-nowrap px-3 py-2">{row.recent_dominant_label ?? "-"}</td></>}
                <td className="px-3 py-2"><span className={`border px-2 py-1 font-semibold ${confidenceClass(row.confidence_level)}`}>{row.confidence_level}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function AffinityIntelligencePage({ depots, products }: { depots: Depot[]; products: Product[] }) {
  const [filters, setFilters] = useState<Filters>({ depotId: depots[0]?.depot_id || "", spbuId: "", startDate: "", endDate: "", productId: "", minimumObservations: "1", confidence: "ALL", temporalBucket: "WEEKLY", recentDays: "7", topN: "5", edgeMetric: "SHIPMENT_COUNT" });
  const [appliedFilters, setAppliedFilters] = useState<Filters | null>(null);
  const [spbus, setSpbus] = useState<SpbuOption[]>([]);
  const [spbuSearch, setSpbuSearch] = useState("");
  const [availability, setAvailability] = useState<DateAvailability | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [dateLoading, setDateLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedScatterPoint, setSelectedScatterPoint] = useState<Analysis["scatter"][number] | null>(null);
  const [scatterInteractionMode, setScatterInteractionMode] = useState<ChartInteractionMode>("pan");
  const [matrixInteractionMode, setMatrixInteractionMode] = useState<ChartInteractionMode>("pan");
  const [scatterViewport, setScatterViewport] = useState<ChartViewport>({ start: 0, end: 100 });
  const [matrixViewport, setMatrixViewport] = useState<ChartViewport>({ start: 0, end: 100 });
  const [savedConfigs, setSavedConfigs] = useState<SavedAffinityAnalysisConfig[]>([]);
  const [savedConfigTotal, setSavedConfigTotal] = useState(0);
  const [savedConfigOffset, setSavedConfigOffset] = useState(0);
  const [savedConfigLimit, setSavedConfigLimit] = useState(5);
  const [savedConfigLoading, setSavedConfigLoading] = useState(false);
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [loadModalOpen, setLoadModalOpen] = useState(false);
  const [selectedSavedConfigId, setSelectedSavedConfigId] = useState("");
  const [configMessage, setConfigMessage] = useState("");
  const scatterChartRef = useRef<ReactECharts>(null);
  const matrixChartRef = useRef<ReactECharts>(null);
  const requestRef = useRef(0);
  const preserveLoadedDatesRef = useRef(false);

  useEffect(() => {
    let active = true;
    apiGet<SpbuOption[]>("/api/v1/master/spbu?limit=5000")
      .then((payload) => active && setSpbus(payload))
      .catch(() => active && setSpbus([]));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!filters.depotId) { setAvailability(null); return; }
    let active = true;
    setDateLoading(true);
    apiGet<DateAvailability>(`/api/v1/affinity-intelligence/available-dates?depot_id=${encodeURIComponent(filters.depotId)}`)
      .then((payload) => {
        if (!active) return;
        setAvailability(payload);
        if (preserveLoadedDatesRef.current) {
          preserveLoadedDatesRef.current = false;
        } else {
          setFilters((current) => ({ ...current, endDate: payload.max_date ?? "", startDate: payload.max_date ? (payload.min_date && addDays(payload.max_date, -29) < payload.min_date ? payload.min_date : addDays(payload.max_date, -29)) : "" }));
        }
      })
      .catch((reason: unknown) => active && setError(reason instanceof Error ? reason.message : "Failed to load dates"))
      .finally(() => active && setDateLoading(false));
    return () => { active = false; };
  }, [filters.depotId]);

  useEffect(() => {
    void fetchSavedConfigs(savedConfigOffset, savedConfigLimit, filters.depotId);
  }, [filters.depotId, savedConfigOffset, savedConfigLimit]);

  async function load(activeFilters: Filters, selectedSpbuId?: string | null, selectedMtId?: string | null) {
    if (!activeFilters.depotId || !activeFilters.startDate || !activeFilters.endDate) { setError("Select Depot and Date Range before running Phase 4."); return; }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      depot_id: activeFilters.depotId,
      start_date: activeFilters.startDate,
      end_date: activeFilters.endDate,
      minimum_observations: activeFilters.minimumObservations,
      confidence: activeFilters.confidence,
      temporal_bucket: activeFilters.temporalBucket,
      recent_days: activeFilters.recentDays,
      top_n: activeFilters.topN,
      edge_metric: activeFilters.edgeMetric,
      network_limit: "120"
    });
    if (activeFilters.productId) params.set("product_id", activeFilters.productId);
    if (selectedSpbuId) params.set("selected_spbu_id", selectedSpbuId);
    if (selectedMtId) params.set("selected_mt_id", selectedMtId);
    try {
      const payload = await apiGet<Analysis>(`/api/v1/affinity-intelligence/analysis?${params.toString()}`);
      if (requestRef.current === requestId) setAnalysis(payload);
    } catch (reason) {
      if (requestRef.current === requestId) setError(reason instanceof Error ? reason.message : "Failed to run Phase 4 analysis");
    } finally {
      if (requestRef.current === requestId) setLoading(false);
    }
  }

  async function fetchSavedConfigs(nextOffset = savedConfigOffset, nextLimit = savedConfigLimit, depotId = filters.depotId) {
    setSavedConfigLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(nextLimit), offset: String(nextOffset) });
      if (depotId) params.set("depot_id", depotId);
      const payload = await apiGet<SavedAffinityAnalysisConfigResponse>(`/api/v1/affinity-intelligence/saved-configurations?${params.toString()}`);
      setSavedConfigs(payload.rows);
      setSavedConfigTotal(payload.total);
      setSavedConfigOffset(payload.offset);
      setSavedConfigLimit(payload.limit);
      setSelectedSavedConfigId((current) => payload.rows.some((row) => row.id === current) ? current : payload.rows[0]?.id ?? "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to load saved affinity configurations");
    } finally {
      setSavedConfigLoading(false);
    }
  }

  function openSaveModal() {
    if (!analysis || !appliedFilters) {
      setError("Run Phase 4 analysis before saving an affinity analysis configuration.");
      setConfigMessage("");
      return;
    }
    setSaveName("");
    setSaveModalOpen(true);
    setError(null);
  }

  function openLoadModal() {
    if (!savedConfigs.length) {
      setError("No saved affinity analysis configuration is available.");
      setConfigMessage("");
      return;
    }
    setSelectedSavedConfigId((current) => current || savedConfigs[0]?.id || "");
    setLoadModalOpen(true);
    setError(null);
  }

  async function saveConfig() {
    if (!analysis || !appliedFilters) return;
    const name = saveName.trim();
    if (!name) { setError("Configuration name is required."); return; }
    setSavedConfigLoading(true);
    setError(null);
    try {
      const saved = await apiSend<SavedAffinityAnalysisConfig>("/api/v1/affinity-intelligence/saved-configurations", "POST", {
        name,
        depot_id: appliedFilters.depotId,
        start_date: appliedFilters.startDate,
        end_date: appliedFilters.endDate,
        product_id: appliedFilters.productId || null,
        minimum_observations: Number(appliedFilters.minimumObservations),
        confidence: appliedFilters.confidence,
        temporal_bucket: appliedFilters.temporalBucket,
        recent_days: Number(appliedFilters.recentDays),
        top_n: Number(appliedFilters.topN),
        edge_metric: appliedFilters.edgeMetric,
        selected_spbu_id: analysis.selected_spbu_profile?.spbu_id ?? (appliedFilters.spbuId || null),
        selected_mt_id: analysis.reverse_detail?.mt_id ?? null,
        ui_state: {
          spbu_search: spbuSearch,
          scatter_interaction_mode: scatterInteractionMode,
          matrix_interaction_mode: matrixInteractionMode,
          scatter_viewport: scatterViewport,
          matrix_viewport: matrixViewport,
        },
        affinity_analysis_snapshot: analysis,
      });
      setConfigMessage(`Saved affinity analysis configuration: ${saved.name}.`);
      setSaveModalOpen(false);
      setSaveName("");
      setSavedConfigOffset(0);
      await fetchSavedConfigs(0, savedConfigLimit, appliedFilters.depotId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to save affinity analysis configuration");
    } finally {
      setSavedConfigLoading(false);
    }
  }

  async function loadConfig() {
    if (!selectedSavedConfigId) { setError("Select a saved affinity analysis configuration to load."); return; }
    setSavedConfigLoading(true);
    setError(null);
    try {
      const saved = await apiGet<SavedAffinityAnalysisConfig>(`/api/v1/affinity-intelligence/saved-configurations/${encodeURIComponent(selectedSavedConfigId)}`);
      const snapshot = saved.affinity_analysis_snapshot;
      if (!snapshot) throw new Error("Saved configuration does not contain an affinity analysis snapshot.");
      const uiState = saved.ui_state ?? {};
      const selectedProfile = snapshot.selected_spbu_profile;
      const nextFilters: Filters = {
        depotId: saved.depot_id,
        spbuId: saved.selected_spbu_id ?? selectedProfile?.spbu_id ?? "",
        startDate: saved.start_date,
        endDate: saved.end_date,
        productId: saved.product_id ?? "",
        minimumObservations: String(saved.minimum_observations),
        confidence: saved.confidence,
        temporalBucket: saved.temporal_bucket,
        recentDays: String(saved.recent_days),
        topN: String(saved.top_n),
        edgeMetric: saved.edge_metric,
      };
      if (filters.depotId !== saved.depot_id) preserveLoadedDatesRef.current = true;
      setSavedConfigOffset(0);
      setFilters(nextFilters);
      setAppliedFilters(nextFilters);
      setSpbuSearch(String(uiState.spbu_search ?? (selectedProfile ? spbuLabel(selectedProfile) : "")));
      setScatterInteractionMode(uiState.scatter_interaction_mode === "zoom" ? "zoom" : "pan");
      setMatrixInteractionMode(uiState.matrix_interaction_mode === "zoom" ? "zoom" : "pan");
      const savedScatterViewport = uiState.scatter_viewport as ChartViewport | undefined;
      const savedMatrixViewport = uiState.matrix_viewport as ChartViewport | undefined;
      setScatterViewport(savedScatterViewport?.start != null && savedScatterViewport?.end != null ? savedScatterViewport : { start: 0, end: 100 });
      setMatrixViewport(savedMatrixViewport?.start != null && savedMatrixViewport?.end != null ? savedMatrixViewport : { start: 0, end: 100 });
      setSelectedScatterPoint(null);
      setAnalysis(snapshot);
      setConfigMessage(`Loaded affinity analysis configuration: ${saved.name}.`);
      setLoadModalOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to load affinity analysis configuration");
    } finally {
      setSavedConfigLoading(false);
    }
  }

  async function deleteSavedConfig(config: SavedAffinityAnalysisConfig) {
    if (!window.confirm(`Delete saved affinity analysis configuration "${config.name}"?`)) return;
    setSavedConfigLoading(true);
    setError(null);
    try {
      await apiSend<{ status: string }>(`/api/v1/affinity-intelligence/saved-configurations/${encodeURIComponent(config.id)}`, "DELETE");
      setConfigMessage(`Deleted affinity analysis configuration: ${config.name}.`);
      setSelectedSavedConfigId((current) => current === config.id ? "" : current);
      const nextOffset = savedConfigs.length === 1 ? Math.max(0, savedConfigOffset - savedConfigLimit) : savedConfigOffset;
      setSavedConfigOffset(nextOffset);
      await fetchSavedConfigs(nextOffset, savedConfigLimit, filters.depotId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to delete affinity analysis configuration");
    } finally {
      setSavedConfigLoading(false);
    }
  }

  const searchableSpbus = useMemo(() => {
    if (analysis?.profiles.length) return analysis.profiles;
    const depotRows = filters.depotId ? spbus.filter((row) => row.primary_depot_id === filters.depotId) : spbus;
    return depotRows.length ? depotRows : spbus;
  }, [analysis, filters.depotId, spbus]);

  function spbuLabel(row: SpbuOption): string {
    return row.spbu_name && row.spbu_name !== row.spbu_code ? `${row.spbu_code} — ${row.spbu_name}` : row.spbu_code;
  }

  function resolveSpbu(value: string): SpbuOption | undefined {
    const needle = value.trim().toLowerCase();
    return searchableSpbus.find((row) => [row.spbu_id, row.spbu_code, row.spbu_name ?? "", spbuLabel(row)].some((candidate) => candidate.toLowerCase() === needle));
  }

  async function apply() {
    const matchedSpbu = spbuSearch.trim() ? resolveSpbu(spbuSearch) : undefined;
    if (spbuSearch.trim() && !matchedSpbu && !filters.spbuId) { setError("Select an SPBU from the search suggestions before applying the filter."); return; }
    const activeFilters = { ...filters, spbuId: matchedSpbu?.spbu_id ?? filters.spbuId };
    setSelectedScatterPoint(null);
    setScatterViewport({ start: 0, end: 100 });
    setMatrixViewport({ start: 0, end: 100 });
    setFilters(activeFilters);
    setAppliedFilters(activeFilters);
    await load(activeFilters, activeFilters.spbuId || null);
  }
  async function selectSpbu(spbuId: string) {
    const selected = analysis?.profiles.find((row) => row.spbu_id === spbuId) ?? spbus.find((row) => row.spbu_id === spbuId);
    if (selected) setSpbuSearch(spbuLabel(selected));
    setFilters((current) => ({ ...current, spbuId }));
    if (appliedFilters) {
      const nextFilters = { ...appliedFilters, spbuId };
      setAppliedFilters(nextFilters);
      await load(nextFilters, spbuId, null);
    }
  }
  async function selectMt(mtId: string) { if (appliedFilters) await load(appliedFilters, analysis?.selected_spbu_profile?.spbu_id, mtId); }

  function fitChart(ref: { current: ReactECharts | null }, updateMode: (mode: ChartInteractionMode) => void, updateViewport: (viewport: ChartViewport) => void) {
    const chart = ref.current?.getEchartsInstance();
    updateViewport({ start: 0, end: 100 });
    chart?.dispatchAction({ type: "dataZoom", dataZoomIndex: 0, start: 0, end: 100 });
    chart?.dispatchAction({ type: "dataZoom", dataZoomIndex: 1, start: 0, end: 100 });
    updateMode("pan");
  }

  function zoomInChart(ref: { current: ReactECharts | null }, viewport: ChartViewport, updateViewport: (viewport: ChartViewport) => void) {
    const chart = ref.current?.getEchartsInstance();
    if (!chart) return;
    const center = (viewport.start + viewport.end) / 2;
    const halfSpan = Math.max(2.5, ((viewport.end - viewport.start) * 0.7) / 2);
    const start = Math.max(0, center - halfSpan);
    const end = Math.min(100, center + halfSpan);
    updateViewport({ start, end });
    chart.dispatchAction({ type: "dataZoom", dataZoomIndex: 0, start, end });
    chart.dispatchAction({ type: "dataZoom", dataZoomIndex: 1, start, end });
  }

  const affinityOption = useMemo(() => analysis ? ({
    grid: { left: 105, right: 55, top: 18, bottom: 30 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (params: Array<{ dataIndex: number }>) => { const row = analysis.affinity_distribution[params[0]?.dataIndex ?? 0]; return row ? `<b>${row.mt_label}</b><br/>MT Tag: ${formatTags(row.mt_tags)}<br/>Shipments: ${number(row.shipment_count)}<br/>P(MT | SPBU): ${percent(row.probability_mt_given_spbu)}<br/>First: ${dateLabel(row.first_observed)}<br/>Last: ${dateLabel(row.last_observed)}` : ""; } },
    xAxis: { type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%" } },
    yAxis: { type: "category", inverse: true, data: analysis.affinity_distribution.map((row) => row.mt_label) },
    series: [{ type: "bar", data: analysis.affinity_distribution.map((row, index) => ({ value: row.probability_mt_given_spbu * 100, itemStyle: { color: index === 0 ? "#b8d211" : "#0b73bf", borderRadius: [0, 7, 7, 0] } })), label: { show: true, position: "right", formatter: ({ value }: { value: number }) => `${value.toFixed(1)}%` } }]
  }) : null, [analysis]);

  const temporalOption = useMemo(() => {
    if (!analysis?.temporal_profile.length) return null;
    const periods = [...new Set(analysis.temporal_profile.map((row) => row.period_start))].sort();
    const mtTotals = new Map<string, { label: string; total: number }>();
    analysis.temporal_profile.forEach((row) => mtTotals.set(row.mt_id, { label: row.mt_label, total: (mtTotals.get(row.mt_id)?.total ?? 0) + row.probability_mt_given_spbu }));
    const topIds = [...mtTotals.entries()].sort((left, right) => right[1].total - left[1].total).slice(0, 6).map(([id]) => id);
    return {
      tooltip: { trigger: "axis", valueFormatter: (value: number) => `${value.toFixed(1)}%` },
      legend: { type: "scroll", top: 0 },
      grid: { left: 48, right: 20, top: 55, bottom: 45 },
      xAxis: { type: "category", data: periods.map(dateLabel), axisLabel: { rotate: periods.length > 8 ? 35 : 0 } },
      yAxis: { type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%" } },
      series: topIds.map((mtId) => ({ name: mtTotals.get(mtId)?.label, type: "line", smooth: 0.18, symbolSize: 7, data: periods.map((period) => (analysis.temporal_profile.find((row) => row.period_start === period && row.mt_id === mtId)?.probability_mt_given_spbu ?? 0) * 100) }))
    };
  }, [analysis]);

  const scatterOption = useMemo(() => {
    if (!analysis) return null;
    const confidenceGroups = [
      { name: "HIGH", level: "HIGH", color: "#0b73bf" },
      { name: "MEDIUM", level: "MEDIUM", color: "#b8d211" },
      { name: "LOW", level: "LOW", color: "#ea4a43" }
    ];
    return {
      tooltip: {
        formatter: ({ data }: { data: { row?: Analysis["scatter"][number] } }) => {
          const row = data.row;
          if (!row) return "";
          return `<b>${row.spbu_name || row.spbu_code}</b><br/>Kode SPBU: ${row.spbu_code}<br/>SPBU Tag: ${formatTags(row.spbu_tags)}<br/>Shipments: ${row.shipment_count}<br/>Unique MT: ${row.value[0]}<br/>Dominant: ${row.dominant_mt_label} (${percent(row.dominant_mt_probability)})<br/>Consistency: ${number(row.consistency_score, 1)}<br/>Variability: ${number(row.variability_score, 1)}<br/>Stability: ${number(row.temporal_stability_score, 1)}<br/>Confidence: ${row.confidence_level}`;
        }
      },
      legend: { top: 0, left: "center", data: confidenceGroups.map((group) => group.name), itemWidth: 12, itemHeight: 12 },
      dataZoom: [
        { id: "scatter-x-zoom", type: "inside", xAxisIndex: 0, filterMode: "none", start: scatterViewport.start, end: scatterViewport.end, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
        { id: "scatter-y-zoom", type: "inside", yAxisIndex: 0, filterMode: "none", start: scatterViewport.start, end: scatterViewport.end, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false }
      ],
      grid: { left: 55, right: 20, top: 55, bottom: 50 },
      xAxis: { name: "Unique MT Count", nameLocation: "middle", nameGap: 32, type: "value", minInterval: 1 },
      yAxis: { name: "Consistency", type: "value", min: 0, max: 100 },
      series: confidenceGroups.map((group) => ({
        name: group.name,
        type: "scatter",
        itemStyle: { color: group.color },
        data: analysis.scatter.filter((row) => row.confidence_level === group.level).map((row) => ({
          value: row.value,
          row,
          itemStyle: row.spbu_id === selectedScatterPoint?.spbu_id ? { color: group.color, borderColor: "#15385b", borderWidth: 4 } : { color: group.color }
        })),
        symbolSize: (value: number[]) => Math.max(8, Math.min(28, 6 + Math.sqrt(value[2] ?? 0)))
      }))
    };
  }, [analysis, selectedScatterPoint, scatterViewport]);

  const matrixOption = useMemo(() => analysis ? ({
    tooltip: { formatter: ({ dataIndex }: { dataIndex: number }) => { const row = analysis.pattern_matrix.points[dataIndex]; return `<b>${row.spbu_code}</b><br/>SPBU Tag: ${formatTags(row.spbu_tags)}<br/>${row.quadrant}<br/>Unique MT: ${row.value[0]}<br/>Dominant affinity: ${percent(row.value[1])}<br/>Shipments: ${row.shipment_count}`; } },
    dataZoom: [
      { id: "matrix-x-zoom", type: "inside", xAxisIndex: 0, filterMode: "none", start: matrixViewport.start, end: matrixViewport.end, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false },
      { id: "matrix-y-zoom", type: "inside", yAxisIndex: 0, filterMode: "none", start: matrixViewport.start, end: matrixViewport.end, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false }
    ],
    grid: { left: 55, right: 25, top: 25, bottom: 50 },
    xAxis: { name: "Unique MT", nameLocation: "middle", nameGap: 32, type: "value", minInterval: 1 },
    yAxis: { name: "Dominant Affinity", type: "value", min: 0, max: 1, axisLabel: { formatter: (value: number) => `${Math.round(value * 100)}%` } },
    series: [{ type: "scatter", data: analysis.pattern_matrix.points.map((row) => ({ value: row.value, itemStyle: { color: row.quadrant === "DEDICATED-LIKE" ? "#0b73bf" : row.quadrant === "PREFERRED-FLEET" ? "#b8d211" : row.quadrant === "HIGHLY FLEXIBLE" ? "#ea4a43" : "#94a3b8" } })), symbolSize: 11, markLine: { silent: true, symbol: "none", lineStyle: { type: "dashed", color: "#94a3b8" }, data: [{ xAxis: analysis.pattern_matrix.unique_mt_split }, { yAxis: analysis.pattern_matrix.affinity_split }] } }]
  }) : null, [analysis, matrixViewport]);

  const reverseOption = useMemo(() => analysis?.reverse_detail ? ({
    grid: { left: 100, right: 50, top: 15, bottom: 30 },
    tooltip: { trigger: "axis", valueFormatter: (value: number) => `${value.toFixed(1)}%` },
    xAxis: { type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%" } },
    yAxis: { type: "category", inverse: true, data: analysis.reverse_detail.distribution.slice(0, 10).map((row) => row.spbu_code) },
    series: [{ type: "bar", data: analysis.reverse_detail.distribution.slice(0, 10).map((row) => row.probability_spbu_given_mt * 100), itemStyle: { color: "#15385b", borderRadius: [0, 7, 7, 0] }, label: { show: true, position: "right", formatter: ({ value }: { value: number }) => `${value.toFixed(1)}%` } }]
  }) : null, [analysis]);

  const networkOption = useMemo(() => analysis ? ({
    tooltip: { formatter: (params: { dataType: string; data: Record<string, unknown> }) => {
      const data = params.data;
      if (params.dataType === "edge") return `<b>${String(data.spbu_code)} ↔ ${String(data.mt_label)}</b><br/>SPBU Tag: ${formatTags(data.spbu_tags as string[])}<br/>MT Tag: ${formatTags(data.mt_tags as string[])}<br/>Historical Shipments: ${String(data.shipment_count)}<br/>P(MT | SPBU): ${percent(Number(data.probability_mt_given_spbu))}<br/>P(SPBU | MT): ${percent(Number(data.probability_spbu_given_mt))}<br/>First: ${dateLabel(String(data.first_observed))}<br/>Last: ${dateLabel(String(data.last_observed))}<br/>Operating Days: ${String(data.operating_day_count)}<br/>Confidence: ${String(data.confidence_level)}`;
      const entityType = String(data.entity_type);
      return `<b>${entityType}</b><br/>${String(data.name)}<br/>${entityType} Tag: ${formatTags(data.tags as string[])}`;
    } },
    legend: [{ data: analysis.network.categories.map((row) => row.name), bottom: 0 }],
    series: [{ type: "graph", layout: "force", roam: true, draggable: true, categories: analysis.network.categories, data: analysis.network.nodes.map((row) => ({ ...row, itemStyle: { color: row.category === 0 ? "#0b73bf" : "#b8d211", borderColor: row.selected ? "#ea4a43" : "#fff", borderWidth: row.selected ? 4 : 1 }, label: { show: row.selected, position: "right" } })), links: analysis.network.edges.map((row) => ({ ...row, lineStyle: { width: row.highlighted ? 4 : Math.max(1, Math.min(6, Math.sqrt(row.shipment_count))), opacity: row.highlighted ? 0.95 : 0.35, color: row.highlighted ? "#ea4a43" : "#94a3b8", curveness: 0.08 } })), force: { repulsion: 130, edgeLength: [60, 160] }, emphasis: { focus: "adjacency", lineStyle: { width: 5, opacity: 1 } } }]
  }) : null, [analysis]);

  const kpis: Array<[string, number, number?]> = analysis ? [
    ["Eligible Shipments", analysis.summary.total_eligible_shipments], ["SPBU Analyzed", analysis.summary.spbu_analyzed], ["MT Observed", analysis.summary.mt_observed], ["Unique SPBU–MT Pairs", analysis.summary.unique_spbu_mt_pairs], ["Avg MT / SPBU", analysis.summary.average_mt_per_spbu, 2], ["Median MT / SPBU", analysis.summary.median_mt_per_spbu, 1], ["High Consistency", analysis.summary.high_consistency_spbu], ["High Variability", analysis.summary.high_variability_spbu], ["Low Stability", analysis.summary.low_stability_spbu], ["Pattern Shifts", analysis.summary.historical_pattern_shifts]
  ] : [];
  const savedShowingStart = savedConfigTotal === 0 ? 0 : savedConfigOffset + 1;
  const savedShowingEnd = Math.min(savedConfigOffset + savedConfigLimit, savedConfigTotal);
  const savedPageNumber = Math.floor(savedConfigOffset / savedConfigLimit) + 1;
  const savedPageCount = Math.max(1, Math.ceil(savedConfigTotal / savedConfigLimit));
  const canPreviousSavedPage = savedConfigOffset > 0 && !savedConfigLoading;
  const canNextSavedPage = savedConfigOffset + savedConfigLimit < savedConfigTotal && !savedConfigLoading;

  return (
    <>
      {saveModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 px-4">
          <div className="w-full max-w-lg border border-line bg-white p-5 shadow-card">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Save Affinity Analysis Configuration</div><div className="mt-1 text-xs text-slate-500">The current Phase 4 filters, selected SPBU–MT detail, chart viewport, and analysis snapshot will be stored in the backend.</div></div>
              <button className="inline-flex h-8 w-8 items-center justify-center border border-line" onClick={() => setSaveModalOpen(false)} title="Close save configuration"><X size={16} /></button>
            </div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Configuration Name<input className="mt-2 w-full border border-line px-3 py-2 text-sm font-normal normal-case tracking-normal" value={saveName} onChange={(event) => setSaveName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void saveConfig(); }} autoFocus placeholder="Example: Medan affinity baseline" /></label>
            <div className="mt-5 flex items-center justify-end gap-2"><button className="border border-line px-3 py-2 text-sm" onClick={() => setSaveModalOpen(false)}>Cancel</button><button className="inline-flex items-center gap-2 bg-petroblue px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={() => void saveConfig()} disabled={savedConfigLoading || !saveName.trim()}><Save size={14} /> Save</button></div>
          </div>
        </div>
      )}
      {loadModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 px-4">
          <div className="w-full max-w-xl border border-line bg-white p-5 shadow-card">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Load Affinity Analysis Configuration</div><div className="mt-1 text-xs text-slate-500">Loading restores the saved Phase 4 filters, selected SPBU–MT detail, chart viewport, and analysis snapshot.</div></div>
              <button className="inline-flex h-8 w-8 items-center justify-center border border-line" onClick={() => setLoadModalOpen(false)} title="Close load configuration"><X size={16} /></button>
            </div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">Saved Configuration<select className="mt-2 w-full border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal" value={selectedSavedConfigId} onChange={(event) => setSelectedSavedConfigId(event.target.value)}>{savedConfigs.map((config) => <option key={config.id} value={config.id}>{config.name} | {config.depot_name ?? config.depot_id} | {dateLabel(config.start_date)} – {dateLabel(config.end_date)}</option>)}</select></label>
            <div className="mt-5 flex items-center justify-end gap-2"><button className="border border-line px-3 py-2 text-sm" onClick={() => setLoadModalOpen(false)}>Cancel</button><button className="inline-flex items-center gap-2 bg-petroblue px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={() => void loadConfig()} disabled={savedConfigLoading || !selectedSavedConfigId}><RefreshCw size={14} /> Load</button></div>
          </div>
        </div>
      )}
      <section className="mb-5 border border-line bg-white p-4">
        <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Phase 4 — SPBU–MT Historical Affinity & Stability Intelligence</div><div className="mt-1 text-xs text-slate-500">Measures assignments that historically occurred. It does not optimize or recommend future MT assignments.</div></div>
          <div className="flex flex-col items-start gap-2 lg:items-end"><div className="flex flex-wrap gap-2"><button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50" onClick={openLoadModal} disabled={savedConfigLoading || savedConfigTotal === 0} title="Load a saved affinity analysis configuration"><RefreshCw size={14} /> Load</button><button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50" onClick={openSaveModal} disabled={loading || !analysis} title="Save current affinity configuration and analysis result"><Save size={14} /> Save</button></div>{configMessage && <div className="text-xs text-slate-500">{configMessage}</div>}</div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 xl:grid-cols-6">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Depot<select className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal normal-case" value={filters.depotId} onChange={(event) => { setAnalysis(null); setAppliedFilters(null); setSpbuSearch(""); setSavedConfigOffset(0); setFilters((current) => ({ ...current, depotId: event.target.value, spbuId: "" })); }}>{depots.map((depot) => <option key={depot.depot_id} value={depot.depot_id}>{depot.depot_name}</option>)}</select></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Search SPBU<input className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal normal-case" type="search" list="phase4-spbu-options" value={spbuSearch} placeholder="Code or SPBU name" disabled={!filters.depotId} onChange={(event) => { const value = event.target.value; const matched = resolveSpbu(value); setSpbuSearch(value); setFilters((current) => ({ ...current, spbuId: matched?.spbu_id ?? "" })); }} /><datalist id="phase4-spbu-options">{searchableSpbus.map((row) => <option key={row.spbu_id} value={spbuLabel(row)} />)}</datalist></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Start Date<input className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal" type="date" value={filters.startDate} min={availability?.min_date ?? undefined} max={availability?.max_date ?? undefined} disabled={dateLoading} onChange={(event) => setFilters((current) => ({ ...current, startDate: event.target.value }))} /></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">End Date<input className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal" type="date" value={filters.endDate} min={availability?.min_date ?? undefined} max={availability?.max_date ?? undefined} disabled={dateLoading} onChange={(event) => setFilters((current) => ({ ...current, endDate: event.target.value }))} /></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Product<select className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal normal-case" value={filters.productId} onChange={(event) => setFilters((current) => ({ ...current, productId: event.target.value }))}><option value="">All Products</option>{products.map((product) => <option key={product.product_id} value={product.product_id}>{product.product_name}</option>)}</select></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Minimum Observations<input className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal" type="number" min="1" value={filters.minimumObservations} onChange={(event) => setFilters((current) => ({ ...current, minimumObservations: event.target.value }))} /></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Confidence<select className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal" value={filters.confidence} onChange={(event) => setFilters((current) => ({ ...current, confidence: event.target.value }))}><option value="ALL">All</option><option value="MEDIUM+">Medium+</option><option value="HIGH">High</option></select></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Temporal Bucket<select className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal" value={filters.temporalBucket} onChange={(event) => setFilters((current) => ({ ...current, temporalBucket: event.target.value }))}><option value="AUTO">Auto</option><option value="DAILY">Daily</option><option value="WEEKLY">Weekly</option><option value="MONTHLY">Monthly</option></select></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recent Period<select className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal" value={filters.recentDays} onChange={(event) => setFilters((current) => ({ ...current, recentDays: event.target.value }))}><option value="7">7 Days</option><option value="14">14 Days</option><option value="30">30 Days</option></select></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top MT<select className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal" value={filters.topN} onChange={(event) => setFilters((current) => ({ ...current, topN: event.target.value }))}><option value="5">Top 5</option><option value="10">Top 10</option><option value="0">All</option></select></label>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Network Edge<select className="mt-1 w-full border border-line px-3 py-2 text-sm font-normal" value={filters.edgeMetric} onChange={(event) => setFilters((current) => ({ ...current, edgeMetric: event.target.value }))}><option value="SHIPMENT_COUNT">Shipment Count</option><option value="AFFINITY_PROBABILITY">Affinity Probability</option></select></label>
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><div className="text-xs text-slate-500">{availability?.min_date ? `Available: ${dateLabel(availability.min_date)} – ${dateLabel(availability.max_date)}` : filters.depotId ? "No shipment dates available." : "Select a depot to load its historical date coverage."}</div><button className="inline-flex items-center gap-2 rounded-full bg-petroblue px-5 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={loading || dateLoading} onClick={apply}><RefreshCw size={15} className={loading ? "animate-spin" : ""} />{loading ? "Running" : "Apply"}</button></div>
        <div className="mt-4 border border-line">
          <div className="flex flex-col gap-2 border-b border-line bg-slate-50 px-3 py-2 lg:flex-row lg:items-center lg:justify-between"><div><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Saved SPBU–MT Affinity Analysis Configurations</div><div className="mt-1 text-xs text-slate-500">Showing {savedShowingStart}-{savedShowingEnd} of {savedConfigTotal.toLocaleString()}</div></div><select className="border border-line bg-white px-2 py-1 text-xs" value={savedConfigLimit} onChange={(event) => { setSavedConfigOffset(0); setSavedConfigLimit(Number(event.target.value)); }} title="Saved configurations per page"><option value={5}>5 rows</option><option value={10}>10 rows</option><option value={25}>25 rows</option></select></div>
          <div className="overflow-x-auto"><table className="w-full border-collapse text-sm"><thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-slate-500"><th className="whitespace-nowrap px-3 py-2">Name</th><th className="whitespace-nowrap px-3 py-2">Depot</th><th className="whitespace-nowrap px-3 py-2">Period</th><th className="whitespace-nowrap px-3 py-2">Product</th><th className="whitespace-nowrap px-3 py-2">SPBU</th><th className="whitespace-nowrap px-3 py-2">MT</th><th className="whitespace-nowrap px-3 py-2">Saved</th><th className="whitespace-nowrap px-3 py-2">Action</th></tr></thead><tbody>{savedConfigs.map((config) => <tr key={config.id} className="border-b border-line"><td className="whitespace-nowrap px-3 py-2 font-medium">{config.name}</td><td className="whitespace-nowrap px-3 py-2">{config.depot_name ?? config.depot_id}</td><td className="whitespace-nowrap px-3 py-2">{dateLabel(config.start_date)} – {dateLabel(config.end_date)}</td><td className="whitespace-nowrap px-3 py-2">{config.product_name}</td><td className="whitespace-nowrap px-3 py-2">{number(config.spbu_analyzed)}</td><td className="whitespace-nowrap px-3 py-2">{number(config.mt_observed)}</td><td className="whitespace-nowrap px-3 py-2">{dateTimeLabel(config.updated_at)}</td><td className="whitespace-nowrap px-3 py-2"><button className="inline-flex items-center justify-center border border-line px-2 py-1 text-xs text-rust disabled:opacity-50" onClick={() => void deleteSavedConfig(config)} disabled={savedConfigLoading} title="Delete saved configuration"><Trash2 size={13} /></button></td></tr>)}{savedConfigs.length === 0 && <tr><td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={8}>No saved affinity analysis configuration.</td></tr>}</tbody></table></div>
          <div className="flex items-center justify-between gap-3 px-3 py-2 text-sm"><button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setSavedConfigOffset(Math.max(0, savedConfigOffset - savedConfigLimit))} disabled={!canPreviousSavedPage}>Previous</button><span className="text-slate-500">Page {savedPageNumber} of {savedPageCount}</span><button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setSavedConfigOffset(savedConfigOffset + savedConfigLimit)} disabled={!canNextSavedPage}>Next</button></div>
        </div>
      </section>

      {error && <div className="mb-5 rounded-2xl border border-rust bg-white px-4 py-3 text-sm text-rust">{error}</div>}
      {!analysis && <section className="border border-dashed border-petroblue/30 bg-white/75 px-6 py-16 text-center"><Network className="mx-auto mb-3 text-petroblue/60" size={32} /><div className="font-semibold">Phase 4 is waiting for an explicit analysis scope</div><div className="mt-1 text-sm text-slate-500">KPI, charts, rankings, tables, and network remain empty until Apply is pressed.</div></section>}

      {analysis && <>
        <section className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{kpis.map(([label, value, digits]) => <div key={label} className="rounded-3xl border border-petroblue/10 bg-white p-4 shadow-card"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-2 text-2xl font-semibold text-petroink">{number(value, digits ?? 0)}</div></div>)}</section>

        <section className="mb-5 border border-line bg-white p-4"><div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Data Quality Summary</div><div className="grid gap-2 text-sm">{[["Source Shipments", analysis.data_quality.source_shipments], ["Eligible Shipments", analysis.data_quality.eligible_shipments], ["Excluded Shipments", analysis.data_quality.excluded_shipments], ["Eligible %", `${number(analysis.data_quality.eligible_pct, 1)}%`], ["Duplicate Observations Removed", analysis.data_quality.duplicate_observations_removed]].map(([label, value]) => <div key={label} className="flex items-center justify-between border-b border-line pb-2"><span>{label}</span><span className="font-semibold">{typeof value === "number" ? number(value) : value}</span></div>)}</div><div className="mt-3 space-y-1 text-xs text-slate-500">{analysis.data_quality.exclusion_reasons.map((row) => <div key={row.reason}>{row.reason}: {number(row.count)}</div>)}{analysis.data_quality.exclusion_reasons.length === 0 && <div>No exclusions in the active scope.</div>}</div><div className="mt-4 rounded-2xl bg-petrocloud p-3 text-xs text-slate-600">Bucket used: <b>{String(analysis.effective_filters.temporal_bucket_used)}</b><br/>Algorithm: <b>{analysis.algorithm_version}</b></div></section>

        <section className="mb-5 grid gap-4 lg:grid-cols-2">
          <section className="relative border border-line bg-white p-4">
            <div className="mb-3 flex items-center justify-between gap-3"><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">SPBU Consistency Scatter Plot</div><ChartInteractionToolbar mode={scatterInteractionMode} onModeChange={setScatterInteractionMode} onZoom={() => zoomInChart(scatterChartRef, scatterViewport, setScatterViewport)} onFit={() => fitChart(scatterChartRef, setScatterInteractionMode, setScatterViewport)} /></div>
            {selectedScatterPoint && <div className="absolute right-6 top-16 z-10 min-w-56 max-w-80 rounded-2xl border border-petroblue/20 bg-white/95 p-3 shadow-card"><button className="absolute right-2 top-1 text-lg leading-none text-slate-400 hover:text-petroink" onClick={() => setSelectedScatterPoint(null)} title="Close selected SPBU popup">×</button><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Selected SPBU</div><div className="mt-1 pr-5 font-semibold text-petroink">{selectedScatterPoint.spbu_name || selectedScatterPoint.spbu_code}</div>{selectedScatterPoint.spbu_name && <div className="mt-1 text-xs text-slate-500">Kode: {selectedScatterPoint.spbu_code}</div>}<div className="mt-2 text-xs text-slate-500">SPBU Tag: <b>{formatTags(selectedScatterPoint.spbu_tags)}</b></div><div className="mt-1 text-xs text-slate-500">Confidence: <b>{selectedScatterPoint.confidence_level}</b></div></div>}
            {scatterOption && <div className={scatterInteractionMode === "zoom" ? "cursor-zoom-in" : "cursor-grab"}><ReactECharts ref={scatterChartRef} option={scatterOption} style={{ height: 360 }} onEvents={{ click: (params: { data?: { row?: Analysis["scatter"][number] } }) => { const row = params.data?.row; if (row) { setSelectedScatterPoint(row); selectSpbu(row.spbu_id); } } }} /></div>}
          </section>
          <section className="border border-line bg-white p-4">
            <div className="mb-1 flex items-center justify-between gap-3"><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Historical Pattern Matrix</div><ChartInteractionToolbar mode={matrixInteractionMode} onModeChange={setMatrixInteractionMode} onZoom={() => zoomInChart(matrixChartRef, matrixViewport, setMatrixViewport)} onFit={() => fitChart(matrixChartRef, setMatrixInteractionMode, setMatrixViewport)} /></div>
            <div className="mb-2 text-xs text-slate-500">Dashed lines use 60% dominant affinity and the active SPBU median unique-MT count.</div>
            {matrixOption && <div className={matrixInteractionMode === "zoom" ? "cursor-zoom-in" : "cursor-grab"}><ReactECharts ref={matrixChartRef} option={matrixOption} style={{ height: 350 }} onEvents={{ click: (params: { dataIndex?: number }) => { const row = analysis.pattern_matrix.points[params.dataIndex ?? -1]; if (row) selectSpbu(row.spbu_id); } }} /></div>}
          </section>
        </section>

        <section className="mb-5 grid gap-4 xl:grid-cols-3"><RankingTable title="Most Historically Consistent SPBU" rows={analysis.rankings.most_consistent} variant="consistent" onSelect={selectSpbu} /><RankingTable title="Most Historically Variable SPBU" rows={analysis.rankings.most_variable} variant="variable" onSelect={selectSpbu} /><RankingTable title="Highest Historical Pattern Change" rows={analysis.rankings.least_stable} variant="stable" onSelect={selectSpbu} /></section>

        <section className="mb-5 border border-line bg-white p-4"><div className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-600">Historical SPBU–MT Bipartite Network</div><div className="mb-2 text-xs text-slate-500">Blue nodes are SPBU; lime nodes are MT. Click either node to switch orientation. Edge width reflects historical shipment evidence.</div>{networkOption ? <ReactECharts option={networkOption} style={{ height: 540 }} onEvents={{ click: (params: { dataType?: string; data?: { entity_type?: string; entity_id?: string } }) => { if (params.dataType !== "node" || !params.data?.entity_id) return; if (params.data.entity_type === "SPBU") selectSpbu(params.data.entity_id); else selectMt(params.data.entity_id); } }} /> : <div className="py-20 text-center text-sm text-slate-500">No network edges.</div>}</section>

        <section className="mb-5 border border-line bg-white p-4"><div className="mb-3 flex flex-wrap items-end justify-between gap-2"><div><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Historical Evidence Drill-Down</div><div className="mt-1 text-xs text-slate-500">{analysis.evidence.relationship ? `${analysis.selected_spbu_profile?.spbu_code ?? analysis.evidence.relationship.spbu_id} ↔ ${analysis.reverse_detail?.mt_label ?? analysis.evidence.relationship.mt_id}: ${number(analysis.evidence.distinct_shipment_count)} distinct shipments` : "Select a valid SPBU–MT relationship."}</div></div><div className="text-xs text-slate-500">Audited to shipment source; duplicated LO rows do not duplicate observations.</div></div><div className="max-h-[440px] overflow-auto border border-line"><table className="w-full border-collapse text-xs"><thead className="sticky top-0 bg-slate-50 text-left uppercase tracking-wide text-slate-500"><tr>{["Date", "Shipment ID", "Depot", "Gate Out", "MT", "SPBU", "Products", "Quantity", "Other SPBU"].map((label) => <th key={label} className="whitespace-nowrap px-3 py-2">{label}</th>)}</tr></thead><tbody>{analysis.evidence.rows.map((row) => <tr key={`${row.shipment_id}-${row.spbu_id}-${row.mt_id}`} className="border-t border-line"><td className="whitespace-nowrap px-3 py-2">{dateLabel(row.date)}</td><td className="whitespace-nowrap px-3 py-2 font-semibold">{row.source_shipment_id}</td><td className="whitespace-nowrap px-3 py-2">{row.depot}</td><td className="whitespace-nowrap px-3 py-2">{row.gate_out ? new Date(row.gate_out).toLocaleString() : "-"}</td><td className="px-3 py-2">{analysis.reverse_detail?.mt_label ?? row.mt_id}</td><td className="px-3 py-2">{analysis.selected_spbu_profile?.spbu_code ?? row.spbu_id}</td><td className="min-w-36 px-3 py-2">{row.products.join(", ") || "-"}</td><td className="px-3 py-2">{number(row.quantity, 2)}</td><td className="min-w-36 px-3 py-2">{row.other_spbu_ids.join(", ") || "-"}</td></tr>)}{analysis.evidence.rows.length === 0 && <tr><td colSpan={9} className="px-3 py-10 text-center text-sm text-slate-500">No evidence for the selected relationship.</td></tr>}</tbody></table></div></section>

        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">SPBU–MT Historical Profile</div>
          {analysis.selected_spbu_profile ? <><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[
            ["SPBU", analysis.selected_spbu_profile.spbu_code], ["SPBU Tag", formatTags(analysis.selected_spbu_profile.spbu_tags)], ["Historical Shipments", number(analysis.selected_spbu_profile.shipment_count)], ["Operating Days", number(analysis.selected_spbu_profile.operating_day_count)], ["Unique MT Used", number(analysis.selected_spbu_profile.unique_mt_count)], ["Dominant Historical MT", analysis.selected_spbu_profile.dominant_mt_label], ["Dominant Probability", percent(analysis.selected_spbu_profile.dominant_mt_probability)], ["Top-3 MT Share", percent(analysis.selected_spbu_profile.top3_mt_share)], ["Historical Pattern", analysis.selected_spbu_profile.historical_pattern]
          ].map(([label, value]) => <div key={label} className="rounded-2xl border border-line p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 font-semibold">{value}</div></div>)}</div>
            <div className="mt-4 grid gap-4 md:grid-cols-2"><MetricTrack label="MT Consistency" value={analysis.selected_spbu_profile.consistency_score} /><MetricTrack label="Historical Variability" value={analysis.selected_spbu_profile.variability_score} color="#ea4a43" /><MetricTrack label="Temporal Stability" value={analysis.selected_spbu_profile.temporal_stability_score} color="#b8d211" /><MetricTrack label="Evidence Confidence" value={analysis.selected_spbu_profile.confidence_score} color="#15385b" /></div>
            <div className="mt-4 flex flex-wrap gap-2"><span className={`border px-2 py-1 text-xs font-semibold ${confidenceClass(analysis.selected_spbu_profile.confidence_level)}`}>Confidence {analysis.selected_spbu_profile.confidence_level}</span><span className={`border px-2 py-1 text-xs font-semibold ${shiftClass(analysis.selected_spbu_profile.pattern_shift_level)}`}>{analysis.selected_spbu_profile.pattern_shift_level}</span><span className="border border-line px-2 py-1 text-xs font-semibold">{analysis.selected_spbu_profile.consistency_classification}</span><span className="border border-line px-2 py-1 text-xs">Dominant persistence {number(analysis.selected_spbu_profile.dominant_mt_persistence, 1)}%</span></div>
          </> : <div className="py-10 text-center text-sm text-slate-500">No SPBU meets the active observation/confidence filter.</div>}
        </section>

        <section className="mb-5 grid gap-4 lg:grid-cols-2"><section className="border border-line bg-white p-4"><div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">MT Historical Probability — {analysis.selected_spbu_profile?.spbu_code ?? "SPBU"}</div>{affinityOption ? <ReactECharts option={affinityOption} style={{ height: 340 }} onEvents={{ click: (params: { dataIndex?: number }) => { const row = analysis.affinity_distribution[params.dataIndex ?? -1]; if (row) selectMt(row.mt_id); } }} /> : <div className="py-20 text-center text-sm text-slate-500">No affinity distribution.</div>}</section><section className="border border-line bg-white p-4"><div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Historical MT Affinity Over Time</div>{temporalOption ? <ReactECharts option={temporalOption} style={{ height: 340 }} /> : <div className="py-20 text-center text-sm text-slate-500">No temporal distribution.</div>}</section></section>

        <section className="mb-5 grid gap-4 lg:grid-cols-[0.8fr_1.2fr]"><section className="border border-line bg-white p-4"><div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Recent vs Full-Period Pattern</div><div className="mb-3 text-xs text-slate-500">Recent begins {dateLabel(analysis.recent_comparison.recent_start_date)}. No hidden recency weighting is applied.</div><div className="grid gap-4 sm:grid-cols-2">{([[
          "Full selected period", analysis.recent_comparison.full_period
        ], [
          "Recent period", analysis.recent_comparison.recent_period
        ]] as Array<[string, DistributionRow[]]>).map(([title, rows]) => <div key={title}><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div><div className="space-y-2">{rows.slice(0, 5).map((row) => <button key={row.mt_id} className="flex w-full items-center justify-between rounded-xl border border-line px-3 py-2 text-left text-xs hover:bg-petrocloud" onClick={() => selectMt(row.mt_id)}><span className="font-semibold">{row.mt_label}</span><span>{percent(row.probability)}</span></button>)}</div></div>)}</div></section><section className="border border-line bg-white p-4"><div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">MT Reverse Historical Affinity</div>{analysis.reverse_detail && reverseOption ? <><div className="mb-2 flex flex-wrap gap-3 text-xs text-slate-500"><b className="text-petroink">{analysis.reverse_detail.mt_label}</b><span>{number(analysis.reverse_detail.historical_shipments)} shipments</span><span>{number(analysis.reverse_detail.unique_spbu_count)} unique SPBU</span><span>{number(analysis.reverse_detail.operating_day_count)} operating days</span><span>Concentration {number(analysis.reverse_detail.consistency_score, 1)}</span><span>Stability {number(analysis.reverse_detail.temporal_stability_score, 1)}</span><span>Dominant SPBU persistence {number(analysis.reverse_detail.dominant_spbu_persistence, 1)}%</span><span className={`border px-2 py-1 font-semibold ${shiftClass(analysis.reverse_detail.pattern_shift_level)}`}>{analysis.reverse_detail.pattern_shift_level}</span></div><ReactECharts option={reverseOption} style={{ height: 290 }} onEvents={{ click: (params: { dataIndex?: number }) => { const row = analysis.reverse_detail?.distribution[params.dataIndex ?? -1]; if (row) selectSpbu(row.spbu_id); } }} /></> : <div className="py-20 text-center text-sm text-slate-500">Select an MT to view P(SPBU | MT).</div>}</section></section>

        <section className="border border-line bg-white p-4"><div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Methodology & Guardrails</div><div className="mt-3 grid gap-3 text-xs text-slate-600 md:grid-cols-2 lg:grid-cols-4"><div className="rounded-2xl bg-petrocloud p-3"><b>Consistency</b><br/>{String(analysis.methodology.consistency)}</div><div className="rounded-2xl bg-petrocloud p-3"><b>Variability</b><br/>{String(analysis.methodology.variability)}</div><div className="rounded-2xl bg-petrocloud p-3"><b>Temporal Stability</b><br/>{String(analysis.methodology.temporal_stability)}</div><div className="rounded-2xl bg-petrocloud p-3"><b>Confidence</b><br/>{String(analysis.methodology.confidence)}</div></div><div className="mt-3 text-xs font-semibold text-petroink">Historical affinity is descriptive evidence, not a recommendation, assignment suggestion, or optimization result.</div></section>
      </>}
    </>
  );
}
