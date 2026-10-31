@echo off
setlocal
title Dispatch Analyzer - Installer Localhost
echo Instalasi lengkap Dispatch Analyzer, dengan restricted roads berbasis Google Routes.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-docker.ps1" %*
set "installer_result=%errorlevel%"
echo.
if "%installer_result%"=="3010" echo Restart Windows, lalu jalankan install.cmd kembali untuk melanjutkan.
if not "%installer_result%"=="0" if not "%installer_result%"=="3010" echo Instalasi belum berhasil. Lihat pesan di atas.
pause
exit /b %installer_result%
