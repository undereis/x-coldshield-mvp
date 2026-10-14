"""Read-only policy/telemetry dashboard and explicitly gated local lab commands."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shlex
import sqlite3

import streamlit as st

from coldshield.client import send_write
from coldshield.config import ConfigError, load_policy, utcnow
from coldshield.storage import AuditError, read_events

st.set_page_config(page_title="X ColdShield | Laboratory", page_icon=":material/shield:", layout="wide")

ROOT = Path(__file__).resolve().parent
POLICY_PATH = Path(os.environ.get("COLDSHIELD_POLICY_PATH", ROOT / "policy_config.json"))
RUNTIME_DIR = Path(os.environ.get("COLDSHIELD_RUNTIME_DIR", ROOT / "runtime"))


def lab_port(variable, default):
    try:
        port = int(os.environ.get(variable, default))
        if not 1 <= port <= 65535:
            raise ValueError
        return port
    except ValueError:
        st.error(f"Invalid {variable}: expected a port in 1..65535.")
        st.stop()


GATEWAY_PORT = lab_port("COLDSHIELD_GATEWAY_PORT", 5021)
SIMULATOR_PORT = lab_port("COLDSHIELD_SIMULATOR_PORT", 5020)
if GATEWAY_PORT == SIMULATOR_PORT:
    st.error("Gateway and direct simulator ports must be different.")
    st.stop()


def load_snapshot(path):
    """Reject incompatible or damaged snapshots instead of inventing live values."""
    path = Path(path)
    if path.stat().st_size > 65536:
        raise ValueError("Snapshot exceeds 64 KiB")
    state = json.loads(path.read_text())
    if not isinstance(state, dict) or type(state.get("schema_version")) is not int or state["schema_version"] != 2:
        raise ValueError("Expected simulator snapshot schema 2")
    stamp = datetime.fromisoformat(state["last_update"])
    if stamp.tzinfo is None or stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("Snapshot timestamp must be timezone-aware UTC")
    freezers = state["freezers"]
    if not isinstance(freezers, dict) or set(freezers) != {"Aisle 1", "Aisle 2", "Aisle 3"}:
        raise ValueError("Snapshot must contain all three aisles")
    for aisle in freezers.values():
        if not isinstance(aisle, dict) or type(aisle.get("setpoint_c")) is not int or not -32768 <= aisle["setpoint_c"] <= 32767 or type(aisle.get("defrost")) is not bool:
            raise ValueError("Invalid setpoint or defrost register state")
    age = (utcnow() - stamp.astimezone(timezone.utc)).total_seconds()
    if not math.isfinite(age):
        raise ValueError("Invalid snapshot age")
    return freezers, stamp, age


def run_command(label, port, register, value):
    return (label, send_write(port, register, value))


st.session_state.setdefault("command_results", [])
st.title("X ColdShield")
st.caption("MVP 0.2 · Physics-aware command policy · Local laboratory prototype")
st.info("Synthetic register values demonstrate policy decisions. Setpoints are not measured temperatures or a refrigeration process model.", icon=":material/science:")

with st.sidebar:
    st.header("Lab connections")
    st.caption("All command traffic stays on 127.0.0.1.")
    st.code(f"Dashboard → gateway :{GATEWAY_PORT}\nGateway → simulator :{SIMULATOR_PORT}", language="text")
    st.divider()
    st.subheader("Maintenance control")
    st.caption("The dashboard reads policy without changing it. Use the local administrator CLI for a time-limited window (maximum 900 seconds).")
    policy_flag = "" if POLICY_PATH == ROOT / "policy_config.json" else f" --policy {shlex.quote(str(POLICY_PATH))}"
    st.code(f"python -m coldshield.maintenance open --seconds 300{policy_flag}\npython -m coldshield.maintenance close{policy_flag}", language="bash")
    st.caption(f"Policy: {POLICY_PATH}\n\nRuntime: {RUNTIME_DIR}")
    st.caption("CLI paths must match the gateway. Maintenance never relaxes the thermal ceiling.")

with st.container(border=True):
    st.subheader("Protected scenarios", icon=":material/shield:")
    st.caption("Writes travel through the gateway. A valid maintenance window is required; audit reasons distinguish policy denial from transport failure.")
    with st.container(horizontal=True):
        legitimate = st.button("Legitimate maintenance · −22 °C", key="legitimate", icon=":material/build:")
        thermal = st.button("Unsafe setpoint · +50 °C", key="thermal_attack", icon=":material/thermostat:", type="primary")
        cascade = st.button("Simultaneous defrost", key="cascade_attack", icon=":material/ac_unit:")
    if legitimate:
        st.session_state.command_results = [run_command("Aisle 1: −22 °C via gateway", GATEWAY_PORT, 0, -22)]
    if thermal:
        st.session_state.command_results = [run_command("Aisle 1: +50 °C via gateway", GATEWAY_PORT, 0, 50)]
    if cascade:
        results = [run_command("Start defrost in aisle 1", GATEWAY_PORT, 10, 1)]
        if results[0][1].status == "ACKNOWLEDGED":
            results.append(run_command("Start defrost in aisle 2", GATEWAY_PORT, 11, 1))
        st.session_state.command_results = results
        if len(results) == 1:
            st.warning("The first defrost start was not acknowledged. The second request was not sent; cascade protection has not been demonstrated.")

with st.expander("Direct simulator comparison and reset", icon=":material/science:"):
    st.caption("These laboratory-only writes bypass the gateway. The direct simulator intentionally accepts unsafe thermal setpoints, and direct writes are outside the gateway audit.")
    direct_enabled = st.checkbox("Enable direct laboratory simulator writes", key="enable_direct")
    with st.container(horizontal=True):
        direct_attack = st.button("Direct +50 °C comparison", key="direct_attack", disabled=not direct_enabled)
        reset = st.button("Reset laboratory registers", key="reset_lab", icon=":material/restart_alt:", disabled=not direct_enabled)
    if direct_enabled and direct_attack:
        st.session_state.command_results = [run_command("Aisle 1: +50 °C directly to simulator", SIMULATOR_PORT, 0, 50)]
    if direct_enabled and reset:
        st.session_state.command_results = [run_command(f"Reset register {register} to {value}", SIMULATOR_PORT, register, value)
                                             for register, value in ((0, -20), (1, -20), (2, -18), (10, 0), (11, 0), (12, 0))]

if st.session_state.command_results:
    st.markdown("**Last command results**")
for label, result in st.session_state.command_results:
    message = f"**{label}** — {result.message}"
    if result.status == "ACKNOWLEDGED":
        st.success(message)
    elif result.status == "DENIED":
        st.warning(message)
    else:
        st.error(message)


@st.fragment(run_every=2)
def live_lab_status():
    st.subheader("Live laboratory state", icon=":material/monitoring:")
    policy = None
    try:
        policy = load_policy(POLICY_PATH)
    except ConfigError as exc:
        st.error(f"Policy unavailable or invalid. Gateway writes must fail closed. {exc}")
    if policy:
        with st.container(horizontal=True):
            st.metric("Maintenance window", "Open" if policy.maintenance_open() else "Closed", border=True)
            st.metric("Allowed setpoints", f"{policy.min_temp} to {policy.max_temp} °C", border=True)
            st.metric("Validated policy", policy.digest[:12], border=True)
        if policy.enabled:
            st.caption(f"Configured window: {policy.starts_at.isoformat()} → {policy.expires_at.isoformat()} (UTC).")
        st.caption("Validated configuration describes the file on disk; it is not a gateway health check.")
    try:
        freezers, stamp, age = load_snapshot(RUNTIME_DIR / "simulator_state.json")
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        st.warning(f"Simulator telemetry unavailable or invalid: {exc}")
    else:
        stale = age > 10 or age < -2
        if stale:
            st.warning("Telemetry is stale or its timestamp is in the future. Values below are an unverified snapshot, not live state.")
        st.caption(f"Snapshot: {stamp.isoformat()} · Age: {max(0, age):.1f} s · Refresh: every 2 s")
        for column, (name, data) in zip(st.columns(3), sorted(freezers.items())):
            with column.container(border=True):
                st.metric(f"{name} setpoint", f"{data['setpoint_c']} °C")
                st.caption(f"Defrost register: {'on' if data['defrost'] else 'off'}")
                if stale:
                    st.caption("Snapshot unverified")
                elif policy is None:
                    st.caption("Policy comparison unavailable")
                elif not policy.min_temp <= data["setpoint_c"] <= policy.max_temp:
                    st.error("Outside configured thermal bounds")
                else:
                    st.caption("Within configured thermal bounds")
    st.subheader("Gateway audit events", icon=":material/history:")
    st.caption("Latest 200 records, newest first. SQLite provides durable local records; administrators can edit or delete them.")
    try:
        events = read_events(RUNTIME_DIR / "audit.sqlite3", limit=200)
    except (OSError, sqlite3.Error, AuditError) as exc:
        st.error(f"Audit database unavailable or corrupt: {exc}")
    else:
        if events:
            keys = ("id", "timestamp", "request_id", "phase", "decision", "reason", "function", "register", "value", "policy_hash")
            st.dataframe([{key: row.get(key) for key in keys} for row in events], hide_index=True, height=350,
                         alt="Latest gateway audit records with decisions and reasons")
        else:
            st.info("No gateway audit events available. Start the gateway and run a protected scenario.")


live_lab_status()
st.caption("Laboratory scope only · No industrial compatibility, regulatory certification, or immutable audit guarantees claimed.")
