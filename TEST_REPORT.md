# MVP 0.2 verification report

Executed 14 October 2026. Tested implementation revision: `0343702fc221c351b598aac2fa4980cc869b3804`, branch `develop/mvp-v0.2`. Subsequent commits add documentation/evidence only. Source-tree digest (entrypoints, package, tests, verification harness, policy, dependency manifests and workflow): `f67600a01e2561e8c54b7e48ffb20f21b443ac2c410533254ecea553c59a0f18`.

## Observed results

| Environment | Streamlit | Tests run | Failures | Errors | Skipped | Measured suite time |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| macOS arm64, Python 3.11.15 | 1.65.0 | 90 | 0 | 0 | 0 | 15.798727 s |
| macOS arm64, Python 3.14.6 | 1.65.0 | 90 | 0 | 0 | 0 | 3.183352 s |

Suite duration is a test-run measurement; it is not gateway latency, throughput, availability or industrial performance. Cold dependency imports affect duration.

Raw unittest transcripts and machine-readable results:

- [Python 3.11 transcript](docs/test-results-python311.txt) and [JSON](docs/test-results-python311.json)
- [Python 3.14 transcript](docs/test-results-python314.txt) and [JSON](docs/test-results-python314.json)

Each JSON records actual UTC execution time, revision and the same source digest. Runtime tests use temporary directories, ephemeral loopback TCP ports, socket pairs and injected failures. Streamlit tests use headless AppTest. No real industrial equipment, external OT host or network discovery was used. Server/client traffic uses literal `127.0.0.1`.

## Reproduction

Linux/macOS, Python 3.11+:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python scripts/verify.py
```

The harness saves version-specific JSON/transcripts in `docs/` and returns nonzero for a failed suite. A later rerun replaces those evidence files with its own measured result and revision. The standard suite can also run without saving evidence:

```sh
python -m unittest discover -s tests -v
```

Two separate local environments were installed from the universal, hash-pinned dependency lock for final verification. `compileall` completed for application/package/test/harness sources, `git diff --check` passed, and dependency installation with `--require-hashes` succeeded. The initial system environment's `pip check` also reported no broken requirements; final tests use the isolated environments.

## Test inventory

| Suite | Count | Evidence exercised |
| --- | ---: | --- |
| `test_protocol.py` | 18 | Split/short reads, grouped ADUs, invalid MBAP PID/length, partial EOF/timeouts, exact signed FC06, FC03, exception/correlation/read-length/write-echo checks |
| `test_config.py` | 16 | Closed defaults, exact schema/types, hard envelope, UTC/offset lease boundaries, duration, missing/corrupt/duplicate/oversized configuration |
| `test_gateway_review.py` | 11 | Lease revocation/expiry while auditing, audit/reservation failures, ambiguous defrost persistence, active state beyond cooldown, backwards clocks, owner lease, correlated events, concurrent SQLite inserts |
| `test_integration.py` | 26 | Real TCP legitimate maintenance, thermal bounds, closed/expired windows, unknown functions/unit/registers, invalid defrost values, concurrent cascade, restart/cooldown, frame faults, unavailable upstream, pre/post-delivery audit failure, atomic snapshots and >50 persisted events |
| `test_dashboard.py` | 11 | Validated client outcomes; no policy writes; explicit direct/reset gate; outage never shown as protective success; stale/corrupt snapshots/audit; bounded rows; invalid/colliding ports |
| `test_transport_faults.py` | 8 | Real TCP timeout/disconnect/mismatched transaction/wrong echo/device exception/malformed defrost state; revoke during connect before send; retain owner lock until shutdown drains handlers |

## Development failures and corrections

Early protocol tests reproduced an empty-PDU `IndexError`; it now raises `ProtocolError`. Independent review reproduced stale maintenance authorization after audit work; every write is rechecked after blocking work and after connect immediately before send. Python 3.14 exposed unclosed SQLite connections; they now close deterministically. Shutdown now waits for bounded handlers before releasing the runtime owner lock, with a regression test.

The sandbox initially denied loopback socket binding, so integration tests were rerun with local socket execution permitted. The first fresh Python 3.14 environment run executed 90 tests with one AppTest timeout at its 10-second cold-import deadline. The deadline was increased to 30 seconds for initial Arrow/pandas import; final runs above passed in both environments. These intermediate runs are not represented as successful verification.

## Continuous integration

`.github/workflows/tests.yml` runs the complete suite on Ubuntu with Python 3.11 and 3.14, installing hash-pinned dependencies. It triggers on development-branch pushes, pull requests and manual dispatch. After the account holder authorized the missing `workflow` scope, the branch was published. [GitHub Actions run 38653980180](https://github.com/undereis/x-coldshield-mvp/actions/runs/38653980180) completed successfully on Ubuntu/Python 3.11 and 3.14 at revision `42e33e0c167ef1aee9e46c26d212daec0aecc3c2`. Both job logs show `Ran 90 tests` followed by `OK`; their installation and test steps succeeded. [Machine-readable CI evidence](docs/ci-results.json) records job links, completion timestamps and measured suite durations. A later documentation-only update records this result without changing tested application code.

## What the evidence does not establish

No vendor conformance suite, actual controller, physical/thermodynamic refrigeration model, hardware deployment, BACnet, security certification, immutable logging, authenticated contractors, power-loss test, sustained-load test, fuzz campaign, independent third-party security assessment or field pilot was completed. AppTest verifies application behavior, not browser layout across devices. Network failures can leave write delivery unknown; acknowledgment verifies the simulator reply, not a measured physical effect.
