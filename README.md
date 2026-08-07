# OCI FinOps Monitor

A Python/Streamlit dashboard that monitors Oracle Cloud Infrastructure (OCI)
spend and surfaces cost-saving recommendations: idle compute instances,
right-sizing candidates, unattached block volumes, budget threshold alerts,
and spend anomalies.

Runs entirely client-side (no external servers) — either on your Windows
laptop for testing, or on a Windows VM in OCI for ongoing monitoring.

## Quick start (Windows laptop, no OCI account needed yet)

1. Install [Python 3.10+](https://www.python.org/downloads/) if you don't
   already have it (check "Add Python to PATH" during install).
2. Unzip this folder anywhere, e.g. `C:\Tools\oci-finops-dashboard`.
3. Double-click **`run_windows.bat`**.
   - First run creates a virtual environment and installs dependencies
     (needs internet access) — takes a minute or two.
   - It then opens the dashboard at **http://localhost:8501** in your
     browser automatically.
4. Leave the sidebar on **"Demo Mode"** — you'll see a fully populated
   dashboard with realistic sample data, no OCI credentials required.

### Command line, if you prefer

```
pip install -r requirements.txt
streamlit run app.py
```

## Connecting to your real OCI tenancy

See the **⚙️ Setup** tab inside the running app for full details. Short
version:

1. Create a read-only IAM policy (usage reports, compartments, compute,
   metrics, volumes, budgets — see the Setup tab for the exact statements).
2. On your laptop: set up `~/.oci/config` (standard OCI CLI config), switch
   the sidebar to **Live OCI**, enter your Tenancy OCID, click **Test
   connection**.
3. On the Windows VM (recommended long-term): put the VM in a **dynamic
   group**, grant it the same read policies, and check **"Use Instance
   Principal"** in the sidebar — no API keys needed on the VM at all.

## Deploying on the Windows VM in OCI

- Copy this folder to the VM.
- Run `run_windows.bat` once to set up the virtual environment.
- To keep it running continuously, either:
  - Add a **Windows Task Scheduler** entry that runs `run_windows.bat` at
    startup / logon, or
  - Wrap it as a proper Windows service using [NSSM](https://nssm.cc/), or
  - Just leave it running in a terminal / RDP session.
- Streamlit serves on port `8501` by default. Open that port on the VM's
  NSG/Security List only to the IPs that need dashboard access, or put a
  reverse proxy (IIS, nginx) with auth in front of it if it needs to be
  reachable more broadly.

## Project layout

```
app.py            Streamlit dashboard (UI, charts, KPI cards, tabs)
oci_client.py      OCI SDK calls (usage, compute, monitoring, volumes, budgets)
analyzer.py        Recommendation engine (idle/right-sizing/storage/budget/anomaly)
mock_data.py        Demo data generator used when Live OCI isn't connected
config.py          Thresholds, paths, and settings
requirements.txt   Python dependencies
run_windows.bat     One-click launcher for Windows
```

## Notes on accuracy

- Spend figures in **Live OCI** mode come directly from the OCI Usage API.
- Estimated savings for idle/right-sizing recommendations are
  approximations based on shape + OCPU count using illustrative hourly
  rates in `config.py` — update `SHAPE_HOURLY_COST_ESTIMATE` with your
  actual negotiated rates for more accurate numbers, or cross-check
  against OCI Cost Analysis before acting on any recommendation.
- This tool never modifies or deletes anything in your tenancy — it's
  read-only / advisory.
