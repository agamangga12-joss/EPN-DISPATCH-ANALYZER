# Dispatch Intelligence Platform

Dispatch Intelligence Platform adalah aplikasi intelligence dan operational control distribusi BBM. Platform ini dibangun bertahap dari Phase 0 sampai Phase 9 untuk mengubah:

Master Data + Loading Order + GPS Operational Data + Historical Dispatch

menjadi trusted operational intelligence, saved prediction, dynamic multi-trip route plan, final human-reviewed dispatch, dan evaluasi keselarasan historis yang auditable. Phase 6 menghasilkan warm start shipment/MT; Phase 7 memakai Google OR-Tools untuk optimasi fleet-wide dan depot bay scheduling; Phase 8 membuat snapshot untuk adjustment manual, per-trip recalculation, simulation, dashboard, audit, dan finalization; Phase 9 mengukur empat kategori alignment secara deskriptif tanpa menilai route baik atau buruk. Google Routes API tetap hanya menjadi provider jarak, waktu, matrix, dan geometry—bukan optimization engine.

Prinsip utama: jangan lanjut ke phase berikutnya sebelum phase berjalan benar, diuji, tervalidasi visual, terdokumentasi, dan usable.

## Run

Untuk Windows tanpa Docker, lihat [panduan lokal](docs/LOCAL_WINDOWS.md).
Setelah runtime lokal disiapkan, jalankan `.\start-local.ps1`; hentikan dengan
`.\stop-local.ps1`. Database lokal terpisah memakai port `5433`.

```bash
cp .env.example .env
# set GOOGLE_ROUTES_ENCRYPTION_KEY to a deployment-specific secret (minimum 16 chars)
# set PGADMIN_DEFAULT_PASSWORD to a strong password for the pgAdmin web login
docker compose up --build
```

`GOOGLE_ROUTES_ENCRYPTION_KEY` melindungi Google Maps API key yang disimpan aplikasi. Jangan commit `.env` atau memakai nilai contoh yang sama pada production. Google API key sendiri dimasukkan setelah login ke UI **Settings - Google Maps**, bukan ke frontend environment.

Services:

- API: `http://localhost:8000/api/v1/health`
- Web: `http://localhost:3000`
- Web juga dapat dibuka melalui `http://127.0.0.1:3000`. Biarkan `VITE_API_BASE_URL` kosong agar request `/api` diteruskan oleh web server ke API Docker tanpa masalah CORS. Untuk development di luar Docker, proxy memakai `http://127.0.0.1:8000` secara default; gunakan `API_PROXY_TARGET` bila backend berada di alamat lain.
- PostgreSQL/PostGIS: `localhost:5432`
- pgAdmin: `http://127.0.0.1:5051` (panduan: [Akses database dengan pgAdmin](docs/PGADMIN.md))
- Phase 6 worker: service internal `phase6-worker`; status/log dapat diperiksa dengan `docker compose ps phase6-worker` dan `docker compose logs -f phase6-worker`

Catatan lokal: jika port `3000` sudah terpakai, jalankan web dengan port lain, misalnya:

```bash
WEB_PORT=3001 docker compose up -d web
```

## Current UI

- Dashboard visualisasi: `/`
- Master Data Management: `/master-data`
- Tag Consistency Analysis: `/tag-consistency`
- Phase 2 - Depot Departure Time Intelligence: `/departure-intelligence`
- Phase 3 - SPBU Pairing Probability Intelligence: `/pairing-intelligence`
- Phase 4 - SPBU–MT Historical Affinity & Stability Intelligence: `/affinity-intelligence`
- Phase 5 - Machine Learning Intelligence: `/machine-learning-intelligence`
- Phase 6 - Shipment & MT Assignment Prediction: `/prediction-assignment`
- Phase 7 - Dynamic Multi-Trip VRP & Depot Bay Queue: `/phase7-optimization`
- Phase 8 - Manual Dispatching & Operational Simulation: `/phase-8/manual-dispatch`
- Phase 9 - Route–Model Alignment Evaluation: `/phase9/route-model-alignment`
- Settings - Google Maps Integration: `/settings/google-maps-integration`
- Documentation - Panduan Pengguna: `/documentation`

Halaman Documentation menyediakan panduan Bahasa Indonesia untuk seluruh page aktif, tree table of contents yang dapat diklik, deep-link per topik, pencarian card/metric/rumus, cara penggunaan, cara membaca output, formula, dan contoh perhitungan.

Tema UI saat ini diselaraskan dengan aplikasi `vrp_planner` dan palet Petrofin:

- Petrofin blue `#0b73bf` untuk primary action, chart, dan aksen navigasi.
- Petrofin lime `#b8d211` untuk active navigation highlight dan focus state.
- Petrofin ink `#15385b` untuk teks utama.
- Petrofin red `#ea4a43` untuk error, warning kritikal, dan destructive action.
- Background memakai warm paper gradient dan panel putih dengan shadow halus agar senada dengan tampilan Petrofin planner.

Dashboard saat ini dibuat clean untuk visualisasi:

- filter dashboard by depot
- KPI cards
- Phase 0 charts
- data quality explorer
- placeholder untuk feature analitik lanjutan, tetapi belum menjadi scope aktif Phase 0

Halaman Master Data berisi operasional data-management:

- import file lokal `.xlsx` atau `.csv`
- export template
- export data per depot
- import sample data
- import history
- CRUD master data
- filter CRUD by search, depot, status
- pagination CRUD per `10`, `50`, `100`, atau `All records`
- checkbox select all dan select per row pada tabel CRUD
- sort pada masing-masing kolom tabel CRUD
- dynamic tag-type columns pada Master MT dan Master SPBU
- edit tag MT/SPBU melalui modal edit CRUD
- Sync Depot/Product/Tag dari canonical source yang masih aktif saja
- SPBU coordinate parsing dari format `latitude longitude`, termasuk decimal comma seperti `5,19182389869645 96,4368560343681`

Halaman Phase 2 - Depot Departure Time Intelligence berisi analisa deskriptif historis keberangkatan Mobil Tangki dari depot:

- filter utama Depot, Start Date, End Date, bucket 30/60 menit, dan Apply
- tombol Apply menjalankan departure analysis dan Operational Shift Intelligence secara terpadu
- tidak menjalankan analisa otomatis saat halaman dibuka
- unit observasi adalah `shipment_id + spbu_id`, sehingga beberapa line Loading Order untuk produk berbeda tidak menggandakan observasi SPBU yang sama
- timestamp analitik `departure_datetime_used` memprioritaskan GPS depot-exit yang reliabel bila tersedia, lalu fallback ke `fact_shipment.gate_out_datetime`
- lineage timestamp tetap ditampilkan sebagai LO gate-out, GPS depot exit, timestamp yang dipakai, dan source (`GPS` atau `LO_GATE_OUT`)
- output meliputi KPI, source coverage, 24-hour distribution, weekday heatmap, SPBU box plot, profile table, confidence, Operational Shift Intelligence, dan source-lineage explorer
- date picker menandai tanggal yang memiliki data departure berbeda dari tanggal tanpa data
- SPBU box plot menggunakan circular-time scale agar pola melewati midnight tidak terlihat sebagai outlier 24 jam palsu
- table pagination `10`, `25`, `50`, dan `100` rows tersinkron dengan box plot dan SPBU Shift Affinity Heatmap

Phase 2 bersifat descriptive intelligence. Halaman ini tidak menghitung arrival SPBU, ETA, route sequence, travel time, route optimization, atau rekomendasi jadwal dispatch.

Halaman Phase 3 - SPBU Pairing Probability Intelligence berisi relationship intelligence antar-SPBU:

- filter utama Depot, Date Range `7 Days` / `14 Days` / `30 Days` / `Custom Range`, Product, Search, dan Apply
- tidak menjalankan analisa otomatis saat halaman dibuka
- unit analitik utama adalah `shipment_id`
- pairing berarti dua SPBU berada dalam shipment yang sama: `A - B`
- pair diolah secara canonical unordered, tetapi conditional probability tetap directional
- `P(B|A) = shipment(A and B) / shipment(A)`
- `P(A|B) = shipment(A and B) / shipment(B)`
- `Support(A,B) = shipment(A and B) / total eligible shipment`
- `Lift(A,B) = P(B|A) / P(B)`, dengan zero denominator ditangani sebagai `0`
- confidence adalah evidence confidence, bukan prediction probability
- default confidence rule: `INSUFFICIENT_DATA` jika `min(shipment_a_count, shipment_b_count) < 5` atau `pair_count < 3`; `LOW` jika `pair_count < 10`; `MEDIUM` jika `10 <= pair_count < 30`; `HIGH` jika `pair_count >= 30`
- KPI, Data Quality panel, Top Pairing Explorer, Pairing Matrix, Pairing Network Prototype, SPBU Pairing Detail, dan Historical Evidence drill-down

Product segmentation:

- `All Products` menggunakan canonical `fact_shipment_spbu`
- product-specific analysis menggunakan distinct `shipment_id + spbu_id` dari Loading Order line yang memiliki product terpilih
- shipment multi-produk tetap dihitung sebagai shipment yang sama
- repeated LO/product/compartment lines tidak menggandakan membership atau pair count

GPS transition distinction:

- `A - B` berarti same-shipment pairing
- `A -> B` berarti actual consecutive visit berdasarkan `fact_shipment_stop.stop_sequence`
- shipment dengan sequence `A -> C -> B` menghasilkan pairing `A - C`, `A - B`, `C - B`, tetapi transition hanya `A -> C` dan `C -> B`
- Phase 3 tidak memakai transition sebagai edge thickness pairing dan tidak melakukan route optimization

Phase 3 tetap independen dari Phase 2. Departure profile dapat menjadi konteks di fase berikutnya, tetapi Phase 3 tidak mengubah departure window atau shift assignment Phase 2.

Halaman Phase 4 mengukur historical vehicle-assignment behavior:

- filter Depot, Search SPBU, Date Range, Product, Minimum Observations, Confidence, Temporal Bucket, Recent Period, Top-N, dan network edge metric
- unit observasi unik `depot_id + shipment_id + spbu_id + mt_id`; product filtering dilakukan sebelum deduplikasi final
- `P(MT|SPBU)`, `P(SPBU|MT)`, dominant MT, Top-3 Share, Fleet Affinity Vector, HHI, normalized HHI, dan normalized entropy
- consistency, variability, evidence confidence, dan temporal stability tetap merupakan metric terpisah
- temporal stability memakai consecutive-bucket Jensen–Shannon similarity dan dominant-MT persistence
- output profile, probability chart, time series, recent comparison, scatter, pattern matrix, rankings, reverse MT detail, bipartite network, dan shipment evidence
- hasil hanya mendeskripsikan historical dispatch; tidak menghasilkan future assignment recommendation atau optimization

### Panduan membaca halaman Phase 4

#### Filter dan tombol Apply

Card paling atas menentukan scope analisis. Perubahan filter belum mengubah hasil sampai tombol **Apply** ditekan.

Tombol **Save** menyimpan filter yang sudah di-Apply, SPBU–MT detail aktif, viewport grafik, serta snapshot hasil analisis ke backend. Tombol **Load** memulihkan snapshot tersebut tanpa menghitung ulang, sehingga hasil yang dibuka tetap merepresentasikan kondisi saat konfigurasi disimpan. Nama yang sama dalam depot yang sama memperbarui konfigurasi tersimpan; tabel **Saved SPBU–MT Affinity Analysis Configurations** menyediakan pagination dan penghapusan konfigurasi.

| Filter | Fungsi | Cara membaca atau menggunakan |
|---|---|---|
| Depot | Membatasi shipment, SPBU, dan MT pada satu depot. | Data antardepot tidak dicampur. Depot wajib dipilih. |
| Search SPBU | Memilih SPBU aktif berdasarkan kode atau nama dari saran pencarian. | Field aktif setelah depot dipilih. Pilih hasil yang sesuai lalu tekan **Apply**; profile, probability chart, time series, recent comparison, network highlight, dan evidence akan memakai SPBU tersebut. Jika dikosongkan, sistem memakai SPBU eligible pertama pada scope aktif. |
| Start Date / End Date | Membatasi tanggal operasi shipment. | Teks `Available` menunjukkan rentang data yang benar-benar tersedia untuk depot tersebut. |
| Product | Memilih All Products atau satu produk. | Product filtering dilakukan sebelum deduplikasi. Shipment–SPBU–MT yang muncul pada beberapa LO untuk produk yang sama tetap dihitung satu kali. |
| Minimum Observations | Menentukan minimum historical shipment sebuah SPBU agar masuk hasil. | Naikkan nilai ini untuk mengurangi profile dengan evidence sangat sedikit. |
| Confidence | Menampilkan semua profile, Medium+, atau hanya High. | Filter ini menyaring kekuatan evidence; tidak mengubah Consistency atau Variability Score. |
| Temporal Bucket | Memilih Daily, Weekly, Monthly, atau Auto. | Bucket yang benar-benar digunakan selalu ditampilkan pada Data Quality card sehingga aggregation tidak tersembunyi. |
| Recent Period | Menentukan recent window 7, 14, atau 30 hari. | Dipakai untuk membandingkan recent distribution dengan full-period distribution, tanpa hidden recency weighting. |
| Top MT | Menentukan Top 5, Top 10, atau seluruh MT pada probability chart. | Mengubah jumlah bar yang ditampilkan, bukan denominator probability. |
| Network Edge | Memilih bobot edge berupa Shipment Count atau Affinity Probability. | Pilihan ini mengubah nilai edge network; edge width tetap membantu melihat kekuatan evidence historis. |

Saat halaman pertama dibuka, KPI dan visualisasi sengaja kosong. Empty state tersebut menandakan analysis scope belum diterapkan, bukan menandakan data tidak tersedia.

SPBU aktif ditentukan dengan urutan berikut:

1. SPBU yang dipilih melalui **Search SPBU** saat Apply;
2. SPBU yang diklik dari ranking, scatter plot, pattern matrix, reverse chart, atau network;
3. SPBU eligible pertama dari hasil analisis jika belum ada pilihan eksplisit.

Pilihan dari grafik atau tabel disinkronkan kembali ke field Search SPBU. Search SPBU memilih fokus detail dan tidak membatasi KPI maupun Data Quality Summary; kedua bagian tersebut tetap merangkum seluruh SPBU yang lolos scope dan filter aktif.

Urutan kelompok card utama pada layout saat ini adalah:

1. KPI Summary dan Data Quality Summary;
2. SPBU Consistency Scatter Plot, Historical Pattern Matrix, ranking cards, dan Historical SPBU–MT Bipartite Network;
3. Historical Evidence Drill-Down;
4. SPBU–MT Historical Profile;
5. MT Historical Probability dan Historical MT Affinity Over Time;
6. Recent vs Full-Period Pattern dan MT Reverse Historical Affinity;
7. Methodology & Guardrails.

#### KPI summary cards

Seluruh KPI mengikuti depot, tanggal, produk, minimum observation, dan confidence filter yang sudah di-Apply.

