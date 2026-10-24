"""
app.py — InfraGuard AI Streamlit Dashboard with Resilience Twin

A professional engineering dashboard for infrastructure resilience simulation.
Uses the shared InfraGuard simulation engine for all logic.

Run: venv\\Scripts\\streamlit.exe run app.py
"""

import streamlit as st
import plotly.graph_objects as go
import networkx as nx
from copy import deepcopy
from datetime import datetime, timezone

from infraguard.simulation import InfraGuardSimulation
from infraguard.routing import check_route, get_route_summary
from infraguard.recovery import (
    activate_backup,
    recover_component,
    get_available_backups,
)

# ──────────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="InfraGuard AI — Infrastructure Resilience",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────
# Custom CSS — dark navy engineering dashboard
# ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* Main app background */
.stApp {
    background: linear-gradient(135deg, #0a0e27 0%, #0d1535 50%, #0a1628 100%);
    font-family: 'Inter', sans-serif;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1535 0%, #111d42 100%);
    border-right: 1px solid rgba(59, 130, 246, 0.2);
}

section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3 {
    color: #e2e8f0 !important;
}

/* Headers */
h1, h2, h3, h4, h5, h6 {
    color: #e2e8f0 !important;
    font-family: 'Inter', sans-serif !important;
}

/* Metric cards */
[data-testid="stMetric"] {
    background: rgba(15, 23, 60, 0.8);
    border: 1px solid rgba(59, 130, 246, 0.25);
    border-radius: 12px;
    padding: 16px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

[data-testid="stMetric"] label {
    color: #94a3b8 !important;
}

[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: #e2e8f0 !important;
}

/* Expanders */
.streamlit-expanderHeader {
    background: rgba(15, 23, 60, 0.6) !important;
    border: 1px solid rgba(59, 130, 246, 0.2) !important;
    border-radius: 8px !important;
    color: #e2e8f0 !important;
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 8px 24px !important;
    transition: all 0.3s ease !important;
}

.stButton > button:hover {
    background: linear-gradient(135deg, #2563eb 0%, #60a5fa 100%) !important;
    box-shadow: 0 4px 15px rgba(59, 130, 246, 0.4) !important;
    transform: translateY(-1px) !important;
}

/* Selectbox */
.stSelectbox > div > div {
    background: rgba(15, 23, 60, 0.8) !important;
    border: 1px solid rgba(59, 130, 246, 0.3) !important;
    border-radius: 8px !important;
    color: #e2e8f0 !important;
}

/* Text */
.stMarkdown, .stText, p, span, li {
    color: #cbd5e1;
}

/* Divider */
hr {
    border-color: rgba(59, 130, 246, 0.2) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    background: rgba(15, 23, 60, 0.5);
    border-radius: 10px;
    padding: 4px;
}

.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #94a3b8 !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
}

.stTabs [aria-selected="true"] {
    background: rgba(59, 130, 246, 0.2) !important;
    color: #60a5fa !important;
}

/* Code blocks */
.stCodeBlock {
    background: rgba(15, 23, 60, 0.8) !important;
    border: 1px solid rgba(59, 130, 246, 0.2) !important;
}

/* Alerts / info boxes */
.stAlert {
    background: rgba(15, 23, 60, 0.6) !important;
    border: 1px solid rgba(59, 130, 246, 0.3) !important;
    border-radius: 8px !important;
}

/* Status badge styles */
.status-operational { color: #22c55e; font-weight: 600; }
.status-failed { color: #ef4444; font-weight: 600; }
.status-affected { color: #f59e0b; font-weight: 600; }
.status-restored { color: #3b82f6; font-weight: 600; }

/* Animated header glow */
.header-glow {
    text-shadow: 0 0 20px rgba(59, 130, 246, 0.5),
                 0 0 40px rgba(59, 130, 246, 0.2);
}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────
# Session state initialization
# ──────────────────────────────────────────────────────────────
if "sim" not in st.session_state:
    st.session_state.sim = InfraGuardSimulation()
if "baseline_snapshot" not in st.session_state:
    st.session_state.baseline_snapshot = None
if "recovery_snapshot" not in st.session_state:
    st.session_state.recovery_snapshot = None
if "event_log_ui" not in st.session_state:
    st.session_state.event_log_ui = []

sim: InfraGuardSimulation = st.session_state.sim


def log_ui_event(msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    st.session_state.event_log_ui.append(f"[{ts}] {msg}")


# ──────────────────────────────────────────────────────────────
# Helper — build Plotly network graph
# ──────────────────────────────────────────────────────────────
def build_network_figure(graph: nx.DiGraph, title: str = "Infrastructure Network") -> go.Figure:
    """Create a Plotly figure of the infrastructure graph."""
    # Fixed positions for consistent layout
    pos = {
        "Main Power Station":          (0.5, 1.0),
        "Backup Generator":            (0.1, 0.75),
        "Water Treatment Plant":       (0.3, 0.55),
        "Hospital":                    (0.15, 0.3),
        "Telecom Tower":               (0.7, 0.55),
        "Transport Hub":               (0.85, 0.75),
        "Emergency Response Center":   (0.55, 0.15),
        "Alternative Transport Route": (0.9, 0.35),
    }

    # State colors
    state_colors = {
        "operational": "#22c55e",
        "failed":      "#ef4444",
        "affected":    "#f59e0b",
        "restored":    "#3b82f6",
    }

    state_symbols = {
        "operational": "circle",
        "failed":      "x",
        "affected":    "diamond",
        "restored":    "square",
    }

    # Build edge traces
    edge_traces = []
    annotations = []
    for src, tgt, data in graph.edges(data=True):
        x0, y0 = pos[src]
        x1, y1 = pos[tgt]

        edge_type = data.get("type", "")
        if edge_type.startswith("backup"):
            dash = "dash"
            color = "rgba(59, 130, 246, 0.5)"
            width = 1.5
        elif edge_type == "transport":
            dash = "dot"
            color = "rgba(168, 85, 247, 0.6)"
            width = 1.5
        elif edge_type == "water":
            dash = "solid"
            color = "rgba(6, 182, 212, 0.6)"
            width = 2
        elif edge_type == "comm":
            dash = "solid"
            color = "rgba(249, 115, 22, 0.6)"
            width = 1.5
        else:  # power
            dash = "solid"
            color = "rgba(250, 204, 21, 0.7)"
            width = 2.5

        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines",
            line=dict(width=width, color=color, dash=dash),
            hoverinfo="text",
            text=f"{src} → {tgt}<br>Type: {data.get('label', edge_type)}",
            showlegend=False,
        ))

        # Arrowhead annotation
        annotations.append(dict(
            ax=x0, ay=y0, x=x1, y=y1,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True,
            arrowhead=3, arrowsize=1.2, arrowwidth=1.5,
            arrowcolor=color,
            opacity=0.5,
        ))

    # Build node traces
    node_x, node_y, node_text, node_color, node_size, node_symbol = [], [], [], [], [], []
    for name, data in graph.nodes(data=True):
        x, y = pos[name]
        node_x.append(x)
        node_y.append(y)
        state = data["state"]
        critical = " ⚡" if data.get("critical") else ""
        node_text.append(f"{name}{critical}<br>State: {state.upper()}<br>Type: {data['kind']}")
        node_color.append(state_colors.get(state, "#64748b"))
        node_size.append(28 if data.get("critical") else 22)
        node_symbol.append(state_symbols.get(state, "circle"))

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        marker=dict(
            size=node_size,
            color=node_color,
            symbol=node_symbol,
            line=dict(width=2, color="rgba(255,255,255,0.3)"),
        ),
        text=[n.replace(" ", "\n") for n in graph.nodes()],
        textposition="top center",
        textfont=dict(size=9, color="#e2e8f0", family="Inter"),
        hovertext=node_text,
        hoverinfo="text",
        showlegend=False,
    )

    fig = go.Figure(data=edge_traces + [node_trace])
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color="#e2e8f0", family="Inter")),
        showlegend=False,
        plot_bgcolor="rgba(10, 14, 39, 0.8)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.05, 1.05]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.05, 1.15]),
        margin=dict(l=20, r=20, t=50, b=20),
        height=480,
        annotations=annotations,
    )

    # Legend as shapes/text
    legend_items = [
        ("🟢 Operational", "#22c55e"), ("🔴 Failed", "#ef4444"),
        ("🟡 Affected", "#f59e0b"), ("🔵 Restored", "#3b82f6"),
    ]
    for i, (label, color) in enumerate(legend_items):
        fig.add_annotation(
            x=0.0, y=-0.02 - i * 0.04,
            text=label, showarrow=False,
            font=dict(size=10, color=color, family="Inter"),
            xanchor="left",
        )

    return fig


# ──────────────────────────────────────────────────────────────
# Sidebar — Controls
# ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛡️ InfraGuard AI")
    st.markdown("*When One Failure Becomes Many*")
    st.markdown("---")

    # Failure simulator
    st.markdown("### ⚡ Failure Simulator")
    component_names = list(sim.get_all_states().keys())
    operational = sim.get_operational_nodes()

    fail_target = st.selectbox(
        "Select component to fail",
        options=operational if operational else ["(all failed)"],
        key="fail_select",
    )
    if st.button("💥 Simulate Failure", key="fail_btn", use_container_width=True):
        if fail_target and fail_target != "(all failed)":
            st.session_state.baseline_snapshot = sim.create_snapshot()
            result = sim.fail_component(fail_target)
            if "error" not in result:
                log_ui_event(f"FAILURE: {fail_target}")
                st.session_state.baseline_snapshot = sim.create_snapshot()
            else:
                st.error(result["error"])
            st.rerun()

    st.markdown("---")

    # Backup activation
    st.markdown("### 🔋 Backup Activation")
    backups = get_available_backups(sim)
    if backups:
        backup_target = st.selectbox("Select backup", options=backups, key="backup_select")
        if st.button("⚡ Activate Backup", key="backup_btn", use_container_width=True):
            result = sim.activate_backup(backup_target)
            if "error" not in result:
                log_ui_event(f"BACKUP: {backup_target} activated")
            else:
                st.error(result["error"])
            st.rerun()
    else:
        st.info("No backups available to activate.")

    st.markdown("---")

    # Recovery
    st.markdown("### 🔧 Recovery")
    failed = sim.get_failed_nodes()
    affected = sim.get_affected_nodes()
    recoverable = failed + affected
    if recoverable:
        recover_target = st.selectbox("Select component to recover", options=recoverable, key="recover_select")
        if st.button("🔧 Recover Component", key="recover_btn", use_container_width=True):
            result = sim.recover_component(recover_target)
            if "error" not in result:
                log_ui_event(f"RECOVERED: {recover_target}")
                st.session_state.recovery_snapshot = sim.create_snapshot()
            else:
                st.error(result["error"])
            st.rerun()
    else:
        st.success("All components operational.")

    st.markdown("---")

    # Reset
    if st.button("🔄 Reset Simulation", key="reset_btn", use_container_width=True):
        sim.reset()
        st.session_state.baseline_snapshot = None
        st.session_state.recovery_snapshot = None
        st.session_state.event_log_ui = []
        log_ui_event("RESET: Simulation reset")
        st.rerun()


# ──────────────────────────────────────────────────────────────
# Main content
# ──────────────────────────────────────────────────────────────

# Header
st.markdown("""
<div style="text-align: center; padding: 10px 0 20px 0;">
    <h1 style="font-size: 2.2rem; margin-bottom: 4px;" class="header-glow">
        🛡️ InfraGuard AI
    </h1>
    <p style="color: #94a3b8; font-size: 1.1rem; margin-top: 0;">
        When One Failure Becomes Many — Simulate, Analyze, Recover
    </p>
</div>
""", unsafe_allow_html=True)

# ── Section 1: Status metrics ──
severity = sim.calculate_severity()
col1, col2, col3, col4, col5 = st.columns(5)

total = len(sim.get_all_states())
op_count = len(sim.get_operational_nodes())
fail_count = len(sim.get_failed_nodes())
aff_count = len(sim.get_affected_nodes())
rest_count = len(sim.get_restored_nodes())

with col1:
    st.metric("Operational", f"{op_count}/{total}", delta=None)
with col2:
    st.metric("Failed", fail_count, delta=None)
with col3:
    st.metric("Affected", aff_count, delta=None)
with col4:
    st.metric("Restored", rest_count, delta=None)
with col5:
    sev_emoji = {"NORMAL": "🟢", "LOW": "🟡", "MODERATE": "🟠", "HIGH": "🔴", "CRITICAL": "🚨"}.get(severity["level"], "⚪")
    st.metric("Severity", f"{sev_emoji} {severity['level']}", delta=f"{severity['score']}%")

st.markdown("---")

# ── Tabs ──
tab_network, tab_impact, tab_routes, tab_twin, tab_log = st.tabs([
    "🌐 Network", "📊 Impact Analysis", "🗺️ Route Checker",
    "🔬 Resilience Twin", "📋 Event Log"
])

# ── Tab 1: Network visualization ──
with tab_network:
    st.plotly_chart(
        build_network_figure(sim.graph, "Infrastructure Dependency Network"),
        use_container_width=True,
        key="main_network"
    )

    # Status table
    st.markdown("#### Component Status")
    status_data = []
    for name, data in sim.graph.nodes(data=True):
        state = data["state"]
        icon = {"operational": "🟢", "failed": "🔴", "affected": "🟡", "restored": "🔵"}.get(state, "⚪")
        critical = "⚡ Yes" if data.get("critical") else "No"
        status_data.append({
            "Status": icon,
            "Component": name,
            "Type": data["kind"].replace("_", " ").title(),
            "State": state.upper(),
            "Critical": critical,
        })
    st.dataframe(status_data, use_container_width=True, hide_index=True)

    # Edge legend
    with st.expander("📐 Edge Legend"):
        st.markdown("""
        | Color | Style | Meaning |
        |-------|-------|---------|
        | 🟡 Yellow solid | ━━━ | Power supply |
        | 🔵 Blue dashed | - - - | Backup power (requires activation) |
        | 🔵 Cyan solid | ━━━ | Water supply |
        | 🟠 Orange solid | ━━━ | Communications |
        | 🟣 Purple dotted | ··· | Transport route |
        """)

# ── Tab 2: Impact analysis ──
with tab_impact:
    col_sev, col_crit = st.columns([1, 1])

    with col_sev:
        st.markdown("#### Severity Assessment")
        severity = sim.calculate_severity()

        # Severity gauge
        gauge_color = {
            "NORMAL": "#22c55e", "LOW": "#84cc16",
            "MODERATE": "#f59e0b", "HIGH": "#ef4444", "CRITICAL": "#dc2626"
        }.get(severity["level"], "#64748b")

        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=severity["score"],
            title={"text": "Infrastructure Impact Score", "font": {"size": 16, "color": "#e2e8f0"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#64748b"},
                "bar": {"color": gauge_color},
                "bgcolor": "rgba(15, 23, 60, 0.8)",
                "steps": [
                    {"range": [0, 40], "color": "rgba(34, 197, 94, 0.15)"},
                    {"range": [40, 60], "color": "rgba(245, 158, 11, 0.15)"},
                    {"range": [60, 80], "color": "rgba(239, 68, 68, 0.15)"},
                    {"range": [80, 100], "color": "rgba(220, 38, 38, 0.25)"},
                ],
                "threshold": {
                    "line": {"color": "#e2e8f0", "width": 2},
                    "thickness": 0.8,
                    "value": severity["score"],
                },
            },
            number={"suffix": "%", "font": {"color": "#e2e8f0"}},
        ))
        fig_gauge.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=280,
            margin=dict(l=30, r=30, t=60, b=20),
        )
        st.plotly_chart(fig_gauge, use_container_width=True, key="severity_gauge")
        st.markdown(f"**{severity['description']}**")

    with col_crit:
        st.markdown("#### Critical Services")
        critical = sim.get_critical_services()
        aff_critical = sim.get_affected_critical_services()

        for svc in critical:
            state = sim.graph.nodes[svc]["state"]
            icon = {"operational": "🟢", "failed": "🔴", "affected": "🟡", "restored": "🔵"}.get(state, "⚪")
            st.markdown(f"{icon} **{svc}** — {state.upper()}")

        if aff_critical:
            st.warning(f"⚠️ {len(aff_critical)} of {len(critical)} critical services impacted")
        else:
            st.success("✅ All critical services operational")

    # Recommendations
    st.markdown("#### 💡 Recovery Recommendations")
    recs = sim._generate_recommendations()
    if recs:
        for i, rec in enumerate(recs, 1):
            st.markdown(f"**{i}.** {rec}")
    else:
        st.info("No recommendations — all systems operational.")

