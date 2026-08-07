"""
config.py
Central place for settings, thresholds and small helpers used across the
FinOps dashboard. Nothing here talks to OCI directly.
"""

import os
from pathlib import Path

APP_NAME = "OCI FinOps Monitor"
APP_ICON = "💰"

# Default OCI config file location (same on Windows: %USERPROFILE%\.oci\config)
DEFAULT_OCI_CONFIG_PATH = str(Path.home() / ".oci" / "config")

# ---- Recommendation engine thresholds (tweak to taste) --------------------
IDLE_CPU_THRESHOLD_PCT = 5.0        # avg CPU below this over the window = "idle"
IDLE_LOOKBACK_DAYS = 14             # how many days of metrics to evaluate
UNDERUTILIZED_CPU_THRESHOLD_PCT = 20.0  # candidate for a smaller shape
ANOMALY_STD_DEV_MULTIPLIER = 2.0    # spend spike sensitivity
BUDGET_WARNING_PCT = 80.0           # warn when forecast crosses this % of budget
BUDGET_CRITICAL_PCT = 100.0

# Rough on-demand hourly cost table (USD) used only to estimate savings when
# the Usage API can't be reached / in demo mode. These are illustrative,
# not official OCI list prices — always show as "estimated".
SHAPE_HOURLY_COST_ESTIMATE = {
    "VM.Standard.E4.Flex": 0.03,     # per OCPU/hr, approx
    "VM.Standard.E5.Flex": 0.034,
    "VM.Standard3.Flex": 0.05,
    "VM.Standard.A1.Flex": 0.01,
    "VM.DenseIO.E4.Flex": 0.07,
    "BM.Standard.E4.128": 6.4,
}

DEFAULT_CURRENCY = "USD"


def get_oci_config_path() -> str:
    return os.environ.get("OCI_CONFIG_FILE", DEFAULT_OCI_CONFIG_PATH)


def oci_config_available() -> bool:
    """True if a real OCI CLI config file appears to exist locally."""
    return Path(get_oci_config_path()).is_file()