| Card | Arti | Cara membaca |
|---|---|---|
| Eligible Shipments | Jumlah distinct shipment yang mempunyai minimal satu observation SPBU–MT valid. | Bandingkan dengan Source Shipments pada Data Quality card. Selisihnya adalah shipment yang tidak dapat dianalisis. |
| SPBU Analyzed | Jumlah SPBU yang lolos minimum observation dan confidence filter. | Nilai dapat turun saat Minimum Observations dinaikkan atau Confidence diperketat. |
| MT Observed | Jumlah MT unik yang muncul pada relationship milik SPBU yang lolos filter. | Ini historical observed fleet, bukan jumlah MT yang tersedia pada master. |
| Unique SPBU–MT Pairs | Jumlah relationship unik SPBU–MT yang benar-benar pernah terjadi. | Satu pair dapat dibentuk oleh satu atau banyak shipment. Duplicate LO tidak menambah jumlah pair. |
| Avg MT / SPBU | Rata-rata jumlah MT unik yang pernah melayani satu SPBU. | Nilai tinggi menunjukkan fleet footprint rata-rata lebih lebar, tetapi belum otomatis berarti pola tidak konsisten. |
| Median MT / SPBU | Nilai tengah jumlah MT unik per SPBU. | Lebih tahan terhadap SPBU ekstrem daripada average. Bandingkan Average dengan Median untuk melihat pengaruh outlier. |
| High Consistency | Jumlah SPBU dengan Consistency Score minimal 65. | Menunjukkan banyaknya SPBU dengan assignment distribution terkonsentrasi. Tetap periksa Confidence. |
| High Variability | Jumlah SPBU dengan Variability Score minimal 65. | Menunjukkan banyaknya SPBU dengan distribution relatif tersebar pada banyak MT. |
| Low Stability | Jumlah SPBU dengan Temporal Stability di bawah 50. | Menunjukkan banyaknya pola SPBU–MT yang berubah kuat antar-bucket. Ini berbeda dari variability keseluruhan periode. |
| Pattern Shifts | Jumlah SPBU dengan flag selain `STABLE`. | Mencakup `MINOR SHIFT`, `MODERATE SHIFT`, dan `MAJOR SHIFT`; aplikasi tidak menyimpulkan penyebab perubahan. |

Contoh interpretasi gabungan:

```text
High Variability tinggi + Low Stability rendah
→ Banyak MT digunakan, tetapi proporsi penggunaannya relatif konsisten dari waktu ke waktu.

High Consistency tinggi + Pattern Shifts tinggi
→ Overall distribution dapat terlihat terkonsentrasi, tetapi dominant fleet atau distribusinya berubah pada bagian tertentu dari periode.
```

#### SPBU–MT Historical Profile card

Card ini menjelaskan SPBU yang sedang dipilih. SPBU dapat dipilih melalui Search SPBU, ranking, scatter plot, pattern matrix, reverse chart, atau network.

| Sub-card / metric | Arti | Cara membaca |
|---|---|---|
| SPBU | Kode SPBU aktif. | Semua affinity chart, temporal chart, recent comparison, dan evidence mengacu pada SPBU ini. |
| SPBU Tag | Daftar tag master yang terhubung ke SPBU aktif. | Tanda `-` berarti SPBU tidak mempunyai tag aktif pada master data. |
| Historical Shipments | Distinct shipment yang melayani SPBU pada scope aktif. | Ini denominator `P(MT|SPBU)`. |
| Operating Days | Jumlah tanggal operasi unik yang mempunyai evidence. | Dua SPBU dengan shipment count sama dapat mempunyai temporal evidence berbeda jika operating days berbeda. |
| Unique MT Used | Jumlah MT berbeda yang pernah melayani SPBU. | Baca bersama probability distribution, consistency, variability, dan confidence; jangan digunakan sendirian. |
| Dominant Historical MT | MT dengan historical shipment count terbesar untuk SPBU. | `Dominant` hanya berarti paling sering terjadi secara historis, bukan MT yang harus digunakan berikutnya. |
| Dominant Probability | Proporsi shipment SPBU yang menggunakan dominant MT. | Contoh 54% berarti 54% shipment SPBU pada scope aktif menggunakan MT tersebut. |
| Top-3 MT Share | Total probability tiga MT teratas. | Nilai tinggi menunjukkan mayoritas assignment terkonsentrasi pada tiga MT utama. |
| Historical Pattern | Label `DEDICATED-LIKE`, `PREFERRED-FLEET`, atau `FLEXIBLE`. | Label bersifat analytical. `DEDICATED-LIKE` bukan status dedicated kontraktual. |

Empat horizontal score tracks dibaca dari 0 di kiri ke 100 di kanan:

- **MT Consistency**: normalized HHI. Nilai tinggi berarti assignment terkonsentrasi pada sedikit MT. Untuk satu MT, nilainya deterministik 100.
- **Historical Variability**: normalized entropy. Nilai tinggi berarti assignment lebih merata atau tersebar. Untuk satu MT, nilainya deterministik 0.
- **Temporal Stability**: persistence pola antar-bucket. Nilai tinggi berarti fleet distribution relatif bertahan dari waktu ke waktu.
- **Evidence Confidence**: kekuatan evidence berdasarkan shipment count, operating days, date coverage, recency, dan temporal coverage. Nilai ini tidak dikalikan dengan score pola.

Badges di bawah score tracks mempunyai arti:

- **Confidence HIGH / MEDIUM / LOW**: tingkat kekuatan evidence.
- **STABLE / MINOR SHIFT / MODERATE SHIFT / MAJOR SHIFT**: besarnya perubahan distribution yang terukur.
- **VERY HIGH CONSISTENCY sampai VERY HIGH VARIABILITY**: klasifikasi user-facing dari concentration score.
- **Dominant persistence**: persentase bucket yang dominant MT-nya sama dengan dominant mode seluruh bucket. Nilai 100% berarti dominant MT tidak berganti.

#### Data Quality Summary card

| Metric | Arti | Cara membaca |
|---|---|---|
| Source Shipments | Seluruh shipment pada depot dan date range sebelum eligibility check. | Menjadi baseline kualitas data. |
| Eligible Shipments | Shipment yang menghasilkan observation valid. | Harus sama dengan KPI Eligible Shipments. |
| Excluded Shipments | Shipment yang tidak menghasilkan observation valid. | Periksa daftar exclusion reasons untuk mengetahui masalah pemetaan atau key wajib. |
| Eligible % | `Eligible Shipments / Source Shipments × 100`. | Nilai tinggi berarti coverage analitik lebih baik. |
| Duplicate Observations Removed | Baris tambahan yang mempunyai key shipment–SPBU–MT sama setelah product filter. | Nilai lebih dari nol adalah bukti deduplikasi berjalan, bukan otomatis data error. |
| Bucket used | Daily, Weekly, atau Monthly yang benar-benar digunakan. | Khusus pilihan Auto, field ini menjelaskan hasil resolusi bucket. |
| Algorithm | Versi formula yang menghasilkan output. | Digunakan untuk reproducibility dan audit. |

Exclusion reason dapat mencakup missing/unmapped MT, unmapped SPBU, invalid analytical keys, atau shipment tanpa observation yang eligible.

### Cara membaca grafik Phase 4

#### 1. MT Historical Probability

Horizontal bar chart ini menampilkan historical MT distribution untuk SPBU aktif.

- Sumbu Y berisi MT, diurutkan dari historical shipment count terbesar.
- Sumbu X berisi `P(MT|SPBU)` dalam persen.
- Bar pertama berwarna lime untuk menandai dominant historical MT; bar lain berwarna biru.
- Panjang bar menunjukkan seberapa sering MT tersebut digunakan relatif terhadap seluruh shipment SPBU.
- Hover menampilkan MT, MT Tag, shipment count, probability, first observed, dan last observed.
- Klik bar untuk memilih MT tersebut, memperbarui reverse detail dan evidence relationship.

Contoh:

```text
T01 = 54%, T02 = 24%, T03 = 11%

Artinya 54% historical shipment SPBU menggunakan T01.
Ini tidak berarti T01 direkomendasikan untuk shipment berikutnya.
```

#### 2. Historical MT Affinity Over Time

Line chart ini menunjukkan perubahan `P(MT|SPBU)` pada setiap temporal bucket.

- Sumbu X adalah period start sesuai Daily, Weekly, atau Monthly bucket.
- Sumbu Y adalah probability MT pada bucket tersebut, dari 0% sampai 100%.
- Setiap garis mewakili satu MT; chart membatasi garis pada MT utama agar tetap terbaca.
- Garis relatif datar menunjukkan probability MT yang stabil.
- Garis turun pada MT lama bersamaan dengan garis naik pada MT lain menunjukkan historical pattern shift.
- Pergantian garis tertinggi menunjukkan perubahan dominant MT.
- Karena hanya beberapa MT utama yang ditampilkan, garis yang terlihat tidak harus berjumlah 100%.

Jangan hanya melihat dominant line. Perubahan material pada seluruh distribution dapat terjadi walaupun dominant MT tetap sama.

#### 3. Recent vs Full-Period Pattern

Card perbandingan ini menampilkan dua ranked distributions:

- **Full selected period**: distribusi sepanjang date range yang dipilih.
- **Recent period**: distribusi hanya pada recent window 7, 14, atau 30 hari.

Cara membaca:

- Bandingkan urutan MT dan persentasenya pada kedua kolom.
- MT yang naik tajam di recent period menunjukkan peningkatan historical usage terbaru.
- MT yang dominan di full period tetapi turun di recent period dapat mengindikasikan pattern shift.
- Klik salah satu MT untuk membuka reverse view dan evidence.

Recent distribution ditampilkan apa adanya. Tidak ada hidden weighting yang memperbesar pengaruh observation terbaru.

#### 4. MT Reverse Historical Affinity

Horizontal bar chart ini membalik orientasi menjadi `MT → SPBU`.

- Header menampilkan MT aktif, historical shipment, unique SPBU, operating days, concentration, temporal stability, dominant-SPBU persistence, dan pattern-shift level.
- Sumbu Y berisi SPBU yang pernah dilayani MT.
- Sumbu X berisi `P(SPBU|MT)`.
- Bar panjang berarti SPBU tersebut muncul pada proporsi besar shipment MT aktif.
- Klik bar SPBU untuk menjadikannya SPBU aktif pada seluruh dashboard.

Satu shipment MT dapat melayani beberapa SPBU. Karena itu total `P(SPBU|MT)` seluruh SPBU dapat melebihi 100%; setiap probability memakai denominator distinct shipment MT, bukan total pair observation.

#### 5. SPBU Consistency Scatter Plot

Setiap titik mewakili satu SPBU.

Kontrol navigasi di kanan atas chart:

- ikon **kaca pembesar** memperbesar viewport secara bertahap; domain dan skala sumbu X/Y mengikuti kondisi zoom;
- ikon **tangan** mengaktifkan pan; drag area plot untuk menggeser viewport pada kondisi zoom;
- ikon **fit** mengembalikan viewport dan skala kedua sumbu ke posisi awal;
- pada mode tangan, scroll mouse/trackpad pada area plot juga dapat memperbesar atau memperkecil viewport.

- Sumbu X: **Unique MT Count**.
- Sumbu Y: **Consistency Score**.
- Ukuran titik: historical shipment count; titik besar mempunyai evidence shipment lebih banyak.
- Warna titik: biru untuk High Confidence, lime untuk Medium, dan merah untuk Low.
- Legend di bagian atas grafik menjelaskan ketiga warna confidence tersebut.

Cara membaca area plot:

- Kiri atas: sedikit MT dan assignment sangat terkonsentrasi.
- Kanan atas: banyak MT pernah digunakan, tetapi sebagian kecil MT tetap mendominasi.
- Kiri bawah: sedikit MT dengan distribution lebih seimbang.
- Kanan bawah: banyak MT dengan distribution tersebar; pola paling flexible.

Hover menampilkan SPBU, SPBU Tag, shipment count, unique MT, dominant MT dan probability, consistency, variability, stability, serta confidence. Klik titik untuk membuka SPBU profile dan popup persisten berisi nama, kode, SPBU Tag, serta confidence SPBU. Titik terpilih diberi border gelap; popup dapat ditutup dengan tombol `×`.

#### 6. Historical Pattern Matrix

Matrix ini memberi operational overview berdasarkan dua dimensi:

Matrix menyediakan kontrol kaca pembesar, tangan, dan fit yang sama dengan Scatter Plot. Zoom dan pan bekerja pada kedua sumbu, sedangkan fit mengembalikan domain `Unique MT` dan `Dominant Affinity` ke skala awal.

- Sumbu X: Unique MT Count.
- Sumbu Y: Dominant MT Affinity.
- Garis horizontal putus-putus: dominant affinity 60%.
- Garis vertikal putus-putus: median Unique MT Count dari SPBU yang lolos filter.

Empat quadrant dibaca sebagai berikut:

| Posisi | Label | Interpretasi historis |
|---|---|---|
| Kiri atas | DEDICATED-LIKE | Sedikit MT dan satu MT sangat dominan. |
| Kanan atas | PREFERRED-FLEET | Banyak MT pernah digunakan, tetapi dominant MT tetap kuat. |
| Kiri bawah | LIMITED BALANCED | Jumlah MT sedikit dan usage relatif terbagi. |
| Kanan bawah | HIGHLY FLEXIBLE | Banyak MT dan dominant affinity rendah. |

Warna titik mengikuti quadrant. Hover menampilkan SPBU, SPBU Tag, quadrant, unique MT, dominant affinity, dan shipment count. Klik titik untuk memilih SPBU.

Matrix adalah ringkasan dua dimensi. Historical Pattern pada profile juga mempertimbangkan consistency dan Top-3 share, sehingga label detail dapat memberi konteks tambahan.

Perbedaan utama kedua grafik:

| Grafik | Pertanyaan yang dijawab | Distribution yang dipakai |
|---|---|---|
| SPBU Consistency Scatter Plot | Seberapa terkonsentrasi penggunaan MT pada setiap SPBU dibanding jumlah MT yang pernah digunakan? | Seluruh probability distribution MT melalui normalized HHI. |
| Historical Pattern Matrix | Apakah SPBU lebih menyerupai dedicated, preferred-fleet, limited-balanced, atau highly-flexible? | Jumlah MT unik dan probability MT paling dominan. |

Dua SPBU dapat berada pada quadrant Matrix yang sama tetapi mempunyai Consistency Score berbeda. Matrix hanya memakai dominant affinity dan jumlah MT unik, sedangkan Scatter Plot memperhitungkan pembagian shipment kepada seluruh MT.

#### 7. Ranking cards

Tiga ranking bukan recommendation list; semuanya ranking descriptive historical behavior.

- **Most Historically Consistent SPBU** menjawab SPBU mana yang penggunaan MT-nya paling terkonsentrasi. Urutan dimulai dari Consistency Score tertinggi, lalu shipment terbanyak dan kode SPBU. Kolom Unique MT, Dominant %, dan Top-3 Share membantu membedakan concentration dengan ukuran fleet.
- **Most Historically Variable SPBU** menjawab SPBU mana yang shipment-nya paling merata tersebar ke berbagai MT. Urutan dimulai dari Variability Score atau normalized entropy tertinggi, lalu shipment terbanyak dan kode SPBU. Variability tinggi tidak otomatis berarti pola sering berubah antarperiode.
- **Highest Historical Pattern Change** menjawab SPBU mana yang distribusi MT-nya paling berubah antar-bucket waktu. Urutan dimulai dari Temporal Stability terendah, dilanjutkan Pattern Shift Distance terbesar dan shipment terbanyak. Previous MT, Recent MT, dan shift level menunjukkan arah serta besarnya perubahan dominant pattern.

Contoh pembeda:

