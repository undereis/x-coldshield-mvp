# X ColdShield MVP 0.2.1 — delivery and comparison

This release targets a reproducible **laboratory technical evaluation** for EuraTechnologies. It does not establish industrial deployment readiness. The audited baseline is `develop/mvp-v0.2` at `8ec975456e1c13de8f94dcb173fc25567ad04b4c`. Work is isolated on `codex/mvp-v0.2.1`; `master` and v0.2 are preserved and no merge is authorized.

## Comparison and corrected behavior

| Area | v0.2 | v0.2.1 |
| --- | --- | --- |
| Responsive sessions | Complete frames could occupy all workers indefinitely | Eight clients/service, 30 s maximum/session, 64 frame attempts; overflow closes and workers are joined before lease release |
| Audit growth | Every denial created a new durable event without a budget | 4096 detailed/reserved events, 8 MiB main DB, known denial aggregation after 256 details; critical outcomes remain detailed; capacity failures refuse forwarding |
| Atomic state | Post-replace fsync failure could leave new disk state but rolled-back memory | Visibility and durability distinguished; visible state retained, error returned, writes degraded until a successful snapshot |
| Maintenance | Concurrent stale read/modify/write could reopen a closed policy | Entire update serialized by flock; strict single read; uncertainty quarantine and explicit close recovery |
| Startup | Same upstream/listener port could loop back into gateway | Invalid ports, timeouts, startup policy and self-targeting topology rejected |
| Time budgets | Client could expire before ordinary gateway phases | 5 s client, 4 s complete request, 1 s upstream exchange; deadlines include framing/queueing and no automatic write retry |
| Unknown outcome | Device exception could be described as rejection after an applied uncertain write | Non-policy device errors recorded as UNKNOWN with delivery uncertainty; validated acknowledgments remain distinct |
| Invalid stored interlock | Missing table could silently be recreated empty | Existing schema/integrity/state validated; valid v0.2 migration preserves events/cooldown, damaged stores refused |
| Test proof | 90 tests; post-run revision and no discovery invariance | 162 exact IDs, pre/post source/Git identity, skips/collection/drift fail, clean CI and retained artifacts |
| Demonstration | Manual separate actions | Actual CLI subprocesses, 11 asserted protocol transactions and two administrative operations, state reads, cleanup/export/hash manifest |

The original session-occupation trigger now terminates responsive sessions at quota/age, releases their slots, and allows a new client. Shutdown interrupts idle clients and retains runtime ownership while an actual worker is still processing. Malformed/unknown-function denial floods use a bounded set of exact-count summaries; they cannot grow detailed records indefinitely. Legitimate fragmented/grouped frames, authorized -22°C writes, reads, closed-default maintenance and conservative persistent defrost coordination remain covered.

An independent read-only candidate review identified the exception-4 uncertainty and missing-table recovery cases. Both were independently reproduced before correction and added to regression coverage. This is an agent-assisted engineering review, not an external security certification.

## Verification and evidence

Executed 15 October 2026 on macOS arm64, clean source commit `6c4d4395aa3ede31528632cd440f98dca5c961bb`, branch `codex/mvp-v0.2.1`. Both runs recorded unchanged clean Git state and source manifests before/after. Source digest: `1c5961cde43dc3ae54d6c5999d6a07d356c5033cc8ce2327c4cbb782ed11744e`. Subsequent release evidence/documentation commits leave this measured source digest unchanged. CI additionally tests the exact published revision.

| Python | Tests | Failures | Errors | Skips | Measured verifier duration | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 3.11.15 | 162 | 0 | 0 | 0 | 6.865964 s | PASSED |
| 3.14.6 | 162 | 0 | 0 | 0 | 6.905903 s | PASSED |

These durations cover verification/discovery and are not throughput or latency benchmarks. The independent automated demo passed all 13 rows (11 protocol transactions plus maintenance open/close). Both child processes exited with status 0, private maintenance was closed and the complete demo manifest's hashes were verified. The suite also runs a real subprocess demo once per Python version.

Retained evidence:

- [Python 3.11 JSON](docs/evidence-v0.2.1/python311/evidence.json) and [transcript](docs/evidence-v0.2.1/python311/transcript.txt).
- [Python 3.14 JSON](docs/evidence-v0.2.1/python314/evidence.json) and [transcript](docs/evidence-v0.2.1/python314/transcript.txt).
- [Demonstration report](docs/evidence-v0.2.1/demo-report.md), [JSON](docs/evidence-v0.2.1/demo-report.json), [audit export](docs/evidence-v0.2.1/demo-audit-export.json), and [complete demo bundle](docs/evidence-v0.2.1/demo-bundle.tar.gz). Extract the bundle to verify its internal `manifest.json`, including runtime state/database and logs.
- [SHA-256 evidence manifest](docs/evidence-v0.2.1/checksums.json).

Complete raw v0.2 results remain unchanged in `docs/test-results-python*`. The earlier targeted unittest invocation by module name exposed an existing sibling import convention; the supported `discover -s tests` command and verifier both use the correct collection path. No collection error was excluded from final results.

Reproduce from a clean checkout with hash-pinned dependencies:

```sh
python scripts/verify.py --require-clean --output-dir runtime/evaluation-tests
python scripts/demo.py --output-dir runtime/evaluation-demo
python -m coldshield.audit_export --audit runtime/evaluation-demo/runtime/audit.sqlite3 --output runtime/second-export.json
```

The demo uses fresh private policy/runtime and ephemeral loopback ports, closes maintenance and stops its own processes. It records transaction/request correlation, reason, decision, observed values, timestamps, code version, revision and checksums. A mismatch, forced shutdown or missing export fails the demonstration. It does not operate real equipment or probe remote services. CI publication uses GitHub only.

## Retention, recovery and communication contract

Only six repeated decision-denial reasons are aggregated: FUNCTION_NOT_ALLOWED, REGISTER_NOT_ALLOWED, UNIT_NOT_ALLOWED, INVALID_PDU, INVALID_FRAME and MAINTENANCE_CLOSED. Their counters retain first/last IDs and timestamps and the latest bounded sample; intermediate individual IDs are not preserved after the detail threshold. Thermal/interlock denials, policy failures, authorization and outcomes remain detailed. No automatic deletion or truncation occurs. Two event slots are reserved before authorized upstream contact. A row reservation cannot guarantee later physical I/O success. The database cap excludes transient rollback journal/metadata and evidence copies.

Export captures events, denial summaries, pending reservations and defrost cooldown state in one database read transaction. It does not free space. Archive a stopped run's export and database before explicitly choosing a fresh runtime for another independent exercise; this does not migrate cooldown state. Pending intents/reservations need operator interpretation, never automatic retry. Schema version 3 explicitly migrates the valid v0.2 core; missing/invalid critical state refuses startup.

ACKNOWLEDGED means a matching FC06 reply, DENIED means a policy/protocol refusal, and UNAVAILABLE in the client means no confirmed acknowledgment and must be treated as unknown. A device exception 4 can follow an applied write. The gateway audit labels such an upstream error UNKNOWN; transport failure retains FAILED with `delivery: unknown`. No retry is automatic. [ARCHITECTURE.md](ARCHITECTURE.md) defines the budgets and recovery sequence.

## Remaining risks and v0.3

- No authenticated client/admin identity, TLS or separation from other local processes; direct simulator access bypasses gateway controls. Separate runtime directories do not coordinate one simulator.
- Session limits do not ensure fairness or resist sustained reconnect flooding. Storage exhaustion deliberately stops authorized traffic. Logs/evidence are local and editable.
- Socket deadlines cannot preempt a stuck filesystem/kernel operation; scheduling/load can exceed ordinary timing budgets. Real power loss, long soaks and fuzzing remain untested.
- Total filesystem refusal can prevent durable quarantine/recovery; stop services if the administrative tool reports that policy may remain visible. No software-only claim of unconditional durability is made.
- The snapshot cannot attest to its own subsequent fsync; simulator restart resets synthetic values. Uncertain state requires reconciliation rather than a retry.
- UTC-clock changes affect maintenance/cooldown. Deployment, multi-gateway operation, archive/restore and crash reconciliation need separate design.
- Only unit 1, FC03/06, a synthetic register map and signed integer-degree setpoints are implemented. No Danfoss/Carel compatibility, BACnet, validated physics, NIS 2 compliance, immutable audit or certified safety is claimed.

Version 0.3 should prioritize authenticated administration, archive/reconciliation recovery, parser fuzzing/soak measurements, clock/storage fault testing and specialist review with explicit acceptance criteria. No real-equipment test is authorized by this release.

Recommendation: suitable for an initial technical presentation as an isolated prototype when accompanied by the measured evidence and these limits. It is not suitable for controlling industrial equipment. Incubator acceptance, partner interest and commercial value remain unvalidated.

## Changed files

- `.github/workflows/tests.yml`
- `ARCHITECTURE.md`
- `DELIVERY_REPORT.md`
- `MVP_0_2_1_REPORT.md`
- `README.md`
- `ROADMAP.md`
- `SECURITY.md`
- `TEST_REPORT.md`
- `coldshield/__init__.py`
- `coldshield/audit_export.py`
- `coldshield/client.py`
- `coldshield/config.py`
- `coldshield/gateway.py`
- `coldshield/limits.py`
- `coldshield/maintenance.py`
- `coldshield/protocol.py`
- `coldshield/server.py`
- `coldshield/simulator.py`
- `coldshield/storage.py`
- `danfoss_sim.py`
- `docs/DEMO.md`
- `docs/INCUBATOR_BRIEF_EN.md`
- `docs/INCUBATOR_BRIEF_FR.md`
- `scripts/demo.py`
- `scripts/verify.py`
- `tests/expected_inventory.json`
- `tests/test_demo_v021.py`
- `tests/test_evidence_v021.py`
- `tests/test_gateway_review.py`
- `tests/test_gateway_v021.py`
- `tests/test_maintenance_v021.py`
- `tests/test_protocol_deadlines_v021.py`
- `tests/test_sessions_v021.py`
- `tests/test_storage_v021.py`
- `tests/test_transport_faults.py`
- `x_coldshield_proxy.py`
- `docs/evidence-v0.2.1/`: retained measured reports, transcripts, export and complete demo bundle.
