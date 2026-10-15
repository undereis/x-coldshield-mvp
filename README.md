# X ColdShield — MVP 0.2.1

X ColdShield is a **local laboratory prototype** of a refrigeration command-policy gateway. It evaluates a deliberately small Modbus TCP register map against maintenance, setpoint and defrost constraints, then forwards permitted requests to a software simulator.

This repository does not establish industrial controller compatibility, food-safety protection, a validated physical model, BACnet support, NIS 2 compliance or certification. Displayed temperatures are simulated **setpoints**, not sensor telemetry. Read [security limitations](SECURITY.md) before evaluating the demonstration.

## Implemented scope

- Length-aware Modbus TCP framing for fragmented or grouped messages, with header and request validation.
- Explicit laboratory allowlist: unit 1, function 03 (read holding registers), function 06 (write one register), setpoint registers 0–2 and defrost registers 10–12.
- Validated policy reloads, closed maintenance by default and a bounded UTC maintenance window.
- Setpoint limits and conservative defrost coordination using simulator state and persistent reservations.
- SQLite intent/outcome records with request identifiers and policy digests. These are local records, **not immutable logs**.
- Loopback-only simulator, scenario client and Streamlit demonstration dashboard.

Read [the original-version audit](AUDIT_REPORT.md) for baseline findings and [the test report](TEST_REPORT.md) for actual verification results.

## Installation

Use Python 3.11 or newer on Linux or macOS. The gateway currently uses POSIX file locking. Run commands from the repository root. Gateway and simulator use the Python standard library. Install requirements for the dashboard and the complete test suite, including Streamlit AppTest checks.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
```

## Automated evaluation

```sh
python scripts/demo.py --output-dir runtime/demo-evaluation
python scripts/verify.py --output-dir runtime/verification-evaluation
```

Choose a new output directory for each run. The demo starts actual simulator and gateway subprocesses on reserved local ports, asserts each result and observed register state, closes maintenance, stops both children and exports correlated audit evidence. Its JSON, Markdown report and SHA-256 manifest support a repeatable technical presentation. See [the 0.2.1 comparison report](MVP_0_2_1_REPORT.md).

Sessions allow at most eight concurrent clients per service, 30 seconds and 64 frame attempts. Excess connections close; reconnects remain possible. Critical audit records have a 4096-event/8 MiB database budget, with limited repeated denial summaries. Capacity exhaustion refuses further authorized operations before upstream contact.

## Local demonstration

Start the simulator in terminal 1:

```sh
python danfoss_sim.py
```

Start the gateway in terminal 2:

```sh
python x_coldshield_proxy.py
```

Open a five-minute laboratory maintenance window in terminal 3, then run the dashboard:

```sh
python -m coldshield.maintenance open --seconds 300
python -m streamlit run dashboard.py --server.address 127.0.0.1
```

The simulator listens on `127.0.0.1:5020` and the gateway on `127.0.0.1:5021`. All network exercises stay local. Do not attach industrial equipment. The dashboard includes an explicitly enabled direct-simulator comparison that bypasses the gateway.

For the terminal scenario menu:

```sh
python attack_simulator.py
```

Close maintenance after the exercise:

```sh
python -m coldshield.maintenance close
```

See [the demo guide](docs/DEMO.md) for expected outcomes, failure interpretation and shutdown instructions.

## Verification

```sh
python scripts/verify.py --output-dir runtime/verification-manual
```

Environment, commands and observed results belong in [TEST_REPORT.md](TEST_REPORT.md). Tests demonstrate only exercised laboratory behavior; they do not certify a product or prove safety on real equipment.

## Repository map

| Path | Role |
| --- | --- |
| `coldshield/` | Protocol framing, policy validation, enforcement, audit and laboratory utilities |
| `x_coldshield_proxy.py` | Gateway entrypoint |
| `danfoss_sim.py` | Illustrative simulator entrypoint; filename retained for continuity |
| `attack_simulator.py` | Local scenario client |
| `dashboard.py` | Streamlit demonstration and event viewer |
| `policy_config.json` | Versioned laboratory policy; maintenance closed by default |
| `runtime/` | Generated SQLite records and simulator state; excluded from Git |
| `tests/` | Reproducible local automated tests |
| `.github/workflows/` | Automated verification configuration |

The tracked `danfoss_state.json` and `security_events.json` files are historical examples from the original MVP, not current runtime evidence. New runtime artifacts belong in `runtime/`.

## Evaluation materials

- [Delivery report](DELIVERY_REPORT.md)
- [Architecture](ARCHITECTURE.md) and [security model](SECURITY.md)
- [Original audit](AUDIT_REPORT.md), [test evidence](TEST_REPORT.md) and [roadmap](ROADMAP.md)
- [English incubation brief](docs/INCUBATOR_BRIEF_EN.md) and [French incubation brief](docs/INCUBATOR_BRIEF_FR.md)

The development branch is `codex/mvp-v0.2.1`. The audited baseline `develop/mvp-v0.2` and `master` are preserved; no merge is part of this release.