- SPBU yang memakai banyak MT secara merata setiap minggu dapat mempunyai Variability tinggi tetapi Temporal Stability tetap tinggi karena pola pembagiannya konsisten.
- SPBU yang hanya memakai dua MT dapat mempunyai Pattern Change tinggi apabila dominant MT berganti tajam antara periode sebelumnya dan periode terbaru.

Klik nama/header kolom untuk mengubah sorting, gunakan Filter SPBU untuk menyaring ranking, dan klik row untuk membuka SPBU profile terkait. Selalu baca ranking bersama Shipment dan Confidence agar profile dengan evidence kecil tidak disamakan dengan profile ber-evidence kuat.

#### 8. Historical SPBU–MT Bipartite Network

Network menghubungkan dua jenis node:

- Node biru: SPBU.
- Node lime: MT.
- Border merah: node yang sedang dipilih.
- Edge: relationship historis SPBU–MT.
- Edge yang terkait node aktif dibuat lebih tebal dan lebih jelas.

Cara membaca:

- SPBU dengan banyak edge pernah dilayani oleh banyak MT.
- MT dengan banyak edge mempunyai historical service footprint ke banyak SPBU.
- Ketebalan edge menunjukkan historical shipment evidence. Pilihan Network Edge mengubah analytical edge value menjadi Shipment Count atau Affinity Probability, sedangkan tooltip tetap menampilkan kedua probability agar arah relationship dapat dibandingkan.
- Hover node SPBU menampilkan SPBU Tag; hover node MT menampilkan MT Tag.
- Hover edge menampilkan SPBU Tag, MT Tag, shipment count, `P(MT|SPBU)`, `P(SPBU|MT)`, first/last observed, operating days, dan confidence.
- Klik node SPBU untuk highlight seluruh MT yang pernah melayaninya.
- Klik node MT untuk membuka reverse service footprint MT tersebut.

Network dibatasi pada relationship teratas agar tetap usable. Gunakan probability chart, reverse chart, dan evidence table untuk audit angka detail.

#### 9. Historical Evidence Drill-Down

Card ini adalah audit table untuk relationship SPBU–MT aktif. Setiap row adalah shipment pembentuk relationship dan menampilkan:

- Date dan Shipment ID;
- Depot dan Gate Out;
- MT dan SPBU;
- Products dan Quantity;
- Other SPBU dalam shipment yang sama.

Jumlah `distinct shipments` pada header harus sama dengan shipment count relationship aktif. Jika satu shipment mempunyai beberapa LO atau produk, detail dapat memuat beberapa product tetapi relationship tetap dihitung satu observation.

#### 10. Methodology & Guardrails

Card terakhir merangkum formula aktif untuk Consistency, Variability, Temporal Stability, dan Confidence beserta algorithm version. Gunakan card ini untuk memastikan interpretasi score konsisten saat membandingkan export, API response, atau periode analisis berbeda.

Aturan interpretasi utama Phase 4:

```text
Affinity menjawab: MT mana yang historically melayani SPBU dan seberapa sering?
Stability menjawab: apakah distribution tersebut bertahan dari waktu ke waktu?
Confidence menjawab: seberapa kuat evidence yang mendukung kedua pembacaan tersebut?
```

Ketiga konsep tersebut tidak boleh dicampur. Historical affinity tinggi tidak membuktikan future suitability, dan confidence tinggi tidak menjadikan pola sebagai rekomendasi assignment.

Operational Shift Intelligence di Phase 2:

- konfigurasi shift operasional per depot melalui Add/Remove Shift, start/end time, Save, dan Load
- validasi konfigurasi shift: format waktu valid, nama tidak duplikat, tidak overlap, dan menutup 24 jam penuh
- tiga metode assignment: Dominant Shift, Median-Based, dan Hybrid / Confidence-Aware
- Operational Shift Summary interaktif: klik shift/status untuk memfilter tabel SPBU Departure Profiles
- Confidence Mix interaktif: klik HIGH/MEDIUM/LOW untuk memfilter tabel profile
- tabel SPBU Departure Profiles menggabungkan profile departure dan shift assignment dalam satu tabel paginated
- SPBU Shift Affinity Heatmap menampilkan SPBU current page yang sama dengan tabel dan box plot
- warna heatmap memakai skala kontras berdasarkan `Shift Affinity %`, bukan jumlah observasi
- box plot memiliki legend dinamis untuk pilihan highlight Primary Historical Shift, Assignment Status, atau Confidence

Operational Shift Intelligence tetap berbasis perilaku historis. Output ini tidak memaksa jadwal dispatch masa depan dan tidak melakukan multi-feature SPBU clustering; advanced clustering tetap menjadi tanggung jawab fase lanjutan.

Catatan scope: fondasi Phase 0 tetap menjadi dasar data utama dan Phase 2 tetap read-only historical intelligence. Prediction/availability Phase 6 dan dynamic route/bay optimization Phase 7 sudah tersedia sebagai modul terpisah; GPS-confirmed arrival/visit dan actual stop reconstruction tetap menunggu evidence GPS yang tervalidasi.

Import workflow: create the depot in Master Data, then select the active depot
in the top bar, immediately left of Google Maps Settings. MT, SPBU, and
Historikal Shipment uploads use that depot automatically; templates no longer
contain depot IDs or names. The queued job captures the selected depot so
switching depot later cannot redirect an upload. Dashboard, master records,
exports, and analysis pages follow the active depot.

Canonical columns and historical RTH rules are described in
[Source Data Mapping](docs/SOURCE_DATA_MAPPING.md). RTH is Shipment End minus
Gate Out; the median of distinct single-SPBU shipments becomes master RTH.
Master travel time is half this duration as a one-way estimate, including
service/waiting time. No valid history means NULL and zero samples. Import,
CRUD edits, and deletion recalculate these values. Existing model/route
snapshots remain auditable; rebuild analysis or create a new run to use new data.
Legacy database fields remain compatibility mirrors, while templates, forms,
and exports expose the consolidated inputs. Migration 0031 consolidates existing
masters and calculates RTH from stored history; back up the database before upgrade.

## Local Tests

```bash
cd apps/api
python -m pip install -r requirements.txt
pytest
```

Jika menggunakan container:

```bash
docker compose exec -T api pytest
```

## Architecture Status

Implemented stack:

- PostgreSQL/PostGIS
- FastAPI
- SQLAlchemy 2.x
- Alembic
- React/Vite
- TypeScript
- Tailwind CSS
- Apache ECharts
- Google OR-Tools Routing Solver dan CP-SAT
- Docker Compose

Monorepo layout:

- `apps/api`: backend API, importer, models, tests
- `apps/web`: frontend dashboard dan master-data UI
- `db/migrations`: Alembic migrations
- `docs`: architecture, data model, phase status, source mapping, future integrations
- `example data`: source workbook Phase 0

Phase 2 departure intelligence details are documented in `docs/PHASE_2_DEPOT_DEPARTURE_INTELLIGENCE.md`.
Phase 3 pairing intelligence implementation is summarized in `PHASE_3_COMPLETION_REPORT.md`.
Phase 4 methodology is documented in `docs/PHASE_4_SPBU_MT_AFFINITY.md`, with implementation status in `PHASE_4_COMPLETION_REPORT.md`.
Phase 7 architecture, workflow, hard/soft constraints, API, schema, dan operasi dispatcher didokumentasikan di `docs/PHASE_7_DYNAMIC_VRP.md`.

Phase 8 snapshot boundary, MT–Trip–LO editing, eligibility, Apply, route legs, multi-trip availability, cascading recalculation, simulation KL/Gantt, daily dashboard, versioning, audit, dan finalization didokumentasikan di `docs/PHASE_8_MANUAL_DISPATCH.md`.

Phase 9 Source-Aligned Bundle, empat metric alignment terpisah, evidence coverage, persistence, API, dashboard, tabel LO, dan aturan interpretasi netral didokumentasikan di `docs/PHASE_9_ROUTE_MODEL_ALIGNMENT.md`.

## Phase Roadmap

### Phase 0: Master Data Strengthening and Operational Data Foundation

Tujuan:

- membangun canonical master data dan operational fact foundation
- memisahkan source instruction dari observed operational evidence
- membuat import pipeline yang auditable
- membuat data-quality issue tracking
- membuat CRUD dan export/import foundation untuk data master dan operational data
- menyiapkan struktur data yang nanti dapat dipakai oleh fase analitik, tanpa menjalankan analisa relasi sebagai fitur aktif

Scope data:

- Mobil Tangki
- SPBU
- Depot
- Product
- Tags dan tag aliases
- Loading Order
- Shipment
- Shipment-SPBU membership sebagai data foundation dari source Loading Order, bukan analisa relasi
- GPS staging foundation
- SPBU visit model foundation
- actual stop sequence foundation
- data quality
- master compatibility placeholder untuk fase lanjutan

Status saat ini: `IN PROGRESS`.

Progress yang sudah dibuat:

- Docker Compose untuk PostGIS, FastAPI, dan web frontend.
- Alembic schema untuk staging, canonical masters, loading-order facts, shipment facts, GPS foundation, geofence, visits, stop sequence, dan data-quality tables.
- Import sample untuk:
  - `master data MT.xlsx`: 162 rows
  - `master data spbu.xlsx`: 583 rows
  - `masterdata_LO.xlsx`: 4,462 rows, 1,876 grouped shipments
- Upload import file lokal `.xlsx` atau `.csv`. Template MT, SPBU, dan Historikal Shipment mengikuti depot aktif di top bar tanpa kolom depot.
- Upload disimpan sebagai durable background job (`QUEUED` → `PROCESSING` → `PUBLISHED`/`FAILED`) agar file besar tidak menahan request API. Status import tetap dipantau setelah browser di-refresh dan tabel UI otomatis dimuat ulang ketika job selesai.
- Export template.
- Export data per depot.
- Import audit dan import history.
- RAW -> STAGING -> VALIDATION -> NORMALIZATION -> PUBLISH -> CANONICAL flow.
- Canonical master MT dengan registration normalization.
- Canonical master SPBU memakai `latitude` dan `longitude`; coordinate gabungan hanya diterima sebagai alias file lama. Waktu master dihitung otomatis dari historikal shipment.
- Canonical depot dari source alias.
- Product bootstrap dari Loading Order.
- Tag splitting, tag master, tag type, MT tag bridge, SPBU tag bridge.
- Tag Vehicle Class pada MT/SPBU disimpan sebagai integer dan ditampilkan sebagai kolom `TAG VEHICLE CLASS`.
- Loading Order grouping menjadi shipment header dan loading-order lines.
- ID canonical depot-scoped dibentuk dari `depot_id + vehicle_registration` untuk MT, `depot_id + spbu_code` untuk SPBU, dan `depot_id + loading_order_number` untuk LO. Nomor/kode yang sama boleh digunakan di depot berbeda tetapi tidak boleh duplikat di depot yang sama.
- Shipment-SPBU membership.
- Driver/kernet preservation.
- Mapping status untuk MT/SPBU masih bersifat internal import diagnostic dan tidak ditampilkan sebagai analisa relasi pada CRUD Phase 0.
- Data-quality issues persisted.
- Compatibility/reconciliation endpoint masih placeholder atau foundation, belum menjadi fitur analitik aktif.
- Dashboard filter by depot.
- Phase 0 KPI cards dan chart categories.
- Master Data CRUD untuk MT, SPBU, Loading Order, Depot, Product, Tag, dan Tag Type.
- CRUD supports add, view, update, soft delete, column search, sort, status filter, depot filter, pagination, select all, select per row, dan multi-row add/edit/delete.
- Deleted master data disembunyikan dari list aktif dan unique key dapat dipakai kembali setelah soft-delete karena create path mereaktivasi record yang sudah deleted.
- Sync master Depot/Product/Tag hanya membaca source aktif: active MT, active SPBU, dan active Loading Order. Data yang sudah `DELETED` tidak dipakai sebagai candidate sync.
- Sync dapat mereaktivasi master Depot/Product/Tag yang deleted bila nilai tersebut masih direferensikan oleh source aktif.
- Frontend theme sudah diselaraskan dengan `vrp_planner` menggunakan palet Petrofin untuk background, header, navigation, panel, focus state, dan chart.
- Phase 6 inference, global MT assignment, audit/override/history/export API dan UI tersedia sebagai extension modular.

Progress validasi:

- Container stack healthy.
- Relevant API/import/normalization tests passing: `18 passed`.
- Frontend build passing.
- Browser smoke tests passing untuk dashboard, master-data page, CRUD pagination, select all, dan All records.
- API container rebuilt dan healthy setelah update sync dan SPBU coordinate backfill.
- Web container rebuilt dan healthy setelah update tema Petrofin dan kolom coordinate SPBU.

Belum selesai:

- Real GPS mapping menunggu file/source schema `GPS_data`.
- GPS visit detection belum tervalidasi dengan GPS real atau synthetic acceptance fixture.
- LO vs GPS reconciliation belum real.
- Actual stop sequence masih placeholder karena belum ada GPS evidence.
- Phase 0 belum boleh ditutup sampai GPS staging/visit/reconstruction divalidasi.

Ready for Phase 1: `NO`.

### Phase 1: Historical Tag Intelligence

Tujuan:

- membandingkan master compatibility dengan actual historical MT-SPBU relationship
- mendeteksi anomaly ketika master data tidak sesuai historical evidence
- menghasilkan recommendation workflow tanpa otomatis mengubah master data

Target output:

- `fact_mt_spbu_observation`
- anomaly classification: green/yellow/red-review
- tag change recommendation workflow
- Historical Tag Intelligence Dashboard
- drill-down evidence dari Loading Order dan GPS-confirmed shipment activity

Status saat ini: `NOT STARTED`.

Gating:

- menunggu Phase 0 selesai dan GPS/operational foundation usable.

### Phase 2: Depot Departure Time Intelligence

Tujuan:

- membangun historical Depot Departure Profile untuk setiap SPBU berdasarkan waktu keberangkatan Mobil Tangki dari depot
- menjaga source lineage antara LO gate-out dan GPS actual depot exit
- menghitung pola historis keberangkatan secara circular-time aware, termasuk distribusi yang melewati midnight

Target output:

- departure distribution per SPBU
- P20, P25/Q1, P50, P75/Q3, P80, P90, P95
- peak departure bucket dengan midpoint sebagai `peak_departure_time`
- Preferred Historical Departure Window berbasis P20-P80 circular-time
- weekday/weekend segmentation
- product/depot/vehicle type segmentation jika berguna
- source coverage dan GPS-vs-LO difference sebagai metrik kualitas data
- SPBU Departure Profile Explorer

Status saat ini: `IMPLEMENTED AS READ-ONLY DERIVED API/UI`.

Progress yang sudah dibuat:

- API `GET /api/v1/departure-intelligence/analysis` dengan pagination, sorting, confidence filter, dan filter daftar SPBU.
- API `GET /api/v1/departure-intelligence/available-dates` untuk date availability.
- API `POST /api/v1/departure-intelligence/shift-analysis` untuk Operational Shift Intelligence.
- Circular-time percentile profile: P20, P25/Q1, P50, P75/Q3, P80, P90, P95, IQR, outlier count, dan Preferred Historical Departure Window.
- Box plot current table page dengan optional highlight by Primary Historical Shift, Assignment Status, atau Confidence.
- Operational shift configuration UI dengan validation, save/load per depot, dan help popup.
- Operational Shift Summary, Shift Affinity Heatmap, dan shift assignment fields digabung ke SPBU Departure Profiles.
- Interactive filter dari Confidence Mix dan Operational Shift Summary ke tabel, box plot, dan heatmap.
- Source Lineage explorer dengan sample observasi per visible SPBU profile.

