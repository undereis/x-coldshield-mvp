# X ColdShield — incubation brief

**Stage:** MVP 0.2, local laboratory prototype. **Project owner:** repository maintainer. **Purpose:** technical evaluation and customer discovery; this document is not evidence of industrial deployment.

## Problem and customer hypothesis

X ColdShield explores how to restrict refrigeration control commands when an otherwise valid industrial message requests an operation outside an agreed operating envelope. The starting hypothesis is that refrigeration integrators, cold-chain operators and retailers may benefit from a gateway that explains why a write was accepted or refused.

Customer need, buying process and willingness to pay have not been validated. No quantified market size or commercial traction is claimed.

## Technical approach

The prototype combines protocol validation with application-specific command policy. A local Modbus TCP gateway accepts only a small laboratory register map and function set. It checks signed temperature setpoints, bounded maintenance authorization and defrost coordination before forwarding a permitted operation to a software simulator. A dashboard presents simulated setpoints and decision records.

The intended differentiator is explainable policy tied to refrigeration control semantics. Its effectiveness relative to existing products remains a research and validation question. The current rules are hand-defined constraints, not a validated thermodynamic model or adaptive detection system.

## Architecture and evidence

The demonstration runs on loopback: a client or Streamlit dashboard sends a request to the gateway on port 5021, which evaluates it and communicates with the simulator on port 5020. Policy configuration is validated, maintenance is closed by default, and intent/outcome events are stored in a local SQLite database. Persistent defrost reservations support conservative behavior after ambiguous communication outcomes.

The evidence package is available in [README](../README.md), [architecture](../ARCHITECTURE.md), [security limitations](../SECURITY.md), [original-version audit](../AUDIT_REPORT.md), [test report](../TEST_REPORT.md) and [demo guide](DEMO.md). Only executed checks recorded in the test report count as test results; source code or a proposed scenario alone does not establish a successful outcome.

## Present limitations

The simulator is an illustrative controller, not a validated Danfoss, Carel or other vendor implementation. The project has no demonstrated industrial interoperability, BACnet implementation, hardware deployment, independent security assessment or field validation. Displayed values are commanded setpoints, not sensor measurements. The maintenance window is a local policy mechanism without contractor identity verification. Local event records can be modified by a host administrator and are not immutable. There is no NIS 2 certification or compliance determination.

## Next milestones

Near-term work is parser fuzzing, failure/recovery experiments, reproducible performance measurements and review by refrigeration/OT specialists. Subsequent work is authenticated administration, controller-specific mappings and independent security review. A controlled partner pilot is conditional on a separately reviewed safety and authorization plan. The [roadmap](../ROADMAP.md) defines evidence gates.

## Proposed validation with French partners

No partnership or pilot is currently established by this work. A proposed sequence is:

1. Seek introductions to a French refrigeration integrator, an OT security specialist and a cold-chain operator for discovery interviews.
2. Agree on a documented register map, maintenance workflow, hazards and acceptance criteria, using vendor documentation and synthetic traces.
3. Reproduce those requirements in an isolated simulator and let partner engineers review decision records and failure cases.
4. Consider an isolated partner test bench only after explicit authorization, safety review and rollback planning. Do not connect this MVP to operating refrigeration equipment as part of the present demonstration.

EuraTechnologies is a potential incubation target because its official site lists cybersecurity and industry among its focus areas. This is a fit hypothesis, not an affiliation or endorsement. See [EuraTechnologies](https://www.euratechnologies.com/en) (checked 14 October 2026). Current program requirements and application availability must be confirmed separately before submission.

The requested support would be technical challenge, customer discovery, introductions and help defining a credible commercialization plan. The immediate evaluation question is whether the laboratory evidence and the proposed validation program justify further investigation.
