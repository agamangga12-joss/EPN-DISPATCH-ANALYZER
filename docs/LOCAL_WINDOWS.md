# Menjalankan tanpa Docker di Windows

Jalankan dari PowerShell di folder proyek:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
```

Launcher menjalankan PostgreSQL/PostGIS portable, migrasi, API, worker Phase 6,
worker import, dan Vite. Web memakai http://127.0.0.1:3000.
Log berada di `outputs/local-runtime/`.

Prerequisite: Python 3.12 virtual environment `.venv` dengan
`apps/api/requirements.txt`, `npm ci` di `apps/web`, dan PostgreSQL 16 portable
beserta PostGIS di `outputs/local-runtime/pgsql`.

Database lokal memakai port **5433**, hanya menerima koneksi loopback, dan
menyimpan data di `outputs/local-runtime/pgdata`. Nama database dan kredensial
diambil dari `.env`; launcher mengatur URL database dan path penyimpanan untuk
Windows tanpa mengubah `.env`. Data volume Docker tidak otomatis tersedia di
database baru ini. Jangan menghapus `pgdata` bila ingin mempertahankan data lokal.

Untuk menghentikan semua layanan:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-local.ps1
```