Gating:

- menggunakan canonical shipment foundation dari Phase 0; GPS depot-exit akan dipakai bila `fact_gps_event.event_type` tersedia sebagai depot-exit event reliabel.

### Phase 3: SPBU Pairing and Directed Edge Intelligence

Tujuan:

- menganalisis SPBU yang sering berada dalam shipment yang sama
- menganalisis actual directed transition dari GPS-confirmed stop sequence
- menghitung actual inter-SPBU travel time

Target output:

- `fact_spbu_pair`
- support, confidence, lift, P(B|A), P(A|B)
- `fact_spbu_edge`
- average/median/P80/P90/P95 travel time
- time-dependent edge profile
- Pairing Intelligence Dashboard
- network prototype

Status saat ini: `NOT STARTED`.

Gating:

- membutuhkan shipment membership dan GPS-confirmed sequence.

### Phase 4: SPBU–MT Historical Affinity & Stability Intelligence

Tujuan:

- mengukur historical affinity `P(MT|SPBU)` dan reverse footprint `P(SPBU|MT)`
- mengukur concentration, variability, evidence confidence, dan temporal stability secara terpisah
- mendeteksi historical distribution shift tanpa memberi causal explanation
- menyediakan Fleet Affinity Vector untuk feature Phase 5

Target output:

- `fact_spbu_mt_pair`
- `fact_spbu_mt_profile`
- `fact_spbu_mt_temporal_profile`
- API `/api/v1/affinity-intelligence/analysis`
- UI `/affinity-intelligence`
- algorithm `spbu_mt_affinity.jsd_v1`

Status saat ini: `COMPLETE`.

Gating:

- acceptance tests, UI build, documentation, dan visual validation harus tetap lulus sebelum Phase 5.

### Phase 5 — Machine Learning Intelligence

Status saat ini: `IMPLEMENTED`.

Tujuan Phase 5 adalah historical pattern discovery dan reusable behavioral clustering. Phase ini tidak melakukan route optimization, tidak merekomendasikan MT untuk assignment berikutnya, tidak menilai dispatcher salah, dan tidak mengubah master data.

Readiness gate:

- scope selalu satu `depot_id`; data antardepot tidak pernah dicampur
- readiness memakai observed Loading Order assignments pada latest available Phase 1 scope dan rule source `app.tag_consistency.evaluate_mt_spbu_tags`
- execution hanya diizinkan jika setidaknya satu assignment dievaluasi dan seluruh assignment tersebut `MATCH`; mismatch maupun data issue akan memblokir execution
- active MT × active SPBU matrix tetap dihitung saat Engine A memerlukan compatible-fleet opportunity, tetapi pasangan yang tidak eligible adalah expected exclusions dan tidak mengurangi readiness
- Vehicle Class pada matrix Engine A mengikuti rule Phase 1 `MT capacity <= SPBU maximum`
- gate tidak dapat dibypass melalui UI maupun API

Engine A — Historical MT–SPBU Concentration Anomaly:

- memakai istilah **Baseline Period**, bukan training period
- tidak memakai train/test split
- memakai canonical observation unik `depot_id + shipment_id + spbu_id + mt_id` dari Phase 4; repeated LO, product, atau compartment line tidak menambah count
- menghitung compatible MT count, historically used compatible MT count, utilization breadth, dominant MT/share, HHI, Shannon entropy, normalized entropy, dan shipment observation count
- SPBU di bawah minimum observation disimpan sebagai `INSUFFICIENT_DATA` dan tidak ikut model scoring
- fitur cukup-data distandardisasi lalu dianalisis dengan Isolation Forest
- raw severity adalah negatif `IsolationForest.score_samples`; 0–100 score memakai deterministic within-run min-max transform. Run dengan semua raw score sama mendapat score 0 karena model tidak menemukan relative anomaly evidence
- peer statistics memakai deterministic log2 band dari compatible fleet count
- hasil tersimpan pada `ml_concentration_analysis_run` dan `ml_spbu_concentration_profile`, dapat dibuka kembali tanpa recompute
- Engine A mendeteksi unusual historical concentration, bukan future assignment deviation

Engine B — SPBU Behavioral Clustering:

- memakai workflow `Prepare Dataset → Validate → Configure → Train → Review → Save`
- menilai setiap SPBU aktif dengan deterministic **Data Sufficiency Score 0–100** dari shipment count, operating days, training-period coverage, shift coverage, pairing evidence, dan recency. Ambang default terpusat adalah `SUFFICIENT >= 80`, `MARGINAL >= 50`, dan `INSUFFICIENT < 50`; konfigurasi serta component weights disnapshot bersama model
- hanya `SUFFICIENT` yang membentuk scaler, UMAP geometry, dan HDBSCAN core boundary. `SUFFICIENT` tidak otomatis menjadi anggota cluster karena HDBSCAN tetap boleh menghasilkan `CORE_NOISE`
- `MARGINAL` tidak ikut fit. Sesudah core training, fitted UMAP mentransform marginal record dan implementasi `sklearn.cluster.HDBSCAN` memakai fallback terdokumentasi **nearest core centroid in UMAP space**. Hanya confidence di atas ambang yang menjadi `MARGINAL_PROJECTED`; sisanya `MARGINAL_UNASSIGNED`
- `INSUFFICIENT` selalu `INSUFFICIENT_UNASSIGNED`: tidak mempunyai cluster ID, membership probability, atau UMAP marker. **INSUFFICIENT bukan noise**, dan **marginal projection bukan core membership**
- tag features mempertahankan tag-type boundary melalui typed multi-hot encoding; Vehicle Class disimpan sebagai feature ordinal
- shift feature memakai seluruh historical shift distribution dan menyimpan exact shift-definition snapshot pada training run/model
- Phase 3 same-shipment relationship dibentuk sebagai weighted graph; edge weight adalah mean dari dua directional conditional probabilities
- pairing graph diubah menjadi embedding dengan Node2Vec memakai seed dan single worker; isolated nodes menerima zero pairing vector, dan graph tanpa edge menghasilkan zero vector untuk seluruh node
- Geographic Proximity adalah feature group keempat. Koordinat canonical Master SPBU divalidasi sebagai `VALID`, `MISSING`, atau `INVALID`; `(0,0)`, out-of-range, null, dan duplicate-coordinate condition ditangani eksplisit. Haversine membentuk nearest distance, average/median K-nearest distance, serta local density. Missing/invalid coordinate memakai median core-training feature plus missing indicator, bukan silent zero
- feature group Tag, Shift, Pairing, dan Geographic distandardisasi sendiri-sendiri, dikalikan `sqrt(weight / group_dimension)`, lalu digabung. Default weight adalah **30% / 20% / 30% / 20%**; geography dapat dimatikan dengan weight 0 dan remaining weights tervalidasi berjumlah 1
- pipeline utama adalah **Node2Vec + UMAP + HDBSCAN**. HDBSCAN noise tetap noise dan ditampilkan sebagai `Noise / Unique Behavioral Pattern`
- pairing graph, shift distribution, geographic representation, dan shipment evidence selalu dibangun ulang dari canonical history/master snapshot pada training period. Pairing graph dapat membawa `MARGINAL` agar dapat ditransform, tetapi hanya `SUFFICIENT` yang menentukan cluster
- training result harus direview sebelum diberi nama dan disimpan; training tidak otomatis membuat registry model atau mengaktifkannya
- saved model untuk depot aktif dapat dipilih dan dibuka langsung dari workspace Behavioral Clustering tanpa prepare dataset atau retraining; UMAP, Geographic Cluster Map, profiles, dan paginated membership memakai assignment model yang tersimpan
- saved package berisi encoder/configuration, scaler metadata, Node2Vec embeddings, internal/visualization UMAP model, HDBSCAN model, vectors, assignments, profiles, dependency versions, manifest, dan checksum
- binary package berada pada persistent `ML_ARTIFACT_DIR`; relational table hanya menyimpan artifact metadata/path/checksum

Arsitektur Engine B:

```text
MASTER COMPATIBILITY → 100% PASS → DATA SUFFICIENCY
                                      ├─ SUFFICIENT → TAG + SHIFT + PAIRING + GEOGRAPHY → UMAP → HDBSCAN → CORE / CORE NOISE
                                      ├─ MARGINAL ─────────────────────────────────────→ POST-TRAINING PROJECTION / UNASSIGNED
                                      └─ INSUFFICIENT ──────────────────────────────────→ NOT ASSIGNED
```

> Geographic Proximity in Phase 5 is a clustering feature only.

Geographic Proximity memakai koordinat SPBU dan Haversine. Ini bukan road distance, large-vehicle route feasibility, travel time, traffic, atau route optimization; kebutuhan tersebut tetap berada pada phase routing/optimization berikutnya.

Model lifecycle:

- status: `SAVED`, `ACTIVE`, `ARCHIVED`
- hanya satu model `ACTIVE` per depot; aktivasi menurunkan model aktif lama menjadi `SAVED`
- retraining tidak overwrite version lama; nama yang sama pada depot yang sama menghasilkan `v1`, `v2`, dan seterusnya
- Duplicate hanya menyalin configuration ke training draft baru, bukan trained artifact
- Compare mengabaikan arbitrary HDBSCAN cluster IDs. Core cluster antar-model dipasangkan berdasarkan Jaccard/Hungarian, sedangkan perubahan kematangan data (`INSUFFICIENT → MARGINAL`, `MARGINAL → SUFFICIENT`, dan arah lain) dilaporkan terpisah
- active-model API menyediakan version, period, assignments, membership probability, dan cluster profiles untuk phase berikutnya

Local ML setup di luar Docker:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r apps/api/requirements.txt
export PYTHONPATH="$PWD/apps/api"
export ML_ARTIFACT_DIR="$PWD/ml_artifacts"
```

Dependency penting dipin pada `apps/api/requirements.txt`: NumPy, SciPy, scikit-learn (termasuk HDBSCAN dan Truncated SVD), umap-learn, NetworkX, dan joblib. Engine B menjalankan Node2Vec biased walks sendiri lalu PPMI/SVD, sehingga tidak bergantung pada ekstensi native Gensim yang dapat memicu `Illegal instruction` pada ARM64. Image API juga memakai profil CPU generik Numba untuk jalur UMAP/PyNNDescent. Docker Compose membuat named volume `ml_artifacts` sehingga package model tetap ada setelah API container direstart.

Detail teknis lengkap: `docs/PHASE_5_MACHINE_LEARNING_INTELLIGENCE.md`.

### Phase 6 — Time-Aware Multi-Trip Prediction & Assignment

Status saat ini: `IMPLEMENTED`.

Phase 6 adalah inference, assignment, dan estimasi availability—bukan training dan bukan fleet route optimization. Satu run menggabungkan saved Phase 5 model, Loading Order bertimestamp, initial MT availability, master compatibility, dan estimasi perjalanan untuk menghasilkan trip plan auditable yang dapat menjadi input Phase 7.

Detail teknis dan panduan operasional lengkap: `docs/PHASE_6_PREDICTION_ASSIGNMENT.md`.

Input workbook:

- Loading Order: `loading_order_no`, `shipment_start_datetime`, `spbu_no`, `product`, dan `order_quantity_kl`; setiap LO wajib tepat 8 KL. Nilai product dipetakan ke `master_product`/alias canonical dan disimpan pada snapshot line prediction
- MT Availability internal: `vehicle_registration_no`, `initial_available_datetime`; user tidak lagi mengunggah workbook MT manual
- template Loading Order dapat diunduh dari page atau API; `.xlsx` dibatasi 10 MB
- card **Loading Order Upload** menyediakan **Data Demo**: user wajib memilih tanggal Loading Order dan memasukkan total order kelipatan 8 KL. Sistem membuat satu LO 8 KL per unit order pada tanggal pilihan, lalu hanya memilih SPBU aktif non-noise dengan `history_eligible=true` dan `coverage_source=BEHAVIORAL_HISTORY` pada saved model yang dipilih. Jam LO dibentuk dari shift snapshot model dalam batch cluster/dominant-shift bertimestamp berdekatan agar demo dapat menguji multi-SPBU. SPBU cold-start, inactive, noise, dan unseen tidak digunakan; input dengan sisa di bawah 8 KL ditolak
- setelah file manual atau Data Demo LO tervalidasi, card **Loading Order Management** membuka seluruh row input—termasuk Product—untuk Add, Edit, dan Delete. Form Add/Edit memakai dropdown SPBU aktif dari Master SPBU pada depot terpilih dan dropdown Product aktif dari Master Product, bukan free text. Setiap header data memiliki filter dan sort, tabel dipaginasi, dan setiap perubahan membentuk ulang workbook aktif lalu menjalankan validator backend yang sama; hasil tabel inilah yang dikirim saat **Run Prediction**
- card **MT Availability** hanya menyediakan **Import Data from Master Data**. Tombol ini mengambil seluruh MT canonical aktif pada depot terpilih dan membuka **MT Management** dengan kolom No MT, MT Tag Class, Status, dan ETA on Depot. Tidak tersedia Add/Delete; status Active/Deactive adalah state operasional run dan tidak menulis balik ke Master MT
- Pada **4A. MT Management**, tombol **Bulk Action** di samping header Status dan ETA on Depot menerapkan status Active/Deactive atau tanggal/jam ETA serentak pada MT yang dicentang atau seluruh hasil pencarian lintas halaman. Pilihan MT bertahan saat berpindah halaman; checkbox header memilih semua hasil pencarian. Setiap bulk action menyusun ulang workbook MT availability dan menjalankan validator prediction yang sama dengan edit per baris.
- seluruh MT hasil import mendapat ETA pada tanggal operasi dan jam awal Shift 1 dari snapshot model. MT dengan profil kapasitas 8 KL yang valid default Active; MT canonical aktif yang profil kapasitasnya tidak valid tetap ditampilkan tetapi default Deactive beserta alasannya. User dapat mengubah status atau ETA; hanya row Active yang dibentuk menjadi workbook internal, divalidasi backend, dan dikirim saat **Run Prediction**. ETA on Depot berarti waktu MT mulai available di depot
- workbook internal hasil management langsung dipasang sebagai input aktif dan melewati validator yang sama; nomor MT, kapasitas, status operasional, dan timestamp ikut dipertahankan untuk audit
- timestamp tanpa offset dibaca memakai timezone depot; normalized snapshot disimpan dalam UTC dan local time
- shift bukan input utama: shift diturunkan dari `shipment_start_datetime` menggunakan exact full-day shift-definition snapshot model Phase 5/Phase 2
- LO divalidasi terhadap planning horizon; MT harus unik, aktif, ada di master, dan berada pada depot run

Prediction flow:

```text
Phase 5 Saved Model
        +
Loading Order
        +
Initial MT Availability
        ↓
Iterative Capacity Grouping + Assignment
32 KL (4 LO) → 24 KL (3 LO) → 16 KL (2 LO) → 8 KL (1 LO)
        ↓
Phase 4 MT Candidate Score
        ↓
Phase 1 Master Compatibility Hard Filter
        +
8 KL Compartment Capacity Sufficiency Hard Filter
        ↓
Rolling Capacity-Tier + Chronological MT Assignment
        ↓
Google Routes / Cache / Historical Estimate
        ↓
Return + Next Availability Update
        ↺ MT may be reused for a later trip
        ↓
Final Dispatch Prediction
        ↓
