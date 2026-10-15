"""Synthetic refrigeration register simulator; the historical filename is retained."""
import argparse
from pathlib import Path
from coldshield.simulator import make_simulator

from coldshield import __version__
from coldshield.limits import validate_port

ROOT = Path(__file__).resolve().parent


def start_simulator():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5020)
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / "runtime")
    args = parser.parse_args()
    try:
        validate_port(args.port)
    except ValueError as exc:
        parser.error(str(exc))
    with make_simulator(args.port, args.runtime_dir) as server:
        print(f"Synthetic {__version__} LAB simulator: 127.0.0.1:{server.server_address[1]}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    start_simulator()
