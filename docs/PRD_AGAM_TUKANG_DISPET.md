# PRD — Agam tukang dispet

Versi: 1.1 — revisi kebutuhan pengguna  
Tanggal: 4 Oktober 2026  
Status: draft untuk pengembangan  
Platform: web app desktop-first, responsif untuk tablet

## 1. Ringkasan produk

Agam tukang dispet adalah aplikasi untuk membantu dispatcher dan analis memahami distribusi BBM berdasarkan master data dan riwayat pengiriman. Aplikasi menggabungkan pengelolaan data, pemeriksaan kesesuaian MT–SPBU, analisis waktu keberangkatan, hubungan antar-SPBU, kebiasaan penggunaan mobil tangki, dan machine learning.

Pertanyaan utama yang dijawab:

1. Apakah data operasional sudah lengkap dan dapat dipercaya?
2. Apakah mobil tangki yang digunakan memenuhi persyaratan SPBU?
3. Kapan kendaraan biasanya berangkat untuk melayani suatu SPBU?
4. SPBU mana yang sering dilayani dalam shipment yang sama?
5. Mobil tangki mana yang paling sering melayani suatu SPBU, dan apakah polanya berubah?
6. SPBU mana yang memiliki pola serupa atau pola penggunaan armada yang tidak biasa?

Produk ini merupakan alat analisis historis. Versi pertama tidak membuat assignment masa depan, jadwal dispatch, ETA, optimasi rute, antrean bay, atau finalisasi dispatch. Clustering bukan keputusan pengiriman.

## 2. Tujuan dan keberhasilan produk

Tujuan:

- Mengurangi analisis manual berulang di spreadsheet.
- Menyatukan master data dan histori dalam satu aplikasi.
- Menampilkan temuan yang dapat ditelusuri sampai shipment dan file sumber.
- Membantu pengguna membedakan pola operasional, masalah data, dan ketidakcukupan bukti.
- Menghasilkan model perilaku SPBU yang dapat disimpan dan dibandingkan.

Kriteria keberhasilan rilis:

- Pengguna dapat menyelesaikan alur import → perbaikan data → analisis → simpan/buka hasil tanpa bantuan developer.
- Seluruh angka analitik memiliki definisi, periode, depot, dan jumlah observasi yang jelas.
- Seluruh temuan dapat dibuka sampai evidence pendukung.
- Filter depot memisahkan data pada UI, API, export, dan model.
- Membuka hasil tersimpan tidak menghitung ulang atau mengubah hasilnya.
- Dataset uji dengan hasil yang diketahui menghasilkan angka yang sesuai pada setiap modul.

Setelah pilot, ukur waktu analisis sebelum/sesudah aplikasi, tingkat keberhasilan import, jumlah isu belum selesai, dan frekuensi penggunaan tiap modul. Target numerik ditetapkan dari baseline pilot, bukan diasumsikan sebagai manfaat yang sudah terbukti.

## 3. Pengguna dan hak akses

| Peran | Kebutuhan | Hak akses |
|---|---|---|
| Admin | Mengelola pengguna, depot, dan aturan | Kelola akses, master, import, aturan, serta seluruh analisis pada depot yang diizinkan |
| Dispatcher | Memeriksa data dan membaca pola distribusi | Import dan edit data pada depot yang diizinkan; menjalankan serta menyimpan analisis |
| Analis | Mendalami pola dan membuat model | Analisis, export, training, save, dan perbandingan model |
| Supervisor | Meninjau hasil | Baca dashboard, evidence, hasil analisis, model, dan export sesuai izin |

Login dan pembatasan akses backend wajib tersedia sebelum aplikasi digunakan bersama. Aktivasi model dibatasi untuk Admin atau Analis yang diberi izin. UI menyembunyikan tindakan yang tidak diizinkan, dan API tetap memverifikasi izin tersebut.

## 4. Ruang lingkup dan navigasi

| Menu | Fungsi |
|---|---|
| Dashboard | Ringkasan hasil Tag Consistency, Departure Time, Pairing, Affinity & Stability, serta Machine Learning |
| Master Data | Depot beserta bay, MT, SPBU, dan Historikal Shipment |
| Import & Kualitas Data | Upload, histori import, mapping, dan daftar isu |
| Tag Consistency | Kesesuaian penugasan historis dengan aturan master |
| Departure Time | Pola waktu keberangkatan dan shift historis |
| SPBU Pairing | Hubungan SPBU dalam shipment yang sama |
| SPBU–MT Affinity | Distribusi penggunaan MT dan perubahan pola |
| Machine Learning | Concentration anomaly dan behavioral clustering |
| Panduan | Definisi, rumus, contoh, serta cara membaca hasil |