Phase 7 Input
```

Shipment inference memakai immutable Phase 5 artifact/normalized model registry: cluster membership probability, same-cluster evidence, model feature weights, derived-shift match, dan saved historical pairing strength. Grouping hanya dipertimbangkan dalam derived shift yang sama dan dalam `maximum_pairing_time_gap_minutes`; default window adalah 90 menit dan tetap configurable dari UI. Default minimum pairing confidence adalah 0,40 agar sufficient-history pair dapat terbentuk tanpa otomatis meloloskan cold-start coverage yang confidence-nya sengaja dibatasi. `planned_start_datetime` adalah timestamp LO paling akhir dalam shipment. Algoritma `CAPACITY_TIME_ROUTE_SET_PACKING` membangun connected candidate group melalui binary MILP set packing (dengan deterministic greedy fallback), menggunakan group model score, time span, 8 KL compartment capacity, pair-evidence coverage, approximate route feasibility, dan operational MT feasibility. Set-packing pada setiap tier hanya memilih grup dengan jumlah LO tepat 4/3/2 serta sedikitnya satu MT berkapasitas sama yang lulus intersection master tag seluruh SPBU dan rolling availability window; grup yang tidak dapat dijalankan tidak menghalangi kombinasi LO alternatif pada tier yang sama.

Orkestrasi `phase6.iterative_exact_capacity_assignment.v11` menjalankan grouping dan MT assignment secara bertingkat: 32 KL/4 LO, 24 KL/3 LO, 16 KL/2 LO, lalu 8 KL/1 LO. Hanya grup yang berhasil mendapat status `ASSIGNED` atau `ASSIGNED_WITH_DELAY` yang mengonsumsi LO. Jika grup besar tidak memiliki MT berkapasitas sama yang available dan compatible, grup tersebut dibubarkan dan LO-nya diprediksi ulang pada tier berikutnya. Di setiap tier, multi-LO tetap wajib memenuhi evidence cluster/shift/time/rute Fase 5, sedangkan candidate MT wajib lulus vehicle type, project tag, depot, dan kapasitas untuk seluruh SPBU. Tidak ada partial-load fallback: shipment 32/24/16/8 KL masing-masing hanya dapat memakai MT 32/24/16/8 KL. Dengan demikian optimizer menyesuaikan komposisi shipment terhadap armada aktual tanpa menjalankan MT yang kompartemennya tidak terisi penuh.

MT ranking memakai Phase 4 historical `P(MT|SPBU)` dengan deterministic Laplace smoothing. Historical affinity hanya score/ranking; rule Phase 1 dari `app.compatibility.evaluate_compatibility_entities` tetap hard filter terpisah. Untuk multi-SPBU shipment, MT harus lulus rule untuk seluruh SPBU (intersection). Capacity profile dihitung dari master `capacity_label`/`vehicle_type_tag` dan `number_of_compartments`; setiap kompartemen bernilai 8 KL. Policy `EXACT_COMPARTMENT_MATCH` mewajibkan `jumlah LO = jumlah kompartemen MT`, sehingga seluruh kapasitas MT selalu terisi sebelum trip dijalankan. Candidate berbeda kapasitas disimpan sebagai diagnostic `CAPACITY_COMPARTMENT_MISMATCH`; candidate yang gagal master/tag compatibility disimpan sebagai `MASTER_COMPATIBILITY_FAIL`. Compartment count kosong dapat diinfer dari kapasitas dengan warning, tetapi data master yang saling bertentangan menjadi validation error.

Assignment otomatis diproses berdasarkan tier kapasitas 32→24→16→8 KL, lalu ascending `planned_start_datetime` di dalam setiap tier. State awal tiap MT adalah `initial_available_datetime`; setelah trip dipilih, sistem menghitung return dan `next_available_datetime`. MT yang sama dapat mendapat Trip 1, 2, 3, dan seterusnya selama `previous.next_available <= next.predicted_departure`. Recalculation setelah manual assignment/grouping menggunakan urutan tier yang sama. Mode:

- `STRICT_START`: MT harus available pada planned start
- `ALLOW_DELAY`: departure boleh bergeser sampai `maximum_allowed_delay_minutes`, dengan status `ASSIGNED_WITH_DELAY`

Unassigned reason meliputi `NO_MT_AVAILABLE_AT_REQUIRED_TIME`, `NO_COMPATIBLE_MT`, `LOW_PREDICTION_CONFIDENCE`, dan `ROUTING_ESTIMATE_FAILED`.

#### Google Maps Routes Integration

Semua request Google berlangsung server-side melalui Compute Routes atau Compute Route Matrix client. API key:

- disimpan encrypted-at-rest memakai `GOOGLE_ROUTES_ENCRYPTION_KEY` dari environment
- tidak pernah dikembalikan penuh, disimpan di localStorage, dicatat dalam log, snapshot run, atau export
- dikelola melalui `/settings/google-maps-integration` dengan Save/Replace/Delete/Test Connection

Phase 6 Indonesia menggunakan mode `DRIVE` secara tetap. Dukungan `TRUCK`/Large Vehicle Routing dimatikan karena belum tersedia untuk wilayah operasi Indonesia. Backend menolak mode selain DRIVE, test connection hanya memeriksa Compute Routes dan Compute Route Matrix, dan UI tidak menyediakan kontrol maupun profile large-vehicle. Jika Google Routes tidak tersedia, sistem tetap menggunakan historical route, cluster median, atau configured default dengan warning `ROUTE_FALLBACK` yang terlihat.

Route cache memisahkan origin, destination, departure bucket, routing preference, routing mode, configuration version, dan vehicle-profile hash. Estimasi fallback tidak menjadikan Google single point of failure:

```text
valid route cache / Google Routes
→ historical SPBU route
→ cluster historical median
→ configured default
```

Di dalam setiap shipment, Phase 6 mengurutkan SPBU secara deterministik berdasarkan jarak radial dari depot: SPBU terdekat lebih dahulu dan SPBU terjauh terakhir. Urutan `depot → SPBU terdekat → ... → SPBU terjauh → depot` digunakan oleh `estimated_visit_sequence`, estimasi cycle time, dan geographic route map. Ini preliminary operational sequence, bukan fleet-wide optimized route.

Formula implementasi:

```text
total_cycle_duration
= depot processing
+ total travel legs (depot → SPBU... → depot)
+ SPBU service per stop
+ return processing

