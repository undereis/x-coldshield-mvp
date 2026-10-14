# X ColdShield 🛡️
### Physics-Aware OT Security Gateway for Legacy Supermarket Refrigeration

**X ColdShield** is an edge security gateway designed to protect legacy supermarket refrigeration and cold chain infrastructure (such as Danfoss and Carel controllers) against advanced remote attacks and thermal sabotage (aligned with the **EU NIS 2 Directive**).

## Key Features
- **Physics-Aware Deep Packet Inspection (DPI):** Intercepts Modbus/BACnet traffic to enforce hard thermal limits (blocking remote temperature overrides above -15°C).
- **Anti-Sabotage Defrost Control:** Prevents coordinated cascade defrost attacks.
- **Zero-Trust Contractor Access:** Time-locks third-party maintenance sessions.
- **NIS 2 Audit Trail:** Generates real-time security event logs and a Streamlit operational dashboard.

## Architecture & Lab Setup
- `danfoss_sim.py`: Simulates legacy refrigeration controllers (Modbus TCP).
- `x_coldshield_proxy.py`: The core physics-aware firewall and proxy engine.
- `attack_simulator.py`: Simulates legitimate maintenance vs. malicious thermal attacks (+50°C).
- `dashboard.py`: Executive telemetry and real-time incident monitoring dashboard (Streamlit).

## Author
**Ramon M Reis** — Founder & Technical Director
