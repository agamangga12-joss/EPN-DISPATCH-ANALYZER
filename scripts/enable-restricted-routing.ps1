param([string]$MapFile, [switch]$NoBrowser)
Write-Host 'Restricted roads kini memakai Google Routes dan waypoint operator. File peta tidak diperlukan; jalankan installer aplikasi.'
& (Join-Path $PSScriptRoot 'install-docker.ps1') -NoBrowser:$NoBrowser
exit $LASTEXITCODE
