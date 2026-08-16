<powershell>
# =====================================================================
# CloudServ OCI FinOps Monitor - Windows bootstrap script
# Runs once via the Oracle Cloud Agent on first boot.
# =====================================================================

$ErrorActionPreference = "Stop"
$logFile = "C:\finops-bootstrap.log"
Start-Transcript -Path $logFile -Append

Write-Output "Starting CloudServ FinOps Monitor bootstrap..."

# ---- 1. Install Chocolatey (package manager) ----
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# ---- 2. Install Python and Git ----
choco install -y python3 --version=3.11.8
choco install -y git
refreshenv

$python = "C:\Python311\python.exe"
if (-not (Test-Path $python)) {
    $python = (Get-Command python).Source
}

# ---- 3. Pull the application code ----
$appDir = "C:\CloudServ\FinOpsMonitor"
New-Item -ItemType Directory -Force -Path "C:\CloudServ" | Out-Null

git clone "${app_repo_url}" $appDir

# ---- 4. Install Python dependencies ----
Set-Location $appDir
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt

# ---- 5. Open the Windows Firewall for the app port ----
New-NetFirewallRule -DisplayName "FinOps Monitor (Streamlit)" `
    -Direction Inbound -Protocol TCP -LocalPort ${app_port} -Action Allow

# ---- 6. Register a scheduled task to run the app at startup ----
$taskName = "CloudServ FinOps Monitor"
$action = New-ScheduledTaskAction -Execute $python `
    -Argument "-m streamlit run app.py --server.port=${app_port} --server.address=0.0.0.0" `
    -WorkingDirectory $appDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force

# ---- 7. Start it immediately so the VM is usable without a reboot ----
Start-ScheduledTask -TaskName $taskName

Write-Output "CloudServ FinOps Monitor bootstrap complete. Dashboard should be reachable on port ${app_port}."
Stop-Transcript
</powershell>