Poin pertama dari referensi, yaitu alur aplikasi, menjadi rancangan perjalanan pengguna, bukan menu tambahan. Menu pendukung login, import, dan panduan memastikan tujuh kelompok fitur utama dapat digunakan secara utuh.

Di luar cakupan: prediction/assignment operasional, VRP, bay scheduling, manual dispatch, route–model alignment, AMT scheduler, live GPS tracking, dan AI chatbot.

## 5. Alur pengguna utama

### Penggunaan awal

1. Admin login dan membuat depot, jam operasi, serta bay satu per satu; zona waktu mengikuti pengaturan aplikasi.
2. Pengguna memilih depot lalu menambah MT/SPBU manual atau mengimpor Excel; tag diisi pada entitas terkait.
3. Pengguna mengunggah file dan meninjau preview serta hasil validasi.
4. Data yang lolos ditulis setelah pengguna menekan Publish; file bermasalah diperbaiki atau baris tidak valid dikeluarkan secara eksplisit.
5. Pengguna memilih depot lalu menambah Historikal Shipment manual atau mengimpor Excel.
6. Pengguna memperbaiki isu referensi dan memeriksa Tag Consistency.
7. Pengguna menjalankan analisis historis sesuai depot dan periode.
8. Analis menjalankan ML setelah readiness terpenuhi, meninjau hasil, dan menyimpan model.

### Penggunaan rutin

Login → pilih depot → lihat dashboard → import histori terbaru bila perlu → tinjau isu → buka analisis → pilih periode/filter → Apply → baca grafik dan evidence → simpan atau export.

Perubahan filter tidak mengubah hasil sebelum Apply. Hasil lama tetap terlihat dengan label “Filter berubah, tekan Apply” agar scope tidak membingungkan.

## 6. Data dan aturan umum

### Struktur master data yang disepakati

Menu Master Data hanya mempunyai empat bagian: Depot, MT, SPBU, dan Historikal Shipment. Produk dan tag adalah field pada data terkait, bukan menu master tersendiri.

| Bagian | Field yang ditampilkan | Cara mengisi/menghapus |
|---|---|---|
| Depot | Kode Depot, Nama Depot, Jam Buka, Jam Tutup | Tambah dan hapus manual |
| Bay dalam Depot | Nomor Bay, Flow Rate, Produk | Tambah satu per satu pada depot; edit/hapus bay |
| MT | No. Polisi, Kapasitas, Kompartemen, Tag | Pilih depot terlebih dahulu; tambah manual atau import Excel; hapus satuan/bulk |
| SPBU | No. SPBU, Jam Buka, Jam Tutup, Kapasitas Maksimal MT, Tag | Pilih depot terlebih dahulu; tambah manual atau import Excel; hapus satuan/bulk |
| Historikal Shipment | Start Validasi, Gate Out, Waktu Kembali, SPBU, LO, Produk, Jarak KM, Mobil Tangki (MT), Kapasitas MT, Volume Order, Tag | Pilih depot terlebih dahulu; tambah manual atau import Excel; hapus satuan/bulk |

Kapasitas dan Volume Order menggunakan KL, jarak menggunakan KM. Start Validasi, Gate Out, dan Waktu Kembali adalah tanggal beserta jam. Jam buka/tutup mendukung operasi melewati tengah malam. Flow rate mempunyai satuan yang ditampilkan dan disepakati sebelum template dikunci. Bentuk Kompartemen (jumlah dan/atau kapasitas per ruang) juga perlu ditetapkan dari data nyata.

ID internal, depot pemilik, status penghapusan, waktu perubahan, serta sumber import ditambahkan otomatis; pengguna tidak perlu mengisinya sebagai kolom bisnis.

Satu shipment dapat memiliki beberapa baris SPBU/LO/produk. Karena field pengguna belum mencantumkan nomor shipment, cara mengelompokkan baris menjadi shipment harus divalidasi dari contoh Excel sebelum analitik diterapkan. Opsi: nomor shipment dari sumber jika tersedia atau aturan pengelompokan depot + MT + waktu operasi yang telah terbukti; sistem tidak boleh menganggap setiap LO sebagai shipment tersendiri.

