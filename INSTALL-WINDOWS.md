# Installer Windows

Salin seluruh folder project ke PC tujuan lalu klik dua kali `install.cmd`.
Lokasi folder bebas, termasuk drive berbeda dan nama folder dengan spasi.
`install.cmd` harus tetap berada di sebelah `docker-compose.yml`; folder `scripts`
dan seluruh source aplikasi juga harus ikut disalin.

## Persiapan PC tujuan

- Windows 10/11 yang didukung Docker Desktop, virtualisasi BIOS/UEFI aktif,
  dan akses Administrator untuk memasang komponen Windows.
- WinGet (App Installer dari Microsoft Store) tersedia untuk pemasangan Docker otomatis.
- Installer memasang Docker Desktop jika belum ada, mengaktifkan fitur Windows
  WSL/VirtualMachinePlatform, memasang/update WSL, lalu menjalankan build aplikasi.
  Klik Yes pada permintaan Administrator. Jika diminta restart, restart Windows
  lalu klik `install.cmd` kembali; langkah yang sudah selesai tidak diulang.
  Selesaikan layar persetujuan/penyiapan pertama Docker Desktop jika muncul.
- Internet untuk download image dan dependency saat build pertama.
- Port bawaan 3000 (web), 8000 (API), 5432 (database), dan 5051 (pgAdmin) tersedia.
  Jika start-local.ps1 sedang berjalan, jalankan stop-local.ps1 dahulu.

Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/

Jika Docker Engine sudah berjalan, pemasangan prasyarat dilewati. Installer mencari Docker, mencoba membuka Docker Desktop jika engine belum aktif,
membuat `.env` dari `.env.example` jika belum ada, dan mengisi kunci enkripsi serta
password pgAdmin yang kosong dengan nilai acak. Nilai yang sudah terisi dipertahankan.
Restricted roads menggunakan Google Routes dan waypoint pengalihan operator;
installer tidak memasang GraphHopper atau mengunduh `.osm.pbf`. Setelah build dan
health check aplikasi berhasil, browser terbuka ke localhost pada WEB_PORT.
Installer dapat dijalankan kembali untuk build perubahan dan menyalakan aplikasi.
Tidak perlu memasang Python, Node.js, atau PostgreSQL terpisah di PC tujuan.

## Restricted roads

Setelah aplikasi terbuka, konfigurasikan API key di **Google Maps Integration**.
Operator kemudian memasukkan ruas terlarang dan waypoint pengalihan untuk setiap
arah yang berlaku pada **Master Restricted Roads**. Tidak perlu layanan routing
lokal, file peta atau alokasi RAM khusus GraphHopper. Instalasi baru tetap dapat
dibuka sebelum API key dikonfigurasi; optimasi yang memakai larangan memerlukan
API key valid dan waypoint lengkap.

Installer menolak memperbarui layanan jika masih ada job `CALCULATING`, agar
perhitungan tidak terputus. Opsi `-NoBrowser` tersedia untuk penggunaan otomatis.
Konfigurasi dan volume data yang sudah ada tetap dipertahankan, termasuk riwayat
rute lama. Variabel `RESTRICTED_ROUTING_*` lama tidak lagi digunakan; berkas peta
dan volume GraphHopper lama tidak dihapus otomatis.

Jika hanya ingin memeriksa prasyarat tanpa mengubah konfigurasi/container:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-docker.ps1 -CheckOnly
```

## Data dan konfigurasi

Menyalin folder source tidak menyalin data di volume Docker. PC baru akan memakai
database baru. Untuk membawa data lama, lakukan backup/restore database dan volume
upload/model yang dibutuhkan secara terpisah. Pertahankan kunci enkripsi `.env`
jika memulihkan database yang berisi Google API key terenkripsi.

Untuk distribusi instalasi baru, gunakan `.env.example` dan jangan sertakan `.env`
pribadi. Installer akan membuat konfigurasi baru. pgAdmin memakai desktop mode:
buka http://localhost:5051 langsung tanpa login atau master password. Akses port
pgAdmin dibatasi ke komputer lokal (127.0.0.1). PGADMIN_DEFAULT_EMAIL dan
PGADMIN_DEFAULT_PASSWORD di `.env` tetap diperlukan untuk inisialisasi container.
Koneksi database memakai password file yang disiapkan otomatis.
Untuk menerapkan perubahan pada instalasi lama, jalankan
`docker compose up -d --force-recreate pgadmin`.

## Menghentikan / memeriksa

Buka terminal di folder project:

```powershell
docker compose down
docker compose ps -a
docker compose logs --tail=100 api
```

`down` mempertahankan volume data. Installer menampilkan log jika startup gagal
dan tidak menghapus database. Jika port bentrok, sesuaikan `.env`. Pada konfigurasi
frontend yang memakai VITE_API_BASE_URL secara eksplisit, sesuaikan URL tersebut
juga jika API_PORT diubah. Pengaturan environment di terminal dapat menimpa `.env`
sesuai perilaku standar Docker Compose.
