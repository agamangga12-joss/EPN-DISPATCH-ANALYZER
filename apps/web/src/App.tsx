import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, Database, Download, Eye, FileUp, GitBranch, MapPinned, Menu, Pencil, Plus, RefreshCw, Route, Save, Search, Trash2, UserCircle, X } from "lucide-react";
import ReactECharts from "echarts-for-react";
import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import "./index.css";
import { apiGet, apiSend, downloadFromApi, uploadImportFile, type SeriesPoint } from "./lib/api";
import { ChartPanel } from "./components/ChartPanel";
import { AffinityIntelligencePage } from "./components/AffinityIntelligencePage";
import { MachineLearningIntelligencePage } from "./components/MachineLearningIntelligencePage";
import { PredictionAssignmentPage } from "./components/PredictionAssignmentPage";
import { GoogleMapsIntegrationPage } from "./components/GoogleMapsIntegrationPage";
import { AppSidebar, type AppPage } from "./components/AppSidebar";
import { DocumentationPage } from "./components/DocumentationPage";
import { Phase7OptimizationPage } from "./components/Phase7OptimizationPage";
import { RestrictedRoadsPage } from "./components/RestrictedRoadsPage";
import { ManualDispatchPage } from "./components/ManualDispatchPage";
import { RouteModelAlignmentPage } from "./components/RouteModelAlignmentPage";
import { AmtSchedulerConnectorPage } from "./components/AmtSchedulerConnectorPage";

type Overview = Record<string, number>;
type Charts = Record<string, SeriesPoint[]>;
type ImportAudit = {
  depot_id?: string | null;
  import_id: string;
  domain: string;
  filename: string;
  sheet_name: string;
  uploaded_at: string;
  total_rows: number;
  valid_rows: number;
  warning_rows: number;
  rejected_rows: number;
  status: string;
  processed_rows?: number;
  file_size_bytes?: number | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};
type ImportDetail = { import: ImportAudit; preview: Array<Record<string, unknown>> };
type QualityIssue = {
  issue_id: string;
  entity_type: string;
  entity_id: string | null;
  rule_code: string;
  severity: string;
  description: string;
};
type CompatibilitySummary = {
  compatible: number;
  incompatible: number;
  insufficient_data: number;
  examples: Array<Record<string, unknown>>;
};
type Depot = {
  depot_id: string;
  active_status?: string;
  depot_code: string | null;
  depot_name: string;
};
type Product = {
  product_id: string;
  product_name: string;
  active_status?: string;
};
type TagType = {
  tag_type_id: string;
  code: string;
  name: string;
};
type CrudResponse = {
  domain: string;
  total: number;
  limit: number;
  offset: number;
  rows: Array<Record<string, unknown>>;
};
type CrudField = {
  key: string;
  label: string;
  kind?: "text" | "number" | "select" | "textarea" | "checkbox" | "time";
  required?: boolean;
  defaultValue?: string | number | boolean;
  readonlyOnEdit?: boolean;
  options?: Array<{ label: string; value: string }>;
};
type CrudDomainConfig = {
  label: string;
  idKey: string;
  titleKey: string;
  columns: string[];
  fields: CrudField[];
  depotFilter?: boolean;
  statusFilter?: boolean;
};
type Page = AppPage;
const pageMetadata: Record<Page, { eyebrow: string; title: string; description: string }> = {
  dashboard: {
    eyebrow: "Overview",
    title: "Dashboard",
    description: "Data foundation overview and operational intelligence summary.",
  },
  "restricted-roads": { eyebrow: "Data Foundation", title: "Master Restricted Roads", description: "Kelola ruas jalan terlarang per depot untuk routing Dynamic VRP." },
  "master-data": {
    eyebrow: "Data Foundation",
    title: "Master Data Management",
    description: "Kelola MT, SPBU, historikal shipment, depot, produk, dan tag sesuai depot aktif.",
  },
  "tag-consistency": {
    eyebrow: "Data Foundation",
    title: "Tag Consistency Analysis",
    description: "Evaluate daily Loading Order assignments against MT–SPBU tagging rules.",
  },
  "departure-intelligence": {
    eyebrow: "Phase 2 · Intelligence",
    title: "Depot Departure Time Intelligence",
    description: "Historical depot departure profiles and operational shift patterns by SPBU.",
  },
  "pairing-intelligence": {
    eyebrow: "Phase 3 · Intelligence",
    title: "SPBU Pairing Probability Intelligence",
    description: "Same-shipment SPBU relationship intelligence with directional GPS evidence.",
  },
  "affinity-intelligence": {
    eyebrow: "Phase 4 · Intelligence",
    title: "SPBU–MT Affinity & Stability",
    description: "Historical SPBU–MT affinity, concentration, and temporal stability intelligence.",
  },
  "machine-learning-intelligence": {
    eyebrow: "Phase 5 · Intelligence",
    title: "Machine Learning Intelligence",
    description: "Historical concentration anomaly detection and SPBU behavioral clustering.",
  },
  "prediction-assignment": {
    eyebrow: "Phase 6 · Planning",
    title: "Prediction & Assignment",
    description: "Time-aware shipment prediction, rolling multi-trip MT assignment, and availability estimates.",
  },
  "phase7-optimization": {
    eyebrow: "Phase 7 · Optimization & Control",
    title: "Dynamic Multi-Trip VRP & Depot Bay Queue",
    description: "Fleet-wide OR-Tools routing, FIFO_BALANCED bay scheduling, rolling operational updates, and immutable route versions.",
  },
  "manual-dispatch": {
    eyebrow: "Phase 8 · Manual Dispatch & Simulation",
    title: "Manual Dispatching & Operational Simulation",
    description: "Human-in-the-loop trip adjustment, compatibility guardrails, route recalculation, fleet simulation, audit, and final dispatch.",
  },
  "route-model-alignment": {
    eyebrow: "Phase 9 · Evaluation",
    title: "Route–Model Alignment Evaluation",
    description: "Neutral, source-aligned measurement of route similarity to historical cluster, shift, SPBU pairing, and MT affinity patterns.",
  },
  "amt-scheduler-connector": {
    eyebrow: "Phase 10 · Integration",
    title: "AMT Scheduler Connector",
    description: "Secure, read-only, versioned access to terminal, MT, historical operation, route, shift, and route-specific availability data.",
  },
  "google-maps-integration": {
    eyebrow: "Settings",
    title: "Google Maps Integration",
    description: "Secure DRIVE-only route estimation, cache, fallback, and cycle-time settings.",
  },
  documentation: {
    eyebrow: "Support",
    title: "Documentation",
    description: "Panduan fungsi, penggunaan, cara membaca card, rumus, dan contoh perhitungan.",
  },
};
type CrudPageSize = 10 | 50 | 100 | "ALL";
type CrudSortDirection = "asc" | "desc";
type CrudModalMode = "add" | "edit" | null;
type CrudBatchFormRow = {
  recordId?: string;
  values: Record<string, unknown>;
};
type TagConsistencyDetail = {
  tag_type: string;
  tag_type_name: string;
  matching_rule: string;
  spbu_required_tags: string[];
  mt_available_tags: string[];
  missing_tags: string[];
  extra_mt_tags: string[];
  result: string;
  reason: string;
  rule_expression?: string | null;
};
type TagConsistencyRow = {
  analysis_id: string;
  loading_order_number: string;
  loading_order_date: string | null;
  vehicle_registration: string | null;
  mt_id: string | null;
  mt_name: string | null;
  mt_vehicle_class: number | null;
  spbu_id: string | null;
  spbu_name: string | null;
  spbu_code: string | null;
  spbu_vehicle_class: number | null;
  depot: string | null;
  product_name: string | null;
  overall_status: string;
  overall_group: "MATCH" | "MISMATCH" | "DATA_ISSUE";
  mismatch_count: number;
  data_issue_count: number;
  vehicle_class_result: string;
  tag_match_result: string;
  primary_reason: string;
  details: TagConsistencyDetail[];
};
type RankedMismatch = {
  spbu?: string;
  vehicle_registration?: string;
  total_assignment: number;
  mismatch: number;
  mismatch_rate: number;
};
type TagConsistencySummary = {
  total_lo_assignments: number;
  matched: number;
  mismatch: number;
  data_issues: number;
  analyzable_lo: number;
  consistency_rate: number;
  mismatch_by_tag_type: SeriesPoint[];
  mismatch_by_tag_value: SeriesPoint[];
  daily_consistency_rate: SeriesPoint[];
  top_spbu_mismatch: RankedMismatch[];
  top_mt_mismatch: RankedMismatch[];
  data_quality_summary: SeriesPoint[];
};
type TagConsistencyResponse = {
  latest_loading_order_date: string | null;
  defaulted_to_latest_date: boolean;
  effective_filters: Record<string, string | number | null>;
  summary: TagConsistencySummary;
  total: number;
  limit: number;
  offset: number;
  rows: TagConsistencyRow[];
};
type TagConsistencyFilters = {
  startDate: string;
  endDate: string;
  depotId: string;
  spbu: string;
  vehicle: string;
  tagType: string;
  status: string;
  productId: string;
  vehicleClass: string;
  search: string;
};
type MismatchSortColumn = "label" | "total_assignment" | "mismatch" | "mismatch_rate";
type DepartureSortColumn =
  | "spbu_code"
  | "preferred_historical_departure_window"
  | "peak_departure_time"
  | "p50"
  | "p80"
  | "p90"
  | "p95"
  | "observation_count"
  | "dispersion_minutes_iqr"
  | "confidence_score";
type DepartureFilters = {
  depotId: string;
  startDate: string;
  endDate: string;
  bucketMinutes: string;
  search: string;
};
type DepartureDateAvailability = {
  depot_id: string;
  depot_name: string;
  available_dates: string[];
  dates: Array<{ date: string; shipment_count: number }>;
  min_date: string | null;
  max_date: string | null;
};
type DepartureSummary = {
  observation_count: number;
  profile_count: number;
  shipment_count: number;
  spbu_count: number;
  vehicle_count: number;
  quantity_dispatched: number;
  gps_timestamp_coverage_pct: number;
  lo_gate_out_coverage_pct: number;
  gps_observation_count: number;
  lo_gate_out_observation_count: number;
  missing_timestamp_count: number;
  invalid_timestamp_count: number;
  avg_gps_vs_lo_difference_minutes: number | null;
  high_confidence_profiles: number;
  medium_confidence_profiles: number;
  low_confidence_profiles: number;
};
type DepartureProfile = {
  spbu_id: string;
  spbu_code: string;
  spbu_name: string | null;
  spbu_tags: string[];
  depot_name: string;
  observation_count: number;
  shipment_count: number;
  vehicle_count: number;
  quantity_dispatched: number;
  p20: string;
  p25: string;
  p50: string;
  p75: string;
  p80: string;
  p90: string;
  p95: string;
  peak_departure_time: string;
  peak_departure_bucket: string;
  preferred_historical_departure_window: string;
  dispersion_minutes_iqr: number;
  outlier_count: number;
  confidence_score: number;
  confidence_level: "HIGH" | "MEDIUM" | "LOW";
  departure_time_source_counts: Record<string, number>;
  algorithm_version: string;
};
type DepartureObservation = {
  observation_id: string;
  shipment_id: string;
  source_shipment_id: string;
  spbu_id: string;
  spbu_code: string;
  operation_date: string | null;
  vehicle_registration: string | null;
  loading_order_gate_out_datetime: string | null;
  gps_actual_depot_exit_datetime: string | null;
  departure_datetime_used: string | null;
  departure_time_source: string | null;
  gps_vs_lo_difference_minutes: number | null;
  quantity: number;
  products: string[];
};
type DepartureAnalysis = {
  algorithm_version: string;
  effective_filters: Record<string, string | number | null>;
  summary: DepartureSummary;
  distribution: SeriesPoint[];
  weekday_heatmap: { x_axis: string[]; y_axis: string[]; data: number[][] };
  box_plot: { categories: string[]; data: number[][] };
  profiles: DepartureProfile[];
  observations: DepartureObservation[];
  total: number;
  limit: number;
  offset: number;
  notes: string[];
};
type ShiftAssignmentMethod = "DOMINANT_SHIFT" | "MEDIAN_BASED" | "HYBRID_CONFIDENCE_AWARE";
type OperationalShiftConfig = {
  shift_id: string;
  name: string;
  start_time: string;
  end_time: string;
};
type ShiftDistribution = {
  shift_id: string;
  shift_name: string;
  shift_order: number;
  start_time: string;
  end_time: string;
  observation_count: number;
  share_pct: number;
  score: number | null;
};
type ShiftAssignmentRow = {
  depot_id: string;
  spbu_id: string;
  spbu_code: string;
  spbu_name: string | null;
  primary_shift_id: string | null;
  primary_shift_name: string | null;
  primary_shift_share: number;
  primary_shift_score: number | null;
  secondary_shift_id: string | null;
  secondary_shift_name: string | null;
  secondary_shift_share: number;
  secondary_shift_score: number | null;
  primary_secondary_gap: number;
  assignment_score: number;
  assignment_status: "CLEAR" | "MODERATE" | "AMBIGUOUS" | "INSUFFICIENT_DATA";
  observation_count: number;
  median_departure: string;
  median_departure_minutes: number;
  peak_departure_time: string;
  preferred_historical_departure_window: string;
  confidence_score: number;
  confidence_level: "HIGH" | "MEDIUM" | "LOW";
  shift_distribution: ShiftDistribution[];
};
type ShiftAnalysis = {
  assignment_method: ShiftAssignmentMethod;
  assignment_method_label: string;
  algorithm_version: string;
  shift_config_id: string;
  shift_config: Array<OperationalShiftConfig & { order: number; start_minute: number; end_minute: number; segments: Array<{ start_minute: number; end_exclusive_minute: number }> }>;
  summary: {
    profile_count: number;
    observation_count: number;
    assigned_by_shift: Array<{ shift_id: string; shift_name: string; spbu_count: number }>;
    status_counts: Record<"CLEAR" | "MODERATE" | "AMBIGUOUS" | "INSUFFICIENT_DATA", number>;
  };
  rows: ShiftAssignmentRow[];
  heatmap: { x_axis: string[]; y_axis: string[]; data: number[][] };
  notes: string[];
};
type SavedShiftAnalysisConfig = {
  id: string;
  name: string;
  depot_id: string;
  depot_name: string | null;
  start_date: string;
  end_date: string;
  bucket_minutes: number;
  search: string;
  sort_column: string;
  sort_direction: string;
  assignment_method: ShiftAssignmentMethod;
  assignment_method_label: string;
  shift_count: number;
  profile_count: number;
  observation_count: number;
  assigned_profile_count: number;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  shift_config?: OperationalShiftConfig[];
  ui_state?: Record<string, string | number | null>;
  departure_analysis_snapshot?: DepartureAnalysis;
  shift_analysis_snapshot?: ShiftAnalysis;
};
type SavedShiftAnalysisConfigResponse = {
  total: number;
  limit: number;
  offset: number;
  rows: SavedShiftAnalysisConfig[];
};
type SavedPairingAnalysisConfig = {
  id: string;
  name: string;
  depot_id: string;
  depot_name: string | null;
  start_date: string;
  end_date: string;
  product_id: string | null;
  product_name: string;
  search: string;
  sort_column: PairingSortColumn;
  sort_direction: CrudSortDirection;
  unique_spbu_pairs: number;
  multi_spbu_shipments: number;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  ui_state?: Record<string, string | number | null>;
  pairing_analysis_snapshot?: PairingAnalysis;
};
type SavedPairingAnalysisConfigResponse = {
  total: number;
  limit: number;
  offset: number;
  rows: SavedPairingAnalysisConfig[];
};
type DepartureConfidenceFilter = "ALL" | "HIGH" | "MEDIUM" | "LOW";
type ShiftSummaryFilter = "ALL" | `SHIFT:${string}` | `STATUS:${"AMBIGUOUS" | "INSUFFICIENT_DATA"}`;
type PairingFilters = {
  depotId: string;
  rangePreset: "7" | "14" | "30" | "CUSTOM";
  startDate: string;
  endDate: string;
  productId: string;
  search: string;
};
type PairingSortColumn =
  | "evidence_strength"
  | "pair_count"
  | "probability_b_given_a"
  | "probability_a_given_b"
  | "support"
  | "lift"
  | "confidence_score"
  | "spbu_a_code"
  | "spbu_b_code";
type PairingPair = {
  spbu_a_id: string;
  spbu_b_id: string;
  spbu_a_code: string;
  spbu_a_name: string | null;
  spbu_a_tags: string[];
  spbu_b_code: string;
  spbu_b_name: string | null;
  spbu_b_tags: string[];
  pair_count: number;
  shipment_a_count: number;
  shipment_b_count: number;
  total_shipment_count: number;
  probability_b_given_a: number;
  probability_a_given_b: number;
  support: number;
  lift: number;
  confidence_score: number;
  confidence_level: "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT_DATA";
  observation_count: number;
  evidence_count: number;
};
type PairingAnalysis = {
  algorithm_version: string;
  effective_filters: Record<string, string | number | null>;
  summary: {
    total_shipments: number;
    source_shipments: number;
    multi_spbu_shipments: number;
    unique_spbu: number;
    unique_spbu_pairs: number;
    high_confidence_pairs: number;
    average_spbu_per_shipment: number;
  };
  data_quality: {
    source_shipments: number;
    eligible_shipments: number;
    excluded_shipments: number;
    exclusion_reasons: Array<{ reason: string; count: number }>;
  };
  distribution: SeriesPoint[];
  pairs: PairingPair[];
  total: number;
  limit: number;
  offset: number;
  matrix: { spbu_ids: string[]; x_axis: string[]; y_axis: string[]; data: Array<[number, number, number, number, number, number, number, number, string, string[], string[]]>; selected_spbu_id: string | null };
  network: { nodes: Array<{ id: string; name: string; tags: string[]; value: number; symbolSize: number }>; edges: Array<{ source: string; target: string; value: number; label: string; metrics: PairingPair }> };
  detail: {
    spbu_id: string;
    spbu_code: string;
    spbu_name: string | null;
    spbu_tags: string[];
    depot_name: string;
    historical_shipments: number;
    top_pairs: Array<PairingPair & { candidate_spbu_id: string; candidate_spbu_code: string; candidate_spbu_tags: string[]; pair_probability: number; reverse_probability: number }>;
  } | null;
  evidence: {
    pair: { spbu_a_id: string; spbu_a_code: string; spbu_a_tags: string[]; spbu_b_id: string; spbu_b_code: string; spbu_b_tags: string[] } | null;
    distinct_shipment_count: number;
    rows: Array<{
      shipment_id: string;
      source_shipment_id: string;
      date: string | null;
      vehicle_registration: string | null;
      gate_out: string | null;
      spbu_in_shipment: string[];
      spbu_tags: Array<{ spbu_id: string; spbu_code: string; tags: string[] }>;
      products: string[];
      quantity: number;
    }>;
  };
  transitions: Array<{ from_spbu_code: string; to_spbu_code: string; transition_count: number; transition_probability: number; confidence_level: string }>;
  traceability: Record<string, string | number>;
  notes: string[];
};
type DepartureProfileFilterOptions = {
  confidenceLevel?: DepartureConfidenceFilter;
  shiftSummaryFilter?: ShiftSummaryFilter;
  profileSearch?: string;
};

const kpiLabels: Record<string, string> = {
  total_mt: "Total MT",
  active_mt: "Active MT",
  total_spbu: "Total SPBU",
  active_spbu: "Active SPBU",
  total_depot: "Depots",
  total_product: "Products",
  total_canonical_tags: "Canonical Tags",
  total_tag_types: "Tag Types",
  total_loading_order_lines: "LO Lines",
  total_shipments: "Shipments",
  unique_mt_observed_in_lo: "Unique MT in LO",
  unique_spbu_observed_in_lo: "Unique SPBU in LO",
  unmatched_mt: "Unmatched MT",
  unmatched_spbu: "Unmatched SPBU",
  gps_events: "GPS Events",
  gps_confirmed_spbu_visits: "GPS Visits",
  data_quality_issues: "Quality Issues"
};

const crudDomainOrder = ["DEPOT", "MOBIL_TANGKI", "SPBU", "LOADING_ORDER", "PRODUCT", "TAG", "TAG_TYPE"];

function tagTypeColumnKey(code: string): string {
  return `tag_${code.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "")}`;
}

function crudConfigs(depots: Depot[], tagTypes: TagType[]): Record<string, CrudDomainConfig> {
  const requiredDepotOptions = depots.map((depot) => ({ label: depot.depot_name, value: depot.depot_id }));
  const mtTagColumns = [...new Set(["tag_vehicle_class", ...tagTypes.map((tagType) => tagTypeColumnKey(tagType.code))])];
  const spbuTagColumns = mtTagColumns;
  const editableTagFields = tagTypes
    .filter((tagType) => tagType.code !== "VEHICLE_CLASS")
    .map((tagType) => ({
      key: tagTypeColumnKey(tagType.code),
      label: `Tag ${tagType.name || tagType.code}`,
      kind: "textarea" as const
    }));
  const tagTypeOptions = [
    { label: "Auto by tag value", value: "" },
    ...tagTypes.map((tagType) => ({ label: `${tagType.code} - ${tagType.name}`, value: tagType.tag_type_id }))
  ];
  const statusOptions = [
    { label: "ACTIVE", value: "ACTIVE" },
    { label: "INACTIVE", value: "INACTIVE" }
  ];
  return {
    MOBIL_TANGKI: {
      label: "Mobil Tangki", idKey: "mt_id", titleKey: "vehicle_registration", depotFilter: true,
      columns: ["vehicle_registration", "number_of_compartments", ...mtTagColumns, "active_status"],
      fields: [
        { key: "vehicle_registration", label: "Vehicle Registration", required: true, readonlyOnEdit: true },
        { key: "vehicle_type_tag", label: "Tag Vehicle Class / Kapasitas (KL)", kind: "number" },
        ...editableTagFields,
        { key: "number_of_compartments", label: "Compartments", kind: "number" },
        { key: "assignee", label: "Assignee" },
        { key: "active_status", label: "Status", kind: "select", options: statusOptions }
      ]
    },
    SPBU: {
      label: "SPBU", idKey: "spbu_id", titleKey: "spbu_code", depotFilter: true,
      columns: ["spbu_code", "address", "latitude", "longitude", "master_distance_km", "master_rth_min", "master_travel_time_min", "master_travel_time_sample_count", "official_window_start", "official_window_end", ...spbuTagColumns, "active_status"],
      fields: [
        { key: "spbu_code", label: "SPBU Code", required: true, readonlyOnEdit: true },
        { key: "address", label: "Address", kind: "textarea" },
        { key: "latitude", label: "Latitude", kind: "number" },
        { key: "longitude", label: "Longitude", kind: "number" },
        { key: "master_distance_km", label: "Distance KM", kind: "number" },
        { key: "vehicle_type_tag", label: "Tag Vehicle Class", kind: "number" },
        ...editableTagFields,
        { key: "official_window_start", label: "Official Window Start", kind: "time", required: true, defaultValue: "00:00" },
        { key: "official_window_end", label: "Official Window End", kind: "time", required: true, defaultValue: "23:59" },
        { key: "active_status", label: "Status", kind: "select", options: statusOptions }
      ]
    },
    LOADING_ORDER: {
      label: "Historikal Shipment", idKey: "crud_record_id", titleKey: "loading_order_number", depotFilter: true, statusFilter: false,
      columns: ["loading_order_number", "shipment_id", "vehicle_registration", "driver_name", "driver_nip", "assistant_name", "assistant_nip", "validation_datetime", "gate_out_datetime", "shipment_end_datetime", "source_spbu_code", "source_product_name", "quantity", "actual_km"],
      fields: [
        { key: "loading_order_number", label: "Loading Order Number", required: true, readonlyOnEdit: true },
        { key: "shipment_id", label: "Shipment ID", required: true, readonlyOnEdit: true },
        { key: "vehicle_registration", label: "Vehicle Registration" },
        { key: "vehicle_type_tag", label: "Vehicle Class Teramati (KL)", kind: "number" },
        { key: "project_tag", label: "Project Tag Teramati" },
        { key: "validation_datetime", label: "Validation (YYYY-MM-DD HH:MM:SS)", required: true },
        { key: "gate_out_datetime", label: "Gate Out (YYYY-MM-DD HH:MM:SS)" },
        { key: "shipment_end_datetime", label: "Shipment End (YYYY-MM-DD HH:MM:SS)" },
        { key: "source_spbu_code", label: "SPBU Code" },
        { key: "source_product_name", label: "Product Name" },
        { key: "quantity", label: "Quantity", kind: "number" },
        { key: "actual_km", label: "Actual KM", kind: "number" },
        { key: "driver_name", label: "Driver Name" },
        { key: "driver_nip", label: "Driver NIP" },
        { key: "assistant_name", label: "Assistant Name" },
        { key: "assistant_nip", label: "Assistant NIP" }
      ]
    },
    DEPOT: {
      label: "Depot",
      idKey: "depot_id",
      titleKey: "depot_name",
      columns: ["depot_id", "depot_code", "depot_name", "latitude", "longitude", "region", "timezone", "depot_operational_start", "depot_operational_end", "active_status"],
      fields: [
        { key: "depot_code", label: "Depot Code" },
        { key: "depot_name", label: "Depot Name", required: true },
        { key: "latitude", label: "Latitude", kind: "number" },
        { key: "longitude", label: "Longitude", kind: "number" },
        { key: "region", label: "Region" },
        { key: "timezone", label: "Timezone" },
        { key: "depot_operational_start", label: "Operational Start", kind: "time", required: true, defaultValue: "00:00" },
        { key: "depot_operational_end", label: "Operational End", kind: "time", required: true, defaultValue: "23:59" },
        { key: "active_status", label: "Status", kind: "select", options: statusOptions }
      ]
    },
    PRODUCT: {
      label: "Product",
      idKey: "product_id",
      titleKey: "product_name",
      columns: ["product_name", "normalized_product", "active_status"],
      fields: [
        { key: "product_name", label: "Product Name", required: true },
        { key: "active_status", label: "Status", kind: "select", options: statusOptions }
      ]
    },
    TAG: {
      label: "Tag",
      idKey: "tag_id",
      titleKey: "tag_value",
      columns: ["tag_value", "normalized_tag", "tag_type_code", "active_status"],
      fields: [
        { key: "tag_value", label: "Tag Value", required: true },
        { key: "tag_type_id", label: "Tag Type", kind: "select", options: tagTypeOptions },
        { key: "active_status", label: "Status", kind: "select", options: statusOptions }
      ]
    },
    TAG_TYPE: {
      label: "Tag Type",
      idKey: "tag_type_id",
      titleKey: "code",
      columns: ["code", "name", "description", "admin_editable"],
      fields: [
        { key: "code", label: "Code", required: true },
        { key: "name", label: "Name", required: true },
        { key: "description", label: "Description", kind: "textarea" },
        { key: "admin_editable", label: "Admin Editable", kind: "checkbox" }
      ]
    }
  };
}