Koordinat SPBU tidak termasuk field wajib yang diminta. Analisis utama tetap berjalan tanpa koordinat. Fitur geografis ML bersifat opsional dan hanya aktif setelah koordinat tersedia melalui perluasan data yang disepakati; jika tidak ada, bobot geografis nol dan bobot lain dinormalisasi eksplisit. GPS tidak menjadi kebutuhan versi pertama.

### Aturan data

- Identitas bisnis MT, SPBU, dan LO dibatasi per depot; kode dipertahankan sebagai teks agar nol di depan tidak hilang.
- Depot harus dibuat terlebih dahulu; import tidak membuat depot otomatis.
- Histori tidak boleh diam-diam mengubah master.
- Data asli, hasil normalisasi, file sumber, nomor baris, dan import ID dipertahankan.
- Upload ulang data identik tidak menambah observasi. Perubahan pada key yang sama ditampilkan sebagai update untuk ditinjau.
- Kuantitas harus positif; timestamp menggunakan zona waktu depot dan disimpan dengan representasi waktu yang konsisten.
- Koordinat kosong atau invalid ditandai; tidak diganti menjadi lokasi palsu.
- Departure menggunakan Gate Out dari Historikal Shipment; tanpa timestamp valid, observasi dikecualikan dan alasannya ditampilkan.
- Data yang dikecualikan dari analisis tetap dapat dilihat beserta alasannya.

## 7. Kebutuhan fitur

### F01 — Dashboard

Tujuan: menjadi ringkasan hasil seluruh analisis pada depot terpilih.

Kebutuhan:

- Filter depot dan periode untuk mencari hasil analisis yang tersimpan dengan scope sesuai.
- Tag Consistency: jumlah/persentase MATCH, MISMATCH, DATA_ISSUE, dan isu utama.
- Departure Time: pola keberangkatan dominan, distribusi shift, coverage timestamp, dan confidence.
- SPBU Pairing: pasangan teratas, pair count, conditional probability, dan evidence confidence.
- SPBU–MT Affinity & Stability: pola konsentrasi armada, consistency, variability, stability, serta perubahan pola.
- Machine Learning: ringkasan anomaly Engine A, cluster Engine B, noise, data insufficient, dan model yang digunakan.
- Setiap bagian menampilkan periode sumber, waktu analisis, versi/ID hasil atau model, dan tombol membuka halaman detail.
- Dashboard tidak menjalankan training atau menghitung ulang analisis secara otomatis. Jika hasil dengan scope yang diminta belum ada, tampilkan “Belum ada analisis untuk periode ini” serta tindakan menjalankan analisis.
- Model ML boleh mempunyai periode training berbeda; periode tersebut wajib terlihat dan tidak diklaim sama dengan filter dashboard.
- Import/edit/hapus sumber menandai hasil sebagai “Data sumber berubah”; snapshot tetap tersedia sampai analisis baru dijalankan.
- Jumlah MT/SPBU dan isu data menjadi konteks pendukung, bukan fokus utama dashboard.
- Tidak ada satu skor gabungan lintas modul karena masing-masing menjelaskan hal berbeda.

Penerimaan: setiap kartu dapat ditelusuri ke hasil analisis tersimpan; angka sama dengan halaman detail; periode berbeda, hasil belum ada, dan hasil terdampak perubahan data terlihat jelas.

### F02 — Master Data, Import, dan Kualitas Data

Tujuan: menyediakan data yang konsisten dan mudah diperbaiki.

Kebutuhan:

- Empat bagian master: Depot, MT, SPBU, Historikal Shipment; bay dikelola di dalam Depot.
- Depot ditambah/hapus manual. MT, SPBU, Historikal Shipment ditambah manual atau import Excel setelah depot dipilih.
- Form dan template mengikuti persis field bisnis pada bagian 6. Produk/tag dikelola melalui field terkait.
- MT, SPBU, dan Historikal Shipment mendukung hapus satuan serta bulk melalui checkbox; tampilkan jumlah, depot, dan dampak sebelum konfirmasi. Pilihan semua pada halaman harus dibedakan dari seluruh hasil filter.
- Hapus depot dengan data terkait diblokir dan menampilkan dependensi; hapus bay tidak menghapus histori.
- Hapus histori mengeluarkan baris dari analisis baru tetapi tidak mengubah snapshot hasil lama.
- Tabel dengan search, filter, sort, pagination, serta kolom tag dinamis.
- Soft delete/nonaktif tanpa menghilangkan histori; catat actor dan waktu perubahan.
- Import Excel XLSX, pilihan sheet, preview mapping kolom, dan template MT/SPBU/Historikal Shipment. Depot dipilih sebelum upload; baris tidak boleh masuk ke depot lain.
- Tahap import: Upload → Preview/Mapping → Validasi → Review → Publish.
- Baris error memblokir publikasi baris tersebut. Publikasi sebagian hanya dilakukan dengan pilihan eksplisit dan laporan baris yang dikeluarkan.
- Warning ditampilkan dan perlu diakui sebelum Publish.
- Status job: QUEUED, PROCESSING, READY_FOR_REVIEW, PUBLISHED, FAILED, atau CANCELLED.
- Refresh browser tetap dapat membuka status job yang sama.
- Daftar isu menampilkan severity, entitas, alasan, sumber, dan tindakan perbaikan; status resolved hanya ketika kondisi pemicu sudah diperbaiki/divalidasi ulang.
- Export master per depot serta laporan import dan isu.

