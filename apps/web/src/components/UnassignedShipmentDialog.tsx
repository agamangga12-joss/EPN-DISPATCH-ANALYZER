import { useEffect, useRef, useState } from "react";
import { RefreshCw, XCircle } from "lucide-react";
import { apiGet } from "../lib/api";

type Candidate = {
  id: string;
  vehicle_registration_no: string;
  compatibility_status: string;
  exclusion_reason: string | null;
  explanation: Record<string, unknown>;
};
type Shipment = {
  id: string;
  predicted_shipment_id: string;
  total_order_kl: number;
  required_compartments: number;
  candidates: Candidate[];
  candidates_loaded: boolean;
  assignment: { unassigned_reason: string | null };
};
const rules: Record<string, string> = {
  PROJECT_TAGS: "Tag wajib SPBU belum seluruhnya dimiliki MT",
  VEHICLE_TYPE: "Kelas kendaraan MT tidak sesuai dengan batas kelas SPBU",
  DEPOT: "Depot MT berbeda dengan depot SPBU",
  MT_OR_SPBU_NOT_FOUND: "MT atau SPBU tidak ditemukan pada master",
  SHIPMENT_MT_CAPACITY_MISMATCH: "Volume/kompartemen shipment tidak sesuai dengan kapasitas MT",
  MT_COMPARTMENT_COUNT_INVALID: "Jumlah kompartemen MT tidak valid",
  MT_COMPARTMENT_COUNT_MISSING: "Jumlah kompartemen MT belum tersedia",
  MT_CAPACITY_NOT_8_KL_MULTIPLE: "Kapasitas MT bukan kelipatan 8 KL",
  MT_COMPARTMENT_CAPACITY_MISMATCH: "Kapasitas MT tidak sesuai dengan jumlah kompartemennya",
  SHIPMENT_VOLUME_NOT_8_KL_MULTIPLE: "Volume shipment bukan kelipatan 8 KL",
};
const labels = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];
const display = (value: unknown) => value == null ? "—" : String(value);
const records = (value: unknown): Record<string, unknown>[] => Array.isArray(value)
  ? value.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object" && !Array.isArray(row)) : [];
const ruleText = (code: string) => rules[code] ?? code.replace(/_/g, " ");

function reasonText(reason: string | null) {
  switch (reason) {
    case "NO_COMPATIBLE_MT": return "Tidak ada kandidat MT yang lolos seluruh aturan master dan kapasitas shipment. Periksa aturan yang gagal pada masing-masing MT di bawah; penyebabnya dapat berupa tag, kelas kendaraan, depot, atau kapasitas.";
    case "NO_MT_AVAILABLE_AT_REQUIRED_TIME": return "Ada MT yang kompatibel, tetapi tidak ada yang tersedia pada waktu shipment sesuai mode assignment dan batas keterlambatan run. MT dapat masih menjalankan trip lain atau belum kembali ke depot. Kompatibilitas tag yang lolos tidak menjamin MT tersedia pada waktu tersebut.";
    case "LOW_PREDICTION_CONFIDENCE": return "Confidence shipment berada di bawah batas pemblokiran yang digunakan saat run. Periksa confidence shipment dan pengaturan run sebelum menjalankan ulang.";
    default: return reason ? `Run mencatat alasan: ${reason.replace(/_/g, " ")}. Periksa rincian kandidat dan penjelasan run sebelum menjalankan ulang.` : "Run belum menyimpan alasan unassigned. Rincian kandidat di bawah menunjukkan hasil pemeriksaan yang tersedia.";
  }
}