# ── Tab 3: Route Checker ──
with tab_routes:
    st.markdown("#### Route Availability Checker")
    col_src, col_tgt = st.columns(2)
    with col_src:
        route_src = st.selectbox("Source", options=component_names, key="route_src",
                                  index=component_names.index("Transport Hub") if "Transport Hub" in component_names else 0)
    with col_tgt:
        route_tgt = st.selectbox("Target", options=component_names, key="route_tgt",
                                  index=component_names.index("Emergency Response Center") if "Emergency Response Center" in component_names else 0)

    if st.button("🔍 Check Route", key="check_route_btn"):
        result = check_route(sim, route_src, route_tgt)
        if "error" in result:
            st.error(result["error"])
        else:
            if result["direct_route_available"]:
                st.success(f"✅ Route available: {' → '.join(result['path'])}")
            else:
                st.error(f"❌ Route blocked")
                if result["blocked_nodes"]:
                    st.warning(f"Blocked at: {', '.join(result['blocked_nodes'])}")
                if result["alternative_routes"]:
                    for i, alt in enumerate(result["alternative_routes"], 1):
                        st.info(f"🔄 Alternative {i}: {' → '.join(alt)}")
                else:
                    st.warning("No alternative routes available.")

    # Show all routes
    with st.expander("📐 All Available Routes"):
        all_routes = sim.find_all_routes(route_src, route_tgt)
        if all_routes:
            for i, route in enumerate(all_routes, 1):
                blocked_nodes = [n for n in route if sim.graph.nodes[n]["state"] in ("failed", "affected")]
                status = "✅" if not blocked_nodes else "❌"
                st.markdown(f"{status} Route {i}: {' → '.join(route)}")
                if blocked_nodes:
                    st.caption(f"  Blocked at: {', '.join(blocked_nodes)}")
        else:
            st.info("No routes exist between these components.")

