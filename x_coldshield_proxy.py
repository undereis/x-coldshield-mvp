"""X ColdShield laboratory gateway entry point (loopback only)."""
import argparse
import logging
from pathlib import Path
from coldshield.gateway import make_gateway

from coldshield import __version__
from coldshield.limits import validate_port

ROOT = Path(__file__).resolve().parent


def start_coldshield():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5021)
    parser.add_argument("--upstream-port", type=int, default=5020)
    parser.add_argument("--policy", type=Path, default=ROOT / "policy_config.json")
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / "runtime")
    args = parser.parse_args()
    try:
        validate_port(args.port)
        validate_port(args.upstream_port)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO)
    with make_gateway(args.port, args.upstream_port, args.policy, args.runtime_dir) as server:
        print(f"X ColdShield {__version__} LAB ONLY: 127.0.0.1:{server.server_address[1]}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    start_coldshield()
