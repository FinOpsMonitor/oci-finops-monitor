"""
mock_data.py
Generates realistic-looking OCI spend / resource data so the dashboard is
fully usable without live OCI credentials. Swapped out automatically for
real oci_client calls once a valid ~/.oci/config is detected (or Instance
Principal auth is available on the VM).
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

SERVICES = [
    "Compute", "Block Storage", "Object Storage", "Database",
    "Networking / Load Balancer", "Monitoring & Logging", "Autonomous Database",
]

COMPARTMENTS = ["root", "prod-workloads", "dev-test", "shared-networking", "data-platform"]

REGIONS = ["me-jeddah-1", "me-dubai-1", "us-ashburn-1"]

rng = np.random.default_rng(42)


def _service_base_rate(service: str) -> float:
    return {
        "Compute": 145.0,
        "Block Storage": 22.0,
        "Object Storage": 9.0,
        "Database": 180.0,
        "Networking / Load Balancer": 14.0,
        "Monitoring & Logging": 4.0,
        "Autonomous Database": 95.0,
    }.get(service, 20.0)


def get_daily_spend(days: int = 90) -> pd.DataFrame:
    """Daily spend by service for the trailing `days` days, with a
    realistic weekly pattern, slow growth trend, and a couple of injected
    anomalies so the anomaly detector has something to find."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=days - 1)
    dates = pd.date_range(start, end, freq="D")

    rows = []
    for service in SERVICES:
        base = _service_base_rate(service)
        trend = np.linspace(0, base * 0.15, len(dates))  # mild upward drift
        weekday_factor = np.array([1.0 if d.weekday() < 5 else 0.6 for d in dates])
        noise = rng.normal(0, base * 0.06, len(dates))
        values = (base + trend) * weekday_factor + noise
        values = np.clip(values, base * 0.2, None)

        # inject a couple of anomalies (e.g. a forgotten job, a burst)
        if service in ("Compute", "Database"):
            spike_idx = rng.integers(len(dates) - 10, len(dates) - 2)
            values[spike_idx] *= rng.uniform(2.2, 3.1)

        for d, v in zip(dates, values):
            rows.append({
                "date": d,
                "service": service,
                "compartment": rng.choice(COMPARTMENTS, p=[0.05, 0.45, 0.25, 0.15, 0.10]),
                "region": rng.choice(REGIONS, p=[0.5, 0.3, 0.2]),
                "cost": round(float(v), 2),
            })

    return pd.DataFrame(rows)


def get_compute_instances() -> pd.DataFrame:
    """Mock compute inventory with recent avg CPU utilization, used for
    idle / right-sizing recommendations."""
    names = [
        "web-frontend-01", "web-frontend-02", "api-gateway-01", "batch-worker-03",
        "batch-worker-04", "legacy-report-runner", "sandbox-test-vm", "jenkins-agent-02",
        "elk-node-01", "elk-node-02", "old-poc-demo-vm", "analytics-cache-01",
    ]
    shapes = ["VM.Standard.E4.Flex", "VM.Standard.E5.Flex", "VM.Standard3.Flex", "VM.Standard.A1.Flex"]
    rows = []
    for i, name in enumerate(names):
        # deliberately make a few of these idle / oversized for interesting recs
        if name in ("sandbox-test-vm", "old-poc-demo-vm", "legacy-report-runner"):
            avg_cpu = rng.uniform(0.5, 4.0)
        elif name in ("elk-node-01", "jenkins-agent-02"):
            avg_cpu = rng.uniform(8, 18)
        else:
            avg_cpu = rng.uniform(15, 70)

        ocpus = int(rng.choice([1, 2, 4, 8]))
        rows.append({
            "instance_name": name,
            "instance_id": f"ocid1.instance.oc1.mock.{i:04d}",
            "compartment": rng.choice(COMPARTMENTS[1:]),
            "shape": rng.choice(shapes),
            "ocpus": ocpus,
            "memory_gb": ocpus * rng.choice([4, 8, 16]),
            "avg_cpu_pct_14d": round(float(avg_cpu), 1),
            "state": "RUNNING",
            "lifecycle_days": int(rng.integers(3, 420)),
        })
    return pd.DataFrame(rows)


def get_block_volumes() -> pd.DataFrame:
    """Mock block volumes, some deliberately unattached."""
    rows = []
    names = [f"vol-{i:03d}" for i in range(1, 15)]
    for i, name in enumerate(names):
        attached = rng.random() > 0.28  # ~28% unattached
        size_gb = int(rng.choice([50, 100, 200, 500, 1024]))
        rows.append({
            "volume_name": name,
            "volume_id": f"ocid1.volume.oc1.mock.{i:04d}",
            "compartment": rng.choice(COMPARTMENTS[1:]),
            "size_gb": size_gb,
            "attached": attached,
            "created_days_ago": int(rng.integers(1, 500)),
            "monthly_cost_estimate": round(size_gb * 0.0255 * 30, 2),
        })
    return pd.DataFrame(rows)


def get_budgets() -> pd.DataFrame:
    return pd.DataFrame([
        {"budget_name": "Monthly Tenancy Budget", "amount": 12000.0, "compartment": "root"},
        {"budget_name": "Prod Workloads", "amount": 7000.0, "compartment": "prod-workloads"},
        {"budget_name": "Dev / Test", "amount": 1500.0, "compartment": "dev-test"},
    ])