# ── Tab 4: Resilience Twin ──
with tab_twin:
    st.markdown("#### 🔬 Resilience Twin — Scenario Comparison")
    st.markdown("""
    Compare **baseline** (after failure) with **recovery** (after backup/repair)
    to measure the verified improvement.
    """)

    twin_col1, twin_col2 = st.columns(2)

    with twin_col1:
        st.markdown("##### 📸 Baseline Snapshot")
        if st.button("📸 Capture Baseline", key="capture_baseline", use_container_width=True):
            st.session_state.baseline_snapshot = sim.create_snapshot()
            log_ui_event("TWIN: Baseline captured")
            st.rerun()

        if st.session_state.baseline_snapshot:
            bs = st.session_state.baseline_snapshot
            sev = bs["severity"]
            st.metric("Baseline Severity", f"{sev['level']} ({sev['score']}%)")
            st.markdown(f"**Failed:** {', '.join(bs['failed']) or 'None'}")
            st.markdown(f"**Affected:** {', '.join(bs['affected']) or 'None'}")
            st.markdown(f"**Critical impacted:** {', '.join(bs['affected_critical']) or 'None'}")
        else:
            st.info("Fail a component, then capture the baseline snapshot.")

    with twin_col2:
        st.markdown("##### 📸 Recovery Snapshot")
        if st.button("📸 Capture Recovery", key="capture_recovery", use_container_width=True):
            st.session_state.recovery_snapshot = sim.create_snapshot()
            log_ui_event("TWIN: Recovery captured")
            st.rerun()

        if st.session_state.recovery_snapshot:
            rs = st.session_state.recovery_snapshot
            sev = rs["severity"]
            st.metric("Recovery Severity", f"{sev['level']} ({sev['score']}%)")
            st.markdown(f"**Failed:** {', '.join(rs['failed']) or 'None'}")
            st.markdown(f"**Affected:** {', '.join(rs['affected']) or 'None'}")
            st.markdown(f"**Critical impacted:** {', '.join(rs['affected_critical']) or 'None'}")
        else:
            st.info("Activate a backup or recover a component, then capture recovery snapshot.")

    # Comparison
    st.markdown("---")
    if st.session_state.baseline_snapshot and st.session_state.recovery_snapshot:
        comparison = sim.compare_scenarios(
            st.session_state.baseline_snapshot,
            st.session_state.recovery_snapshot
        )

        st.markdown("##### 📊 Comparison Results")

        comp_c1, comp_c2, comp_c3 = st.columns(3)
        with comp_c1:
            st.metric(
                "Improvement Score",
                f"{comparison['improvement_score']}pts",
                delta=f"{comparison['improvement_score']}% improvement" if comparison['improvement_score'] > 0 else "No change"
            )
        with comp_c2:
            st.metric(
                "Services Down",
                f"{comparison['recovery_down_count']}",
                delta=f"-{comparison['baseline_down_count'] - comparison['recovery_down_count']} recovered"
                if comparison['baseline_down_count'] > comparison['recovery_down_count'] else "No change"
            )
        with comp_c3:
            st.metric("Services Recovered", len(comparison["services_recovered"]))

        if comparison["services_recovered"]:
            st.success(f"✅ Recovered: {', '.join(comparison['services_recovered'])}")
        if comparison["still_affected"]:
            st.warning(f"⚠️ Still affected: {', '.join(comparison['still_affected'])}")

        # Before/after network comparison
        comp_fig_col1, comp_fig_col2 = st.columns(2)

        # Build a temp graph for baseline visualization
        with comp_fig_col1:
            baseline_graph = sim.graph.copy()
            for name in baseline_graph.nodes():
                state = st.session_state.baseline_snapshot["states"].get(name, "operational")
                baseline_graph.nodes[name]["state"] = state
            st.plotly_chart(
                build_network_figure(baseline_graph, "Baseline (After Failure)"),
                use_container_width=True, key="twin_baseline_net"
            )

        with comp_fig_col2:
            recovery_graph = sim.graph.copy()
            for name in recovery_graph.nodes():
                state = st.session_state.recovery_snapshot["states"].get(name, "operational")
                recovery_graph.nodes[name]["state"] = state
            st.plotly_chart(
                build_network_figure(recovery_graph, "Recovery (After Action)"),
                use_container_width=True, key="twin_recovery_net"
            )
    else:
        st.info("Capture both baseline and recovery snapshots to see the comparison.")

