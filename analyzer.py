"""
analyzer.py
Turns raw spend / resource data into concrete, prioritized FinOps
recommendations. Pure functions, no I/O — easy to unit test.
"""

from dataclasses import dataclass, field
from typing import List
import pandas as pd
import numpy as np

import config as cfg


@dataclass
class Recommendation:
    title: str
    category: str          # "Idle Resource" | "Right-Sizing" | "Storage" | "Budget" | "Anomaly"
    severity: str           # "High" | "Medium" | "Low"
    description: str
    estimated_monthly_savings: float = 0.0
    resource: str = ""

    def severity_rank(self) -> int:
        return {"High": 0, "Medium": 1, "Low": 2}.get(self.severity, 3)


def _shape_hourly_rate(shape: str, ocpus: float) -> float:
    per_ocpu = cfg.SHAPE_HOURLY_COST_ESTIMATE.get(shape)
    if per_ocpu is None:
        return 0.04 * (ocpus or 1)
    if shape.startswith("BM."):
        return per_ocpu  # flat rate already
    return per_ocpu * (ocpus or 1)


def find_idle_instances(instances: pd.DataFrame) -> List[Recommendation]:
    recs = []
    if instances is None or instances.empty:
        return recs
    idle = instances[instances["avg_cpu_pct_14d"] < cfg.IDLE_CPU_THRESHOLD_PCT]
    for _, row in idle.iterrows():
        hourly = _shape_hourly_rate(row["shape"], row.get("ocpus") or 1)
        monthly = hourly * 24 * 30
        recs.append(Recommendation(
            title=f"Idle instance: {row['instance_name']}",
            category="Idle Resource",
            severity="High",
            description=(
                f"Average CPU utilization was only {row['avg_cpu_pct_14d']}% over the last "
                f"{cfg.IDLE_LOOKBACK_DAYS} days ({row['shape']}, {row.get('ocpus','?')} OCPUs). "
                f"Consider stopping, terminating, or moving this workload to a smaller / "
                f"burstable shape if it's still needed."
            ),
            estimated_monthly_savings=round(monthly, 2),
            resource=row["instance_name"],
        ))
    return recs


def find_underutilized_instances(instances: pd.DataFrame) -> List[Recommendation]:
    recs = []
    if instances is None or instances.empty:
        return recs
    mask = (instances["avg_cpu_pct_14d"] >= cfg.IDLE_CPU_THRESHOLD_PCT) & \
           (instances["avg_cpu_pct_14d"] < cfg.UNDERUTILIZED_CPU_THRESHOLD_PCT)
    for _, row in instances[mask].iterrows():
        hourly = _shape_hourly_rate(row["shape"], row.get("ocpus") or 1)
        monthly = hourly * 24 * 30
        # assume right-sizing to half the OCPUs saves ~35% of instance cost
        potential_savings = round(monthly * 0.35, 2)
        recs.append(Recommendation(
            title=f"Right-sizing candidate: {row['instance_name']}",
            category="Right-Sizing",
            severity="Medium",
            description=(
                f"Running at {row['avg_cpu_pct_14d']}% average CPU on {row.get('ocpus','?')} "
                f"OCPUs ({row['shape']}). This looks oversized for its actual load — "
                f"consider dropping to a smaller flex shape."
            ),
            estimated_monthly_savings=potential_savings,
            resource=row["instance_name"],
        ))
    return recs


def find_unattached_volumes(volumes: pd.DataFrame) -> List[Recommendation]:
    recs = []
    if volumes is None or volumes.empty:
        return recs
    unattached = volumes[~volumes["attached"]]
    for _, row in unattached.iterrows():
        recs.append(Recommendation(
            title=f"Unattached volume: {row['volume_name']}",
            category="Storage",
            severity="Medium" if row["created_days_ago"] > 30 else "Low",
            description=(
                f"{row['size_gb']} GB volume has no attached instance and has existed for "
                f"{row['created_days_ago']} days. If it's no longer needed, delete it "
                f"(back it up first if unsure)."
            ),
            estimated_monthly_savings=round(row["monthly_cost_estimate"], 2),
            resource=row["volume_name"],
        ))
    return recs


def budget_alerts(budgets: pd.DataFrame, spend_by_compartment: pd.Series) -> List[Recommendation]:
    recs = []
    if budgets is None or budgets.empty:
        return recs
    for _, row in budgets.iterrows():
        actual = spend_by_compartment.get(row["compartment"], None)
        if actual is None:
            continue
        pct = (actual / row["amount"]) * 100 if row["amount"] else 0
        if pct >= cfg.BUDGET_CRITICAL_PCT:
            recs.append(Recommendation(
                title=f"Budget exceeded: {row['budget_name']}",
                category="Budget",
                severity="High",
                description=(
                    f"Month-to-date spend (${actual:,.0f}) has exceeded the "
                    f"${row['amount']:,.0f} budget ({pct:.0f}%) for compartment "
                    f"'{row['compartment']}'."
                ),
                resource=row["budget_name"],
            ))
        elif pct >= cfg.BUDGET_WARNING_PCT:
            recs.append(Recommendation(
                title=f"Approaching budget: {row['budget_name']}",
                category="Budget",
                severity="Medium",
                description=(
                    f"Month-to-date spend (${actual:,.0f}) is at {pct:.0f}% of the "
                    f"${row['amount']:,.0f} budget for compartment '{row['compartment']}'."
                ),
                resource=row["budget_name"],
            ))
    return recs


def detect_anomalies(daily_spend: pd.DataFrame) -> List[Recommendation]:
    """Flags days where total spend deviated sharply from the trailing
    average, per service."""
    recs = []
    if daily_spend is None or daily_spend.empty:
        return recs

    for service, g in daily_spend.groupby("service"):
        g = g.groupby("date", as_index=False)["cost"].sum().sort_values("date")
        if len(g) < 10:
            continue
        rolling_mean = g["cost"].rolling(7, min_periods=5).mean()
        rolling_std = g["cost"].rolling(7, min_periods=5).std()
        threshold = rolling_mean + cfg.ANOMALY_STD_DEV_MULTIPLIER * rolling_std
        anomalies = g[g["cost"] > threshold]
        for _, row in anomalies.tail(3).iterrows():  # most recent few only
            baseline = rolling_mean.loc[row.name]
            if pd.isna(baseline) or baseline <= 0:
                continue
            pct_over = ((row["cost"] - baseline) / baseline) * 100
            recs.append(Recommendation(
                title=f"Spend spike in {service}",
                category="Anomaly",
                severity="High" if pct_over > 100 else "Medium",
                description=(
                    f"On {row['date']:%b %d}, {service} cost ${row['cost']:,.2f}, "
                    f"{pct_over:.0f}% above its recent 7-day baseline of ${baseline:,.2f}. "
                    f"Worth checking for a forgotten job, scaling event, or misconfiguration."
                ),
                resource=service,
            ))
    return recs


def generate_all_recommendations(instances=None, volumes=None, budgets=None,
                                  spend_by_compartment=None,
                                  daily_spend=None) -> List[Recommendation]:
    recs: List[Recommendation] = []
    recs += find_idle_instances(instances)
    recs += find_underutilized_instances(instances)
    recs += find_unattached_volumes(volumes)
    if budgets is not None and spend_by_compartment is not None:
        recs += budget_alerts(budgets, spend_by_compartment)
    if daily_spend is not None:
        recs += detect_anomalies(daily_spend)

    recs.sort(key=lambda r: (r.severity_rank(), -r.estimated_monthly_savings))
    return recs