Penerimaan: depot tidak dikenal ditolak; upload ulang identik tidak menggandakan data; baris invalid tidak menjadi data aktif; perubahan master dapat diaudit.

### F03 — Tag Consistency

Tujuan: memeriksa penugasan MT–SPBU historis terhadap aturan master yang berlaku pada analisis.

Kebutuhan:

- Filter depot, tanggal, SPBU, MT, produk, jenis tag, dan status.
- Ringkasan MATCH, MISMATCH, dan DATA_ISSUE beserta jumlah serta persentase.
- Aturan kelas: kapasitas/kelas MT ≤ batas maksimum kelas MT pada SPBU.
- Tag wajib SPBU harus dipenuhi oleh MT pada jenis tag yang sama.
- Aturan produk hanya dievaluasi jika sumber aturan eksplisit tersedia; jika belum, tampilkan NOT_AVAILABLE.
- Detail menampilkan LO, shipment, MT/SPBU, tag pembanding, failed rule, dan sumber data.
- Simpan versi aturan serta snapshot master yang dipakai agar hasil dapat direproduksi.
- Aplikasi tidak mengubah tag secara otomatis atau menganggap mismatch sebagai kesalahan dispatcher.

Penerimaan: MT 16 KL lolos batas SPBU 24 KL; MT 32 KL gagal; entitas/tag tidak ditemukan menjadi DATA_ISSUE, bukan MATCH. Snapshot hasil lama tetap sama setelah master berubah.

### F04 — Departure Time Intelligence

Tujuan: memahami jam keberangkatan historis untuk melayani masing-masing SPBU.

Kebutuhan:

- Filter depot, rentang tanggal, bucket 30/60 menit, SPBU, dan confidence; eksekusi lewat Apply.
- Unit observasi unik shipment + SPBU, bukan setiap baris LO.
- Timestamp analitik memakai Gate Out dari Historikal Shipment; jika tidak tersedia/invalid, observasi dikecualikan.
- Tampilkan source coverage, lineage timestamp, distribusi 24 jam, weekday heatmap, box plot, profile table, dan evidence.
- Profil: jumlah observasi, median, P20/P80, P25/P75, P90/P95, peak bucket, outlier, dan confidence.
- Gunakan perhitungan circular time untuk pola melewati tengah malam.
- Shift dapat ditambah/dihapus; nama unik, tanpa overlap, dan mencakup 24 jam.
- Metode shift: Dominant, Median-Based, dan Hybrid Confidence-Aware; jelaskan faktor/rumus yang dipakai.
- Tampilkan shift share, primary/secondary shift, serta status CLEAR, MODERATE, AMBIGUOUS, atau INSUFFICIENT_DATA.
- Save menyimpan filter, konfigurasi shift, dan snapshot hasil di backend; Load tidak menghitung ulang.

Penerimaan: tiga LO satu shipment untuk satu SPBU menghasilkan satu observasi; 23.50 dan 00.10 terbaca berdekatan; shift overlap ditolak; sumber Gate Out dan observasi yang dikecualikan terlihat jelas.

Batas: waktu keberangkatan bukan waktu tiba SPBU atau rekomendasi dispatch.

### F05 — SPBU Pairing Intelligence

Tujuan: menemukan SPBU yang sering berada dalam shipment yang sama.

Kebutuhan:

- Filter depot, periode 7/14/30 hari atau custom, produk, SPBU, dan Apply.
- Hitung membership unik shipment + SPBU setelah filter produk; pasangan A–B sama dengan B–A untuk pair count.
- Hitung P(B|A), P(A|B), support, lift, dan evidence confidence.
- Tampilkan top pairs, matrix, network, detail pasangan, jumlah shipment, dan evidence.
- Network memakai hubungan same-shipment. Urutan kunjungan tidak disimpulkan dari pairing.
- Save/Load snapshot dan export hasil.
- Data sedikit diberi status INSUFFICIENT_DATA; definisi threshold tampil dalam panduan dan tersimpan bersama hasil.

Penerimaan: 30 shipment bersama dari 100 shipment A dan 40 shipment B menghasilkan P(B|A)=30% dan P(A|B)=75%; duplicate LO tidak menambah pair count; filter produk diterapkan sebelum deduplikasi.

### F06 — SPBU–MT Affinity & Stability

Tujuan: menjelaskan kebiasaan penggunaan armada dan perubahan pola dari waktu ke waktu.

Kebutuhan:

- Unit observasi unik depot + shipment + SPBU + MT; filter produk sebelum deduplikasi.
- Filter periode, SPBU, minimum observasi, confidence, temporal bucket, dan recent period.
- Hitung P(MT|SPBU), P(SPBU|MT), dominant MT, Top-3 Share, consistency, variability, temporal stability, dan confidence.
- Consistency memakai normalized HHI; variability memakai normalized entropy; stability memakai kemiripan distribusi antar-bucket dan dominant-MT persistence.
- Confidence merupakan kualitas bukti, terpisah dari skor pola.
- Grafik probability, time series, recent versus full period, scatter, pattern matrix, rankings, network, dan evidence.
- Label pola seperti DEDICATED-LIKE, PREFERRED-FLEET, atau FLEXIBLE dijelaskan sebagai label analitik.
- Simpan parameter, formula/versi algoritma, snapshot, serta export.

Penerimaan: satu MT yang selalu digunakan memiliki consistency 100 dan variability 0; stability menjadi N/A bila bucket tidak cukup; penggunaan beberapa MT secara stabil tidak otomatis dilabeli perubahan pola.

### F07 — Machine Learning: Engine A

Tujuan: menemukan konsentrasi penggunaan MT yang relatif tidak biasa.

Kebutuhan:

- Pilih depot, baseline period, minimum observasi, dan parameter analisis.
- Fitur mencakup jumlah MT kompatibel, jumlah digunakan, utilization breadth, dominant share, HHI, entropy, dan jumlah shipment.
- Hanya profil dengan evidence cukup mengikuti standardisasi dan Isolation Forest.
- Tampilkan skor relatif 0–100, ukuran sampel, fitur profil, peer context, dan evidence.
- Jelaskan bahwa skor adalah posisi relatif dalam run, bukan probabilitas kesalahan atau skor yang otomatis sebanding antarrun.
- Jika seluruh raw score sama, skor relatif menjadi 0.
- Save/Open hasil tanpa recompute; export profil.

Penerimaan: profil insufficient tetap terlihat tetapi tidak diberi skor model; skor dapat direproduksi dari snapshot, seed, parameter, dan versi algoritma yang sama.

### F08 — Machine Learning: Engine B

Tujuan: mengelompokkan SPBU dengan pola perilaku historis serupa.

Alur: Prepare Dataset → Validate → Configure → Train → Review → Save → Activate bila diperlukan.

Kebutuhan:

- Fitur tag, distribusi shift, graph pairing, dan geografis.
- Jika koordinat tersedia dan fitur geografis diaktifkan, bobot awal tag 30%, shift 20%, pairing 30%, geografis 20%. Tanpa koordinat, geografis 0% dan bobot awal tag 37,5%, shift 25%, pairing 37,5%. Pengguna dapat mengubah bobot dan total harus 100%.
- Geography dapat dinonaktifkan; kedekatan Haversine bukan jarak jalan.
- Pipeline yang direncanakan: embedding graph pairing Node2Vec/PPMI-SVD → scaling/fusion fitur → UMAP → HDBSCAN.
- Tampilkan data sufficiency untuk setiap SPBU: SUFFICIENT ≥80, MARGINAL ≥50, dan INSUFFICIENT <50 sebagai default yang versioned.
- SUFFICIENT membentuk model; MARGINAL dapat diproyeksikan dengan metode dan threshold confidence tersimpan; INSUFFICIENT tetap unassigned.
- Noise dari HDBSCAN dibedakan dari data insufficient dan marginal projection.
- Visualisasi UMAP terpisah dari peta geografis; tampilkan profil cluster, daftar anggota, shift, tag, pairing, serta coverage koordinat/data.
- Model harus diberi nama saat Save; versi tersimpan immutable.
- Satu model aktif per depot; aktivasi baru menonaktifkan status aktif sebelumnya tanpa menghapusnya.
- Model aktif tidak dapat dihapus; model lain dapat diarsipkan.
- Perbandingan model memakai kecocokan anggota, bukan menyamakan nomor cluster; tampilkan perubahan populasi dan parameter.

