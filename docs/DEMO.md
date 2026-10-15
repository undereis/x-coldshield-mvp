# Local laboratory demonstration

## Purpose and prerequisites

This guide demonstrates command policy using a software simulator. It does not establish real controller compatibility or physical protection. Run on a host dedicated to the exercise, using loopback only. Python 3.11+ is required; dashboard dependencies are declared in `requirements.txt` and locked in `requirements.lock`.

Run from the repository root so processes share policy/runtime paths. Follow [README.md](../README.md) installation instructions. Do not reuse a gateway or simulator from another exercise.

## Automated 0.2.1 presentation

```sh
python scripts/demo.py --output-dir runtime/eura-demo-01
```

This creates a private closed policy and runtime, starts the two real entrypoints on reserved loopback ports, verifies 11 protocol transactions and two administrative operations, and returns a nonzero exit code for any unexpected result or forced cleanup. The sequence checks unchanged state after denials, -22°C acknowledgment, +50°C refusal, defrost 10 accepted/11 refused, and unknown function/register rejection. It closes the private policy and requests orderly shutdown even after a failed step. It leaves other existing laboratory processes/policies untouched.

Retain `report.md`, `report.json`, `audit-export.json`, `manifest.json`, child logs and final snapshot/policy. Verify hashes before sharing. Choose a fresh directory on repetition; no existing evidence is overwritten. Releasing a reserved port before child binding has a small local race: another process taking the port makes startup fail visibly rather than silently changing topology.

For the presentation, run the verifier in a fresh output directory, show its revision/inventory/result, run the demo, and use its table to explain intent versus validated acknowledgment versus unknown delivery. Explain the scope and remaining limitations before discussing future pilot work. The dashboard is optional; the automated evidence does not depend on manual UI interaction.

## Start

In separate terminals:

```sh
python danfoss_sim.py
```

```sh
python x_coldshield_proxy.py
```

```sh
python -m streamlit run dashboard.py --server.address 127.0.0.1
```

The dashboard should show a fresh simulator heartbeat and commanded setpoints. Missing/stale state means the simulator cannot currently be confirmed; it is not evidence that an attack was blocked. New runtime files are `runtime/simulator_state.json` and `runtime/audit.sqlite3`. Tracked legacy JSON files are historical samples.

## Exercise policy

Use the terminal menu or dashboard controls:

```sh
python attack_simulator.py
```

| Step | Action | Expected behavior |
| --- | --- | --- |
| 1 | Maintenance closed: request -22°C through port 5021 | Refuse write; setpoint unchanged |
| 2 | Open maintenance, request -22°C | Permit; confirm only after a valid matching simulator reply |
| 3 | Request +50°C through gateway | Refuse above laboratory ceiling |
| 4 | Start defrost register 10, then register 11 | First can pass; second refused while active state or reservation blocks it |
| 5 | Close maintenance, repeat normal write | Refuse closed maintenance |
| 6 | Stop simulator, attempt write | Report connection failure or uncertainty; absent reply alone proves no confirmed application |

```sh
python -m coldshield.maintenance open --seconds 300
```

```sh
python -m coldshield.maintenance close
```

Non-interactive protected examples use the same fixed local ports:

```sh
python attack_simulator.py --scenario legit --target gateway
python attack_simulator.py --scenario attack_50c --target gateway
python attack_simulator.py --scenario attack --target gateway
```

Maintenance expires by UTC wall-clock time and is limited to 900 seconds. Waiting 120 seconds alone does not authorize a second active defrost: simulator defrost flags are also checked. Reservations may conservatively block starts after failed exchanges/restarts.

## Optional bypass comparison

Explicitly enable the dashboard's direct-simulator laboratory control before its +50°C bypass example. It sends only to port 5020 on this host. The simulator deliberately accepts that setpoint. This illustrates bypass when downstream access is possible; it does not compromise equipment or demonstrate a vendor vulnerability.

Use the local reset control after the example. Reset changes simulator state and does not erase gateway reservations. Review reset errors and allow cooldown before another defrost demonstration.

## Evidence and failures

Distinguish policy decision from simulator acknowledgment. A timeout after send may occur after application; inspect the snapshot and correlated audit outcome before describing the result.

The dashboard view is not a permanent evidence bundle. Keep code revision, policy, timestamps, command and event records for a documented exercise. [TEST_REPORT.md](../TEST_REPORT.md) records executed tests separately; this guide states expectations, not claimed results.

Malformed messages, function/register denials and communication faults are exercised by automated tests:

```sh
python -m unittest discover -s tests -v
```

## Shutdown and repeatability

Close maintenance, then stop dashboard, gateway and simulator with Ctrl+C. Confirm processes exited before restart. Retain audit records for review. For an independent exercise, configure simulator and gateway to use the same new directory with `--runtime-dir`, and keep it with the evidence.

With custom paths or ports, match `--policy` and `--runtime-dir` on the gateway, `--runtime-dir` on the simulator and `--policy` on the maintenance command. The dashboard reads `COLDSHIELD_POLICY_PATH`, `COLDSHIELD_RUNTIME_DIR`, `COLDSHIELD_GATEWAY_PORT` and `COLDSHIELD_SIMULATOR_PORT` from its environment. The scenario client uses the default ports; use the dashboard for custom-port exercises.

No network discovery, remote target or real-equipment test is part of this guide.
