"""Local-only command scenarios; never targets an external host."""
import argparse
from coldshield.protocol import write_frame
from coldshield.client import send_write


def build_modbus_write(reg_addr, value):
    return write_frame(reg_addr, value).encode()


def run_simulation(port, mode):
    commands = {
        "legit": [(0, -22)], "attack_50c": [(0, 50)],
        "attack": [(10, 1), (11, 1)],
        "reset": [(0, -20), (1, -20), (2, -18), (10, 0), (11, 0), (12, 0)]}
    if mode not in commands:
        raise ValueError("Unknown lab scenario")
    print(f"LAB ONLY: 127.0.0.1:{port} / {mode}")
    results = []
    for register, value in commands[mode]:
        result = send_write(port, register, value)
        results.append(result)
        print(f"REG-{register} = {value}: {result.status} — {result.message}")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("legit", "attack_50c", "attack", "reset"))
    parser.add_argument("--target", choices=("gateway", "simulator"), default="gateway")
    args = parser.parse_args()
    if args.scenario:
        results = run_simulation(5021 if args.target == "gateway" else 5020, args.scenario)
        return 1 if any(result.status == "UNAVAILABLE" for result in results) else 0
    print("1: legitimate -22°C via gateway\n2: +50°C directly to LAB simulator\n"
          "3: +50°C via gateway\n4: defrost cascade via gateway")
    choice = input("Scenario (1..4): ").strip()
    options = {"1": (5021, "legit"), "2": (5020, "attack_50c"),
               "3": (5021, "attack_50c"), "4": (5021, "attack")}
    if choice not in options:
        parser.error("Choose 1..4")
    run_simulation(*options[choice])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