Penerimaan: bobot invalid ditolak; SPBU insufficient tidak menerima cluster/probability palsu; saved model dibuka tanpa training ulang; edit koordinat master tidak mengubah snapshot model lama.

### Readiness ML bersama

- Harus ada setidaknya satu penugasan historis yang dievaluasi dalam scope readiness yang ditampilkan.
- Semua penugasan dalam scope tersebut harus MATCH; MISMATCH dan DATA_ISSUE memblokir eksekusi.
- Default scope adalah tanggal histori terbaru pada depot terpilih; UI menampilkan tanggal, numerator/denominator, dan tautan isu. Gate ini tidak diklaim memvalidasi seluruh baseline/training period.
- Baseline/training dataset memiliki validasi tambahan atas referensi, kecukupan bukti, dan coverage; baris yang dikecualikan ditampilkan.
- Pasangan MT–SPBU yang tidak eligible dalam matriks seluruh master bukan otomatis masalah historis.
- Gate diperiksa ulang backend saat Analyze, Prepare, Train, Save, dan Activate; state UI tidak dapat melewatinya.

## 8. Rumus dan cara membaca hasil

| Metrik | Definisi sederhana |
|---|---|
| P(B|A) | Shipment berisi A dan B / shipment berisi A |
| Support(A,B) | Shipment berisi A dan B / seluruh shipment eligible |
| Lift(A,B) | P(B|A) / proporsi shipment berisi B |
| P(MT|SPBU) | Shipment SPBU memakai MT / seluruh shipment SPBU |
| P(SPBU|MT) | Shipment MT melayani SPBU / seluruh shipment MT |
| Shift share | Observasi departure dalam shift / seluruh observasi departure SPBU |
| HHI | Jumlah kuadrat proporsi penggunaan setiap MT |
| Top-3 Share | Jumlah proporsi tiga MT yang paling sering digunakan |

Setiap rumus memiliki tooltip dan contoh. Denominator kosong ditampilkan N/A dengan alasan; bukti cukup tetapi kejadian tidak ada dapat menghasilkan 0. Confidence tidak boleh disamakan dengan probabilitas prediction. Formula hybrid shift, confidence, sufficiency, serta stability harus didokumentasikan dan diberi versi sebelum implementasi diterima.

## 9. Pengalaman pengguna

- Nama produk “Agam tukang dispet” tampil pada sidebar dan halaman login.
- Bahasa utama Indonesia; istilah teknis diberi penjelasan singkat.
- Identitas visual dibuat sendiri, tidak menyalin logo/branding Petrofin.
- Sidebar konsisten, depot aktif jelas, serta filter/Apply berada di atas halaman.
- Urutan analisis: ringkasan → grafik → tabel → detail evidence.
- Grafik dan tabel saling menyorot entitas yang dipilih; filter detail tidak mengubah KPI global tanpa penjelasan.
- Pagination tabel analitik 10/25/50/100; tabel besar tidak memuat seluruh data sekaligus.
- Warna status disertai teks/ikon agar dapat dipahami tanpa membedakan warna.
- Ada loading, empty, insufficient, failure, dan permission state yang berbeda.
- Export mencantumkan depot, periode, filter, waktu analisis, versi algoritma, dan data sumber.

## 10. Kebutuhan nonfungsional

- Akses depot diperiksa di server, termasuk file hasil export dan model.
- File upload dibatasi ukuran/format dan disimpan di lokasi terlindungi.
- Audit mencatat import/publish, perubahan master/aturan, run analisis, dan lifecycle model.
- Import dan training berjalan melalui job persisten dengan progress, timeout, recovery, serta diagnostic; menutup browser tidak membatalkan job.
- Analisis menyimpan input snapshot, parameter, versi aturan/algoritma, dan source lineage.
- Kesalahan provider peta tidak menghilangkan tabel atau hasil analisis.
- Backup database dan artifact model harus memiliki uji pemulihan.
- Target awal: p95 halaman ringkasan/tabel ≤3 detik pada dataset dan lingkungan pilot yang disepakati. Analisis besar/training menggunakan job; durasi nyata dicatat, tanpa janji selesai ≤3 detik.
- Sebelum pengujian performa, tetapkan volume MT/SPBU/LO, rentang histori, pengguna bersamaan, dan spesifikasi server pilot.

