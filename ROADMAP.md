# Evolution after MVP 0.2.1

Version 0.2.1 adds bounded sessions and audit storage, conservative publication recovery, serialized local administration, topology checks and measured evaluation artifacts. It remains an isolated prototype. Historical v0.2 test evidence stays available; [MVP_0_2_1_REPORT.md](MVP_0_2_1_REPORT.md) compares the two versions.

## Version 0.3 evidence gates

1. Separate authenticated administrative identity/roles from a host-wide maintenance window, with revocation and an explicit threat model. Preserve closed defaults.
2. Design controlled archive/restore and reconciliation for pending intents/reservations, full audit capacity and uncertain simulator state. Test interrupted writes and real process crashes; avoid treating injected errors as power-loss proof.
3. Introduce reproducible parser fuzzing/property tests and long-running reconnect/load experiments, measuring fairness, shutdown latency, queue behavior and storage growth. Define limits before claiming performance.
4. Test monotonic deadlines alongside UTC clock changes and scheduled maintenance, including storage stalls that socket timeouts cannot preempt.
5. Obtain refrigeration/OT specialist review of synthetic rules. Document vendor-specific maps only from authoritative documentation and authorized isolated test benches; qualify every interoperability claim.
6. Prepare packaging, supported operating systems, upgrade/rollback and dependency/security maintenance procedures.

## Incubation and customer discovery

Use the local evidence to invite technical challenge and interviews with refrigeration integrators, OT specialists and cold-chain operators. Establish maintenance workflows, existing controls, procurement ownership and measurable acceptance criteria. No market traction, loss-prevention metric or industrial readiness follows from simulator results. EuraTechnologies evaluation is the immediate target; outreach, application submission and real-equipment trials require separate authorization.
