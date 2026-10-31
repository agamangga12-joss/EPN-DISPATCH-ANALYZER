param(
    [switch]$CheckOnly,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Invoke-Docker {
    param([string[]]$DockerArgs)
    & $script:dockerExe @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Perintah Docker gagal (exit $LASTEXITCODE): docker $($DockerArgs -join ' ')" }
}

function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Test-DockerEngine {
    if (!$script:dockerExe) { return $false }
    $ErrorActionPreference = 'Continue'
    & $script:dockerExe info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Get-EnvValue {
    param([string]$Name)
    $match = [regex]::Match($script:envText, '(?m)^\s*' + [regex]::Escape($Name) + '\s*=([^\r\n]*)')
    if ($match.Success) { return $match.Groups[1].Value.Trim().Trim([char]34).Trim([char]39) }
    return ''
}

try {
    Write-Host "Folder aplikasi: $projectRoot"
    foreach ($required in @('docker-compose.yml', '.env.example', 'apps/api/Dockerfile', 'apps/web/Dockerfile')) {
        if (!(Test-Path -LiteralPath (Join-Path $projectRoot $required))) { throw "File project tidak ditemukan: $required. Salin seluruh folder project." }
    }
    $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
    $script:dockerExe = if ($dockerCommand) { $dockerCommand.Source } else { $null }
    if (!$script:dockerExe) {
        foreach ($candidate in @("$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe")) {
            if (Test-Path -LiteralPath $candidate) { $script:dockerExe = $candidate; break }
        }
    }
    if (!$CheckOnly -and !(Test-DockerEngine)) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'install-prerequisites.ps1')
        $prereqResult = $LASTEXITCODE
        if ($prereqResult -eq 3010) {
            Write-Host 'Restart Windows lalu jalankan install.cmd kembali. Instalasi akan melanjutkan dengan komponen yang sudah terpasang.' -ForegroundColor Yellow
            exit 3010
        }
        if ($prereqResult -ne 0) { throw 'Persiapan Docker/WSL belum berhasil. Lihat pesan di atas.' }
        $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
        if ($dockerCommand) { $script:dockerExe = $dockerCommand.Source }
        foreach ($candidate in @("$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe")) {
            if (Test-Path -LiteralPath $candidate) { $script:dockerExe = $candidate; break }
        }
    }
    if (!$script:dockerExe) { throw 'Docker Desktop belum ditemukan. Jalankan install.cmd kembali setelah instalasi/restart selesai.' }
    Invoke-Docker -DockerArgs @('compose', 'version')
    if ($CheckOnly) {
        Invoke-Docker -DockerArgs @('info', '--format', '{{.OSType}}')
        Write-Host 'Pemeriksaan selesai. Tidak ada konfigurasi atau container yang diubah.'
        exit 0
    }

    if (!(Test-DockerEngine)) {
        foreach ($desktop in @("$env:ProgramFiles\Docker\Docker\Docker Desktop.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe")) {
            if (Test-Path -LiteralPath $desktop) { Start-Process -FilePath $desktop -WindowStyle Hidden; break }
        }
        Write-Host 'Menunggu Docker Engine (maksimal 120 detik)...'
        $deadline = (Get-Date).AddSeconds(120)
        do {
            Start-Sleep -Seconds 3
            if (Test-DockerEngine) { break }
        } while ((Get-Date) -lt $deadline)
        if (!(Test-DockerEngine)) { throw 'Docker Engine belum siap. Buka Docker Desktop, selesaikan layar persetujuan/penyiapan pertama, periksa WSL 2/virtualisasi, lalu ulangi installer.' }
    }
    $osType = & $script:dockerExe info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0 -or "$osType".Trim() -ne 'linux') { throw 'Aktifkan Linux containers di Docker Desktop, lalu ulangi installer.' }

    $envPath = Join-Path $projectRoot '.env'
    if (!(Test-Path -LiteralPath $envPath)) {
        Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $envPath
        Write-Host '.env dibuat dari .env.example.'
    }
    $script:envText = [IO.File]::ReadAllText($envPath)
    $changed = $false
    foreach ($key in @('GOOGLE_ROUTES_ENCRYPTION_KEY', 'PGADMIN_DEFAULT_PASSWORD')) {
        if ([string]::IsNullOrWhiteSpace((Get-EnvValue $key))) {
            $replacement = $key + '=' + (New-Secret)
            $pattern = '(?m)^\s*' + [regex]::Escape($key) + '\s*=[^\r\n]*'
            if ([regex]::IsMatch($script:envText, $pattern)) {
                $script:envText = [regex]::Replace($script:envText, $pattern, $replacement)
            } else { $script:envText += "`r`n$replacement`r`n" }
            $changed = $true
            Write-Host "$key disiapkan otomatis di .env."
        }
    }
    if ((Get-EnvValue 'GOOGLE_ROUTES_ENCRYPTION_KEY').Length -lt 16) { throw 'GOOGLE_ROUTES_ENCRYPTION_KEY di .env harus minimal 16 karakter. Nilai yang ada tidak diubah otomatis.' }
    if ($changed) { [IO.File]::WriteAllText($envPath, $script:envText, (New-Object Text.UTF8Encoding($false))) }

    # Always use this folder's Compose and .env, independent of the caller's directory.
    $compose = @('compose', '--project-directory', $projectRoot, '--env-file', $envPath, '-f', (Join-Path $projectRoot 'docker-compose.yml'))
    Invoke-Docker -DockerArgs ($compose + @('config', '--quiet'))
    $runningApi = & $script:dockerExe @compose ps --status running -q api
    if ($LASTEXITCODE -ne 0) { throw 'Tidak dapat memeriksa layanan aplikasi yang sudah berjalan.' }
    if ($runningApi) {
        $jobCheck = 'from app.database import engine; from sqlalchemy import inspect,text; c=engine.connect(); print(c.execute(text("select count(*) from optimization_job where status=:status"), {"status":"CALCULATING"}).scalar() if inspect(engine).has_table("optimization_job") else 0); c.close()'
        # Encode constant source to avoid PowerShell 5 native-argument quoting
        # changing Python string literals passed through Docker.
        $jobCheckBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($jobCheck))
        $jobCheckCommand = "import base64;exec(base64.b64decode('$jobCheckBase64'))"
        $calculating = & $script:dockerExe @compose exec -T api python -c $jobCheckCommand
        if ($LASTEXITCODE -ne 0) { throw 'Tidak dapat memeriksa optimasi aktif. Periksa API/database sebelum memperbarui layanan.' }
        if ("$calculating".Trim() -ne '0') { throw 'Masih ada optimasi CALCULATING. Tunggu sampai selesai, lalu jalankan installer kembali agar perhitungan tidak terputus.' }
    }
    Write-Host 'Membangun dan menjalankan layanan. Build pertama memerlukan internet dan dapat memakan beberapa menit...'
    & $script:dockerExe @compose up -d --build --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) {
        & $script:dockerExe @compose ps -a
        & $script:dockerExe @compose logs --tail=80 api db web
        throw 'Layanan belum siap. Periksa log di atas. Jika port terpakai, hentikan aplikasi yang memakai port tersebut atau ubah port di .env.'
    }
    $port = Get-EnvValue 'WEB_PORT'
    if (!$port) { $port = '3000' }
    $url = "http://localhost:$port"
    try { $null = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15 } catch { throw "Container berjalan, tetapi web belum dapat diakses di $url. Periksa WEB_PORT dan log web." }
    Write-Host "Aplikasi siap: $url" -ForegroundColor Green
    Write-Host 'Restricted roads memakai Google Routes. Atur API key pada Google Maps Integration, lalu lengkapi waypoint pengalihan di master depot.' -ForegroundColor Green
    Write-Host 'Untuk menjalankan lagi, klik install.cmd. Konfigurasi dan volume data tetap dipakai.'
    if (!$NoBrowser) { Start-Process $url }
    exit 0
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
