import { useEffect, useMemo, useRef, useState } from "react";
import { CircleMarker, MapContainer, Polygon, Polyline, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";
import type { LatLngBoundsExpression, LatLngTuple } from "leaflet";
import "leaflet/dist/leaflet.css";
import { apiGet, apiSend } from "../lib/api";

type Point = [number, number]; // GeoJSON: longitude, latitude
type Road = {
  restricted_road_id: string; depot_id: string; name: string; reason: string;
  geometry: Point[]; buffer_meters: number; active: boolean; revision: number;
  valid_from: string | null; valid_until: string | null;
  direction: "BOTH" | "FORWARD" | "REVERSE"; forward_waypoints: Point[]; reverse_waypoints: Point[];
};
type RoadList = { roads: Road[]; router_configured: boolean; scope: string; missing_detour_ids?: string[] };
type Draft = { name: string; reason: string; buffer: number; active: boolean; from: string; until: string; direction: Road["direction"] };
const emptyDraft = (): Draft => ({ name: "", reason: "", buffer: 12, active: true, from: "", until: "", direction: "BOTH" });
const field = "w-full rounded border border-line bg-white px-3 py-2 text-sm";
const button = "rounded border border-line px-3 py-2 text-sm disabled:opacity-50";
const latlng = (p: Point): LatLngTuple => [p[1], p[0]];
const pointText = (points: Point[]) => points.map((p) => `${p[1]}, ${p[0]}`).join("\n");
function parsePoints(value: string): Point[] {
  return value.trim().split("\n").filter(Boolean).flatMap((line) => {
    const parts = line.split(",");
    if (parts.length !== 2 || parts.some((p) => !p.trim())) return [];
    const [lat, lon] = parts.map(Number);
    return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 85 && Math.abs(lon) <= 180 ? [[lon, lat] as Point] : [];
  });
}


function MapTools({ points, onPoint }: { points: Point[]; onPoint: (p: Point) => void }) {
  const map = useMap();
  useMapEvents({ click: (event) => onPoint([Number(event.latlng.lng.toFixed(7)), Number(event.latlng.lat.toFixed(7))]) });
  useEffect(() => {
    map.invalidateSize();
    if (points.length > 1) map.fitBounds(points.map(latlng) as LatLngBoundsExpression, { padding: [35, 35], maxZoom: 17 });
    else if (points.length) map.setView(latlng(points[0]), 15);
  }, [map, points]);
  return null;
}

function corridors(geometry: Point[], width: number): LatLngTuple[][] {
  return geometry.slice(1).flatMap((b, index) => {
    const a = geometry[index], sx = 111320 * Math.cos((a[1] + b[1]) / 2 * Math.PI / 180), sy = 111320;
    const dx = (b[0] - a[0]) * sx, dy = (b[1] - a[1]) * sy, length = Math.hypot(dx, dy);
    if (length < 0.01) return [];
    const ux = dx / length, uy = dy / length, ax = -ux * width, ay = -uy * width;
    const bx = dx + ux * width, by = dy + uy * width;
    return [[ [ax - uy * width, ay + ux * width], [bx - uy * width, by + ux * width],
      [bx + uy * width, by - ux * width], [ax + uy * width, ay - ux * width] ]
      .map(([x, y]) => [a[1] + y / sy, a[0] + x / sx] as LatLngTuple)];
  });
}

export function RestrictedRoadsPage({ depotId }: { depotId: string }) {
  const [data, setData] = useState<RoadList>({ roads: [], router_configured: false, scope: "" });
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [editing, setEditing] = useState<Road | null>(null);
  const [waypoints, setWaypoints] = useState("");
  const [forwardText, setForwardText] = useState("");
  const [reverseText, setReverseText] = useState("");
  const [mapTarget, setMapTarget] = useState<"ROAD" | "FORWARD" | "REVERSE">("ROAD");
  const forward = useMemo(() => parsePoints(forwardText), [forwardText]);
  const reverse = useMemo(() => parsePoints(reverseText), [reverseText]);
  const [geometry, setGeometry] = useState<Point[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const generation = useRef(0);
  const endpoint = `/api/v1/depots/${encodeURIComponent(depotId)}/restricted-roads`;
  async function load() { setData(await apiGet<RoadList>(endpoint)); }
  useEffect(() => { if (depotId) void load().catch((e: Error) => setError(e.message)); }, [depotId]);
  const points = useMemo(() => parsePoints(waypoints), [waypoints]);
  const shown = useMemo(() => data.roads.filter((r) => `${r.name} ${r.reason}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => Number(b.active) - Number(a.active) || a.name.localeCompare(b.name)), [data.roads, search]);
  const mapPoints = useMemo(() => { const selected = [...(geometry.length ? geometry : points), ...forward, ...reverse]; return selected.length ? selected : data.roads.flatMap((r) => r.geometry); }, [geometry, points, forward, reverse, data.roads]);
  const polygons = useMemo(() => corridors(geometry, draft.buffer), [geometry, draft.buffer]);
  function updatePoints(value: string) { generation.current++; setWaypoints(value); setGeometry([]); setConfirmed(false); setNotice(""); }
  function reset() { generation.current++; setDraft(emptyDraft()); setEditing(null); setWaypoints(""); setForwardText(""); setReverseText(""); setMapTarget("ROAD"); setGeometry([]); setConfirmed(false); setError(""); }
  function edit(road: Road) {
    reset(); setEditing(road); setDraft({ name: road.name, reason: road.reason, buffer: road.buffer_meters, active: road.active, from: road.valid_from || "", until: road.valid_until || "", direction: road.direction || "BOTH" });
    setForwardText(pointText(road.forward_waypoints || [])); setReverseText(pointText(road.reverse_waypoints || []));
    setWaypoints([road.geometry[0], road.geometry[road.geometry.length - 1]].map((p) => `${p[1]}, ${p[0]}`).join("\n"));
    setGeometry(road.geometry);
  }
  async function preview() {
    setError(""); setNotice(""); setConfirmed(false);
    if (points.length < 2 || points.length !== waypoints.trim().split("\n").filter(Boolean).length) {
      setError("Masukkan sedikitnya dua koordinat valid, satu latitude, longitude per baris."); return;
    }
    const token = ++generation.current;
    setBusy(true);
    try {
      const response = await apiSend<{ geometry: Point[] }>(`${endpoint}/preview`, "POST", { coordinates: points });
      if (generation.current === token) setGeometry(response.geometry);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setError(""); setNotice("");
    try {
      for (const [text, parsed] of [[forwardText, forward], [reverseText, reverse]] as const) {
        if (parsed.length !== text.trim().split("\n").filter(Boolean).length || parsed.length > 25) throw new Error("Waypoint harus berupa latitude, longitude yang valid, maksimal 25 titik per arah.");
      }
      if (draft.active && ((draft.direction !== "REVERSE" && !forward.length) || (draft.direction !== "FORWARD" && !reverse.length))) throw new Error("Lengkapi waypoint pengalihan untuk setiap arah yang berlaku.");
      const values = { name: draft.name, reason: draft.reason, buffer_meters: draft.buffer, active: draft.active,
        geometry, geometry_confirmed: confirmed, valid_from: draft.from || null, valid_until: draft.until || null,
        revision: editing?.revision, direction: draft.direction, forward_waypoints: forward, reverse_waypoints: reverse };
      await apiSend(editing ? `${endpoint}/${editing.restricted_road_id}` : endpoint, editing ? "PUT" : "POST", values);
      reset(); await load(); setNotice("Restricted road tersimpan. Jalankan Re-Optimize pada job aktif untuk memakai aturan terbaru.");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function toggle(road: Road) {
    if (!road.active && ((road.direction !== "REVERSE" && !road.forward_waypoints?.length) || (road.direction !== "FORWARD" && !road.reverse_waypoints?.length))) {
      setError("Lengkapi waypoint pengalihan melalui Tinjau / Edit sebelum mengaktifkan aturan."); return;
    }
    if (!window.confirm(`${road.active ? "Nonaktifkan" : "Aktifkan"} restricted road ${road.name}? Versi rencana sebelumnya tetap tersimpan.`)) return;
    setBusy(true); setError("");
    try {
      await apiSend(`${endpoint}/${road.restricted_road_id}`, "PUT", { ...road, active: !road.active, geometry_confirmed: true });
      await load(); if (editing?.restricted_road_id === road.restricted_road_id) reset();
      setNotice("Status diperbarui. Re-Optimize diperlukan untuk memperbarui rencana aktif.");
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  if (!depotId) return <div className="border border-line bg-white p-5">Pilih depot aktif untuk mengelola restricted roads.</div>;
  return <div className="space-y-5">
    <section className="border border-line bg-white p-5">
      <h2 className="text-lg font-semibold">Master Restricted Roads</h2>
      <p className="mt-2 text-sm text-slate-600">Larangan dua arah untuk seluruh MT depot aktif, termasuk perjalanan antar-SPBU. Pilih awal–akhir ruas, tinjau jalur dan area merah, lalu konfirmasi.</p>
      <p className="mt-2 text-sm text-slate-600">Aturan yang berlaku dalam 48 jam sejak waktu optimasi diterapkan secara konservatif sepanjang rencana. Versi lama dan pekerjaan berjalan tetap tersimpan; konflik perlu ditinjau dispatcher.</p>
      {!data.router_configured && <div role="status" className="mt-3 rounded bg-amber-50 p-3 text-sm text-amber-900">Konfigurasikan API key pada Google Maps Integration untuk preview dan optimasi.</div>}
      {Boolean(data.missing_detour_ids?.length) && <div role="alert" className="mt-3 rounded bg-amber-50 p-3 text-sm text-amber-900">{data.missing_detour_ids?.length} aturan aktif belum memiliki waypoint pengalihan lengkap. Tinjau / Edit aturan tersebut sebelum optimasi.</div>}
      {error && <div role="alert" className="mt-3 rounded bg-red-50 p-3 text-sm text-red-800">{error}</div>}
      {notice && <div role="status" className="mt-3 rounded bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</div>}
    </section>
    <section className="grid gap-5 border border-line bg-white p-5 lg:grid-cols-[360px_1fr]">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <h3 className="font-semibold">{editing ? `Edit: ${editing.name}` : "Tambah restricted road"}</h3>
        <label className="block text-sm">Nama ruas<input className={field} required maxLength={255} value={draft.name} disabled={busy} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        <label className="block text-sm">Alasan larangan<textarea className={field} required maxLength={2000} value={draft.reason} disabled={busy} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} /></label>
        <label className="block text-sm">Awal → titik antara (opsional) → akhir<textarea className={field} rows={4} value={waypoints} disabled={busy} placeholder={"-6.200000, 106.800000\n-6.205000, 106.810000"} onChange={(e) => updatePoints(e.target.value)} /></label>
        <p className="text-xs text-slate-500">Satu latitude, longitude per baris. Klik peta untuk menambahkan titik. Dua titik akan dicocokkan ke jalur jalan; tambahkan titik antara jika ruasnya keliru.</p>
        <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={busy} onClick={() => void preview()}>{busy ? "Memproses…" : "Preview ruas jalan"}</button><button type="button" className={button} disabled={busy} onClick={() => updatePoints("")}>Hapus titik</button><button type="button" className={button} disabled={busy || points.length < 2} onClick={() => { generation.current++; setGeometry(points); setConfirmed(false); setNotice("Geometri manual mengikuti garis antartitik. Tambahkan titik antara sampai sesuai bentuk ruas, lalu periksa area merah sebelum konfirmasi."); }}>Gunakan geometri manual</button></div>
        <label className="block text-sm">Lebar larangan dari sumbu jalan (meter)<input className={field} type="number" min={2} max={100} step={1} required value={draft.buffer} disabled={busy} onChange={(e) => { setDraft({ ...draft, buffer: Number(e.target.value) }); setConfirmed(false); }} /></label>
        <p className="text-xs text-slate-500">Periksa area merah agar tidak menutup jalan paralel atau persimpangan yang masih boleh dilewati. Area ini berlaku secara geografis, termasuk pada jalan bertingkat.</p>
        <label className="block text-sm">Arah larangan<select className={field} value={draft.direction} disabled={busy} onChange={(e) => { setDraft({ ...draft, direction: e.target.value as Road["direction"] }); setMapTarget("ROAD"); setConfirmed(false); }}><option value="BOTH">Dua arah</option><option value="FORWARD">Awal ke akhir saja</option><option value="REVERSE">Akhir ke awal saja</option></select></label>
        {draft.direction !== "REVERSE" && <label className="block text-sm">Waypoint pengalihan awal ? akhir<textarea className={field} rows={3} value={forwardText} disabled={busy} placeholder="latitude, longitude (sesuai urutan perjalanan)" onChange={(e) => { setForwardText(e.target.value); setConfirmed(false); }} /></label>}
        {draft.direction !== "FORWARD" && <label className="block text-sm">Waypoint pengalihan akhir ? awal<textarea className={field} rows={3} value={reverseText} disabled={busy} placeholder="latitude, longitude (sesuai urutan perjalanan balik)" onChange={(e) => { setReverseText(e.target.value); setConfirmed(false); }} /></label>}
        {draft.direction === "BOTH" && <button type="button" className={button} disabled={busy || !forward.length} onClick={() => { setReverseText(pointText([...forward].reverse())); setConfirmed(false); }}>Salin urutan terbalik untuk arah balik</button>}
        <p className="text-xs text-slate-500">Minimal satu waypoint per arah yang berlaku; maksimal 25. Titik dilalui tanpa stop tambahan. Periksa arah balik secara terpisah, khususnya jalan satu arah. Rute hasil Google tetap akan diperiksa terhadap semua larangan.</p>
        <label className="block text-sm">Klik peta untuk mengisi<select className={field} value={mapTarget} disabled={busy} onChange={(e) => setMapTarget(e.target.value as typeof mapTarget)}><option value="ROAD">Titik acuan ruas terlarang</option>{draft.direction !== "REVERSE" && <option value="FORWARD">Waypoint awal ? akhir (hijau)</option>}{draft.direction !== "FORWARD" && <option value="REVERSE">Waypoint akhir ? awal (oranye)</option>}</select></label>
        <label className="block text-sm">Mulai berlaku (opsional)<input className={field} value={draft.from} disabled={busy} placeholder="2026-10-28T08:00:00+07:00" onChange={(e) => setDraft({ ...draft, from: e.target.value })} /></label>
        <label className="block text-sm">Akhir berlaku (opsional)<input className={field} value={draft.until} disabled={busy} placeholder="2026-10-29T17:00:00+07:00" onChange={(e) => setDraft({ ...draft, until: e.target.value })} /></label>
        <p className="text-xs text-slate-500">Gunakan tanggal ISO dengan zona waktu, misalnya +07:00. Kosong berarti tanpa batas tanggal.</p>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.active} disabled={busy} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} />Aturan aktif</label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={confirmed} disabled={busy || geometry.length < 2} onChange={(e) => setConfirmed(e.target.checked)} />Saya sudah memeriksa ruas, arah larangan, dan urutan waypoint pengalihan di peta.</label>
        <div className="flex gap-2"><button className={`${button} bg-ocean text-white`} disabled={busy || !confirmed || geometry.length < 2}>Simpan</button><button type="button" className={button} disabled={busy} onClick={reset}>Batal / Baru</button></div>
      </form>
      <div className="min-w-0"><MapContainer center={[-2.5, 118]} zoom={5} style={{ height: 580, width: "100%" }}>
        <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <MapTools points={mapPoints} onPoint={(p) => { if (busy) return; const line = `${p[1]}, ${p[0]}`; if (mapTarget === "ROAD") updatePoints(`${waypoints.trim()}${waypoints.trim() ? "\n" : ""}${line}`); else { const setter = mapTarget === "FORWARD" ? setForwardText : setReverseText; setter((old) => `${old.trim()}${old.trim() ? "\n" : ""}${line}`); setConfirmed(false); } }} />
        {data.roads.filter((r) => r.restricted_road_id !== editing?.restricted_road_id).map((r) => <Polyline key={r.restricted_road_id} positions={r.geometry.map(latlng)} pathOptions={{ color: r.active ? "#b91c1c" : "#94a3b8", weight: 4, opacity: 0.7 }}><Popup>{r.name} · {r.active ? "Aktif" : "Nonaktif"}<br />{r.reason}</Popup></Polyline>)}
        {geometry.length > 1 && <Polyline positions={geometry.map(latlng)} pathOptions={{ color: "#dc2626", weight: 4 }} />}
        {forward.length > 1 && <Polyline positions={forward.map(latlng)} pathOptions={{ color: "#059669", dashArray: "4 4", weight: 2 }} />}
        {reverse.length > 1 && <Polyline positions={reverse.map(latlng)} pathOptions={{ color: "#ea580c", dashArray: "4 4", weight: 2 }} />}
        {forward.map((p, i) => <CircleMarker key={`f-${i}`} center={latlng(p)} radius={7} pathOptions={{ color: "#059669" }}><Popup>Pengalihan awal ? akhir ? {i + 1}<br />{p[1]}, {p[0]}</Popup></CircleMarker>)}
        {reverse.map((p, i) => <CircleMarker key={`r-${i}`} center={latlng(p)} radius={7} pathOptions={{ color: "#ea580c" }}><Popup>Pengalihan akhir ? awal ? {i + 1}<br />{p[1]}, {p[0]}</Popup></CircleMarker>)}
        {polygons.map((ring, i) => <Polygon key={i} positions={ring} pathOptions={{ color: "#dc2626", weight: 0, fillOpacity: 0.25 }} />)}
        {points.map((p, i) => <CircleMarker key={`${i}-${p.join()}`} center={latlng(p)} radius={6} pathOptions={{ color: "#0369a1" }}><Popup>Titik {i + 1}: {p[1]}, {p[0]}</Popup></CircleMarker>)}
      </MapContainer><p className="mt-2 text-xs text-slate-500">Garis merah: ruas terpilih. Area merah: batas yang dilarang mesin routing. Titik biru: acuan ruas. Hijau/oranye: waypoint pengalihan sesuai arah. Garis antartitik pengalihan hanya panduan urutan, bukan hasil routing Google.</p></div>
    </section>
    <section className="border border-line bg-white p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Daftar ruas · {shown.length}</h3><input aria-label="Cari restricted roads" className={`${field} max-w-sm`} placeholder="Cari nama / alasan" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} /></div>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="p-2">Nama / alasan</th><th className="p-2">Status</th><th className="p-2">Masa berlaku</th><th className="p-2">Revisi</th><th className="p-2">Aksi</th></tr></thead><tbody>
        {shown.slice((page - 1) * 10, page * 10).map((road) => <tr key={road.restricted_road_id} className="border-b"><td className="p-2"><strong>{road.name}</strong><div className="text-xs text-slate-500">{road.reason}</div></td><td className="p-2">{road.active ? "Aktif" : "Nonaktif"}<div className="text-xs text-slate-500">{road.direction === "FORWARD" ? "Awal ? akhir" : road.direction === "REVERSE" ? "Akhir ? awal" : "Dua arah"}</div>{data.missing_detour_ids?.includes(road.restricted_road_id) && <div className="text-xs text-amber-700">Lengkapi pengalihan</div>}</td><td className="p-2 text-xs">{road.valid_from || "Tanpa batas awal"}<br />{road.valid_until || "Permanen"}</td><td className="p-2">{road.revision}</td><td className="p-2"><div className="flex gap-2"><button className={button} disabled={busy} onClick={() => edit(road)}>Tinjau / Edit</button><button className={button} disabled={busy} onClick={() => void toggle(road)}>{road.active ? "Nonaktifkan" : "Aktifkan"}</button></div></td></tr>)}
        {!shown.length && <tr><td colSpan={5} className="p-6 text-center text-slate-500">Belum ada ruas yang sesuai.</td></tr>}
      </tbody></table></div>
      <div className="mt-3 flex items-center justify-end gap-3 text-sm"><button className={button} disabled={page <= 1} onClick={() => setPage(page - 1)}>Sebelumnya</button><span>{page} / {Math.max(1, Math.ceil(shown.length / 10))}</span><button className={button} disabled={page * 10 >= shown.length} onClick={() => setPage(page + 1)}>Berikutnya</button></div>
    </section>
  </div>;
}
