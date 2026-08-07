"""
app.py
OCI FinOps Monitor — Streamlit dashboard entry point.

Run locally (Windows or anywhere):
    pip install -r requirements.txt
    streamlit run app.py

Works in two modes:
  - Demo Mode:  synthetic data, no OCI credentials needed. Good for testing
                the dashboard on your laptop right now.
  - Live Mode:  reads real cost/usage/resource data from your OCI tenancy
                via the OCI Python SDK. Needs ~/.oci/config (laptop) or
                Instance Principal auth (when deployed on the OCI VM).
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

import config as cfg
import mock_data
import oci_client
import analyzer

st.set_page_config(
    page_title=cfg.APP_NAME,
    page_icon=cfg.APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------------
# Styling
# ----------------------------------------------------------------------------
st.markdown("""
<style>
    .kpi-card {
        background: linear-gradient(145deg, #161B22 0%, #1D232B 100%);
        border: 1px solid #2A2F38;
        border-radius: 14px;
        padding: 18px 20px;
        height: 100%;
    }
    .kpi-label {
        font-size: 0.80rem;
        color: #9AA4B2;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 6px;
    }
    .kpi-value {
        font-size: 1.9rem;
        font-weight: 700;
        color: #F2F2F2;
    }
    .kpi-delta-up { color: #FF6B5A; font-size: 0.85rem; }
    .kpi-delta-down { color: #3DDC97; font-size: 0.85rem; }
    .rec-card {
        border-radius: 12px;
        padding: 14px 18px;
        margin-bottom: 10px;
        border-left: 5px solid #555;
        background-color: #161B22;
    }
    .rec-high { border-left-color: #FF5A5A; }
    .rec-medium { border-left-color: #FFB020; }
    .rec-low { border-left-color: #3DDC97; }
    .rec-title { font-weight: 700; font-size: 1.02rem; color: #F2F2F2; }
    .rec-meta { color: #9AA4B2; font-size: 0.8rem; margin-bottom: 6px; }
    .rec-savings { color: #3DDC97; font-weight: 700; }
    .badge {
        display: inline-block; padding: 2px 10px; border-radius: 999px;
        font-size: 0.72rem; font-weight: 700; margin-right: 6px;
    }
    .badge-high { background-color: #3A1A1A; color: #FF8A7A; }
    .badge-medium { background-color: #3A2E10; color: #FFC168; }
    .badge-low { background-color: #123024; color: #6EE8B5; }
    section[data-testid="stSidebar"] { border-right: 1px solid #2A2F38; }
</style>
""", unsafe_allow_html=True)

SEVERITY_CLASS = {"High": "rec-high", "Medium": "rec-medium", "Low": "rec-low"}
BADGE_CLASS = {"High": "badge-high", "Medium": "badge-medium", "Low": "badge-low"}


# ----------------------------------------------------------------------------
# Sidebar — mode & filters
# ----------------------------------------------------------------------------
with st.sidebar:
    st.markdown(f"## {cfg.APP_ICON} {cfg.APP_NAME}")
    st.caption("Oracle Cloud Infrastructure spend monitoring & recommendations")

    st.markdown("---")
    mode = st.radio(
        "Data source",
        ["Demo Mode (sample data)", "Live OCI"],
        index=0 if not cfg.oci_config_available() else 1,
        help="Demo Mode works immediately with no setup. Live OCI needs a "
             "configured ~/.oci/config or Instance Principal auth.",
    )
    live_mode = mode == "Live OCI"

    tenancy_id = None
    use_instance_principal = False
    connection_ok = False
    connection_msg = ""

    if live_mode:
        use_instance_principal = st.checkbox(
            "Use Instance Principal (running on an OCI VM)", value=False,
            help="Enable this when this app runs ON an OCI compute instance "
                 "with a dynamic group / policy granting it read access. "
                 "Leave unchecked when testing from your laptop with "
                 "~/.oci/config.",
        )
        if not use_instance_principal:
            st.text_input("OCI config file path", value=cfg.get_oci_config_path(),
                           disabled=True)
        tenancy_id = st.text_input("Tenancy OCID", value="", placeholder="ocid1.tenancy.oc1..xxxx")

        if st.button("Test connection", use_container_width=True):
            connection_ok, connection_msg = oci_client.test_connection(use_instance_principal)
            if connection_ok:
                st.success(connection_msg)
            else:
                st.error(connection_msg)

    st.markdown("---")
    days_back = st.slider("History window (days)", 14, 180, 90, step=7)
    st.markdown("---")
    st.caption(
        "Estimated costs & savings shown here are illustrative approximations "
        "unless pulled directly from the OCI Usage API. Always confirm against "
        "the OCI Cost Analysis console before acting."
    )

st.markdown(f"# {cfg.APP_ICON} {cfg.APP_NAME}")
st.caption(f"Last refreshed: {datetime.now():%A, %B %d %Y — %H:%M} · Mode: **{mode}**")


# ----------------------------------------------------------------------------
# Data loading (live with graceful fallback to demo)
# ----------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def load_demo_data(days):
    return {
        "daily_spend": mock_data.get_daily_spend(days),
        "instances": mock_data.get_compute_instances(),
        "volumes": mock_data.get_block_volumes(),
        "budgets": mock_data.get_budgets(),
    }


def load_live_data(tenancy_id, use_instance_principal, days):
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    daily_spend = oci_client.fetch_usage_data(tenancy_id, start, end, use_instance_principal)
    compartments = oci_client.list_compartments(tenancy_id, use_instance_principal) or []

    all_instances, all_volumes = [], []
    for c in compartments:
        inst = oci_client.list_compute_instances_with_cpu(c["id"], cfg.IDLE_LOOKBACK_DAYS, use_instance_principal)
        if inst is not None and not inst.empty:
            all_instances.append(inst)
        vol = oci_client.list_unattached_block_volumes(c["id"], use_instance_principal)
        if vol is not None and not vol.empty:
            all_volumes.append(vol)

    instances = pd.concat(all_instances, ignore_index=True) if all_instances else pd.DataFrame()
    volumes = pd.concat(all_volumes, ignore_index=True) if all_volumes else pd.DataFrame()
    budgets = oci_client.list_budgets(tenancy_id, use_instance_principal)

    return {
        "daily_spend": daily_spend,
        "instances": instances,
        "volumes": volumes,
        "budgets": budgets,
    }, (daily_spend is None and instances.empty)


data_is_fallback = False
if live_mode and tenancy_id:
    live_data, failed = load_live_data(tenancy_id, use_instance_principal, days_back)
    if failed:
        st.warning(
            "Couldn't retrieve live data (check credentials / IAM policy / tenancy OCID). "
            "Showing demo data instead so you can still explore the dashboard.",
            icon="⚠️",
        )
        data = load_demo_data(days_back)
        data_is_fallback = True
    else:
        data = live_data
        # backfill anything that failed individually with empty frames
        for k in ("daily_spend", "instances", "volumes", "budgets"):
            if data.get(k) is None:
                data[k] = pd.DataFrame()
else:
    if live_mode and not tenancy_id:
        st.info("Enter your Tenancy OCID in the sidebar to pull live data. Showing demo data for now.", icon="ℹ️")
    data = load_demo_data(days_back)
    data_is_fallback = live_mode

daily_spend = data["daily_spend"] if data["daily_spend"] is not None else pd.DataFrame()
instances = data["instances"] if data["instances"] is not None else pd.DataFrame()
volumes = data["volumes"] if data["volumes"] is not None else pd.DataFrame()
budgets = data["budgets"] if data["budgets"] is not None else pd.DataFrame()

if data_is_fallback:
    st.caption("🔶 Currently displaying **sample data** — connect Live OCI in the sidebar for real figures.")


# ----------------------------------------------------------------------------
# KPI calculations
# ----------------------------------------------------------------------------
today = daily_spend["date"].max() if not daily_spend.empty else pd.Timestamp(datetime.utcnow().date())
mtd_start = pd.Timestamp(today.replace(day=1)) if not daily_spend.empty else None

if not daily_spend.empty:
    mtd_mask = daily_spend["date"] >= mtd_start
    mtd_spend = daily_spend.loc[mtd_mask, "cost"].sum()
    days_elapsed = max((today - mtd_start).days + 1, 1)
    days_in_month = pd.Period(today, freq="M").days_in_month
    forecast = mtd_spend / days_elapsed * days_in_month

    prev_month_end = mtd_start - pd.Timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    prev_mask = (daily_spend["date"] >= prev_month_start) & (daily_spend["date"] <= prev_month_end)
    prev_month_spend = daily_spend.loc[prev_mask, "cost"].sum()

    last7 = daily_spend[daily_spend["date"] > today - pd.Timedelta(days=7)]["cost"].sum()
    prior7 = daily_spend[(daily_spend["date"] <= today - pd.Timedelta(days=7)) &
                          (daily_spend["date"] > today - pd.Timedelta(days=14))]["cost"].sum()
    wow_change = ((last7 - prior7) / prior7 * 100) if prior7 else 0
else:
    mtd_spend = forecast = prev_month_spend = wow_change = 0

recommendations = analyzer.generate_all_recommendations(
    instances=instances if not instances.empty else None,
    volumes=volumes if not volumes.empty else None,
    budgets=budgets if not budgets.empty else None,
    spend_by_compartment=(daily_spend.groupby("compartment")["cost"].sum()
                           if not daily_spend.empty else None),
    daily_spend=daily_spend if not daily_spend.empty else None,
)
total_potential_savings = sum(r.estimated_monthly_savings for r in recommendations)
high_severity_count = sum(1 for r in recommendations if r.severity == "High")


# ----------------------------------------------------------------------------
# KPI row
# ----------------------------------------------------------------------------
def kpi_card(label, value, delta=None, delta_positive_is_bad=True):
    delta_html = ""
    if delta is not None:
        arrow = "▲" if delta >= 0 else "▼"
        bad = (delta >= 0) if delta_positive_is_bad else (delta < 0)
        cls = "kpi-delta-up" if bad else "kpi-delta-down"
        delta_html = f'<div class="{cls}">{arrow} {abs(delta):.1f}% vs prior week</div>'
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {delta_html}
    </div>
    """

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(kpi_card("Month-to-Date Spend", f"${mtd_spend:,.0f}", wow_change), unsafe_allow_html=True)
with k2:
    mom = ((forecast - prev_month_spend) / prev_month_spend * 100) if prev_month_spend else 0
    st.markdown(kpi_card("Forecasted Month-End", f"${forecast:,.0f}", mom), unsafe_allow_html=True)
with k3:
    st.markdown(kpi_card("Potential Monthly Savings", f"${total_potential_savings:,.0f}",
                          delta=None), unsafe_allow_html=True)
with k4:
    st.markdown(kpi_card("High-Priority Alerts", f"{high_severity_count}", delta=None),
                unsafe_allow_html=True)

st.write("")

# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------
tab_overview, tab_breakdown, tab_recs, tab_anomalies, tab_help = st.tabs(
    ["📈 Overview", "🧭 Cost Breakdown", "💡 Recommendations", "🚨 Anomalies", "⚙️ Setup"]
)

# ---- Overview ----
with tab_overview:
    if daily_spend.empty:
        st.info("No spend data available yet.")
    else:
        trend = daily_spend.groupby("date", as_index=False)["cost"].sum()
        fig = px.area(trend, x="date", y="cost", title="Daily Total Spend")
        fig.update_traces(line_color="#FF5A1F", fillcolor="rgba(255,90,31,0.15)")
        fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font_color="#E6E6E6", margin=dict(t=50, l=10, r=10, b=10),
            yaxis_title="Cost (USD)", xaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            by_service = daily_spend.groupby("service", as_index=False)["cost"].sum().sort_values("cost", ascending=True)
            fig2 = px.bar(by_service, x="cost", y="service", orientation="h",
                          title="Total Spend by Service", color="cost",
                          color_continuous_scale=["#3DDC97", "#FFB020", "#FF5A5A"])
            fig2.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               font_color="#E6E6E6", showlegend=False, coloraxis_showscale=False,
                               margin=dict(t=50, l=10, r=10, b=10), xaxis_title="", yaxis_title="")
            st.plotly_chart(fig2, use_container_width=True)
        with c2:
            weekly = trend.copy()
            weekly["week"] = pd.to_datetime(weekly["date"]).dt.to_period("W").apply(lambda p: p.start_time)
            weekly = weekly.groupby("week", as_index=False)["cost"].sum()
            fig3 = px.bar(weekly, x="week", y="cost", title="Weekly Spend Trend")
            fig3.update_traces(marker_color="#4C8DFF")
            fig3.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               font_color="#E6E6E6", margin=dict(t=50, l=10, r=10, b=10),
                               yaxis_title="Cost (USD)", xaxis_title="")
            st.plotly_chart(fig3, use_container_width=True)

# ---- Cost Breakdown ----
with tab_breakdown:
    if daily_spend.empty:
        st.info("No spend data available yet.")
    else:
        c1, c2 = st.columns([1, 1])
        with c1:
            by_service = daily_spend.groupby("service", as_index=False)["cost"].sum()
            fig = px.pie(by_service, names="service", values="cost", hole=0.55,
                        title="Spend Share by Service")
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#E6E6E6",
                              margin=dict(t=50, l=10, r=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            by_comp = daily_spend.groupby("compartment", as_index=False)["cost"].sum()
            fig = px.pie(by_comp, names="compartment", values="cost", hole=0.55,
                        title="Spend Share by Compartment")
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#E6E6E6",
                              margin=dict(t=50, l=10, r=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Spend detail")
        pivot = daily_spend.pivot_table(index="service", columns="compartment", values="cost", aggfunc="sum", fill_value=0)
        pivot["Total"] = pivot.sum(axis=1)
        pivot = pivot.sort_values("Total", ascending=False).round(2)
        try:
            styled = pivot.style.background_gradient(cmap="Oranges", subset=pivot.columns[:-1])
            st.dataframe(styled, use_container_width=True)
        except ImportError:
            # matplotlib not installed — fall back to a plain table rather than crash
            st.dataframe(pivot, use_container_width=True)

# ---- Recommendations ----
with tab_recs:
    if not recommendations:
        st.success("No recommendations right now — spend and resource usage look healthy.")
    else:
        cats = sorted(set(r.category for r in recommendations))
        sel_cats = st.multiselect("Filter by category", cats, default=cats)
        filtered = [r for r in recommendations if r.category in sel_cats]

        st.caption(f"{len(filtered)} recommendation(s) · up to "
                   f"${sum(r.estimated_monthly_savings for r in filtered):,.0f}/mo in potential savings")

        for r in filtered:
            savings_html = (f'<span class="rec-savings">Est. savings: ${r.estimated_monthly_savings:,.0f}/mo</span>'
                            if r.estimated_monthly_savings else "")
            st.markdown(f"""
            <div class="rec-card {SEVERITY_CLASS.get(r.severity,'')}">
                <span class="badge {BADGE_CLASS.get(r.severity,'')}">{r.severity}</span>
                <span class="badge" style="background-color:#1E2733;color:#9AA4B2;">{r.category}</span>
                <div class="rec-title">{r.title}</div>
                <div class="rec-meta">{r.resource}</div>
                <div>{r.description}</div>
                <div style="margin-top:6px;">{savings_html}</div>
            </div>
            """, unsafe_allow_html=True)

# ---- Anomalies ----
with tab_anomalies:
    anomaly_recs = [r for r in recommendations if r.category == "Anomaly"]
    if daily_spend.empty:
        st.info("No spend data available yet.")
    elif not anomaly_recs:
        st.success("No cost anomalies detected in the selected window.")
    else:
        for r in anomaly_recs:
            st.markdown(f"""
            <div class="rec-card {SEVERITY_CLASS.get(r.severity,'')}">
                <span class="badge {BADGE_CLASS.get(r.severity,'')}">{r.severity}</span>
                <div class="rec-title">{r.title}</div>
                <div>{r.description}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("#### Spend vs. rolling baseline")
        service_pick = st.selectbox("Service", sorted(daily_spend["service"].unique()))
        g = daily_spend[daily_spend["service"] == service_pick].groupby("date", as_index=False)["cost"].sum().sort_values("date")
        g["baseline"] = g["cost"].rolling(7, min_periods=1).mean()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["date"], y=g["cost"], name="Daily cost", line=dict(color="#FF5A1F")))
        fig.add_trace(go.Scatter(x=g["date"], y=g["baseline"], name="7-day baseline",
                                 line=dict(color="#4C8DFF", dash="dash")))
        fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          font_color="#E6E6E6", margin=dict(t=20, l=10, r=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

# ---- Setup / Help ----
with tab_help:
    st.markdown("""
### Getting this connected to your real OCI tenancy

**1. IAM policy (read-only is enough)** — create a group (e.g. `finops-readers`) and attach a policy like:

```
Allow group finops-readers to read usage-reports in tenancy
Allow group finops-readers to read compartments in tenancy
Allow group finops-readers to inspect compute-instances in tenancy
Allow group finops-readers to read compute-instances in tenancy
Allow group finops-readers to read metrics in tenancy
Allow group finops-readers to read volumes in tenancy
Allow group finops-readers to read volume-attachments in tenancy
Allow group finops-readers to read budgets in tenancy
```

**2. Auth on your laptop** — install the OCI CLI or just create `~/.oci/config`
(`%USERPROFILE%\\.oci\\config` on Windows) with an API key pair generated for
your user, then set the mode to **Live OCI** in the sidebar.

**3. Auth on the Windows VM (recommended for the deployed version)** —
skip API keys entirely. Put the VM in a **dynamic group** matching its OCID,
and grant that dynamic group the same read policies above. Then in the app,
check **"Use Instance Principal"** — no config file needed at all.

**4. Running continuously on the VM** — either:
   - Use Windows **Task Scheduler** to run `run_windows.bat` at startup, or
   - Wrap it as a Windows service with [NSSM](https://nssm.cc/), or
   - Just leave `streamlit run app.py` running in a terminal window.

   By default Streamlit serves on `http://localhost:8501` — open the VM's
   security list / NSG to your IP on that port (or put it behind a reverse
   proxy) if you need to view it remotely.

**5. Costs shown here** — spend figures come straight from the OCI Usage API
when Live OCI is connected. Savings estimates for idle/right-sizing
recommendations are approximations based on shape and OCPU count — always
verify in **Cost Analysis** before making changes.
""")
