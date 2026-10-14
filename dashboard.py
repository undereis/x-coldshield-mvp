import streamlit as st
import json
import os
import socket
import struct
import pandas as pd

st.set_page_config(page_title="X ColdShield | OT Security Gateway", page_icon="🛡️", layout="wide")

def send_modbus_cmd(port, reg_addr, value):
    packet = struct.pack('>HHHBBHh', 1, 0, 6, 1, 6, reg_addr, value)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            s.connect(('127.0.0.1', port))
            s.sendall(packet)
            resp = s.recv(1024)
            return bool(resp)
    except:
        return False

# Cabeçalho Executivo
st.title("🛡️ X ColdShield — Physics-Aware OT Security Gateway")
st.caption("Zero-Trust Protection for Legacy Supermarket Refrigeration Controllers (Danfoss / Carel) | EU NIS 2 Directive Ready")

# Barra Lateral: Controlo Zero-Trust e Simulador de Ataques Ao Vivo
st.sidebar.header("🔒 Zero-Trust Policy Control")

policy_file = "policy_config.json"
policy = {"maintenance_window_open": True, "max_temp": -15}
if os.path.exists(policy_file):
    try:
        with open(policy_file, "r") as f:
            policy = json.load(f)
    except:
        pass

maint_open = st.sidebar.toggle("Allow 3rd-Party Contractor Access (Maintenance Window)", value=policy.get("maintenance_window_open", True))
max_temp = st.sidebar.slider("Hard Thermal Safety Limit (°C)", min_value=-25, max_value=0, value=policy.get("max_temp", -15))

with open(policy_file, "w") as f:
    json.dump({"maintenance_window_open": maint_open, "max_temp": max_temp}, f)

st.sidebar.divider()
st.sidebar.header("⚡ Live Demo Attack Launcher")

if st.sidebar.button("👨‍🔧 1. Legit Contractor Cmd (-22°C)", use_container_width=True):
    ok = send_modbus_cmd(5021, 0, -22)
    if ok:
        st.sidebar.success("Command verified and applied (-22°C).")
    else:
        st.sidebar.error("Blocked by X ColdShield Zero-Trust Policy!")

if st.sidebar.button("💀 2. Launch +50°C Attack (Protected)", type="primary", use_container_width=True):
    ok = send_modbus_cmd(5021, 0, 50)
    if not ok:
        st.sidebar.success("🛡️ ATTACK INTERCEPTED! +50°C packet dropped at edge.")

if st.sidebar.button("🔥 3. Mass Defrost Sabotage (Protected)", use_container_width=True):
    send_modbus_cmd(5021, 10, 1)
    ok2 = send_modbus_cmd(5021, 11, 1)
    if not ok2:
        st.sidebar.success("🛡️ CASCADE BLOCKED! Simultaneous defrost prevented.")

if st.sidebar.button("⚠️ 4. Direct Attack WITHOUT ColdShield (+50°C)", use_container_width=True):
    send_modbus_cmd(5020, 0, 50)
    st.sidebar.warning("💥 Direct hit on port 5020! Legacy controller compromised.")

if st.sidebar.button("🔄 Reset Freezers to Normal (-20°C)", use_container_width=True):
    send_modbus_cmd(5020, 0, -20)
    send_modbus_cmd(5020, 1, -20)
    send_modbus_cmd(5020, 2, -18)
    send_modbus_cmd(5020, 10, 0)
    send_modbus_cmd(5020, 11, 0)
    send_modbus_cmd(5020, 12, 0)

# Secção 1: Estado das Arcas Frigoríficas em Tempo Real
st.subheader("❄️ Live Supermarket Cold Chain Telemetry (Danfoss AK-SM 800)")

if os.path.exists("danfoss_state.json"):
    with open("danfoss_state.json", "r") as f:
        state = json.load(f)
    
    cols = st.columns(3)
    for idx, (aisle, data) in enumerate(state["freezers"].items()):
        temp = data["temp"]
        defrost = data["defrost"]
        status_icon = "🚨 CRITICAL SPOILAGE" if temp > -10 else "✅ OPTIMAL"
        defrost_txt = "🔥 ACTIVE" if defrost else "OFF"
        cols[idx].metric(
            label=aisle,
            value=f"{temp} °C",
            delta=f"Defrost: {defrost_txt} | {status_icon}",
            delta_color="inverse" if temp > -10 or defrost else "normal"
        )
else:
    st.info("Waiting for Danfoss Simulator telemetry...")

st.divider()

# Secção 2: Registo de Auditoria e DPI (NIS 2 Compliance)
st.subheader("🛡️ Deep Packet Inspection (DPI) & NIS 2 Audit Trail")

if os.path.exists("security_events.json"):
    with open("security_events.json", "r") as f:
        events = json.load(f)
    if events:
        df = pd.DataFrame(events)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.write("No network packets inspected yet.")
else:
    st.write("No security events logged yet. Use the Live Demo buttons on the left to test!")
