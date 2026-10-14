"""Explicit, expiring local lab maintenance leases."""
import argparse
from datetime import timedelta
from pathlib import Path
from .config import load_policy, utcnow, validate_policy
from .storage import atomic_json
import json

ROOT = Path(__file__).resolve().parents[1]


def set_window(path, seconds=None):
    load_policy(path)  # Never silently repair an invalid policy or relax a hard limit.
    data = json.loads(Path(path).read_text())
    now = utcnow()
    if seconds is None:
        data["maintenance"] = {"enabled": False, "starts_at": None, "expires_at": None}
    else:
        if type(seconds) is not int or not 1 <= seconds <= 900:
            raise ValueError("Lease must last 1..900 seconds")
        data["maintenance"] = {"enabled": True, "starts_at": now.isoformat(),
                               "expires_at": (now + timedelta(seconds=seconds)).isoformat()}
    validate_policy(data)
    atomic_json(path, data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("open", "close"))
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--policy", type=Path, default=ROOT / "policy_config.json")
    args = parser.parse_args()
    try:
        result = set_window(args.policy, args.seconds if args.action == "open" else None)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Maintenance update rejected: {exc}\n")
    print(json.dumps(result["maintenance"], indent=2))


if __name__ == "__main__":
    main()
