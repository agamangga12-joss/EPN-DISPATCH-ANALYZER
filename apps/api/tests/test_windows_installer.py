"""Exercise the Windows installer without downloading maps or touching Docker."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
POWERSHELL = shutil.which("powershell.exe")


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.fixture
def installer_workspace(tmp_path):
    project = tmp_path / "project with spaces"
    for name in ["scripts/install-docker.ps1", "docker-compose.yml",
                 ".env.example", "apps/api/Dockerfile", "apps/web/Dockerfile"]:
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    map_file = tmp_path / "map with spaces.osm.pbf"
    map_file.write_bytes(b"\x00\x00\x00\x0aOSMHeader\x00installer-test")
    (project / ".env").write_text("WEB_PORT=3000\nGOOGLE_ROUTES_ENCRYPTION_KEY=keep-this-existing-secret-12345678\nPGADMIN_DEFAULT_PASSWORD=keep-this-password\n", encoding="utf-8")
    return project, map_file


def run_installer(project, arguments="", scenario="success"):
    log = project / "docker-calls.jsonl"
    runner = project / "runner.ps1"
    runner.write_text(f"""
$scenario = {ps_quote(scenario)}
$dockerLog = {ps_quote(log)}
function Get-Command {{
    param([string]$Name)
    if ($Name -eq 'docker.exe') {{ return [pscustomobject]@{{ Source = 'Invoke-FakeDocker' }} }}
    Microsoft.PowerShell.Core\\Get-Command $Name
}}
function Invoke-FakeDocker {{
    $items = @($args)
    [IO.File]::AppendAllText($dockerLog, (ConvertTo-Json -InputObject $items -Compress) + "`n")
    $global:LASTEXITCODE = 0
    if ($items[0] -eq 'info' -and $items -contains '{{{{.OSType}}}}') {{ 'linux' }}
    elseif ($items[0] -eq 'info' -and $items -contains '{{{{.MemTotal}}}}') {{
        if ($scenario -eq 'low-memory') {{ '1073741824' }} else {{ '12884901888' }}
    }}
    elseif ($items -contains 'ps' -and $scenario -eq 'active-job') {{ 'fake-api-container' }}
    elseif ($items -contains 'exec' -and $items -contains '-c') {{ '1' }}
    elseif ($items -contains 'up' -and $scenario -eq 'startup-failure') {{ $global:LASTEXITCODE = 1 }}
}}
function Invoke-WebRequest {{ return [pscustomobject]@{{ StatusCode = 200 }} }}
function Start-Process {{ throw 'The test must never open a browser.' }}
. {ps_quote(project / 'scripts/install-docker.ps1')} {arguments}
exit $LASTEXITCODE
""", encoding="utf-8")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner)],
                            capture_output=True, text=True, timeout=30)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell is required")
def test_complete_installer_needs_no_graphhopper_map_or_extra_memory(installer_workspace):
    project, _ = installer_workspace
    result, calls = run_installer(project, "-NoBrowser", "low-memory")
    assert result.returncode == 0, result.stdout + result.stderr
    environment = (project / ".env").read_text()
    assert "RESTRICTED_ROUTING_URL=" not in environment
    assert "keep-this-existing-secret-12345678" in environment
    assert "keep-this-password" in environment
    assert not (project / "routing-data").exists()
    assert not any("--profile" in call or "/app/services/restricted-routing/check_ready.py" in call for call in calls)
    assert any("up" in call for call in calls)
    prior = (project / ".env").read_bytes()
    result, _ = run_installer(project, "-NoBrowser")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (project / ".env").read_bytes() == prior


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell is required")
@pytest.mark.parametrize("scenario", ["startup-failure", "active-job"])
def test_installer_does_not_report_success_if_routing_or_resources_are_not_ready(installer_workspace, scenario):
    project, map_file = installer_workspace
    result, calls = run_installer(project, "-NoBrowser", scenario)
    assert result.returncode == 1
    assert "Aplikasi siap:" not in result.stdout
    if scenario == "active-job":
        assert not any("up" in call for call in calls)


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell is required")
def test_external_router_is_preserved_and_checked_without_local_map(installer_workspace):
    project, _ = installer_workspace
    with (project / ".env").open("a") as stream:
        stream.write("RESTRICTED_ROUTING_URL=http://existing-router:8989\nRESTRICTED_ROUTING_PROFILE=tanker\n")
    result, calls = run_installer(project, "-NoBrowser")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (project / "routing-data").exists()
    assert "RESTRICTED_ROUTING_PROFILE=tanker" in (project / ".env").read_text()
    assert not any("--profile" in call for call in calls)
    assert not any("/app/services/restricted-routing/check_ready.py" in call for call in calls)


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell is required")
def test_check_only_keeps_environment_and_map_unchanged(installer_workspace):
    project, _ = installer_workspace
    before = (project / ".env").read_bytes()
    result, calls = run_installer(project, "-CheckOnly")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (project / ".env").read_bytes() == before
    assert not (project / "routing-data").exists()
    assert not any("up" in call for call in calls)






