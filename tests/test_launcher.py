"""Windows launcher checks without stopping real processes or calling the API."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
LAUNCHER = Path(__file__).resolve().parents[1] / "launch.cmd"
SYSTEM32 = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"


@pytest.mark.parametrize("setup_fails", [False, True], ids=["missing-uv", "sync-fails"])
def test_setup_failure_stops_before_port_cleanup(tmp_path: Path, setup_fails: bool) -> None:
    project = tmp_path / "project with spaces"
    project.mkdir()
    launcher = project / "launch.cmd"
    launcher.write_bytes(LAUNCHER.read_bytes())
    if setup_fails:
        (project / "uv.cmd").write_text("@echo off\necho Simulated setup failure\nexit /b 9\n")
    environment = {**os.environ, "PATH": str(SYSTEM32)}
    result = subprocess.run(
        [str(SYSTEM32 / "cmd.exe"), "/d", "/c", str(launcher)],
        cwd=tmp_path,
        env=environment,
        input="\n",
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 1
    assert "Launcher failed" in result.stdout
    assert "Clearing TCP port" not in result.stdout
    assert ("Simulated setup failure" if setup_fails else "uv is not installed") in result.stdout


@pytest.mark.parametrize("scenario", ["free", "busy", "denied", "reoccupied", "query-fails"])
def test_port_cleanup(scenario: str) -> None:
    line = next(
        line for line in LAUNCHER.read_text().splitlines() if line.startswith("powershell.exe")
    )
    command = line.split('-Command "', 1)[1][:-1]
    # Mock Windows process operations, retaining the launcher's actual control flow.
    mock = """
$script:stopped = $false
function Get-NetTCPConnection {
    param($State)
    if ($scenario -eq 'query-fails') { throw 'Simulated query failure' }
    [pscustomobject]@{ LocalPort = 8501; OwningProcess = 111 }
    if ($scenario -ne 'free' -and (-not $script:stopped -or $scenario -eq 'reoccupied')) {
        [pscustomobject]@{ LocalPort = 8507; OwningProcess = 222 }
        [pscustomobject]@{ LocalPort = 8507; OwningProcess = 222 }
    }
}
function Stop-Process {
    param($Id, [switch]$Force, $ErrorAction)
    if ($Id -ne 222) { throw 'Wrong process selected' }
    Write-Output "STOP:$Id"
    if ($scenario -eq 'denied') { throw 'Simulated access denied' }
    $script:stopped = $true
}
"""
    result = subprocess.run(
        [
            str(SYSTEM32 / "WindowsPowerShell/v1.0/powershell.exe"),
            "-NoProfile",
            "-Command",
            f"$scenario = '{scenario}';\n{mock}\n{command}",
        ],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == (0 if scenario in {"free", "busy"} else 1), result.stdout
    assert "STOP:111" not in result.stdout
    assert result.stdout.count("STOP:222") == (0 if scenario in {"free", "query-fails"} else 1)
    if scenario == "reoccupied":
        assert "still occupied" in result.stdout
