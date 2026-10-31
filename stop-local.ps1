$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtime = Join-Path $projectRoot 'outputs/local-runtime'
if (Test-Path "$runtime/processes.json") {
    foreach ($servicePid in (Get-Content "$runtime/processes.json" | ConvertFrom-Json)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$servicePid"
        if ($process -and ($process.CommandLine -like '*scripts*local-run.py*' -or $process.CommandLine -like '*node_modules/vite/bin/vite.js*')) {
            & taskkill.exe /PID $servicePid /T /F | Out-Null
        }
    }
    Remove-Item -LiteralPath "$runtime/processes.json"
}
& "$projectRoot/.venv/Scripts/python.exe" "$projectRoot/scripts/local-run.py" stop-database
if ($LASTEXITCODE) { throw 'Database gagal dihentikan. Periksa log lokal.' }
Write-Host 'Layanan lokal dihentikan. Data database tetap tersimpan.'