export default function UnassignedShipmentDialog({ runId, shipment, onClose }: {
  runId: string; shipment: Shipment; onClose: () => void;
}) {
  const [candidates, setCandidates] = useState<Candidate[]>(shipment.candidates);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    let active = true;
    {
      setLoading(true);
      setError(null);
      apiGet<{ candidates: Candidate[] }>(`/api/v1/phase6/predictions/${runId}/shipments/${shipment.id}/candidates`)
        .then((payload) => { if (active) setCandidates(payload.candidates); })
        .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Rincian MT gagal dimuat."); })
        .finally(() => { if (active) setLoading(false); });
    }
    return () => { active = false; };
  }, [runId, shipment.id, shipment.candidates_loaded, retry]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        const elements = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button, summary, [tabindex="0"]') ?? []).filter((element) => element.getClientRects().length > 0);
        const first = elements[0];
        const last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  const failedCounts: Record<string, number> = {};
  candidates.forEach((candidate) => new Set(labels(candidate.explanation.failed_rules)).forEach((code) => {
    failedCounts[code] = (failedCounts[code] ?? 0) + 1;
  }));
  const compatibleCount = candidates.filter((row) => row.compatibility_status === "PASS").length;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-petroink/50 p-4" onClick={onClose}>
      <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="unassigned-title" className="flex max-h-[90vh] w-full max-w-4xl flex-col border border-line bg-white shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b border-line p-5">
          <div><h2 id="unassigned-title" className="font-semibold text-petroink">Mengapa shipment Unassigned?</h2><p className="mt-1 font-mono text-xs text-slate-500">{shipment.predicted_shipment_id}</p></div>
          <button type="button" autoFocus aria-label="Tutup penjelasan unassigned" className="rounded p-1 focus:ring-2 focus:ring-petroblue" onClick={onClose}><XCircle size={20} /></button>
        </div>
        <div className="space-y-4 overflow-y-auto p-5 text-sm">
          <div className="border border-rust/30 bg-rust/5 p-4"><p className="font-semibold text-rust">{shipment.assignment.unassigned_reason?.replace(/_/g, " ") ?? "UNASSIGNED"}</p><p className="mt-2">{reasonText(shipment.assignment.unassigned_reason)}</p></div>
          <p>Kebutuhan shipment: <strong>{shipment.total_order_kl} KL · {shipment.required_compartments} kompartemen</strong>.</p>
          {loading && <p role="status" className="flex items-center gap-2"><RefreshCw size={16} className="animate-spin" /> Memuat hasil evaluasi kandidat MT…</p>}
          {error && <div role="alert" className="text-rust">{error}<button type="button" className="ml-3 underline" onClick={() => setRetry((value) => value + 1)}>Coba lagi</button></div>}
          {!loading && !error && <>
            <p>{candidates.length} kandidat MT pada run · {compatibleCount} lolos kompatibilitas · {candidates.length - compatibleCount} gagal.</p>
            {Object.keys(failedCounts).length > 0 && <ul className="list-disc space-y-1 pl-5">{Object.entries(failedCounts).map(([code, count]) => <li key={code}>{ruleText(code)}: <strong>{count} MT</strong>.</li>)}</ul>}
            {candidates.length === 0 && <p className="border border-line p-3">Tidak ada kandidat MT tersimpan untuk shipment ini. Periksa input MT Availability, aktivasi MT, dan master MT pada depot yang digunakan saat run. Tidak ada bukti untuk menyimpulkan bahwa tag adalah penyebabnya.</p>}
            {candidates.map((candidate) => {
              const explanation = candidate.explanation;
              const snapshot = Array.isArray(explanation.master_checks);
              const checks = records(snapshot ? explanation.master_checks : explanation.current_master_checks);
              const failed = labels(explanation.failed_rules);
              return <details key={candidate.id} className="border border-line">
                <summary className="cursor-pointer bg-slate-50 p-3 font-medium">{candidate.vehicle_registration_no} · {candidate.compatibility_status === "PASS" ? "Kompatibel" : "Tidak kompatibel"}{failed.length > 0 ? ` — ${failed.map(ruleText).join("; ")}` : candidate.exclusion_reason ? ` — ${candidate.exclusion_reason.replace(/_/g, " ")}` : ""}</summary>
                <div className="space-y-3 p-4">
                  <p>Hasil tersimpan: master <strong>{display(explanation.master_compatibility)}</strong> · kapasitas <strong>{display(explanation.capacity_compatibility)}</strong>.</p>
                  <p>Kapasitas MT saat run: <strong>{display(explanation.mt_capacity_kl)} KL · {display(explanation.mt_number_of_compartments)} kompartemen</strong>. Kebijakan: {explanation.capacity_policy === "EXACT_COMPARTMENT_MATCH" ? "muatan harus tepat memenuhi kapasitas MT" : explanation.capacity_policy === "ALLOW_PARTIAL_LOAD" ? "muatan parsial diperbolehkan, tidak boleh melebihi kapasitas MT" : display(explanation.capacity_policy)}.</p>
                  {checks.length > 0 && <>
                    <p className={snapshot ? "text-slate-500" : "text-amber-700"}>{snapshot ? "Rincian master berikut disimpan saat run." : "Run lama belum menyimpan rincian tag per SPBU. Rincian berikut diperiksa menggunakan master saat ini, yang bisa berbeda dari saat run; hasil tersimpan di atas tetap menjadi acuan."}</p>
                    <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b border-line"><th className="p-2">SPBU</th><th className="p-2">Kelas MT / SPBU</th><th className="p-2">Tag wajib SPBU</th><th className="p-2">Tag MT</th><th className="p-2">Tag kurang / aturan gagal</th></tr></thead><tbody>{checks.map((check, index) => <tr key={`${check.spbu_id}-${index}`} className="border-b border-line align-top"><td className="p-2">{display(check.spbu_code ?? check.spbu_id)}</td><td className="p-2">{display(check.mt_vehicle_class)} / {display(check.spbu_vehicle_class)}<div className="mt-1 text-slate-500">{check.vehicle_mode === "EXACT_MATCH" ? "Harus sama" : "MT ≤ batas SPBU"}</div></td><td className="p-2">{labels(check.required_tags).join(", ") || "—"}</td><td className="p-2">{labels(check.available_tags).join(", ") || "—"}</td><td className="p-2 text-rust">{labels(check.missing_tags).length > 0 && <div>Tag kurang: {labels(check.missing_tags).join(", ")}</div>}{labels(check.failed_rules).map(ruleText).join("; ") || <span className="text-emerald-700">Lolos</span>}</td></tr>)}</tbody></table></div>
                  </>}
                  {candidate.compatibility_status === "PASS" && <p className="text-slate-500">MT ini lolos aturan master dan kapasitas. Assignment tetap bergantung pada ketersediaan dinamis setelah trip lain, waktu shipment, dan kebijakan run.</p>}
                </div>
              </details>;
            })}
          </>}
        </div>
      </section>
    </div>
  );
}
