# Akses database dengan pgAdmin

Buka **http://127.0.0.1:5051**. Login menggunakan `PGADMIN_DEFAULT_EMAIL` dan `PGADMIN_DEFAULT_PASSWORD` dari file `.env` di root proyek. Akun web pgAdmin berbeda dari akun PostgreSQL.

## Melihat tabel dan data

1. Buka **Servers > Aplikasi > Dispatch Intelligence** pada Object Explorer.
2. Buka **Databases > dispatch_intelligence > Schemas > public > Tables** (nama database mengikuti `POSTGRES_DB`).
3. Klik kanan tabel, lalu pilih **View/Edit Data > First 100 Rows** untuk melihat isi tabel.
4. Gunakan **Query Tool** untuk menjalankan SQL. Contoh untuk melihat daftar tabel:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

## Diagram relasi

Klik kanan database atau schema, lalu pilih **ERD For Database** atau **ERD For Schema** untuk melihat tabel dan relasi foreign key. Untuk diagram lebih kecil, buka **Tools > ERD Tool** dan tambahkan tabel yang diperlukan. Relasi yang hanya ditentukan oleh logika aplikasi dan tidak memiliki foreign key tidak otomatis muncul.

## Konfigurasi Docker

- Service: `pgadmin`, image resmi `dpage/pgadmin4:9.18`.
- Port lokal: `PGADMIN_PORT` (default `5051`); akses terikat ke `127.0.0.1`.
- Host database dari pgAdmin: `db`, port `5432`.
- Nama database, username, dan password koneksi mengikuti `POSTGRES_DB`, `POSTGRES_USER`, dan `POSTGRES_PASSWORD` di `.env`.
- Definisi server dibuat otomatis pada inisialisasi pertama. Password koneksi disiapkan melalui file `.pgpass` dengan izin `0600`, sehingga tidak perlu diketik ulang.
- Volume `pgadmin_data` menyimpan akun, konfigurasi, dan pekerjaan pgAdmin; volume `postgres_data` tetap menyimpan database aplikasi.
- `PGADMIN_DEFAULT_EMAIL` dan `PGADMIN_DEFAULT_PASSWORD` membuat akun saat inisialisasi pertama. Mengganti nilainya setelah itu tidak mengganti akun yang sudah ada; gunakan menu akun pgAdmin untuk perubahan login.
- Bila username atau nama database diubah setelah inisialisasi, sesuaikan **Properties** pada server tersimpan. Password PostgreSQL juga harus benar-benar diubah pada database; mengedit `.env` saja tidak mengganti password database yang sudah ada.

Jalankan dari root proyek setelah mengisi `PGADMIN_DEFAULT_PASSWORD`:

```bash
docker compose up -d pgadmin
docker compose ps pgadmin
docker compose logs --tail 50 pgadmin
```

Referensi: [deployment container pgAdmin](https://www.pgadmin.org/docs/pgadmin4/9.18/container_deployment.html).
