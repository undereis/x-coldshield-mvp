"""Shared finite resource and time limits for the loopback laboratory."""
import math

MAX_CLIENTS = 8
SESSION_MAX_SECONDS = 30.0
MAX_SESSION_REQUESTS = 64
FRAME_TIMEOUT = 1.0
UPSTREAM_TIMEOUT = 1.0
REQUEST_BUDGET = 4.0
CLIENT_TIMEOUT = 5.0
RESPONSE_RESERVE = 0.25


def validate_positive_int(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_positive_number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def validate_port(port, *, allow_ephemeral=False):
    minimum = 0 if allow_ephemeral else 1
    if type(port) is not int or not minimum <= port <= 65535:
        raise ValueError(f"Port must be an integer in {minimum}..65535")
    return port


for _name in ("MAX_CLIENTS", "MAX_SESSION_REQUESTS"):
    validate_positive_int(globals()[_name], _name)
for _name in ("SESSION_MAX_SECONDS", "FRAME_TIMEOUT", "UPSTREAM_TIMEOUT",
              "REQUEST_BUDGET", "CLIENT_TIMEOUT", "RESPONSE_RESERVE"):
    validate_positive_number(globals()[_name], _name)
