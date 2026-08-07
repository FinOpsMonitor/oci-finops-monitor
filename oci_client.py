"""
oci_client.py
Thin wrapper around the OCI Python SDK. Every function fails soft: if auth
isn't configured, a permission is missing, or the SDK isn't installed, it
returns None (or an empty DataFrame) instead of raising, so app.py can
fall back to demo data and keep the dashboard usable.

Auth resolution order (standard OCI SDK behaviour):
  1. ~/.oci/config (or OCI_CONFIG_FILE env var)         -> for your laptop
  2. Instance Principal (no keys needed at all)          -> recommended for
                                                             the Windows VM
                                                             once deployed
"""

from datetime import datetime, timedelta
import pandas as pd

try:
    import oci
    OCI_SDK_AVAILABLE = True
except ImportError:
    OCI_SDK_AVAILABLE = False

from config import get_oci_config_path, oci_config_available


def get_signer_and_config(use_instance_principal: bool = False):
    """Returns (config_dict_or_None, signer_or_None). Never raises."""
    if not OCI_SDK_AVAILABLE:
        return None, None

    if use_instance_principal:
        try:
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            return {}, signer
        except Exception:
            return None, None

    try:
        config = oci.config.from_file(file_location=get_oci_config_path())
        oci.config.validate_config(config)
        return config, None
    except Exception:
        return None, None


def test_connection(use_instance_principal: bool = False):
    """Quick sanity check: can we reach OCI Identity with these creds?
    Returns (ok: bool, message: str)."""
    if not OCI_SDK_AVAILABLE:
        return False, "The 'oci' Python SDK is not installed (pip install oci)."

    config, signer = get_signer_and_config(use_instance_principal)
    if config is None and signer is None:
        return False, "No usable OCI credentials found."

    try:
        if signer:
            identity = oci.identity.IdentityClient(config={}, signer=signer)
            tenancy_id = signer.tenancy_id
        else:
            identity = oci.identity.IdentityClient(config)
            tenancy_id = config["tenancy"]
        identity.get_tenancy(tenancy_id).data
        return True, "Connected to OCI successfully."
    except Exception as e:
        return False, f"Connection failed: {e}"


def fetch_usage_data(tenancy_id: str, start: datetime, end: datetime,
                      use_instance_principal: bool = False):
    """Pulls daily cost data grouped by service via the Usage API.
    Returns a DataFrame with columns [date, service, compartment, cost] or
    None on failure."""
    if not OCI_SDK_AVAILABLE:
        return None

    config, signer = get_signer_and_config(use_instance_principal)
    if config is None and signer is None:
        return None

    try:
        client = (oci.usage_api.UsageapiClient(config={}, signer=signer)
                  if signer else oci.usage_api.UsageapiClient(config))

        details = oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=tenancy_id,
            time_usage_started=start,
            time_usage_ended=end,
            granularity="DAILY",
            group_by=["service", "compartmentName"],
        )
        response = client.request_summarized_usages(details)
        rows = []
        for item in response.data.items:
            rows.append({
                "date": item.time_usage_started.date(),
                "service": item.service or "Other",
                "compartment": item.compartment_name or "root",
                "cost": float(item.computed_amount or 0.0),
            })
        return pd.DataFrame(rows)
    except Exception:
        return None


def list_compartments(tenancy_id: str, use_instance_principal: bool = False):
    if not OCI_SDK_AVAILABLE:
        return None
    config, signer = get_signer_and_config(use_instance_principal)
    if config is None and signer is None:
        return None
    try:
        client = (oci.identity.IdentityClient(config={}, signer=signer)
                  if signer else oci.identity.IdentityClient(config))
        comps = oci.pagination.list_call_get_all_results(
            client.list_compartments, tenancy_id,
            compartment_id_in_subtree=True, lifecycle_state="ACTIVE"
        ).data
        return [{"id": c.id, "name": c.name} for c in comps]
    except Exception:
        return None


