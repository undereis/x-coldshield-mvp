# Security model and limitations

## Intended use

X ColdShield 0.2.1 is a loopback-only laboratory prototype. Current tests use software clients and a software simulator. Do not connect the demonstration to industrial equipment or expose its services to another host.

The register map and temperature limits illustrate policy enforcement. They are not validated refrigeration safety limits, a controller safety function or evidence of food-safety protection. No NIS 2 certification, compliance determination, BACnet support or industrial compatibility is claimed.

## Assets, trust boundaries and threats

| Asset or boundary | Threat considered | Laboratory control | Remaining limitation |
| --- | --- | --- | --- |
| Client → gateway stream | Fragmented, grouped, invalid/incomplete frames | Length-aware framing, fixed request shapes, deadlines | No full conformance or exhaustive fuzzing proof |
| Command policy | Unknown functions/registers or unsafe synthetic values | Function/unit/register allowlist, bounded signed values | Synthetic mapping covers a narrow subset |
| Maintenance | Writes outside an authorized interval | Closed default, bounded UTC interval | No identity, MFA, roles or remote administration |
| Defrost | Coordinated starts and restart evasion | Upstream state check, serialized decisions, persistent reservations | Trusts simulator/host; independent gateways and bypass clients not coordinated |
| Policy file | Invalid or accidentally relaxed policy | Strict schema, hard laboratory thermal ceiling | A privileged user can replace code/files |
| Upstream connection | Timeout, malformed reply, unavailable simulator | Bounded exchanges, validated replies, uncertainty records | Write may apply before acknowledgment is lost |
| Event records | Lost intent or accidental truncation | SQLite transactions, synchronous durability requested, intent before send | No tamper resistance or remote retention |
| Simulator access | Gateway bypass | Loopback scope, explicit demo bypass control | Local processes can bypass via port 5020 |
| Availability | Slow clients or connection exhaustion | Eight clients, finite session age/frame count, bounded queue waits | Reconnect flooding, unfair scheduling and sustained operation remain unvalidated |

The trusted computing base includes Python, the OS, local administrator, clock, filesystem, policy and simulator. A compromised local administrator is outside the enforcement boundary. Modbus messages do not authenticate a contractor; the MVP adds no TLS or cryptographic client identity.

## Failure behavior

Invalid configuration, unknown commands, unverified defrost state and pre-forward audit errors prevent a new write from being forwarded. A blocked parseable command produces a protocol exception where possible; invalid framing or broken connections may close the session.

If a write is sent and its upstream reply is lost, the outcome is uncertain. The simulator may have accepted it. A permitted decision must not be displayed as confirmed application. Defrost reservations are retained conservatively after ambiguous outcomes. Post-write logging failure cannot undo a write.

Refusing a command can affect an industrial process. This laboratory policy is not a universal safe state and has not been assessed for refrigeration availability, equipment damage or hazards. Future deployment requires site-specific engineering review and an independently reviewed recovery strategy.

## Deliberate demonstration exceptions

The simulator accepts out-of-envelope thermal setpoints to demonstrate bypass. The dashboard requires explicit opt-in for direct simulator exercises. Direct access does not authenticate users and must stay local. Historical tracked JSON samples are not the active event store.

Opening maintenance with `python -m coldshield.maintenance open --seconds 300` authorizes local write attempts for that interval. Anyone reaching the gateway from the host can attempt writes. File permissions and exclusive lab access are assumptions, not an implemented identity system.

## Storage and traceability

SQLite records correlate decisions/outcomes using request identifiers and a policy digest. The digest identifies canonical configuration content; it does not authenticate the author. Host administrators can alter/delete records. No immutable, independently verified or certified audit trail is provided. Disk/storage failures prevent new forwarding when detected before send; post-send failures remain uncertain. Storage capacity can intentionally stop authorized traffic. An exception 4 from the simulator can follow a visible but not durably confirmed write; classify it as unknown rather than proof of no effect. Maintenance recovery requires an explicit successful close. POSIX fsync/flock behavior assumes a functioning local filesystem; simultaneous failures that prevent both quarantine recovery and removal cannot provide a persistent fail-closed guarantee. The services must then be stopped by the operator.

Keep runtime evidence, policy, code revision and test environment together when reviewing an exercise. The bounded laboratory retention/aggregation and coherent export policy is described in [ARCHITECTURE.md](ARCHITECTURE.md). External integrity protection, authenticated access and operational archival recovery remain future work.

## Vulnerability reporting

Do not post credentials, production endpoints or sensitive traces in public issues. Report non-sensitive reproducible laboratory problems through the repository's existing issue process. No private disclosure channel or response-time commitment is established; coordinate with the maintainer before sharing sensitive details.

## Before a future partner pilot

A pilot requires separate authorization, a verified device map, vendor documentation, safety/availability assessment, authenticated administration, enforced network placement, recovery procedures, clock/storage review and independent testing. These are roadmap requirements, not completed work. See [ROADMAP.md](ROADMAP.md).