# ── Tab 5: Event Log ──
with tab_log:
    st.markdown("#### 📋 Event Log")

    # Combine simulation and UI event logs
    all_events = sim.get_event_log() + st.session_state.event_log_ui
    if all_events:
        for event in reversed(all_events[-50:]):
            st.code(event, language=None)
    else:
        st.info("No events recorded. Simulate a failure to begin.")

    st.markdown("---")
    st.markdown("#### ⚠️ Model Limitations")
    st.markdown("""
    - This is an **educational simulation** using synthetic assumptions.
    - Infrastructure dependencies are modeled, not measured from real systems.
    - Severity scores reflect modeled critical-service impact, not validated risk assessments.
    - Backup activation is a modeled action; real backup systems have complex activation requirements.
    - Route availability is based on graph connectivity, not physical transport logistics.
    - Recovery times are not modeled — recovery is instantaneous in this simulation.
    - Multiple simultaneous failures are handled additively; real cascading failures may have non-linear interactions.
    """)

# ──────────────────────────────────────────────────────────────
# Footer
# ──────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #64748b; font-size: 0.85rem;'>"
    "InfraGuard AI — Infrastructure Resilience Simulation | "
    "Educational Demo | Built with Fetch.ai uAgents + Streamlit"
    "</div>",
    unsafe_allow_html=True,
)
