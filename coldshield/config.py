"""Strict policy parsing. Filesystem access is the laboratory trust boundary."""
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path


class ConfigError(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def default_policy():
    return {"version": 2, "min_temp": -40, "max_temp": -15,
            "maintenance": {"enabled": False, "starts_at": None, "expires_at": None}}


def parse_time(value):
    if not isinstance(value, str):
        raise ConfigError("Maintenance timestamps must be ISO 8601 strings")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError("Invalid maintenance timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ConfigError("Maintenance timestamps must include a timezone")
    try:
        return stamp.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ConfigError("Maintenance timestamp is outside supported range") from exc


@dataclass(frozen=True)
class Policy:
    min_temp: int
    max_temp: int
    enabled: bool
    starts_at: datetime | None
    expires_at: datetime | None
    digest: str

    def maintenance_open(self, now=None):
        now = now or utcnow()
        return bool(self.enabled and self.starts_at <= now < self.expires_at)


def validate_policy(data):
    if not isinstance(data, dict) or set(data) != {"version", "min_temp", "max_temp", "maintenance"}:
        raise ConfigError("Expected exact v2 policy keys; legacy policies require explicit migration")
    if type(data["version"]) is not int or data["version"] != 2:
        raise ConfigError("Unsupported policy version")
    low, high = data["min_temp"], data["max_temp"]
    if type(low) is not int or type(high) is not int or not -40 <= low <= high <= -15:
        raise ConfigError("Temperature bounds must satisfy -40 <= min_temp <= max_temp <= -15")
    window = data["maintenance"]
    if not isinstance(window, dict) or set(window) != {"enabled", "starts_at", "expires_at"}:
        raise ConfigError("Invalid maintenance fields")
    if type(window["enabled"]) is not bool:
        raise ConfigError("Maintenance enabled must be boolean")
    start, end = window["starts_at"], window["expires_at"]
    if start is None and end is None and not window["enabled"]:
        pass
    else:
        start, end = parse_time(start), parse_time(end)
        if not 0 < (end - start).total_seconds() <= 900:
            raise ConfigError("Maintenance duration must be 1..900 seconds")
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return Policy(low, high, window["enabled"], start, end,
                  hashlib.sha256(canonical.encode()).hexdigest())


def uncertainty_path(path):
    return Path(str(path) + ".uncertain")


def read_policy_data(path):
    """Strict single read, also used inside the administrative exclusive lock."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConfigError("Duplicate policy key")
            result[key] = value
        return result
    try:
        with Path(path).open("r", encoding="utf-8") as file:
            contents = file.read(16385)
        if len(contents.encode("utf-8")) > 16384:
            raise ConfigError("Policy exceeds 16 KiB")
        data = json.loads(contents, object_pairs_hook=unique)
        validate_policy(data)
        return data
    except (OSError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise ConfigError(f"Policy unavailable or invalid: {exc}") from exc


def load_policy(path):
    path = Path(path)
    lease = None
    try:
        # Refuse during administrative publication, including marker removal.
        lock_path = Path(str(path) + ".lock")
        try:
            lease = lock_path.open("r")
        except FileNotFoundError:
            pass
        if lease is not None:
            fcntl.flock(lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
        if uncertainty_path(path).exists():
            raise ConfigError("Policy publication uncertain; explicit maintenance close required")
        data = read_policy_data(path)
        if uncertainty_path(path).exists():
            raise ConfigError("Policy publication uncertain; explicit maintenance close required")
        return validate_policy(data)
    except (OSError, OverflowError) as exc:
        raise ConfigError(f"Policy unavailable or invalid: {exc}") from exc
    finally:
        if lease is not None:
            lease.close()