function crudColumnLabel(column: string): string {
  const labels: Record<string, string> = {
    validation_date: "Tanggal Validasi",
    validation_time: "Jam Validasi",
    driver_name: "Nama Driver",
    driver_nip: "NIP Driver",
    assistant_name: "Nama Kernet",
    assistant_nip: "NIP Kernet",
    shipment_end_date: "Tanggal Endshipment",
    shipment_end_time: "Waktu Endshipment",
    vehicle_registration: "Vehicle Registration"
  };
  const historicalLabels: Record<string, string> = { master_rth_min: "Median RTH (min)", master_travel_time_min: "Estimasi Satu Arah (min)", master_travel_time_sample_count: "Sampel RTH", validation_datetime: "Validation", gate_out_datetime: "Gate Out", shipment_end_datetime: "Shipment End", tag_vehicle_class: "Vehicle Class / Kapasitas (KL)" };
  return historicalLabels[column] ?? labels[column] ?? column.replace(/_/g, " ");
}

function formatCrudValue(value: unknown, column?: string): string {
  if (value === null || value === undefined || value === "") return "-";
  if (column === "validation_date") return formatCrudDate(String(value));
  if (column === "validation_time") return formatCrudTime(String(value));
  if (column === "shipment_end_date") return formatCrudDate(String(value));
  if (column === "shipment_end_time") return formatCrudTime(String(value));
  if (column?.endsWith("_datetime")) return formatImportDateTime(String(value));
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

function formatCrudDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(date);
}

function formatCrudTime(value: string): string {
  const normalized = value.includes("T") ? value : `1970-01-01T${value}`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(date);
}

function formatImportDateTime(value: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(date);
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

function formatDateTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
}

function formatMetric(value: number | null | undefined, maximumFractionDigits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits });
}

function formatTags(tags: string[] | null | undefined): string {
  if (!tags || tags.length === 0) return "-";
  return tags.join(", ");
}

function minuteAxisLabel(value: number): string {
  const rounded = Math.round(value) % 1440;
  return `${String(Math.floor(rounded / 60)).padStart(2, "0")}:${String(rounded % 60).padStart(2, "0")}`;
}

function shiftedMinuteAxisLabel(value: number): string {
  const dayShift = Math.floor(Math.max(0, Math.round(value)) / 1440);
  const label = minuteAxisLabel(value);
  return dayShift > 0 ? `${label} +${dayShift}d` : label;
}

