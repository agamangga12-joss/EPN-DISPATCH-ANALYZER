# Source Data Mapping

## Depot aktif

Buat Master Depot, lalu pilih depot di top bar sebelah kiri Google Maps Settings.
Semua upload MT, SPBU, dan Historikal Shipment memakai depot tersebut. File tidak
memerlukan depot ID atau nama depot. Backend menyimpan depot pada import audit
ketika job dibuat; kolom depot dari file lama tidak dapat mengganti konteks ini.
API upload menerima depot_id sebagai parameter request (bukan kolom file).

## Mobil Tangki

Sheet: Mobil Tangki. Gunakan template terbaru dari aplikasi.

| Kolom | Makna |
| --- | --- |
| vehicle_registration | Nomor registrasi kendaraan, dinormalisasi |
| vehicle_type_tag | Vehicle Class sekaligus kapasitas KL (integer) |
| project_tag | Daftar tag proyek |
| number_of_compartments | Jumlah kompartemen |
| active_status | ACTIVE / INACTIVE |

Vehicle name raw dan capacity label tidak perlu diisi. Nilai kapasitas analisis
dan connector mengikuti vehicle_type_tag; capacity label lama hanya fallback.

## SPBU

Sheet: SPBU. SPBU code disimpan sebagai teks, termasuk angka nol di depan.

| Kolom | Makna |
| --- | --- |
| spbu_code | Identitas SPBU; menggantikan nama duplikat |
| address | Alamat tunggal; menggantikan city |
| latitude, longitude | Koordinat numerik terpisah |
| master_distance_km | Jarak referensi |
| vehicle_type_tag, project_tag | Persyaratan kendaraan dan tag |
| official_window_start, official_window_end | Jendela layanan |
| active_status | ACTIVE / INACTIVE |

Master travel time tidak dapat diisi manual. Sistem menggunakan:

- RTH = shipment_end_datetime - gate_out_datetime, dalam menit.
- master_rth_min = median RTH shipment yang hanya memiliki satu SPBU terpetakan.
- master_travel_time_min = master_rth_min / 2 (estimasi satu arah).
- master_travel_time_sample_count = jumlah shipment, bukan jumlah baris produk.

Durasi nol/negatif, waktu kosong, shipment multi-SPBU, baris SPBU tak terpetakan,
serta baris yang dihapus tidak menjadi sampel. Depot shipment harus sesuai depot
SPBU. Tanpa sampel, nilai waktu NULL dan jumlah sampel 0. RTH masih memuat layanan
dan waktu tunggu; estimasi ini bukan durasi mengemudi murni. Kolom hasil tersedia
di tabel dan export, tetapi tidak perlu dimasukkan saat upload.

## Historikal Shipment

Sheet: Historikal Shipment. Kode domain API LOADING_ORDER dipertahankan untuk
kompatibilitas. Ini adalah data histori; input LO operasional Phase 6 tetap terpisah.

| Kolom | Makna |
| --- | --- |
| shipment_id | Kunci shipment; semua baris satu shipment menggunakan ID sama |
| loading_order_number | Nomor LO unik dalam depot |
| vehicle_registration | Nomor kendaraan, dipetakan dalam depot aktif |
| vehicle_type_tag, project_tag | Kelas/tag yang teramati pada shipment |
| validation_datetime | Tanggal dan waktu validasi; wajib |
| gate_out_datetime | Tanggal dan waktu keluar depot |
| shipment_end_datetime | Tanggal dan waktu shipment selesai |
| source_spbu_code | SPBU tujuan, dipetakan dalam depot aktif |
| source_product_name | Nama produk lengkap; koma di dalam nama tidak memecah produk |
| quantity | Kuantitas |
| driver_name, driver_nip | Identitas pengemudi |
| assistant_name, assistant_nip | Identitas kernet |
| actual_km | Jarak aktual tunggal |

Timestamp menggunakan YYYY-MM-DD HH:MM:SS pada zona waktu depot, atau ISO 8601
dengan offset eksplisit. Tanggal operasional diturunkan dari validation_datetime.
Status, source_distance_km, area_id, area, operating_date, shipto, serta tanggal
atau jam terpisah tidak ada pada template/form baru. Shipment ID yang sudah
terpakai pada depot berbeda ditolak agar data tidak berpindah depot.

## Pembaruan dan kompatibilitas

Import, edit, dan delete memperbarui relasi shipment-SPBU serta menghitung ulang
waktu master. Analisis langsung membaca master canonical. Model, prediction,
dan route tersimpan merupakan snapshot; jalankan ulang analisis atau buat run
baru untuk memakai perubahan historikal.

Kolom database lama dipertahankan sebagai mirror/fallback untuk integrasi dan
histori. Nama MT mengikuti registration, capacity label mengikuti kelas numerik,
nama SPBU mengikuti kode, city mengikuti address, dan source distance mengikuti
actual km. Alias header file lama tetap dapat dibaca, tetapi template terbaru
adalah kontrak input yang dianjurkan. Migration 0031 menyatukan nilai master lama
dan menghitung RTH dari histori; lakukan backup sebelum migrasi.

## GPS

Mapping GPS tetap terpisah dari perubahan ini. Skema sumber aktual perlu ditinjau
sebelum event GPS digunakan sebagai bukti urutan kunjungan.
