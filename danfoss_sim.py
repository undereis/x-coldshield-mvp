import socket
import struct
import json
from datetime import datetime

HOST = '127.0.0.1'
PORT = 5020

registers = {
    0: -20,  # Freezer 1 (Meat & Poultry)
    1: -20,  # Freezer 2 (Ice Cream & Frozen)
    2: -18,  # Freezer 3 (Dairy & Cold Chain)
    10: 0,   # Defrost Freezer 1
    11: 0,   # Defrost Freezer 2
    12: 0    # Defrost Freezer 3
}

def save_state():
    state = {
        "last_update": datetime.now().strftime('%H:%M:%S'),
        "freezers": {
            "Aisle 1 (Meat & Poultry)": {"temp": registers[0], "defrost": bool(registers[10])},
            "Aisle 2 (Frozen Foods)": {"temp": registers[1], "defrost": bool(registers[11])},
            "Aisle 3 (Dairy & Logistics)": {"temp": registers[2], "defrost": bool(registers[12])}
        }
    }
    with open("danfoss_state.json", "w") as f:
        json.dump(state, f, indent=2)

def print_status():
    save_state()
    print("\n" + "="*55)
    print(f"❄️  [DANFOSS AK-SM 800 SIMULATOR] - {datetime.now().strftime('%H:%M:%S')}")
    for i in range(3):
        temp = registers[i]
        defrost = "🔥 LIGADO (PERIGO!)" if registers[i+10] == 1 else "DESLIGADO (Normal)"
        alerta = " 🚨 [ALIMENTOS ESTRAGANDO!]" if temp > -10 else " ✅ [OK]"
        print(f"   • Ilha Congelados {i+1}: Setpoint = {temp}°C | Degelo: {defrost}{alerta}")
    print("="*55)

def start_simulator():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    print(f"🟢 Controlador de Refrigeração rodando em {HOST}:{PORT}")
    print_status()

    while True:
        client, addr = server.accept()
        try:
            while True:
                data = client.recv(1024)
                if not data or len(data) < 12:
                    break
                trans_id, proto_id, length, unit_id, func_code, reg_addr, val = struct.unpack('>HHHBBHh', data[:12])
                if func_code == 6:
                    registers[reg_addr] = val
                    print(f"\n⚠️  [COMANDO RECEBIDO NA REDE] Registrador {reg_addr} alterado para -> {val}")
                    print_status()
                    client.sendall(data[:12])
        except Exception as e:
            print(f"Erro: {e}")
        finally:
            client.close()

if __name__ == '__main__':
    start_simulator()
