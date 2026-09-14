@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto :failed

where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv is not installed or is not on PATH.
    goto :failed
)

echo Preparing the locked Python environment...
call uv sync --locked
if errorlevel 1 goto :failed

echo Clearing TCP port 8507. Any listening process will be stopped.
powershell.exe -NoProfile -Command "$ErrorActionPreference = 'Stop'; try { $listeners = @(Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 8507); foreach ($owner in @($listeners.OwningProcess | Sort-Object -Unique)) { if ($null -eq $owner) { continue }; $current = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 8507 -and $_.OwningProcess -eq $owner }); if ($current.Count) { Write-Host ('Stopping PID ' + $owner); Stop-Process -Id $owner -Force -ErrorAction Stop } }; $deadline = [DateTime]::UtcNow.AddSeconds(5); do { $remaining = @(Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 8507); if (-not $remaining.Count) { exit 0 }; Start-Sleep -Milliseconds 200 } while ([DateTime]::UtcNow -lt $deadline); throw 'Port 8507 is still occupied.' } catch { Write-Host ('ERROR: Cannot clear port 8507. ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 goto :failed

echo Opening http://127.0.0.1:8507
echo Keep this window open. Press Ctrl+C to stop the app.
call uv run --no-sync streamlit run streamlit_app.py --server.port=8507 --server.address=127.0.0.1 --server.headless=false
if errorlevel 1 goto :failed
exit /b 0

:failed
echo Launcher failed. Review the error above.
pause
exit /b 1