estimated_return = predicted_departure + total_cycle_duration
next_available = estimated_return + turnaround buffer
```

Turnaround buffer disimpan terpisah dan tidak dihitung dua kali dalam `total_cycle_duration`.

Dispatcher dapat:

- mengganti MT hanya ke candidate yang lulus historical/master compatibility dan mempunyai kompartemen cukup; route dan timeline downstream dihitung ulang dalam mode DRIVE
- move LO/SPBU ke shipment same-shift, membuat shipment baru/single, atau combine same-shift shipment tanpa melewati batas kompartemen
- melihat nomor cluster model aktif di samping setiap nomor SPBU; pilihan `Move to…` menampilkan shipment ID beserta daftar nomor SPBU dan cluster target
- menelusuri **Prediction Run History** dengan pagination client-side 10/25/50 baris, indikator rentang, dan navigasi halaman tanpa mengubah immutable run data
- memicu ulang candidate scoring, compatibility filter, rolling state, route duration, return, dan affected future availability tanpa training ulang
- memicu kalkulasi ulang multi-trip MT, total assigned KL, distribusi KL per jam, cumulative distribution, dan geographic MT route pada setiap manual assignment atau perubahan grouping shipment
- membandingkan immutable `original_model_prediction` dengan `final_dispatch_prediction`

Persistence migration `0010_phase6_prediction` menambah prediction core; `0011_phase6_demo_lo` menambah audit quantity KL; `0012_phase6_multitrip` menambah timestamp planning, `prediction_trip`, encrypted Google configuration, route cache, routing metrics, serta original/final snapshots. Migration `0013_phase6_drive_only` menormalisasi konfigurasi dan seluruh status profile MT ke mode DRIVE/NOT_REQUIRED. Migration `0014_phase6_worker` menambah durable PostgreSQL job queue, worker lease, heartbeat, attempt count, dan recovery metadata. Migration `0015_phase6_road_geometry` menyimpan Google Routes overview GeoJSON per trip agar map mengikuti jalan tanpa membebani payload dengan navigation-step resolution. Prediction run snapshot menyimpan model/config version, traffic/cycle parameters, tetapi tidak menyimpan raw API key.

Run Prediction diproses secara asynchronous oleh service Docker `phase6-worker`, terpisah dari proses FastAPI. `POST /api/v1/phase6/predictions` hanya memvalidasi input, menyimpan snapshot serta row `prediction_job`, membuat run berstatus `QUEUED`, lalu langsung mengembalikan `202 Accepted`. Tombol Run tetap aktif setelah enqueue sehingga user dapat mengirim beberapa prediction tanpa menunggu task sebelumnya; seluruh task disimpan durable di PostgreSQL dan worker mengklaim job secara FIFO memakai row lock serta lease token. Inference dijalankan dalam child process terisolasi, sementara heartbeat diperbarui tanpa mengunci transaction hasil prediction. Default heartbeat adalah 5 detik, lease timeout 30 detik, execution timeout 3.600 detik, dan maksimum tiga attempt; seluruh nilai dapat diubah melalui environment `PHASE6_*` di `.env.example`.

Jika worker/container berhenti, lease yang kedaluwarsa otomatis direcovery menjadi `QUEUED` dan dicoba ulang. Setelah retry limit tercapai, run ditutup sebagai `FAILED` dengan diagnostic `WORKER_HEARTBEAT_TIMEOUT`, `PREDICTION_TIMEOUT`, atau worker-exit terkait. Lease token menjadi fencing token: worker lama yang hidup kembali tidak dapat menimpa hasil attempt baru. Re-run dari history juga membuat job baru dari immutable input snapshot dan kembali melalui antrean, termasuk untuk run `FAILED`.

Frontend memantau seluruh task aktif secara berkala, menampilkan jumlah `RUNNING` dan `QUEUED`, attempt serta heartbeat pada history, melanjutkan pemantauan run aktif saat page dibuka kembali, dan otomatis menampilkan hasil task terbaru yang selesai. Endpoint detail hanya mengirim summary, timeline, metadata map, dan satu halaman shipment; kandidat MT dimuat ketika detail shipment dibuka, sedangkan geometri jalan dimuat hanya untuk MT terpilih. Pemisahan ini mencegah puluhan ribu kandidat dan jutaan titik geometri diserialisasi menjadi satu response. Tombol **Refresh** mempunyai loading spinner, disabled state selama request, timestamp keberhasilan, dan pesan error yang terlihat sehingga klik tidak lagi tampak tanpa respons.

Tepat di atas **Prediction Run History**, result workspace menampilkan dua visual operasional. Grafik kombinasi memakai bar untuk KL assigned shipment pada setiap jam `predicted_departure_datetime` dalam timezone depot dan line untuk cumulative assigned KL; bucket kosong di antara jam pertama dan terakhir tetap ditampilkan sebagai nol. Geographic Route per MT memakai koordinat Master Depot/SPBU yang sama dengan Geographic Cluster Map Fase 5 pada basemap OpenStreetMap, filter satu/semua MT, warna konsisten per kendaraan, dan urutan terdekat-ke-terjauh. Marker selalu menunjukkan exact master coordinate, sedangkan garis solid memakai overview GeoJSON dari Google Routes sehingga mengikuti jalan dan dapat mengalami road snapping di dekat marker. Prediction lama melakukan lazy backfill geometri ketika MT dipilih; kegagalan Google ditampilkan sebagai garis fallback putus-putus agar tidak disalahartikan sebagai rute jalan. Shipment tanpa assignment tidak masuk grafik maupun map, dan perubahan manual langsung mengembalikan payload hasil yang telah dihitung ulang.

History menyediakan View, Download, dan Duplicate/Re-run. Export `.xlsx` berisi Summary, Shipment Result, Trip Timeline, MT Assignment, MT Candidates, dan Validation. UI main table menampilkan trip, MT beserta kapasitas/kompartemen, shipment/SPBU, jumlah LO dan volume, planned/departure/return/next-available, confidence, serta status; urutan kunjungan menggunakan kode SPBU yang dapat dibaca, bukan ID internal. Card 7–8 menggunakan server-side pagination 25 shipment per halaman dengan pilihan 25/50/100 dan filter shift di backend. Expandable detail menampilkan pemakaian slot 8 KL, daftar LO/SPBU, preliminary sequence, mode, distance, travel/service/cycle, fallback, serta kandidat/exclusion yang diambil secara lazy. MT Multi-Trip Timeline menampilkan periode kendaraan sampai turnaround selesai dengan pagination terpisah 10 MT per halaman dan pilihan 10/25/50 agar chart tetap ringkas pada hasil besar.

Authorization mengikuti seam existing melalui `X-User` dan `X-Permissions`: `phase6:view`, `phase6:run`, `phase6:export`, `phase6:override`, `google_routes:view`, dan `google_routes:manage`. Local requests tetap permissive sampai identity provider production menggantikan dependency ini.

#### Batas Phase 6 dan Phase 7

Phase 6 boleh menghitung travel estimate, cycle time, preliminary visit sequence dalam satu shipment, dan rolling multi-trip availability. Phase 6 tidak memanggil Google Route Optimization API/GMPRO `optimizeTours`, tidak menyelesaikan full fleet VRP, tidak mengoptimalkan urutan semua shipment/MT secara global, dan tidak menghasilkan final optimized route.

Phase 7 sekarang bertanggung jawab atas final route optimization, fleet-wide constraints, global visit sequencing, vehicle working time, depot bay queue, dan cost objective. Implementasi tidak memakai Google Route Optimization API/GMPRO; optimization engine adalah OR-Tools.

Verification terakhir:

- migration PostgreSQL memiliki single head revision `0022_phase8_manual_dispatch`
- full deployment-image regression terbaru lulus **158 tests**; focused Phase 7 lulus **69 tests**, termasuk current-version warm start V1→V2→V3, actual-state freeze/release MT, retained working-time tanpa double count future trip, reference time/timezone depot, asynchronous reservation, bay subset/timeout semantics, depot gate-out window yang tidak membatasi return MT, geometry depot-stop-depot, activation cost satu kali per MT, dan material gate-out change
- focused Phase 8 lulus **7 tests** untuk immutable source snapshot, canonical eligibility/tag guardrail, selected-MT Google road geometry yang read-only, multi-trip availability dan cascade, duplicate LO/delete-trip recovery, KL capacity gap, finalization, finalized read-only state, serta dispatch versioning
- focused Phase 5 + Phase 6 regression suite berisi **39 tests**
- Phase 7 acceptance/hardening meliputi warm start, dispatcher-selected reference time, compartment, multi-trip, ETA, freeze, DONE/ONGOING, bay compatibility/queue/loading, versioning, dropped reason, final geometry, dan trip-number continuation
- TypeScript type checking dan Vite production build lulus
- API health, kontrak OpenAPI Phase 7, end-to-end V1 persistence, route fallback geometry, parameter/constraint profiles, migration, dan existing Phase 0–6 behavior telah diuji
- visual browser smoke test lulus untuk navigation, depot-scoped empty state, Create Job modal, dan dokumentasi Phase 7 tanpa console error
- Vite memberi non-blocking warning untuk application chunk sekitar 1,90 MB; code splitting ECharts/page modules menjadi technical debt performance
- host Python tanpa dependency ML lengkap tidak dapat menjalankan dua training tests Phase 5; deployment image adalah verification environment canonical dan membutuhkan `NUMBA_CPU_NAME=generic` serta `NUMBA_DISABLE_JIT=1` pada ARM untuk menghindari illegal-instruction dari Numba/UMAP

### Phase 7 — Dynamic Multi-Trip VRP & Depot Bay Queue Optimization

Phase 7 adalah workspace operational control per depot dan operating date. Dispatcher membuat Job, memilih completed Phase 6 Prediction Run secara eksplisit berdasarkan Run ID, mengimpor LO + warm start tanpa mengubah tabel Phase 6, memuat MT canonical depot, mengisi initial ETA Depot, memperbarui actual bay state/queue, memilih parameter profile, lalu menjalankan initial plan atau reroute.

Card **Job Management** memuat tombol **Create New Job**, pencarian lintas Job ID/nama/tanggal/depot/route/status, sorting pada setiap header data, pilihan 5/10/25/50 row, pagination, Open Job, dan Delete Job. Delete selalu meminta konfirmasi dan menghapus workspace operasional Phase 7 beserta versi/snapshot turunannya, tetapi tidak menghapus Prediction Run Phase 6 atau master data. Job berstatus `CALCULATING` tidak dapat dihapus; route-provider request log tetap dipertahankan sebagai audit evidence tanpa referensi Job.

Tab **LO Management** dan **MT Management** menyediakan search, sorting pada setiap header data, pilihan jumlah row, serta pagination Previous/Next. LO Management menampilkan **System ETA Depot** dari trip tepat tempat LO tersebut ditugaskan: semua LO Trip 1 memakai waktu kembali Trip 1, semua LO Trip 2 memakai waktu kembali Trip 2, dan seterusnya; sebelum ada current route assignment nilainya kosong. Select-all LO berlaku pada halaman aktif, sementara perubahan draft ETA/status MT tetap dipertahankan saat user mencari, mengurutkan, atau berpindah halaman. MT Management memiliki **Delivery Status** turunan dari status LO assignment aktif: `ONGOING` menang bila ada LO ongoing, jika tidak `DONE` menang bila ada LO done, sedangkan MT dengan hanya LO planned atau tanpa assignment tampil `PLANNED`. System ETA pada MT hanya tampil ketika Delivery Status `ONGOING` dan nilainya sama dengan return ETA trip current-version tempat LO ongoing tersebut berada; pada status lainnya System ETA tampil kosong. Karena nilai ini dihitung dari LO, Apply Operational Update langsung tercermin setelah workspace di-refresh tanpa menyimpan sumber status kedua. Tab **Bay Management** menyediakan Delete Bay dengan konfirmasi; bay dikeluarkan dari konfigurasi aktif secara soft-delete dan current occupancy/queue terkait dibersihkan, sedangkan snapshot serta histori route/bay assignment tetap auditable. Grid kecepatan pengisian product memisahkan nama product, input angka, dan unit `min / compartment` agar label panjang tidak bertumpuk.

Bulk action MT Phase 7 tersedia di samping header **Operational Status** dan **Planned ETA Depot**. Pilih MT melalui checkbox lintas halaman, atau terapkan ke seluruh hasil pencarian. Active memakai `READY`, Deactive memakai `UNAVAILABLE`. Bulk hanya mengirim field yang dipilih untuk MT target; draft perubahan lain tetap tersimpan di workspace.

Pada tab **MT Management**, **Template MT Readiness** mengunduh Excel `.xlsx` dengan kolom **MT REGISTRATION**, **OPERATIONAL STATUS**, dan **PLANNED ETA DEPOT**. Registrasi otomatis mencakup seluruh MT yang dimuat pada Job aktif, lintas halaman dan filter; status serta ETA memakai nilai tersimpan saat template diunduh. **Import Excel MT Readiness** menyimpan perubahan berdasarkan registrasi tanpa perlu Apply MT Update. Gunakan status `READY`, `ON_TRIP`, `RETURNING`, `QUEUEING`, `LOADING`, atau `UNAVAILABLE` dan sel tanggal Excel/teks `YYYY-MM-DD HH:MM:SS` dalam timezone depot. Kolom kosong mempertahankan nilai; baris yang tidak ingin diperbarui dapat dihapus. Seluruh workbook divalidasi sebelum perubahan disimpan: registrasi asing/duplikat, formula, status tidak valid, serta tanggal salah membatalkan seluruh upload dengan rincian nomor baris. Upload dinonaktifkan ketika Job sedang menghitung optimasi.

Lifecycle ETA MT memakai `planned_eta_depot` sebagai satu-satunya input availability untuk Initial dan Reroute. Semua MT wajib memiliki Planned ETA dan nilainya harus sama atau lebih lambat dari waktu optimasi pilihan dispatcher; optimasi 00:00 dengan Planned ETA 00:00 valid, sedangkan optimasi 12:00 dengan Planned ETA 07:00 ditolak sebelum Job masuk `CALCULATING`. Setelah hasil berhasil dipersist, Planned ETA otomatis di-reset menjadi `null`; run gagal tidak menghapus input. `system_eta_depot` masih `null` sebelum V1 karena belum ada hasil kalkulasi. Pada MT Management, System ETA hanya ditampilkan untuk MT berstatus `ONGOING` dan mengambil `estimated_return_depot` trip current-version yang berisi LO ongoing tersebut—termasuk Trip 2 bila Trip 2 sedang berlangsung. MT berstatus `PLANNED`, `DONE`, atau tanpa LO ongoing menampilkan System ETA `null`. User ETA Override telah dikeluarkan dari API, UI, dan perhitungan solver; kolom database legacy dipertahankan kosong untuk kompatibilitas skema.

Tab **Route Plan** memakai dropdown MT, box **Search MT number or ID**, dan pagination berbasis MT unik. Search mencocokkan registration/no MT maupun canonical `mt_id`, mengembalikan pagination ke halaman pertama, dan memakai scope yang sama untuk Route Plan, **Vehicle Multi-Trip Timeline**, serta Route Details. Kontrol pagination ditempatkan tepat di bawah ringkasan **Solver Status / Gate Out / Dispatch Span**. Card terpisah Vehicle Multi-Trip Timeline berada setelah Route Plan dan sebelum Route Details, sehingga Gantt terlihat sebelum daftar route yang panjang. Gantt hanya merender MT pada halaman aktif; sumbu X selalu memakai gate-out pertama sampai return depot terakhir pada route version, sedangkan registration MT berada pada sumbu kanan. Bar membedakan antri bay, pengisian, gate process, perjalanan, dan pelayanan SPBU. Milestone menunjukkan gate-out/perjalanan, tiba di setiap SPBU, perjalanan berikutnya, dan kembali ke depot; mouseover menampilkan popup MT, trip, status, lokasi, timestamp, dan durasi. Queue/loading yang terjadi sebelum gate-out pertama ditampilkan pada batas awal dengan timestamp aktual di tooltip. Dropdown `All MT`/satu nomor MT menggunakan state yang sama dengan Gantt dan route details. Kolom Product membaca nama canonical dari `master_product.product_name` (misalnya Bio Solar atau Pertamax); `product_id` tetap tersedia pada payload untuk lineage dan filter. Card **Operational KPI Groups** berada di tab **Simulation**, tepat di bawah **Simulation KPI**.

Tab **Comparison** membandingkan dua LO List immutable dalam satu Job: source Phase 6, Phase 7 V1, V2, dan versi berikutnya. Dispatcher memilih LO List A dan B lalu klik **Apply Comparison**. Dashboard menampilkan coverage assigned/drop, LO yang hanya ada di salah satu list, stabilitas/perubahan MT, serta jumlah dan rata-rata perubahan gate-out/ETA Depot. Tabel detail menggunakan Loading Order ID sebagai key dan memperlihatkan tujuan SPBU, product/volume, MT LO A/B, status/trip, gate-out A/B, ETA Depot A/B, dan delta waktu `B − A`; search, sorting header, page size, dan pagination tersedia untuk audit list besar. Data Phase 6 berasal dari `prediction_shipment_line` + `prediction_assignment`/`prediction_trip`, sedangkan setiap Phase 7 source dibaca langsung dari snapshot `route_version_lo_assignment` + `route_version_trip`, sehingga Comparison tidak mengubah current route maupun source lama.

Tab **Geographic Map** memakai pagination MT yang sama sehingga pilihan `All MT` tidak lagi merender seluruh armada sekaligus. Hanya trip untuk halaman aktif yang dibuat sebagai layer Leaflet dan daftar legend juga dibatasi pada scope tersebut. Map menggunakan canvas renderer, validasi koordinat, batas jumlah geometry point per trip, ukuran eksplisit, serta `invalidateSize` + `fitBounds` setiap versi/filter/page berubah. Ini mencegah blank map setelah perpindahan tab dan menghindari ratusan polyline, marker, serta legend card membebani UI dalam satu render. Geometry halaman di-hydrate secara lazy dengan prioritas cache full-route, exact ordered-stop geometry dari Route Version/Prediction Trip historis, live Google Routes, lalu OSRM sebagai fallback **geometry-only**. OSRM tidak mengubah matrix, distance, ETA, assignment, sequence, atau cost solver; hasil Route Version tetap immutable. Garis solid berarti road geometry berhasil, sedangkan garis putus-putus tetap menandai master-coordinate fallback.

Pada Job Overview, tombol **Validate** berada di card **Optimization Flow**, tepat sebelum **Run Initial Optimization**. Klik Validate menjalankan pre-solver gate terhadap current LO, MT, bay state, loading duration, dan draft constraint; hasil **Optimization Readiness** (`READY`, `WARNING`, atau `BLOCKED`) ditampilkan sebagai popup, bukan card permanen.

Klik **Run Initial Optimization** selalu membuka dialog tanggal dan waktu referensi. Tanggal Initial harus sama dengan `operating_date` Job; waktu tersebut menjadi batas awal availability MT, Bay State Effective/queue, departure matrix, dan seluruh perhitungan waktu route. Klik **Re-Optimize Now** membuka dialog yang sama dengan tanggal dikunci ke tanggal Initial. Jam Re-optimize tidak boleh mundur dari run terakhir dan menjadi patokan `current time` untuk freeze window serta state bay. Dialog juga menghitung saran minimum `route_optimization_time_limit` dari jumlah LO optimizable dan MT tersedia: `round30(15 + 0.25 × LO + 10 × ceil(LO / MT))`, dibatasi 30–3.600 detik. Jika parameter aktif di bawah saran, dispatcher harus menaikkannya atau mencentang konfirmasi sadar-risiko; backend menerapkan konfirmasi yang sama. Timestamp pilihan dispatcher disimpan pada `optimization_run.optimization_reference_time`, solver metadata, dan audit state snapshot; jam server API tidak digunakan sebagai effective time operasional bay.

Initial Optimization dan Re-Optimize bersifat asynchronous dari sudut pandang UI. Setelah preflight berhasil, API mengunci Job ke `CALCULATING`, mengembalikan `202 Accepted`, lalu menjalankan matrix, solver, dan persistence melalui background task dengan database session terpisah. UI langsung menutup dialog dan kembali ke **Job Management** tanpa overlay global; row Job menampilkan spinner/status `CALCULATING` dan daftar diperbarui otomatis setiap dua detik hingga menjadi `ACTIVE`, `CLOSED`, atau `FAILED`. Duplicate optimization dan Delete Job tetap ditolak selama kalkulasi. Jika proses API terhenti, recovery startup menandai run in-process sebagai `FAILED/INTERRUPTED` agar Job tidak tertinggal permanen pada status `CALCULATING`.

Progress run disimpan secara auditable pada `optimization_run.solver_metadata` sebagai `BUILDING_MATRIX`, `SOLVING_ROUTES`, `PERSISTING_RESULT`, lalu `COMPLETED`/`FAILED`, lengkap dengan `progress_pct` dan `stage_updated_at`. `PERSISTING_RESULT` mencakup materialisasi trip/assignment serta final route geometry, sehingga Job tetap `CALCULATING` walaupun OR-Tools sudah selesai. Kegagalan Google Routes seperti `403` atau `429` tidak menggagalkan hasil solver: request dihentikan oleh geometry time/request guard, route memakai fallback yang diberi label, lalu versi tetap disimpan. Durasi wall-clock dapat lebih panjang dari `solve_duration_ms` bila host/Docker sempat sleep atau pause; status disebut stuck hanya jika stage tidak berubah, tidak ada aktivitas proses/database, dan tidak ada terminal recovery/error.

Pemilihan Prediction Run bersifat ketat dan auditable. Dropdown hanya menampilkan run Phase 6 berstatus `COMPLETED` pada depot yang sama dan memiliki sedikitnya satu LO dengan tanggal operasional lokal yang sama dengan `operating_date` Job Phase 7. Tanggal yang tertulis di `prediction_run_no` seperti `PRED-20260826-71EF00` adalah tanggal pembuatan run, bukan jaminan tanggal operasional LO. Tanggal operasional diturunkan dari `shipment_start_datetime_local`, atau dari timestamp UTC yang dikonversi memakai timezone Master Depot. Jika dropdown kosong, periksa kombinasi depot, Job Operating Date, status run, dan tanggal lokal LO; buat Job baru dengan tanggal yang benar atau hasilkan completed Phase 6 Run untuk tanggal tersebut. Jangan mengubah tanggal snapshot atau source run secara langsung karena akan merusak lineage audit.

```text
Saved Phase 6 Run (immutable)
    → Phase 7 LO operational state + Phase 6 soft warm start
    → cached Google Routes distance/time matrix
    → OR-Tools Routing Solver per physical-vehicle trip round
    → CP-SAT compartment assignment
    → FIFO_BALANCED bay eligibility, queue, loading, and gate-out schedule
    → event-driven return/availability propagation
    → post-bay per-trip repair (failed LO → candidate MT audit → global FIFO bay re-schedule)
    → immutable route version + state and parameter snapshots