function parseIsoDate(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function isoDateFromParts(year: number, monthIndex: number, day: number): string {
  return `${year}-${String(monthIndex + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function isoDateFromDate(value: Date): string {
  return isoDateFromParts(value.getFullYear(), value.getMonth(), value.getDate());
}

function addDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

function monthLabel(value: Date): string {
  return new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric" }).format(value);
}

function pageFromPath(pathname: string): Page {
  if (pathname === "/master-data/restricted-roads") return "restricted-roads";
  if (pathname === "/master-data") return "master-data";
  if (pathname === "/tag-consistency") return "tag-consistency";
  if (pathname === "/departure-intelligence") return "departure-intelligence";
  if (pathname === "/pairing-intelligence") return "pairing-intelligence";
  if (pathname === "/affinity-intelligence") return "affinity-intelligence";
  if (pathname === "/machine-learning-intelligence") return "machine-learning-intelligence";
  if (pathname === "/prediction-assignment") return "prediction-assignment";
  if (pathname === "/phase7-optimization") return "phase7-optimization";
  if (pathname === "/phase-8/manual-dispatch" || pathname.startsWith("/phase-8/manual-dispatch/")) return "manual-dispatch";
  if (pathname === "/phase9/route-model-alignment") return "route-model-alignment";
  if (pathname === "/phase10/amt-scheduler-connector") return "amt-scheduler-connector";
  if (pathname === "/settings/google-maps-integration") return "google-maps-integration";
  if (pathname === "/documentation") return "documentation";
  return "dashboard";
}

function confidenceClass(level: string): string {
  if (level === "HIGH") return "border-mint bg-mint/10 text-mint";
  if (level === "MEDIUM") return "border-amber bg-amber/10 text-amber";
  return "border-rust bg-rust/10 text-rust";
}

function statusClass(status: string): string {
  if (status === "MATCH") return "border-mint bg-mint/10 text-mint";
  if (status === "MISMATCH") return "border-rust bg-rust/10 text-rust";
  return "border-amber bg-amber/10 text-amber";
}

function statusLabel(status: string): string {
  if (["MT_NOT_FOUND", "SPBU_NOT_FOUND", "MT_TAG_INCOMPLETE", "SPBU_TAG_INCOMPLETE", "DATA_ERROR"].includes(status)) return "DATA ISSUE";
  return status.replace(/_/g, " ");
}

const defaultShiftConfig: OperationalShiftConfig[] = [
  { shift_id: "shift_1", name: "Shift 1", start_time: "00:00", end_time: "05:59" },
  { shift_id: "shift_2", name: "Shift 2", start_time: "06:00", end_time: "11:59" },
  { shift_id: "shift_3", name: "Shift 3", start_time: "12:00", end_time: "17:59" },
  { shift_id: "shift_4", name: "Shift 4", start_time: "18:00", end_time: "23:59" }
];

const shiftMethodLabels: Record<ShiftAssignmentMethod, string> = {
  DOMINANT_SHIFT: "Dominant Shift",
  MEDIAN_BASED: "Median-Based",
  HYBRID_CONFIDENCE_AWARE: "Hybrid / Confidence-Aware"
};

function shiftStatusClass(status: string): string {
  if (status === "CLEAR") return "border-mint bg-mint/10 text-mint";
  if (status === "MODERATE") return "border-amber bg-amber/10 text-amber";
  if (status === "AMBIGUOUS") return "border-slate-400 bg-slate-100 text-slate-600";
  return "border-rust bg-rust/10 text-rust";
}

function parseTimeToMinute(value: string): number | null {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

function validateOperationalShifts(shifts: OperationalShiftConfig[]): string[] {
  const errors: string[] = [];
  if (shifts.length === 0) errors.push("At least one shift is required.");
  const names = new Set<string>();
  const covered = Array<number | null>(1440).fill(null);
  shifts.forEach((shift, index) => {
    const name = shift.name.trim();
    if (!name) errors.push(`Shift ${index + 1} needs a name.`);
    const normalizedName = name.toLowerCase();
    if (normalizedName && names.has(normalizedName)) errors.push(`Duplicate shift name: ${name}.`);
    names.add(normalizedName);
    const start = parseTimeToMinute(shift.start_time);
    const end = parseTimeToMinute(shift.end_time);
    if (start === null || end === null) {
      errors.push(`${name || `Shift ${index + 1}`} needs valid HH:MM start and end times.`);
      return;
    }
    const segments = start <= end ? [[start, end + 1]] : [[start, 1440], [0, end + 1]];
    segments.forEach(([segmentStart, segmentEnd]) => {
      for (let minute = segmentStart; minute < segmentEnd; minute += 1) {
        if (covered[minute] !== null) {
          errors.push(`Shift ranges overlap around ${minuteAxisLabel(minute)}.`);
          return;
        }
        covered[minute] = index;
      }
    });
  });
  const gap = covered.findIndex((owner) => owner === null);
  if (gap >= 0) errors.push(`Shift ranges must cover the full 24-hour day. Gap starts at ${minuteAxisLabel(gap)}.`);
  return Array.from(new Set(errors));
}

function shiftPalette(index: number): string {
  return ["#2f7d6d", "#b87516", "#475569", "#7c3aed", "#0f766e", "#be123c", "#2563eb", "#a16207"][index % 8];
}

const assignmentStatusBoxPlotColors: Record<string, string> = {
  CLEAR: "#2f7d6d",
  MODERATE: "#b87516",
  AMBIGUOUS: "#64748b",
  INSUFFICIENT_DATA: "#b64a35"
};

const confidenceBoxPlotColors: Record<string, string> = {
  HIGH: "#2f7d6d",
  MEDIUM: "#b87516",
  LOW: "#b64a35"
};

function renderTags(values: string[], variant: "default" | "missing" = "default") {
  if (!values.length) return <span className="text-slate-400">-</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {values.map((value) => (
        <span key={value} className={`border px-2 py-1 text-xs ${variant === "missing" ? "border-rust bg-rust/10 text-rust" : "border-line bg-slate-50 text-slate-700"}`}>
          {value}
        </span>
      ))}
    </div>
  );
}

const emptyTagConsistencySummary: TagConsistencySummary = {
  total_lo_assignments: 0,
  matched: 0,
  mismatch: 0,
  data_issues: 0,
  analyzable_lo: 0,
  consistency_rate: 0,
  mismatch_by_tag_type: [],
  mismatch_by_tag_value: [],
  daily_consistency_rate: [],
  top_spbu_mismatch: [],
  top_mt_mismatch: [],
  data_quality_summary: []
};

function sortedMismatchRows(
  rows: RankedMismatch[],
  labelKey: "spbu" | "vehicle_registration",
  sortColumn: MismatchSortColumn,
  sortDirection: CrudSortDirection
): RankedMismatch[] {
  return [...rows].sort((left, right) => {
    const leftValue = sortColumn === "label" ? left[labelKey] ?? "" : left[sortColumn];
    const rightValue = sortColumn === "label" ? right[labelKey] ?? "" : right[sortColumn];
    const comparison =
      typeof leftValue === "number" && typeof rightValue === "number"
        ? leftValue - rightValue
        : String(leftValue).localeCompare(String(rightValue));
    return sortDirection === "asc" ? comparison : -comparison;
  });
}

function DepartureDatePicker({
  label,
  value,
  availableDates,
  dateCounts,
  minDate,
  maxDate,
  disabled,
  onChange
}: {
  label: string;
  value: string;
  availableDates: Set<string>;
  dateCounts: Map<string, number>;
  minDate: string | null;
  maxDate: string | null;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [visibleMonth, setVisibleMonth] = useState(() => (value ? parseIsoDate(value) : minDate ? parseIsoDate(minDate) : new Date()));
  const calendarRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (value) {
      setVisibleMonth(parseIsoDate(value));
    } else if (minDate) {
      setVisibleMonth(parseIsoDate(minDate));
    }
  }, [minDate, value]);

  useEffect(() => {
    if (!open) return;
    const handleClick = (event: MouseEvent) => {
      if (calendarRef.current && !calendarRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const monthStart = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
  const firstGridDate = new Date(monthStart);
  firstGridDate.setDate(firstGridDate.getDate() - firstGridDate.getDay());
  const days = Array.from({ length: 42 }, (_, index) => {
    const day = new Date(firstGridDate);
    day.setDate(firstGridDate.getDate() + index);
    return day;
  });
  const min = minDate ? parseIsoDate(minDate) : null;
  const max = maxDate ? parseIsoDate(maxDate) : null;

  function moveMonth(delta: number) {
    setVisibleMonth((current) => new Date(current.getFullYear(), current.getMonth() + delta, 1));
  }

  return (
    <div className="relative" ref={calendarRef}>
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 border border-line bg-white px-3 py-2 text-left text-sm disabled:bg-slate-100 disabled:text-slate-400"
        onClick={() => !disabled && setOpen((current) => !current)}
        disabled={disabled}
        title={label}
      >
        <span className={value ? "text-slate-900" : "text-slate-400"}>{value || label}</span>
        <CalendarDays size={16} className="text-slate-500" />
      </button>
      {open && (
        <div className="absolute left-0 top-[calc(100%+6px)] z-40 w-80 border border-line bg-white p-3 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <button type="button" className="inline-flex h-8 w-8 items-center justify-center border border-line" onClick={() => moveMonth(-1)} title="Previous month">
              <ChevronLeft size={16} />
            </button>
            <div className="text-sm font-semibold">{monthLabel(visibleMonth)}</div>
            <button type="button" className="inline-flex h-8 w-8 items-center justify-center border border-line" onClick={() => moveMonth(1)} title="Next month">
              <ChevronRight size={16} />
            </button>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center text-xs font-semibold uppercase tracking-wide text-slate-500">
            {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((day) => <div key={day}>{day}</div>)}
          </div>
          <div className="mt-1 grid grid-cols-7 gap-1">
            {days.map((day) => {
              const isoDate = isoDateFromDate(day);
              const inMonth = day.getMonth() === visibleMonth.getMonth();
              const hasData = availableDates.has(isoDate);
              const selected = value === isoDate;
              const outsideRange = Boolean((min && day < min) || (max && day > max));
              const count = dateCounts.get(isoDate) ?? 0;
              return (
                <button
                  key={isoDate}
                  type="button"
                  className={[
                    "h-9 border text-sm",
                    selected ? "border-mint bg-mint text-white" : hasData ? "border-mint bg-mint/10 text-mint" : "border-line bg-slate-50 text-slate-400",
                    !inMonth ? "opacity-40" : "",
                    outsideRange ? "cursor-not-allowed opacity-30" : "hover:border-mint"
                  ].join(" ")}
                  disabled={outsideRange}
                  onClick={() => {
                    onChange(isoDate);
                    setOpen(false);
                  }}
                  title={hasData ? `${isoDate}: ${count.toLocaleString()} shipments` : `${isoDate}: no departure data`}
                >
                  {day.getDate()}
                </button>
              );
            })}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1"><span className="h-3 w-3 border border-mint bg-mint/10" /> Ada data</span>
            <span className="inline-flex items-center gap-1"><span className="h-3 w-3 border border-line bg-slate-50" /> Tidak ada data</span>
          </div>
        </div>
      )}
    </div>
  );
}

function emptyCrudValues(config: CrudDomainConfig): Record<string, unknown> {
  return Object.fromEntries(config.fields.map((field) => [field.key, field.defaultValue ?? (field.kind === "checkbox" ? false : "")]));
}

function crudValuesFromRow(row: Record<string, unknown>, config: CrudDomainConfig): Record<string, unknown> {
  return Object.fromEntries(config.fields.map((field) => [field.key, row[field.key] ?? (field.kind === "checkbox" ? false : "")]));
}

function initialTagConsistencyFilters(): TagConsistencyFilters {
  const params = new URLSearchParams(window.location.search);
  return {
    startDate: params.get("start_date") ?? "",
    endDate: params.get("end_date") ?? "",
    depotId: params.get("depot_id") ?? "ALL",
    spbu: params.get("spbu") ?? "",
    vehicle: params.get("vehicle") ?? "",
    tagType: params.get("tag_type") ?? "ALL",
    status: params.get("overall_status") ?? "ALL",
    productId: params.get("product_id") ?? "",
    vehicleClass: params.get("vehicle_class") ?? "",
    search: params.get("search") ?? ""
  };
}

function App() {
  const [activeDepotId, setActiveDepotId] = useState(() => window.localStorage.getItem("dispatch-active-depot") || "");
  function chooseDepot(depotId: string) {
    window.localStorage.setItem("dispatch-active-depot", depotId);
    let path = window.location.pathname;
    if (path.startsWith("/phase-8/manual-dispatch/")) path = "/phase-8/manual-dispatch";
    window.history.replaceState({}, "", path);
    setActiveDepotId(depotId);
  }
  return <DepotWorkspace key={activeDepotId} activeDepotId={activeDepotId} onDepotChange={chooseDepot} />;
}

function DepotWorkspace({ activeDepotId, onDepotChange }: { activeDepotId: string; onDepotChange: (id: string) => void }) {
  const [currentPage, setCurrentPage] = useState<Page>(() => pageFromPath(window.location.pathname));
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.localStorage.getItem("dispatch-sidebar-collapsed") === "true");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [overview, setOverview] = useState<Overview>({});
  const [charts, setCharts] = useState<Charts>({});
  const [imports, setImports] = useState<ImportAudit[]>([]);
  const [issues, setIssues] = useState<QualityIssue[]>([]);
  const [allDepots, setDepots] = useState<Depot[]>([]);
  const depots = useMemo(() => allDepots.filter((depot) => depot.depot_id === activeDepotId), [allDepots, activeDepotId]);
  const [products, setProducts] = useState<Product[]>([]);
  const [tagTypes, setTagTypes] = useState<TagType[]>([]);
  const [compatibility, setCompatibility] = useState<CompatibilitySummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [activeImportId, setActiveImportId] = useState<string | null>(() => window.localStorage.getItem("dispatch-active-import-id"));
  const [activeImportStatus, setActiveImportStatus] = useState<string | null>(() => (
    window.localStorage.getItem("dispatch-active-import-id") ? "QUEUED" : null
  ));
  const [exporting, setExporting] = useState(false);
  const [domain, setDomain] = useState("MOBIL_TANGKI");
  const [sheetName, setSheetName] = useState("Mobil Tangki");
  const [exportDomain, setExportDomain] = useState("ALL");
  const [exportDepotId, setExportDepotId] = useState(activeDepotId);
  const [exportFormat, setExportFormat] = useState("xlsx");
  const [dashboardDepotId, setDashboardDepotId] = useState(activeDepotId);
  const [crudDomain, setCrudDomain] = useState("MOBIL_TANGKI");
  const [crudRows, setCrudRows] = useState<Array<Record<string, unknown>>>([]);
  const [crudTotal, setCrudTotal] = useState(0);
  const [crudOffset, setCrudOffset] = useState(0);
  const [crudLimit, setCrudLimit] = useState<CrudPageSize>(10);
  const [crudSearch, setCrudSearch] = useState("");
  const [crudAppliedSearch, setCrudAppliedSearch] = useState("");
  const [crudSearchColumn, setCrudSearchColumn] = useState("vehicle_registration");
  const [crudAppliedSearchColumn, setCrudAppliedSearchColumn] = useState("vehicle_registration");
  const [crudSortColumn, setCrudSortColumn] = useState("vehicle_registration");
  const [crudSortDirection, setCrudSortDirection] = useState<CrudSortDirection>("asc");
  const [crudDepotId, setCrudDepotId] = useState(activeDepotId);
  const [crudModalMode, setCrudModalMode] = useState<CrudModalMode>(null);
  const [crudBatchForms, setCrudBatchForms] = useState<CrudBatchFormRow[]>([]);
  const [selectedCrudIds, setSelectedCrudIds] = useState<Set<string>>(() => new Set());
  const [crudLoading, setCrudLoading] = useState(false);
  const [crudSyncing, setCrudSyncing] = useState(false);
  const [tagFilters, setTagFilters] = useState<TagConsistencyFilters>(() => ({ ...initialTagConsistencyFilters(), depotId: activeDepotId }));
  const [tagAnalysis, setTagAnalysis] = useState<TagConsistencyResponse | null>(null);
  const [tagLoading, setTagLoading] = useState(false);
  const [tagExporting, setTagExporting] = useState(false);
  const [tagExportParams, setTagExportParams] = useState<string | null>(null);
  const [tagOffset, setTagOffset] = useState(0);
  const [tagLimit, setTagLimit] = useState(25);
  const [tagSortColumn, setTagSortColumn] = useState("loading_order_date");
  const [tagSortDirection, setTagSortDirection] = useState<CrudSortDirection>("desc");
  const [mismatchRowsPerPage, setMismatchRowsPerPage] = useState(10);
  const [spbuMismatchPage, setSpbuMismatchPage] = useState(0);
  const [mtMismatchPage, setMtMismatchPage] = useState(0);
  const [spbuMismatchSortColumn, setSpbuMismatchSortColumn] = useState<MismatchSortColumn>("mismatch");
  const [spbuMismatchSortDirection, setSpbuMismatchSortDirection] = useState<CrudSortDirection>("desc");
  const [mtMismatchSortColumn, setMtMismatchSortColumn] = useState<MismatchSortColumn>("mismatch");
  const [mtMismatchSortDirection, setMtMismatchSortDirection] = useState<CrudSortDirection>("desc");
  const [selectedAnalysis, setSelectedAnalysis] = useState<TagConsistencyRow | null>(null);
  const [departureFilters, setDepartureFilters] = useState<DepartureFilters>({
    depotId: activeDepotId,
    startDate: "",
    endDate: "",
    bucketMinutes: "30",
    search: ""
  });
  const [departureAnalysis, setDepartureAnalysis] = useState<DepartureAnalysis | null>(null);
  const [appliedDepartureFilters, setAppliedDepartureFilters] = useState<DepartureFilters | null>(null);
  const [departureDateAvailability, setDepartureDateAvailability] = useState<DepartureDateAvailability | null>(null);
  const [departureDateLoading, setDepartureDateLoading] = useState(false);
  const [departureLoading, setDepartureLoading] = useState(false);
  const [departureOffset, setDepartureOffset] = useState(0);
  const [departureLimit, setDepartureLimit] = useState(25);
  const [departureSortColumn, setDepartureSortColumn] = useState<DepartureSortColumn>("observation_count");
  const [departureSortDirection, setDepartureSortDirection] = useState<CrudSortDirection>("desc");
  const [selectedDepartureSpbuId, setSelectedDepartureSpbuId] = useState<string | null>(null);
  const [departureProfileSearch, setDepartureProfileSearch] = useState("");
  const [shiftConfigs, setShiftConfigs] = useState<OperationalShiftConfig[]>(defaultShiftConfig);
  const [shiftMethod, setShiftMethod] = useState<ShiftAssignmentMethod>("DOMINANT_SHIFT");
  const [shiftAnalysis, setShiftAnalysis] = useState<ShiftAnalysis | null>(null);
  const [shiftLoading, setShiftLoading] = useState(false);
  const [shiftHelpOpen, setShiftHelpOpen] = useState(false);
  const [shiftConfigMessage, setShiftConfigMessage] = useState("");
  const [savedShiftConfigs, setSavedShiftConfigs] = useState<SavedShiftAnalysisConfig[]>([]);
  const [savedShiftConfigTotal, setSavedShiftConfigTotal] = useState(0);
  const [savedShiftConfigOffset, setSavedShiftConfigOffset] = useState(0);
  const [savedShiftConfigLimit, setSavedShiftConfigLimit] = useState(5);
  const [savedShiftConfigLoading, setSavedShiftConfigLoading] = useState(false);
  const [shiftSaveModalOpen, setShiftSaveModalOpen] = useState(false);
  const [shiftSaveName, setShiftSaveName] = useState("");
  const [shiftLoadModalOpen, setShiftLoadModalOpen] = useState(false);
  const [selectedSavedShiftConfigId, setSelectedSavedShiftConfigId] = useState("");
  const [departureConfidenceFilter, setDepartureConfidenceFilter] = useState<DepartureConfidenceFilter>("ALL");
  const [shiftSummaryFilter, setShiftSummaryFilter] = useState<ShiftSummaryFilter>("ALL");
  const [boxPlotHighlightBy, setBoxPlotHighlightBy] = useState<"NONE" | "PRIMARY_SHIFT" | "ASSIGNMENT_STATUS" | "CONFIDENCE">("NONE");
  const [pairingFilters, setPairingFilters] = useState<PairingFilters>({
    depotId: activeDepotId,
    rangePreset: "30",
    startDate: "",
    endDate: "",
    productId: "",
    search: ""
  });
  const [pairingAnalysis, setPairingAnalysis] = useState<PairingAnalysis | null>(null);
  const [appliedPairingFilters, setAppliedPairingFilters] = useState<PairingFilters | null>(null);
  const [pairingDateAvailability, setPairingDateAvailability] = useState<DepartureDateAvailability | null>(null);
  const [pairingDateLoading, setPairingDateLoading] = useState(false);
  const [pairingLoading, setPairingLoading] = useState(false);
  const [pairingOffset, setPairingOffset] = useState(0);
  const [pairingLimit, setPairingLimit] = useState(25);
  const [pairingSortColumn, setPairingSortColumn] = useState<PairingSortColumn>("evidence_strength");
  const [pairingSortDirection, setPairingSortDirection] = useState<CrudSortDirection>("desc");
  const [selectedPairingSpbuId, setSelectedPairingSpbuId] = useState<string | null>(null);
  const [selectedPairingPair, setSelectedPairingPair] = useState<{ spbu_a_id: string; spbu_b_id: string } | null>(null);
  const [savedPairingConfigs, setSavedPairingConfigs] = useState<SavedPairingAnalysisConfig[]>([]);
  const [savedPairingConfigTotal, setSavedPairingConfigTotal] = useState(0);
  const [savedPairingConfigOffset, setSavedPairingConfigOffset] = useState(0);
  const [savedPairingConfigLimit, setSavedPairingConfigLimit] = useState(5);
  const [savedPairingConfigLoading, setSavedPairingConfigLoading] = useState(false);
  const [pairingSaveModalOpen, setPairingSaveModalOpen] = useState(false);
  const [pairingSaveName, setPairingSaveName] = useState("");
  const [pairingLoadModalOpen, setPairingLoadModalOpen] = useState(false);
  const [selectedSavedPairingConfigId, setSelectedSavedPairingConfigId] = useState("");
  const [pairingConfigMessage, setPairingConfigMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const crudRequestRef = useRef(0);
  const tagRequestRef = useRef(0);
  const departureRequestRef = useRef(0);
  const pairingRequestRef = useRef(0);
  const configs = useMemo(() => crudConfigs(depots, tagTypes), [depots, tagTypes]);
  const activeCrudConfig = configs[crudDomain];

  async function fetchCrud() {
    if (activeCrudConfig.depotFilter && !activeDepotId) { setCrudRows([]); setCrudTotal(0); return; }
    const requestId = crudRequestRef.current + 1;
    crudRequestRef.current = requestId;
    setCrudLoading(true);
    setError(null);
    try {
      const requestLimit = crudLimit === "ALL" ? 10000 : crudLimit;
      const requestOffset = crudLimit === "ALL" ? 0 : crudOffset;
      const params = new URLSearchParams({
        limit: String(requestLimit),
        offset: String(requestOffset)
      });
      params.set("sort_column", crudSortColumn || activeCrudConfig.columns[0]);
      params.set("sort_direction", crudSortDirection);
      if (crudAppliedSearch.trim()) {
        params.set("search", crudAppliedSearch.trim());
        params.set("search_column", crudAppliedSearchColumn || activeCrudConfig.columns[0]);
      }
      if (crudDepotId !== "ALL") params.set("depot_id", crudDepotId);
      const payload = await apiGet<CrudResponse>(`/api/v1/master-crud/${crudDomain}?${params.toString()}`);
      if (crudRequestRef.current === requestId) {
        setCrudRows(payload.rows);
        setCrudTotal(payload.total);
        setSelectedCrudIds(new Set());
      }
    } catch (err) {
      if (crudRequestRef.current === requestId) {
        setError(err instanceof Error ? err.message : "Failed to load CRUD data");
      }
    } finally {
      if (crudRequestRef.current === requestId) {
        setCrudLoading(false);
      }
    }
  }

  async function fetchTagAnalysis(nextOffset = tagOffset, filters = tagFilters) {
    const requestId = tagRequestRef.current + 1;
    tagRequestRef.current = requestId;
    setTagLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(tagLimit),
        offset: String(nextOffset),
        sort_column: tagSortColumn,
        sort_direction: tagSortDirection
      });
      if (filters.startDate) params.set("start_date", filters.startDate);
      if (filters.endDate) params.set("end_date", filters.endDate);
      if (filters.depotId !== "ALL") params.set("depot_id", filters.depotId);
      if (filters.spbu.trim()) params.set("spbu", filters.spbu.trim());
      if (filters.vehicle.trim()) params.set("vehicle", filters.vehicle.trim());
      if (filters.tagType !== "ALL") params.set("tag_type", filters.tagType);
      if (filters.status !== "ALL") params.set("overall_status", filters.status);
      if (filters.productId) params.set("product_id", filters.productId);
      if (filters.vehicleClass) params.set("vehicle_class", filters.vehicleClass);
      if (filters.search.trim()) params.set("search", filters.search.trim());
      const payload = await apiGet<TagConsistencyResponse>(`/api/v1/tag-consistency/analysis?${params.toString()}`);
      if (tagRequestRef.current === requestId) {
        setTagAnalysis(payload);
        // Capture the successful table scope, including its effective default dates.
        for (const [key, value] of Object.entries(payload.effective_filters)) {
          if (value !== null) params.set(key, String(value));
        }
        params.delete("limit");
        params.delete("offset");
        setTagExportParams(params.toString());
      }
    } catch (err) {
      if (tagRequestRef.current === requestId) {
        setError(err instanceof Error ? err.message : "Failed to load tag consistency analysis");
      }
    } finally {
      if (tagRequestRef.current === requestId) {
        setTagLoading(false);
      }
    }
  }

  async function handleExportTagAnalysis() {
    if (!tagExportParams || tagExporting) return;
    setTagExporting(true);
    setError(null);
    try {
      const params = new URLSearchParams(tagExportParams);
      params.set("export_excel", "true");
      await downloadFromApi(`/api/v1/tag-consistency/analysis?${params.toString()}`, "tag_consistency.xlsx");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tag consistency export failed");
    } finally {
      setTagExporting(false);
    }
  }

  function spbuIdsForShiftSummaryFilter(filter: ShiftSummaryFilter, analysis = shiftAnalysis): string[] | null {
    if (filter === "ALL") return null;
    if (!analysis) return [];
    if (filter.startsWith("SHIFT:")) {
      const shiftId = filter.replace("SHIFT:", "");
      return analysis.rows.filter((row) => row.primary_shift_id === shiftId).map((row) => row.spbu_id);
    }
    if (filter === "STATUS:AMBIGUOUS") {
      return analysis.rows.filter((row) => row.assignment_status === "AMBIGUOUS").map((row) => row.spbu_id);
    }
    if (filter === "STATUS:INSUFFICIENT_DATA") {
      return analysis.rows.filter((row) => row.assignment_status === "INSUFFICIENT_DATA").map((row) => row.spbu_id);
    }
    return null;
  }

  async function fetchDepartureAnalysis(
    nextOffset = departureOffset,
    filters = departureFilters,
    profileFilters: DepartureProfileFilterOptions = {}
  ): Promise<DepartureAnalysis | null> {
    if (!filters.depotId || !filters.startDate || !filters.endDate) {
      setError("Select a depot, start date, and end date before running Phase 2.");
      return null;
    }
    const effectiveConfidenceFilter = profileFilters.confidenceLevel ?? departureConfidenceFilter;
    const effectiveShiftSummaryFilter = profileFilters.shiftSummaryFilter ?? shiftSummaryFilter;
    const effectiveProfileSearch = profileFilters.profileSearch ?? departureProfileSearch;
    const filteredSpbuIds = spbuIdsForShiftSummaryFilter(effectiveShiftSummaryFilter);
    const requestId = departureRequestRef.current + 1;
    departureRequestRef.current = requestId;
    setDepartureLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        depot_id: filters.depotId,
        start_date: filters.startDate,
        end_date: filters.endDate,
        bucket_minutes: filters.bucketMinutes,
        limit: String(departureLimit),
        offset: String(nextOffset),
        sort_column: departureSortColumn,
        sort_direction: departureSortDirection
      });
      if (filters.search.trim()) params.set("search", filters.search.trim());
      if (effectiveProfileSearch.trim()) params.set("profile_search", effectiveProfileSearch.trim());
      if (effectiveConfidenceFilter !== "ALL") params.set("confidence_level", effectiveConfidenceFilter);
      if (filteredSpbuIds !== null) params.set("spbu_ids", filteredSpbuIds.length > 0 ? filteredSpbuIds.join(",") : "__NO_MATCH__");
      const payload = await apiGet<DepartureAnalysis>(`/api/v1/departure-intelligence/analysis?${params.toString()}`);
      if (departureRequestRef.current === requestId) {
        setDepartureAnalysis(payload);
        setAppliedDepartureFilters(filters);
        setSelectedDepartureSpbuId(payload.profiles[0]?.spbu_id ?? null);
      }
      return payload;
    } catch (err) {
      if (departureRequestRef.current === requestId) {
        setError(err instanceof Error ? err.message : "Failed to load departure intelligence");
      }
      return null;
    } finally {
      if (departureRequestRef.current === requestId) {
        setDepartureLoading(false);
      }
    }
  }

  async function fetchDepartureDateAvailability(depotId: string) {
    if (!depotId) {
      setDepartureDateAvailability(null);
      return;
    }
    setDepartureDateLoading(true);
    try {
      const payload = await apiGet<DepartureDateAvailability>(`/api/v1/departure-intelligence/available-dates?depot_id=${encodeURIComponent(depotId)}`);
      setDepartureDateAvailability(payload);
    } catch (err) {
      setDepartureDateAvailability(null);
      setError(err instanceof Error ? err.message : "Failed to load departure date availability");
    } finally {
      setDepartureDateLoading(false);
    }
  }

  async function fetchPairingDateAvailability(depotId: string) {
    if (!depotId) {
      setPairingDateAvailability(null);
      return;
    }
    setPairingDateLoading(true);
    try {
      const payload = await apiGet<DepartureDateAvailability>(`/api/v1/pairing-intelligence/available-dates?depot_id=${encodeURIComponent(depotId)}`);
      setPairingDateAvailability(payload);
      setPairingFilters((current) => {
        if (current.startDate || current.endDate || !payload.max_date) return current;
        const end = parseIsoDate(payload.max_date);
        return { ...current, endDate: payload.max_date, startDate: isoDateFromDate(addDays(end, -29)) };
      });
    } catch (err) {
      setPairingDateAvailability(null);
      setError(err instanceof Error ? err.message : "Failed to load pairing date availability");
    } finally {
      setPairingDateLoading(false);
    }
  }

  async function fetchPairingAnalysis(
    nextOffset = pairingOffset,
    filters = pairingFilters,
    selectedSpbuId = selectedPairingSpbuId,
    selectedPair = selectedPairingPair
  ): Promise<PairingAnalysis | null> {
    if (!filters.depotId || !filters.startDate || !filters.endDate) {
      setError("Select a depot, date range, and product scope before running Phase 3.");
      return null;
    }
    const requestId = pairingRequestRef.current + 1;
    pairingRequestRef.current = requestId;
    setPairingLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        depot_id: filters.depotId,
        start_date: filters.startDate,
        end_date: filters.endDate,
        limit: String(pairingLimit),
        offset: String(nextOffset),
        sort_column: pairingSortColumn,
        sort_direction: pairingSortDirection,
        matrix_limit: "30",
        network_limit: "40"
      });
      if (filters.productId) params.set("product_id", filters.productId);
      if (filters.search.trim()) params.set("search", filters.search.trim());
      if (selectedSpbuId) params.set("selected_spbu_id", selectedSpbuId);
      if (selectedPair) {
        params.set("evidence_spbu_a_id", selectedPair.spbu_a_id);
        params.set("evidence_spbu_b_id", selectedPair.spbu_b_id);
      }
      const payload = await apiGet<PairingAnalysis>(`/api/v1/pairing-intelligence/analysis?${params.toString()}`);
      if (pairingRequestRef.current === requestId) {
        setPairingAnalysis(payload);
        setAppliedPairingFilters(filters);
        setSelectedPairingSpbuId(payload.detail?.spbu_id ?? null);
        setSelectedPairingPair(payload.evidence.pair ? { spbu_a_id: payload.evidence.pair.spbu_a_id, spbu_b_id: payload.evidence.pair.spbu_b_id } : null);
      }
      return payload;
    } catch (err) {
      if (pairingRequestRef.current === requestId) {
        setError(err instanceof Error ? err.message : "Failed to load SPBU pairing intelligence");
      }
      return null;
    } finally {
      if (pairingRequestRef.current === requestId) {
        setPairingLoading(false);
      }
    }
  }

  async function fetchShiftAnalysis(filters = appliedDepartureFilters) {
    if (!filters) return;
    const validationErrors = validateOperationalShifts(shiftConfigs);
    if (validationErrors.length > 0) {
      setError(validationErrors[0]);
      return;
    }
    setShiftLoading(true);
    setError(null);
    try {
      const payload = await apiSend<ShiftAnalysis>("/api/v1/departure-intelligence/shift-analysis", "POST", {
        depot_id: filters.depotId,
        start_date: filters.startDate,
        end_date: filters.endDate,
        bucket_minutes: Number(filters.bucketMinutes),
        shifts: shiftConfigs,
        assignment_method: shiftMethod,
        search: filters.search,
        sort_column: departureSortColumn,
        sort_direction: departureSortDirection
      });
      setShiftAnalysis(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load operational shift intelligence");
    } finally {
      setShiftLoading(false);
    }
  }

  async function fetchSavedShiftConfigs(nextOffset = savedShiftConfigOffset, nextLimit = savedShiftConfigLimit) {
    setSavedShiftConfigLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(nextLimit),
        offset: String(nextOffset)
      });
      if (departureFilters.depotId) params.set("depot_id", departureFilters.depotId);
      const payload = await apiGet<SavedShiftAnalysisConfigResponse>(`/api/v1/departure-intelligence/saved-shift-configurations?${params.toString()}`);
      setSavedShiftConfigs(payload.rows);
      setSavedShiftConfigTotal(payload.total);
      setSavedShiftConfigOffset(payload.offset);
      setSavedShiftConfigLimit(payload.limit);
      setSelectedSavedShiftConfigId((current) => (
        payload.rows.some((row) => row.id === current) ? current : payload.rows[0]?.id || ""
      ));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load saved shift configurations");
    } finally {
      setSavedShiftConfigLoading(false);
    }
  }

  async function fetchSavedPairingConfigs(nextOffset = savedPairingConfigOffset, nextLimit = savedPairingConfigLimit) {
    setSavedPairingConfigLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(nextLimit),
        offset: String(nextOffset)
      });
      if (pairingFilters.depotId) params.set("depot_id", pairingFilters.depotId);
      const payload = await apiGet<SavedPairingAnalysisConfigResponse>(`/api/v1/pairing-intelligence/saved-configurations?${params.toString()}`);
      setSavedPairingConfigs(payload.rows);
      setSavedPairingConfigTotal(payload.total);
      setSavedPairingConfigOffset(payload.offset);
      setSavedPairingConfigLimit(payload.limit);
      setSelectedSavedPairingConfigId((current) => (
        payload.rows.some((row) => row.id === current) ? current : payload.rows[0]?.id || ""
      ));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load saved pairing configurations");
    } finally {
      setSavedPairingConfigLoading(false);
    }
  }

  async function refresh() {
    setError(null);
    const available = await apiGet<Depot[]>("/api/v1/master/depots");
    setDepots(available);
    if (!available.some((depot) => depot.depot_id === activeDepotId && depot.active_status === "ACTIVE")) {
      const next = available.find((depot) => depot.active_status === "ACTIVE")?.depot_id || "";
      if (next !== activeDepotId) onDepotChange(next);
      return;
    }
    const dashboardParams = dashboardDepotId !== "ALL" ? `?depot_id=${encodeURIComponent(dashboardDepotId)}` : "";
    const issueParams = new URLSearchParams({ limit: "20" });
    if (dashboardDepotId !== "ALL") issueParams.set("depot_id", dashboardDepotId);
    const compatibilityParams = new URLSearchParams({ limit: "12" });
    if (dashboardDepotId !== "ALL") compatibilityParams.set("depot_id", dashboardDepotId);
    const [overviewData, chartData, importData, issueData, depotData, tagTypeData, productData] = await Promise.all([
      apiGet<Overview>(`/api/v1/foundation/overview${dashboardParams}`),
      apiGet<Charts>(`/api/v1/foundation/charts${dashboardParams}`),
      apiGet<ImportAudit[]>(`/api/v1/imports?depot_id=${encodeURIComponent(activeDepotId)}`),
      apiGet<QualityIssue[]>(`/api/v1/data-quality/issues?${issueParams.toString()}`),
      apiGet<Depot[]>("/api/v1/master/depots"),
      apiGet<CrudResponse>("/api/v1/master-crud/TAG_TYPE?limit=10000"),
      apiGet<Product[]>("/api/v1/master/products")
    ]);
    setOverview(overviewData);
    setCharts(chartData);
    setImports(importData);
    setIssues(issueData);
    setDepots(depotData);
    setTagTypes(tagTypeData.rows as unknown as TagType[]);
    setProducts(productData);
    setExportDepotId((current) => current || depotData[0]?.depot_id || "");
    apiGet<CompatibilitySummary>(`/api/v1/master/compatibility/summary?${compatibilityParams.toString()}`)
      .then(setCompatibility)
      .catch(() => setCompatibility({ compatible: 0, incompatible: 0, insufficient_data: 0, examples: [] }));
  }

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [dashboardDepotId]);

  useEffect(() => {
    if (currentPage === "master-data") {
      fetchCrud();
    }
  }, [currentPage, crudDomain, crudOffset, crudLimit, crudDepotId, crudAppliedSearch, crudAppliedSearchColumn, crudSortColumn, crudSortDirection]);

  useEffect(() => {
    if (!activeImportId) return;
    let cancelled = false;
    let timer: number | undefined;

    async function pollImport() {
      try {
        const payload = await apiGet<ImportDetail>(`/api/v1/imports/${activeImportId}`);
        if (cancelled) return;
        const nextStatus = payload.import.status;
        setActiveImportStatus(nextStatus);
        if (payload.import.depot_id === activeDepotId) setImports((current) => [
          payload.import,
          ...current.filter((item) => item.import_id !== payload.import.import_id)
        ].slice(0, 8));
        if (["PUBLISHED", "STAGED", "FAILED"].includes(nextStatus)) {
          window.localStorage.removeItem("dispatch-active-import-id");
          setActiveImportId(null);
          setUploading(false);
          await refresh();
          if (currentPage === "master-data") await fetchCrud();
          if (nextStatus === "FAILED") {
            setError(payload.import.error_message || "File import failed");
          }
          return;
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to read import status");
      }
      if (!cancelled) timer = window.setTimeout(pollImport, 1500);
    }

    void pollImport();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeImportId, currentPage]);

  useEffect(() => {
    if (currentPage === "tag-consistency") {
      fetchTagAnalysis();
    }
  }, [currentPage, tagOffset, tagLimit, tagSortColumn, tagSortDirection]);

  useEffect(() => {
    if (currentPage === "departure-intelligence" && departureAnalysis && appliedDepartureFilters) {
      fetchDepartureAnalysis(departureOffset, appliedDepartureFilters);
    }
  }, [currentPage, departureOffset, departureLimit, departureSortColumn, departureSortDirection, departureConfidenceFilter, shiftSummaryFilter, departureProfileSearch, shiftAnalysis]);

  useEffect(() => {
    if (currentPage === "departure-intelligence") {
      fetchSavedShiftConfigs(savedShiftConfigOffset, savedShiftConfigLimit);
    }
  }, [currentPage, departureFilters.depotId, savedShiftConfigOffset, savedShiftConfigLimit]);

  useEffect(() => {
    if (currentPage === "departure-intelligence") {
      fetchDepartureDateAvailability(departureFilters.depotId);
    }
  }, [currentPage, departureFilters.depotId]);

  useEffect(() => {
    if (currentPage === "pairing-intelligence" && pairingAnalysis && appliedPairingFilters) {
      fetchPairingAnalysis(pairingOffset, appliedPairingFilters);
    }
  }, [currentPage, pairingOffset, pairingLimit, pairingSortColumn, pairingSortDirection]);

  useEffect(() => {
    if (currentPage === "pairing-intelligence") {
      fetchSavedPairingConfigs(savedPairingConfigOffset, savedPairingConfigLimit);
    }
  }, [currentPage, pairingFilters.depotId, savedPairingConfigOffset, savedPairingConfigLimit]);

  useEffect(() => {
    if (currentPage === "pairing-intelligence") {
      fetchPairingDateAvailability(pairingFilters.depotId);
    }
  }, [currentPage, pairingFilters.depotId]);

  useEffect(() => {
    const handlePopState = () => setCurrentPage(pageFromPath(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const hasData = useMemo(() => (overview.total_mt ?? 0) > 0 || (overview.total_spbu ?? 0) > 0, [overview]);
  const visibleCrudIds = useMemo(
    () =>
      crudRows
        .map((row) => row[activeCrudConfig.idKey])
        .filter((value): value is string | number => value !== null && value !== undefined && value !== "")
        .map(String),
    [activeCrudConfig.idKey, crudRows]
  );
  const selectedCrudRows = useMemo(
    () =>
      crudRows.filter((row) => {
        const rawRecordId = row[activeCrudConfig.idKey];
        return rawRecordId !== null && rawRecordId !== undefined && rawRecordId !== "" && selectedCrudIds.has(String(rawRecordId));
      }),
    [activeCrudConfig.idKey, crudRows, selectedCrudIds]
  );
  const allVisibleCrudRowsSelected = visibleCrudIds.length > 0 && visibleCrudIds.every((recordId) => selectedCrudIds.has(recordId));
  const selectedCrudCount = selectedCrudRows.length;
  const isCrudAllRecords = crudLimit === "ALL";
  const crudPageSizeNumber = typeof crudLimit === "number" ? crudLimit : 0;
  const crudDisplayOffset = isCrudAllRecords ? 0 : crudOffset;
  const crudShowingStart = crudTotal === 0 ? 0 : crudDisplayOffset + 1;
  const crudShowingEnd = isCrudAllRecords ? crudRows.length : Math.min(crudDisplayOffset + crudPageSizeNumber, crudTotal);
  const crudPageNumber = isCrudAllRecords ? 1 : Math.floor(crudOffset / crudPageSizeNumber) + 1;
  const crudPageCount = isCrudAllRecords ? 1 : Math.max(1, Math.ceil(crudTotal / crudPageSizeNumber));
  const canPreviousCrudPage = !isCrudAllRecords && crudOffset > 0 && !crudLoading;
  const canNextCrudPage = !isCrudAllRecords && crudOffset + crudPageSizeNumber < crudTotal && !crudLoading;
  const canSyncCrudDomain = ["PRODUCT", "TAG"].includes(crudDomain);
  const tagSummary = tagAnalysis?.summary ?? emptyTagConsistencySummary;
  const tagRows = tagAnalysis?.rows ?? [];
  const tagTotal = tagAnalysis?.total ?? 0;
  const tagShowingStart = tagTotal === 0 ? 0 : tagOffset + 1;
  const tagShowingEnd = Math.min(tagOffset + tagLimit, tagTotal);
  const tagPageNumber = Math.floor(tagOffset / tagLimit) + 1;
  const tagPageCount = Math.max(1, Math.ceil(tagTotal / tagLimit));
  const canPreviousTagPage = tagOffset > 0 && !tagLoading;
  const canNextTagPage = tagOffset + tagLimit < tagTotal && !tagLoading;
  const departureSummary = departureAnalysis?.summary;
  const departureAvailableDateSet = useMemo(() => new Set(departureDateAvailability?.available_dates ?? []), [departureDateAvailability]);
  const departureDateCountMap = useMemo(
    () => new Map((departureDateAvailability?.dates ?? []).map((item) => [item.date, item.shipment_count])),
    [departureDateAvailability]
  );
  const departureProfiles = departureAnalysis?.profiles ?? [];
  const departureObservations = departureAnalysis?.observations ?? [];
  const departureTotal = departureAnalysis?.total ?? 0;
  const departureShowingStart = departureTotal === 0 ? 0 : departureOffset + 1;
  const departureShowingEnd = Math.min(departureOffset + departureLimit, departureTotal);
  const departurePageNumber = Math.floor(departureOffset / departureLimit) + 1;
  const departurePageCount = Math.max(1, Math.ceil(departureTotal / departureLimit));
  const canPreviousDeparturePage = departureOffset > 0 && !departureLoading;
  const canNextDeparturePage = departureOffset + departureLimit < departureTotal && !departureLoading;
  const savedShiftConfigShowingStart = savedShiftConfigTotal === 0 ? 0 : savedShiftConfigOffset + 1;
  const savedShiftConfigShowingEnd = Math.min(savedShiftConfigOffset + savedShiftConfigLimit, savedShiftConfigTotal);
  const savedShiftConfigPageNumber = Math.floor(savedShiftConfigOffset / savedShiftConfigLimit) + 1;
  const savedShiftConfigPageCount = Math.max(1, Math.ceil(savedShiftConfigTotal / savedShiftConfigLimit));
  const canPreviousSavedShiftConfigPage = savedShiftConfigOffset > 0 && !savedShiftConfigLoading;
  const canNextSavedShiftConfigPage = savedShiftConfigOffset + savedShiftConfigLimit < savedShiftConfigTotal && !savedShiftConfigLoading;
  const selectedDepartureProfile = departureProfiles.find((profile) => profile.spbu_id === selectedDepartureSpbuId) ?? departureProfiles[0] ?? null;
  const selectedDepartureObservations = selectedDepartureProfile
    ? departureObservations.filter((row) => row.spbu_id === selectedDepartureProfile.spbu_id).slice(0, 20)
    : [];
  const shiftValidationErrors = useMemo(() => validateOperationalShifts(shiftConfigs), [shiftConfigs]);
  const shiftRowBySpbuId = useMemo(() => new Map((shiftAnalysis?.rows ?? []).map((row) => [row.spbu_id, row])), [shiftAnalysis]);
  const currentPageShiftRows = useMemo(
    () => departureProfiles.map((profile) => shiftRowBySpbuId.get(profile.spbu_id)).filter((row): row is ShiftAssignmentRow => Boolean(row)),
    [departureProfiles, shiftRowBySpbuId]
  );
  const selectedShiftRow = shiftAnalysis?.rows.find((row) => row.spbu_id === selectedDepartureProfile?.spbu_id) ?? null;
  const pairingRows = pairingAnalysis?.pairs ?? [];
  const pairingSummary = pairingAnalysis?.summary;
  const pairingTotal = pairingAnalysis?.total ?? 0;
  const pairingShowingStart = pairingTotal === 0 ? 0 : pairingOffset + 1;
  const pairingShowingEnd = Math.min(pairingOffset + pairingLimit, pairingTotal);
  const pairingPageNumber = Math.floor(pairingOffset / pairingLimit) + 1;
  const pairingPageCount = Math.max(1, Math.ceil(pairingTotal / pairingLimit));
  const canPreviousPairingPage = pairingOffset > 0 && !pairingLoading;
  const canNextPairingPage = pairingOffset + pairingLimit < pairingTotal && !pairingLoading;
  const savedPairingConfigShowingStart = savedPairingConfigTotal === 0 ? 0 : savedPairingConfigOffset + 1;
  const savedPairingConfigShowingEnd = Math.min(savedPairingConfigOffset + savedPairingConfigLimit, savedPairingConfigTotal);
  const savedPairingConfigPageNumber = Math.floor(savedPairingConfigOffset / savedPairingConfigLimit) + 1;
  const savedPairingConfigPageCount = Math.max(1, Math.ceil(savedPairingConfigTotal / savedPairingConfigLimit));
  const canPreviousSavedPairingConfigPage = savedPairingConfigOffset > 0 && !savedPairingConfigLoading;
  const canNextSavedPairingConfigPage = savedPairingConfigOffset + savedPairingConfigLimit < savedPairingConfigTotal && !savedPairingConfigLoading;
  const selectedPairingDetail = pairingAnalysis?.detail ?? null;
  const pairingMatrixOption = useMemo(() => {
    const matrix = pairingAnalysis?.matrix;
    if (!matrix || matrix.x_axis.length === 0) return null;
    return {
      tooltip: {
        position: "top",
        formatter: (params: { data: [number, number, number, number, number, number, number, number, string, string[], string[]] }) => {
          const [x, y, probability, pairCount, reverseProbability, support, lift, observationCount, confidence, anchorTags, candidateTags] = params.data;
          return `${matrix.y_axis[y]} -> ${matrix.x_axis[x]}<br />Anchor SPBU Tag: ${formatTags(anchorTags)}<br />Candidate SPBU Tag: ${formatTags(candidateTags)}<br />Pair Count: ${pairCount}<br />P(candidate|anchor): ${formatPercent(probability)}<br />Reverse Probability: ${formatPercent(reverseProbability)}<br />Support: ${formatPercent(support)}<br />Lift: ${formatMetric(lift)}<br />Observation Count: ${observationCount}<br />Confidence: ${confidence}`;
        }
      },
      grid: { top: 20, right: 24, bottom: 84, left: 96 },
      xAxis: { type: "category", data: matrix.x_axis, axisLabel: { interval: 0, rotate: 45 } },
      yAxis: { type: "category", data: matrix.y_axis, axisLabel: { interval: 0 } },
      visualMap: { min: 0, max: 1, dimension: 2, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#f8fafc", "#dbeafe", "#93c5fd", "#0b73bf"] } },
      series: [{ type: "heatmap", data: matrix.data, itemStyle: { borderColor: "#ffffff", borderWidth: 1 } }]
    };
  }, [pairingAnalysis]);
  const pairingNetworkOption = useMemo(() => {
    const network = pairingAnalysis?.network;
    if (!network || network.nodes.length === 0) return null;
    return {
      tooltip: {
        formatter: (params: { dataType?: string; data?: { name?: string; tags?: string[]; value?: number; metrics?: PairingPair; label?: string } }) => {
          if (params.dataType === "edge" && params.data?.metrics) {
            const row = params.data.metrics;
            return `${params.data.label}<br />SPBU A Tag: ${formatTags(row.spbu_a_tags)}<br />SPBU B Tag: ${formatTags(row.spbu_b_tags)}<br />Pair Count: ${row.pair_count}<br />P(B|A): ${formatPercent(row.probability_b_given_a)}<br />P(A|B): ${formatPercent(row.probability_a_given_b)}<br />Support: ${formatPercent(row.support)}<br />Lift: ${formatMetric(row.lift)}<br />Confidence: ${row.confidence_level}`;
          }
          return `${params.data?.name ?? ""}<br />SPBU Tag: ${formatTags(params.data?.tags)}<br />Shipments: ${params.data?.value ?? 0}`;
        }
      },
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          draggable: true,
          data: network.nodes,
          edges: network.edges,
          label: { show: true, position: "right", formatter: "{b}" },
          force: { repulsion: 180, edgeLength: 96 },
          lineStyle: { color: "#0b73bf", curveness: 0.08 },
          emphasis: { focus: "adjacency" }
        }
      ]
    };
  }, [pairingAnalysis]);
  const shiftAffinityHeatmapOption = useMemo(() => {
    if (!shiftAnalysis || currentPageShiftRows.length === 0) return null;
    const xAxis = shiftAnalysis.shift_config.map((shift) => shift.name);
    const yAxis = currentPageShiftRows.map((row) => row.spbu_code);
    const data = currentPageShiftRows.flatMap((row, rowIndex) =>
      row.shift_distribution.map((distribution, shiftIndex) => [shiftIndex, rowIndex, distribution.share_pct, distribution.observation_count, row.observation_count])
    );
    return {
      tooltip: {
        position: "top",
        formatter: (params: { data: number[] }) => {
          const [shiftIndex, rowIndex, share, count, total] = params.data;
          const row = currentPageShiftRows[rowIndex];
          const spbu = yAxis[rowIndex];
          const shift = xAxis[shiftIndex];
          const name = row?.spbu_name ?? "";
          return `${spbu}${name ? ` - ${name}` : ""}<br />${shift}<br />${count} of ${total} historical observations<br />Shift Affinity = ${share}%`;
        }
      },
      grid: { top: 18, right: 24, bottom: 42, left: 104 },
      xAxis: { type: "category", data: xAxis, axisLabel: { interval: 0, rotate: 0 } },
      yAxis: { type: "category", data: yAxis, axisLabel: { interval: 0 } },
      visualMap: {
        min: 0,
        max: 100,
        dimension: 2,
        calculable: true,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        inRange: { color: ["#f8fafc", "#dbeafe", "#60a5fa", "#2563eb", "#1e3a8a"] }
      },
      dataZoom: yAxis.length > 30 ? [{ type: "slider", yAxisIndex: 0, right: 0, width: 14 }, { type: "inside" }] : undefined,
      series: [
        {
          type: "heatmap",
          data,
          itemStyle: { borderColor: "#ffffff", borderWidth: 1 },
          emphasis: { itemStyle: { borderColor: "#0f172a", borderWidth: 1, shadowBlur: 6, shadowColor: "rgba(0,0,0,0.16)" } }
        }
      ]
    };
  }, [currentPageShiftRows, shiftAnalysis]);
  const heatmapOption = useMemo(() => {
    const heatmap = departureAnalysis?.weekday_heatmap;
    if (!heatmap) return null;
    const maxValue = Math.max(1, ...heatmap.data.map((item) => item[2] ?? 0));
    return {
      tooltip: {
        position: "top",
        formatter: (params: { data: number[] }) => `${heatmap.y_axis[params.data[1]]}<br />${heatmap.x_axis[params.data[0]]}: ${params.data[2]} observations`
      },
      grid: { top: 16, right: 24, bottom: 76, left: 84 },
      xAxis: { type: "category", data: heatmap.x_axis, axisLabel: { interval: 1, rotate: 45 } },
      yAxis: { type: "category", data: heatmap.y_axis },
      visualMap: { min: 0, max: maxValue, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#edf2f1", "#7fb2a8", "#2f7d6d"] } },
      series: [{ type: "heatmap", data: heatmap.data, emphasis: { itemStyle: { shadowBlur: 6, shadowColor: "rgba(0,0,0,0.18)" } } }]
    };
  }, [departureAnalysis]);
  const boxPlotOption = useMemo(() => {
    const boxPlot = departureAnalysis?.box_plot;
    if (!boxPlot) return null;
    const flattenedValues = boxPlot.data.flat();
    const yMin = Math.max(0, Math.floor(Math.min(0, ...flattenedValues) / 180) * 180);
    const yMax = Math.max(1440, Math.ceil(Math.max(1440, ...flattenedValues) / 180) * 180);
    const shiftRowsBySpbu = new Map((shiftAnalysis?.rows ?? []).map((row) => [row.spbu_code, row]));
    const shiftColorById = new Map((shiftAnalysis?.shift_config ?? []).map((shift, index) => [shift.shift_id, shiftPalette(index)]));
    const data = boxPlot.data.map((value, index) => {
      const row = shiftRowsBySpbu.get(boxPlot.categories[index]);
      let borderColor = "#2f7d6d";
      if (row && boxPlotHighlightBy === "PRIMARY_SHIFT" && row.primary_shift_id) borderColor = shiftColorById.get(row.primary_shift_id) ?? borderColor;
      if (row && boxPlotHighlightBy === "ASSIGNMENT_STATUS") borderColor = assignmentStatusBoxPlotColors[row.assignment_status] ?? borderColor;
      if (row && boxPlotHighlightBy === "CONFIDENCE") borderColor = confidenceBoxPlotColors[row.confidence_level] ?? borderColor;
      return { value, itemStyle: { color: "#dfe9e6", borderColor } };
    });
    const boundaryData = (shiftAnalysis?.shift_config ?? [])
      .flatMap((shift) => [shift.start_minute, shift.start_minute + 1440])
      .filter((minute) => minute > yMin && minute < yMax)
      .map((minute) => ({
        yAxis: minute,
        label: { formatter: shiftedMinuteAxisLabel(minute), color: "#b91c1c", fontWeight: 700 },
        lineStyle: { color: "#dc2626", type: "dashed", width: 2.5 }
      }));
    return {
      tooltip: {
        trigger: "item",
        formatter: (params: { name: string; data: number[] | { value: number[] } }) => {
          const values = Array.isArray(params.data) ? params.data : params.data.value;
          const row = shiftRowsBySpbu.get(params.name);
          return `${params.name}<br />Min ${shiftedMinuteAxisLabel(values[1])}<br />Q1 ${shiftedMinuteAxisLabel(values[2])}<br />P50 ${shiftedMinuteAxisLabel(values[3])}<br />Q3 ${shiftedMinuteAxisLabel(values[4])}<br />Max ${shiftedMinuteAxisLabel(values[5])}${row ? `<br />Primary Shift ${row.primary_shift_name ?? "-"}` : ""}`;
        }
      },
      grid: { top: 16, right: 24, bottom: 76, left: 52 },
      xAxis: { type: "category", data: boxPlot.categories, axisLabel: { interval: 0, rotate: 45 } },
      yAxis: { type: "value", min: yMin, max: yMax, interval: 180, axisLabel: { formatter: (value: number) => shiftedMinuteAxisLabel(value) } },
      dataZoom: boxPlot.categories.length > 30 ? [{ type: "slider", bottom: 18, height: 18 }, { type: "inside" }] : undefined,
      series: [
        {
          name: "Departure time",
          type: "boxplot",
          data,
          itemStyle: { color: "#dfe9e6", borderColor: "#2f7d6d" },
          markLine: boundaryData.length
            ? {
                silent: true,
                symbol: "none",
                label: { color: "#b91c1c", fontWeight: 700 },
                lineStyle: { color: "#dc2626", type: "dashed", width: 2.5 },
                data: boundaryData
              }
            : undefined
        }
      ]
    };
  }, [boxPlotHighlightBy, departureAnalysis, shiftAnalysis]);
  const boxPlotLegendItems = useMemo(() => {
    if (boxPlotHighlightBy === "PRIMARY_SHIFT") {
      return (shiftAnalysis?.shift_config ?? []).map((shift, index) => ({ label: shift.name, color: shiftPalette(index) }));
    }
    if (boxPlotHighlightBy === "ASSIGNMENT_STATUS") {
      return [
        { label: "CLEAR", color: assignmentStatusBoxPlotColors.CLEAR },
        { label: "MODERATE", color: assignmentStatusBoxPlotColors.MODERATE },
        { label: "AMBIGUOUS", color: assignmentStatusBoxPlotColors.AMBIGUOUS },
        { label: "INSUFFICIENT DATA", color: assignmentStatusBoxPlotColors.INSUFFICIENT_DATA }
      ];
    }
    if (boxPlotHighlightBy === "CONFIDENCE") {
      return [
        { label: "HIGH", color: confidenceBoxPlotColors.HIGH },
        { label: "MEDIUM", color: confidenceBoxPlotColors.MEDIUM },
        { label: "LOW", color: confidenceBoxPlotColors.LOW }
      ];
    }
    return [];
  }, [boxPlotHighlightBy, shiftAnalysis]);
  const allSpbuMismatchRows = useMemo(
    () => sortedMismatchRows(tagSummary.top_spbu_mismatch, "spbu", spbuMismatchSortColumn, spbuMismatchSortDirection),
    [tagSummary.top_spbu_mismatch, spbuMismatchSortColumn, spbuMismatchSortDirection]
  );
  const allMtMismatchRows = useMemo(
    () => sortedMismatchRows(tagSummary.top_mt_mismatch, "vehicle_registration", mtMismatchSortColumn, mtMismatchSortDirection),
    [tagSummary.top_mt_mismatch, mtMismatchSortColumn, mtMismatchSortDirection]
  );
  const spbuMismatchPageCount = Math.max(1, Math.ceil(allSpbuMismatchRows.length / mismatchRowsPerPage));
  const mtMismatchPageCount = Math.max(1, Math.ceil(allMtMismatchRows.length / mismatchRowsPerPage));
  const visibleSpbuMismatchRows = allSpbuMismatchRows.slice(spbuMismatchPage * mismatchRowsPerPage, (spbuMismatchPage + 1) * mismatchRowsPerPage);
  const visibleMtMismatchRows = allMtMismatchRows.slice(mtMismatchPage * mismatchRowsPerPage, (mtMismatchPage + 1) * mismatchRowsPerPage);

  function handleDomainChange(nextDomain: string) {
    setDomain(nextDomain);
    const defaultSheets: Record<string, string> = {
      MOBIL_TANGKI: "Mobil Tangki",
      SPBU: "SPBU",
      LOADING_ORDER: "Historikal Shipment",
      GPS: ""
    };
    setSheetName(defaultSheets[nextDomain] ?? "");
  }

  async function handleFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!activeDepotId) { setError("Pilih depot aktif di top bar sebelum upload."); return; }
    setUploading(true);
    setError(null);
    try {
      const queued = await uploadImportFile(domain, sheetName || "Sheet1", file, activeDepotId);
      window.localStorage.setItem("dispatch-active-import-id", queued.import_id);
      setActiveImportId(queued.import_id);
      setActiveImportStatus(queued.status);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "File import failed");
      setUploading(false);
    }
  }

  async function handleExportTemplate() {
    setExporting(true);
    setError(null);
    try {
      const params = new URLSearchParams({ domain, file_format: exportFormat });
      await downloadFromApi(`/api/v1/exports/template?${params.toString()}`, `template_${domain.toLowerCase()}.${exportFormat}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Template export failed");
    } finally {
      setExporting(false);
    }
  }

  async function handleExportData() {
    if (!exportDepotId) {
      setError("Depot belum tersedia untuk export data.");
      return;
    }
    setExporting(true);
    setError(null);
    try {
      const actualFormat = exportDomain === "ALL" ? "xlsx" : exportFormat;
      const params = new URLSearchParams({ domain: exportDomain, depot_id: exportDepotId, file_format: actualFormat });
      await downloadFromApi(`/api/v1/exports/data?${params.toString()}`, `export_${exportDomain.toLowerCase()}.${actualFormat}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Data export failed");
    } finally {
      setExporting(false);
    }
  }

  function closeCrudModal() {
    setCrudModalMode(null);
    setCrudBatchForms([]);
  }

  function openCrudAddModal() {
    if (activeCrudConfig.depotFilter && !activeDepotId) { setError("Pilih depot aktif terlebih dahulu."); return; }
    setError(null);
    setCrudModalMode("add");
    setCrudBatchForms([{ values: emptyCrudValues(activeCrudConfig) }]);
  }

  function openCrudEditModal() {
    if (selectedCrudRows.length === 0) {
      setError("Pilih minimal satu row untuk edit.");
      return;
    }
    setError(null);
    setCrudModalMode("edit");
    setCrudBatchForms(
      selectedCrudRows.map((row) => ({
        recordId: String(row[activeCrudConfig.idKey]),
        values: crudValuesFromRow(row, activeCrudConfig)
      }))
    );
  }

  function addCrudBatchRow() {
    setCrudBatchForms((current) => [...current, { values: emptyCrudValues(activeCrudConfig) }]);
  }

  function removeCrudBatchRow(rowIndex: number) {
    setCrudBatchForms((current) => current.filter((_, index) => index !== rowIndex));
  }

  function updateCrudBatchValue(rowIndex: number, fieldKey: string, value: unknown) {
    setCrudBatchForms((current) =>
      current.map((formRow, index) =>
        index === rowIndex ? { ...formRow, values: { ...formRow.values, [fieldKey]: value } } : formRow
      )
    );
  }

  function changeCrudDomain(nextDomain: string) {
    const nextSearchColumn = configs[nextDomain].columns[0] ?? "";
    crudRequestRef.current += 1;
    setCrudDomain(nextDomain);
    setCrudRows([]);
    setCrudTotal(0);
    setSelectedCrudIds(new Set());
    setCrudOffset(0);
    setCrudSearch("");
    setCrudAppliedSearch("");
    setCrudSearchColumn(nextSearchColumn);
    setCrudAppliedSearchColumn(nextSearchColumn);
    setCrudSortColumn(nextSearchColumn);
    setCrudSortDirection("asc");
    closeCrudModal();
  }

  async function saveCrudBatch() {
    if (!crudModalMode || crudBatchForms.length === 0) return;
    setCrudLoading(true);
    setError(null);
    try {
      for (const formRow of crudBatchForms) {
        if (crudModalMode === "edit") {
          if (!formRow.recordId) continue;
          await apiSend(`/api/v1/master-crud/${crudDomain}/${encodeURIComponent(formRow.recordId)}`, "PUT", { ...formRow.values, depot_id: activeDepotId, primary_depot_id: activeDepotId });
        } else {
          await apiSend(`/api/v1/master-crud/${crudDomain}`, "POST", { ...formRow.values, depot_id: activeDepotId, primary_depot_id: activeDepotId });
        }
      }
      closeCrudModal();
      await fetchCrud();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save master data");
    } finally {
      setCrudLoading(false);
    }
  }

  async function deleteSelectedCrudRows() {
    if (selectedCrudRows.length === 0) {
      setError("Pilih minimal satu row untuk delete.");
      return;
    }
    if (!window.confirm(`Delete ${selectedCrudRows.length.toLocaleString()} ${activeCrudConfig.label} record?`)) return;
    setCrudLoading(true);
    setError(null);
    try {
      for (const row of selectedCrudRows) {
        const recordId = String(row[activeCrudConfig.idKey]);
        await apiSend(`/api/v1/master-crud/${crudDomain}/${encodeURIComponent(recordId)}`, "DELETE");
      }
      setSelectedCrudIds(new Set());
      await fetchCrud();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete master data");
    } finally {
      setCrudLoading(false);
    }
  }

  async function syncCrudMasterData() {
    if (!canSyncCrudDomain) return;
    setCrudSyncing(true);
    setError(null);
    try {
      await apiSend(`/api/v1/master-crud/${crudDomain}/sync`, "POST");
      setSelectedCrudIds(new Set());
      setCrudOffset(0);
      await fetchCrud();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to sync master data");
    } finally {
      setCrudSyncing(false);
    }
  }

  function applyCrudSearch() {
    setCrudOffset(0);
    setCrudAppliedSearch(crudSearch.trim());
    setCrudAppliedSearchColumn(crudSearchColumn || activeCrudConfig.columns[0]);
  }

  function handleCrudLimitChange(value: string) {
    setCrudOffset(0);
    setCrudLimit(value === "ALL" ? "ALL" : (Number(value) as CrudPageSize));
  }

  function handleCrudSort(column: string) {
    setCrudOffset(0);
    setCrudSortDirection((current) => (crudSortColumn === column && current === "asc" ? "desc" : "asc"));
    setCrudSortColumn(column);
  }

  function updateTagFilter(key: keyof TagConsistencyFilters, value: string) {
    setTagFilters((current) => ({ ...current, [key]: value }));
  }

  function applyTagFilters() {
    setTagOffset(0);
    setSpbuMismatchPage(0);
    setMtMismatchPage(0);
    fetchTagAnalysis(0);
  }

  function resetTagFilters() {
    const cleared = {
      startDate: "",
      endDate: "",
      depotId: activeDepotId,
      spbu: "",
      vehicle: "",
      tagType: "ALL",
      status: "ALL",
      productId: "",
      vehicleClass: "",
      search: ""
    };
    setTagFilters(cleared);
    setTagOffset(0);
    setSpbuMismatchPage(0);
    setMtMismatchPage(0);
    fetchTagAnalysis(0, cleared);
  }

  function updateDepartureFilter(key: keyof DepartureFilters, value: string) {
    setDepartureFilters((current) => ({
      ...current,
      [key]: value,
      ...(key === "depotId" ? { startDate: "", endDate: "" } : {})
    }));
    if (key === "depotId") {
      setDepartureDateAvailability(null);
      setShiftAnalysis(null);
      setDepartureConfidenceFilter("ALL");
      setShiftSummaryFilter("ALL");
      setShiftConfigMessage("");
      setShiftConfigs(defaultShiftConfig);
      setSavedShiftConfigOffset(0);
      setSelectedSavedShiftConfigId("");
    }
  }

  async function applyDepartureFilters() {
    const validationErrors = validateOperationalShifts(shiftConfigs);
    if (validationErrors.length > 0) {
      setError(validationErrors[0]);
      return;
    }
    setDepartureOffset(0);
    setShiftAnalysis(null);
    setDepartureConfidenceFilter("ALL");
    setShiftSummaryFilter("ALL");
    setDepartureProfileSearch("");
    const payload = await fetchDepartureAnalysis(0, departureFilters, { confidenceLevel: "ALL", shiftSummaryFilter: "ALL", profileSearch: "" });
    if (payload) {
      await fetchShiftAnalysis(departureFilters);
    }
  }

  function toggleConfidenceProfileFilter(level: "HIGH" | "MEDIUM" | "LOW") {
    setDepartureConfidenceFilter((current) => (current === level ? "ALL" : level));
    setDepartureOffset(0);
  }

  function toggleShiftSummaryProfileFilter(filter: ShiftSummaryFilter) {
    setShiftSummaryFilter((current) => (current === filter ? "ALL" : filter));
    setDepartureOffset(0);
  }

  function clearDepartureProfileFilters() {
    setDepartureConfidenceFilter("ALL");
    setShiftSummaryFilter("ALL");
    setDepartureProfileSearch("");
    setDepartureOffset(0);
  }

  function updateDepartureProfileSearch(value: string) {
    setDepartureProfileSearch(value);
    setDepartureOffset(0);
  }

  function handleDepartureSort(column: DepartureSortColumn) {
    setDepartureOffset(0);
    setDepartureSortDirection((current) => (departureSortColumn === column && current === "asc" ? "desc" : "asc"));
    setDepartureSortColumn(column);
  }

  function updatePairingFilter(key: keyof PairingFilters, value: string) {
    setPairingFilters((current) => {
      const next = { ...current, [key]: value };
      if (key === "depotId") {
        next.startDate = "";
        next.endDate = "";
      }
      if (key === "rangePreset" && value !== "CUSTOM" && pairingDateAvailability?.max_date) {
        const days = Number(value);
        const end = parseIsoDate(pairingDateAvailability.max_date);
        next.endDate = pairingDateAvailability.max_date;
        next.startDate = isoDateFromDate(addDays(end, -(days - 1)));
      }
      if ((key === "startDate" || key === "endDate") && current.rangePreset !== "CUSTOM") {
        next.rangePreset = "CUSTOM";
      }
      return next;
    });
    if (key === "depotId") {
      setPairingDateAvailability(null);
      setSelectedPairingSpbuId(null);
      setSelectedPairingPair(null);
      setSavedPairingConfigOffset(0);
      setSelectedSavedPairingConfigId("");
      setPairingConfigMessage("");
    }
  }

  async function applyPairingFilters() {
    setPairingOffset(0);
    setSelectedPairingSpbuId(null);
    setSelectedPairingPair(null);
    setPairingConfigMessage("");
    await fetchPairingAnalysis(0, pairingFilters, null, null);
  }

  function handlePairingSort(column: PairingSortColumn) {
    setPairingOffset(0);
    setPairingSortDirection((current) => (pairingSortColumn === column && current === "asc" ? "desc" : "asc"));
    setPairingSortColumn(column);
  }

  function selectPairingSpbu(spbuId: string | null) {
    setSelectedPairingSpbuId(spbuId);
    if (appliedPairingFilters) {
      fetchPairingAnalysis(0, appliedPairingFilters, spbuId, selectedPairingPair);
    }
  }

  function selectPairingPair(row: PairingPair) {
    const nextPair = { spbu_a_id: row.spbu_a_id, spbu_b_id: row.spbu_b_id };
    setSelectedPairingPair(nextPair);
    setSelectedPairingSpbuId(row.spbu_a_id);
    if (appliedPairingFilters) {
      fetchPairingAnalysis(pairingOffset, appliedPairingFilters, row.spbu_a_id, nextPair);
    }
  }

  function openSavePairingConfigModal() {
    if (!pairingAnalysis || !appliedPairingFilters) {
      setError("Run Phase 3 analysis before saving a pairing analysis configuration.");
      setPairingConfigMessage("");
      return;
    }
    setPairingSaveName("");
    setPairingSaveModalOpen(true);
    setError(null);
  }

  function openLoadPairingConfigModal() {
    if (savedPairingConfigs.length === 0) {
      setError("No saved pairing analysis configuration is available.");
      setPairingConfigMessage("");
      return;
    }
    setSelectedSavedPairingConfigId((current) => current || savedPairingConfigs[0]?.id || "");
    setPairingLoadModalOpen(true);
    setError(null);
  }

  async function savePairingConfig() {
    if (!pairingAnalysis || !appliedPairingFilters) return;
    const name = pairingSaveName.trim();
    if (!name) {
      setError("Configuration name is required.");
      return;
    }
    setSavedPairingConfigLoading(true);
    setError(null);
    try {
      const saved = await apiSend<SavedPairingAnalysisConfig>("/api/v1/pairing-intelligence/saved-configurations", "POST", {
        name,
        depot_id: appliedPairingFilters.depotId,
        start_date: appliedPairingFilters.startDate,
        end_date: appliedPairingFilters.endDate,
        product_id: appliedPairingFilters.productId || null,
        search: appliedPairingFilters.search,
        sort_column: pairingSortColumn,
        sort_direction: pairingSortDirection,
        ui_state: {
          range_preset: appliedPairingFilters.rangePreset,
          pairing_offset: pairingOffset,
          pairing_limit: pairingLimit,
          pairing_sort_column: pairingSortColumn,
          pairing_sort_direction: pairingSortDirection,
          selected_pairing_spbu_id: selectedPairingSpbuId,
          evidence_spbu_a_id: selectedPairingPair?.spbu_a_id ?? null,
          evidence_spbu_b_id: selectedPairingPair?.spbu_b_id ?? null
        },
        pairing_analysis_snapshot: pairingAnalysis
      });
      setPairingConfigMessage(`Saved pairing analysis configuration: ${saved.name}.`);
      setPairingSaveModalOpen(false);
      setPairingSaveName("");
      setSavedPairingConfigOffset(0);
      await fetchSavedPairingConfigs(0, savedPairingConfigLimit);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save pairing analysis configuration");
    } finally {
      setSavedPairingConfigLoading(false);
    }
  }

  async function loadPairingConfig() {
    if (!selectedSavedPairingConfigId) {
      setError("Select a saved pairing analysis configuration to load.");
      return;
    }
    setSavedPairingConfigLoading(true);
    setError(null);
    try {
      const saved = await apiGet<SavedPairingAnalysisConfig>(`/api/v1/pairing-intelligence/saved-configurations/${encodeURIComponent(selectedSavedPairingConfigId)}`);
      const pairingSnapshot = saved.pairing_analysis_snapshot;
      if (!pairingSnapshot) {
        throw new Error("Saved configuration does not contain a pairing analysis snapshot.");
      }
      const uiState = saved.ui_state ?? {};
      const nextFilters: PairingFilters = {
        depotId: saved.depot_id,
        rangePreset: (uiState.range_preset as PairingFilters["rangePreset"]) ?? "CUSTOM",
        startDate: saved.start_date,
        endDate: saved.end_date,
        productId: saved.product_id ?? "",
        search: saved.search ?? ""
      };
      const nextPair = uiState.evidence_spbu_a_id && uiState.evidence_spbu_b_id
        ? { spbu_a_id: String(uiState.evidence_spbu_a_id), spbu_b_id: String(uiState.evidence_spbu_b_id) }
        : pairingSnapshot.evidence.pair
          ? { spbu_a_id: pairingSnapshot.evidence.pair.spbu_a_id, spbu_b_id: pairingSnapshot.evidence.pair.spbu_b_id }
          : null;
      setPairingFilters(nextFilters);
      setAppliedPairingFilters(nextFilters);
      setPairingSortColumn((uiState.pairing_sort_column as PairingSortColumn) ?? (saved.sort_column as PairingSortColumn) ?? "evidence_strength");
      setPairingSortDirection((uiState.pairing_sort_direction as CrudSortDirection) ?? (saved.sort_direction as CrudSortDirection) ?? "desc");
      setPairingLimit(Number(uiState.pairing_limit ?? pairingSnapshot.limit ?? 25));
      setPairingOffset(Number(uiState.pairing_offset ?? pairingSnapshot.offset ?? 0));
      setSelectedPairingSpbuId(String(uiState.selected_pairing_spbu_id ?? pairingSnapshot.detail?.spbu_id ?? "") || null);
      setSelectedPairingPair(nextPair);
      setPairingAnalysis(pairingSnapshot);
      setPairingConfigMessage(`Loaded pairing analysis configuration: ${saved.name}.`);
      setPairingLoadModalOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load pairing analysis configuration");
    } finally {
      setSavedPairingConfigLoading(false);
    }
  }

  async function deleteSavedPairingConfig(config: SavedPairingAnalysisConfig) {
    if (!window.confirm(`Delete saved pairing analysis configuration "${config.name}"?`)) return;
    setSavedPairingConfigLoading(true);
    setError(null);
    try {
      await apiSend<{ status: string }>(`/api/v1/pairing-intelligence/saved-configurations/${encodeURIComponent(config.id)}`, "DELETE");
      setPairingConfigMessage(`Deleted pairing analysis configuration: ${config.name}.`);
      setSelectedSavedPairingConfigId((current) => (current === config.id ? "" : current));
      const nextOffset = savedPairingConfigs.length === 1 ? Math.max(0, savedPairingConfigOffset - savedPairingConfigLimit) : savedPairingConfigOffset;
      setSavedPairingConfigOffset(nextOffset);
      await fetchSavedPairingConfigs(nextOffset, savedPairingConfigLimit);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete pairing analysis configuration");
    } finally {
      setSavedPairingConfigLoading(false);
    }
  }

  function updateShiftConfig(index: number, key: keyof OperationalShiftConfig, value: string) {
    setShiftConfigs((current) => current.map((shift, shiftIndex) => (shiftIndex === index ? { ...shift, [key]: value } : shift)));
  }

  function addShiftConfig() {
    setShiftConfigs((current) => [
      ...current,
      { shift_id: `shift_${current.length + 1}`, name: `Shift ${current.length + 1}`, start_time: "00:00", end_time: "23:59" }
    ]);
  }

  function removeShiftConfig(index: number) {
    setShiftConfigs((current) => current.filter((_, shiftIndex) => shiftIndex !== index));
  }

  function openSaveShiftConfigModal() {
    if (!departureAnalysis || !shiftAnalysis || !appliedDepartureFilters) {
      setError("Run Phase 2 analysis before saving a shift analysis configuration.");
      setShiftConfigMessage("");
      return;
    }
    const validationErrors = validateOperationalShifts(shiftConfigs);
    if (validationErrors.length > 0) {
      setError(validationErrors[0]);
      setShiftConfigMessage("");
      return;
    }
    setShiftSaveName("");
    setShiftSaveModalOpen(true);
    setError(null);
  }

  function openLoadShiftConfigModal() {
    if (savedShiftConfigs.length === 0) {
      setError("No saved shift analysis configuration is available.");
      setShiftConfigMessage("");
      return;
    }
    setSelectedSavedShiftConfigId((current) => current || savedShiftConfigs[0]?.id || "");
    setShiftLoadModalOpen(true);
    setError(null);
  }

  async function saveShiftConfig() {
    if (!departureAnalysis || !shiftAnalysis || !appliedDepartureFilters) return;
    const name = shiftSaveName.trim();
    if (!name) {
      setError("Configuration name is required.");
      return;
    }
    setSavedShiftConfigLoading(true);
    setError(null);
    try {
      const saved = await apiSend<SavedShiftAnalysisConfig>("/api/v1/departure-intelligence/saved-shift-configurations", "POST", {
        name,
        depot_id: appliedDepartureFilters.depotId,
        start_date: appliedDepartureFilters.startDate,
        end_date: appliedDepartureFilters.endDate,
        bucket_minutes: Number(appliedDepartureFilters.bucketMinutes),
        search: appliedDepartureFilters.search,
        sort_column: departureSortColumn,
        sort_direction: departureSortDirection,
        assignment_method: shiftMethod,
        shift_config: shiftConfigs,
        ui_state: {
          departure_offset: departureOffset,
          departure_limit: departureLimit,
          departure_sort_column: departureSortColumn,
          departure_sort_direction: departureSortDirection,
          departure_confidence_filter: departureConfidenceFilter,
          shift_summary_filter: shiftSummaryFilter,
          departure_profile_search: departureProfileSearch
        },
        departure_analysis_snapshot: departureAnalysis,
        shift_analysis_snapshot: shiftAnalysis
      });
      setShiftConfigMessage(`Saved shift analysis configuration: ${saved.name}.`);
      setShiftSaveModalOpen(false);
      setShiftSaveName("");
      setSavedShiftConfigOffset(0);
      await fetchSavedShiftConfigs(0, savedShiftConfigLimit);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save shift analysis configuration");
    } finally {
      setSavedShiftConfigLoading(false);
    }
  }

  async function loadShiftConfig() {
    if (!selectedSavedShiftConfigId) {
      setError("Select a saved shift analysis configuration to load.");
      return;
    }
    setSavedShiftConfigLoading(true);
    setError(null);
    try {
      const saved = await apiGet<SavedShiftAnalysisConfig>(`/api/v1/departure-intelligence/saved-shift-configurations/${encodeURIComponent(selectedSavedShiftConfigId)}`);
      const departureSnapshot = saved.departure_analysis_snapshot;
      const shiftSnapshot = saved.shift_analysis_snapshot;
      if (!departureSnapshot || !shiftSnapshot) {
        throw new Error("Saved configuration does not contain complete analysis snapshots.");
      }
      const uiState = saved.ui_state ?? {};
      const nextFilters = {
        depotId: saved.depot_id,
        startDate: saved.start_date,
        endDate: saved.end_date,
        bucketMinutes: String(saved.bucket_minutes),
        search: saved.search ?? ""
      };
      setDepartureFilters(nextFilters);
      setAppliedDepartureFilters(nextFilters);
      setShiftConfigs(saved.shift_config ?? defaultShiftConfig);
      setShiftMethod(saved.assignment_method);
      setDepartureSortColumn((uiState.departure_sort_column as DepartureSortColumn) ?? (saved.sort_column as DepartureSortColumn) ?? "observation_count");
      setDepartureSortDirection((uiState.departure_sort_direction as CrudSortDirection) ?? (saved.sort_direction as CrudSortDirection) ?? "desc");
      setDepartureConfidenceFilter((uiState.departure_confidence_filter as DepartureConfidenceFilter) ?? "ALL");
      setShiftSummaryFilter((uiState.shift_summary_filter as ShiftSummaryFilter) ?? "ALL");
      setDepartureProfileSearch(String(uiState.departure_profile_search ?? ""));
      setDepartureLimit(Number(uiState.departure_limit ?? departureSnapshot.limit ?? 25));
      setDepartureOffset(Number(uiState.departure_offset ?? departureSnapshot.offset ?? 0));
      setDepartureAnalysis(departureSnapshot);
      setShiftAnalysis(shiftSnapshot);
      setSelectedDepartureSpbuId(departureSnapshot.profiles[0]?.spbu_id ?? null);
      setShiftConfigMessage(`Loaded shift analysis configuration: ${saved.name}.`);
      setShiftLoadModalOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load shift analysis configuration");
    } finally {
      setSavedShiftConfigLoading(false);
    }
  }

  async function deleteSavedShiftConfig(config: SavedShiftAnalysisConfig) {
    if (!window.confirm(`Delete saved shift analysis configuration "${config.name}"?`)) return;
    setSavedShiftConfigLoading(true);
    setError(null);
    try {
      await apiSend<{ status: string }>(`/api/v1/departure-intelligence/saved-shift-configurations/${encodeURIComponent(config.id)}`, "DELETE");
      setShiftConfigMessage(`Deleted shift analysis configuration: ${config.name}.`);
      setSelectedSavedShiftConfigId((current) => (current === config.id ? "" : current));
      const nextOffset = savedShiftConfigs.length === 1 ? Math.max(0, savedShiftConfigOffset - savedShiftConfigLimit) : savedShiftConfigOffset;
      setSavedShiftConfigOffset(nextOffset);
      await fetchSavedShiftConfigs(nextOffset, savedShiftConfigLimit);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete shift analysis configuration");
    } finally {
      setSavedShiftConfigLoading(false);
    }
  }

  function handleTagSort(column: string) {
    setTagOffset(0);
    setTagSortDirection((current) => (tagSortColumn === column && current === "asc" ? "desc" : "asc"));
    setTagSortColumn(column);
  }

  function handleMismatchRowsPerPage(value: string) {
    setMismatchRowsPerPage(Number(value));
    setSpbuMismatchPage(0);
    setMtMismatchPage(0);
  }

  function handleSpbuMismatchSort(column: MismatchSortColumn) {
    setSpbuMismatchPage(0);
    setSpbuMismatchSortDirection((current) => (spbuMismatchSortColumn === column && current === "asc" ? "desc" : "asc"));
    setSpbuMismatchSortColumn(column);
  }

  function handleMtMismatchSort(column: MismatchSortColumn) {
    setMtMismatchPage(0);
    setMtMismatchSortDirection((current) => (mtMismatchSortColumn === column && current === "asc" ? "desc" : "asc"));
    setMtMismatchSortColumn(column);
  }

  function toggleCrudRowSelection(recordId: string) {
    setSelectedCrudIds((current) => {
      const next = new Set(current);
      if (next.has(recordId)) {
        next.delete(recordId);
      } else {
        next.add(recordId);
      }
      return next;
    });
  }

  function toggleVisibleCrudSelection() {
    setSelectedCrudIds((current) => {
      const next = new Set(current);
      if (allVisibleCrudRowsSelected) {
        visibleCrudIds.forEach((recordId) => next.delete(recordId));
      } else {
        visibleCrudIds.forEach((recordId) => next.add(recordId));
      }
      return next;
    });
  }

  function navigate(page: Page) {
    const path =
      page === "restricted-roads" ? "/master-data/restricted-roads" : page === "master-data"
        ? "/master-data"
        : page === "tag-consistency"
          ? "/tag-consistency"
          : page === "departure-intelligence"
            ? "/departure-intelligence"
            : page === "pairing-intelligence"
              ? "/pairing-intelligence"
              : page === "affinity-intelligence"
                ? "/affinity-intelligence"
                : page === "machine-learning-intelligence"
                  ? "/machine-learning-intelligence"
                  : page === "prediction-assignment"
                    ? "/prediction-assignment"
                    : page === "phase7-optimization"
                      ? "/phase7-optimization"
                    : page === "manual-dispatch"
                      ? "/phase-8/manual-dispatch"
                    : page === "route-model-alignment"
                      ? "/phase9/route-model-alignment"
                    : page === "amt-scheduler-connector"
                      ? "/phase10/amt-scheduler-connector"
                    : page === "google-maps-integration"
                      ? "/settings/google-maps-integration"
                      : page === "documentation"
                        ? "/documentation"
              : "/";
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
    setCurrentPage(page);
    setMobileSidebarOpen(false);
  }

  function toggleSidebarCollapsed() {
    setSidebarCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("dispatch-sidebar-collapsed", String(next));
      return next;
    });
  }

  const activePageMetadata = pageMetadata[currentPage];

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-is-collapsed" : ""}`}>
      <AppSidebar
        currentPage={currentPage}
        collapsed={sidebarCollapsed}
        mobileOpen={mobileSidebarOpen}
        onNavigate={navigate}
        onToggleCollapsed={toggleSidebarCollapsed}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      <main className="app-main min-h-screen bg-transparent text-petroink">
        <header className="app-topbar">
          <div className="app-topbar-left">
            <button
              type="button"
              className="mobile-menu-button"
              onClick={() => setMobileSidebarOpen(true)}
              aria-label="Open navigation menu"
            >
              <Menu size={20} />
            </button>
            <div className="topbar-context">
              <span>Dispatch Intelligence</span>
              <strong>{activePageMetadata.title}</strong>
            </div>
          </div>
          <div className="app-topbar-actions">
            <label className="topbar-depot-selector">
              <span>Depot Aktif</span>
              <select aria-label="Depot aktif" value={activeDepotId} disabled={uploading} onChange={(event) => onDepotChange(event.target.value)}>
                {!activeDepotId && <option value="">Pilih depot</option>}
                {allDepots.filter((depot) => depot.active_status === "ACTIVE").map((depot) => <option key={depot.depot_id} value={depot.depot_id}>{depot.depot_name}</option>)}
              </select>
            </label>
            <button
              type="button"
              className="topbar-settings-button"
              onClick={() => navigate("google-maps-integration")}
            >
              <MapPinned size={18} />
              <span>Google Maps Settings</span>
            </button>
            <div className="topbar-profile" aria-label="Current workspace profile">
              <span className="topbar-avatar"><UserCircle size={22} /></span>
              <span className="topbar-profile-copy">
                <strong>Petrofin</strong>
                <small>Operations</small>
              </span>
            </div>
          </div>
        </header>

        <div className="app-content mx-auto max-w-[1600px] px-5 py-5 lg:px-7 lg:py-6">
          {currentPage !== "documentation" && (
            <section className="app-page-intro">
              <div className="app-page-eyebrow">{activePageMetadata.eyebrow}</div>
              <h1>{activePageMetadata.title}</h1>
              <p>{activePageMetadata.description}</p>
            </section>
          )}
        {error && <div className="mb-4 border border-rust bg-white px-4 py-3 text-sm text-rust">{error}</div>}
        {!activeDepotId && <div className="mb-4 border border-line bg-white px-4 py-3 text-sm">Belum ada depot aktif. Buat depot terlebih dahulu untuk mulai mengunggah data dan membuka analisis. <button className="ml-2 font-semibold text-ocean underline" onClick={() => { navigate("master-data"); changeCrudDomain("DEPOT"); }}>Kelola Depot</button></div>}
        {shiftHelpOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 px-4">
            <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto border border-line bg-white p-5 shadow-card">
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Shift Assignment Method</div>
                  <div className="mt-1 text-xs text-slate-500">Historical and descriptive only. Hybrid does not create an optimized shift schedule.</div>
                </div>
                <button className="inline-flex h-8 w-8 items-center justify-center border border-line" onClick={() => setShiftHelpOpen(false)} title="Close help">
                  <X size={16} />
                </button>
              </div>
              <div className="grid gap-4 text-sm text-slate-700">
                <div className="border border-line p-3">
                  <div className="font-semibold text-petroink">Dominant Shift</div>
                  <p className="mt-1">Assigns an SPBU to the shift containing the largest percentage of its historical shipment departures.</p>
                  <p className="mt-1 text-xs text-slate-500">Example: Shift 1 = 70%, Shift 2 = 20%, Shift 3 = 8%, Shift 4 = 2%. Result: Primary Historical Shift = Shift 1.</p>
                  <p className="mt-1 text-xs text-slate-500">Best for a simple operational view when one shift clearly dominates historical data.</p>
                </div>
                <div className="border border-line p-3">
                  <div className="font-semibold text-petroink">Median-Based</div>
                  <p className="mt-1">Assigns an SPBU to the shift containing its historical median departure time, or P50.</p>
                  <p className="mt-1 text-xs text-slate-500">Example: Historical Median Departure = 07:15 and Shift 2 = 06:00-11:59. Result: Primary Historical Shift = Shift 2.</p>
                  <p className="mt-1 text-xs text-slate-500">This is robust to isolated extreme departure times, but it can hide multi-shift behavior.</p>
                </div>
                <div className="border border-line p-3">
                  <div className="font-semibold text-petroink">Hybrid / Confidence-Aware</div>
                  <p className="mt-1">Combines historical shift share, median departure, preferred-window overlap, peak departure time, observation count, and Phase 2 confidence.</p>
                  <p className="mt-1 text-xs text-slate-500">The system treats assignment as strong only when several historical signals point toward the same shift.</p>
                  <p className="mt-1 text-xs text-slate-500">When behavior is split or the sample is too small, the SPBU may be marked MODERATE, AMBIGUOUS, or INSUFFICIENT DATA.</p>
                </div>
                <div className="border border-line bg-slate-50 p-3 text-xs">
                  <div className="font-semibold uppercase tracking-wide text-slate-500">Recommended usage</div>
                  <div className="mt-2 grid gap-1">
                    <div>Dominant Shift: simplest operational view.</div>
                    <div>Median-Based: robust single-point historical classification.</div>
                    <div>Hybrid / Confidence-Aware: recommended when a more reliable historical classification is required.</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
        {shiftSaveModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 px-4">
            <div className="w-full max-w-lg border border-line bg-white p-5 shadow-card">
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Save Shift Analysis Configuration</div>
                  <div className="mt-1 text-xs text-slate-500">The current shift configuration and analysis result will be stored in the backend.</div>
                </div>
                <button className="inline-flex h-8 w-8 items-center justify-center border border-line" onClick={() => setShiftSaveModalOpen(false)} title="Close save configuration">
                  <X size={16} />
                </button>
              </div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
                Configuration Name
                <input
                  className="mt-2 w-full border border-line px-3 py-2 text-sm normal-case tracking-normal"
                  value={shiftSaveName}
                  onChange={(event) => setShiftSaveName(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") void saveShiftConfig(); }}
                  autoFocus
                  placeholder="Example: Medan 4 shift baseline"
                />
              </label>
              <div className="mt-5 flex items-center justify-end gap-2">
                <button className="border border-line px-3 py-2 text-sm" onClick={() => setShiftSaveModalOpen(false)}>Cancel</button>
                <button className="inline-flex items-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={() => void saveShiftConfig()} disabled={savedShiftConfigLoading || !shiftSaveName.trim()}>
                  <Save size={14} /> Save
                </button>
              </div>
            </div>
          </div>
        )}
        {shiftLoadModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 px-4">
            <div className="w-full max-w-xl border border-line bg-white p-5 shadow-card">
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Load Shift Analysis Configuration</div>
                  <div className="mt-1 text-xs text-slate-500">Loading restores the saved shift configuration and analysis snapshot.</div>
                </div>
                <button className="inline-flex h-8 w-8 items-center justify-center border border-line" onClick={() => setShiftLoadModalOpen(false)} title="Close load configuration">
                  <X size={16} />
                </button>
              </div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
                Saved Configuration
                <select
                  className="mt-2 w-full border border-line bg-white px-3 py-2 text-sm normal-case tracking-normal"
                  value={selectedSavedShiftConfigId}
                  onChange={(event) => setSelectedSavedShiftConfigId(event.target.value)}
                >
                  {savedShiftConfigs.map((config) => (
                    <option key={config.id} value={config.id}>
                      {config.name} | {config.depot_name ?? config.depot_id} | {formatDate(config.start_date)} - {formatDate(config.end_date)}
                    </option>
                  ))}
                </select>
              </label>
              <div className="mt-5 flex items-center justify-end gap-2">
                <button className="border border-line px-3 py-2 text-sm" onClick={() => setShiftLoadModalOpen(false)}>Cancel</button>
                <button className="inline-flex items-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={() => void loadShiftConfig()} disabled={savedShiftConfigLoading || !selectedSavedShiftConfigId}>
                  <RefreshCw size={14} /> Load
                </button>
              </div>
            </div>
          </div>
        )}
        {pairingSaveModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 px-4">
            <div className="w-full max-w-lg border border-line bg-white p-5 shadow-card">
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Save Pairing Analysis Configuration</div>
                  <div className="mt-1 text-xs text-slate-500">The current Phase 3 filters and pairing analysis snapshot will be stored in the backend.</div>
                </div>
                <button className="inline-flex h-8 w-8 items-center justify-center border border-line" onClick={() => setPairingSaveModalOpen(false)} title="Close save configuration">
                  <X size={16} />
                </button>
              </div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
                Configuration Name
                <input
                  className="mt-2 w-full border border-line px-3 py-2 text-sm normal-case tracking-normal"
                  value={pairingSaveName}
                  onChange={(event) => setPairingSaveName(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") void savePairingConfig(); }}
                  autoFocus
                  placeholder="Example: Medan pairing baseline"
                />
              </label>
              <div className="mt-5 flex items-center justify-end gap-2">
                <button className="border border-line px-3 py-2 text-sm" onClick={() => setPairingSaveModalOpen(false)}>Cancel</button>
                <button className="inline-flex items-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={() => void savePairingConfig()} disabled={savedPairingConfigLoading || !pairingSaveName.trim()}>
                  <Save size={14} /> Save
                </button>
              </div>
            </div>
          </div>
        )}
        {pairingLoadModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 px-4">
            <div className="w-full max-w-xl border border-line bg-white p-5 shadow-card">
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Load Pairing Analysis Configuration</div>
                  <div className="mt-1 text-xs text-slate-500">Loading restores the saved Phase 3 filters and pairing analysis snapshot.</div>
                </div>
                <button className="inline-flex h-8 w-8 items-center justify-center border border-line" onClick={() => setPairingLoadModalOpen(false)} title="Close load configuration">
                  <X size={16} />
                </button>
              </div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
                Saved Configuration
                <select
                  className="mt-2 w-full border border-line bg-white px-3 py-2 text-sm normal-case tracking-normal"
                  value={selectedSavedPairingConfigId}
                  onChange={(event) => setSelectedSavedPairingConfigId(event.target.value)}
                >
                  {savedPairingConfigs.map((config) => (
                    <option key={config.id} value={config.id}>
                      {config.name} | {config.depot_name ?? config.depot_id} | {formatDate(config.start_date)} - {formatDate(config.end_date)}
                    </option>
                  ))}
                </select>
              </label>
              <div className="mt-5 flex items-center justify-end gap-2">
                <button className="border border-line px-3 py-2 text-sm" onClick={() => setPairingLoadModalOpen(false)}>Cancel</button>
                <button className="inline-flex items-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={() => void loadPairingConfig()} disabled={savedPairingConfigLoading || !selectedSavedPairingConfigId}>
                  <RefreshCw size={14} /> Load
                </button>
              </div>
            </div>
          </div>
        )}
        {!hasData && (
          <section className="mb-5 border border-line bg-white p-5">
            <div className="flex items-start gap-3">
              <Database className="mt-1 text-mint" />
              <div>
                <h2 className="text-lg font-semibold">No canonical data loaded</h2>
                <p className="mt-1 text-sm text-slate-600">Use the import action to stage, validate, normalize, and publish the provided MT, SPBU, and LO workbooks.</p>
              </div>
            </div>
          </section>
        )}

        {currentPage === "affinity-intelligence" && depots.length > 0 && (
          <AffinityIntelligencePage depots={depots} products={products} />
        )}

        {currentPage === "machine-learning-intelligence" && depots.length > 0 && (
          <MachineLearningIntelligencePage depots={depots} />
        )}

        {currentPage === "prediction-assignment" && depots.length > 0 && (
          <PredictionAssignmentPage depots={depots} products={products} />
        )}

        {currentPage === "phase7-optimization" && depots.length > 0 && (
          <Phase7OptimizationPage depots={depots} products={products} />
        )}

        {currentPage === "manual-dispatch" && depots.length > 0 && (
          <ManualDispatchPage depots={depots} />
        )}

        {currentPage === "route-model-alignment" && depots.length > 0 && (
          <RouteModelAlignmentPage depots={depots} />
        )}

        {currentPage === "amt-scheduler-connector" && depots.length > 0 && (
          <AmtSchedulerConnectorPage depots={depots} />
        )}

        {currentPage === "google-maps-integration" && (
          <GoogleMapsIntegrationPage />
        )}

        {currentPage === "documentation" && (
          <DocumentationPage onNavigate={navigate} />
        )}

        {currentPage === "pairing-intelligence" && (
        <>
        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Phase 3 - SPBU Pairing Probability Intelligence</div>
              <div className="mt-1 text-xs text-slate-500">Same-shipment SPBU pairing. Consecutive GPS transition is kept as separate directional evidence.</div>
            </div>
            <div className="flex flex-col items-start gap-2 lg:items-end">
              <div className="flex flex-wrap gap-2">
                <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50" onClick={openLoadPairingConfigModal} disabled={savedPairingConfigLoading || savedPairingConfigTotal === 0} title="Load a saved pairing analysis configuration">
                  <RefreshCw size={14} /> Load
                </button>
                <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50" onClick={openSavePairingConfigModal} disabled={pairingLoading || !pairingAnalysis} title="Save current pairing configuration and analysis result">
                  <Save size={14} /> Save
                </button>
              </div>
              {pairingConfigMessage && <div className="text-xs text-slate-500">{pairingConfigMessage}</div>}
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-[1.4fr_0.7fr_0.8fr_0.8fr_1fr_1fr_auto]">
            <select className="border border-line bg-white px-3 py-2 text-sm" value={pairingFilters.depotId} onChange={(event) => updatePairingFilter("depotId", event.target.value)} title="Depot">

              {depots.map((depot) => (
                <option key={depot.depot_id} value={depot.depot_id}>{depot.depot_name}</option>
              ))}
            </select>
            <select className="border border-line bg-white px-3 py-2 text-sm" value={pairingFilters.rangePreset} onChange={(event) => updatePairingFilter("rangePreset", event.target.value)} disabled={!pairingFilters.depotId || pairingDateLoading} title="Date range preset">
              <option value="7">7 Days</option>
              <option value="14">14 Days</option>
              <option value="30">30 Days</option>
              <option value="CUSTOM">Custom Range</option>
            </select>
            <input className="border border-line px-3 py-2 text-sm" type="date" value={pairingFilters.startDate} onChange={(event) => updatePairingFilter("startDate", event.target.value)} disabled={!pairingFilters.depotId || pairingDateLoading} title="Start date" />
            <input className="border border-line px-3 py-2 text-sm" type="date" value={pairingFilters.endDate} onChange={(event) => updatePairingFilter("endDate", event.target.value)} disabled={!pairingFilters.depotId || pairingDateLoading} title="End date" />
            <select className="border border-line bg-white px-3 py-2 text-sm" value={pairingFilters.productId} onChange={(event) => updatePairingFilter("productId", event.target.value)} title="Product">
              <option value="">All Products</option>
              {products.map((product) => (
                <option key={product.product_id} value={product.product_id}>{product.product_name}</option>
              ))}
            </select>
            <input
              className="border border-line px-3 py-2 text-sm"
              value={pairingFilters.search}
              onChange={(event) => updatePairingFilter("search", event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") applyPairingFilters(); }}
              placeholder="Search SPBU pair"
              title="Search SPBU pair"
            />
            <button className="inline-flex items-center justify-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={applyPairingFilters} disabled={pairingLoading} title="Run SPBU pairing analysis">
              <Search size={16} />
              {pairingLoading ? "Running" : "Apply"}
            </button>
          </div>
          <div className="mt-3 text-xs text-slate-500">
            {pairingDateAvailability?.min_date && pairingDateAvailability?.max_date
              ? `Available shipment dates: ${formatDate(pairingDateAvailability.min_date)} - ${formatDate(pairingDateAvailability.max_date)}.`
              : pairingFilters.depotId
                ? "Date availability will load for the selected depot."
                : "Choose a depot before running analysis."}
          </div>
          <div className="mt-4 border border-line">
            <div className="flex flex-col gap-2 border-b border-line bg-slate-50 px-3 py-2 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Saved SPBU Pairing Analysis Configurations</div>
                <div className="mt-1 text-xs text-slate-500">Showing {savedPairingConfigShowingStart}-{savedPairingConfigShowingEnd} of {savedPairingConfigTotal.toLocaleString()}</div>
              </div>
              <select className="border border-line bg-white px-2 py-1 text-xs" value={savedPairingConfigLimit} onChange={(event) => { setSavedPairingConfigOffset(0); setSavedPairingConfigLimit(Number(event.target.value)); }} title="Saved configurations per page">
                <option value={5}>5 rows</option>
                <option value={10}>10 rows</option>
                <option value={25}>25 rows</option>
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="whitespace-nowrap px-3 py-2">Name</th>
                    <th className="whitespace-nowrap px-3 py-2">Depot</th>
                    <th className="whitespace-nowrap px-3 py-2">Period</th>
                    <th className="whitespace-nowrap px-3 py-2">Product</th>
                    <th className="whitespace-nowrap px-3 py-2">Pairs</th>
                    <th className="whitespace-nowrap px-3 py-2">Saved</th>
                    <th className="whitespace-nowrap px-3 py-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {savedPairingConfigs.map((config) => (
                    <tr key={config.id} className="border-b border-line">
                      <td className="whitespace-nowrap px-3 py-2 font-medium">{config.name}</td>
                      <td className="whitespace-nowrap px-3 py-2">{config.depot_name ?? config.depot_id}</td>
                      <td className="whitespace-nowrap px-3 py-2">{formatDate(config.start_date)} - {formatDate(config.end_date)}</td>
                      <td className="whitespace-nowrap px-3 py-2">{config.product_name}</td>
                      <td className="whitespace-nowrap px-3 py-2">{config.unique_spbu_pairs.toLocaleString()}</td>
                      <td className="whitespace-nowrap px-3 py-2">{formatDateTime(config.updated_at)}</td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <button className="inline-flex items-center justify-center border border-line px-2 py-1 text-xs text-rust disabled:opacity-50" onClick={() => deleteSavedPairingConfig(config)} disabled={savedPairingConfigLoading} title="Delete saved configuration">
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {savedPairingConfigs.length === 0 && (
                    <tr><td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={7}>No saved pairing analysis configuration.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setSavedPairingConfigOffset(Math.max(0, savedPairingConfigOffset - savedPairingConfigLimit))} disabled={!canPreviousSavedPairingConfigPage}>Previous</button>
              <span className="text-slate-500">Page {savedPairingConfigPageNumber} of {savedPairingConfigPageCount}</span>
              <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setSavedPairingConfigOffset(savedPairingConfigOffset + savedPairingConfigLimit)} disabled={!canNextSavedPairingConfigPage}>Next</button>
            </div>
          </div>
        </section>

        {!pairingAnalysis && (
          <section className="border border-line bg-white p-8 text-center">
            <div className="mx-auto max-w-2xl text-sm text-slate-600">
              Select a depot, date range, and product scope, then click Apply to run SPBU Pairing Probability Intelligence.
            </div>
          </section>
        )}

        {pairingAnalysis && pairingSummary && (
        <>
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          {[
            ["Total Shipments", pairingSummary.total_shipments.toLocaleString()],
            ["Multi-SPBU Shipments", pairingSummary.multi_spbu_shipments.toLocaleString()],
            ["Unique SPBU", pairingSummary.unique_spbu.toLocaleString()],
            ["Unique SPBU Pairs", pairingSummary.unique_spbu_pairs.toLocaleString()],
            ["High-Confidence Pairs", pairingSummary.high_confidence_pairs.toLocaleString()],
            ["Avg SPBU / Shipment", formatMetric(pairingSummary.average_spbu_per_shipment)]
          ].map(([label, value]) => (
            <div key={label} className="border border-line bg-white p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
              <div className="mt-2 text-2xl font-semibold">{value}</div>
            </div>
          ))}
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-3">
          <div className="border border-line bg-white p-4">
            <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Data Quality</div>
            <div className="grid gap-3 text-sm">
              <div className="flex items-center justify-between border-b border-line pb-2"><span>Source Shipments</span><span className="font-semibold">{pairingAnalysis.data_quality.source_shipments.toLocaleString()}</span></div>
              <div className="flex items-center justify-between border-b border-line pb-2"><span>Eligible Shipments</span><span className="font-semibold">{pairingAnalysis.data_quality.eligible_shipments.toLocaleString()}</span></div>
              <div className="flex items-center justify-between border-b border-line pb-2"><span>Excluded Shipments</span><span className="font-semibold">{pairingAnalysis.data_quality.excluded_shipments.toLocaleString()}</span></div>
              <div className="grid gap-1 text-xs text-slate-500">
                {pairingAnalysis.data_quality.exclusion_reasons.length > 0
                  ? pairingAnalysis.data_quality.exclusion_reasons.map((item) => <div key={item.reason}>{item.reason}: {item.count.toLocaleString()}</div>)
                  : <div>No exclusions in the active filter.</div>}
              </div>
            </div>
          </div>
          <section className="min-h-[320px] border border-line bg-white p-4 lg:col-span-2">
            <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Pairing Probability Distribution</div>
            <ReactECharts option={{
              tooltip: { trigger: "axis" },
              grid: { top: 16, right: 16, bottom: 42, left: 48 },
              xAxis: { type: "category", data: pairingAnalysis.distribution.map((item) => item.name) },
              yAxis: { type: "value" },
              series: [{ type: "bar", data: pairingAnalysis.distribution.map((item) => item.value), itemStyle: { color: "#0b73bf" } }]
            }} style={{ height: 260 }} />
          </section>
        </section>

        <section className="mt-5 border border-line bg-white p-4">
          <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Top SPBU Pairings</div>
              <div className="mt-1 text-xs text-slate-500">Showing {pairingShowingStart}-{pairingShowingEnd} of {pairingTotal.toLocaleString()} pairs. Default ranking prioritizes evidence strength.</div>
            </div>
            <select className="border border-line bg-white px-3 py-2 text-sm" value={pairingLimit} onChange={(event) => { setPairingOffset(0); setPairingLimit(Number(event.target.value)); }} title="Rows per page">
              <option value={10}>10 rows</option>
              <option value={25}>25 rows</option>
              <option value={50}>50 rows</option>
              <option value={100}>100 rows</option>
            </select>
          </div>
          <div className="overflow-x-auto border border-line">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  {[
                    ["spbu_a_code", "SPBU A"],
                    ["spbu_a_tags", "SPBU A Tag"],
                    ["spbu_b_code", "SPBU B"],
                    ["spbu_b_tags", "SPBU B Tag"],
                    ["pair_count", "Pair Count"],
                    ["probability_b_given_a", "P(B|A)"],
                    ["probability_a_given_b", "P(A|B)"],
                    ["support", "Support"],
                    ["lift", "Lift"],
                    ["confidence_score", "Confidence"]
                  ].map(([column, label]) => (
                    <th key={column} className="whitespace-nowrap px-3 py-2">
                      {column.endsWith("_tags") ? (
                        <span>{label}</span>
                      ) : (
                        <button className="inline-flex items-center gap-1 uppercase tracking-wide" onClick={() => handlePairingSort(column as PairingSortColumn)} title={`Sort by ${label}`}>
                          <span>{label}</span>
                          {pairingSortColumn === column ? (pairingSortDirection === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />) : <ArrowUpDown size={14} className="text-slate-300" />}
                        </button>
                      )}
                    </th>
                  ))}
                  <th className="whitespace-nowrap px-3 py-2">Evidence Count</th>
                </tr>
              </thead>
              <tbody>
                {pairingRows.map((row) => (
                  <tr key={`${row.spbu_a_id}-${row.spbu_b_id}`} className="cursor-pointer border-b border-line hover:bg-petrocloud/40" onClick={() => selectPairingPair(row)}>
                    <td className="whitespace-nowrap px-3 py-2"><div className="font-medium">{row.spbu_a_code}</div><div className="text-xs text-slate-500">{row.spbu_a_name ?? "-"}</div></td>
                    <td className="min-w-48 px-3 py-2 text-xs text-slate-600">{formatTags(row.spbu_a_tags)}</td>
                    <td className="whitespace-nowrap px-3 py-2"><div className="font-medium">{row.spbu_b_code}</div><div className="text-xs text-slate-500">{row.spbu_b_name ?? "-"}</div></td>
                    <td className="min-w-48 px-3 py-2 text-xs text-slate-600">{formatTags(row.spbu_b_tags)}</td>
                    <td className="whitespace-nowrap px-3 py-2 font-semibold">{row.pair_count.toLocaleString()}</td>
                    <td className="whitespace-nowrap px-3 py-2">{formatPercent(row.probability_b_given_a)}</td>
                    <td className="whitespace-nowrap px-3 py-2">{formatPercent(row.probability_a_given_b)}</td>
                    <td className="whitespace-nowrap px-3 py-2">{formatPercent(row.support)}</td>
                    <td className="whitespace-nowrap px-3 py-2">{formatMetric(row.lift)}</td>
                    <td className="px-3 py-2"><span className={`inline-flex border px-2 py-1 text-xs font-semibold ${confidenceClass(row.confidence_level)}`}>{row.confidence_level.replace(/_/g, " ")} {formatMetric(row.confidence_score, 2)}</span></td>
                    <td className="whitespace-nowrap px-3 py-2">{row.evidence_count.toLocaleString()}</td>
                  </tr>
                ))}
                {pairingRows.length === 0 && (
                  <tr><td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={11}>No SPBU pairs match the active filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center justify-between gap-3 text-sm">
            <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setPairingOffset(Math.max(0, pairingOffset - pairingLimit))} disabled={!canPreviousPairingPage}>Previous</button>
            <span className="text-slate-500">Page {pairingPageNumber} of {pairingPageCount}</span>
            <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setPairingOffset(pairingOffset + pairingLimit)} disabled={!canNextPairingPage}>Next</button>
          </div>
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-2">
          <section className="min-h-[420px] border border-line bg-white p-4">
            <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">SPBU Pairing Matrix</div>
            {pairingMatrixOption ? <ReactECharts option={pairingMatrixOption} style={{ height: 360 }} /> : <div className="py-20 text-center text-sm text-slate-500">No matrix data.</div>}
          </section>
          <section className="min-h-[420px] border border-line bg-white p-4">
            <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Pairing Network Prototype</div>
            {pairingNetworkOption ? (
              <ReactECharts
                option={pairingNetworkOption}
                style={{ height: 360 }}
                onEvents={{ click: (params: { dataType?: string; data?: { id?: string } }) => { if (params.dataType === "node" && params.data?.id) selectPairingSpbu(params.data.id); } }}
              />
            ) : <div className="py-20 text-center text-sm text-slate-500">No network data.</div>}
          </section>
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <section className="border border-line bg-white p-4">
            <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">SPBU Pairing Detail</div>
            {selectedPairingDetail ? (
              <>
                <div className="mb-3 grid gap-3 sm:grid-cols-2">
                  <div className="border border-line p-3"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected SPBU</div><div className="mt-1 font-semibold">{selectedPairingDetail.spbu_code}</div></div>
                  <div className="border border-line p-3"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Historical Shipments</div><div className="mt-1 font-semibold">{selectedPairingDetail.historical_shipments.toLocaleString()}</div></div>
                </div>
                <div className="grid gap-2">
                  {selectedPairingDetail.top_pairs.map((row) => (
                    <button key={`${row.spbu_a_id}-${row.spbu_b_id}`} className="border border-line p-3 text-left hover:bg-petrocloud/40" onClick={() => selectPairingPair(row)} title="Open pair evidence">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="font-semibold">{row.candidate_spbu_code}</div>
                          <div className="text-xs text-slate-500">Pair Count {row.pair_count.toLocaleString()} | Lift {formatMetric(row.lift)}</div>
                        </div>
                        <span className={`border px-2 py-1 text-xs font-semibold ${confidenceClass(row.confidence_level)}`}>{row.confidence_level.replace(/_/g, " ")}</span>
                      </div>
                      <div className="mt-2 text-sm">Pair Probability {formatPercent(row.pair_probability)} | Reverse {formatPercent(row.reverse_probability)}</div>
                    </button>
                  ))}
                  {selectedPairingDetail.top_pairs.length === 0 && <div className="py-8 text-center text-sm text-slate-500">No same-shipment pair for the selected SPBU.</div>}
                </div>
              </>
            ) : (
              <div className="py-8 text-center text-sm text-slate-500">Select a pair or network node to inspect SPBU detail.</div>
            )}
          </section>
          <section className="border border-line bg-white p-4">
            <div className="mb-3 flex flex-col gap-1">
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Historical Evidence</div>
              <div className="text-xs text-slate-500">
                {pairingAnalysis.evidence.pair
                  ? `${pairingAnalysis.evidence.pair.spbu_a_code} - ${pairingAnalysis.evidence.pair.spbu_b_code}: ${pairingAnalysis.evidence.distinct_shipment_count.toLocaleString()} distinct shipments`
                  : "Select a pair to inspect evidence."}
              </div>
            </div>
            <div className="max-h-[420px] overflow-auto border border-line">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="whitespace-nowrap px-3 py-2">Date</th>
                    <th className="whitespace-nowrap px-3 py-2">Shipment</th>
                    <th className="whitespace-nowrap px-3 py-2">Vehicle</th>
                    <th className="whitespace-nowrap px-3 py-2">Gate Out</th>
                    <th className="whitespace-nowrap px-3 py-2">SPBU in Shipment</th>
                    <th className="whitespace-nowrap px-3 py-2">SPBU Tag</th>
                    <th className="whitespace-nowrap px-3 py-2">Products</th>
                    <th className="whitespace-nowrap px-3 py-2">Quantity</th>
                  </tr>
                </thead>
                <tbody>
                  {pairingAnalysis.evidence.rows.map((row) => (
                    <tr key={row.shipment_id} className="border-b border-line">
                      <td className="whitespace-nowrap px-3 py-2">{formatDate(row.date)}</td>
                      <td className="whitespace-nowrap px-3 py-2">{row.source_shipment_id}</td>
                      <td className="whitespace-nowrap px-3 py-2">{row.vehicle_registration ?? "-"}</td>
                      <td className="whitespace-nowrap px-3 py-2">{formatDateTime(row.gate_out)}</td>
                      <td className="min-w-56 px-3 py-2">{row.spbu_in_shipment.join(", ")}</td>
                      <td className="min-w-72 px-3 py-2 text-xs text-slate-600">
                        {(row.spbu_tags ?? []).length > 0 ? row.spbu_tags.map((item) => `${item.spbu_code}: ${formatTags(item.tags)}`).join(" | ") : "-"}
                      </td>
                      <td className="min-w-44 px-3 py-2">{row.products.join(", ") || "-"}</td>
                      <td className="whitespace-nowrap px-3 py-2">{formatMetric(row.quantity)}</td>
                    </tr>
                  ))}
                  {pairingAnalysis.evidence.rows.length === 0 && (
                    <tr><td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={8}>No historical evidence for the selected pair.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </section>

        <section className="mt-5 border border-line bg-white p-4">
          <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">GPS Consecutive Transition Context</div>
          <div className="mb-3 text-xs text-slate-500">Transition A to B means actual consecutive visit sequence. It is not used as same-shipment pair count.</div>
          <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-4">
            {pairingAnalysis.transitions.slice(0, 8).map((row) => (
              <div key={`${row.from_spbu_code}-${row.to_spbu_code}`} className="border border-line p-3 text-sm">
                <div className="font-semibold">{row.from_spbu_code} to {row.to_spbu_code}</div>
                <div className="mt-1 text-xs text-slate-500">{row.transition_count.toLocaleString()} transitions | {formatPercent(row.transition_probability)}</div>
              </div>
            ))}
            {pairingAnalysis.transitions.length === 0 && <div className="text-sm text-slate-500">No GPS stop sequence transitions in the active filter.</div>}
          </div>
        </section>
        </>
        )}
        </>
        )}

        {currentPage === "departure-intelligence" && (
        <>
        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Phase 2 - Depot Departure Time Intelligence</div>
              <div className="mt-1 text-xs text-slate-500">Historical depot departure behavior only. This page does not calculate arrivals, ETA, route sequence, or dispatch recommendations.</div>
            </div>
            <div className="flex flex-col items-start gap-2 lg:items-end">
              <div className="flex flex-wrap gap-2">
                <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50" onClick={openLoadShiftConfigModal} disabled={savedShiftConfigLoading || savedShiftConfigTotal === 0} title="Load a saved shift analysis configuration">
                  <RefreshCw size={14} /> Load
                </button>
                <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50" onClick={openSaveShiftConfigModal} disabled={departureLoading || shiftLoading || !departureAnalysis || !shiftAnalysis} title="Save current shift configuration and analysis result">
                  <Save size={14} /> Save
                </button>
              </div>
              {shiftConfigMessage && <div className="text-xs text-slate-500">{shiftConfigMessage}</div>}
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-[1.4fr_0.8fr_0.8fr_0.7fr_1fr_auto]">
            <select className="border border-line bg-white px-3 py-2 text-sm" value={departureFilters.depotId} onChange={(event) => updateDepartureFilter("depotId", event.target.value)} title="Depot">

              {depots.map((depot) => (
                <option key={depot.depot_id} value={depot.depot_id}>{depot.depot_name}</option>
              ))}
            </select>
            <DepartureDatePicker
              label={departureDateLoading ? "Loading dates" : "Start Date"}
              value={departureFilters.startDate}
              availableDates={departureAvailableDateSet}
              dateCounts={departureDateCountMap}
              minDate={departureDateAvailability?.min_date ?? null}
              maxDate={departureDateAvailability?.max_date ?? null}
              disabled={!departureFilters.depotId || departureDateLoading}
              onChange={(value) => updateDepartureFilter("startDate", value)}
            />
            <DepartureDatePicker
              label={departureDateLoading ? "Loading dates" : "End Date"}
              value={departureFilters.endDate}
              availableDates={departureAvailableDateSet}
              dateCounts={departureDateCountMap}
              minDate={departureDateAvailability?.min_date ?? null}
              maxDate={departureDateAvailability?.max_date ?? null}
              disabled={!departureFilters.depotId || departureDateLoading}
              onChange={(value) => updateDepartureFilter("endDate", value)}
            />
            <select className="border border-line bg-white px-3 py-2 text-sm" value={departureFilters.bucketMinutes} onChange={(event) => updateDepartureFilter("bucketMinutes", event.target.value)} title="Time bucket size">
              <option value="30">30-minute buckets</option>
              <option value="60">60-minute buckets</option>
            </select>
            <input
              className="border border-line px-3 py-2 text-sm"
              value={departureFilters.search}
              onChange={(event) => updateDepartureFilter("search", event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") applyDepartureFilters(); }}
              placeholder="Search SPBU or shipment"
              title="Search SPBU or shipment"
            />
            <button className="inline-flex items-center justify-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={applyDepartureFilters} disabled={departureLoading || shiftLoading} title="Run departure filters and operational shift analysis">
              <Search size={16} />
              {departureLoading || shiftLoading ? "Running" : "Apply"}
            </button>
          </div>
          <div className="mt-4 border border-line">
            <div className="flex flex-col gap-2 border-b border-line bg-slate-50 px-3 py-2 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Saved Shift Analysis Configurations</div>
                <div className="mt-1 text-xs text-slate-500">Showing {savedShiftConfigShowingStart}-{savedShiftConfigShowingEnd} of {savedShiftConfigTotal.toLocaleString()}</div>
              </div>
              <select className="border border-line bg-white px-2 py-1 text-xs" value={savedShiftConfigLimit} onChange={(event) => { setSavedShiftConfigOffset(0); setSavedShiftConfigLimit(Number(event.target.value)); }} title="Saved configurations per page">
                <option value={5}>5 rows</option>
                <option value={10}>10 rows</option>
                <option value={25}>25 rows</option>
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="whitespace-nowrap px-3 py-2">Name</th>
                    <th className="whitespace-nowrap px-3 py-2">Depot</th>
                    <th className="whitespace-nowrap px-3 py-2">Period</th>
                    <th className="whitespace-nowrap px-3 py-2">Method</th>
                    <th className="whitespace-nowrap px-3 py-2">Profiles</th>
                    <th className="whitespace-nowrap px-3 py-2">Saved</th>
                    <th className="whitespace-nowrap px-3 py-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {savedShiftConfigs.map((config) => (
                    <tr key={config.id} className="border-b border-line">
                      <td className="whitespace-nowrap px-3 py-2 font-medium">{config.name}</td>
                      <td className="whitespace-nowrap px-3 py-2">{config.depot_name ?? config.depot_id}</td>
                      <td className="whitespace-nowrap px-3 py-2">{formatDate(config.start_date)} - {formatDate(config.end_date)}</td>
                      <td className="whitespace-nowrap px-3 py-2">{config.assignment_method_label}</td>
                      <td className="whitespace-nowrap px-3 py-2">{config.profile_count.toLocaleString()}</td>
                      <td className="whitespace-nowrap px-3 py-2">{formatDateTime(config.updated_at)}</td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <button className="inline-flex items-center justify-center border border-line px-2 py-1 text-xs text-rust disabled:opacity-50" onClick={() => deleteSavedShiftConfig(config)} disabled={savedShiftConfigLoading} title="Delete saved configuration">
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {savedShiftConfigs.length === 0 && (
                    <tr><td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={7}>No saved shift analysis configuration.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setSavedShiftConfigOffset(Math.max(0, savedShiftConfigOffset - savedShiftConfigLimit))} disabled={!canPreviousSavedShiftConfigPage}>Previous</button>
              <span className="text-slate-500">Page {savedShiftConfigPageNumber} of {savedShiftConfigPageCount}</span>
              <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setSavedShiftConfigOffset(savedShiftConfigOffset + savedShiftConfigLimit)} disabled={!canNextSavedShiftConfigPage}>Next</button>
            </div>
          </div>
        </section>

        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-4 flex flex-col gap-2">
            <div>
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Operational Shift Configuration</div>
              <div className="mt-1 text-xs text-slate-500">Descriptive historical shift affinity based on the already applied depot/date range.</div>
            </div>
          </div>
          <div className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Number of Shifts: {shiftConfigs.length}</div>
              <div className="grid gap-2">
                {shiftConfigs.map((shift, index) => (
                  <div key={`${shift.shift_id}-${index}`} className="grid gap-2 md:grid-cols-[1fr_130px_130px_auto]">
                    <input className="border border-line px-3 py-2 text-sm" value={shift.name} onChange={(event) => updateShiftConfig(index, "name", event.target.value)} title={`Shift ${index + 1} name`} />
                    <input className="border border-line px-3 py-2 text-sm" type="time" value={shift.start_time} onChange={(event) => updateShiftConfig(index, "start_time", event.target.value)} title={`Shift ${index + 1} start time`} />
                    <input className="border border-line px-3 py-2 text-sm" type="time" value={shift.end_time} onChange={(event) => updateShiftConfig(index, "end_time", event.target.value)} title={`Shift ${index + 1} end time`} />
                    <button className="inline-flex items-center justify-center border border-line px-3 py-2 text-sm disabled:opacity-40" onClick={() => removeShiftConfig(index)} disabled={shiftConfigs.length <= 1} title="Remove shift">
                      <Trash2 size={15} />
                    </button>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm" onClick={addShiftConfig} title="Add operational shift">
                  <Plus size={15} /> Add Shift
                </button>
              </div>
              {shiftValidationErrors.length > 0 && (
                <div className="mt-3 border border-rust bg-rust/5 px-3 py-2 text-xs text-rust">{shiftValidationErrors[0]}</div>
              )}
            </div>
            <div className="border border-line p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Shift Assignment Method</label>
                <button className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-line text-xs font-semibold" onClick={() => setShiftHelpOpen(true)} title="Explain shift assignment methods">?</button>
              </div>
              <select className="w-full border border-line bg-white px-3 py-2 text-sm" value={shiftMethod} onChange={(event) => setShiftMethod(event.target.value as ShiftAssignmentMethod)}>
                <option value="DOMINANT_SHIFT">Dominant Shift</option>
                <option value="MEDIAN_BASED">Median-Based</option>
                <option value="HYBRID_CONFIDENCE_AWARE">Hybrid / Confidence-Aware</option>
              </select>
              <div className="mt-3 border border-line bg-slate-50 px-3 py-2 text-xs text-slate-500">
                The main Apply button runs both departure filters and shift analysis. This analysis does not prescribe future dispatch schedules.
              </div>
            </div>
          </div>
        </section>

        {!departureAnalysis && (
          <section className="border border-line bg-white p-8 text-center">
            <div className="mx-auto max-w-2xl text-sm text-slate-600">
              Select a depot and analysis period, then click Apply to run Depot Departure Time Intelligence.
            </div>
          </section>
        )}

        {departureAnalysis && departureSummary && (
        <>
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          {[
            ["Observations", departureSummary.observation_count.toLocaleString()],
            ["SPBU Profiles", departureSummary.profile_count.toLocaleString()],
            ["Shipments", departureSummary.shipment_count.toLocaleString()],
            ["Vehicles", departureSummary.vehicle_count.toLocaleString()],
            ["Quantity", departureSummary.quantity_dispatched.toLocaleString()],
            ["Missing Timestamps", departureSummary.missing_timestamp_count.toLocaleString()]
          ].map(([label, value]) => (
            <div key={label} className="border border-line bg-white p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
              <div className="mt-2 text-2xl font-semibold">{value}</div>
            </div>
          ))}
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-3">
          <div className="border border-line bg-white p-4">
            <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Source Data Quality</div>
            <div className="grid gap-3 text-sm">
              <div className="flex items-center justify-between border-b border-line pb-2"><span>GPS timestamp coverage</span><span className="font-semibold">{departureSummary.gps_timestamp_coverage_pct}%</span></div>
              <div className="flex items-center justify-between border-b border-line pb-2"><span>LO gate-out coverage</span><span className="font-semibold">{departureSummary.lo_gate_out_coverage_pct}%</span></div>
              <div className="flex items-center justify-between border-b border-line pb-2"><span>GPS observations</span><span className="font-semibold">{departureSummary.gps_observation_count.toLocaleString()}</span></div>
              <div className="flex items-center justify-between border-b border-line pb-2"><span>LO gate-out observations</span><span className="font-semibold">{departureSummary.lo_gate_out_observation_count.toLocaleString()}</span></div>
              <div className="flex items-center justify-between"><span>Avg GPS vs LO difference</span><span className="font-semibold">{departureSummary.avg_gps_vs_lo_difference_minutes ?? "-"} min</span></div>
            </div>
          </div>
          <div className="border border-line bg-white p-4 lg:col-span-2">
            <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Confidence Mix</div>
            <div className="grid gap-3 sm:grid-cols-3">
              {[
                ["High", departureSummary.high_confidence_profiles, "HIGH"],
                ["Medium", departureSummary.medium_confidence_profiles, "MEDIUM"],
                ["Low", departureSummary.low_confidence_profiles, "LOW"]
              ].map(([label, value, level]) => {
                const confidenceLevel = String(level) as "HIGH" | "MEDIUM" | "LOW";
                const isActive = departureConfidenceFilter === confidenceLevel;
                return (
                  <button
                    key={label}
                    type="button"
                    className={`border p-4 text-left transition hover:shadow-sm ${confidenceClass(confidenceLevel)} ${isActive ? "ring-2 ring-petroblue ring-offset-2" : ""}`}
                    onClick={() => toggleConfidenceProfileFilter(confidenceLevel)}
                    title={`Filter profiles by ${label} confidence`}
                    aria-pressed={isActive}
                  >
                    <div className="text-xs font-semibold uppercase tracking-wide">{label}</div>
                    <div className="mt-2 text-3xl font-semibold">{Number(value).toLocaleString()}</div>
                  </button>
                );
              })}
            </div>
            <div className="mt-4 text-xs text-slate-500">
              Algorithm: {departureAnalysis.algorithm_version}. Peak departure time is the midpoint of the busiest bucket.
              {departureConfidenceFilter !== "ALL" ? ` Active confidence filter: ${departureConfidenceFilter}.` : ""}
            </div>
          </div>
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-2">
          <ChartPanel title="24-Hour Departure Distribution" data={departureAnalysis.distribution} />
          <section className="min-h-[320px] border border-line bg-white p-4">
            <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Weekday Departure Heatmap</div>
            {heatmapOption ? <ReactECharts option={heatmapOption} style={{ height: 260 }} /> : <div className="py-20 text-center text-sm text-slate-500">No heatmap data.</div>}
          </section>
          <section className="min-h-[360px] border border-line bg-white p-4 lg:col-span-2">
            <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">SPBU Departure Time Box Plot - Current Table Page</div>
                <div className="mt-1 text-xs text-slate-500">Circular-time scale: labels with +1d are early-morning departures visually shifted after midnight to avoid false 24-hour spread.</div>
              </div>
              <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Group / Highlight By
                <select className="border border-line bg-white px-2 py-1 text-xs normal-case tracking-normal" value={boxPlotHighlightBy} onChange={(event) => setBoxPlotHighlightBy(event.target.value as typeof boxPlotHighlightBy)}>
                  <option value="NONE">None</option>
                  <option value="PRIMARY_SHIFT">Primary Historical Shift</option>
                  <option value="ASSIGNMENT_STATUS">Assignment Status</option>
                  <option value="CONFIDENCE">Confidence</option>
                </select>
              </label>
            </div>
            {boxPlotLegendItems.length > 0 && (
              <div className="mb-3 flex flex-wrap items-center gap-3 border border-line bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <span className="font-semibold uppercase tracking-wide text-slate-500">Legend</span>
                {boxPlotLegendItems.map((item) => (
                  <span key={item.label} className="inline-flex items-center gap-2">
                    <span className="inline-block h-3 w-5 border-2 bg-[#dfe9e6]" style={{ borderColor: item.color }} />
                    <span>{item.label}</span>
                  </span>
                ))}
                <span className="text-slate-400">Color applies to box border; fill remains unchanged.</span>
              </div>
            )}
            {boxPlotOption ? <ReactECharts option={boxPlotOption} style={{ height: 300 }} /> : <div className="py-20 text-center text-sm text-slate-500">No box plot data.</div>}
          </section>
        </section>

        {shiftAnalysis && (
          <>
            <section className="mt-5 border border-line bg-white p-4">
              <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Operational Shift Summary</div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
                {shiftAnalysis.summary.assigned_by_shift.map((item, index) => {
                  const filter = `SHIFT:${item.shift_id}` as ShiftSummaryFilter;
                  const isActive = shiftSummaryFilter === filter;
                  return (
                    <button
                      key={item.shift_id}
                      type="button"
                      className={`border border-line p-3 text-left transition hover:shadow-sm ${isActive ? "ring-2 ring-petroblue ring-offset-2" : ""}`}
                      onClick={() => toggleShiftSummaryProfileFilter(filter)}
                      title={`Filter profiles by ${item.shift_name}`}
                      aria-pressed={isActive}
                    >
                      <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: shiftPalette(index) }}>{item.shift_name}</div>
                      <div className="mt-2 text-2xl font-semibold">{item.spbu_count.toLocaleString()} SPBU</div>
                    </button>
                  );
                })}
                {(["AMBIGUOUS", "INSUFFICIENT_DATA"] as const).map((status) => {
                  const filter = `STATUS:${status}` as ShiftSummaryFilter;
                  const isActive = shiftSummaryFilter === filter;
                  return (
                    <button
                      key={status}
                      type="button"
                      className={`border p-3 text-left transition hover:shadow-sm ${shiftStatusClass(status)} ${isActive ? "ring-2 ring-petroblue ring-offset-2" : ""}`}
                      onClick={() => toggleShiftSummaryProfileFilter(filter)}
                      title={`Filter profiles by ${status.replace(/_/g, " ")}`}
                      aria-pressed={isActive}
                    >
                      <div className="text-xs font-semibold uppercase tracking-wide">{status.replace(/_/g, " ")}</div>
                      <div className="mt-2 text-2xl font-semibold">{shiftAnalysis.summary.status_counts[status].toLocaleString()} SPBU</div>
                    </button>
                  );
                })}
              </div>
              <div className="mt-3 text-xs text-slate-500">
                Method: {shiftAnalysis.assignment_method_label}. Algorithm: {shiftAnalysis.algorithm_version}.
                {shiftSummaryFilter !== "ALL" ? " Active shift summary filter applied." : ""}
              </div>
            </section>

            <section className="mt-5 min-h-[360px] border border-line bg-white p-4">
              <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">SPBU Shift Affinity Heatmap</div>
              <div className="mb-3 text-xs text-slate-500">Rows are current-page SPBU and columns are configured shifts. Darker cells mean a larger share of historical departures occurred in that shift.</div>
              {shiftAffinityHeatmapOption ? <ReactECharts option={shiftAffinityHeatmapOption} style={{ height: 360 }} /> : <div className="py-20 text-center text-sm text-slate-500">No shift affinity data.</div>}
            </section>
          </>
        )}

        <section className="mt-5 border border-line bg-white p-4">
          <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">SPBU Departure Profiles</div>
              <div className="mt-1 text-xs text-slate-500">
                Showing {departureShowingStart}-{departureShowingEnd} of {departureTotal.toLocaleString()} profiles
                {departureProfileSearch.trim() ? ` | Table filter: ${departureProfileSearch.trim()}` : ""}
                {departureConfidenceFilter !== "ALL" ? ` | Confidence: ${departureConfidenceFilter}` : ""}
                {shiftSummaryFilter !== "ALL" ? " | Shift summary filter active" : ""}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {(departureProfileSearch.trim() || departureConfidenceFilter !== "ALL" || shiftSummaryFilter !== "ALL") && (
                <button className="border border-line px-3 py-2 text-sm" onClick={clearDepartureProfileFilters} title="Clear profile filters">Clear Filters</button>
              )}
              <select className="border border-line bg-white px-3 py-2 text-sm" value={departureLimit} onChange={(event) => { setDepartureOffset(0); setDepartureLimit(Number(event.target.value)); }} title="Rows per page">
                <option value={10}>10 rows</option>
                <option value={25}>25 rows</option>
                <option value={50}>50 rows</option>
                <option value={100}>100 rows</option>
              </select>
            </div>
          </div>
          <div className="mb-3 grid gap-2 lg:grid-cols-[minmax(280px,520px)_1fr]">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
              <input
                className="w-full border border-line py-2 pl-9 pr-3 text-sm"
                value={departureProfileSearch}
                onChange={(event) => updateDepartureProfileSearch(event.target.value)}
                placeholder="Filter table by SPBU name/code or tag value"
                title="Filter table by SPBU name/code or tag value"
              />
            </label>
          </div>
          <div className="overflow-x-auto border border-line">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  {[
                    ["spbu_code", "SPBU"],
                    ["preferred_historical_departure_window", "Preferred Historical Departure Window"],
                    ["peak_departure_time", "Peak"],
                    ["p50", "P50"],
                    ["p80", "P80"],
                    ["p90", "P90"],
                    ["p95", "P95"],
                    ["observation_count", "Obs"],
                    ["dispersion_minutes_iqr", "IQR"],
                    ["confidence_score", "Confidence"]
                  ].map(([column, label]) => {
                    const isActiveSortColumn = departureSortColumn === column;
                    return (
                      <th key={column} className="whitespace-nowrap px-3 py-2" aria-sort={isActiveSortColumn ? (departureSortDirection === "asc" ? "ascending" : "descending") : "none"}>
                        <button
                          type="button"
                          className="inline-flex min-h-6 items-center gap-1 text-left uppercase tracking-wide hover:text-slate-900"
                          onClick={() => handleDepartureSort(column as DepartureSortColumn)}
                          title={`Sort by ${label}`}
                        >
                          <span>{label}</span>
                          {isActiveSortColumn ? (
                            departureSortDirection === "asc" ? <ArrowUp size={14} aria-hidden="true" /> : <ArrowDown size={14} aria-hidden="true" />
                          ) : (
                            <ArrowUpDown size={14} className="text-slate-300" aria-hidden="true" />
                          )}
                        </button>
                      </th>
                    );
                  })}
                  <th className="whitespace-nowrap px-3 py-2">SPBU Tag</th>
                  <th className="whitespace-nowrap px-3 py-2">Primary Shift</th>
                  <th className="whitespace-nowrap px-3 py-2">Secondary Shift</th>
                  <th className="whitespace-nowrap px-3 py-2">Shift Gap</th>
                  <th className="whitespace-nowrap px-3 py-2">Shift Affinity</th>
                  <th className="whitespace-nowrap px-3 py-2">Shift Status</th>
                </tr>
              </thead>
              <tbody>
                {departureProfiles.map((profile) => {
                  const shiftRow = shiftRowBySpbuId.get(profile.spbu_id);
                  return (
                    <tr
                      key={profile.spbu_id}
                      className={`cursor-pointer border-b border-line ${selectedDepartureProfile?.spbu_id === profile.spbu_id ? "bg-mint/10" : ""}`}
                      onClick={() => setSelectedDepartureSpbuId(profile.spbu_id)}
                    >
                      <td className="whitespace-nowrap px-3 py-2">
                        <div className="font-medium">{profile.spbu_code}</div>
                        <div className="text-xs text-slate-500">{profile.spbu_name ?? "-"}</div>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-semibold">{profile.preferred_historical_departure_window}</td>
                      <td className="whitespace-nowrap px-3 py-2">{profile.peak_departure_time} <span className="text-xs text-slate-500">({profile.peak_departure_bucket})</span></td>
                      <td className="whitespace-nowrap px-3 py-2">{profile.p50}</td>
                      <td className="whitespace-nowrap px-3 py-2">{profile.p80}</td>
                      <td className="whitespace-nowrap px-3 py-2">{profile.p90}</td>
                      <td className="whitespace-nowrap px-3 py-2">{profile.p95}</td>
                      <td className="whitespace-nowrap px-3 py-2">{profile.observation_count.toLocaleString()}</td>
                      <td className="whitespace-nowrap px-3 py-2">{profile.dispersion_minutes_iqr.toLocaleString()} min</td>
                      <td className="px-3 py-2">
                        <span className={`inline-flex border px-2 py-1 text-xs font-semibold ${confidenceClass(profile.confidence_level)}`}>{profile.confidence_level} {profile.confidence_score}</span>
                      </td>
                      <td className="min-w-[220px] px-3 py-2">
                        {profile.spbu_tags.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {profile.spbu_tags.map((tag) => (
                              <span key={tag} className="border border-line bg-slate-50 px-2 py-1 text-xs text-slate-600">{tag}</span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-semibold" title={shiftRow?.primary_shift_score !== null && shiftRow?.primary_shift_score !== undefined ? `Assignment score ${shiftRow.primary_shift_score}` : undefined}>
                        {shiftRow?.primary_shift_name ?? "-"} {shiftRow ? <span className="text-xs text-slate-500">{shiftRow.primary_shift_share}%</span> : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        {shiftRow?.secondary_shift_name ?? "-"} {shiftRow ? <span className="text-xs text-slate-500">{shiftRow.secondary_shift_share}%</span> : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">{shiftRow ? `${shiftRow.primary_secondary_gap}%` : "-"}</td>
                      <td className="min-w-[220px] px-3 py-2">
                        {shiftRow ? (
                          <div className="flex flex-wrap gap-1">
                            {shiftRow.shift_distribution.map((item, index) => (
                              <span key={item.shift_id} className="border px-2 py-1 text-xs" style={{ borderColor: shiftPalette(index), color: shiftPalette(index) }} title={`${item.observation_count} of ${shiftRow.observation_count} observations${item.score !== null ? `, score ${item.score}` : ""}`}>
                                {item.shift_name} {item.share_pct}%
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {shiftRow ? <span className={`inline-flex border px-2 py-1 text-xs font-semibold ${shiftStatusClass(shiftRow.assignment_status)}`}>{shiftRow.assignment_status.replace(/_/g, " ")}</span> : <span className="text-slate-400">-</span>}
                      </td>
                    </tr>
                  );
                })}
                {departureProfiles.length === 0 && (
                  <tr><td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={16}>No departure profiles match the selected depot and period.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center justify-between gap-3 text-sm">
            <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setDepartureOffset(Math.max(0, departureOffset - departureLimit))} disabled={!canPreviousDeparturePage}>Previous</button>
            <span className="text-slate-500">Page {departurePageNumber} of {departurePageCount}</span>
            <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setDepartureOffset(departureOffset + departureLimit)} disabled={!canNextDeparturePage}>Next</button>
          </div>
        </section>

        <section className="mt-5 border border-line bg-white p-4">
          <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">SPBU Explorer - Source Lineage</div>
          {selectedDepartureProfile ? (
            <>
              <div className="mb-3 grid gap-3 md:grid-cols-4">
                <div className="border border-line p-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected SPBU</div>
                  <div className="mt-1 font-semibold">{selectedDepartureProfile.spbu_code}</div>
                </div>
                <div className="border border-line p-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Source Counts</div>
                  <div className="mt-1 text-sm">GPS {selectedDepartureProfile.departure_time_source_counts.GPS ?? 0} / LO {selectedDepartureProfile.departure_time_source_counts.LO_GATE_OUT ?? 0}</div>
                </div>
                <div className="border border-line p-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Vehicles</div>
                  <div className="mt-1 font-semibold">{selectedDepartureProfile.vehicle_count.toLocaleString()}</div>
                </div>
                <div className="border border-line p-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quantity</div>
                  <div className="mt-1 font-semibold">{selectedDepartureProfile.quantity_dispatched.toLocaleString()}</div>
                </div>
              </div>
              {shiftAnalysis && (
                <div className="mb-3 border border-line p-3">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Operational Shift Intelligence</div>
                  {selectedShiftRow ? (
                    <div className="grid gap-3 text-sm lg:grid-cols-3">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Assignment Method</div>
                        <div className="mt-1 font-semibold">{shiftAnalysis.assignment_method_label}</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Primary Historical Shift</div>
                        <div className="mt-1 font-semibold">{selectedShiftRow.primary_shift_name ?? "-"}</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Secondary Shift</div>
                        <div className="mt-1 font-semibold">{selectedShiftRow.secondary_shift_name ?? "-"}</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status</div>
                        <div className="mt-1"><span className={`inline-flex border px-2 py-1 text-xs font-semibold ${shiftStatusClass(selectedShiftRow.assignment_status)}`}>{selectedShiftRow.assignment_status.replace(/_/g, " ")}</span></div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Median / Peak</div>
                        <div className="mt-1 font-semibold">{selectedShiftRow.median_departure} / {selectedShiftRow.peak_departure_time}</div>
                      </div>
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Preferred Window</div>
                        <div className="mt-1 font-semibold">{selectedShiftRow.preferred_historical_departure_window}</div>
                      </div>
                      <div className="lg:col-span-3">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Shift Affinity</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {selectedShiftRow.shift_distribution.map((item, index) => (
                            <span key={item.shift_id} className="border px-2 py-1 text-xs" style={{ borderColor: shiftPalette(index), color: shiftPalette(index) }}>
                              {item.shift_name} {item.share_pct}%
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm text-slate-500">No shift profile for the selected SPBU.</div>
                  )}
                </div>
              )}
              <div className="overflow-x-auto border border-line">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                      <th className="whitespace-nowrap px-3 py-2">Operation Date</th>
                      <th className="whitespace-nowrap px-3 py-2">Shipment</th>
                      <th className="whitespace-nowrap px-3 py-2">Vehicle</th>
                      <th className="whitespace-nowrap px-3 py-2">LO Gate-Out</th>
                      <th className="whitespace-nowrap px-3 py-2">GPS Depot Exit</th>
                      <th className="whitespace-nowrap px-3 py-2">Used Timestamp</th>
                      <th className="whitespace-nowrap px-3 py-2">Source</th>
                      <th className="whitespace-nowrap px-3 py-2">GPS vs LO</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedDepartureObservations.map((row) => (
                      <tr key={row.observation_id} className="border-b border-line">
                        <td className="whitespace-nowrap px-3 py-2">{formatDate(row.operation_date)}</td>
                        <td className="whitespace-nowrap px-3 py-2">{row.source_shipment_id}</td>
                        <td className="whitespace-nowrap px-3 py-2">{row.vehicle_registration ?? "-"}</td>
                        <td className="whitespace-nowrap px-3 py-2">{formatDateTime(row.loading_order_gate_out_datetime)}</td>
                        <td className="whitespace-nowrap px-3 py-2">{formatDateTime(row.gps_actual_depot_exit_datetime)}</td>
                        <td className="whitespace-nowrap px-3 py-2">{formatDateTime(row.departure_datetime_used)}</td>
                        <td className="whitespace-nowrap px-3 py-2">{row.departure_time_source ?? "-"}</td>
                        <td className="whitespace-nowrap px-3 py-2">{row.gps_vs_lo_difference_minutes ?? "-"} min</td>
                      </tr>
                    ))}
                    {selectedDepartureObservations.length === 0 && (
                      <tr><td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={8}>No observations for the selected profile.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="py-8 text-center text-sm text-slate-500">Select a profile row to inspect source timestamps.</div>
          )}
        </section>
        </>
        )}
        </>
        )}

        {currentPage === "tag-consistency" && (
        <>
        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-3 flex flex-col gap-1">
            <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Tag Consistency Analysis</div>
            <div className="text-xs text-slate-500">
              {tagAnalysis?.effective_filters.start_date && tagAnalysis?.effective_filters.end_date
                ? `Tanggal analisis: ${formatDate(String(tagAnalysis.effective_filters.start_date))} - ${formatDate(String(tagAnalysis.effective_filters.end_date))}`
                : "Default date menggunakan latest available Loading Order date."}
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
            <input className="border border-line px-3 py-2 text-sm" type="date" value={tagFilters.startDate} onChange={(event) => updateTagFilter("startDate", event.target.value)} title="Start date" />
            <input className="border border-line px-3 py-2 text-sm" type="date" value={tagFilters.endDate} onChange={(event) => updateTagFilter("endDate", event.target.value)} title="End date" />
            <select className="border border-line bg-white px-3 py-2 text-sm" value={tagFilters.depotId} onChange={(event) => updateTagFilter("depotId", event.target.value)} title="Depot">

              {depots.map((depot) => (
                <option key={depot.depot_id} value={depot.depot_id}>{depot.depot_name}</option>
              ))}
            </select>
            <input className="border border-line px-3 py-2 text-sm" value={tagFilters.spbu} onChange={(event) => updateTagFilter("spbu", event.target.value)} placeholder="SPBU" title="Filter SPBU" />
            <input className="border border-line px-3 py-2 text-sm" value={tagFilters.vehicle} onChange={(event) => updateTagFilter("vehicle", event.target.value)} placeholder="Vehicle / MT" title="Filter vehicle registration" />
            <select className="border border-line bg-white px-3 py-2 text-sm" value={tagFilters.tagType} onChange={(event) => updateTagFilter("tagType", event.target.value)} title="Tag type">
              <option value="ALL">All Tag Types</option>
              {tagTypes.map((tagType) => (
                <option key={tagType.code} value={tagType.code}>{tagType.name}</option>
              ))}
            </select>
            <select className="border border-line bg-white px-3 py-2 text-sm" value={tagFilters.status} onChange={(event) => updateTagFilter("status", event.target.value)} title="Overall status">
              <option value="ALL">All Status</option>
              <option value="MATCH">Match</option>
              <option value="MISMATCH">Mismatch</option>
              <option value="DATA_ISSUE">Data Issue</option>
            </select>
            <select className="border border-line bg-white px-3 py-2 text-sm" value={tagFilters.productId} onChange={(event) => updateTagFilter("productId", event.target.value)} title="Product">
              <option value="">All Products</option>
              {products.map((product) => (
                <option key={product.product_id} value={product.product_id}>{product.product_name}</option>
              ))}
            </select>
            <input className="border border-line px-3 py-2 text-sm" type="number" value={tagFilters.vehicleClass} onChange={(event) => updateTagFilter("vehicleClass", event.target.value)} placeholder="Vehicle Class" title="Vehicle class" />
            <input
              className="border border-line px-3 py-2 text-sm"
              value={tagFilters.search}
              onChange={(event) => updateTagFilter("search", event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") applyTagFilters(); }}
              placeholder="Search LO, MT, SPBU"
              title="Search analysis"
            />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="inline-flex items-center justify-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={applyTagFilters} disabled={tagLoading} title="Apply tag consistency filters">
              <Search size={16} />
              {tagLoading ? "Loading" : "Apply Filter"}
            </button>
            <button className="inline-flex items-center justify-center gap-2 border border-line px-3 py-2 text-sm" onClick={resetTagFilters} title="Reset filters">
              <RefreshCw size={16} />
              Reset
            </button>
          </div>
        </section>

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          {[
            ["Total LO Assignments", tagSummary.total_lo_assignments.toLocaleString()],
            ["Matched", tagSummary.matched.toLocaleString()],
            ["Mismatch", tagSummary.mismatch.toLocaleString()],
            ["Data Issues", tagSummary.data_issues.toLocaleString()],
            ["Analyzable LO", tagSummary.analyzable_lo.toLocaleString()],
            ["Consistency Rate", `${tagSummary.consistency_rate.toLocaleString()}%`]
          ].map(([label, value]) => (
            <div key={label} className="border border-line bg-white p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
              <div className="mt-2 text-2xl font-semibold">{value}</div>
            </div>
          ))}
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-2">
          <ChartPanel title="Mismatch by Tag Type" data={tagSummary.mismatch_by_tag_type} orientation="horizontal" />
          <ChartPanel title="Mismatch by Tag Value" data={tagSummary.mismatch_by_tag_value} orientation="horizontal" />
          <ChartPanel title="Daily Tag Consistency Rate" data={tagSummary.daily_consistency_rate} />
          <ChartPanel title="Data Quality Issues" data={tagSummary.data_quality_summary} kind="pie" />
          <div className="flex flex-wrap items-center justify-between gap-3 lg:col-span-2">
            <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Mismatch Tables</div>
            <label className="inline-flex items-center gap-2 text-sm">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Rows per page</span>
              <select className="border border-line bg-white px-3 py-2 text-sm" value={mismatchRowsPerPage} onChange={(event) => handleMismatchRowsPerPage(event.target.value)} title="Rows per page for both mismatch tables">
                <option value={10}>10 rows</option>
                <option value={20}>20 rows</option>
                <option value={50}>50 rows</option>
              </select>
            </label>
          </div>
          <section className="border border-line bg-white p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">All SPBU with Tag Mismatch</div>
              <div className="text-xs text-slate-500">{allSpbuMismatchRows.length.toLocaleString()} SPBU</div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-slate-500">
                    {[
                      ["label", "SPBU"],
                      ["total_assignment", "Assignments"],
                      ["mismatch", "Mismatch"],
                      ["mismatch_rate", "Rate"]
                    ].map(([column, label]) => (
                      <th key={column} className="py-2 pr-3">
                        <button className="inline-flex items-center gap-1 uppercase tracking-wide" onClick={() => handleSpbuMismatchSort(column as MismatchSortColumn)} title={`Sort SPBU mismatch by ${label}`}>
                          <span>{label}</span>
                          {spbuMismatchSortColumn === column ? (spbuMismatchSortDirection === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />) : <ArrowUpDown size={14} className="text-slate-300" />}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visibleSpbuMismatchRows.map((row) => (
                    <tr key={row.spbu} className="border-b border-line">
                      <td className="py-2 pr-3">{row.spbu}</td>
                      <td className="py-2 pr-3">{row.total_assignment.toLocaleString()}</td>
                      <td className="py-2 pr-3">{row.mismatch.toLocaleString()}</td>
                      <td className="py-2 pr-3">{row.mismatch_rate.toLocaleString()}%</td>
                    </tr>
                  ))}
                  {allSpbuMismatchRows.length === 0 && (
                    <tr><td className="py-8 text-center text-slate-500" colSpan={4}>No SPBU mismatch in the active filter.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between gap-3 text-sm">
              <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setSpbuMismatchPage(Math.max(0, spbuMismatchPage - 1))} disabled={spbuMismatchPage === 0}>Previous</button>
              <span className="text-slate-500">Page {spbuMismatchPage + 1} of {spbuMismatchPageCount}</span>
              <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setSpbuMismatchPage(Math.min(spbuMismatchPageCount - 1, spbuMismatchPage + 1))} disabled={spbuMismatchPage + 1 >= spbuMismatchPageCount}>Next</button>
            </div>
          </section>
          <section className="border border-line bg-white p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">All MT with Tag Mismatch</div>
              <div className="text-xs text-slate-500">{allMtMismatchRows.length.toLocaleString()} MT</div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-slate-500">
                    {[
                      ["label", "Vehicle Registration"],
                      ["total_assignment", "Assignments"],
                      ["mismatch", "Mismatch"],
                      ["mismatch_rate", "Rate"]
                    ].map(([column, label]) => (
                      <th key={column} className="py-2 pr-3">
                        <button className="inline-flex items-center gap-1 uppercase tracking-wide" onClick={() => handleMtMismatchSort(column as MismatchSortColumn)} title={`Sort MT mismatch by ${label}`}>
                          <span>{label}</span>
                          {mtMismatchSortColumn === column ? (mtMismatchSortDirection === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />) : <ArrowUpDown size={14} className="text-slate-300" />}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visibleMtMismatchRows.map((row) => (
                    <tr key={row.vehicle_registration} className="border-b border-line">
                      <td className="py-2 pr-3">{row.vehicle_registration}</td>
                      <td className="py-2 pr-3">{row.total_assignment.toLocaleString()}</td>
                      <td className="py-2 pr-3">{row.mismatch.toLocaleString()}</td>
                      <td className="py-2 pr-3">{row.mismatch_rate.toLocaleString()}%</td>
                    </tr>
                  ))}
                  {allMtMismatchRows.length === 0 && (
                    <tr><td className="py-8 text-center text-slate-500" colSpan={4}>No MT mismatch in the active filter.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between gap-3 text-sm">
              <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setMtMismatchPage(Math.max(0, mtMismatchPage - 1))} disabled={mtMismatchPage === 0}>Previous</button>
              <span className="text-slate-500">Page {mtMismatchPage + 1} of {mtMismatchPageCount}</span>
              <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setMtMismatchPage(Math.min(mtMismatchPageCount - 1, mtMismatchPage + 1))} disabled={mtMismatchPage + 1 >= mtMismatchPageCount}>Next</button>
            </div>
          </section>
        </section>

        <section className="mt-5 border border-line bg-white p-4">
          <div className="mb-3 flex flex-col gap-1 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Main Analysis Table</div>
              <div className="mt-1 text-xs text-slate-500">Showing {tagShowingStart}-{tagShowingEnd} of {tagTotal.toLocaleString()} assignments</div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
            <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50" onClick={handleExportTagAnalysis} disabled={tagLoading || tagExporting || !tagExportParams || tagTotal === 0} title="Export all matching assignments using the applied filters and table sorting">
              <Download size={16} />
              {tagExporting ? "Exporting..." : "Export to Excel"}
            </button>
            <select className="border border-line bg-white px-3 py-2 text-sm" value={tagLimit} onChange={(event) => { setTagOffset(0); setTagLimit(Number(event.target.value)); }} title="Rows per page">
              <option value={25}>25 rows</option>
              <option value={50}>50 rows</option>
              <option value={100}>100 rows</option>
            </select>
            </div>
          </div>
          <div className="overflow-x-auto border border-line">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  {[
                    ["loading_order_date", "Date"],
                    ["loading_order_number", "Loading Order"],
                    ["vehicle_registration", "Vehicle Registration"],
                    ["spbu_name", "SPBU"],
                    ["depot", "Depot"],
                    ["overall_status", "Overall Status"]
                  ].map(([column, label]) => (
                    <th key={column} className="whitespace-nowrap px-3 py-2">
                      <button className="inline-flex items-center gap-1 uppercase tracking-wide" onClick={() => handleTagSort(column)} title={`Sort by ${label}`}>
                        <span>{label}</span>
                        {tagSortColumn === column ? (tagSortDirection === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />) : <ArrowUpDown size={14} className="text-slate-300" />}
                      </button>
                    </th>
                  ))}
                  <th className="whitespace-nowrap px-3 py-2">Vehicle Class Result</th>
                  <th className="whitespace-nowrap px-3 py-2">Tag Match Result</th>
                  <th className="whitespace-nowrap px-3 py-2">Issue / Reason</th>
                  <th className="whitespace-nowrap px-3 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {tagRows.map((row) => (
                  <tr key={row.analysis_id} className="border-b border-line">
                    <td className="whitespace-nowrap px-3 py-2">{formatDate(row.loading_order_date)}</td>
                    <td className="whitespace-nowrap px-3 py-2">{row.loading_order_number}</td>
                    <td className="whitespace-nowrap px-3 py-2">{row.vehicle_registration ?? "-"}</td>
                    <td className="whitespace-nowrap px-3 py-2">{row.spbu_code ?? row.spbu_name ?? "-"}</td>
                    <td className="max-w-48 truncate px-3 py-2" title={row.depot ?? "-"}>{row.depot ?? "-"}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex border px-2 py-1 text-xs font-semibold ${statusClass(row.overall_status)}`}>{statusLabel(row.overall_status)}</span>
                    </td>
                    <td className="px-3 py-2">{row.vehicle_class_result.replace(/_/g, " ")}</td>
                    <td className="px-3 py-2">{row.tag_match_result.replace(/_/g, " ")} ({row.mismatch_count})</td>
                    <td className="max-w-80 truncate px-3 py-2" title={row.primary_reason}>{row.primary_reason}</td>
                    <td className="px-3 py-2">
                      <button className="inline-flex items-center gap-2 border border-line px-3 py-2 text-xs" onClick={() => setSelectedAnalysis(row)} title="View tag matrix detail">
                        <Eye size={14} />
                        View Detail
                      </button>
                    </td>
                  </tr>
                ))}
                {tagRows.length === 0 && (
                  <tr>
                    <td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={10}>
                      {tagLoading ? "Loading analysis..." : "No Loading Order assignments match the active filter."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center justify-between gap-3 text-sm">
            <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setTagOffset(Math.max(0, tagOffset - tagLimit))} disabled={!canPreviousTagPage}>Previous</button>
            <span className="text-slate-500">Page {tagPageNumber} of {tagPageCount}</span>
            <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setTagOffset(tagOffset + tagLimit)} disabled={!canNextTagPage}>Next</button>
          </div>
        </section>
        </>
        )}

        {currentPage === "dashboard" && (
        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Dashboard Filter</div>
          <div className="grid gap-3 md:grid-cols-[1fr_auto]">
            <select className="border border-line bg-white px-3 py-2 text-sm" value={dashboardDepotId} onChange={(event) => setDashboardDepotId(event.target.value)} title="Filter dashboard by depot">

              {depots.map((depot) => (
                <option key={depot.depot_id} value={depot.depot_id}>
                  {depot.depot_name}
                </option>
              ))}
            </select>
            <button className="inline-flex items-center justify-center gap-2 border border-line px-3 py-2 text-sm" onClick={() => refresh()} title="Apply dashboard filter">
              <RefreshCw size={16} />
              Apply Filter
            </button>
          </div>
        </section>
        )}

        {currentPage === "restricted-roads" && <RestrictedRoadsPage depotId={activeDepotId} />}
        {currentPage === "master-data" && <div className="mb-4"><button className="border border-line bg-white px-4 py-2 text-sm" onClick={() => navigate("restricted-roads")}>Kelola Restricted Roads</button></div>}
        {currentPage === "master-data" && (
        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-600">
            <FileUp size={16} />
            Import Data
          </div>
          <div className="grid gap-3 lg:grid-cols-[0.9fr_1.2fr_auto_auto_auto]">
            <select className="border border-line bg-white px-3 py-2 text-sm" value={domain} onChange={(event) => handleDomainChange(event.target.value)} title="Import domain">
              <option value="MOBIL_TANGKI">Mobil Tangki</option>
              <option value="SPBU">SPBU</option>
              <option value="LOADING_ORDER">Historikal Shipment</option>
              <option value="GPS">GPS Data</option>
            </select>
            <input className="border border-line px-3 py-2 text-sm" value={sheetName} onChange={(event) => setSheetName(event.target.value)} placeholder="Sheet name" title="Sheet name" />
            <input ref={fileInputRef} className="hidden" type="file" accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={handleFileSelected} />
            <button className="inline-flex items-center justify-center gap-2 bg-amber px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={() => fileInputRef.current?.click()} disabled={!activeDepotId || uploading || Boolean(activeImportId)} title="Choose XLSX or CSV file to import">
              <FileUp size={16} />
              {uploading ? "Uploading" : activeImportId ? "Import Processing" : "Import File"}
            </button>
            <button className="inline-flex items-center justify-center gap-2 border border-line px-3 py-2 text-sm" onClick={handleExportTemplate} disabled={exporting} title="Download import template">
              <Download size={16} />
              Template
            </button>
            <button className="inline-flex items-center justify-center gap-2 border border-line px-3 py-2 text-sm" onClick={() => refresh()} title="Refresh master data">
              <RefreshCw size={16} />
              Refresh
            </button>
          </div>
          <p className="mt-3 text-sm text-slate-600">Upload mengikuti depot aktif: <strong>{depots[0]?.depot_name || "Pilih depot di top bar"}</strong>. File tidak perlu kolom depot ID atau nama depot.</p>
          {activeImportId && (
            <div className="mt-3 border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800">
              Import tetap berjalan di background dan aman jika halaman di-refresh. Status: {activeImportStatus || "QUEUED"}.
              Tabel akan diperbarui otomatis setelah selesai.
            </div>
          )}
        </section>
        )}

        {currentPage === "master-data" && (
        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-600">
            <Download size={16} />
            Export Data Per Depot
          </div>
          <div className="grid gap-3 md:grid-cols-[1fr_1.3fr_0.7fr_auto]">
            <select
              className="border border-line bg-white px-3 py-2 text-sm"
              value={exportDomain}
              onChange={(event) => {
                setExportDomain(event.target.value);
                if (event.target.value === "ALL") setExportFormat("xlsx");
              }}
              title="Export data domain"
            >
              <option value="ALL">All Data</option>
              <option value="MOBIL_TANGKI">Mobil Tangki</option>
              <option value="SPBU">SPBU</option>
              <option value="SHIPMENT">Shipments</option>
              <option value="LOADING_ORDER">Historikal Shipment</option>
            </select>
            <select className="border border-line bg-white px-3 py-2 text-sm" value={exportDepotId} onChange={(event) => setExportDepotId(event.target.value)} title="Depot">
              {depots.length === 0 && <option value="">No depot data</option>}
              {depots.map((depot) => (
                <option key={depot.depot_id} value={depot.depot_id}>
                  {depot.depot_name}
                </option>
              ))}
            </select>
            <select className="border border-line bg-white px-3 py-2 text-sm" value={exportFormat} onChange={(event) => setExportFormat(event.target.value)} title="Export format">
              <option value="xlsx">XLSX</option>
              <option value="csv" disabled={exportDomain === "ALL"}>
                CSV
              </option>
            </select>
            <button className="inline-flex items-center justify-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={handleExportData} disabled={exporting || !exportDepotId} title="Download canonical data filtered by depot">
              <Download size={16} />
              {exporting ? "Exporting" : "Export Data"}
            </button>
          </div>
        </section>
        )}

        {currentPage === "master-data" && (
        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-600">
            <FileUp size={16} />
            Import History
          </div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-3">Domain</th>
                  <th className="py-2 pr-3">File</th>
                  <th className="py-2 pr-3">Tanggal & Waktu Import</th>
                  <th className="py-2 pr-3">Rows</th>
                  <th className="py-2 pr-3">Valid</th>
                  <th className="py-2 pr-3">Warnings</th>
                  <th className="py-2 pr-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {imports.map((item) => (
                  <tr key={item.import_id} className="border-b border-line">
                    <td className="py-2 pr-3">{item.domain === "LOADING_ORDER" ? "Historikal Shipment" : item.domain}</td>
                    <td className="py-2 pr-3">{item.filename}</td>
                    <td className="whitespace-nowrap py-2 pr-3">{formatImportDateTime(item.uploaded_at)}</td>
                    <td className="py-2 pr-3">{item.total_rows.toLocaleString()}</td>
                    <td className="py-2 pr-3">{item.valid_rows.toLocaleString()}</td>
                    <td className="py-2 pr-3">{item.warning_rows.toLocaleString()}</td>
                    <td className="py-2 pr-3" title={item.error_message || undefined}>
                      {item.status}
                      {item.status === "PROCESSING" && item.total_rows > 0 && (
                        <span className="ml-1 text-xs text-slate-500">({item.processed_rows || 0}/{item.total_rows})</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        )}

        {currentPage === "master-data" && (
        <section className="mb-5 border border-line bg-white p-4">
          <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Master Data CRUD</div>
              <div className="mt-1 text-xs text-slate-500">
                Showing {crudShowingStart}-{crudShowingEnd} of {crudTotal.toLocaleString()} records
                {selectedCrudIds.size > 0 && <span className="ml-2">Selected {selectedCrudIds.size.toLocaleString()}</span>}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {crudDomainOrder.map((domainKey) => (
                <button
                  key={domainKey}
                  className={`border px-3 py-2 text-sm ${crudDomain === domainKey ? "border-mint bg-mint text-white" : "border-line bg-white"}`}
                  onClick={() => changeCrudDomain(domainKey)}
                  title={`Open ${configs[domainKey].label} CRUD`}
                >
                  {configs[domainKey].label}
                </button>
              ))}
            </div>
          </div>

          <div className="mb-4 grid gap-3 md:grid-cols-[1.5fr_0.8fr_0.8fr_0.6fr_auto]">
            <input
              className="border border-line px-3 py-2 text-sm"
              value={crudSearch}
              onChange={(event) => setCrudSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") applyCrudSearch();
              }}
              placeholder={`Search ${activeCrudConfig.label}`}
              title="Search master data"
            />
            <select
              className="border border-line bg-white px-3 py-2 text-sm"
              value={crudSearchColumn}
              onChange={(event) => setCrudSearchColumn(event.target.value)}
              title="Search column"
            >
              {activeCrudConfig.columns.map((column) => (
                <option key={column} value={column}>
                  {crudColumnLabel(column)}
                </option>
              ))}
            </select>
            <select
              className="border border-line bg-white px-3 py-2 text-sm disabled:bg-slate-100"
              value={crudDepotId}
              onChange={(event) => { setCrudOffset(0); setCrudDepotId(event.target.value); }}
              disabled={!activeCrudConfig.depotFilter}
              title="Filter depot"
            >

              {depots.map((depot) => (
                <option key={depot.depot_id} value={depot.depot_id}>
                  {depot.depot_name}
                </option>
              ))}
            </select>
            <select className="border border-line bg-white px-3 py-2 text-sm" value={String(crudLimit)} onChange={(event) => handleCrudLimitChange(event.target.value)} title="Rows per page">
              <option value={10}>10 rows</option>
              <option value={50}>50 rows</option>
              <option value={100}>100 rows</option>
              <option value="ALL">All records</option>
            </select>
            <button className="inline-flex items-center justify-center gap-2 bg-amber px-3 py-2 text-sm font-medium text-white" onClick={applyCrudSearch} title="Apply search">
              <Search size={16} />
              Search
            </button>
          </div>

          <div className="mb-4 flex flex-wrap items-center gap-2">
            <button className="inline-flex items-center justify-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" onClick={openCrudAddModal} disabled={crudLoading} title="Add one or more records">
              <Plus size={16} />
              Add
            </button>
            {canSyncCrudDomain && (
              <button className="inline-flex items-center justify-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50" onClick={syncCrudMasterData} disabled={crudLoading || crudSyncing} title={`Sync ${activeCrudConfig.label} from imported source data`}>
                <RefreshCw size={16} />
                {crudSyncing ? "Syncing" : "Sync"}
              </button>
            )}
            <button className="inline-flex items-center justify-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50" onClick={openCrudEditModal} disabled={crudLoading || selectedCrudCount === 0} title="Edit selected records">
              <Pencil size={16} />
              Edit {selectedCrudCount > 0 ? `(${selectedCrudCount})` : ""}
            </button>
            <button className="inline-flex items-center justify-center gap-2 border border-line px-3 py-2 text-sm text-rust disabled:opacity-50" onClick={deleteSelectedCrudRows} disabled={crudLoading || selectedCrudCount === 0} title="Delete selected records">
              <Trash2 size={16} />
              Delete {selectedCrudCount > 0 ? `(${selectedCrudCount})` : ""}
            </button>
          </div>

          <div className="overflow-x-auto border border-line">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="w-12 px-3 py-2">
                    <input
                      aria-label="Select all visible master data rows"
                      type="checkbox"
                      checked={allVisibleCrudRowsSelected}
                      disabled={visibleCrudIds.length === 0}
                      onChange={toggleVisibleCrudSelection}
                    />
                  </th>
                  {activeCrudConfig.columns.map((column) => {
                    const isActiveSortColumn = crudSortColumn === column;
                    return (
                      <th key={column} className="whitespace-nowrap px-3 py-2" aria-sort={isActiveSortColumn ? (crudSortDirection === "asc" ? "ascending" : "descending") : "none"}>
                        <button
                          type="button"
                          className="inline-flex min-h-6 items-center gap-1 text-left uppercase tracking-wide hover:text-slate-900"
                          onClick={() => handleCrudSort(column)}
                          title={`Sort by ${crudColumnLabel(column)}`}
                        >
                          <span>{crudColumnLabel(column)}</span>
                          {isActiveSortColumn ? (
                            crudSortDirection === "asc" ? <ArrowUp size={14} aria-hidden="true" /> : <ArrowDown size={14} aria-hidden="true" />
                          ) : (
                            <ArrowUpDown size={14} className="text-slate-300" aria-hidden="true" />
                          )}
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {crudRows.map((row, rowIndex) => {
                  const rawRecordId = row[activeCrudConfig.idKey];
                  const hasRecordId = rawRecordId !== null && rawRecordId !== undefined && rawRecordId !== "";
                  const recordId = hasRecordId ? String(rawRecordId) : `${crudDomain}-${crudOffset}-${rowIndex}`;
                  return (
                    <tr key={recordId} className="border-b border-line">
                      <td className="px-3 py-2">
                        <input
                          aria-label={`Select ${activeCrudConfig.label} row ${rowIndex + 1}`}
                          type="checkbox"
                          checked={hasRecordId && selectedCrudIds.has(recordId)}
                          disabled={!hasRecordId}
                          onChange={() => toggleCrudRowSelection(recordId)}
                        />
                      </td>
                      {activeCrudConfig.columns.map((column) => (
                        <td key={column} className="max-w-64 truncate px-3 py-2" title={formatCrudValue(row[column], column)}>
                          {formatCrudValue(row[column], column)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
                {crudRows.length === 0 && (
                  <tr>
                    <td className="px-3 py-8 text-center text-sm text-slate-500" colSpan={activeCrudConfig.columns.length + 1}>
                      {crudLoading ? "Loading data..." : "No records match the active filter."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex items-center justify-between gap-3 text-sm">
            <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setCrudOffset(Math.max(0, crudOffset - crudPageSizeNumber))} disabled={!canPreviousCrudPage}>
              Previous
            </button>
            <span className="text-slate-500">
              Page {crudPageNumber} of {crudPageCount}
            </span>
            <button className="border border-line px-3 py-2 disabled:opacity-50" onClick={() => setCrudOffset(crudOffset + crudPageSizeNumber)} disabled={!canNextCrudPage}>
              Next
            </button>
          </div>
        </section>
        )}

        {currentPage === "master-data" && crudModalMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 py-6">
          <div className="flex max-h-[90vh] w-full max-w-6xl flex-col border border-line bg-white shadow-xl">
            <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
              <div>
                <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                  {crudModalMode === "edit" ? `Edit ${crudBatchForms.length.toLocaleString()} ${activeCrudConfig.label} Record` : `Add ${activeCrudConfig.label} Record`}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {crudModalMode === "edit" ? "Setiap row terpilih dapat diedit sebelum disimpan." : "Tambahkan beberapa row sekaligus sebelum disimpan."}
                </div>
              </div>
              <button type="button" className="inline-flex h-9 w-9 items-center justify-center border border-line" onClick={closeCrudModal} title="Close modal">
                <X size={17} />
              </button>
            </div>

            <form
              className="flex min-h-0 flex-1 flex-col"
              onSubmit={(event) => {
                event.preventDefault();
                saveCrudBatch();
              }}
            >
              <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
                <div className="grid gap-4">
                  {crudBatchForms.map((formRow, rowIndex) => (
                    <div key={formRow.recordId ?? `new-${rowIndex}`} className="border border-line p-4">
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                          Row {rowIndex + 1}{formRow.recordId ? ` - ${String(formRow.values[activeCrudConfig.titleKey] ?? formRow.recordId)}` : ""}
                        </div>
                        {(crudModalMode === "add" || crudBatchForms.length > 1) && (
                          <button type="button" className="inline-flex items-center gap-1 text-xs text-rust disabled:opacity-40" onClick={() => removeCrudBatchRow(rowIndex)} disabled={crudBatchForms.length === 1 && crudModalMode === "add"}>
                            <X size={14} />
                            Remove
                          </button>
                        )}
                      </div>
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                        {activeCrudConfig.fields.map((field) => {
                          const fieldValue = formRow.values[field.key] ?? "";
                          const fieldDisabled = Boolean(crudModalMode === "edit" && field.readonlyOnEdit);
                          if (field.kind === "checkbox") {
                            return (
                              <label key={field.key} className="flex items-center gap-2 text-sm">
                                <input
                                  type="checkbox"
                                  checked={Boolean(fieldValue)}
                                  disabled={fieldDisabled}
                                  onChange={(event) => updateCrudBatchValue(rowIndex, field.key, event.target.checked)}
                                />
                                {field.label}
                              </label>
                            );
                          }
                          return (
                            <label key={field.key} className="grid gap-1 text-sm">
                              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                                {field.label}{field.required ? " *" : ""}
                              </span>
                              {field.kind === "select" ? (
                                <select
                                  className="border border-line bg-white px-3 py-2 text-sm disabled:bg-slate-100"
                                  value={String(fieldValue)}
                                  disabled={fieldDisabled}
                                  onChange={(event) => updateCrudBatchValue(rowIndex, field.key, event.target.value)}
                                >
                                  {(field.options ?? []).map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
                                  ))}
                                </select>
                              ) : field.kind === "textarea" ? (
                                <textarea
                                  className="min-h-20 border border-line px-3 py-2 text-sm disabled:bg-slate-100"
                                  value={String(fieldValue)}
                                  disabled={fieldDisabled}
                                  onChange={(event) => updateCrudBatchValue(rowIndex, field.key, event.target.value)}
                                />
                              ) : (
                                <input
                                  className="border border-line px-3 py-2 text-sm disabled:bg-slate-100"
                                  type={field.kind === "number" ? "number" : field.kind === "time" ? "time" : "text"}
                                  step={field.kind === "number" ? "any" : undefined}
                                  value={String(fieldValue)}
                                  disabled={fieldDisabled}
                                  onChange={(event) => updateCrudBatchValue(rowIndex, field.key, event.target.value)}
                                />
                              )}
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4">
                <div className="text-xs text-slate-500">
                  {crudBatchForms.length.toLocaleString()} row siap diproses
                </div>
                <div className="flex flex-wrap gap-2">
                  {crudModalMode === "add" && (
                    <button type="button" className="inline-flex items-center justify-center gap-2 border border-line px-3 py-2 text-sm" onClick={addCrudBatchRow}>
                      <Plus size={16} />
                      Add Row
                    </button>
                  )}
                  <button type="button" className="border border-line px-3 py-2 text-sm" onClick={closeCrudModal}>Cancel</button>
                  <button type="submit" className="inline-flex items-center justify-center gap-2 bg-mint px-3 py-2 text-sm font-medium text-white disabled:opacity-60" disabled={crudLoading || crudBatchForms.length === 0}>
                    <Save size={16} />
                    {crudLoading ? "Saving" : crudModalMode === "edit" ? "Save Changes" : "Save Records"}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
        )}

        {currentPage === "dashboard" && (
        <>
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(kpiLabels).map(([key, label]) => (
            <div key={key} className="border border-line bg-white p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
              <div className="mt-2 text-2xl font-semibold">{Number(overview[key] ?? 0).toLocaleString()}</div>
            </div>
          ))}
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-2">
          <ChartPanel title="MT by Tag Vehicle Class" data={charts.mt_by_vehicle_type_tag ?? []} />
          <ChartPanel title="SPBU by Tag Vehicle Class" data={charts.spbu_by_vehicle_type_tag ?? []} />
          <ChartPanel title="MT by Project Tag" data={charts.mt_by_project_tag ?? []} />
          <ChartPanel title="SPBU by Project Tag" data={charts.spbu_by_project_tag ?? []} />
          <ChartPanel title="SPBU per Shipment Distribution" data={charts.spbu_per_shipment_distribution ?? []} />
          <ChartPanel title="Product Distribution" data={charts.product_distribution ?? []} kind="pie" />
          <ChartPanel title="Reference Mapping Coverage" data={charts.reference_mapping_coverage ?? []} kind="pie" />
          <ChartPanel title="Data Quality Issues by Severity" data={charts.data_quality_issues_by_severity ?? []} kind="pie" />
          <ChartPanel title="MT vs SPBU Tag Coverage" data={charts.mt_vs_spbu_tag_coverage ?? []} kind="pie" />
          <ChartPanel title="GPS Reconstruction Coverage" data={charts.gps_reconstruction_coverage ?? []} kind="pie" />
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-3">
          <div className="border border-line bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-600">
              <GitBranch size={16} />
              Compatibility Summary
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="border border-line p-3">
                <CheckCircle2 className="mx-auto text-mint" size={18} />
                <div className="mt-2 text-xl font-semibold">{compatibility?.compatible ?? 0}</div>
                <div className="text-xs text-slate-500">Compatible</div>
              </div>
              <div className="border border-line p-3">
                <AlertTriangle className="mx-auto text-rust" size={18} />
                <div className="mt-2 text-xl font-semibold">{compatibility?.incompatible ?? 0}</div>
                <div className="text-xs text-slate-500">Incompatible</div>
              </div>
              <div className="border border-line p-3">
                <Route className="mx-auto text-amber" size={18} />
                <div className="mt-2 text-xl font-semibold">{compatibility?.insufficient_data ?? 0}</div>
                <div className="text-xs text-slate-500">Insufficient</div>
              </div>
            </div>
            <div className="mt-3 max-h-64 overflow-y-auto text-xs text-slate-700">
              {(compatibility?.examples ?? []).slice(0, 6).map((item, index) => (
                <div key={index} className="border-t border-line py-2">
                  {String(item.vehicle_registration)} to {String(item.spbu_code)}: {String(item.explanation)}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="mt-5 border border-line bg-white p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-600">
            <AlertTriangle size={16} />
            Data Quality Explorer
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {issues.map((issue) => (
              <div key={issue.issue_id} className="border border-line p-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-semibold">{issue.rule_code}</span>
                  <span className="text-xs uppercase text-rust">{issue.severity}</span>
                </div>
                <div className="mt-1 text-slate-600">
                  {issue.entity_type} {issue.entity_id ?? "UNKNOWN"}: {issue.description}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-5 border border-line bg-white p-4">
          <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Trip Reconstruction Validator</div>
          <p className="mt-2 text-sm text-slate-600">GPS staging, geofence, visit, reconciliation, and stop-sequence tables are present. The screen reports NO_GPS_SEQUENCE until the future GPS_data source mapping is supplied or synthetic GPS acceptance scenarios are loaded.</p>
        </section>
        </>
        )}

        {selectedAnalysis && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 py-6">
          <div className="flex max-h-[90vh] w-full max-w-6xl flex-col border border-line bg-white shadow-xl">
            <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
              <div>
                <div className="text-sm font-semibold uppercase tracking-wide text-slate-600">Loading Order Tag Analysis</div>
                <div className="mt-1 text-xs text-slate-500">
                  {selectedAnalysis.loading_order_number} · {formatDate(selectedAnalysis.loading_order_date)} · {selectedAnalysis.vehicle_registration ?? "-"} · {selectedAnalysis.spbu_code ?? selectedAnalysis.spbu_name ?? "-"}
                </div>
              </div>
              <button type="button" className="inline-flex h-9 w-9 items-center justify-center border border-line" onClick={() => setSelectedAnalysis(null)} title="Close detail">
                <X size={17} />
              </button>
            </div>
            <div className="grid gap-3 border-b border-line px-5 py-4 text-sm md:grid-cols-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Overall Result</div>
                <span className={`mt-2 inline-flex border px-2 py-1 text-xs font-semibold ${statusClass(selectedAnalysis.overall_status)}`}>{statusLabel(selectedAnalysis.overall_status)}</span>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Depot</div>
                <div className="mt-2">{selectedAnalysis.depot ?? "-"}</div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">MT Vehicle Class</div>
                <div className="mt-2">{selectedAnalysis.mt_vehicle_class ?? "-"}</div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">SPBU Maximum</div>
                <div className="mt-2">{selectedAnalysis.spbu_vehicle_class ?? "-"}</div>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="py-2 pr-3">Tag Type</th>
                    <th className="py-2 pr-3">SPBU Requirement</th>
                    <th className="py-2 pr-3">MT Tags</th>
                    <th className="py-2 pr-3">Missing</th>
                    <th className="py-2 pr-3">Result</th>
                    <th className="py-2 pr-3">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedAnalysis.details.map((detail) => (
                    <tr key={detail.tag_type} className="border-b border-line align-top">
                      <td className="py-3 pr-3 font-medium">
                        <div>{detail.tag_type_name}</div>
                        <div className="mt-1 text-xs font-normal text-slate-500">{detail.matching_rule.replace(/_/g, " ")}</div>
                      </td>
                      <td className="py-3 pr-3">
                        {detail.tag_type === "VEHICLE_CLASS" ? (
                          <span>Maximum {detail.spbu_required_tags[0] ?? "-"}</span>
                        ) : renderTags(detail.spbu_required_tags)}
                      </td>
                      <td className="py-3 pr-3">{renderTags(detail.mt_available_tags)}</td>
                      <td className="py-3 pr-3">{renderTags(detail.missing_tags, "missing")}</td>
                      <td className="py-3 pr-3">
                        <span className={`inline-flex border px-2 py-1 text-xs font-semibold ${statusClass(detail.result)}`}>{statusLabel(detail.result)}</span>
                      </td>
                      <td className="py-3 pr-3">
                        <div>{detail.reason}</div>
                        {detail.rule_expression && <div className="mt-1 text-xs text-slate-500">Rule: {detail.rule_expression}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        )}
        </div>
      </main>
    </div>
  );
}

export default App;