## 11. Rancangan teknis dan struktur proyek

### Teknologi yang disepakati

- Frontend: HTML, CSS, dan JavaScript standar dengan JavaScript modules; tidak mewajibkan React atau TypeScript. ECharts digunakan untuk grafik; Leaflet hanya jika fitur peta diaktifkan.
- Backend: Python + FastAPI untuk API, validasi, import Excel, analisis, dan ML.
- Database: PostgreSQL lokal selama pembangunan, dengan penyimpanan persisten. PostGIS belum diperlukan tanpa fitur geografis khusus.
- pgAdmin: tersedia untuk membuka database dan melihat tabel/baris/kolom melalui browser. Sertakan petunjuk koneksi, melihat tabel, query dasar, dan backup/restore.
- Worker job persisten untuk import, analisis berat, dan ML.
- Analitik: pandas/NumPy/scikit-learn/UMAP/NetworkX.
- Docker Compose dapat menjalankan backend, database, pgAdmin, dan worker secara konsisten.

Frontend mengakses backend; backend mengakses database. pgAdmin terhubung langsung ke PostgreSQL sebagai alat pemeriksaan. Folder database berisi rancangan tabel, migrasi, serta contoh data; file internal PostgreSQL disimpan pada volume persisten terpisah. Hentikan/restart container tidak menghapus volume. Kredensial lokal ditempatkan pada konfigurasi privat dan tidak dikomit.

### Struktur folder wajib saat implementasi

Struktur ini adalah rancangan aplikasi baru; revisi PRD tidak memindahkan kode repositori referensi.

```text
agam-tukang-dispet/
├── frontend/                  # Tampilan di browser
│   ├── index.html             # Halaman masuk aplikasi
│   ├── halaman/               # Tampilan setiap menu
│   ├── komponen/              # Sidebar, tabel, filter, dialog
│   ├── gaya/                  # CSS
│   ├── skrip/                 # JavaScript interaksi dan API
│   └── aset/                  # Logo, ikon, gambar
├── backend/                   # Pengolahan data dengan Python
│   ├── aplikasi.py            # Titik awal backend
│   ├── pengaturan.py          # Membaca konfigurasi
│   ├── rute/                  # Endpoint API per menu
│   ├── validasi/              # Pemeriksaan input/import
│   ├── layanan/               # Pengelolaan data dan aturan
│   ├── analisis/              # Departure, pairing, affinity, ML
│   └── pekerja/               # Proses antrean di latar belakang
├── database/                  # Rancangan dan perubahan tabel
│   ├── skema/                 # Struktur/hubungan tabel
│   ├── migrasi/               # Perubahan database berurutan
│   └── contoh_data/           # Data buatan untuk belajar/uji
├── pengujian/                 # Uji fitur, API, dan analitik
├── dokumentasi/               # PRD, panduan, penjelasan struktur
├── penyimpanan/               # File import dan artifact model lokal
├── cadangan/                  # Hasil backup lokal
├── compose.yaml               # Menjalankan layanan lokal
├── .env.example               # Contoh konfigurasi tanpa rahasia
└── README.md                  # Cara mulai dan peta folder
```

Nama folder/file menggunakan bahasa Indonesia yang mudah dipahami, huruf kecil dan underscore jika terdiri dari beberapa kata. Nama standar alat seperti index.html, README.md, dan compose.yaml dipertahankan. Contoh: dashboard.js, master_depot.js, historikal_shipment.js, analisis_keberangkatan.py, analisis_pairing.py, analisis_afinitas.py, dan koneksi_database.py.

Setiap folder utama mempunyai README singkat yang menjelaskan fungsi, file penting, dan cara menjalankannya. Komentar menjelaskan alasan aturan/perhitungan dengan bahasa sederhana. Pisahkan tampilan, komunikasi API, validasi, pengolahan, dan penyimpanan agar tidak terkumpul dalam satu file besar. File upload, model, backup, dan rahasia dikecualikan dari Git.

### Tabel yang mudah diperiksa melalui pgAdmin

Nama awal: depot, bay_depot, mobil_tangki, spbu, historikal_shipment, detail_shipment, riwayat_import, masalah_data, hasil_analisis, konfigurasi_shift, model_machine_learning, dan catatan_perubahan. Struktur header/detail histori ditetapkan setelah identitas shipment pada file sumber dipastikan. Produk/tag tetap field pengguna; tabel relasi internal boleh digunakan bila diperlukan tanpa menambah menu master.

