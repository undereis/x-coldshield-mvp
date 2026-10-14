# Original MVP audit and v0.2 remediation

Audit target: original commit `ed5cfc68eb9e770626d8510d748f1dd41590d447` on `master`, 14 October 2026. The local checkout was clean and matched its tracked remote branch. The connected GitHub integration returned the original `master/x_coldshield_proxy.py`, matching the reviewed local source. All nine tracked files were inspected: four Python entrypoints, README, policy, two historical JSON samples and `.gitignore`. Local ignored skill instructions were also read; personal outreach/dossier files were excluded from the deliverable and retained locally.

This is a source-based engineering audit with independent QA review, followed by laboratory regression testing. It is not a certified assessment or a full industrial security evaluation. Original line references below refer to the immutable baseline commit, not the rewritten files.

## What was implemented originally

The original gateway listened on loopback and inspected function 06 single-register writes. It checked an upper limit on registers 0–2, gated writes using a maintenance boolean, and counted defrost starts within 120 seconds. A synthetic register simulator, interactive attack client and Streamlit dashboard demonstrated those rules. JSON files stored at most 50 events and current simulated setpoints.

No tests, dependency manifest, CI, installation procedure, threat model or vendor compatibility evidence existed. The original simulator was not a refrigeration process model.

## Findings and remediation

| Priority | Original evidence | Problem and impact | v0.2 response |
| --- | --- | --- | --- |
| High | `x_coldshield_proxy.py:54–58,106–118` | One `recv` assumed one frame; first 12 bytes inspected, entire chunk forwarded. No MBAP protocol/length/unit checks. Legitimate fragments fail and grouped ADUs are not independently checked. Original simulator discards trailing data; a compliant downstream server could process unchecked extra requests. | Exact MBAP-directed bounded reads, protocol/length validation, per-frame unit and PDU validation; grouped frames inspected separately. |
| High | `x_coldshield_proxy.py:61–88`; `danfoss_sim.py:57–58` | Unknown functions/registers allowed; arbitrary nonzero defrost values bypass start rule. | Fixed unit/function/register allowlist and 0/1 defrost values, exact request shapes. |
| High | `x_coldshield_proxy.py:21–31,63` | Missing/corrupt policy enables maintenance, with no schema validation. | Invalid policy refuses forwarding; schema v2, strict types/keys, duplicate rejection and size limit. |
| High | `x_coldshield_proxy.py:78–86` | Expiring command counter is not active-defrost coordination; restart erases it. | Live defrost register reads, serialized command decisions, persistent conservative start reservations. |
| High | `x_coldshield_proxy.py:103–119`; `danfoss_sim.py:49–61` | Sequential sockets without deadlines allow one client/upstream to stall service. | Bounded workers and frame/connection deadlines; parseable failures return exceptions. |
| Medium | `x_coldshield_proxy.py:115–120` | ALLOWED logged before unvalidated response; delivery failure merely printed. | Correlated authorization and outcome, exact echo/response matching; ambiguous delivery recorded as unknown. |
| Medium | `x_coldshield_proxy.py:33–52` | Non-atomic rewrite, 50-event cap and silent reset on parse error lose evidence. | Transactional SQLite with full synchronous writes requested; bounded read-only dashboard query. No immutability claim. |
| Medium | `dashboard.py:10–20,54–67` | Any response treated as applied; timeout reported as successful blocking; direct attack success unconditional. | Shared validated client distinguishes acknowledgment, policy denial and communication uncertainty. |
| Medium | `dashboard.py:29–42,80–106` | Every rerun writes policy; partial JSON can crash display; thermal slider permits weaker ceiling. | Dashboard reads policy only; explicit local CLI manages bounded leases. Snapshot validation/staleness warnings. |
| Claims | README; `dashboard.py:25,103`; `danfoss_sim.py:32–36` | BACnet, NIS 2 readiness, contractor zero trust, vendor emulation and spoilage claims exceed code/evidence. | English docs/UI state narrow laboratory scope, synthetic setpoints, no certification or industrial interoperability claim. |

## Intentional security behavior changes

- The old two-key policy is replaced with explicit schema v2. There is no silent migration that opens maintenance. The repository policy is closed, and malformed legacy policies are denied.
- Reads using FC03 are added for the fixed map; all other functions are denied. This is a deliberate narrow subset. No BACnet is implemented.
- All FC06 writes, including defrost OFF, require maintenance. Safe setpoint writes use a laboratory interval within -40°C to -15°C; the ceiling cannot be relaxed through configuration. These values are demonstration rules, not validated physical limits.
- Maintenance is an explicit timezone-aware lease of at most 900 seconds, checked again after blocking work and immediately before socket send. It authorizes host-local attempts, not identified contractors. File replacement remains a local-admin trust boundary.
- Defrost starts check live synthetic state and a 120-second start cooldown. Same-aisle ON is idempotently permitted when no other aisle is active. OFF does not erase cooldown. Failed/unknown delivery retains reservations; this may deny a legitimate later start conservatively.
- Parseable denials now receive Modbus exceptions instead of an unexplained disconnect. Invalid framing is closed. Lost/malformed responses indicate uncertainty and are never automatically retried.
- Authorization intent must persist before forwarding. Post-delivery audit failure returns an error and cannot undo the write; a dangling intent must be reconciled.
- Runtime artifacts move to ignored `runtime/`; old tracked JSON examples and historical entrypoint names remain available. Original code remains in Git history. No original tracked file was deleted.

Each change is covered by the executable suites described in `TEST_REPORT.md`. Initial QA found and reproduced empty-PDU handling, policy-revocation timing, SQLite connection lifecycle and shutdown lease issues; those were corrected before final verification.

## Remaining risks and recommendations

This design assumes one gateway owns the simulator. The runtime lock prevents a second gateway sharing that directory; independent runtime directories or direct simulator clients are not coordinated. State-check/write atomicity does not extend across bypass clients. Wall-clock manipulation, privileged local filesystem edits, compromised dependencies and upstream state forgery remain outside protection. Retain the audit database and do not clear reservations to work around denials without a controlled lab reset.

No real controller, industrial network, physical refrigeration process, formal protocol conformance suite, destructive power-loss test, long soak test, denial-of-service assessment or commercial deployment was exercised. Logging lacks authentication, remote retention and tamper resistance. Dashboard dependencies are transitively pinned with hashes; a dependency vulnerability assessment remains pending. Linux/macOS are the intended hosts because the owner lock uses `fcntl`; Windows support is pending.

The appropriate next steps are authenticated administration, verified device/register maps, isolated partner simulation, physical model and safety/availability review, independent protocol/security assessment and protected audit export. `ROADMAP.md` defines evidence gates before any separately authorized industrial pilot.
