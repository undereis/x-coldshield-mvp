import socket
import struct
import time
import json
import os
from datetime import datetime

LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 5021
DANFOSS_HOST = '127.0.0.1'
DANFOSS_PORT = 5020

MAX_ALLOWED_TEMP = -15
MAX_SIMULTANEOUS_DEFROST = 1
DEFROST_WINDOW_SEC = 120

defrost_history = []
EVENTS_FILE = "security_events.json"
POLICY_FILE = "policy_config.json"

def get_policy():
    if not os.path.exists(POLICY_FILE):
        default_policy = {"maintenance_window_open": True, "max_temp": -15}
        with open(POLICY_FILE, "w") as f:
            json.dump(default_policy, f)
        return default_policy
    try:
        with open(POLICY_FILE, "r") as f:
            return json.load(f)
    except:
        return {"maintenance_window_open": True, "max_temp": -15}

def log_event(status, action_type, details, reg_addr, val):
    events = []
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, "r") as f:
                events = json.load(f)
        except:
            events = []
    
    new_event = {
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "status": status,
        "type": action_type,
        "register": f"REG-{reg_addr}",
        "Attempted_Value": val,
        "details": details
    }
    events.insert(0, new_event)
    with open(EVENTS_FILE, "w") as f:
        json.dump(events[:50], f, indent=2)

def inspect_modbus_packet(data):
    if len(data) < 12:
        return False, "MALFORMED_PACKET", "Invalid Modbus TCP length", -1, 0

    trans_id, proto_id, length, unit_id, func_code, reg_addr, val = struct.unpack('>HHHBBHh', data[:12])
    policy = get_policy()

    if func_code == 6:
        # REGRA ZERO-TRUST: Janela de Manutenção de Técnicos Terceirizados
        if not policy.get("maintenance_window_open", True):
            return False, "ZERO_TRUST_TIME_LOCK", (
                f"Unauthorized contractor access outside maintenance window! "
                f"Write attempt on REG-{reg_addr} rejected."
            ), reg_addr, val

        # REGRA FÍSICA 1: Limite Térmico Seguro
        max_temp = policy.get("max_temp", MAX_ALLOWED_TEMP)
        if reg_addr in [0, 1, 2] and val > max_temp:
            return False, "THERMAL_SAFETY_VIOLATION", (
                f"Physics-Aware DPI blocked dangerous setpoint (+{val}°C) on Aisle {reg_addr+1}. "
                f"Hard limit is {max_temp}°C."
            ), reg_addr, val

        # REGRA FÍSICA 2: Anti-Sabotagem de Degelo Simultâneo
        if reg_addr in [10, 11, 12] and val == 1:
            now = time.time()
            defrost_history[:] = [t for t in defrost_history if now - t < DEFROST_WINDOW_SEC]
            if len(defrost_history) >= MAX_SIMULTANEOUS_DEFROST:
                return False, "MASS_DEFROST_SABOTAGE", (
                    f"Simultaneous defrost cascade blocked on Aisle {reg_addr-9}. "
                    f"Thermal overload prevention triggered."
                ), reg_addr, val
            defrost_history.append(now)

    return True, "AUTHORIZED_COMMAND", f"Validated write on REG-{reg_addr} (Value: {val})", reg_addr, val

def start_coldshield():
    get_policy()
    proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    proxy.bind((LISTEN_HOST, LISTEN_PORT))
    proxy.listen(5)

    print("="*65)
    print("🛡️  X COLDSHIELD - OT Zero-Trust Gateway & Physics Firewall ATIVO")
    print(f"🔒 Escutando conexões externas em {LISTEN_HOST}:{LISTEN_PORT}")
    print("="*65)

    while True:
        client_sock, addr = proxy.accept()
        try:
            while True:
                data = client_sock.recv(1024)
                if not data:
                    break

                allowed, action_type, reason, reg_addr, val = inspect_modbus_packet(data)
                timestamp = datetime.now().strftime('%H:%M:%S')

                if allowed:
                    print(f"✅ [{timestamp}] PERMITIDO: {reason}")
                    log_event("ALLOWED", action_type, reason, reg_addr, val)
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as danfoss_sock:
                        danfoss_sock.connect((DANFOSS_HOST, DANFOSS_PORT))
                        danfoss_sock.sendall(data)
                        response = danfoss_sock.recv(1024)
                        client_sock.sendall(response)
                else:
                    print(f"\n🚨 [{timestamp}] [BLOQUEADO - {action_type}] {reason}\n")
                    log_event("BLOCKED", action_type, reason, reg_addr, val)
                    break
        except Exception as e:
            print(f"Erro: {e}")
        finally:
            client_sock.close()

if __name__ == '__main__':
    start_coldshield()