Penerimaan teknis: pengguna dapat menjalankan layanan mengikuti README, membuka pgAdmin, melihat tabel depot/MT/SPBU/histori, dan mencocokkan contoh record dengan web app. Backup/restore diuji. Frontend memakai HTML/JavaScript dan bagian aplikasi dapat ditemukan dari peta folder.

## 12. Tahapan pembangunan

| Tahap | Hasil | Syarat selesai |
|---|---|---|
| 1 — Fondasi | Struktur folder, HTML/JavaScript, backend, PostgreSQL + pgAdmin, login, empat master, import/publish, kualitas data | Tabel terlihat di pgAdmin; akses depot dan dataset tervalidasi |
| 2 — Pemeriksaan | Dashboard dan Tag Consistency | KPI cocok dengan data; aturan/evidence dapat ditelusuri |
| 3 — Historis | Departure/shift, pairing, affinity | Deduplikasi, rumus, midnight, dan snapshot lulus acceptance |
| 4 — ML | Engine A, Engine B, registry/comparison | Gate, sufficiency, reproducibility, serta lifecycle model teruji |
| 5 — Pilot | Export, panduan lengkap, backup, uji pengguna/performa | Seluruh cakupan rilis dipakai end-to-end pada data pilot |

Semua tahap termasuk cakupan produk yang diminta. Urutan ini merupakan urutan pengerjaan, bukan pengurangan fitur rilis.

## 13. Skenario penerimaan end-to-end

1. Buat dua depot dengan kode SPBU/nomor MT yang sama; buktikan data, analisis, dan akses tetap terpisah.
2. Import file valid, invalid, dan duplikat; tinjau lalu publish; pastikan histori dan baris error dapat ditelusuri.
3. Periksa pasangan MT–SPBU yang cocok, melampaui kelas, kehilangan tag, dan kehilangan referensi.
4. Analisis shipment multi-produk dan departure lintas tengah malam; buktikan observasi tidak berlipat.
5. Hitung pairing dan affinity dari dataset kecil dengan hasil manual yang diketahui.
6. Simpan analisis, edit master/import histori baru, lalu buka snapshot lama; hasil harus tetap sama.
7. Jalankan ML untuk gate gagal, data insufficient, noise, dan model valid; buktikan status tidak tercampur.
8. Putus sesi browser saat import/training, lalu buka kembali; job tetap dapat dipantau.
9. Simpan dan aktifkan model per depot; bandingkan versi tanpa bergantung pada nomor cluster.
10. Login dengan peran/depot berbeda; buktikan tindakan dan data di luar izin ditolak API.

## 14. Keputusan yang perlu ditetapkan saat kickoff

Rancangan dapat menjadi dasar implementasi; hal berikut harus dipastikan dari data/pengguna nyata sebelum kontrak teknis dikunci:

- File sumber, mapping kolom, identitas shipment, dan aturan konflik/update import.
- Daftar jenis tag serta mana yang wajib; ketersediaan aturan kompatibilitas produk.
- Definisi shift operasional per depot.
- Formula/threshold confidence, hybrid shift, sufficiency, stability, dan proyeksi marginal.
- Identitas/pengelompokan shipment multi-LO pada contoh Excel, satuan flow rate bay, dan bentuk field kompartemen.
- Ketersediaan koordinat jika fitur geografis ML akan diaktifkan; GPS di luar kebutuhan awal.
- Ukuran dataset, concurrency, lingkungan deployment, identity provider, dan retensi data/artifact.

Asumsi awal: histori shipment tersedia; zona waktu mengikuti pengaturan aplikasi yang dapat dikonfigurasi per depot bila diperlukan; departure memakai Gate Out; penggunaan utama melalui desktop. PostgreSQL dan pgAdmin dijalankan lokal pada tahap pembangunan. Asumsi data harus divalidasi dalam pilot.


## 15. Catatan revisi 1.1

Revisi mengikuti arahan pengguna: dashboard merangkum lima kelompok analisis; master hanya Depot/bay, MT, SPBU, Historikal Shipment dengan field yang disepakati; pilih depot sebelum add/import; hapus satuan/bulk; frontend HTML/JavaScript; backend Python; PostgreSQL lokal dapat dibuka melalui pgAdmin; struktur folder dan penamaan mudah dipelajari.
