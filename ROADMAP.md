# X ColdShield roadmap

This roadmap describes proposed work, not delivered features or commercial commitments. Version 0.2 is a local laboratory prototype. Every stage requires an explicit evidence review before the next stage begins.

| Stage | Objective | Evidence required to proceed |
| --- | --- | --- |
| 0.2 — reproducible laboratory | Strict Modbus TCP framing, bounded local maintenance, explicit register policy, durable local decision records and simulator demonstration | Reproducible automated tests, recorded failure cases, architecture and limitations, dependency installation and demo instructions |
| 0.3 — stronger laboratory validation | Extend negative testing, fuzz the protocol parser, measure load and latency, exercise power-loss recovery and independent review | Published test method and raw results; no loss of policy enforcement under tested faults; documented resource limits |
| 0.4 — partner preparation | Define a controller-specific register map, threat model, physical operating envelope and deployment requirements with a consenting partner | Reviewed requirements; vendor documentation; reproducible controller emulation; acceptance criteria and rollback plan |
| Controlled partner pilot | Evaluate a reviewed configuration in an isolated partner test environment under a separate authorization | Safety review, site-specific authorization, accountable operators, recovery procedures and measured outcomes |
| Product engineering | Build supported operations, authenticated administration, key management, remote log export, lifecycle support and a commercial offering | Independent security assessment, documented compatibility matrix, operational support plan, legal review and validated customer demand |

## Next technical priorities

1. Test fragmented and malformed traffic more extensively, including fuzzing and long-lived connection load. Establish reproducible performance measurements before quoting latency or throughput.
2. Review failure modes with an OT refrigeration engineer. Rejecting a write can have operational consequences; software policy does not replace controller protection or a safety assessment.
3. Replace laboratory register assumptions with an explicitly versioned mapping for each proposed controller. Evaluate scaling, units, device exceptions and allowed functions from authoritative documentation.
4. Design administrator authentication and authorization, signed configuration distribution, credential handling and audit export with independently protected retention.
5. Investigate restart and power-loss behavior, clock trust, policy reload behavior and ambiguous downstream write outcomes. Define recovery ownership and reconciliation procedures.
6. Establish packaging, dependency review, vulnerability response and upgrade/rollback support before promising deployment support.

## Business validation priorities

The initial customer hypotheses are refrigeration integrators, cold-chain operators and food retailers that need better control over remote write commands. These hypotheses are unvalidated. No market size, customer contract, revenue, loss-prevention result or willingness to pay is asserted.

Proposed discovery interviews should establish the actual maintenance workflow, existing network controls, installation constraints, procurement ownership and acceptance criteria. Compare the proposed gateway against controller configuration, network segmentation and existing security products using measured customer requirements.

Incubation could support customer discovery, specialist introductions and product planning. No incubator admission, partner relationship or industrial pilot has been obtained by this repository work. Outreach and any use of real equipment require separate authorization.