def list_compute_instances_with_cpu(compartment_id: str, lookback_days: int = 14,
                                     use_instance_principal: bool = False):
    """Returns a DataFrame of instances with average CPU utilization over
    the lookback window (via the Monitoring service), or None on failure."""
    if not OCI_SDK_AVAILABLE:
        return None
    config, signer = get_signer_and_config(use_instance_principal)
    if config is None and signer is None:
        return None
    try:
        compute = (oci.core.ComputeClient(config={}, signer=signer)
                   if signer else oci.core.ComputeClient(config))
        monitoring = (oci.monitoring.MonitoringClient(config={}, signer=signer)
                      if signer else oci.monitoring.MonitoringClient(config))

        instances = oci.pagination.list_call_get_all_results(
            compute.list_instances, compartment_id,
            lifecycle_state="RUNNING"
        ).data

        rows = []
        end = datetime.utcnow()
        start = end - timedelta(days=lookback_days)
        for inst in instances:
            avg_cpu = None
            try:
                query = f'CpuUtilization[1d]{{resourceId = "{inst.id}"}}.mean()'
                details = oci.monitoring.models.SummarizeMetricsDataDetails(
                    namespace="oci_computeagent",
                    query=query,
                    start_time=start,
                    end_time=end,
                )
                metric_resp = monitoring.summarize_metrics_data(compartment_id, details)
                if metric_resp.data:
                    points = metric_resp.data[0].aggregated_datapoints
                    if points:
                        avg_cpu = sum(p.value for p in points) / len(points)
            except Exception:
                pass

            rows.append({
                "instance_name": inst.display_name,
                "instance_id": inst.id,
                "compartment": compartment_id,
                "shape": inst.shape,
                "ocpus": getattr(inst.shape_config, "ocpus", None) if inst.shape_config else None,
                "memory_gb": getattr(inst.shape_config, "memory_in_gbs", None) if inst.shape_config else None,
                "avg_cpu_pct_14d": round(avg_cpu, 1) if avg_cpu is not None else None,
                "state": inst.lifecycle_state,
                "lifecycle_days": (datetime.utcnow() - inst.time_created.replace(tzinfo=None)).days,
            })
        return pd.DataFrame(rows)
    except Exception:
        return None


def list_unattached_block_volumes(compartment_id: str, use_instance_principal: bool = False):
    if not OCI_SDK_AVAILABLE:
        return None
    config, signer = get_signer_and_config(use_instance_principal)
    if config is None and signer is None:
        return None
    try:
        blockstorage = (oci.core.BlockstorageClient(config={}, signer=signer)
                        if signer else oci.core.BlockstorageClient(config))
        compute = (oci.core.ComputeClient(config={}, signer=signer)
                  if signer else oci.core.ComputeClient(config))

        volumes = oci.pagination.list_call_get_all_results(
            blockstorage.list_volumes, compartment_id
        ).data
        attachments = oci.pagination.list_call_get_all_results(
            compute.list_volume_attachments, compartment_id
        ).data
        attached_ids = {a.volume_id for a in attachments}

        rows = []
        for v in volumes:
            rows.append({
                "volume_name": v.display_name,
                "volume_id": v.id,
                "compartment": compartment_id,
                "size_gb": v.size_in_gbs,
                "attached": v.id in attached_ids,
                "created_days_ago": (datetime.utcnow() - v.time_created.replace(tzinfo=None)).days,
                "monthly_cost_estimate": round((v.size_in_gbs or 0) * 0.0255 * 30, 2),
            })
        return pd.DataFrame(rows)
    except Exception:
        return None


def list_budgets(tenancy_id: str, use_instance_principal: bool = False):
    if not OCI_SDK_AVAILABLE:
        return None
    config, signer = get_signer_and_config(use_instance_principal)
    if config is None and signer is None:
        return None
    try:
        client = (oci.budget.BudgetClient(config={}, signer=signer)
                 if signer else oci.budget.BudgetClient(config))
        budgets = oci.pagination.list_call_get_all_results(
            client.list_budgets, compartment_id=tenancy_id, target_type="ALL"
        ).data
        rows = [{
            "budget_name": b.display_name,
            "amount": b.amount,
            "compartment": b.target_compartment_id or "root",
        } for b in budgets]
        return pd.DataFrame(rows)
    except Exception:
        return None