```

Warm-start lineage bersifat berantai. Phase 6 hanya menjadi seed untuk **Initial Optimization → V1**. Saat reroute, solver membaca `current_route_version_id`: remaining V1 menjadi seed V2, remaining V2 menjadi seed V3, dan seterusnya. DONE disalin apa adanya; ONGOING mempertahankan trip/MT aktif tetapi return-to-depot mengikuti Planned ETA aktual dispatcher; near-term PLANNED dengan MT on-time/lebih cepat mempertahankan MT dan relative stop sequence sambil menghitung ulang route/bay time; near-term PLANNED dengan MT terlambat atau unavailable dilepas kembali ke routing pool. Future PLANNED lain tetap dapat diubah dengan penalty previous vehicle/shipment/sequence/gate-out/bay agar versi baru tidak berubah tanpa manfaat objective yang cukup. Reroute hanya membawa working time trip DONE/ONGOING; operating time future dari versi lama tidak dihitung ganda dan dihitung ulang oleh solver. Metadata run mencatat sumber/version warm start dan jumlah seed pada setiap multi-trip round.

Kontrak utama:

- Phase 6 predicted shipment, MT, pairing, confidence, dan model ID disimpan terpisah dari current Phase 7 vehicle/trip/shipment/compartment assignment.
- Phase 6 adalah warm start khusus V1; current Route Version adalah warm start untuk setiap reroute berikutnya. Setiap business constraint Phase 7 mempunyai `enabled`, mode `HARD`/`SOFT`, dan nilai penalty yang disimpan di parameter profile. `HARD` wajib lolos dan mengabaikan penalty; `SOFT` boleh dilanggar dengan penalty; disabled tidak dienforce dan penalty efektifnya nol.
- `vehicle_working_time.limit_minutes` adalah satu-satunya sumber batas kerja MT. Planned ETA hanya menyatakan kapan MT tersedia; MT system-planned yang masih parkir belum memakai working time. Jam kerja dimulai saat MT dilepas ke queue/loading, lalu mencakup queue aktual, loading, perjalanan dan service sampai kembali ke depot; field lama `default_vehicle_working_time_minutes` sudah dihapus.
- `depot_operating_window` membatasi awal loading dan gate-out, bukan return MT. Dengan window 00:00–23:59, loading boleh mulai pukul 00:00 dan gate-out terakhir boleh tepat 23:59; MT boleh kembali sesudahnya selama masih memenuhi `vehicle_working_time` dan SPBU receiving window. KPI Depot Operation Span dihitung dari first loading start sampai last gate-out.
- Routing Solver dijalankan dalam physical-vehicle multi-trip loop. Setelah Trip 1 kembali, MT baru eligible untuk Trip 2 pada `estimated_return_depot + mt_turnaround_buffer_minutes`. Parameter ini tersimpan per Parameter Profile (default 30 menit; nilai 0 menonaktifkan jeda), sehingga skenario dapat memakai waktu persiapan MT yang berbeda tanpa mengubah timestamp fisik `estimated_return_depot`.
- CP-SAT compartment assignment menerapkan mode constraint untuk compartment capacity dan product separation, lalu mencatat setiap pelanggaran SOFT pada trip cost breakdown.
- `bay_scheduler_strategy=FIFO_BALANCED` adalah default operational scheduler. Trip masuk antrean global menurut `vehicle_ready_at_depot`, preliminary gate-out, nomor trip, MT, dan LO sebagai tie-break deterministik. Scheduler memilih bay kompatibel dengan gate-out paling awal, lalu workload/jumlah assignment paling rendah; bay khusus produk diprioritaskan sebelum bay fleksibel bila waktu dan penalty sama. Enam bay multi-product yang identik akan membagi antrean secara merata tanpa pencarian kombinatorial.
- Actual occupancy dan Current Physical Queue diblok lebih dahulu per bay. Trip berikutnya milik MT yang sama baru masuk antrean setelah gate-out aktual ditambah durasi route/return trip sebelumnya dan `mt_turnaround_buffer_minutes`. `BAY_PRODUCT_CONSTRAINT` berarti tidak ada bay yang lolos eligibility struktural, sedangkan `BAY_WINDOW_EXHAUSTED` berarti bay kompatibel ada tetapi seluruhnya tidak dapat gate-out sebelum batas waktu. Kegagalan trip awal mencegah trip berikutnya melompati urutan fisik MT.
- Route dan bay tetap memiliki parameter budget terpisah. `bay_optimization_time_limit`, `bay_cp_sat_workers`, dan `max_coordination_iterations` hanya memengaruhi strategi eksperimen `CP_SAT`; FIFO_BALANCED bersifat deterministik, tidak memakai search worker atau timeout bay. `CP_SAT` tetap dapat dipilih eksplisit pada tab Parameter untuk perbandingan/audit, tetapi bukan default operasional.
- Route assignment belum dianggap final sebelum waktu queue/loading/gate-out bay diterapkan. `VEHICLE_TIME_EXHAUSTED`, `BAY_WINDOW_EXHAUSTED`, `BAY_CONGESTION`, dan komposisi `BAY_PRODUCT_CONSTRAINT` yang masih mungkin dipisah dikembalikan ke repair pool per physical trip. Kandidat diuji satu per satu dengan prioritas MT belum terpakai, ETA paling awal, remaining working time terbesar, lalu ID stabil. Setiap kandidat dihitung dari retained-trip state, diuji route/compartment, dan divalidasi lewat global FIFO bay re-schedule; satu group gagal tidak menggagalkan group lain. Jika grouping shipment/freeze tidak HARD, group yang tetap gagal dapat dipecah menjadi LO tunggal. Final drop baru dibuat setelah semua kandidat tercatat gagal; budget habis menjadi `POST_BAY_REASSIGNMENT_TIMEOUT`, bukan bukti `INFEASIBLE`. Metadata menyimpan candidate MT, ETA, sisa kerja, hasil/reason, split count, dan jumlah evaluation.
- Terminasi `UNKNOWN`/`TIMEOUT` dibedakan dari bukti `INFEASIBLE`; kehabisan waktu tidak lagi disimpulkan sebagai ketidaklayakan fisik.
- Default loading mode adalah `SEQUENTIAL`; model mendukung `PARALLEL` dengan `number_of_loading_arms`.
- `DONE`, `ONGOING`, dan near-term `PLANNED` di dalam `freeze_window_minutes` diklasifikasikan per physical trip. DONE disalin, ONGOING mempertahankan assignment dengan actual return ETA, near-term PLANNED on-time mengunci MT/sequence tetapi menghitung ulang waktu, sedangkan MT late/unavailable melepaskan trip kembali ke routing pool. Jika satu LO frozen berada pada trip yang sama, seluruh trip diperlakukan sebagai unit execution yang konsisten.
- Initial hanya dapat membuat baseline sekali. Setelah V1 tersedia, dispatcher memakai Re-Optimize untuk V2/V3; tanggal tetap sama dan waktu referensi bergerak maju secara kronologis.
- Planned ETA Depot aktual dari dispatcher serta actual bay/queue state mengalahkan previous predicted state. Bay/queue state selalu disejajarkan ke timestamp Initial atau Reroute yang dimasukkan user. Reroute tidak menjalankan Phase 6 ulang.
- Setiap run membuat `V1`, `V2`, dan seterusnya secara append-only bersama operational snapshot, parameter checksum/snapshot, solver metadata, cost, dropped reason, dan comparison/adherence.
- LO infeasible tidak pernah hilang: result menyimpan reason seperti `NO_COMPATIBLE_MT`, `COMPARTMENT_INFEASIBLE`, `BAY_PRODUCT_CONSTRAINT`, `DEPOT_TIME_EXHAUSTED`, atau `UNSERVED_END_OF_DAY`.

Tab **Parameter → Constraint Settings · Hard / Soft / Disabled** adalah sumber pengaturan constraint. Mengubah objective tidak otomatis mengubah mode constraint. Setiap run menyimpan seluruh rule, nilai penalty tersimpan, effective penalty, dan checksum pada immutable parameter snapshot. Nilai penalty hanya efektif ketika rule aktif dalam mode `SOFT`; nilainya tetap disimpan tetapi tidak dipakai saat `HARD`, sehingga dapat dipakai kembali jika dispatcher mengubah mode ke `SOFT`.

Pada **Vehicle Activation Cost Rules**, `priority` hanya memilih rule biaya yang berlaku ketika beberapa rule cocok pada MT yang sama. Rule diurutkan dari priority terbesar; jika sama, rule dengan `vehicle_tag` didahulukan dari rule class-only. Hanya `activation_cost` dari rule pertama yang cocok yang dipakai, bukan dijumlahkan. Priority tinggi tidak otomatis membuat MT lebih disukai—activation cost yang lebih rendahlah yang membuat MT lebih menarik bagi objective. Rule ini tidak menggantikan MT–SPBU Compatibility atau HARD constraint lainnya; jika tidak ada rule yang cocok, activation cost MT adalah nol.

`DONE`/`ONGOING`, satu identity assignment per LO, foreign-key/version integrity, dan append-only route version adalah safeguard struktural, bukan business constraint yang dapat dimatikan. Near-term `PLANNED` pada freeze window tetap configurable.

Objectives tersedia tanpa mengubah mode constraint:

- `MIN_TOTAL_COST`: activation + distance + operating + queue + loading + overtime + penalties.
- `MIN_TOTAL_DISTANCE`: total route distance.
- `MIN_TOTAL_OPERATING_TIME`: driving + waiting + SPBU service + depot queue + loading.

Google Routes configuration Phase 7:

- final map geometry memakai satu Compute Routes request per trip dengan SPBU sequence sebagai ordered intermediate waypoints, sehingga polyline mengikuti jalan untuk rangkaian Depot → seluruh stop → Depot;
- ketika membuka tab Geographic Map, endpoint `POST /jobs/{job_id}/map/road-geometry` hanya meng-hydrate trip pada halaman MT aktif. Urutannya adalah full-route cache → exact historical road geometry → Google Routes → OSRM road geometry. Cache hasil hydration berlaku 30 hari secara default dan tidak menulis ulang Route Version;
- OSRM adalah fallback geometry-only saat Google terkena `403`, `429`, timeout, atau tidak dikonfigurasi. Nilai distance/time OSRM tidak dipakai oleh optimizer maupun laporan route version, sehingga OR-Tools tetap menjadi satu-satunya penentu assignment dan stop order;
- geometry request tidak dipanggil dari solver callback; fallback garis putus-putus hanya dipakai dan diberi label jika road provider gagal atau dinonaktifkan;
- default final-geometry guard adalah `route_geometry_time_limit_seconds=120` dan `route_geometry_google_request_budget=500` untuk satu run; nilai dapat diperkecil pada parameter profile jika fallback cepat lebih penting daripada kelengkapan road geometry;
- `403`/invalid key dan `429`/rate limit dicatat pada log provider, tetapi tidak mengubah solver result menjadi gagal. Setelah guard habis, remaining trip memakai cached/master fallback dan run melanjutkan persistence;
- `route_vehicle_mode=GENERAL_VEHICLE` adalah default dan tidak memerlukan Large Vehicle Routing.
- `route_vehicle_mode=TRUCK` hanya dipilih secara eksplisit. Pada deployment/region yang belum mendukung truck request, hasil harus tetap menunjukkan fallback/provider source dan tidak boleh disamarkan sebagai truck road result.
- `traffic_aware` dan `route_matrix_cache_enabled` configurable.
- Matrix dimaterialisasi sebelum solver callback. Google tidak pernah dipanggil dari cost callback OR-Tools.
- Final selected legs dapat mengambil road geometry; cached/master-coordinate fallback terlihat sebagai `MIXED_OR_MASTER_FALLBACK`.

Parameter profiles (`Balanced Default`, `Cost Efficiency`, `High Historical Adherence`, `Peak Operation`, `High Bay Congestion`) mendukung Load, Save sebagai versi berikutnya, dan Save As. Exact effective values selalu disalin ke immutable `optimization_parameter_snapshot`.

Schema migration `0019_phase7_dynamic_vrp` menambah job/run/version/trip/stop/LO/vehicle result, operational state, bay state/queue/operation, parameter profile/snapshot/cost rules, serta Phase 7 route matrix cache/request log. Migration `0020_phase7_reference_time` menambah timestamp referensi optimasi yang dipilih dispatcher. Service logic dipisahkan di `phase7_service.py`, `phase7_optimization.py`, dan `phase7_matrix.py`; handler API tidak memuat solver logic.

Environment dan run:

```bash
cd apps/api
python -m pip install -r requirements.txt  # includes ortools
pytest tests/test_phase7_dynamic_vrp.py

