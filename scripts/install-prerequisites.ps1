$ErrorActionPreference = 'Stop'
try {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (!$admin) {
        Write-Host 'Meminta izin Administrator untuk memasang Docker Desktop / WSL...'
        $child = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"')
        exit $child.ExitCode
    }
    $restart = $false
    $dockerPresent = Get-Command docker.exe -ErrorAction SilentlyContinue
    foreach ($candidate in @("$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe")) {
        if (Test-Path -LiteralPath $candidate) { $dockerPresent = $true }
    }
    if (!$dockerPresent) {
        if (!(Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw 'WinGet belum tersedia. Pasang/update App Installer dari Microsoft Store, lalu jalankan install.cmd kembali.' }
        Write-Host 'Memasang Docker Desktop melalui WinGet...'
        & winget.exe install --id Docker.DockerDesktop --exact --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity
        $result = $LASTEXITCODE
        if ($result -in @(3010, 1641)) { $restart = $true }
        elseif ($result -ne 0) { throw "Pemasangan Docker Desktop gagal (exit $result)." }
    }
    foreach ($featureName in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $featureName
        if ($feature.State -ne 'Enabled') {
            Write-Host "Mengaktifkan $featureName..."
            $null = Enable-WindowsOptionalFeature -Online -FeatureName $featureName -All -NoRestart
            $restart = $true
        }
    }
    if ($restart) {
        Write-Host 'Komponen Windows disiapkan. Restart Windows, lalu klik install.cmd kembali untuk melanjutkan.' -ForegroundColor Yellow
        exit 3010
    }
    $ErrorActionPreference = 'Continue'
    & wsl.exe --version *> $null
    $wslReady = $LASTEXITCODE -eq 0
    $ErrorActionPreference = 'Stop'
    if (!$wslReady) {
        Write-Host 'Memasang WSL tanpa distribusi Ubuntu tambahan...'
        & wsl.exe --install --no-distribution
        if ($LASTEXITCODE -notin @(0, 3010, 1641)) { throw "Pemasangan WSL gagal (exit $LASTEXITCODE)." }
        if ($LASTEXITCODE -ne 0) { exit 3010 }
    }
    & wsl.exe --update
    if ($LASTEXITCODE -ne 0) { throw "Update WSL gagal (exit $LASTEXITCODE)." }
    & wsl.exe --set-default-version 2
    if ($LASTEXITCODE -ne 0) { throw 'WSL 2 belum siap. Periksa virtualisasi BIOS/UEFI dan restart Windows.' }
    exit 0
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
