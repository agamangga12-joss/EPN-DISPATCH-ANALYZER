import ReactECharts from "echarts-for-react";
import {
  Archive,
  BrainCircuit,
  CheckCircle2,
  Copy,
  Eye,
  Play,
  RefreshCw,
  Save,
  Scale,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { apiGet, apiSend } from "../lib/api";

type Depot = { depot_id: string; depot_name: string };
type Tab = "concentration" | "clustering" | "registry";
type Readiness = {
  depot_id: string;
  depot_name: string;
  depot_latitude: number | null;
  depot_longitude: number | null;
  master_compatibility_pass_percentage: number;
  compatibility_scope: string;
  compatibility_scope_description: string;
  scope_start_date: string | null;
  scope_end_date: string | null;
  evaluated_assignment_count: number;
  passed_assignment_count: number;
  failed_assignment_count: number;
  mismatch_assignment_count: number;
  data_issue_assignment_count: number;
  evaluated_pair_count: number;
  passed_pair_count: number;
  failed_pair_count: number;
  is_ready: boolean;
  status: string;
  requirement: string;
  status_counts: Record<string, number>;
  compatibility_issues_path: string;
};
type MTDistribution = {
  mt_id: string;
  mt_registration: string;
  mt_tags: string[];
  shipment_count: number;
  historical_share: number;
  historically_used: boolean;
};
type ConcentrationProfile = {
  spbu_id: string;
  spbu_code: string;
  spbu_name: string | null;
  spbu_tags: string[];
  shipment_observation_count: number;
  compatible_mt_count: number;
  historically_used_mt_count: number;
  utilization_breadth: number;
  dominant_mt_id: string | null;
  dominant_mt_registration: string | null;
  dominant_mt_share: number;
  hhi: number;
  entropy: number;
  normalized_entropy: number;
  raw_ml_anomaly_score: number | null;
  concentration_anomaly_score: number | null;
  concentration_classification: string;
  data_sufficiency_status: string;
  peer_statistics: Record<string, string | number>;
  mt_distribution: MTDistribution[];
};
type ConcentrationRun = {
  analysis_run_id: string;
  depot_id: string;
  depot_name: string;
  baseline_start_date: string;
  baseline_end_date: string;
  minimum_shipment_observation: number;
  algorithm_version: string;
  algorithm_parameters?: {
    n_estimators?: number;
    contamination?: string | number;
    random_seed?: number;
    classification_thresholds?: {
      moderate?: number;
      high?: number;
      investigation?: number;
    };
  };
  status: string;
  created_by: string;
  created_at: string | null;
  summary: Record<string, number>;
  profiles: ConcentrationProfile[];
};
type SavedConcentrationAnalysis = {
  id: string;
  name: string;
  depot_id: string;
  depot_name: string;
  analysis_run_id: string;
  baseline_start_date: string;
  baseline_end_date: string;
  minimum_shipment_observation: number;
  status: string;
  spbu_count: number;
  investigation_recommended_count: number;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  ui_state?: Record<string, unknown>;
  analysis_run?: ConcentrationRun;
};
type SavedConcentrationAnalysisResponse = {
  total: number;
  limit: number;
  offset: number;
  rows: SavedConcentrationAnalysis[];
};
type ShiftDefinition = {
  shift_id: string;
  name: string;
  start_time: string;
  end_time: string;
};
type DatasetSummary = {
  depot_name: string;
  training_start_date: string;
  training_end_date: string;
  shipment_count: number;
  source_shipment_count: number;
  spbu_count: number;
  mt_count: number;
  master_compatibility_pass_percentage: number;
  sufficient_history_spbu_count: number;
  active_master_spbu_count?: number;
  cold_start_active_spbu_count?: number;
  no_history_active_spbu_count?: number;
  insufficient_history_active_spbu_count?: number;
  excluded_insufficient_data_spbu_count: number;
  geocoded_training_spbu_count: number;
  missing_coordinate_training_spbu_count: number;
  pairing_edge_count: number;
  isolated_spbu_count: number;
  total_spbu: number;
  sufficient_count: number;
  marginal_count: number;
  insufficient_count: number;
  core_training_count: number;
  valid_coordinate_count: number;
  invalid_coordinate_count: number;
  geographic_coverage_percentage: number;
  geographic_proximity_enabled: boolean;
  geography_configuration: Record<string, string | number | boolean>;
  feature_weights: Record<string, number>;
};
type DataSufficiencyStatus = "SUFFICIENT" | "MARGINAL" | "INSUFFICIENT";
type ClusterAssignmentType =
  | "CORE_MEMBER"
  | "CORE_NOISE"
  | "MARGINAL_PROJECTED"
  | "MARGINAL_UNASSIGNED"
  | "INSUFFICIENT_UNASSIGNED";
type Assignment = {
  spbu_id: string;
  spbu_code: string;
  spbu_name: string | null;
  latitude?: number | null;
  longitude?: number | null;
  shipment_observation_count?: number;
  coverage_source?:
    | "BEHAVIORAL_HISTORY"
    | "MARGINAL_HISTORY"
    | "INSUFFICIENT_HISTORY"
    | "ACTIVE_MASTER_COLD_START";
  history_eligible?: boolean;
  data_sufficiency_score: number;
  data_sufficiency_status: DataSufficiencyStatus;
  data_sufficiency_components?: Record<string, number>;
  operating_day_count?: number;
  training_period_coverage?: number;
  shift_observation_coverage?: number;
  pairing_observation_count?: number;
  pairing_observation_strength?: number;
  last_operating_date?: string | null;
  recency_age_days?: number | null;
  cluster_id: number | null;
  cluster_label: string;
  cluster_assignment_type: ClusterAssignmentType;
  membership_probability: number | null;
  projected_cluster_id?: number | null;
  projection_confidence?: number | null;
  projection_status?: string;
  unassigned_reason?: string | null;
  is_noise: boolean;
  dominant_shift: string;
  vehicle_class?: number | null;
  key_tags: string[];
  geographic_data_status: "VALID" | "MISSING" | "INVALID";
  geographic_duplicate_coordinate?: boolean;
  nearest_spbu_distance_km?: number | null;
  average_k_nearest_distance_km?: number | null;
  median_k_nearest_distance_km?: number | null;
  local_spbu_density?: number | null;
  visualization_x: number | null;
  visualization_y: number | null;
};
type ClusterProfile = {
  cluster_id: number;
  cluster_label: string;
  cluster_size: number;
  historical_member_count: number;
  cold_start_member_count: number;
  projected_member_count?: number;
  no_history_member_count: number;
  training_spbu_percentage: number;
  common_tags: Array<{
    tag: string;
    member_count: number;
    member_share: number;
  }>;
  shift_distribution: Array<{
    shift_id: string;
    shift_name: string;
    share: number;
  }>;
  dominant_shift: string;
  top_internal_pairings: Array<{
    spbu_a_code: string;
    spbu_b_code: string;
    pair_count: number;
    pairing_strength: number;
  }>;
  average_membership_probability: number;
  low_confidence_member_count: number;
  evidence_scope?: string;
};
type TrainingResult = {
  summary: {
    training_spbu_count: number;
    historical_training_spbu_count: number;
    total_covered_spbu_count: number;
    cold_start_covered_spbu_count: number;
    no_history_spbu_count: number;
    insufficient_history_spbu_count: number;
    cluster_count: number;
    clustered_spbu_count: number;
    noise_spbu_count: number;
    average_membership_probability: number;
    total_spbu_count: number;
    sufficient_spbu_count: number;
    marginal_spbu_count: number;
    insufficient_spbu_count: number;
    core_training_spbu_count: number;
    core_cluster_member_count: number;
    core_noise_count: number;
    marginal_projected_count: number;
    marginal_unassigned_count: number;
    insufficient_unassigned_count: number;
    average_projection_confidence: number;
    valid_coordinate_count: number;
    invalid_coordinate_count: number;
    geographic_coverage_percentage: number;
  };
  assignments: Assignment[];
  cluster_profiles: ClusterProfile[];
  warnings: string[];
  saved: boolean;
};
type TrainingRun = {
  training_run_id: string;
  depot_id: string;
  depot_name: string;
  training_start_date: string;
  training_end_date: string;
  minimum_shipment_observation: number;
  status: string;
  dataset_summary: DatasetSummary;
  shift_definition_snapshot: ShiftDefinition[];
  result: TrainingResult | Record<string, never>;
  error_message: string | null;
};
type ModelSummary = {
  model_id: string;
  model_name: string;
  model_description: string | null;
  model_version: number;
  depot_id: string;
  depot_name: string;
  training_start_date: string;
  training_end_date: string;
  training_shipment_count: number;
  training_spbu_count: number;
  historical_training_spbu_count: number;
  total_covered_spbu_count: number;
  cold_start_covered_spbu_count: number;
  no_history_spbu_count: number;
  insufficient_history_spbu_count: number;
  minimum_shipment_observation: number;
  cluster_count: number;
  noise_spbu_count: number;
  average_membership_probability: number;
  total_spbu_count: number;
  sufficient_spbu_count: number;
  marginal_spbu_count: number;
  insufficient_spbu_count: number;
  core_training_spbu_count: number;
  core_cluster_member_count: number;
  marginal_projected_count: number;
  marginal_unassigned_count: number;
  insufficient_unassigned_count: number;
  average_projection_confidence: number;
  geographic_proximity_enabled: boolean;
  geographic_weight: number;
  valid_coordinate_count: number;
  invalid_coordinate_count: number;
  geographic_coverage_percentage: number;
  model_status: string;
  algorithm_version: string;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
};
type EvidenceFilter = "CORE" | "MARGINAL" | "ALL";
type ModelDetail = ModelSummary & {
  feature_weights: Record<string, number>;
  node2vec_parameters: Record<string, string | number>;
  umap_parameters: Record<string, string | number>;
  hdbscan_parameters: Record<string, string | number>;
  shift_definition_snapshot: ShiftDefinition[];
  assignments: Assignment[];
  cluster_profiles: ClusterProfile[];
  library_versions: Record<string, string>;
  data_sufficiency_configuration: Record<string, unknown>;
  geographic_configuration: Record<string, unknown>;
  projection_method: string;
  projection_parameters: Record<string, unknown>;
  minimum_projection_confidence: number;
};
type Comparison = {
  model_a: ModelSummary & {
    feature_weights: Record<string, number>;
    geographic_configuration: Record<string, string | number | boolean>;
  };
  model_b: ModelSummary & {
    feature_weights: Record<string, number>;
    geographic_configuration: Record<string, string | number | boolean>;
  };
  cluster_matches: Array<{
    model_a_cluster_id: number;
    model_b_cluster_id: number;
    jaccard_similarity: number;
    intersection_count: number;
  }>;
  stable_cluster_neighborhood_spbu_ids: string[];
  matched_cluster_changed_spbu_ids: string[];
  new_noise_spbu_ids: string[];
  noise_returning_to_cluster_spbu_ids: string[];
  cluster_splits: unknown[];
  cluster_merges: unknown[];
  methodology: string;
  data_maturity_transitions: Array<{
    transition: string;
    count: number;
    spbu_ids: string[];
  }>;
};

const CLUSTER_COLORS = [
  "#5470c6",
  "#91cc75",
  "#fac858",
  "#ee6666",
  "#73c0de",
  "#3ba272",
  "#fc8452",
  "#9a60b4",
  "#ea7ccc",
  "#2f4554",
  "#61a0a8",
  "#d48265",
  "#749f83",
  "#ca8622",
  "#bda29a",
  "#6e7074",
  "#546570",
  "#c4ccd3",
  "#0b73bf",
  "#b8d211",
  "#ef5b5b",
  "#7c3aed",
  "#0891b2",
  "#16a34a",
];

function clusterColor(clusterLabel: string, clusterLabels: string[]) {
  if (clusterLabel === "Noise / Unique Behavioral Pattern") return "#94a3b8";
  const clusteredLabels = clusterLabels.filter(
    (value) => value !== "Noise / Unique Behavioral Pattern",
  );
  return CLUSTER_COLORS[
    Math.max(0, clusteredLabels.indexOf(clusterLabel)) % CLUSTER_COLORS.length
  ];
}

const defaultShifts: ShiftDefinition[] = [
  {
    shift_id: "shift_1",
    name: "Shift 1",
    start_time: "00:00",
    end_time: "05:59",
  },
  {
    shift_id: "shift_2",
    name: "Shift 2",
    start_time: "06:00",
    end_time: "11:59",
  },
  {
    shift_id: "shift_3",
    name: "Shift 3",
    start_time: "12:00",
    end_time: "17:59",
  },
  {
    shift_id: "shift_4",
    name: "Shift 4",
    start_time: "18:00",
    end_time: "23:59",
  },
];
const defaultConfig = {
  feature_weights: { tag: 0.3, shift: 0.2, pairing: 0.3, geographic: 0.2 },
  data_sufficiency_configuration: {
    minimum_shipment_observations: 10,
    minimum_operating_days: 5,
    minimum_period_coverage: 0.25,
    minimum_shift_coverage: 0.6,
    minimum_pairing_evidence: 3,
    recency_configuration: { maximum_age_days: 30 },
    thresholds: { sufficient: 80, marginal: 50 },
  },
  geographic_configuration: {
    enabled: true,
    k_nearest_neighbors: 10,
    maximum_proximity_distance_km: 30,
  },
  projection_configuration: {
    method: "UMAP_NEAREST_CORE_CENTROID",
    minimum_confidence: 0.55,
    distance_scale_multiplier: 2,
  },
  node2vec_parameters: {
    dimensions: 16,
    walk_length: 20,
    num_walks: 40,
    p: 1,
    q: 1,
    window: 8,
    seed: 42,
  },
  umap_parameters: {
    n_neighbors: 15,
    n_components: 5,
    min_dist: 0.05,
    metric: "euclidean",
    random_state: 42,
  },
  hdbscan_parameters: {
    min_cluster_size: 5,
    min_samples: 3,
    metric: "euclidean",
    cluster_selection_method: "eom",
  },
  random_seed: 42,
};

function pct(value: number | null | undefined, digits = 1) {
  return value === null || value === undefined
    ? "-"
    : `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: digits })}%`;
}

function score(value: number | null | undefined) {
  return value === null || value === undefined
    ? "-"
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function dateTimeLabel(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : "-";
}

function label(value: string) {
  return value.replace(/_/g, " ");
}

function formatTags(tags: string[] | null | undefined) {
  return tags?.length ? tags.join(", ") : "-";
}

function escapeTooltip(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function hasHistoricalEvidence(assignment: Assignment) {
  return assignment.data_sufficiency_status === "SUFFICIENT";
}

function evidenceStatus(assignment: Assignment) {
  return `${assignment.data_sufficiency_status} · ${label(assignment.cluster_assignment_type)}`;
}

function confidenceLabel(assignment: Assignment) {
  return assignment.cluster_assignment_type.startsWith("MARGINAL")
    ? "Projection Confidence"
    : assignment.cluster_assignment_type.startsWith("CORE")
      ? "Membership Probability"
      : "Not applicable";
}

function assignmentConfidence(assignment: Assignment) {
  return assignment.cluster_assignment_type.startsWith("MARGINAL")
    ? assignment.projection_confidence
    : assignment.cluster_assignment_type.startsWith("CORE")
      ? assignment.membership_probability
      : null;
}

function badgeClass(value: string) {
  if (
    [
      "READY_FOR_MACHINE_LEARNING",
      "ACTIVE",
      "NORMAL",
      "COMPLETED",
      "DATASET_READY",
      "SUFFICIENT",
      "CORE_MEMBER",
      "PROJECTED",
    ].includes(value)
  )
    return "border-mint bg-mint/10 text-mint";
  if (
    [
      "MODERATE_CONCENTRATION",
      "SAVED",
      "ARCHIVED",
      "MARGINAL",
      "MARGINAL_PROJECTED",
      "MARGINAL_UNASSIGNED",
    ].includes(value)
  )
    return "border-amber bg-amber/10 text-amber";
  if (
    [
      "INSUFFICIENT_DATA",
      "NOISE",
      "Noise / Unique Behavioral Pattern",
      "INSUFFICIENT",
      "INSUFFICIENT_UNASSIGNED",
      "CORE_NOISE",
    ].includes(value)
  )
    return "border-slate-300 bg-slate-50 text-slate-600";
  return "border-rust bg-rust/10 text-rust";
}

function Metric({
  title,
  value,
  hint,
}: {
  title: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="border border-line bg-white p-4" title={hint}>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </div>
      <div className="mt-2 text-2xl font-semibold text-petroink">{value}</div>
    </div>
  );
}

type MappedAssignment = Assignment & { latitude: number; longitude: number };
type DepotLocation = {
  depot_id: string;
  depot_name: string;
  latitude: number | null;
  longitude: number | null;
};
type MappedDepotLocation = DepotLocation & {
  latitude: number;
  longitude: number;
};
type GeographicMapFocus = "DEPOT_REGION" | "ALL";

const DEPOT_FOCUS_RADIUS_KM = 150;

function hasGeographicCoordinates(
  assignment: Assignment,
): assignment is MappedAssignment {
  return (
    typeof assignment.latitude === "number" &&
    Number.isFinite(assignment.latitude) &&
    assignment.latitude >= -90 &&
    assignment.latitude <= 90 &&
    typeof assignment.longitude === "number" &&
    Number.isFinite(assignment.longitude) &&
    assignment.longitude >= -180 &&
    assignment.longitude <= 180
  );
}

function hasDepotCoordinates(
  depot: DepotLocation | null,
): depot is MappedDepotLocation {
  return (
    Boolean(depot) &&
    typeof depot?.latitude === "number" &&
    Number.isFinite(depot.latitude) &&
    depot.latitude >= -90 &&
    depot.latitude <= 90 &&
    typeof depot.longitude === "number" &&
    Number.isFinite(depot.longitude) &&
    depot.longitude >= -180 &&
    depot.longitude <= 180
  );
}

function geographicDistanceKm(
  origin: { latitude: number; longitude: number },
  destination: { latitude: number; longitude: number },
) {
  const degreesToRadians = (value: number) => (value * Math.PI) / 180;
  const earthRadiusKm = 6371;
  const latitudeDelta = degreesToRadians(
    destination.latitude - origin.latitude,
  );
  const longitudeDelta = degreesToRadians(
    destination.longitude - origin.longitude,
  );
  const originLatitude = degreesToRadians(origin.latitude);
  const destinationLatitude = degreesToRadians(destination.latitude);
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(originLatitude) *
      Math.cos(destinationLatitude) *
      Math.sin(longitudeDelta / 2) ** 2;

  return (
    earthRadiusKm *
    2 *
    Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine))
  );
}

function FitGeographicBounds({
  assignments,
  depot,
  focus,
}: {
  assignments: MappedAssignment[];
  depot: MappedDepotLocation | null;
  focus: GeographicMapFocus;
}) {
  const map = useMap();

  useEffect(() => {
    const focusedAssignments =
      focus === "DEPOT_REGION" && depot
        ? assignments.filter(
            (assignment) =>
              geographicDistanceKm(depot, assignment) <= DEPOT_FOCUS_RADIUS_KM,
          )
        : assignments;
    const assignmentsForBounds = focusedAssignments.length
      ? focusedAssignments
      : assignments;
    const positions = assignmentsForBounds.map(
      (assignment) =>
        [assignment.latitude, assignment.longitude] as [number, number],
    );
    if (depot) positions.push([depot.latitude, depot.longitude]);
    if (!positions.length) return;
    map.invalidateSize({ animate: false });
    map.fitBounds(positions, { padding: [28, 28], maxZoom: 12 });
  }, [assignments, depot, focus, map]);

  return null;
}

function GeographicClusterMap({
  assignments,
  depot,
}: {
  assignments: Assignment[];
  depot: DepotLocation | null;
}) {
  const mappedAssignments = useMemo(
    () => assignments.filter(hasGeographicCoordinates),
    [assignments],
  );
  const mappedDepot = hasDepotCoordinates(depot) ? depot : null;
  const depotRegionAssignments = useMemo(
    () =>
      mappedDepot
        ? mappedAssignments.filter(
            (assignment) =>
              geographicDistanceKm(mappedDepot, assignment) <=
              DEPOT_FOCUS_RADIUS_KM,
          )
        : [],
    [mappedAssignments, mappedDepot],
  );
  const defaultMapFocus: GeographicMapFocus =
    mappedDepot &&
    mappedAssignments.length > 250 &&
    depotRegionAssignments.length
      ? "DEPOT_REGION"
      : "ALL";
  const [mapFocus, setMapFocus] = useState<GeographicMapFocus>(defaultMapFocus);
  const clusterLabels = useMemo(
    () =>
      Array.from(
        new Set(
          mappedAssignments.map((assignment) => assignment.cluster_label),
        ),
      ),
    [mappedAssignments],
  );
  const missingCoordinateCount = assignments.length - mappedAssignments.length;

  useEffect(() => {
    setMapFocus(defaultMapFocus);
  }, [assignments, defaultMapFocus]);

  return (
    <div className="border border-line bg-white p-4 lg:col-span-2">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
            Geographic Cluster Map
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            Master SPBU and Master Depot coordinates. Haversine proximity is a
            clustering feature when enabled; this is not road distance, travel
            time, or route feasibility.
          </p>
        </div>
        <div className="text-xs text-slate-500">
          {mappedAssignments.length.toLocaleString()} SPBU mapped ·{" "}
          {missingCoordinateCount.toLocaleString()} missing ·{" "}
          {mappedDepot ? "Depot mapped" : "Depot coordinates missing"}
        </div>
      </div>
      {mappedAssignments.length || mappedDepot ? (
        <>
          <div className="mt-3 flex flex-col gap-2 border border-line bg-slate-50 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-xs text-slate-600">
              Semua marker tetap berada pada koordinat Master SPBU; pilihan
              berikut hanya mengubah area tampilan peta.
            </div>
            <div
              className="flex shrink-0 flex-wrap items-center gap-2"
              aria-label="Geographic map focus"
            >
              <button
                type="button"
                className={`border px-3 py-1.5 text-xs font-semibold ${mapFocus === "DEPOT_REGION" ? "border-petroblue bg-petroblue text-white" : "border-line bg-white text-petroink hover:border-petroblue"}`}
                disabled={!mappedDepot || !depotRegionAssignments.length}
                onClick={() => setMapFocus("DEPOT_REGION")}
              >
                Fokus Depot ≤ {DEPOT_FOCUS_RADIUS_KM} km (
                {depotRegionAssignments.length.toLocaleString()})
              </button>
              <button
                type="button"
                className={`border px-3 py-1.5 text-xs font-semibold ${mapFocus === "ALL" ? "border-petroblue bg-petroblue text-white" : "border-line bg-white text-petroink hover:border-petroblue"}`}
                onClick={() => setMapFocus("ALL")}
              >
                Tampilkan Semua ({mappedAssignments.length.toLocaleString()})
              </button>
            </div>
          </div>
          <div
            className="relative z-0 mt-3 overflow-hidden rounded-2xl border border-line"
            role="region"
            aria-label="Geographic cluster map using Master SPBU and Master Depot coordinates"
          >
            <MapContainer
              center={
                mappedDepot
                  ? [mappedDepot.latitude, mappedDepot.longitude]
                  : [
                      mappedAssignments[0].latitude,
                      mappedAssignments[0].longitude,
                    ]
              }
              zoom={8}
              scrollWheelZoom
              preferCanvas
              className="h-[500px] w-full bg-slate-100"
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <FitGeographicBounds
                assignments={mappedAssignments}
                depot={mappedDepot}
                focus={mapFocus}
              />
              {mappedAssignments.map((assignment) => (
                <CircleMarker
                  key={assignment.spbu_id}
                  center={[assignment.latitude, assignment.longitude]}
                  radius={assignment.is_noise ? 5 : 6}
                  pathOptions={{
                    color:
                      assignment.data_sufficiency_status === "SUFFICIENT"
                        ? "#ffffff"
                        : assignment.data_sufficiency_status === "MARGINAL"
                          ? "#f59e0b"
                          : "#64748b",
                    fillColor:
                      (assignment.shipment_observation_count ?? 0) === 0 &&
                      !hasHistoricalEvidence(assignment)
                        ? "#e2e8f0"
                        : clusterColor(assignment.cluster_label, clusterLabels),
                    fillOpacity:
                      assignment.data_sufficiency_status === "SUFFICIENT"
                        ? 0.88
                        : assignment.data_sufficiency_status === "MARGINAL"
                          ? 0.55
                          : 0.25,
                    weight: hasHistoricalEvidence(assignment) ? 1.5 : 2.5,
                  }}
                >
                  <Tooltip direction="top" opacity={1}>
                    <div className="min-w-60 text-sm text-petroink">
                      <div className="font-semibold">
                        {assignment.spbu_name || assignment.spbu_code}
                      </div>
                      <div className="text-xs text-slate-500">
                        SPBU {assignment.spbu_code} · {assignment.cluster_label}
                      </div>
                      <div
                        className={`mt-2 font-semibold ${hasHistoricalEvidence(assignment) ? "text-mint" : "text-amber"}`}
                      >
                        {evidenceStatus(assignment)}
                      </div>
                      <div>
                        <span className="font-semibold">
                          Historical observations:
                        </span>{" "}
                        {assignment.shipment_observation_count ?? 0}
                      </div>
                      <div>
                        <span className="font-semibold">
                          {confidenceLabel(assignment)}:
                        </span>{" "}
                        {pct(assignmentConfidence(assignment))}
                      </div>
                      <div className="mt-2">
                        <span className="font-semibold">Shift:</span>{" "}
                        {assignment.dominant_shift}
                      </div>
                      <div>
                        <span className="font-semibold">Vehicle tag:</span>{" "}
                        {assignment.vehicle_class === null ||
                        assignment.vehicle_class === undefined
                          ? "-"
                          : `Vehicle Class ${assignment.vehicle_class}`}
                      </div>
                      <div className="mt-1">
                        <span className="font-semibold">Other tags:</span>{" "}
                        {assignment.key_tags.join(", ") || "-"}
                      </div>
                    </div>
                  </Tooltip>
                  <Popup>
                    <div className="min-w-48 text-sm text-petroink">
                      <div className="font-semibold">
                        {assignment.spbu_code} · {assignment.spbu_name}
                      </div>
                      <div className="mt-1">{assignment.cluster_label}</div>
                      <div
                        className={`mt-1 font-semibold ${hasHistoricalEvidence(assignment) ? "text-mint" : "text-amber"}`}
                      >
                        {evidenceStatus(assignment)}
                      </div>
                      <div>
                        Historical observations:{" "}
                        {assignment.shipment_observation_count ?? 0}
                      </div>
                      <div>
                        {confidenceLabel(assignment)}:{" "}
                        {pct(assignmentConfidence(assignment))}
                      </div>
                      <div>Dominant shift: {assignment.dominant_shift}</div>
                      <div>
                        Vehicle tag:{" "}
                        {assignment.vehicle_class === null ||
                        assignment.vehicle_class === undefined
                          ? "-"
                          : `Vehicle Class ${assignment.vehicle_class}`}
                      </div>
                      <div>
                        Other tags: {assignment.key_tags.join(", ") || "-"}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {assignment.latitude.toFixed(5)},{" "}
                        {assignment.longitude.toFixed(5)}
                      </div>
                    </div>
                  </Popup>
                </CircleMarker>
              ))}
              {mappedDepot && (
                <CircleMarker
                  center={[mappedDepot.latitude, mappedDepot.longitude]}
                  radius={11}
                  pathOptions={{
                    color: "#facc15",
                    fillColor: "#0f2942",
                    fillOpacity: 1,
                    weight: 4,
                  }}
                >
                  <Tooltip direction="top" opacity={1}>
                    <div className="min-w-48 text-sm text-petroink">
                      <div className="font-semibold">
                        Depot · {mappedDepot.depot_name}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        Master Depot position
                      </div>
                      <div className="mt-1">
                        {mappedDepot.latitude.toFixed(5)},{" "}
                        {mappedDepot.longitude.toFixed(5)}
                      </div>
                    </div>
                  </Tooltip>
                  <Popup>
                    <div className="min-w-48 text-sm text-petroink">
                      <div className="font-semibold">
                        Depot · {mappedDepot.depot_name}
                      </div>
                      <div className="mt-1">Coordinates from Master Depot</div>
                      <div className="text-xs text-slate-500">
                        {mappedDepot.latitude.toFixed(5)},{" "}
                        {mappedDepot.longitude.toFixed(5)}
                      </div>
                    </div>
                  </Popup>
                </CircleMarker>
              )}
            </MapContainer>
          </div>
          <div className="mt-3 flex max-h-24 flex-wrap gap-x-4 gap-y-2 overflow-y-auto text-xs text-slate-600">
            {mappedDepot && (
              <div className="inline-flex items-center gap-1.5 font-semibold text-petroink">
                <span className="h-3 w-3 rounded-full border-2 border-yellow-400 bg-petroink" />
                Depot
              </div>
            )}
            <div className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full border border-white bg-petroblue" />
              Sufficient core evidence
            </div>
            <div className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-full border-2 border-petroblue bg-white" />
              Marginal / insufficient (outlined)
            </div>
            {clusterLabels.map((clusterLabel) => (
              <div
                className="inline-flex items-center gap-1.5"
                key={clusterLabel}
              >
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{
                    backgroundColor: clusterColor(clusterLabel, clusterLabels),
                  }}
                />
                {clusterLabel}
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="mt-3 border border-dashed border-line bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
          Neither the selected depot nor any training SPBU has complete master
          latitude/longitude coordinates.
        </div>
      )}
    </div>
  );
}

export function MachineLearningIntelligencePage({
  depots,
}: {
  depots: Depot[];
}) {
  const [tab, setTab] = useState<Tab>("concentration");
  const [depotId, setDepotId] = useState(depots[0]?.depot_id || "");
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<{
    min_date: string | null;
    max_date: string | null;
  }>({ min_date: null, max_date: null });

  const [baselineStart, setBaselineStart] = useState("");
  const [baselineEnd, setBaselineEnd] = useState("");
  const [engineAMinimum, setEngineAMinimum] = useState("10");
  const [engineAAdvanced, setEngineAAdvanced] = useState(false);
  const [engineAEstimators, setEngineAEstimators] = useState("200");
  const [engineAContamination, setEngineAContamination] = useState("auto");
  const [engineASeed, setEngineASeed] = useState("42");
  const [engineAThresholds, setEngineAThresholds] = useState({
    moderate: "40",
    high: "60",
    investigation: "80",
  });
  const [engineALoading, setEngineALoading] = useState(false);
  const [concentrationRun, setConcentrationRun] =
    useState<ConcentrationRun | null>(null);
  const [savedConcentrationAnalyses, setSavedConcentrationAnalyses] = useState<
    SavedConcentrationAnalysis[]
  >([]);
  const [savedConcentrationTotal, setSavedConcentrationTotal] = useState(0);
  const [savedConcentrationOffset, setSavedConcentrationOffset] = useState(0);
  const [savedConcentrationLimit, setSavedConcentrationLimit] = useState(5);
  const [savedConcentrationLoading, setSavedConcentrationLoading] =
    useState(false);
  const [selectedSavedConcentrationId, setSelectedSavedConcentrationId] =
    useState("");
  const [concentrationSaveDialog, setConcentrationSaveDialog] = useState(false);
  const [concentrationLoadDialog, setConcentrationLoadDialog] = useState(false);
  const [concentrationSaveName, setConcentrationSaveName] = useState("");
  const [concentrationSavedMessage, setConcentrationSavedMessage] =
    useState("");
  const [classificationFilter, setClassificationFilter] = useState("ALL");
  const [minimumScore, setMinimumScore] = useState("0");
  const [minimumObservationFilter, setMinimumObservationFilter] = useState("0");
  const [spbuSearch, setSpbuSearch] = useState("");
  const [scoreDirection, setScoreDirection] = useState<"desc" | "asc">("desc");
  const [concentrationPage, setConcentrationPage] = useState(0);
  const [concentrationPageSize, setConcentrationPageSize] = useState(10);
  const [selectedConcentration, setSelectedConcentration] =
    useState<ConcentrationProfile | null>(null);

  const [trainingStart, setTrainingStart] = useState("");
  const [trainingEnd, setTrainingEnd] = useState("");
  const [trainingMinimum, setTrainingMinimum] = useState("10");
  const [shiftDefinitions, setShiftDefinitions] =
    useState<ShiftDefinition[]>(defaultShifts);
  const [trainingConfig, setTrainingConfig] = useState(defaultConfig);
  const [engineBAdvanced, setEngineBAdvanced] = useState(false);
  const [engineBLoading, setEngineBLoading] = useState(false);
  const [trainingRun, setTrainingRun] = useState<TrainingRun | null>(null);
  const [clusterMembershipPage, setClusterMembershipPage] = useState(0);
  const [clusterMembershipPageSize, setClusterMembershipPageSize] =
    useState(10);
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>("CORE");
  const [sufficiencyFilter, setSufficiencyFilter] = useState("ALL");
  const [assignmentTypeFilter, setAssignmentTypeFilter] = useState("ALL");
  const [clusterFilter, setClusterFilter] = useState("ALL");
  const [noiseFilter, setNoiseFilter] = useState("ALL");
  const [minimumProjectionConfidence, setMinimumProjectionConfidence] =
    useState("0");
  const [minimumMembershipProbability, setMinimumMembershipProbability] =
    useState("0");
  const [geographicStatusFilter, setGeographicStatusFilter] = useState("ALL");
  const [clusterSpbuSearch, setClusterSpbuSearch] = useState("");
  const [selectedAssignment, setSelectedAssignment] =
    useState<Assignment | null>(null);
  const [selectedCluster, setSelectedCluster] = useState<ClusterProfile | null>(
    null,
  );
  const [saveDialog, setSaveDialog] = useState(false);
  const [modelName, setModelName] = useState("");
  const [modelDescription, setModelDescription] = useState("");

  const [models, setModels] = useState<ModelSummary[]>([]);
  const [registryLoading, setRegistryLoading] = useState(false);
  const [openedModel, setOpenedModel] = useState<ModelDetail | null>(null);
  const [selectedClusteringModelId, setSelectedClusteringModelId] =
    useState("");
  const [clusteringLoadDialog, setClusteringLoadDialog] = useState(false);
  const [clusteringSavedMessage, setClusteringSavedMessage] = useState("");
  const [clusteringSavedPage, setClusteringSavedPage] = useState(0);
  const [clusteringSavedPageSize, setClusteringSavedPageSize] = useState(5);
  const [displayedSavedModel, setDisplayedSavedModel] =
    useState<ModelDetail | null>(null);
  const [clusteringModelLoading, setClusteringModelLoading] = useState(false);
  const [compareA, setCompareA] = useState("");
  const [compareB, setCompareB] = useState("");
  const [comparison, setComparison] = useState<Comparison | null>(null);

  useEffect(() => {
    if (!depotId && depots.length) setDepotId(depots[0].depot_id);
  }, [depotId, depots]);

  useEffect(() => {
    if (!depotId) return;
    setReadinessLoading(true);
    setReadiness(null);
    setConcentrationRun(null);
    setTrainingRun(null);
    setDisplayedSavedModel(null);
    setSelectedClusteringModelId("");
    setModels([]);
    setSavedConcentrationAnalyses([]);
    setSavedConcentrationTotal(0);
    setSavedConcentrationOffset(0);
    setSelectedSavedConcentrationId("");
    setConcentrationSavedMessage("");
    setClusteringSavedMessage("");
    setError(null);
    Promise.all([
      apiGet<Readiness>(
        `/api/v1/phase5/readiness?depot_id=${encodeURIComponent(depotId)}`,
      ),
      apiGet<{ min_date: string | null; max_date: string | null }>(
        `/api/v1/affinity-intelligence/available-dates?depot_id=${encodeURIComponent(depotId)}`,
      ),
    ])
      .then(([gate, dates]) => {
        setReadiness(gate);
        setDateRange(dates);
        if (dates.min_date && dates.max_date) {
          setBaselineStart(dates.min_date);
          setBaselineEnd(dates.max_date);
          setTrainingStart(dates.min_date);
          setTrainingEnd(dates.max_date);
        }
      })
      .catch((reason: unknown) =>
        setError(
          reason instanceof Error
            ? reason.message
            : "Failed to load Phase 5 readiness.",
        ),
      )
      .finally(() => setReadinessLoading(false));
  }, [depotId]);

  useEffect(() => {
    if (!depotId) return;
    void refreshSavedConcentrationAnalyses(
      savedConcentrationOffset,
      savedConcentrationLimit,
      depotId,
    );
  }, [depotId, savedConcentrationLimit, savedConcentrationOffset]);

  useEffect(() => {
    if (tab === "registry" || tab === "clustering") void refreshRegistry();
  }, [tab, depotId]);

  async function refreshReadiness() {
    if (!depotId) return;
    setReadinessLoading(true);
    try {
      setReadiness(
        await apiGet<Readiness>(
          `/api/v1/phase5/readiness?depot_id=${encodeURIComponent(depotId)}`,
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Failed to refresh readiness.",
      );
    } finally {
      setReadinessLoading(false);
    }
  }

  async function runEngineA() {
    if (!readiness?.is_ready || !baselineStart || !baselineEnd) return;
    setEngineALoading(true);
    setError(null);
    try {
      const payload = await apiSend<ConcentrationRun>(
        "/api/v1/phase5/engine-a/analyze",
        "POST",
        {
          depot_id: depotId,
          baseline_start_date: baselineStart,
          baseline_end_date: baselineEnd,
          minimum_shipment_observation: Number(engineAMinimum),
          parameters: {
            n_estimators: Number(engineAEstimators),
            contamination:
              engineAContamination === "auto"
                ? "auto"
                : Number(engineAContamination),
            random_seed: Number(engineASeed),
            classification_thresholds: {
              moderate: Number(engineAThresholds.moderate),
              high: Number(engineAThresholds.high),
              investigation: Number(engineAThresholds.investigation),
            },
          },
        },
      );
      setConcentrationRun(payload);
      setConcentrationSavedMessage(
        "Analysis completed. Use Save to store this result in the saved analysis list.",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Concentration analysis failed.",
      );
    } finally {
      setEngineALoading(false);
    }
  }

  async function refreshSavedConcentrationAnalyses(
    nextOffset = savedConcentrationOffset,
    nextLimit = savedConcentrationLimit,
    targetDepotId = depotId,
  ) {
    setSavedConcentrationLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(nextLimit),
        offset: String(nextOffset),
      });
      if (targetDepotId) params.set("depot_id", targetDepotId);
      const payload = await apiGet<SavedConcentrationAnalysisResponse>(
        `/api/v1/phase5/engine-a/saved-analyses?${params.toString()}`,
      );
      setSavedConcentrationAnalyses(payload.rows);
      setSavedConcentrationTotal(payload.total);
      setSavedConcentrationOffset(payload.offset);
      setSavedConcentrationLimit(payload.limit);
      setSelectedSavedConcentrationId((current) =>
        payload.rows.some((row) => row.id === current)
          ? current
          : payload.rows[0]?.id ?? "",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Failed to load saved concentration analyses.",
      );
    } finally {
      setSavedConcentrationLoading(false);
    }
  }

  function openConcentrationSaveDialog() {
    if (!concentrationRun || concentrationRun.status !== "COMPLETED") {
      setError("Run and complete a concentration analysis before saving it.");
      return;
    }
    setConcentrationSaveName("");
    setConcentrationSaveDialog(true);
    setError(null);
  }

  function openConcentrationLoadDialog() {
    if (!savedConcentrationAnalyses.length) {
      setError("No saved concentration analysis is available for this depot.");
      return;
    }
    setSelectedSavedConcentrationId(
      (current) => current || savedConcentrationAnalyses[0]?.id || "",
    );
    setConcentrationLoadDialog(true);
    setError(null);
  }

  async function saveCurrentConcentrationAnalysis() {
    if (!concentrationRun || !concentrationSaveName.trim()) return;
    setSavedConcentrationLoading(true);
    setError(null);
    try {
      const saved = await apiSend<SavedConcentrationAnalysis>(
        "/api/v1/phase5/engine-a/saved-analyses",
        "POST",
        {
          name: concentrationSaveName.trim(),
          analysis_run_id: concentrationRun.analysis_run_id,
          ui_state: {
            classification_filter: classificationFilter,
            minimum_score: minimumScore,
            minimum_observation_filter: minimumObservationFilter,
            spbu_search: spbuSearch,
            score_direction: scoreDirection,
            table_page_size: concentrationPageSize,
          },
        },
      );
      setConcentrationSavedMessage(`Saved concentration analysis: ${saved.name}.`);
      setConcentrationSaveDialog(false);
      setConcentrationSaveName("");
      setSavedConcentrationOffset(0);
      await refreshSavedConcentrationAnalyses(0, savedConcentrationLimit, depotId);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Failed to save concentration analysis.",
      );
    } finally {
      setSavedConcentrationLoading(false);
    }
  }

  async function loadSavedConcentrationAnalysis(
    savedAnalysisId = selectedSavedConcentrationId,
  ) {
    if (!savedAnalysisId) return;
    setSavedConcentrationLoading(true);
    setError(null);
    try {
      const saved = await apiGet<SavedConcentrationAnalysis>(
        `/api/v1/phase5/engine-a/saved-analyses/${encodeURIComponent(savedAnalysisId)}`,
      );
      if (!saved.analysis_run) {
        throw new Error("Saved analysis does not contain a concentration result.");
      }
      const run = saved.analysis_run;
      const uiState = saved.ui_state ?? {};
      const thresholds = run.algorithm_parameters?.classification_thresholds;
      setConcentrationRun(run);
      setBaselineStart(run.baseline_start_date);
      setBaselineEnd(run.baseline_end_date);
      setEngineAMinimum(String(run.minimum_shipment_observation));
      setEngineAEstimators(String(run.algorithm_parameters?.n_estimators ?? 200));
      setEngineAContamination(String(run.algorithm_parameters?.contamination ?? "auto"));
      setEngineASeed(String(run.algorithm_parameters?.random_seed ?? 42));
      setEngineAThresholds({
        moderate: String(thresholds?.moderate ?? 40),
        high: String(thresholds?.high ?? 60),
        investigation: String(thresholds?.investigation ?? 80),
      });
      setClassificationFilter(String(uiState.classification_filter ?? "ALL"));
      setMinimumScore(String(uiState.minimum_score ?? "0"));
      setMinimumObservationFilter(
        String(uiState.minimum_observation_filter ?? "0"),
      );
      setSpbuSearch(String(uiState.spbu_search ?? ""));
      setScoreDirection(uiState.score_direction === "asc" ? "asc" : "desc");
      setConcentrationPageSize(Number(uiState.table_page_size ?? 10));
      setConcentrationPage(0);
      setSelectedConcentration(null);
      setSelectedSavedConcentrationId(saved.id);
      setConcentrationSavedMessage(`Loaded concentration analysis: ${saved.name}.`);
      setConcentrationLoadDialog(false);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Failed to load saved concentration analysis.",
      );
    } finally {
      setSavedConcentrationLoading(false);
    }
  }

  async function deleteSavedConcentrationAnalysis(
    saved: SavedConcentrationAnalysis,
  ) {
    if (!window.confirm(`Delete saved concentration analysis "${saved.name}"?`))
      return;
    setSavedConcentrationLoading(true);
    setError(null);
    try {
      await apiSend(
        `/api/v1/phase5/engine-a/saved-analyses/${encodeURIComponent(saved.id)}`,
        "DELETE",
      );
      setConcentrationSavedMessage(
        `Deleted saved concentration analysis: ${saved.name}.`,
      );
      const nextOffset =
        savedConcentrationAnalyses.length === 1
          ? Math.max(0, savedConcentrationOffset - savedConcentrationLimit)
          : savedConcentrationOffset;
      setSavedConcentrationOffset(nextOffset);
      await refreshSavedConcentrationAnalyses(
        nextOffset,
        savedConcentrationLimit,
        depotId,
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Failed to delete saved concentration analysis.",
      );
    } finally {
      setSavedConcentrationLoading(false);
    }
  }

  const filteredConcentration = useMemo(() => {
    if (!concentrationRun) return [];
    const needle = spbuSearch.trim().toLowerCase();
    return [...concentrationRun.profiles]
      .filter(
        (row) =>
          classificationFilter === "ALL" ||
          row.concentration_classification === classificationFilter,
      )
      .filter((row) =>
        row.concentration_anomaly_score === null
          ? Number(minimumScore || 0) <= 0
          : row.concentration_anomaly_score >= Number(minimumScore || 0),
      )
      .filter(
        (row) =>
          row.shipment_observation_count >=
          Number(minimumObservationFilter || 0),
      )
      .filter(
        (row) =>
          !needle ||
          `${row.spbu_code} ${row.spbu_name ?? ""}`
            .toLowerCase()
            .includes(needle),
      )
      .sort((left, right) => {
        const difference =
          (left.concentration_anomaly_score ?? -1) -
          (right.concentration_anomaly_score ?? -1);
        return scoreDirection === "desc" ? -difference : difference;
      });
  }, [
    classificationFilter,
    concentrationRun,
    minimumObservationFilter,
    minimumScore,
    scoreDirection,
    spbuSearch,
  ]);

  useEffect(() => {
    setConcentrationPage(0);
  }, [
    classificationFilter,
    concentrationRun?.analysis_run_id,
    minimumObservationFilter,
    minimumScore,
    scoreDirection,
    spbuSearch,
  ]);

  const concentrationPageCount = Math.max(
    1,
    Math.ceil(filteredConcentration.length / concentrationPageSize),
  );
  const concentrationPageRows = useMemo(
    () =>
      filteredConcentration.slice(
        concentrationPage * concentrationPageSize,
        (concentrationPage + 1) * concentrationPageSize,
      ),
    [concentrationPage, concentrationPageSize, filteredConcentration],
  );
  const concentrationRangeStart =
    filteredConcentration.length === 0
      ? 0
      : concentrationPage * concentrationPageSize + 1;
  const concentrationRangeEnd = Math.min(
    filteredConcentration.length,
    (concentrationPage + 1) * concentrationPageSize,
  );
  const savedConcentrationShowingStart =
    savedConcentrationTotal === 0 ? 0 : savedConcentrationOffset + 1;
  const savedConcentrationShowingEnd = Math.min(
    savedConcentrationOffset + savedConcentrationLimit,
    savedConcentrationTotal,
  );
  const savedConcentrationPage =
    Math.floor(savedConcentrationOffset / savedConcentrationLimit) + 1;
  const savedConcentrationPageCount = Math.max(
    1,
    Math.ceil(savedConcentrationTotal / savedConcentrationLimit),
  );

  const concentrationChartRows = useMemo(
    () =>
      (concentrationRun?.profiles ?? []).filter(
        (row) => row.concentration_anomaly_score !== null,
      ),
    [concentrationRun],
  );

  function updateWeight(
    key: "tag" | "shift" | "pairing" | "geographic",
    value: string,
  ) {
    setTrainingConfig((current) => ({
      ...current,
      feature_weights: { ...current.feature_weights, [key]: Number(value) },
    }));
  }

  function toggleGeography(enabled: boolean) {
    setTrainingConfig((current) => {
      if (enabled) {
        return {
          ...current,
          geographic_configuration: {
            ...current.geographic_configuration,
            enabled: true,
          },
          feature_weights: {
            tag: 0.3,
            shift: 0.2,
            pairing: 0.3,
            geographic: 0.2,
          },
        };
      }
      return {
        ...current,
        geographic_configuration: {
          ...current.geographic_configuration,
          enabled: false,
        },
        feature_weights: {
          tag: 0.375,
          shift: 0.25,
          pairing: 0.375,
          geographic: 0,
        },
      };
    });
  }

  const weightTotal = Object.values(trainingConfig.feature_weights).reduce(
    (total, value) => total + value,
    0,
  );

  async function prepareDataset() {
    if (!readiness?.is_ready || !trainingStart || !trainingEnd) return;
    setEngineBLoading(true);
    setError(null);
    setTrainingRun(null);
    setDisplayedSavedModel(null);
    try {
      setTrainingRun(
        await apiSend<TrainingRun>(
          "/api/v1/phase5/engine-b/prepare-dataset",
          "POST",
          {
            depot_id: depotId,
            training_start_date: trainingStart,
            training_end_date: trainingEnd,
            minimum_shipment_observation: Number(trainingMinimum),
            shift_definitions: shiftDefinitions,
            data_sufficiency_configuration: {
              ...trainingConfig.data_sufficiency_configuration,
              minimum_shipment_observations: Number(trainingMinimum),
            },
            geographic_configuration: trainingConfig.geographic_configuration,
            feature_weights: trainingConfig.feature_weights,
          },
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Dataset preparation failed.",
      );
    } finally {
      setEngineBLoading(false);
    }
  }

  async function trainModel() {
    if (
      !trainingRun ||
      !Number.isFinite(weightTotal) ||
      Math.abs(weightTotal - 1) > 0.000001
    )
      return;
    setEngineBLoading(true);
    setError(null);
    try {
      setTrainingRun(
        await apiSend<TrainingRun>(
          `/api/v1/phase5/engine-b/training-runs/${trainingRun.training_run_id}/train`,
          "POST",
          { configuration: trainingConfig },
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Model training failed.",
      );
    } finally {
      setEngineBLoading(false);
    }
  }

  async function saveModel() {
    if (!trainingRun || !modelName.trim()) return;
    setEngineBLoading(true);
    try {
      const savedModel = await apiSend<ModelDetail>(
        `/api/v1/phase5/engine-b/training-runs/${trainingRun.training_run_id}/save`,
        "POST",
        {
          model_name: modelName.trim(),
          description: modelDescription.trim() || null,
        },
      );
      setSaveDialog(false);
      setModelName("");
      setModelDescription("");
      await refreshRegistry();
      setTrainingRun(null);
      setDisplayedSavedModel(savedModel);
      setSelectedClusteringModelId(savedModel.model_id);
      setClusteringSavedMessage(
        `Saved behavioral analysis: ${savedModel.model_name} v${savedModel.model_version}.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Model save failed.");
    } finally {
      setEngineBLoading(false);
    }
  }

  async function refreshRegistry() {
    setRegistryLoading(true);
    try {
      const registryModels = await apiGet<ModelSummary[]>(
        `/api/v1/phase5/models${depotId ? `?depot_id=${encodeURIComponent(depotId)}` : ""}`,
      );
      setModels(registryModels);
      setSelectedClusteringModelId((current) =>
        registryModels.some((model) => model.model_id === current)
          ? current
          : "",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Failed to load Model Registry.",
      );
    } finally {
      setRegistryLoading(false);
    }
  }

  async function openModel(modelId: string) {
    try {
      setOpenedModel(
        await apiGet<ModelDetail>(`/api/v1/phase5/models/${modelId}`),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Failed to open model.",
      );
    }
  }

  function openClusteringLoadDialog() {
    if (!models.length) {
      setError("No saved behavioral analysis is available for this depot.");
      return;
    }
    setSelectedClusteringModelId((current) => current || models[0]?.model_id || "");
    setClusteringLoadDialog(true);
    setError(null);
  }

  async function openClusteringModel(
    modelId = selectedClusteringModelId,
  ) {
    if (!modelId) return;
    setClusteringModelLoading(true);
    setError(null);
    try {
      const model = await apiGet<ModelDetail>(
        `/api/v1/phase5/models/${modelId}`,
      );
      setTrainingRun(null);
      setSelectedCluster(null);
      setDisplayedSavedModel(model);
      setSelectedClusteringModelId(model.model_id);
      setClusterMembershipPage(0);
      setClusteringSavedMessage(
        `Loaded behavioral analysis: ${model.model_name} v${model.model_version}.`,
      );
      setClusteringLoadDialog(false);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Failed to open saved clustering model.",
      );
    } finally {
      setClusteringModelLoading(false);
    }
  }

  async function activateModel(modelId: string) {
    try {
      await apiSend(`/api/v1/phase5/models/${modelId}/activate`, "POST");
      await refreshRegistry();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Activation failed.");
    }
  }

  async function archiveModel(modelId: string) {
    try {
      await apiSend(`/api/v1/phase5/models/${modelId}/status`, "POST", {
        status: "ARCHIVED",
      });
      await refreshRegistry();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Archive failed.");
    }
  }

  async function duplicateModel(modelId: string) {
    try {
      const draft = await apiSend<{
        depot_id: string;
        training_start_date: string;
        training_end_date: string;
        minimum_shipment_observation: number;
        shift_definitions: ShiftDefinition[];
        feature_weights: typeof defaultConfig.feature_weights;
        node2vec_parameters: typeof defaultConfig.node2vec_parameters;
        umap_parameters: typeof defaultConfig.umap_parameters;
        hdbscan_parameters: typeof defaultConfig.hdbscan_parameters;
        data_sufficiency_configuration: typeof defaultConfig.data_sufficiency_configuration;
        geographic_configuration: typeof defaultConfig.geographic_configuration;
        projection_configuration: typeof defaultConfig.projection_configuration;
        random_seed: number;
      }>(`/api/v1/phase5/models/${modelId}/duplicate`, "POST");
      setDepotId(draft.depot_id);
      setTrainingStart(draft.training_start_date);
      setTrainingEnd(draft.training_end_date);
      setTrainingMinimum(String(draft.minimum_shipment_observation));
      setShiftDefinitions(
        draft.shift_definitions.map((shift, index) => ({
          shift_id: shift.shift_id || `shift_${index + 1}`,
          name: shift.name,
          start_time: shift.start_time,
          end_time: shift.end_time,
        })),
      );
      setTrainingConfig({
        feature_weights: draft.feature_weights,
        data_sufficiency_configuration: draft.data_sufficiency_configuration,
        geographic_configuration: draft.geographic_configuration,
        projection_configuration: draft.projection_configuration,
        node2vec_parameters: draft.node2vec_parameters,
        umap_parameters: draft.umap_parameters,
        hdbscan_parameters: draft.hdbscan_parameters,
        random_seed: draft.random_seed,
      });
      setTrainingRun(null);
      setDisplayedSavedModel(null);
      setTab("clustering");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Duplicate configuration failed.",
      );
    }
  }

  async function deleteModel(model: ModelSummary) {
    if (
      !window.confirm(
        `Delete ${model.model_name} v${model.model_version}? Saved artifacts will also be removed.`,
      )
    )
      return;
    try {
      await apiSend(`/api/v1/phase5/models/${model.model_id}`, "DELETE");
      if (displayedSavedModel?.model_id === model.model_id) {
        setDisplayedSavedModel(null);
      }
      if (selectedClusteringModelId === model.model_id) {
        setSelectedClusteringModelId("");
      }
      setClusteringSavedMessage(
        `Deleted behavioral analysis: ${model.model_name} v${model.model_version}.`,
      );
      await refreshRegistry();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Delete failed.");
    }
  }

  async function compareModels() {
    if (!compareA || !compareB || compareA === compareB) return;
    try {
      setComparison(
        await apiSend<Comparison>("/api/v1/phase5/models/compare", "POST", {
          model_a_id: compareA,
          model_b_id: compareB,
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Model comparison failed.",
      );
    }
  }

  const trainedResult =
    trainingRun?.result && "summary" in trainingRun.result
      ? (trainingRun.result as TrainingResult)
      : null;
  const savedModelResult = useMemo<TrainingResult | null>(
    () =>
      displayedSavedModel
        ? {
            summary: {
              training_spbu_count: displayedSavedModel.training_spbu_count,
              historical_training_spbu_count:
                displayedSavedModel.historical_training_spbu_count,
              total_covered_spbu_count:
                displayedSavedModel.total_covered_spbu_count,
              cold_start_covered_spbu_count:
                displayedSavedModel.cold_start_covered_spbu_count,
              no_history_spbu_count: displayedSavedModel.no_history_spbu_count,
              insufficient_history_spbu_count:
                displayedSavedModel.insufficient_history_spbu_count,
              cluster_count: displayedSavedModel.cluster_count,
              clustered_spbu_count:
                displayedSavedModel.training_spbu_count -
                displayedSavedModel.noise_spbu_count,
              noise_spbu_count: displayedSavedModel.noise_spbu_count,
              average_membership_probability:
                displayedSavedModel.average_membership_probability,
              total_spbu_count: displayedSavedModel.total_spbu_count,
              sufficient_spbu_count: displayedSavedModel.sufficient_spbu_count,
              marginal_spbu_count: displayedSavedModel.marginal_spbu_count,
              insufficient_spbu_count:
                displayedSavedModel.insufficient_spbu_count,
              core_training_spbu_count:
                displayedSavedModel.core_training_spbu_count,
              core_cluster_member_count:
                displayedSavedModel.core_cluster_member_count,
              core_noise_count: displayedSavedModel.noise_spbu_count,
              marginal_projected_count:
                displayedSavedModel.marginal_projected_count,
              marginal_unassigned_count:
                displayedSavedModel.marginal_unassigned_count,
              insufficient_unassigned_count:
                displayedSavedModel.insufficient_unassigned_count,
              average_projection_confidence:
                displayedSavedModel.average_projection_confidence,
              valid_coordinate_count:
                displayedSavedModel.valid_coordinate_count,
              invalid_coordinate_count:
                displayedSavedModel.invalid_coordinate_count,
              geographic_coverage_percentage:
                displayedSavedModel.geographic_coverage_percentage,
            },
            assignments: displayedSavedModel.assignments,
            cluster_profiles: displayedSavedModel.cluster_profiles,
            warnings: [],
            saved: true,
          }
        : null,
    [displayedSavedModel],
  );
  const displayedClusterResult = savedModelResult ?? trainedResult;
  const clusteringSavedPageCount = Math.max(
    1,
    Math.ceil(models.length / clusteringSavedPageSize),
  );
  const clusteringSavedSafePage = Math.min(
    clusteringSavedPage,
    clusteringSavedPageCount - 1,
  );
  const clusteringSavedRows = models.slice(
    clusteringSavedSafePage * clusteringSavedPageSize,
    (clusteringSavedSafePage + 1) * clusteringSavedPageSize,
  );
  const clusteringSavedRangeStart =
    models.length === 0
      ? 0
      : clusteringSavedSafePage * clusteringSavedPageSize + 1;
  const clusteringSavedRangeEnd = Math.min(
    models.length,
    (clusteringSavedSafePage + 1) * clusteringSavedPageSize,
  );
  const evidenceCounts = useMemo(() => {
    const assignments = displayedClusterResult?.assignments ?? [];
    const historical = assignments.filter(hasHistoricalEvidence).length;
    const marginal = assignments.filter(
      (assignment) => assignment.data_sufficiency_status === "MARGINAL",
    ).length;
    const insufficient = assignments.filter(
      (assignment) => assignment.data_sufficiency_status === "INSUFFICIENT",
    ).length;
    return {
      historical,
      marginal,
      insufficient,
      marginalProjected: assignments.filter(
        (assignment) =>
          assignment.cluster_assignment_type === "MARGINAL_PROJECTED",
      ).length,
      coreNoise: assignments.filter(
        (assignment) => assignment.cluster_assignment_type === "CORE_NOISE",
      ).length,
      total: assignments.length,
    };
  }, [displayedClusterResult?.assignments]);
  const evidenceFilteredAssignments = useMemo(
    () =>
      (displayedClusterResult?.assignments ?? [])
        .filter(
          (assignment) =>
            evidenceFilter === "ALL" ||
            (evidenceFilter === "CORE" &&
              assignment.data_sufficiency_status === "SUFFICIENT") ||
            (evidenceFilter === "MARGINAL" &&
              assignment.data_sufficiency_status === "MARGINAL"),
        )
        .filter(
          (assignment) =>
            assignment.data_sufficiency_status !== "INSUFFICIENT" &&
            assignment.visualization_x !== null &&
            assignment.visualization_y !== null,
        ),
    [displayedClusterResult?.assignments, evidenceFilter],
  );
  const behavioralClusterLabels = useMemo(
    () =>
      Array.from(
        new Set(
          evidenceFilteredAssignments.map(
            (assignment) => assignment.cluster_label,
          ),
        ),
      ),
    [evidenceFilteredAssignments],
  );
  const clusterMembershipAssignments = useMemo(() => {
    const minimumProjection = Number(minimumProjectionConfidence || 0);
    const minimumMembership = Number(minimumMembershipProbability || 0);
    const needle = clusterSpbuSearch.trim().toLowerCase();
    return (displayedClusterResult?.assignments ?? [])
      .filter(
        (assignment) =>
          sufficiencyFilter === "ALL" ||
          assignment.data_sufficiency_status === sufficiencyFilter,
      )
      .filter(
        (assignment) =>
          assignmentTypeFilter === "ALL" ||
          assignment.cluster_assignment_type === assignmentTypeFilter,
      )
      .filter(
        (assignment) =>
          clusterFilter === "ALL" ||
          String(assignment.cluster_id ?? "UNASSIGNED") === clusterFilter,
      )
      .filter(
        (assignment) =>
          noiseFilter === "ALL" ||
          (noiseFilter === "YES" ? assignment.is_noise : !assignment.is_noise),
      )
      .filter(
        (assignment) =>
          minimumProjection <= 0 ||
          (assignment.projection_confidence ?? -1) >= minimumProjection,
      )
      .filter(
        (assignment) =>
          minimumMembership <= 0 ||
          (assignment.membership_probability ?? -1) >= minimumMembership,
      )
      .filter(
        (assignment) =>
          geographicStatusFilter === "ALL" ||
          assignment.geographic_data_status === geographicStatusFilter,
      )
      .filter(
        (assignment) =>
          !needle ||
          `${assignment.spbu_code} ${assignment.spbu_name ?? ""}`
            .toLowerCase()
            .includes(needle),
      );
  }, [
    assignmentTypeFilter,
    clusterFilter,
    clusterSpbuSearch,
    displayedClusterResult?.assignments,
    geographicStatusFilter,
    minimumMembershipProbability,
    minimumProjectionConfidence,
    noiseFilter,
    sufficiencyFilter,
  ]);
  const clusterMembershipPageCount = Math.max(
    1,
    Math.ceil(clusterMembershipAssignments.length / clusterMembershipPageSize),
  );
  const clusterMembershipSafePage = Math.min(
    clusterMembershipPage,
    clusterMembershipPageCount - 1,
  );
  const clusterMembershipPageRows = clusterMembershipAssignments.slice(
    clusterMembershipSafePage * clusterMembershipPageSize,
    (clusterMembershipSafePage + 1) * clusterMembershipPageSize,
  );
  const clusterMembershipRangeStart =
    clusterMembershipAssignments.length === 0
      ? 0
      : clusterMembershipSafePage * clusterMembershipPageSize + 1;
  const clusterMembershipRangeEnd = Math.min(
    clusterMembershipAssignments.length,
    (clusterMembershipSafePage + 1) * clusterMembershipPageSize,
  );
  const displayedShiftDefinitions =
    displayedSavedModel?.shift_definition_snapshot ?? shiftDefinitions;
  const geographicDepot = useMemo<DepotLocation | null>(
    () =>
      readiness
        ? {
            depot_id: readiness.depot_id,
            depot_name: readiness.depot_name,
            latitude: readiness.depot_latitude,
            longitude: readiness.depot_longitude,
          }
        : null,
    [readiness],
  );

  useEffect(() => {
    setClusterMembershipPage(0);
  }, [
    displayedSavedModel?.model_id,
    assignmentTypeFilter,
    clusterFilter,
    clusterSpbuSearch,
    geographicStatusFilter,
    minimumMembershipProbability,
    minimumProjectionConfidence,
    noiseFilter,
    sufficiencyFilter,
    trainingRun?.training_run_id,
    displayedClusterResult?.assignments,
  ]);

  useEffect(() => {
    setEvidenceFilter("CORE");
  }, [displayedSavedModel?.model_id, trainingRun?.training_run_id]);

  useEffect(() => {
    setClusteringSavedPage(0);
  }, [depotId, clusteringSavedPageSize]);

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-start justify-between border border-rust bg-rust/5 px-4 py-3 text-sm text-rust">
          <span>{error}</span>
          <button onClick={() => setError(null)}>
            <X size={16} />
          </button>
        </div>
      )}

      <section className="border border-line bg-white p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-600">
              <BrainCircuit size={18} /> Phase 5 Readiness
            </div>
            <p className="mt-1 text-sm text-slate-500">
              Machine learning is unlocked when every observed Loading Order
              assignment in the latest Phase 1 scope passes tag compatibility.
              Unused ineligible MT–SPBU combinations are expected exclusions and
              do not block Phase 5.
            </p>
          </div>
          <div className="flex gap-2">
            <select
              className="min-w-64 border border-line bg-white px-3 py-2 text-sm"
              value={depotId}
              onChange={(event) => setDepotId(event.target.value)}
              title="Phase 5 depot"
            >

              {depots.map((depot) => (
                <option key={depot.depot_id} value={depot.depot_id}>
                  {depot.depot_name}
                </option>
              ))}
            </select>
            <button
              className="border border-line px-3 py-2"
              onClick={refreshReadiness}
              disabled={!depotId || readinessLoading}
              title="Refresh compatibility readiness"
            >
              <RefreshCw
                size={17}
                className={readinessLoading ? "animate-spin" : ""}
              />
            </button>
          </div>
        </div>
        {readiness && (
          <div
            className={`mt-4 grid gap-4 border p-4 lg:grid-cols-[1fr_1fr_auto] ${readiness.is_ready ? "border-mint bg-mint/5" : "border-rust bg-rust/5"}`}
          >
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Observed Assignment Compatibility
              </div>
              <div className="mt-1 text-3xl font-semibold">
                {readiness.master_compatibility_pass_percentage.toFixed(2)}%
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {readiness.passed_assignment_count.toLocaleString()} of{" "}
                {readiness.evaluated_assignment_count.toLocaleString()} Loading
                Order assignments pass
              </div>
              <div className="mt-1 text-xs text-slate-500">
                Phase 1 scope:{" "}
                {readiness.scope_start_date ?? "no available date"}
                {readiness.scope_end_date &&
                readiness.scope_end_date !== readiness.scope_start_date
                  ? ` – ${readiness.scope_end_date}`
                  : ""}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Status
              </div>
              <span
                className={`mt-2 inline-flex border px-3 py-1 text-sm font-semibold ${badgeClass(readiness.status)}`}
              >
                {label(readiness.status)}
              </span>
              <p className="mt-2 text-xs text-slate-500">
                {readiness.requirement}
              </p>
            </div>
            {!readiness.is_ready && (
              <button
                className="self-center border border-rust px-3 py-2 text-sm font-semibold text-rust"
                onClick={() => {
                  window.location.href = readiness.compatibility_issues_path;
                }}
              >
                View Phase 1 Results
              </button>
            )}
          </div>
        )}
      </section>

      <div className="flex flex-wrap gap-2 border-b border-line pb-3">
        {(
          [
            ["concentration", "1. Historical MT–SPBU Anomaly"],
            ["clustering", "2. SPBU Behavioral Clustering"],
            ["registry", "3. Model Registry"],
          ] as Array<[Tab, string]>
        ).map(([value, text]) => (
          <button
            key={value}
            className={`px-4 py-2 text-sm font-semibold ${tab === value ? "bg-petroblue text-white" : "border border-line bg-white text-slate-600"}`}
            onClick={() => setTab(value)}
          >
            {text}
          </button>
        ))}
      </div>

      {tab === "concentration" && (
        <>
          <section className="border border-line bg-white p-5">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-xl font-semibold">
                  Historical MT–SPBU Concentration Anomaly
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Find unexpected historical concentration relative to
                  compatible fleet opportunity. This is not an assignment-error
                  classifier.
                </p>
              </div>
              <div className="flex flex-col items-end gap-2">
                <div className="flex gap-2">
                  <button
                    className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50"
                    onClick={openConcentrationLoadDialog}
                    disabled={
                      savedConcentrationLoading || savedConcentrationTotal === 0
                    }
                    title="Load a saved concentration analysis"
                  >
                    <RefreshCw size={14} /> Load
                  </button>
                  <button
                    className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50"
                    onClick={openConcentrationSaveDialog}
                    disabled={
                      engineALoading ||
                      !concentrationRun ||
                      concentrationRun.status !== "COMPLETED"
                    }
                    title="Save the current concentration analysis result"
                  >
                    <Save size={14} /> Save
                  </button>
                </div>
                {concentrationSavedMessage && (
                  <div className="max-w-md text-right text-xs text-slate-500">
                    {concentrationSavedMessage}
                  </div>
                )}
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Depot
                <input
                  className="mt-1 w-full border border-line bg-slate-50 px-3 py-2 text-sm"
                  value={readiness?.depot_name ?? ""}
                  readOnly
                />
              </label>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Baseline Start Date
                <input
                  className="mt-1 w-full border border-line px-3 py-2 text-sm"
                  type="date"
                  min={dateRange.min_date ?? undefined}
                  max={dateRange.max_date ?? undefined}
                  value={baselineStart}
                  onChange={(event) => setBaselineStart(event.target.value)}
                />
              </label>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Baseline End Date
                <input
                  className="mt-1 w-full border border-line px-3 py-2 text-sm"
                  type="date"
                  min={dateRange.min_date ?? undefined}
                  max={dateRange.max_date ?? undefined}
                  value={baselineEnd}
                  onChange={(event) => setBaselineEnd(event.target.value)}
                />
              </label>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Minimum Shipment Observation
                <input
                  className="mt-1 w-full border border-line px-3 py-2 text-sm"
                  type="number"
                  min="1"
                  value={engineAMinimum}
                  onChange={(event) => setEngineAMinimum(event.target.value)}
                />
              </label>
              <button
                className="mt-5 inline-flex items-center justify-center gap-2 bg-mint px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
                disabled={
                  !readiness?.is_ready ||
                  engineALoading ||
                  !baselineStart ||
                  !baselineEnd
                }
                onClick={runEngineA}
              >
                <Play size={16} />{" "}
                {engineALoading ? "Running…" : "Run Analysis"}
              </button>
            </div>
            <button
              className="mt-4 text-sm font-semibold text-petroblue"
              onClick={() => setEngineAAdvanced((value) => !value)}
            >
              Advanced Settings {engineAAdvanced ? "▴" : "▾"}
            </button>
            {engineAAdvanced && (
              <div className="mt-3 grid gap-3 border border-line bg-slate-50 p-4 md:grid-cols-3 lg:grid-cols-6">
                <label className="text-xs">
                  Estimators
                  <input
                    className="mt-1 w-full border border-line px-2 py-2"
                    type="number"
                    value={engineAEstimators}
                    onChange={(event) =>
                      setEngineAEstimators(event.target.value)
                    }
                  />
                </label>
                <label className="text-xs">
                  Contamination
                  <input
                    className="mt-1 w-full border border-line px-2 py-2"
                    value={engineAContamination}
                    onChange={(event) =>
                      setEngineAContamination(event.target.value)
                    }
                  />
                </label>
                <label className="text-xs">
                  Random Seed
                  <input
                    className="mt-1 w-full border border-line px-2 py-2"
                    type="number"
                    value={engineASeed}
                    onChange={(event) => setEngineASeed(event.target.value)}
                  />
                </label>
                {(["moderate", "high", "investigation"] as const).map((key) => (
                  <label className="text-xs" key={key}>
                    {key} threshold
                    <input
                      className="mt-1 w-full border border-line px-2 py-2"
                      type="number"
                      value={engineAThresholds[key]}
                      onChange={(event) =>
                        setEngineAThresholds((current) => ({
                          ...current,
                          [key]: event.target.value,
                        }))
                      }
                    />
                  </label>
                ))}
                <button
                  className="text-left text-xs font-semibold text-petroblue"
                  onClick={() => {
                    setEngineAEstimators("200");
                    setEngineAContamination("auto");
                    setEngineASeed("42");
                    setEngineAThresholds({
                      moderate: "40",
                      high: "60",
                      investigation: "80",
                    });
                  }}
                >
                  Reset defaults
                </button>
              </div>
            )}
            <div className="mt-4 border border-line">
              <div className="flex flex-col gap-2 border-b border-line bg-slate-50 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Saved Historical MT–SPBU Concentration Analyses
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    Showing {savedConcentrationShowingStart}–
                    {savedConcentrationShowingEnd} of {savedConcentrationTotal}
                  </div>
                </div>
                <select
                  className="border border-line bg-white px-2 py-1 text-xs"
                  value={savedConcentrationLimit}
                  onChange={(event) => {
                    setSavedConcentrationOffset(0);
                    setSavedConcentrationLimit(Number(event.target.value));
                  }}
                  title="Saved analyses per page"
                >
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
                      <th className="whitespace-nowrap px-3 py-2">Min. Obs.</th>
                      <th className="whitespace-nowrap px-3 py-2">SPBU</th>
                      <th className="whitespace-nowrap px-3 py-2">Investigation</th>
                      <th className="whitespace-nowrap px-3 py-2">Saved</th>
                      <th className="whitespace-nowrap px-3 py-2">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {savedConcentrationAnalyses.map((saved) => (
                      <tr className="border-b border-line" key={saved.id}>
                        <td className="whitespace-nowrap px-3 py-2 font-medium">
                          {saved.name}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          {saved.depot_name}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          {saved.baseline_start_date} – {saved.baseline_end_date}
                        </td>
                        <td className="px-3 py-2">
                          {saved.minimum_shipment_observation}
                        </td>
                        <td className="px-3 py-2">{saved.spbu_count}</td>
                        <td className="px-3 py-2">
                          {saved.investigation_recommended_count}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          {dateTimeLabel(saved.updated_at)}
                        </td>
                        <td className="px-3 py-2">
                          <button
                            className="inline-flex items-center justify-center border border-line p-2 text-rust disabled:opacity-40"
                            onClick={() =>
                              void deleteSavedConcentrationAnalysis(saved)
                            }
                            disabled={savedConcentrationLoading}
                            title="Delete saved concentration analysis"
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {savedConcentrationAnalyses.length === 0 && (
                      <tr>
                        <td
                          colSpan={8}
                          className="px-3 py-8 text-center text-slate-500"
                        >
                          No saved concentration analysis for this depot.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                <button
                  className="border border-line px-3 py-2 disabled:opacity-50"
                  onClick={() =>
                    setSavedConcentrationOffset(
                      Math.max(
                        0,
                        savedConcentrationOffset - savedConcentrationLimit,
                      ),
                    )
                  }
                  disabled={
                    savedConcentrationOffset === 0 || savedConcentrationLoading
                  }
                >
                  Previous
                </button>
                <span className="text-slate-500">
                  Page {savedConcentrationPage} of {savedConcentrationPageCount}
                </span>
                <button
                  className="border border-line px-3 py-2 disabled:opacity-50"
                  onClick={() =>
                    setSavedConcentrationOffset(
                      savedConcentrationOffset + savedConcentrationLimit,
                    )
                  }
                  disabled={
                    savedConcentrationOffset + savedConcentrationLimit >=
                      savedConcentrationTotal || savedConcentrationLoading
                  }
                >
                  Next
                </button>
              </div>
            </div>
          </section>

          {concentrationRun && (
            <>
              <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric
                  title="Analyzed SPBU"
                  value={concentrationRun.summary.spbu_count ?? 0}
                />
                <Metric
                  title="Sufficient Evidence"
                  value={concentrationRun.summary.sufficient_data_count ?? 0}
                />
                <Metric
                  title="Insufficient Data"
                  value={concentrationRun.summary.insufficient_data_count ?? 0}
                />
                <Metric
                  title="Investigation Recommended"
                  value={
                    concentrationRun.summary.investigation_recommended_count ??
                    0
                  }
                />
              </section>
              <section className="grid gap-4 lg:grid-cols-3">
                <div className="border border-line bg-white p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                    Anomaly Ranking
                  </h3>
                  <ReactECharts
                    style={{ height: 300 }}
                    option={{
                      grid: { left: 55, right: 20, bottom: 70 },
                      xAxis: {
                        type: "category",
                        data: concentrationChartRows
                          .slice(0, 15)
                          .map((row) => row.spbu_code),
                        axisLabel: { rotate: 45 },
                      },
                      yAxis: { type: "value", min: 0, max: 100 },
                      tooltip: { trigger: "axis" },
                      series: [
                        {
                          type: "bar",
                          data: concentrationChartRows
                            .slice(0, 15)
                            .map((row) => row.concentration_anomaly_score),
                        },
                      ],
                    }}
                  />
                </div>
                <div className="border border-line bg-white p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                    Compatibility vs Actual Usage
                  </h3>
                  <ReactECharts
                    style={{ height: 300 }}
                    option={{
                      xAxis: { name: "Compatible MT" },
                      yAxis: { name: "Historically Used MT" },
                      tooltip: {
                        formatter: (params: {
                          data: { name: string; value: number[] };
                        }) =>
                          `${params.data.name}<br/>Compatible: ${params.data.value[0]}<br/>Used: ${params.data.value[1]}<br/>Score: ${params.data.value[2]}`,
                      },
                      series: [
                        {
                          type: "scatter",
                          symbolSize: 10,
                          data: concentrationChartRows.map((row) => ({
                            name: row.spbu_code,
                            value: [
                              row.compatible_mt_count,
                              row.historically_used_mt_count,
                              row.concentration_anomaly_score,
                            ],
                          })),
                        },
                      ],
                    }}
                  />
                </div>
                <div className="border border-line bg-white p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                    Dominant Share vs Utilization Breadth
                  </h3>
                  <ReactECharts
                    style={{ height: 300 }}
                    option={{
                      xAxis: { name: "Utilization Breadth", min: 0, max: 1 },
                      yAxis: { name: "Dominant MT Share", min: 0, max: 1 },
                      tooltip: {
                        formatter: (params: {
                          data: { name: string; value: number[] };
                        }) =>
                          `${params.data.name}<br/>Breadth: ${pct(params.data.value[0])}<br/>Dominant: ${pct(params.data.value[1])}<br/>Score: ${params.data.value[2]}`,
                      },
                      series: [
                        {
                          type: "scatter",
                          symbolSize: 10,
                          data: concentrationChartRows.map((row) => ({
                            name: row.spbu_code,
                            value: [
                              row.utilization_breadth,
                              row.dominant_mt_share,
                              row.concentration_anomaly_score,
                            ],
                          })),
                        },
                      ],
                    }}
                  />
                </div>
              </section>
              <section className="border border-line bg-white p-4">
                <div className="mb-4 flex flex-wrap gap-3">
                  <select
                    className="border border-line px-3 py-2 text-sm"
                    value={classificationFilter}
                    onChange={(event) =>
                      setClassificationFilter(event.target.value)
                    }
                  >
                    <option value="ALL">All classifications</option>
                    {[
                      "NORMAL",
                      "MODERATE_CONCENTRATION",
                      "HIGH_CONCENTRATION",
                      "INVESTIGATION_RECOMMENDED",
                      "INSUFFICIENT_DATA",
                    ].map((value) => (
                      <option key={value} value={value}>
                        {label(value)}
                      </option>
                    ))}
                  </select>
                  <input
                    className="border border-line px-3 py-2 text-sm"
                    type="number"
                    min="0"
                    max="100"
                    value={minimumScore}
                    onChange={(event) => setMinimumScore(event.target.value)}
                    placeholder="Minimum anomaly score"
                    title="Minimum anomaly score"
                  />
                  <input
                    className="border border-line px-3 py-2 text-sm"
                    type="number"
                    min="0"
                    value={minimumObservationFilter}
                    onChange={(event) =>
                      setMinimumObservationFilter(event.target.value)
                    }
                    placeholder="Minimum observation"
                    title="Minimum observation"
                  />
                  <input
                    className="min-w-60 border border-line px-3 py-2 text-sm"
                    value={spbuSearch}
                    onChange={(event) => setSpbuSearch(event.target.value)}
                    placeholder="Search SPBU"
                  />
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                        <th className="px-3 py-2">SPBU</th>
                        <th className="px-3 py-2">Observations</th>
                        <th className="px-3 py-2">Compatible MT</th>
                        <th className="px-3 py-2">Used MT</th>
                        <th
                          className="px-3 py-2"
                          title="Historically used compatible MT divided by compatible MT."
                        >
                          Utilization Breadth
                        </th>
                        <th className="px-3 py-2">Dominant MT</th>
                        <th
                          className="px-3 py-2"
                          title="Largest historical P(MT | SPBU)."
                        >
                          Dominant Share
                        </th>
                        <th
                          className="px-3 py-2"
                          title="Higher HHI means a smaller fleet dominates historical assignments."
                        >
                          HHI
                        </th>
                        <th
                          className="px-3 py-2"
                          title="Shannon entropy normalized by the number of historically used MTs; higher means more even usage."
                        >
                          Normalized Entropy
                        </th>
                        <th
                          className="px-3 py-2"
                          title="Negative Isolation Forest score_samples value; higher is more unusual within the run."
                        >
                          Raw ML
                        </th>
                        <th
                          className="px-3 py-2"
                          title="Raw ML severity min-max scaled to 0–100 within this run; higher means more unusual concentration."
                        >
                          <button
                            onClick={() =>
                              setScoreDirection((value) =>
                                value === "desc" ? "asc" : "desc",
                              )
                            }
                          >
                            Anomaly Score{" "}
                            {scoreDirection === "desc" ? "↓" : "↑"}
                          </button>
                        </th>
                        <th className="px-3 py-2">Classification</th>
                      </tr>
                    </thead>
                    <tbody>
                      {concentrationPageRows.map((row) => (
                        <tr
                          key={row.spbu_id}
                          className="cursor-pointer border-b border-line hover:bg-petrocloud/50"
                          onClick={() => setSelectedConcentration(row)}
                        >
                          <td className="px-3 py-2">
                            <div className="font-semibold">{row.spbu_code}</div>
                            <div className="text-xs text-slate-500">
                              {row.spbu_name}
                            </div>
                          </td>
                          <td className="px-3 py-2">
                            {row.shipment_observation_count}
                          </td>
                          <td className="px-3 py-2">
                            {row.compatible_mt_count}
                          </td>
                          <td className="px-3 py-2">
                            {row.historically_used_mt_count}
                          </td>
                          <td className="px-3 py-2">
                            {pct(row.utilization_breadth)}
                          </td>
                          <td className="px-3 py-2">
                            {row.dominant_mt_registration ?? "-"}
                          </td>
                          <td className="px-3 py-2">
                            {pct(row.dominant_mt_share)}
                          </td>
                          <td className="px-3 py-2">{score(row.hhi)}</td>
                          <td className="px-3 py-2">
                            {score(row.normalized_entropy)}
                          </td>
                          <td className="px-3 py-2">
                            {score(row.raw_ml_anomaly_score)}
                          </td>
                          <td className="px-3 py-2 font-semibold">
                            {score(row.concentration_anomaly_score)}
                          </td>
                          <td className="px-3 py-2">
                            <span
                              className={`whitespace-nowrap border px-2 py-1 text-xs ${badgeClass(row.concentration_classification)}`}
                            >
                              {label(row.concentration_classification)}
                            </span>
                          </td>
                        </tr>
                      ))}
                      {filteredConcentration.length === 0 && (
                        <tr>
                          <td
                            colSpan={12}
                            className="px-3 py-8 text-center text-slate-500"
                          >
                            No profiles match the active filters.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <div className="mt-4 flex flex-col gap-3 border-t border-line pt-4 text-sm sm:flex-row sm:items-center sm:justify-between">
                  <div className="text-slate-500">
                    Showing {concentrationRangeStart.toLocaleString()}–
                    {concentrationRangeEnd.toLocaleString()} of{" "}
                    {filteredConcentration.length.toLocaleString()} SPBUs
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="inline-flex items-center gap-2 text-slate-500">
                      Rows per page
                      <select
                        className="border border-line bg-white px-3 py-2 text-sm text-petroink"
                        value={concentrationPageSize}
                        onChange={(event) => {
                          setConcentrationPageSize(Number(event.target.value));
                          setConcentrationPage(0);
                        }}
                        title="Rows per page"
                      >
                        <option value={10}>10</option>
                        <option value={20}>20</option>
                        <option value={50}>50</option>
                      </select>
                    </label>
                    <button
                      className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() =>
                        setConcentrationPage((current) =>
                          Math.max(0, current - 1),
                        )
                      }
                      disabled={concentrationPage === 0}
                    >
                      Previous
                    </button>
                    <span className="min-w-24 text-center text-slate-500">
                      Page {concentrationPage + 1} of {concentrationPageCount}
                    </span>
                    <button
                      className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() =>
                        setConcentrationPage((current) =>
                          Math.min(concentrationPageCount - 1, current + 1),
                        )
                      }
                      disabled={concentrationPage + 1 >= concentrationPageCount}
                    >
                      Next
                    </button>
                  </div>
                </div>
              </section>
            </>
          )}
        </>
      )}

      {tab === "clustering" && (
        <>
          <section className="border border-line bg-white p-5">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h2 className="font-display text-xl font-semibold">
                  SPBU Behavioral Clustering
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Tag + full shift distribution + Phase 3 co-shipment graph +
                  Haversine geographic proximity. Only SUFFICIENT SPBUs determine
                  core clusters; clusters never override compatibility.
                </p>
              </div>
              <div className="flex flex-col items-end gap-2">
                <div className="flex gap-2">
                  <button
                    className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50"
                    onClick={openClusteringLoadDialog}
                    disabled={registryLoading || models.length === 0}
                    title="Load a saved behavioral analysis"
                  >
                    <RefreshCw size={14} /> Load
                  </button>
                  <button
                    className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm disabled:opacity-50"
                    onClick={() => setSaveDialog(true)}
                    disabled={
                      engineBLoading || !trainedResult || Boolean(displayedSavedModel)
                    }
                    title="Save the current trained behavioral analysis"
                  >
                    <Save size={14} /> Save
                  </button>
                </div>
                {clusteringSavedMessage && (
                  <div className="max-w-md text-right text-xs text-slate-500">
                    {clusteringSavedMessage}
                  </div>
                )}
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-5">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Depot
                <input
                  className="mt-1 w-full border border-line bg-slate-50 px-3 py-2 text-sm"
                  value={readiness?.depot_name ?? ""}
                  readOnly
                />
              </label>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Training Start Date
                <input
                  className="mt-1 w-full border border-line px-3 py-2 text-sm"
                  type="date"
                  value={trainingStart}
                  onChange={(event) => setTrainingStart(event.target.value)}
                />
              </label>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Training End Date
                <input
                  className="mt-1 w-full border border-line px-3 py-2 text-sm"
                  type="date"
                  value={trainingEnd}
                  onChange={(event) => setTrainingEnd(event.target.value)}
                />
              </label>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Minimum Shipment Observation
                <input
                  className="mt-1 w-full border border-line px-3 py-2 text-sm"
                  type="number"
                  min="1"
                  value={trainingMinimum}
                  onChange={(event) => setTrainingMinimum(event.target.value)}
                />
              </label>
              <button
                className="mt-5 bg-mint px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
                disabled={
                  !readiness?.is_ready ||
                  engineBLoading ||
                  !trainingStart ||
                  !trainingEnd
                }
                onClick={prepareDataset}
              >
                {engineBLoading && !trainingRun
                  ? "Preparing…"
                  : "Prepare Training Dataset"}
              </button>
            </div>
            <button
              type="button"
              className="mt-4 text-sm font-semibold text-petroblue"
              onClick={() => setEngineBAdvanced((value) => !value)}
            >
              Advanced Settings {engineBAdvanced ? "▴" : "▾"}
            </button>
            {engineBAdvanced && !displayedSavedModel && (
              <div className="mt-3 space-y-5 border border-line bg-slate-50 p-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Data Sufficiency
                  </div>
                  <div className="mt-2 grid gap-3 md:grid-cols-3 lg:grid-cols-6">
                    {(
                      [
                        ["minimum_operating_days", "Min Operating Days"],
                        ["minimum_period_coverage", "Min Period Coverage"],
                        ["minimum_shift_coverage", "Min Shift Coverage"],
                        ["minimum_pairing_evidence", "Min Pair Evidence"],
                      ] as const
                    ).map(([key, title]) => (
                      <label className="text-xs" key={key}>
                        {title}
                        <input
                          className="mt-1 w-full border border-line p-2"
                          type="number"
                          min="0"
                          step={key.includes("coverage") ? "0.05" : "1"}
                          value={
                            trainingConfig.data_sufficiency_configuration[key]
                          }
                          onChange={(event) =>
                            setTrainingConfig((current) => ({
                              ...current,
                              data_sufficiency_configuration: {
                                ...current.data_sufficiency_configuration,
                                [key]: Number(event.target.value),
                              },
                            }))
                          }
                        />
                      </label>
                    ))}
                    <label className="text-xs">
                      Sufficient Score
                      <input
                        className="mt-1 w-full border border-line p-2"
                        type="number"
                        min="0"
                        max="100"
                        value={
                          trainingConfig.data_sufficiency_configuration
                            .thresholds.sufficient
                        }
                        onChange={(event) =>
                          setTrainingConfig((current) => ({
                            ...current,
                            data_sufficiency_configuration: {
                              ...current.data_sufficiency_configuration,
                              thresholds: {
                                ...current.data_sufficiency_configuration
                                  .thresholds,
                                sufficient: Number(event.target.value),
                              },
                            },
                          }))
                        }
                      />
                    </label>
                    <label className="text-xs">
                      Marginal Score
                      <input
                        className="mt-1 w-full border border-line p-2"
                        type="number"
                        min="0"
                        max="100"
                        value={
                          trainingConfig.data_sufficiency_configuration
                            .thresholds.marginal
                        }
                        onChange={(event) =>
                          setTrainingConfig((current) => ({
                            ...current,
                            data_sufficiency_configuration: {
                              ...current.data_sufficiency_configuration,
                              thresholds: {
                                ...current.data_sufficiency_configuration
                                  .thresholds,
                                marginal: Number(event.target.value),
                              },
                            },
                          }))
                        }
                      />
                    </label>
                  </div>
                </div>
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Geographic Proximity
                    </div>
                    <label className="inline-flex items-center gap-2 text-sm font-semibold">
                      <input
                        type="checkbox"
                        checked={
                          trainingConfig.geographic_configuration.enabled
                        }
                        onChange={(event) =>
                          toggleGeography(event.target.checked)
                        }
                      />
                      Use Geographic Proximity
                    </label>
                  </div>
                  <div className="mt-2 grid gap-3 md:grid-cols-3">
                    <label className="text-xs">
                      K Nearest Neighbors
                      <input
                        className="mt-1 w-full border border-line p-2"
                        type="number"
                        min="1"
                        value={
                          trainingConfig.geographic_configuration
                            .k_nearest_neighbors
                        }
                        onChange={(event) =>
                          setTrainingConfig((current) => ({
                            ...current,
                            geographic_configuration: {
                              ...current.geographic_configuration,
                              k_nearest_neighbors: Number(event.target.value),
                            },
                          }))
                        }
                      />
                    </label>
                    <label className="text-xs">
                      Maximum Proximity Distance (km)
                      <input
                        className="mt-1 w-full border border-line p-2"
                        type="number"
                        min="0.1"
                        value={
                          trainingConfig.geographic_configuration
                            .maximum_proximity_distance_km
                        }
                        onChange={(event) =>
                          setTrainingConfig((current) => ({
                            ...current,
                            geographic_configuration: {
                              ...current.geographic_configuration,
                              maximum_proximity_distance_km: Number(
                                event.target.value,
                              ),
                            },
                          }))
                        }
                      />
                    </label>
                    <label className="text-xs">
                      Minimum Projection Confidence
                      <input
                        className="mt-1 w-full border border-line p-2"
                        type="number"
                        min="0"
                        max="1"
                        step="0.05"
                        value={
                          trainingConfig.projection_configuration
                            .minimum_confidence
                        }
                        onChange={(event) =>
                          setTrainingConfig((current) => ({
                            ...current,
                            projection_configuration: {
                              ...current.projection_configuration,
                              minimum_confidence: Number(event.target.value),
                            },
                          }))
                        }
                      />
                    </label>
                  </div>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Feature Weights · total {(weightTotal * 100).toFixed(0)}%
                  </div>
                  <div className="mt-2 grid gap-3 md:grid-cols-4">
                    {(["tag", "shift", "pairing", "geographic"] as const).map(
                      (key) => (
                        <label className="text-sm capitalize" key={key}>
                          {key}
                          <input
                            className="mt-1 w-full border border-line px-3 py-2"
                            type="number"
                            min="0"
                            max="1"
                            step="0.05"
                            disabled={
                              key === "geographic" &&
                              !trainingConfig.geographic_configuration.enabled
                            }
                            value={trainingConfig.feature_weights[key]}
                            onChange={(event) =>
                              updateWeight(key, event.target.value)
                            }
                          />
                        </label>
                      ),
                    )}
                  </div>
                  {Math.abs(weightTotal - 1) > 0.000001 && (
                    <div className="mt-2 text-xs font-semibold text-rust">
                      Weights must equal exactly 1.00.
                    </div>
                  )}
                </div>
              </div>
            )}
            <div className="mt-4 border border-line">
              <div className="flex flex-col gap-2 border-b border-line bg-slate-50 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Saved SPBU Behavioral Clustering Analyses
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    Showing {clusteringSavedRangeStart}–{clusteringSavedRangeEnd} of{" "}
                    {models.length}
                  </div>
                </div>
                <select
                  className="border border-line bg-white px-2 py-1 text-xs"
                  value={clusteringSavedPageSize}
                  onChange={(event) =>
                    setClusteringSavedPageSize(Number(event.target.value))
                  }
                  title="Saved analyses per page"
                >
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
                      <th className="whitespace-nowrap px-3 py-2">Version</th>
                      <th className="whitespace-nowrap px-3 py-2">Depot</th>
                      <th className="whitespace-nowrap px-3 py-2">Period</th>
                      <th className="whitespace-nowrap px-3 py-2">SPBU</th>
                      <th className="whitespace-nowrap px-3 py-2">Clusters</th>
                      <th className="whitespace-nowrap px-3 py-2">Status</th>
                      <th className="whitespace-nowrap px-3 py-2">Saved</th>
                      <th className="whitespace-nowrap px-3 py-2">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clusteringSavedRows.map((model) => (
                      <tr className="border-b border-line" key={model.model_id}>
                        <td className="whitespace-nowrap px-3 py-2 font-medium">
                          {model.model_name}
                        </td>
                        <td className="px-3 py-2">v{model.model_version}</td>
                        <td className="whitespace-nowrap px-3 py-2">
                          {model.depot_name}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          {model.training_start_date} – {model.training_end_date}
                        </td>
                        <td className="px-3 py-2">{model.total_spbu_count}</td>
                        <td className="px-3 py-2">{model.cluster_count}</td>
                        <td className="px-3 py-2">
                          <span
                            className={`border px-2 py-1 text-xs ${badgeClass(model.model_status)}`}
                          >
                            {label(model.model_status)}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          {dateTimeLabel(model.updated_at ?? model.created_at)}
                        </td>
                        <td className="px-3 py-2">
                          <button
                            className="inline-flex items-center justify-center border border-line p-2 text-rust disabled:opacity-30"
                            onClick={() => void deleteModel(model)}
                            disabled={
                              model.model_status === "ACTIVE" || registryLoading
                            }
                            title={
                              model.model_status === "ACTIVE"
                                ? "Active model cannot be deleted"
                                : "Delete saved behavioral analysis"
                            }
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {clusteringSavedRows.length === 0 && (
                      <tr>
                        <td
                          colSpan={9}
                          className="px-3 py-8 text-center text-slate-500"
                        >
                          No saved behavioral analysis for this depot.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                <button
                  className="border border-line px-3 py-2 disabled:opacity-50"
                  onClick={() =>
                    setClusteringSavedPage((current) => Math.max(0, current - 1))
                  }
                  disabled={clusteringSavedSafePage === 0 || registryLoading}
                >
                  Previous
                </button>
                <span className="text-slate-500">
                  Page {clusteringSavedSafePage + 1} of {clusteringSavedPageCount}
                </span>
                <button
                  className="border border-line px-3 py-2 disabled:opacity-50"
                  onClick={() =>
                    setClusteringSavedPage((current) =>
                      Math.min(clusteringSavedPageCount - 1, current + 1),
                    )
                  }
                  disabled={
                    clusteringSavedSafePage + 1 >= clusteringSavedPageCount ||
                    registryLoading
                  }
                >
                  Next
                </button>
              </div>
            </div>
            <div className="mt-4 border border-line bg-slate-50 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Shift Definition Snapshot
                </div>
                {displayedSavedModel && (
                  <span className="text-xs text-petroblue">
                    Stored with opened model
                  </span>
                )}
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-4">
                {displayedShiftDefinitions.map((shift, index) => (
                  <div
                    className="border border-line bg-white p-3"
                    key={shift.shift_id}
                  >
                    <input
                      className="w-full border-b border-line pb-1 text-sm font-semibold disabled:bg-white"
                      value={shift.name}
                      disabled={Boolean(displayedSavedModel)}
                      onChange={(event) =>
                        setShiftDefinitions((current) =>
                          current.map((row, rowIndex) =>
                            rowIndex === index
                              ? { ...row, name: event.target.value }
                              : row,
                          ),
                        )
                      }
                    />
                    <div className="mt-2 flex items-center gap-2">
                      <input
                        className="w-full border border-line p-1 text-xs disabled:bg-white"
                        type="time"
                        value={shift.start_time}
                        disabled={Boolean(displayedSavedModel)}
                        onChange={(event) =>
                          setShiftDefinitions((current) =>
                            current.map((row, rowIndex) =>
                              rowIndex === index
                                ? { ...row, start_time: event.target.value }
                                : row,
                            ),
                          )
                        }
                      />
                      <span>–</span>
                      <input
                        className="w-full border border-line p-1 text-xs disabled:bg-white"
                        type="time"
                        value={shift.end_time}
                        disabled={Boolean(displayedSavedModel)}
                        onChange={(event) =>
                          setShiftDefinitions((current) =>
                            current.map((row, rowIndex) =>
                              rowIndex === index
                                ? { ...row, end_time: event.target.value }
                                : row,
                            ),
                          )
                        }
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {trainingRun && (
            <section className="border border-line bg-white p-5">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Training Dataset
                  </div>
                  <h3 className="mt-1 text-lg font-semibold">
                    {trainingRun.status === "DATASET_READY"
                      ? "Dataset Ready for Validation"
                      : label(trainingRun.status)}
                  </h3>
                </div>
                <span
                  className={`border px-3 py-1 text-xs font-semibold ${badgeClass(trainingRun.status)}`}
                >
                  {label(trainingRun.status)}
                </span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
                <Metric
                  title="Total SPBU"
                  value={trainingRun.dataset_summary.total_spbu ?? 0}
                />
                <Metric
                  title="Sufficient"
                  value={trainingRun.dataset_summary.sufficient_count ?? 0}
                  hint="Only these SPBUs determine UMAP geometry and HDBSCAN core boundaries."
                />
                <Metric
                  title="Marginal"
                  value={trainingRun.dataset_summary.marginal_count ?? 0}
                  hint="Excluded from core fitting; eligible only for post-training projection."
                />
                <Metric
                  title="Insufficient"
                  value={trainingRun.dataset_summary.insufficient_count ?? 0}
                  hint="Not clustered and not HDBSCAN noise."
                />
                <Metric
                  title="Core Training"
                  value={trainingRun.dataset_summary.core_training_count ?? 0}
                />
                <Metric
                  title="Valid Coordinates"
                  value={
                    trainingRun.dataset_summary.valid_coordinate_count ?? 0
                  }
                />
                <Metric
                  title="Missing / Invalid"
                  value={
                    trainingRun.dataset_summary.invalid_coordinate_count ?? 0
                  }
                />
                <Metric
                  title="Geographic Coverage"
                  value={`${(trainingRun.dataset_summary.geographic_coverage_percentage ?? 0).toFixed(1)}%`}
                />
              </div>
              <div className="mt-3 border border-petroblue bg-petrocloud/40 px-4 py-3 text-sm text-petroink">
                Geographic Proximity:{" "}
                <strong>
                  {trainingRun.dataset_summary.geographic_proximity_enabled
                    ? "Enabled"
                    : "Disabled"}
                </strong>
                {" · "}Weights: Tag{" "}
                {pct(trainingRun.dataset_summary.feature_weights?.tag)} · Shift{" "}
                {pct(trainingRun.dataset_summary.feature_weights?.shift)} ·
                Pairing{" "}
                {pct(trainingRun.dataset_summary.feature_weights?.pairing)} ·
                Geography{" "}
                {pct(trainingRun.dataset_summary.feature_weights?.geographic)}
              </div>
              <button
                className="mt-4 text-sm font-semibold text-petroblue"
                onClick={() => setEngineBAdvanced((value) => !value)}
              >
                Advanced Algorithm Settings {engineBAdvanced ? "▴" : "▾"}
              </button>
              {engineBAdvanced && (
                <div className="mt-3 space-y-4 border border-line bg-slate-50 p-4">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Feature Weights · total {(weightTotal * 100).toFixed(0)}%
                    </div>
                    <div className="mt-2 grid gap-3 md:grid-cols-4">
                      {(["tag", "shift", "pairing", "geographic"] as const).map(
                        (key) => (
                          <label className="text-sm capitalize" key={key}>
                            {key}
                            <input
                              className="mt-1 w-full border border-line px-3 py-2"
                              type="number"
                              min="0"
                              max="1"
                              step="0.05"
                              value={trainingConfig.feature_weights[key]}
                              onChange={(event) =>
                                updateWeight(key, event.target.value)
                              }
                            />
                          </label>
                        ),
                      )}
                    </div>
                    {Math.abs(weightTotal - 1) > 0.000001 && (
                      <div className="mt-2 text-xs font-semibold text-rust">
                        Weights must equal exactly 1.00.
                      </div>
                    )}
                  </div>
                  <div className="grid gap-4 lg:grid-cols-3">
                    {(
                      [
                        "node2vec_parameters",
                        "umap_parameters",
                        "hdbscan_parameters",
                      ] as const
                    ).map((group) => (
                      <div key={group}>
                        <div
                          className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                          title={
                            group === "node2vec_parameters"
                              ? "Node2Vec converts the weighted SPBU co-shipment graph into numeric pairing vectors."
                              : group === "umap_parameters"
                                ? "UMAP reduces the fused feature space while preserving local behavioral neighborhoods."
                                : "HDBSCAN discovers variable-density clusters and may leave unique SPBUs as noise."
                          }
                        >
                          {group.replace("_parameters", "")}
                        </div>
                        <div className="mt-2 grid grid-cols-2 gap-2">
                          {Object.entries(trainingConfig[group]).map(
                            ([key, value]) => (
                              <label className="text-xs" key={key}>
                                {key}
                                <input
                                  className="mt-1 w-full border border-line p-2"
                                  value={value}
                                  onChange={(event) =>
                                    setTrainingConfig((current) => ({
                                      ...current,
                                      [group]: {
                                        ...current[group],
                                        [key]:
                                          typeof value === "number"
                                            ? Number(event.target.value)
                                            : event.target.value,
                                      },
                                    }))
                                  }
                                />
                              </label>
                            ),
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="grid gap-2 text-xs text-slate-500 lg:grid-cols-3">
                    <p>
                      <strong>Node2Vec:</strong> turns Phase 3 pairing
                      relationships into a vector while preserving graph
                      neighborhoods.
                    </p>
                    <p>
                      <strong>UMAP:</strong> reduces fused behavior features
                      before clustering and separately creates the 2D map.
                    </p>
                    <p>
                      <strong>HDBSCAN:</strong> finds natural density groups
                      without selecting a cluster count and retains noise as a
                      valid outcome.
                    </p>
                  </div>
                  <button
                    className="text-xs font-semibold text-petroblue"
                    onClick={() => setTrainingConfig(defaultConfig)}
                  >
                    Reset defaults
                  </button>
                </div>
              )}
              {!trainedResult && (
                <div className="mt-4 flex gap-2">
                  <button
                    className="inline-flex items-center gap-2 bg-petroblue px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
                    onClick={trainModel}
                    disabled={
                      engineBLoading || Math.abs(weightTotal - 1) > 0.000001
                    }
                  >
                    <Play size={16} />{" "}
                    {engineBLoading ? "Training…" : "Train Model"}
                  </button>
                  <button
                    className="border border-line px-4 py-2 text-sm"
                    onClick={() => setTrainingRun(null)}
                  >
                    Discard Dataset
                  </button>
                </div>
              )}
            </section>
          )}

          {displayedClusterResult && (
            <>
              {displayedSavedModel && (
                <section className="flex flex-col gap-3 border border-petroblue bg-petrocloud/50 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-petroblue">
                      Opened Saved Model
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <h3 className="text-lg font-semibold">
                        {displayedSavedModel.model_name} v
                        {displayedSavedModel.model_version}
                      </h3>
                      <span
                        className={`border px-2 py-1 text-xs ${badgeClass(displayedSavedModel.model_status)}`}
                      >
                        {label(displayedSavedModel.model_status)}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">
                      Training period {displayedSavedModel.training_start_date}{" "}
                      – {displayedSavedModel.training_end_date} ·{" "}
                      {displayedSavedModel.algorithm_version}
                    </p>
                  </div>
                  <button
                    className="border border-line bg-white px-4 py-2 text-sm"
                    onClick={() => {
                      setDisplayedSavedModel(null);
                      setSelectedCluster(null);
                    }}
                  >
                    Close Saved Model
                  </button>
                </section>
              )}
              <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
                <Metric
                  title="Core Training SPBU"
                  value={evidenceCounts.historical}
                  hint="SPBUs used to fit UMAP/HDBSCAN."
                />
                <Metric
                  title="Marginal SPBU"
                  value={evidenceCounts.marginal}
                  hint="Excluded from core fitting and considered only for projection."
                />
                <Metric
                  title="Insufficient SPBU"
                  value={evidenceCounts.insufficient}
                />
                <Metric title="Core Noise" value={evidenceCounts.coreNoise} />
                <Metric
                  title="Marginal Projected"
                  value={evidenceCounts.marginalProjected}
                />
                <Metric
                  title="Marginal Unassigned"
                  value={
                    evidenceCounts.marginal - evidenceCounts.marginalProjected
                  }
                />
                <Metric
                  title="Average Core Membership"
                  value={pct(
                    displayedClusterResult.summary
                      .average_membership_probability,
                  )}
                />
                <Metric
                  title="Average Projection Confidence"
                  value={pct(
                    displayedClusterResult.summary
                      .average_projection_confidence,
                  )}
                />
                <Metric
                  title="Valid Coordinates"
                  value={displayedClusterResult.summary.valid_coordinate_count}
                />
                <Metric
                  title="Geographic Coverage"
                  value={`${displayedClusterResult.summary.geographic_coverage_percentage.toFixed(1)}%`}
                />
              </section>
              <div className="border border-amber bg-amber/5 px-4 py-3 text-sm text-amber">
                Model behavior was learned from{" "}
                {evidenceCounts.historical.toLocaleString()} SUFFICIENT SPBUs.
                Marginal projection never changes core boundaries, and{" "}
                {evidenceCounts.insufficient.toLocaleString()} INSUFFICIENT
                SPBUs remain unassigned—not HDBSCAN noise.
              </div>
              {displayedClusterResult.warnings.map((warning) => (
                <div
                  key={warning}
                  className="border border-amber bg-amber/5 px-4 py-3 text-sm text-amber"
                >
                  {warning}
                </div>
              ))}
              <section className="border border-line bg-white p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                      Evidence Display
                    </h3>
                    <p className="mt-1 text-xs text-slate-500">
                      The default view shows only SPBUs that trained the
                      behavioral model.
                    </p>
                  </div>
                  <div
                    className="flex flex-wrap gap-2"
                    aria-label="Behavioral evidence filter"
                  >
                    {(
                      [
                        [
                          "CORE",
                          `Core Only (${evidenceCounts.historical.toLocaleString()})`,
                        ],
                        [
                          "MARGINAL",
                          `Marginal Overlay (${evidenceCounts.marginal.toLocaleString()})`,
                        ],
                        [
                          "ALL",
                          `Core + Marginal (${(evidenceCounts.historical + evidenceCounts.marginal).toLocaleString()})`,
                        ],
                      ] as Array<[EvidenceFilter, string]>
                    ).map(([value, textValue]) => (
                      <button
                        type="button"
                        key={value}
                        className={`border px-3 py-2 text-xs font-semibold ${evidenceFilter === value ? "border-petroblue bg-petroblue text-white" : "border-line bg-white text-petroink hover:border-petroblue"}`}
                        onClick={() => setEvidenceFilter(value)}
                      >
                        {textValue}
                      </button>
                    ))}
                  </div>
                </div>
              </section>
              <section className="grid gap-4 lg:grid-cols-2">
                <div className="border border-line bg-white p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                    UMAP Cluster Map
                  </h3>
                  <ReactECharts
                    style={{ height: 420 }}
                    option={{
                      color: behavioralClusterLabels.map((clusterLabel) =>
                        clusterColor(clusterLabel, behavioralClusterLabels),
                      ),
                      tooltip: {
                        formatter: (params: {
                          data: {
                            name: string;
                            value: number[];
                            detail: Assignment;
                          };
                        }) =>
                          `${params.data.name}<br/>${params.data.detail.cluster_label}<br/>Data Sufficiency: ${params.data.detail.data_sufficiency_status} (${score(params.data.detail.data_sufficiency_score)})<br/>Assignment: ${label(params.data.detail.cluster_assignment_type)}<br/>Historical observations: ${params.data.detail.shipment_observation_count ?? 0}<br/>${confidenceLabel(params.data.detail)}: ${pct(assignmentConfidence(params.data.detail))}<br/>${params.data.detail.dominant_shift}<br/>${params.data.detail.key_tags.slice(0, 3).join(", ")}`,
                      },
                      xAxis: { show: false },
                      yAxis: { show: false },
                      series: behavioralClusterLabels.map((clusterLabel) => ({
                        name: clusterLabel,
                        type: "scatter",
                        symbolSize: 11,
                        data: evidenceFilteredAssignments
                          .filter((row) => row.cluster_label === clusterLabel)
                          .map((row) => ({
                            name: row.spbu_code,
                            value: [
                              row.visualization_x as number,
                              row.visualization_y as number,
                            ],
                            detail: row,
                            symbol: hasHistoricalEvidence(row)
                              ? "circle"
                              : "emptyCircle",
                            symbolSize: hasHistoricalEvidence(row) ? 11 : 14,
                            itemStyle: hasHistoricalEvidence(row)
                              ? undefined
                              : {
                                  color:
                                    (row.shipment_observation_count ?? 0) === 0
                                      ? "#e2e8f0"
                                      : clusterColor(
                                          row.cluster_label,
                                          behavioralClusterLabels,
                                        ),
                                  borderColor: clusterColor(
                                    row.cluster_label,
                                    behavioralClusterLabels,
                                  ),
                                  borderWidth: 2,
                                  opacity: 0.75,
                                },
                          })),
                      })),
                    }}
                  />
                </div>
                <div className="border border-line bg-white p-4">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                    Cluster Profiles · Historical Evidence Only
                  </h3>
                  <div className="mt-3 max-h-[420px] space-y-3 overflow-y-auto">
                    {displayedClusterResult.cluster_profiles.map((profile) => (
                      <button
                        className="w-full border border-line p-3 text-left hover:bg-petrocloud"
                        key={profile.cluster_id}
                        onClick={() => setSelectedCluster(profile)}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-semibold">
                            {profile.cluster_label}
                          </span>
                          <span className="text-right text-sm">
                            {profile.historical_member_count} core ·{" "}
                            {profile.projected_member_count ?? 0} projected
                          </span>
                        </div>
                        <div className="mt-2 text-sm text-slate-600">
                          Dominant shift: {profile.dominant_shift}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          {profile.common_tags
                            .slice(0, 3)
                            .map((tag) => tag.tag)
                            .join(" · ") ||
                            "No tag shared by at least 50% of historical members"}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          Historical average membership{" "}
                          {pct(profile.average_membership_probability)} ·{" "}
                          {profile.low_confidence_member_count} low-confidence
                          historical members
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
                <GeographicClusterMap
                  assignments={displayedClusterResult.assignments}
                  depot={geographicDepot}
                />
              </section>
              <section className="border border-line bg-white p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                  Cluster Membership
                </h3>
                <div className="mt-3 grid gap-2 md:grid-cols-4 xl:grid-cols-8">
                  <select
                    className="border border-line p-2 text-xs"
                    value={sufficiencyFilter}
                    onChange={(event) =>
                      setSufficiencyFilter(event.target.value)
                    }
                  >
                    <option value="ALL">All sufficiency</option>
                    <option value="SUFFICIENT">Sufficient</option>
                    <option value="MARGINAL">Marginal</option>
                    <option value="INSUFFICIENT">Insufficient</option>
                  </select>
                  <select
                    className="border border-line p-2 text-xs"
                    value={assignmentTypeFilter}
                    onChange={(event) =>
                      setAssignmentTypeFilter(event.target.value)
                    }
                  >
                    <option value="ALL">All assignment types</option>
                    {[
                      "CORE_MEMBER",
                      "CORE_NOISE",
                      "MARGINAL_PROJECTED",
                      "MARGINAL_UNASSIGNED",
                      "INSUFFICIENT_UNASSIGNED",
                    ].map((value) => (
                      <option value={value} key={value}>
                        {label(value)}
                      </option>
                    ))}
                  </select>
                  <select
                    className="border border-line p-2 text-xs"
                    value={clusterFilter}
                    onChange={(event) => setClusterFilter(event.target.value)}
                  >
                    <option value="ALL">All clusters</option>
                    <option value="UNASSIGNED">Not Assigned</option>
                    {Array.from(
                      new Set(
                        displayedClusterResult.assignments
                          .filter((row) => row.cluster_id !== null)
                          .map((row) => row.cluster_id as number),
                      ),
                    )
                      .sort((a, b) => a - b)
                      .map((value) => (
                        <option value={String(value)} key={value}>
                          Cluster {value + 1}
                        </option>
                      ))}
                  </select>
                  <select
                    className="border border-line p-2 text-xs"
                    value={noiseFilter}
                    onChange={(event) => setNoiseFilter(event.target.value)}
                  >
                    <option value="ALL">All noise states</option>
                    <option value="YES">Core noise only</option>
                    <option value="NO">Exclude core noise</option>
                  </select>
                  <input
                    className="border border-line p-2 text-xs"
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    placeholder="Min projection confidence"
                    value={minimumProjectionConfidence}
                    onChange={(event) =>
                      setMinimumProjectionConfidence(event.target.value)
                    }
                  />
                  <input
                    className="border border-line p-2 text-xs"
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    placeholder="Min membership probability"
                    value={minimumMembershipProbability}
                    onChange={(event) =>
                      setMinimumMembershipProbability(event.target.value)
                    }
                  />
                  <select
                    className="border border-line p-2 text-xs"
                    value={geographicStatusFilter}
                    onChange={(event) =>
                      setGeographicStatusFilter(event.target.value)
                    }
                  >
                    <option value="ALL">All geographic status</option>
                    <option value="VALID">Valid coordinate</option>
                    <option value="MISSING">Missing coordinate</option>
                    <option value="INVALID">Invalid coordinate</option>
                  </select>
                  <input
                    className="border border-line p-2 text-xs"
                    placeholder="Search SPBU"
                    value={clusterSpbuSearch}
                    onChange={(event) =>
                      setClusterSpbuSearch(event.target.value)
                    }
                  />
                </div>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                        <th className="px-3 py-2">SPBU</th>
                        <th className="px-3 py-2">Sufficiency</th>
                        <th className="px-3 py-2">Cluster</th>
                        <th className="px-3 py-2">Assignment Type</th>
                        <th className="px-3 py-2">Membership Probability</th>
                        <th className="px-3 py-2">Projection Confidence</th>
                        <th className="px-3 py-2">Dominant Shift</th>
                        <th className="px-3 py-2">Key Tags</th>
                        <th className="px-3 py-2">Geographic Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {clusterMembershipPageRows.map((row) => (
                        <tr
                          className="cursor-pointer border-b border-line hover:bg-petrocloud/40"
                          key={row.spbu_id}
                          onClick={() => setSelectedAssignment(row)}
                        >
                          <td className="px-3 py-2">
                            <div className="font-semibold">{row.spbu_code}</div>
                            <div className="text-xs text-slate-500">
                              {row.spbu_name}
                            </div>
                          </td>
                          <td className="px-3 py-2">
                            <span
                              className={`border px-2 py-1 text-xs font-semibold ${badgeClass(row.data_sufficiency_status)}`}
                            >
                              {row.data_sufficiency_status}
                            </span>
                            <div className="mt-1 text-xs">
                              {score(row.data_sufficiency_score)}/100
                            </div>
                          </td>
                          <td className="px-3 py-2">{row.cluster_label}</td>
                          <td className="px-3 py-2">
                            {label(row.cluster_assignment_type)}
                          </td>
                          <td className="px-3 py-2">
                            {pct(row.membership_probability)}
                          </td>
                          <td className="px-3 py-2">
                            {pct(row.projection_confidence)}
                          </td>
                          <td className="px-3 py-2">{row.dominant_shift}</td>
                          <td className="max-w-72 px-3 py-2 text-xs">
                            {row.key_tags.slice(0, 4).join(", ") || "-"}
                          </td>
                          <td className="px-3 py-2">
                            {row.geographic_data_status}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-4 flex flex-col gap-3 border-t border-line pt-4 text-sm sm:flex-row sm:items-center sm:justify-between">
                  <div className="text-slate-500">
                    Showing {clusterMembershipRangeStart.toLocaleString()}–
                    {clusterMembershipRangeEnd.toLocaleString()} of{" "}
                    {clusterMembershipAssignments.length.toLocaleString()} SPBUs
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="inline-flex items-center gap-2 text-slate-500">
                      Rows per page
                      <select
                        className="border border-line bg-white px-3 py-2 text-sm text-petroink"
                        value={clusterMembershipPageSize}
                        onChange={(event) => {
                          setClusterMembershipPageSize(
                            Number(event.target.value),
                          );
                          setClusterMembershipPage(0);
                        }}
                        title="Cluster membership rows per page"
                      >
                        <option value={10}>10</option>
                        <option value={20}>20</option>
                        <option value={50}>50</option>
                      </select>
                    </label>
                    <button
                      className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() =>
                        setClusterMembershipPage((current) =>
                          Math.max(0, current - 1),
                        )
                      }
                      disabled={clusterMembershipSafePage === 0}
                    >
                      Previous
                    </button>
                    <span className="min-w-24 text-center text-slate-500">
                      Page {clusterMembershipSafePage + 1} of{" "}
                      {clusterMembershipPageCount}
                    </span>
                    <button
                      className="border border-line px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() =>
                        setClusterMembershipPage((current) =>
                          Math.min(clusterMembershipPageCount - 1, current + 1),
                        )
                      }
                      disabled={
                        clusterMembershipSafePage + 1 >=
                        clusterMembershipPageCount
                      }
                    >
                      Next
                    </button>
                  </div>
                </div>
                {displayedSavedModel ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      className="border border-line px-4 py-2 text-sm"
                      onClick={() => {
                        setOpenedModel(displayedSavedModel);
                        setTab("registry");
                      }}
                    >
                      View Registry Details
                    </button>
                    <button
                      className="border border-line px-4 py-2 text-sm"
                      onClick={() => {
                        setDisplayedSavedModel(null);
                        setSelectedCluster(null);
                      }}
                    >
                      Close Saved Model
                    </button>
                  </div>
                ) : (
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      className="border border-line px-4 py-2 text-sm"
                      onClick={() => setTrainingRun(null)}
                    >
                      Discard Result
                    </button>
                    <button
                      className="border border-line px-4 py-2 text-sm"
                      onClick={() =>
                        setTrainingRun((current) =>
                          current ? { ...current, result: {} } : current,
                        )
                      }
                    >
                      Adjust Parameters & Retrain
                    </button>
                  </div>
                )}
              </section>
            </>
          )}
        </>
      )}

      {tab === "registry" && (
        <>
          <section className="border border-line bg-white p-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-display text-xl font-semibold">
                  Model Registry
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Saved, versioned Engine B packages. Only one model may be
                  active per depot.
                </p>
              </div>
              <button
                className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm"
                onClick={refreshRegistry}
              >
                <RefreshCw
                  size={16}
                  className={registryLoading ? "animate-spin" : ""}
                />{" "}
                Refresh
              </button>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">Model Name</th>
                    <th className="px-3 py-2">Version</th>
                    <th className="px-3 py-2">Depot</th>
                    <th className="px-3 py-2">Training Period</th>
                    <th className="px-3 py-2">Total SPBU</th>
                    <th className="px-3 py-2">Core Training</th>
                    <th className="px-3 py-2">
                      Sufficient / Marginal / Insufficient
                    </th>
                    <th className="px-3 py-2">Geography</th>
                    <th className="px-3 py-2">Clusters</th>
                    <th className="px-3 py-2">Noise</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((model) => (
                    <tr className="border-b border-line" key={model.model_id}>
                      <td className="px-3 py-2 font-semibold">
                        {model.model_name}
                      </td>
                      <td className="px-3 py-2">v{model.model_version}</td>
                      <td className="px-3 py-2">{model.depot_name}</td>
                      <td className="whitespace-nowrap px-3 py-2">
                        {model.training_start_date} – {model.training_end_date}
                      </td>
                      <td className="px-3 py-2">{model.total_spbu_count}</td>
                      <td className="px-3 py-2">
                        {model.core_training_spbu_count}
                      </td>
                      <td className="px-3 py-2">
                        {pct(
                          model.sufficient_spbu_count /
                            Math.max(1, model.total_spbu_count),
                        )}{" "}
                        /{" "}
                        {pct(
                          model.marginal_spbu_count /
                            Math.max(1, model.total_spbu_count),
                        )}{" "}
                        /{" "}
                        {pct(
                          model.insufficient_spbu_count /
                            Math.max(1, model.total_spbu_count),
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {model.geographic_proximity_enabled
                          ? "Enabled"
                          : "Disabled"}{" "}
                        · {pct(model.geographic_weight)}
                      </td>
                      <td className="px-3 py-2">{model.cluster_count}</td>
                      <td className="px-3 py-2">{model.noise_spbu_count}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`border px-2 py-1 text-xs ${badgeClass(model.model_status)}`}
                        >
                          {model.model_status}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex gap-1">
                          <button
                            className="border border-line p-2"
                            onClick={() => openModel(model.model_id)}
                            title="Open"
                          >
                            <Eye size={15} />
                          </button>
                          {model.model_status !== "ACTIVE" && (
                            <button
                              className="border border-line p-2"
                              onClick={() => activateModel(model.model_id)}
                              title="Activate"
                            >
                              <CheckCircle2 size={15} />
                            </button>
                          )}
                          <button
                            className="border border-line p-2"
                            onClick={() => duplicateModel(model.model_id)}
                            title="Duplicate configuration"
                          >
                            <Copy size={15} />
                          </button>
                          {model.model_status !== "ARCHIVED" && (
                            <button
                              className="border border-line p-2"
                              onClick={() => archiveModel(model.model_id)}
                              title="Archive"
                            >
                              <Archive size={15} />
                            </button>
                          )}
                          <button
                            className="border border-line p-2 text-rust disabled:opacity-30"
                            onClick={() => deleteModel(model)}
                            disabled={model.model_status === "ACTIVE"}
                            title="Delete"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {models.length === 0 && (
                    <tr>
                      <td
                        colSpan={12}
                        className="px-3 py-8 text-center text-slate-500"
                      >
                        No saved models for this depot.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
          <section className="border border-line bg-white p-5">
            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-600">
              <Scale size={17} /> Compare Models
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <select
                className="min-w-64 border border-line px-3 py-2 text-sm"
                value={compareA}
                onChange={(event) => setCompareA(event.target.value)}
              >
                <option value="">Model A</option>
                {models.map((model) => (
                  <option key={model.model_id} value={model.model_id}>
                    {model.model_name} v{model.model_version}
                  </option>
                ))}
              </select>
              <select
                className="min-w-64 border border-line px-3 py-2 text-sm"
                value={compareB}
                onChange={(event) => setCompareB(event.target.value)}
              >
                <option value="">Model B</option>
                {models.map((model) => (
                  <option key={model.model_id} value={model.model_id}>
                    {model.model_name} v{model.model_version}
                  </option>
                ))}
              </select>
              <button
                className="bg-petroblue px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
                disabled={!compareA || !compareB || compareA === compareB}
                onClick={compareModels}
              >
                Compare
              </button>
            </div>
            {comparison && (
              <div className="mt-4 space-y-4">
                <p className="text-xs text-slate-500">
                  {comparison.methodology}
                </p>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
                  <Metric
                    title="Matched Clusters"
                    value={comparison.cluster_matches.length}
                  />
                  <Metric
                    title="Stable Neighborhood"
                    value={
                      comparison.stable_cluster_neighborhood_spbu_ids.length
                    }
                  />
                  <Metric
                    title="Changed Neighborhood"
                    value={comparison.matched_cluster_changed_spbu_ids.length}
                  />
                  <Metric
                    title="New Noise"
                    value={comparison.new_noise_spbu_ids.length}
                  />
                  <Metric
                    title="Returned from Noise"
                    value={
                      comparison.noise_returning_to_cluster_spbu_ids.length
                    }
                  />
                  <Metric
                    title="Splits / Merges"
                    value={`${comparison.cluster_splits.length} / ${comparison.cluster_merges.length}`}
                  />
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  {(
                    [
                      ["Model A", comparison.model_a],
                      ["Model B", comparison.model_b],
                    ] as const
                  ).map(([title, model]) => (
                    <div className="border border-line p-4" key={title}>
                      <h3 className="font-semibold">
                        {title} · {model.model_name} v{model.model_version}
                      </h3>
                      <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                        <div>Total / Core</div>
                        <div>
                          {model.total_spbu_count} /{" "}
                          {model.core_training_spbu_count}
                        </div>
                        <div>Sufficient / Marginal / Insufficient</div>
                        <div>
                          {model.sufficient_spbu_count} /{" "}
                          {model.marginal_spbu_count} /{" "}
                          {model.insufficient_spbu_count}
                        </div>
                        <div>Weights T / S / P / G</div>
                        <div>
                          {pct(model.feature_weights.tag)} /{" "}
                          {pct(model.feature_weights.shift)} /{" "}
                          {pct(model.feature_weights.pairing)} /{" "}
                          {pct(model.feature_weights.geographic)}
                        </div>
                        <div>Geography</div>
                        <div>
                          {model.geographic_proximity_enabled
                            ? "Enabled"
                            : "Disabled"}{" "}
                          · K{" "}
                          {String(
                            model.geographic_configuration
                              .k_nearest_neighbors ?? "-",
                          )}{" "}
                          · max{" "}
                          {String(
                            model.geographic_configuration
                              .maximum_proximity_distance_km ?? "-",
                          )}{" "}
                          km
                        </div>
                        <div>Coverage</div>
                        <div>
                          {model.geographic_coverage_percentage.toFixed(1)}%
                        </div>
                        <div>Clusters / Core Noise</div>
                        <div>
                          {model.cluster_count} / {model.noise_spbu_count}
                        </div>
                        <div>Avg Core / Projection</div>
                        <div>
                          {pct(model.average_membership_probability)} /{" "}
                          {pct(model.average_projection_confidence)}
                        </div>
                        <div>Marginal Projection Rate</div>
                        <div>
                          {pct(
                            model.marginal_projected_count /
                              Math.max(1, model.marginal_spbu_count),
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="border border-line p-4">
                  <h3 className="font-semibold">Data Maturity Changes</h3>
                  <div className="mt-2 flex flex-wrap gap-2 text-sm">
                    {comparison.data_maturity_transitions.map((transition) => (
                      <span
                        className="border border-line px-3 py-2"
                        key={transition.transition}
                        title={transition.spbu_ids.join(", ")}
                      >
                        {transition.transition} · {transition.count}
                      </span>
                    ))}
                    {comparison.data_maturity_transitions.length === 0 && (
                      <span className="text-slate-500">
                        No sufficiency-status transitions among shared SPBUs.
                      </span>
                    )}
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                        <th className="px-3 py-2">Model A Cluster</th>
                        <th className="px-3 py-2">Matched Model B Cluster</th>
                        <th className="px-3 py-2">Jaccard Similarity</th>
                        <th className="px-3 py-2">Shared SPBU</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparison.cluster_matches.map((match) => (
                        <tr
                          className="border-b border-line"
                          key={`${match.model_a_cluster_id}-${match.model_b_cluster_id}`}
                        >
                          <td className="px-3 py-2">
                            Cluster {match.model_a_cluster_id + 1}
                          </td>
                          <td className="px-3 py-2">
                            Cluster {match.model_b_cluster_id + 1}
                          </td>
                          <td className="px-3 py-2">
                            {pct(match.jaccard_similarity)}
                          </td>
                          <td className="px-3 py-2">
                            {match.intersection_count}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
        </>
      )}

      {selectedConcentration && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/35">
          <div className="h-full w-full max-w-3xl overflow-y-auto bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  SPBU Concentration Detail
                </div>
                <h2 className="mt-1 text-xl font-semibold">
                  {selectedConcentration.spbu_code} ·{" "}
                  {selectedConcentration.spbu_name}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Baseline {concentrationRun?.baseline_start_date} –{" "}
                  {concentrationRun?.baseline_end_date}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-semibold uppercase tracking-wide text-slate-500">
                    SPBU Tag
                  </span>
                  {selectedConcentration.spbu_tags?.length ? (
                    selectedConcentration.spbu_tags.map((tag) => (
                      <span
                        className="border border-petroblue/30 bg-petrocloud px-2 py-1 font-semibold text-petroink"
                        key={tag}
                      >
                        {tag}
                      </span>
                    ))
                  ) : (
                    <span className="text-slate-500">-</span>
                  )}
                </div>
              </div>
              <button
                className="border border-line p-2"
                onClick={() => setSelectedConcentration(null)}
              >
                <X size={17} />
              </button>
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                title="Compatible MT"
                value={selectedConcentration.compatible_mt_count}
              />
              <Metric
                title="Historically Used"
                value={selectedConcentration.historically_used_mt_count}
              />
              <Metric
                title="Dominant Share"
                value={pct(selectedConcentration.dominant_mt_share)}
              />
              <Metric
                title="Anomaly Score"
                value={score(selectedConcentration.concentration_anomaly_score)}
              />
              <Metric
                title="Utilization Breadth"
                value={pct(selectedConcentration.utilization_breadth)}
              />
              <Metric title="HHI" value={score(selectedConcentration.hhi)} />
              <Metric
                title="Entropy"
                value={score(selectedConcentration.entropy)}
              />
              <Metric
                title="Normalized Entropy"
                value={score(selectedConcentration.normalized_entropy)}
              />
            </div>
            <div className="mt-5 border border-line p-4">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                Historical MT Distribution
              </h3>
              <ReactECharts
                style={{ height: 320 }}
                option={{
                  grid: { left: 60, right: 20, bottom: 80 },
                  xAxis: {
                    type: "category",
                    data: selectedConcentration.mt_distribution
                      .filter((row) => row.historically_used)
                      .map((row) => row.mt_registration),
                    axisLabel: { rotate: 45 },
                  },
                  yAxis: { type: "value", name: "Shipment count" },
                  tooltip: {
                    trigger: "axis",
                    axisPointer: { type: "shadow" },
                    formatter: (params: Array<{ dataIndex: number }>) => {
                      const row = selectedConcentration.mt_distribution.filter(
                        (distribution) => distribution.historically_used,
                      )[params[0]?.dataIndex ?? -1];
                      return row
                        ? `<b>${escapeTooltip(row.mt_registration)}</b><br/>MT Tag: ${escapeTooltip(formatTags(row.mt_tags))}<br/>Shipment count: ${row.shipment_count}<br/>Historical share: ${pct(row.historical_share)}`
                        : "";
                    },
                  },
                  series: [
                    {
                      type: "bar",
                      data: selectedConcentration.mt_distribution
                        .filter((row) => row.historically_used)
                        .map((row) => row.shipment_count),
                    },
                  ],
                }}
              />
            </div>
            <div className="mt-5 border border-line p-4">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                Peer Context
              </h3>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                {Object.entries(selectedConcentration.peer_statistics).map(
                  ([key, value]) => (
                    <div key={key}>
                      <span className="text-slate-500">{label(key)}:</span>{" "}
                      <span className="font-semibold">{String(value)}</span>
                    </div>
                  ),
                )}
              </div>
            </div>
            <div className="mt-5 border border-line p-4">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                Compatible but Historically Unused MT
              </h3>
              <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {selectedConcentration.mt_distribution
                  .filter((row) => !row.historically_used)
                  .map((row) => (
                    <div
                      className="border border-line px-3 py-2 text-sm"
                      key={row.mt_id}
                    >
                      {row.mt_registration}
                    </div>
                  ))}
                {selectedConcentration.mt_distribution.every(
                  (row) => row.historically_used,
                ) && (
                  <div className="text-sm text-slate-500">
                    Every compatible MT was historically used.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {selectedAssignment && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/35">
          <div className="h-full w-full max-w-3xl overflow-y-auto bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  SPBU Behavioral Detail
                </div>
                <h2 className="mt-1 text-xl font-semibold">
                  {selectedAssignment.spbu_code} ·{" "}
                  {selectedAssignment.spbu_name}
                </h2>
              </div>
              <button
                className="border border-line p-2"
                onClick={() => setSelectedAssignment(null)}
              >
                <X size={17} />
              </button>
            </div>
            <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-slate-600">
              Data Sufficiency
            </h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                title="Score"
                value={`${score(selectedAssignment.data_sufficiency_score)}/100`}
              />
              <Metric
                title="Status"
                value={selectedAssignment.data_sufficiency_status}
              />
              <Metric
                title="Shipment Observations"
                value={selectedAssignment.shipment_observation_count ?? 0}
              />
              <Metric
                title="Operating Days"
                value={selectedAssignment.operating_day_count ?? 0}
              />
              <Metric
                title="Period Coverage"
                value={pct(selectedAssignment.training_period_coverage)}
              />
              <Metric
                title="Shift Coverage"
                value={pct(selectedAssignment.shift_observation_coverage)}
              />
              <Metric
                title="Pairing Evidence"
                value={selectedAssignment.pairing_observation_count ?? 0}
              />
              <Metric
                title="Recency"
                value={
                  selectedAssignment.recency_age_days === null ||
                  selectedAssignment.recency_age_days === undefined
                    ? "No history"
                    : `${selectedAssignment.recency_age_days} days`
                }
              />
            </div>
            <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-slate-600">
              Cluster Result
            </h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                title="Assignment Type"
                value={label(selectedAssignment.cluster_assignment_type)}
              />
              <Metric
                title="Cluster"
                value={selectedAssignment.cluster_label}
              />
              <Metric
                title="Membership Probability"
                value={pct(selectedAssignment.membership_probability)}
              />
              <Metric
                title="Projection Confidence"
                value={pct(selectedAssignment.projection_confidence)}
              />
            </div>
            {selectedAssignment.unassigned_reason && (
              <div className="mt-3 border border-amber bg-amber/5 px-4 py-3 text-sm text-amber">
                {selectedAssignment.unassigned_reason}
              </div>
            )}
            <h3 className="mt-5 text-sm font-semibold uppercase tracking-wide text-slate-600">
              Geographic Data
            </h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                title="Status"
                value={selectedAssignment.geographic_data_status}
              />
              <Metric
                title="Latitude"
                value={selectedAssignment.latitude ?? "-"}
              />
              <Metric
                title="Longitude"
                value={selectedAssignment.longitude ?? "-"}
              />
              <Metric
                title="Nearest SPBU"
                value={
                  selectedAssignment.nearest_spbu_distance_km === null ||
                  selectedAssignment.nearest_spbu_distance_km === undefined
                    ? "-"
                    : `${score(selectedAssignment.nearest_spbu_distance_km)} km`
                }
              />
              <Metric
                title="Average K-Nearest"
                value={
                  selectedAssignment.average_k_nearest_distance_km === null ||
                  selectedAssignment.average_k_nearest_distance_km === undefined
                    ? "-"
                    : `${score(selectedAssignment.average_k_nearest_distance_km)} km`
                }
              />
            </div>
          </div>
        </div>
      )}

      {selectedCluster && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto bg-white p-5 shadow-xl">
            <div className="flex justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Cluster Detail
                </div>
                <h2 className="mt-1 text-xl font-semibold">
                  {selectedCluster.cluster_label}
                </h2>
              </div>
              <button
                className="border border-line p-2"
                onClick={() => setSelectedCluster(null)}
              >
                <X size={17} />
              </button>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                title="Core Members"
                value={selectedCluster.historical_member_count}
              />
              <Metric
                title="Marginal Projected"
                value={selectedCluster.projected_member_count ?? 0}
              />
              <Metric
                title="Historical Avg Membership"
                value={pct(selectedCluster.average_membership_probability)}
              />
              <Metric
                title="Historical Low Confidence"
                value={selectedCluster.low_confidence_member_count}
              />
            </div>
            <div className="mt-4 border border-petroblue bg-petrocloud/40 px-4 py-3 text-sm text-petroink">
              Tag, shift, pairing, geography, and membership statistics below
              use CORE_MEMBER SPBUs only. Projected marginal SPBUs are listed
              separately and never define the cluster.
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div className="border border-line p-4">
                <h3 className="font-semibold">Tag Profile</h3>
                <div className="mt-2 space-y-2 text-sm">
                  {selectedCluster.common_tags.map((tag) => (
                    <div key={tag.tag}>
                      {tag.tag} · {pct(tag.member_share)}
                    </div>
                  ))}
                </div>
              </div>
              <div className="border border-line p-4">
                <h3 className="font-semibold">Shift Profile</h3>
                <div className="mt-2 space-y-2 text-sm">
                  {selectedCluster.shift_distribution.map((shift) => (
                    <div key={shift.shift_id}>
                      {shift.shift_name} · {pct(shift.share)}
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-4 border border-line p-4">
              <h3 className="font-semibold">Covered SPBUs</h3>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {displayedClusterResult?.assignments
                  .filter(
                    (assignment) =>
                      assignment.cluster_id === selectedCluster.cluster_id &&
                      !assignment.is_noise,
                  )
                  .map((assignment) => (
                    <div
                      className="border border-line px-3 py-2 text-sm"
                      key={assignment.spbu_id}
                    >
                      <div>
                        <span className="font-semibold">
                          {assignment.spbu_code}
                        </span>{" "}
                        · {assignment.spbu_name}
                      </div>
                      <div
                        className={`mt-1 text-xs ${hasHistoricalEvidence(assignment) ? "text-mint" : "text-amber"}`}
                      >
                        {evidenceStatus(assignment)} ·{" "}
                        {(
                          assignment.shipment_observation_count ?? 0
                        ).toLocaleString()}{" "}
                        observations
                      </div>
                    </div>
                  ))}
              </div>
            </div>
            <div className="mt-4 border border-line p-4">
              <h3 className="font-semibold">Top Internal Pairings</h3>
              <div className="mt-2 space-y-2 text-sm">
                {selectedCluster.top_internal_pairings.map((pair) => (
                  <div key={`${pair.spbu_a_code}-${pair.spbu_b_code}`}>
                    {pair.spbu_a_code} ↔ {pair.spbu_b_code} · {pair.pair_count}{" "}
                    shipments · strength {pct(pair.pairing_strength)}
                  </div>
                ))}
                {selectedCluster.top_internal_pairings.length === 0 && (
                  <div className="text-slate-500">
                    No internal co-shipment edges.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {concentrationSaveDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
          <div className="w-full max-w-lg border border-line bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">
                  Save Concentration Analysis
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  Stores a named reference to the completed Engine A result and
                  its current table filters. Loading does not rerun the analysis.
                </p>
              </div>
              <button onClick={() => setConcentrationSaveDialog(false)}>
                <X size={17} />
              </button>
            </div>
            <label className="mt-4 block text-xs font-semibold uppercase tracking-wide text-slate-500">
              Analysis Name *
              <input
                className="mt-1 w-full border border-line px-3 py-2 text-sm"
                value={concentrationSaveName}
                onChange={(event) => setConcentrationSaveName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter")
                    void saveCurrentConcentrationAnalysis();
                }}
                placeholder="Example: Medan concentration baseline"
                autoFocus
              />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                className="border border-line px-4 py-2 text-sm"
                onClick={() => setConcentrationSaveDialog(false)}
              >
                Cancel
              </button>
              <button
                className="inline-flex items-center gap-2 bg-mint px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
                disabled={
                  !concentrationSaveName.trim() || savedConcentrationLoading
                }
                onClick={() => void saveCurrentConcentrationAnalysis()}
              >
                <Save size={14} />
                {savedConcentrationLoading ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}

      {concentrationLoadDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
          <div className="w-full max-w-xl border border-line bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">
                  Load Concentration Analysis
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  Restores the saved result, analysis parameters, and table
                  filters without running Engine A again.
                </p>
              </div>
              <button onClick={() => setConcentrationLoadDialog(false)}>
                <X size={17} />
              </button>
            </div>
            <label className="mt-4 block text-xs font-semibold uppercase tracking-wide text-slate-500">
              Saved Analysis
              <select
                className="mt-1 w-full border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal"
                value={selectedSavedConcentrationId}
                onChange={(event) =>
                  setSelectedSavedConcentrationId(event.target.value)
                }
              >
                {savedConcentrationAnalyses.map((saved) => (
                  <option value={saved.id} key={saved.id}>
                    {saved.name} | {saved.depot_name} |{" "}
                    {saved.baseline_start_date}–{saved.baseline_end_date}
                  </option>
                ))}
              </select>
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                className="border border-line px-4 py-2 text-sm"
                onClick={() => setConcentrationLoadDialog(false)}
              >
                Cancel
              </button>
              <button
                className="inline-flex items-center gap-2 bg-petroblue px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
                disabled={
                  !selectedSavedConcentrationId || savedConcentrationLoading
                }
                onClick={() => void loadSavedConcentrationAnalysis()}
              >
                <RefreshCw size={14} />
                {savedConcentrationLoading ? "Loading…" : "Load"}
              </button>
            </div>
          </div>
        </div>
      )}

      {clusteringLoadDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
          <div className="w-full max-w-xl border border-line bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">
                  Load Behavioral Clustering Analysis
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  Opens the stored cluster assignments, UMAP, geographic map,
                  profiles, and membership without preparing or retraining data.
                </p>
              </div>
              <button onClick={() => setClusteringLoadDialog(false)}>
                <X size={17} />
              </button>
            </div>
            <label className="mt-4 block text-xs font-semibold uppercase tracking-wide text-slate-500">
              Saved Analysis
              <select
                className="mt-1 w-full border border-line bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal"
                value={selectedClusteringModelId}
                onChange={(event) =>
                  setSelectedClusteringModelId(event.target.value)
                }
              >
                {models.map((model) => (
                  <option value={model.model_id} key={model.model_id}>
                    {model.model_name} v{model.model_version} |{" "}
                    {label(model.model_status)} | {model.training_start_date}–
                    {model.training_end_date}
                  </option>
                ))}
              </select>
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                className="border border-line px-4 py-2 text-sm"
                onClick={() => setClusteringLoadDialog(false)}
              >
                Cancel
              </button>
              <button
                className="inline-flex items-center gap-2 bg-petroblue px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
                disabled={!selectedClusteringModelId || clusteringModelLoading}
                onClick={() => void openClusteringModel()}
              >
                <RefreshCw size={14} />
                {clusteringModelLoading ? "Loading…" : "Load"}
              </button>
            </div>
          </div>
        </div>
      )}

      {saveDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
          <div className="w-full max-w-lg bg-white p-5 shadow-xl">
            <div className="flex justify-between">
              <h2 className="text-lg font-semibold">Save Behavioral Model</h2>
              <button onClick={() => setSaveDialog(false)}>
                <X size={17} />
              </button>
            </div>
            <label className="mt-4 block text-xs font-semibold uppercase tracking-wide text-slate-500">
              Model Name *
              <input
                className="mt-1 w-full border border-line px-3 py-2 text-sm"
                value={modelName}
                onChange={(event) => setModelName(event.target.value)}
                placeholder="Balongan Behavioral Cluster 2025"
              />
            </label>
            <label className="mt-3 block text-xs font-semibold uppercase tracking-wide text-slate-500">
              Description
              <textarea
                className="mt-1 w-full border border-line px-3 py-2 text-sm"
                rows={4}
                value={modelDescription}
                onChange={(event) => setModelDescription(event.target.value)}
              />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                className="border border-line px-4 py-2 text-sm"
                onClick={() => setSaveDialog(false)}
              >
                Cancel
              </button>
              <button
                className="bg-mint px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
                disabled={!modelName.trim() || engineBLoading}
                onClick={saveModel}
              >
                {engineBLoading ? "Saving…" : "Save Model"}
              </button>
            </div>
          </div>
        </div>
      )}

      {openedModel && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/35">
          <div className="h-full w-full max-w-4xl overflow-y-auto bg-white p-5 shadow-xl">
            <div className="flex justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Saved Model Package
                </div>
                <h2 className="mt-1 text-xl font-semibold">
                  {openedModel.model_name} v{openedModel.model_version}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  {openedModel.model_description}
                </p>
              </div>
              <button
                className="border border-line p-2"
                onClick={() => setOpenedModel(null)}
              >
                <X size={17} />
              </button>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                title="Core Training SPBU"
                value={openedModel.core_training_spbu_count}
              />
              <Metric
                title="Marginal"
                value={openedModel.marginal_spbu_count}
              />
              <Metric
                title="Insufficient"
                value={openedModel.insufficient_spbu_count}
              />
              <Metric title="Total SPBU" value={openedModel.total_spbu_count} />
              <Metric title="Clusters" value={openedModel.cluster_count} />
              <Metric
                title="Historical Noise"
                value={openedModel.noise_spbu_count}
              />
              <Metric
                title="Historical Avg Membership"
                value={pct(openedModel.average_membership_probability)}
              />
            </div>
            <div className="mt-4 border border-line p-4">
              <h3 className="font-semibold">Reproducibility Package</h3>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-slate-600">
                {JSON.stringify(
                  {
                    feature_weights: openedModel.feature_weights,
                    node2vec: openedModel.node2vec_parameters,
                    umap: openedModel.umap_parameters,
                    hdbscan: openedModel.hdbscan_parameters,
                    data_sufficiency:
                      openedModel.data_sufficiency_configuration,
                    geography: openedModel.geographic_configuration,
                    projection: {
                      method: openedModel.projection_method,
                      parameters: openedModel.projection_parameters,
                    },
                    libraries: openedModel.library_versions,
                  },
                  null,
                  2,
                )}
              </pre>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">SPBU</th>
                    <th className="px-3 py-2">Cluster</th>
                    <th className="px-3 py-2">Sufficiency</th>
                    <th className="px-3 py-2">Assignment Type</th>
                    <th className="px-3 py-2">Observations</th>
                    <th className="px-3 py-2">Confidence</th>
                    <th className="px-3 py-2">Dominant Shift</th>
                  </tr>
                </thead>
                <tbody>
                  {openedModel.assignments.map((assignment) => (
                    <tr
                      className="border-b border-line"
                      key={assignment.spbu_id}
                    >
                      <td className="px-3 py-2">{assignment.spbu_code}</td>
                      <td className="px-3 py-2">{assignment.cluster_label}</td>
                      <td
                        className={`px-3 py-2 text-xs font-semibold ${hasHistoricalEvidence(assignment) ? "text-mint" : "text-amber"}`}
                      >
                        {evidenceStatus(assignment)}
                      </td>
                      <td className="px-3 py-2">
                        {label(assignment.cluster_assignment_type)}
                      </td>
                      <td className="px-3 py-2">
                        {assignment.shipment_observation_count ?? 0}
                      </td>
                      <td className="px-3 py-2">
                        <div>{pct(assignmentConfidence(assignment))}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          {confidenceLabel(assignment)}
                        </div>
                      </td>
                      <td className="px-3 py-2">{assignment.dominant_shift}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
