"""Explicit, expiring local lab maintenance leases."""
import argparse
from contextlib import contextmanager
from datetime import timedelta
import fcntl
import json
import os
from pathlib import Path
import time
from .config import ConfigError, read_policy_data, uncertainty_path, utcnow, validate_policy
from .storage import atomic_json, fsync_directory

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def policy_lock(path, timeout=1.0):
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
        raise ValueError("Invalid policy lock timeout")
    with Path(str(path) + ".lock").open("a") as lease:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ConfigError("Policy update lock timed out")
                time.sleep(min(.01, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(lease, fcntl.LOCK_UN)


def _mark_uncertain(marker):
    # Creation precedes any policy replacement. Even a failed marker fsync leaves
    # a visible interlock and prevents publication of an open lease.
    with marker.open("w", encoding="utf-8") as file:
        file.write("Administrative policy durability uncertain; close to recover.\n")
        file.flush()
        os.fsync(file.fileno())
    fsync_directory(marker.parent)



def _quarantine_policy(path, data):
    """Keep a failed marker recovery closed before releasing the writer lock."""
    closed = {**data, "maintenance": {"enabled": False, "starts_at": None, "expires_at": None}}
    try:
        atomic_json(path, closed)
        return
    except OSError:
        # A failed closed replacement may still leave the previous open policy
        # visible. Remove its public name if durable replacement is unavailable.
        try:
            path.unlink(missing_ok=True)
        except OSError:
            try:
                os.replace(path, Path(str(path) + ".quarantined"))
            except OSError as exc:
                raise OSError("Fail-closed recovery unavailable: filesystem refused closed replacement, "
                              "removal and quarantine; policy may remain visible") from exc
        try:
            fsync_directory(path.parent)
        except OSError as exc:
            raise OSError("Policy is currently unavailable, but recovery durability is uncertain") from exc


def set_window(path, seconds=None, *, lock_timeout=1.0):
    path = Path(path)
    if seconds is not None and (type(seconds) is not int or not 1 <= seconds <= 900):
        raise ValueError("Lease must last 1..900 seconds")
    with policy_lock(path, lock_timeout):
        marker = uncertainty_path(path)
        if seconds is not None and marker.exists():
            raise ConfigError("Uncertain policy requires explicit close before opening")
        data = read_policy_data(path)
        now = utcnow()
        if seconds is None:
            data["maintenance"] = {"enabled": False, "starts_at": None, "expires_at": None}
        else:
            try:
                end = now + timedelta(seconds=seconds)
            except OverflowError as exc:
                raise ConfigError("Maintenance lease exceeds supported date range") from exc
            data["maintenance"] = {"enabled": True, "starts_at": now.isoformat(), "expires_at": end.isoformat()}
        validate_policy(data)
        _mark_uncertain(marker)
        atomic_json(path, data)
        try:
            marker.unlink()
            fsync_directory(path.parent)
        except OSError:
            # Restore the visible interlock before releasing the administrative
            # lock if removal durability cannot be confirmed.
            try:
                _mark_uncertain(marker)
            except OSError as marker_error:
                _quarantine_policy(path, data)
                raise OSError("Policy marker recovery failed; policy was quarantined closed") from marker_error
            raise
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
