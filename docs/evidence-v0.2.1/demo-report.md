# X ColdShield 0.2.1 local demonstration

Result: PASSED
UTC: 2026-10-15T13:21:19.946877+00:00
Revision: `6c4d4395aa3ede31528632cd440f98dca5c961bb`

synthetic loopback laboratory, 127.0.0.1 only

| UTC | Command | Transaction | Decision | Reason | Result |
| --- | --- | --- | --- | --- | --- |
| 2026-10-15T13:21:20.102979+00:00 | CLOSED: legitimate setpoint -22 | 101 | BLOCKED | MAINTENANCE_CLOSED | PASSED |
| 2026-10-15T13:21:20.122720+00:00 | CLOSED: verify unchanged temperature | 102 | ACKNOWLEDGED | VALIDATED_RESPONSE | PASSED |
| 2026-10-15T13:21:20.128571+00:00 | python -m coldshield.maintenance open | None | OPEN | POLICY_STATE_VERIFIED | PASSED |
| 2026-10-15T13:21:20.184003+00:00 | OPEN: legitimate setpoint -22 | 103 | ACKNOWLEDGED | VALIDATED_RESPONSE | PASSED |
| 2026-10-15T13:21:20.189161+00:00 | OPEN: verify legitimate temperature | 104 | ACKNOWLEDGED | VALIDATED_RESPONSE | PASSED |
| 2026-10-15T13:21:20.192405+00:00 | OPEN: unsafe setpoint +50 | 105 | BLOCKED | THERMAL_LIMIT | PASSED |
| 2026-10-15T13:21:20.193871+00:00 | OPEN: verify blocked temperature | 106 | ACKNOWLEDGED | VALIDATED_RESPONSE | PASSED |
| 2026-10-15T13:21:20.196886+00:00 | OPEN: defrost register 10 ON | 107 | ACKNOWLEDGED | VALIDATED_RESPONSE | PASSED |
| 2026-10-15T13:21:20.201592+00:00 | OPEN: defrost register 11 ON | 108 | BLOCKED | DEFROST_INTERLOCK | PASSED |
| 2026-10-15T13:21:20.206012+00:00 | OPEN: verify defrost state | 109 | ACKNOWLEDGED | VALIDATED_RESPONSE | PASSED |
| 2026-10-15T13:21:20.209703+00:00 | OPEN: unsupported FC16 | 110 | BLOCKED | FUNCTION_NOT_ALLOWED | PASSED |
| 2026-10-15T13:21:20.211160+00:00 | OPEN: unsupported register 999 | 111 | BLOCKED | REGISTER_NOT_ALLOWED | PASSED |
| 2026-10-15T13:21:20.212382+00:00 | python -m coldshield.maintenance close | None | CLOSED | POLICY_STATE_VERIFIED | PASSED |

Private maintenance policy closed: True

## Processes

- simulator: stopped=True, exit=0, forced=False
- gateway: stopped=True, exit=0, forced=False

## Errors

None.