# full stack and migrations
docker compose up --build
```

Google API key tetap disimpan melalui Settings UI dan dienkripsi oleh `GOOGLE_ROUTES_ENCRYPTION_KEY`. Tidak ada key baru yang ditempatkan di frontend atau parameter snapshot.

## Phase Quality Gate

Setiap phase harus melewati gate berikut sebelum phase berikutnya dimulai:

1. migration berhasil
2. import/seed berhasil
3. analytics jobs berhasil
4. unit tests pass
5. API tests pass
6. integration tests pass
7. Docker stack healthy
8. API health verified
9. frontend screen dibuka
10. visual validation pass
11. acceptance scenarios pass
12. blocking issues fixed
13. documentation updated
14. phase completion report dibuat

## Current API Highlights

- `GET /api/v1/health`
- `POST /api/v1/imports?domain=...&sheet_name=...`
- `GET /api/v1/imports`
- `GET /api/v1/imports/{id}`
- `GET /api/v1/exports/template?domain=...&file_format=xlsx|csv`
- `GET /api/v1/exports/data?domain=...&depot_id=...&file_format=xlsx|csv`
- `GET /api/v1/foundation/overview?depot_id=...`
- `GET /api/v1/foundation/charts?depot_id=...`
- `GET /api/v1/master-crud/{domain}?limit=...&offset=...&search=...&depot_id=...&active_status=...`
- `POST /api/v1/master-crud/{domain}`
- `PUT /api/v1/master-crud/{domain}/{record_id}`
- `DELETE /api/v1/master-crud/{domain}/{record_id}`
- `POST /api/v1/master/compatibility/check`
- `GET /api/v1/master/compatibility/summary?depot_id=...`
- `GET /api/v1/data-quality/issues?depot_id=...`
- `GET /api/v1/tag-intelligence/anomalies`
- `GET /api/v1/tag-intelligence/recommendations`
- `GET /api/v1/network/nodes`
- `GET /api/v1/network/edges`
- `GET /api/v1/affinity-intelligence/analysis?depot_id=...&start_date=...&end_date=...`
- `GET /api/v1/affinity-intelligence/available-dates?depot_id=...`
- `GET /api/v1/phase5/readiness?depot_id=...`
- `POST /api/v1/phase5/engine-a/analyze`
- `GET /api/v1/phase5/engine-a/runs`
- `GET /api/v1/phase5/engine-a/runs/{run_id}`
- `POST /api/v1/phase5/engine-b/prepare-dataset`
- `POST /api/v1/phase5/engine-b/training-runs/{run_id}/train`
- `POST /api/v1/phase5/engine-b/training-runs/{run_id}/save`
- `GET /api/v1/phase5/models`
- `GET /api/v1/phase5/models/active?depot_id=...`
- `POST /api/v1/phase5/models/compare`
- `GET /api/v1/phase6/models?depot_id=...`
- `GET /api/v1/phase6/templates/loading-order`
- `GET /api/v1/phase6/templates/mt-availability`
- `GET /api/v1/phase6/templates/mt-initial-availability`
- `POST /api/v1/phase6/demo/loading-order`
- `POST /api/v1/phase6/demo/mt-availability`
- `POST /api/v1/phase6/validate/loading-order`
- `POST /api/v1/phase6/validate/mt-availability`
- `POST /api/v1/phase6/predictions`
- `GET /api/v1/phase6/predictions`
- `GET /api/v1/phase6/predictions/{run_id}/status`
- `GET /api/v1/phase6/predictions/{run_id}?shipment_page=1&shipment_page_size=25&shift_id=...`
- `GET /api/v1/phase6/predictions/{run_id}/shipments/{shipment_id}/candidates`
- `POST /api/v1/phase6/predictions/{run_id}/route-geometry`
- `POST /api/v1/phase6/predictions/{run_id}/recalculate`
- `PATCH /api/v1/phase6/predictions/{run_id}/shipments/{shipment_id}`
- `PATCH /api/v1/phase6/predictions/{run_id}/assignments/{assignment_id}`
- `PATCH /api/v1/phase6/predictions/{run_id}/trips/{trip_id}`
- `GET /api/v1/phase6/predictions/{run_id}/export`
- `GET /api/v1/settings/google-routes`
- `PUT /api/v1/settings/google-routes`
- `DELETE /api/v1/settings/google-routes/api-key`
- `POST /api/v1/settings/google-routes/test`
- `POST /api/v1/phase7/jobs`
- `GET /api/v1/phase7/jobs?depot_id=...`
- `GET /api/v1/phase7/jobs/{job_id}`
- `DELETE /api/v1/phase7/jobs/{job_id}`
- `GET /api/v1/phase7/jobs/{job_id}/prediction-runs`
- `POST /api/v1/phase7/jobs/{job_id}/prediction-run`
- `GET/PATCH /api/v1/phase7/jobs/{job_id}/loading-orders[/status]`
- `POST /api/v1/phase7/jobs/{job_id}/vehicles/load-master`
- `GET/PATCH /api/v1/phase7/jobs/{job_id}/vehicles`
- `GET/PUT /api/v1/phase7/depots/{depot_id}/bays`
- `DELETE /api/v1/phase7/depots/{depot_id}/bays/{bay_id}`
- `GET/PUT /api/v1/phase7/jobs/{job_id}/bay-state`
- `GET/POST /api/v1/phase7/jobs/{job_id}/validation`
- `POST /api/v1/phase7/jobs/{job_id}/optimize`
- `POST /api/v1/phase7/jobs/{job_id}/reroute`
- `GET /api/v1/phase7/jobs/{job_id}/versions`
- `GET /api/v1/phase7/jobs/{job_id}/versions/{version_id}`
- `GET /api/v1/phase7/jobs/{job_id}/versions/{version_id}/trips/{trip_id}`
- `GET /api/v1/phase7/jobs/{job_id}/simulation`
- `GET /api/v1/phase7/jobs/{job_id}/map`
- `POST /api/v1/phase7/jobs/{job_id}/map/road-geometry`
- `GET /api/v1/phase7/jobs/{job_id}/cost-analysis`
- `GET /api/v1/phase7/jobs/{job_id}/dropped-loading-orders`
- `GET/POST/PUT /api/v1/phase7/parameter-profiles[...]`
- `GET /api/v1/phase7/constraint-catalog`

### Handoff Phase 7 → Phase 8

Phase 7 dan Phase 8 memakai data operasional yang sama sebagai lineage, tetapi mempunyai authority dan lifecycle berbeda. Phase 7 memilih assignment dan sequence fleet-wide melalui optimization; Phase 8 menerima satu hasil terpilih sebagai snapshot lalu hanya mengizinkan adjustment manual serta recalculation lokal per trip.

| Aspek | Phase 7 | Phase 8 |
|---|---|---|
| Input utama | Saved Phase 6 Prediction Run + current LO/MT/bay state | Phase 6 warm start atau Route Version Phase 7 yang dipilih |
| Authority | Global assignment, multi-trip routing, compartment, bay, dan gate-out optimization | Human-reviewed MT–Trip–LO assignment, constraint guardrail, timeline, simulation, dan final dispatch |
| Engine | OR-Tools Routing Solver, compartment CP-SAT, `FIFO_BALANCED` bay scheduler default | Tidak ada global solver; canonical validation + Google Routes per-trip Apply |
| Version | Immutable Route V1/V2/...; current pointer berada pada Phase 7 Job | Dispatch V1/V2/... sebagai deep-copy snapshot dengan parent lineage |
| Mutation source | Tidak menulis ulang Phase 6 | Tidak menulis ulang Phase 6 maupun Phase 7 |
| Output | Optimized operational route candidate | Finalized, read-only, human-reviewed dispatch plan |

Saat membuat Manual Dispatch Job, daftar Phase 7 Job dibatasi oleh depot dan operational date. Source route dibaca dinamis—tanpa hardcoded maximum version—kemudian vehicle, trip, LO scope, assignment, cluster, shift, tags, route metadata, dan configuration snapshot disalin ke tabel Phase 8. Perubahan Phase 7 setelah snapshot dibuat tidak mengubah Manual Dispatch Job yang sudah ada; dispatcher harus membuat job/version baru bila ingin memakai source terbaru.

### Phase 8 — Manual Dispatching & Operational Simulation

Phase 8 dimulai dari landing **Manual Dispatch Job List**, bukan langsung membuka editor. Create Job memakai dependent selection Depot → Operational Date → Phase 7 Job → source route dinamis. Source dapat berupa Phase 6 Prediction/Warm Start atau route Phase 7 mana pun. `Create & Load` membuat relational snapshot MT, trip, LO scope, assignment, cluster, shift, tag, route, configuration, dan lineage tanpa mengubah source.

Workspace job memakai header persisten dan lima tab yang membaca current state yang sama: **Trip Management**, **Simulation Diagram**, **Daily Distribution Dashboard**, **Geographic Map**, dan **History / Audit**. Operasi Add/Remove/Move/Reorder/Edit menandai trip `MODIFIED`. Tombol Apply menjalankan canonical compatibility, capacity/sequence/timeline validation, Google Routes per leg, service time, ETA SPBU, return depot, turnaround, next availability, dan invalidasi trip berikutnya menjadi `NEEDS_RECALCULATION`. Phase 8 tidak menjalankan OR-Tools atau global VRP reoptimization.

Tab **Geographic Map** mempunyai search box nomor/ID MT dan dropdown **Select No. MT**. Map hanya memuat satu MT terpilih agar ringan, tetapi menampilkan seluruh trip MT itu. Geometry memakai hasil Google Routes yang sudah tersimpan atau satu full-route Google request Depot → ordered SPBU → Depot untuk source snapshot yang belum memiliki geometry Google. Hydration bersifat read-only dan tidak mengubah assignment, sequence, ETA, status, distance, atau dispatch version. Jika Google Routes gagal/tidak dikonfigurasi, error ditampilkan per trip dan route tidak diganti garis lurus.

Lifecycle job adalah `DRAFT → IN_PROGRESS → READY → FINALIZED`. Lifecycle trip membedakan `DRAFT`, `MODIFIED`, `CALCULATING`, `VALID`, `WARNING`, `CONFLICT`, dan `NEEDS_RECALCULATION`. Hanya Apply sukses yang menghasilkan route/timeline authoritative. Finalized job tidak dapat diedit langsung; perubahan lanjutan wajib melalui **Create New Version**.

Simulation memakai KL sebagai capacity metric: gate-out demand KL, available MT capacity KL, capacity gap, serta Gantt `AVAILABLE_AT_DEPOT`/`TRIP`. Dashboard membedakan Time Utilization dari Volume Capacity Utilization, memakai saved shift/cluster source, dan dapat membuka filtered Unassigned LO. Finalization memblokir incompatibility, duplicate, uncalculated/stale route, dan timeline overlap; unassigned demand default-nya warning dengan acknowledgment. Finalized version read-only dan **Create New Version** menghasilkan deep-copy snapshot baru.

Endpoint Phase 8:

- `GET /api/v1/phase8/manual-dispatch/sources`
- `GET/POST /api/v1/phase8/manual-dispatch/jobs`
- `GET /api/v1/phase8/manual-dispatch/jobs/{job_id}`
- `POST /api/v1/phase8/manual-dispatch/jobs/{job_id}/versions`
- `GET /api/v1/phase8/manual-dispatch/jobs/{job_id}/vehicles/{vehicle_id}/eligible-loading-orders`
- `POST /api/v1/phase8/manual-dispatch/jobs/{job_id}/trips`
- `PATCH/DELETE /api/v1/phase8/manual-dispatch/jobs/{job_id}/trips/{trip_id}`
- `POST/DELETE /api/v1/phase8/manual-dispatch/jobs/{job_id}/trips/{trip_id}/loading-orders[...]`
- `POST /api/v1/phase8/manual-dispatch/jobs/{job_id}/loading-orders/{lo_scope_id}/move`
- `PUT /api/v1/phase8/manual-dispatch/jobs/{job_id}/trips/{trip_id}/stop-order`
- `POST /api/v1/phase8/manual-dispatch/jobs/{job_id}/trips/{trip_id}/apply`
- `GET /api/v1/phase8/manual-dispatch/jobs/{job_id}/simulation`
- `GET /api/v1/phase8/manual-dispatch/jobs/{job_id}/dashboard`
- `GET /api/v1/phase8/manual-dispatch/jobs/{job_id}/map?vehicle_id=...`
- `GET /api/v1/phase8/manual-dispatch/jobs/{job_id}/audit`
- `GET /api/v1/phase8/manual-dispatch/jobs/{job_id}/validation`
- `POST /api/v1/phase8/manual-dispatch/jobs/{job_id}/finalize`

### Phase 9 — Route–Model Alignment Evaluation

Phase 9 membaca satu immutable Route Version Phase 7 dan menjelaskan seberapa selaras route tersebut dengan bukti historis yang menjadi lineage analitisnya. User hanya memilih **TBBM** dan **Route Version**; system kemudian membentuk **Source-Aligned Bundle** otomatis dari source Phase 5 model/training snapshot serta historical MT affinity yang scope dan cutoff waktunya eligible. Tidak ada pemilihan saved analysis/model manual pada flow utama dan tidak ada silent recomputation saat hasil tersimpan dibuka kembali.

Empat metric ditampilkan terpisah pada skala `0–100%`:

- **Cluster Cohesion**: proporsi pasangan SPBU evaluable dalam trip yang berada pada cluster Phase 5 yang sama;
- **Shift Alignment**: historical `P(route shift | SPBU)` berdasarkan planned gate-out dan shift snapshot source model;
- **Historical SPBU Pairing**: mean symmetric dari `P(B|A)` dan `P(A|B)` untuk unique SPBU pair dalam trip;
- **Historical MT Affinity**: raw historical `P(MT|SPBU)` untuk assigned MT.

Metric tidak dicampurkan menjadi overall score, tidak memakai label baik/buruk, dan tidak menghasilkan rekomendasi operasional. `0%` berarti denominator historis tersedia tetapi pattern tidak pernah terlihat; `N/A` berarti bukti atau assignment yang diperlukan tidak cukup. Evidence coverage, resolution method, historical period, checksum bundle, dan detail numerator/denominator tetap ditampilkan terpisah agar hasil auditable.

Dashboard menyediakan metric cards, overview/distribution, evidence coverage, Source-Aligned Bundle, **Trip Alignment Matrix**, dan Loading Order detail. Trip Alignment Matrix memiliki kolom **No. LO** dan **No. SPBU** terpisah dari jumlah LO/SPBU, server-side search untuk shipment/trip/MT/shift/LO/SPBU/nama SPBU, sorting per kolom, serta pagination `10/25/50/100`. Tabel Loading Order mempunyai search, sorting, pagination, dan evidence drawer sendiri; kontrol kedua tabel tidak mengubah aggregate route-level.

Endpoint Phase 9:

- `GET /api/v1/phase9/route-model-alignment/routes?depot_id=...`
- `POST /api/v1/phase9/route-model-alignment/evaluations`
- `GET /api/v1/phase9/route-model-alignment/evaluations/by-route/{route_version_id}`
- `GET /api/v1/phase9/route-model-alignment/evaluations/{evaluation_run_id}`
- `GET /api/v1/phase9/route-model-alignment/evaluations/{evaluation_run_id}/trips`
- `GET /api/v1/phase9/route-model-alignment/evaluations/{evaluation_run_id}/rows`
- `GET /api/v1/phase9/route-model-alignment/evaluations/{evaluation_run_id}/rows/{evaluation_row_id}`

Persistence Phase 9 memakai evaluation run, one-row-per-LO alignment snapshot, dan unique trip-pair evidence. Idempotency menggunakan `route_version_id + source_bundle_checksum + algorithm_version`; perubahan source bundle atau algorithm version membuat run baru tanpa mengubah Route Version.

### Phase 10 — AMT Scheduler Connector

Phase 10 menyediakan REST API read-only di `/api/v1/integration/amt-scheduler` dan console internal di `/phase10/amt-scheduler-connector`. AMT Scheduler melakukan pull terhadap canonical Terminal, MT, historical operation pada grain trip, seluruh Route Version Phase 7, seluruh versi Manual Dispatch Phase 8, authoritative shift definition, dan MT availability yang selalu dihitung dari route terpilih.

External endpoint menggunakan bearer token acak yang disimpan sebagai SHA-256 hash, kecuali health check. Setiap request memiliki `X-Request-ID`, canonical error envelope, database request log yang tidak menyimpan token, logical dataset version, pagination, serta incremental `updated_since` pada terminal/vehicle/history. Adapter `Phase7RouteAdapter` dan `Phase8RouteAdapter` tidak mengubah source route.

Availability memakai boundary `departure_at <= reference_at < return_to_depot_at`: exact departure `ON_TRIP`, exact return `AVAILABLE`, initial availability di masa depan `UNAVAILABLE`, dan incomplete/invalid timeline `UNKNOWN`. Output hanya mencakup vehicle timeline, next availability/departure, serta informational handover window; Phase 10 tidak membuat roster, crew pairing, AMT–MT assignment, handover decision, atau recommended AMT arrival.

Lihat `docs/PHASE_10_AMT_SCHEDULER_CONNECTOR.md` untuk mapping, auth/RBAC, endpoint, cURL, shift lineage, logging, dan limitation.

## Important Design Principles

- Jangan overwrite master data secara diam-diam dari historical evidence.
- Pisahkan official master rule, operational instruction, observed behavior, analytical finding, recommendation, dan approved master-data change.
- Semua canonical dan derived records harus menjaga lineage jika memungkinkan.
- Jangan menggunakan LLM untuk deterministic analytics.
- Phase 7 route optimization hanya boleh membaca saved Phase 6 sebagai warm start; jangan menulis balik atau menjalankan Phase 6 otomatis saat reroute.
- Phase 8 hanya boleh menyalin Phase 6/7 sebagai working snapshot; jangan menulis balik source dan jangan menjalankan global reoptimization otomatis.
- Phase 9 hanya menjelaskan alignment terhadap historical evidence; jangan mengubahnya menjadi route quality score, pass/fail, ranking, atau recommendation.
- Phase 10 hanya menyediakan canonical read API dan route-scoped MT availability; jangan menambahkan AMT scheduling, roster, crew assignment, atau recommended AMT arrival.
- Google Routes menyediakan travel data dan geometry saja; OR-Tools adalah satu-satunya optimization engine Phase 7.
- Jangan tampilkan uncertainty sebagai fakta pasti; gunakan status seperti `UNKNOWN`, `UNMAPPED`, `AMBIGUOUS`, `LOW CONFIDENCE`, `PARTIAL`, atau `INSUFFICIENT DATA`.

## Documentation

Dokumen pendukung:

- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/SOURCE_DATA_MAPPING.md`
- `docs/IMPORT_PROCESS.md`
- `docs/MASTER_DATA.md`
- `docs/TAG_MODEL.md`
- `docs/TAG_COMPATIBILITY.md`
- `docs/DATA_QUALITY.md`
- `docs/PHASE_7_DYNAMIC_VRP.md`
- `docs/PHASE_8_MANUAL_DISPATCH.md`
- `docs/PHASE_9_ROUTE_MODEL_ALIGNMENT.md`
- `docs/PHASE_10_AMT_SCHEDULER_CONNECTOR.md`
- `docs/SHIPMENT_MODEL.md`
- `docs/GPS_MODEL.md`
- `docs/PHASES.md`
- `docs/PHASE_0_STATUS.md`
- `docs/PHASE_4_SPBU_MT_AFFINITY.md`
- `docs/PHASE_5_MACHINE_LEARNING_INTELLIGENCE.md`
- `docs/PHASE_6_PREDICTION_ASSIGNMENT.md`
- `docs/FUTURE_VRP_INTEGRATION.md`
- `docs/FUTURE_AI_ASSISTANT.md`
