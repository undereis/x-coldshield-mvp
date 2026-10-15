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

Final clean-checkout measurements and artifact links are appended after immutable source validation below. Earlier development checks ran all 162 tests in both Python 3.11.15 and 3.14.6 with zero failures/errors/skips. The automated demonstration is also exercised by the suite. Complete raw v0.2 results remain unchanged in `docs/test-results-python*`.

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
