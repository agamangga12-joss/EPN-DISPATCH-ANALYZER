$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
$runner = Join-Path $projectRoot 'scripts/local-run.py'
$runtime = Join-Path $projectRoot 'outputs/local-runtime'
if (Test-Path "$runtime/processes.json") {
    foreach ($servicePid in (Get-Content "$runtime/processes.json" | ConvertFrom-Json)) {
        if (Get-Process -Id $servicePid -ErrorAction SilentlyContinue) {
            throw 'Proses lokal masih berjalan. Jalankan .\stop-local.ps1 sebelum start ulang.'
        }
    }
}
if (!(Test-Path $pythonExe) -or !(Test-Path "$runtime/pgsql/bin/pg_ctl.exe")) {
    throw 'Python .venv dan PostgreSQL portable belum disiapkan. Lihat docs/LOCAL_WINDOWS.md.'
}
& $pythonExe $runner database
if ($LASTEXITCODE) { throw 'Database gagal dijalankan.' }
& $pythonExe $runner migrate
if ($LASTEXITCODE) { throw 'Migrasi gagal.' }
$processes = @()
foreach ($service in @('api', 'phase6_worker', 'import_worker')) {
    $process = Start-Process $pythonExe -ArgumentList ('"' + $runner + '"'), $service -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput "$runtime/$service.log" -RedirectStandardError "$runtime/$service-error.log" -PassThru
    $processes += $process.Id
}
$nodeExe = (Get-Command node.exe).Source
$web = Start-Process $nodeExe -ArgumentList 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '3000', '--strictPort' -WorkingDirectory "$projectRoot/apps/web" -WindowStyle Hidden -RedirectStandardOutput "$runtime/web.log" -RedirectStandardError "$runtime/web-error.log" -PassThru
$processes += $web.Id
$processes | ConvertTo-Json | Set-Content "$runtime/processes.json"
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2
        $ready = $true
        break
    } catch { Start-Sleep -Seconds 2 }
}
if (!$ready) { throw "API belum siap. Periksa $runtime/api-error.log; hentikan layanan dengan .\stop-local.ps1." }
Write-Host 'Web: http://127.0.0.1:3000 | API: http://127.0.0.1:8000/api/v1/health'
Write-Host "Log: $runtime"
