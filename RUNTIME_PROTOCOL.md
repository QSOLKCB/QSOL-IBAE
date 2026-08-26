# IBAE Runtime Protocol v1

Status: v0.3 implementation contract.

`IBAE-RUNTIME-PROTOCOL-V1` is the narrow in-process boundary between Python orchestration and the Rust execution authority. It is transported as canonical UTF-8 JSON through one opaque PyO3 session. It is not an RPC or network protocol.

## Authority boundary

Python may construct a command, provide an admitted cacheable-read callback, and consume copied outcomes. Rust alone mutates runtime counters, logical ticks, cache, history, and runtime state identity.

The native session exposes only:

- `dispatch(canonical_command, optional_callback)`;
- `snapshot()` returning canonical copied state;
- `terminal_cycle_period()` returning a copied enum-sized value.

There are no Python setters, cache insertion/deletion functions, raw counter functions, or mutable state references.

## Canonical value domain

Protocol values use the existing Python sorted-key, compact UTF-8 JSON profile. Rust independently parses, bounds, re-renders, and byte-compares every command and callback envelope.

The admitted domain is bounded by:

| Property | Hard bound |
|---|---:|
| Canonical UTF-8 bytes | 262,144 |
| Nesting depth | 32 |
| Total value nodes | 4,096 |
| Items in one mapping/sequence | 1,024 |
| UTF-8 bytes in one string | 65,536 |
| Integer magnitude | 256 bits |
| Session/tool/dependency text | 4,096 UTF-8 bytes |

Runtime-emitted outcomes and snapshots use a distinct bounded envelope of 2,097,152 UTF-8 bytes, depth 40, 32,768 nodes, and 4,096 items in one mapping/sequence. This output allowance reserves wrapper depth/space for one fully admitted observation plus its receipt and for every identity in the declared 4,096-entry cache/history bounds; it does not enlarge the arbitrary command, argument, or observation domain.

Mappings require unique string keys. NaN, infinities, non-canonical number spellings, duplicate keys, non-canonical mapping order/spacing, over-size values, and unsupported Python object forms are rejected. Runtime observations additionally require exact JSON Python forms (`None`, exact booleans/integers/floats/strings, exact lists, and exact dictionaries already in canonical key order). Tuples, mapping/scalar subclasses, and non-canonical insertion order reject before cache insertion because JSON cannot preserve their frozen Python reference semantics.

## Commands

Only two closed command variants exist.

### `execute_read`

```json
{
  "admission_id": "<lowercase SHA-256>",
  "arguments": {"path":"example"},
  "command_type": "execute_read",
  "dependency_fingerprint": "<declared deterministic dependency identity>",
  "protocol_version": "IBAE-RUNTIME-PROTOCOL-V1",
  "tool_name": "read.file"
}
```

The Python orchestration adapter admits only `ReplaySafety.CACHEABLE_READ` actions to this path, recomputes the supplied capability contract plus dependency identity against the v0.2 action ID, and binds that verified action ID as `admission_id`. Occurrence-sensitive or effectful actions—and same-name capabilities whose contract identity differs—are rejected by the adapter rather than reclassified. The compatibility executor derives a deterministic admission ID for standalone v0.1 calls.

For a cold read, Rust commits request admission, then actual-execution admission, before invoking the callback. The callback returns one canonical envelope:

```json
{"observation":{"value":42},"status":"ok"}
```

or a closed non-identity-bearing failure envelope:

```json
{"reason_code":"invalid_observation","status":"rejected"}
```

```json
{"reason_code":"operation_failed","status":"rejected"}
```

Exception messages, Python object representations, and addresses never enter correctness identity. A valid observation is canonicalized before cache insertion. A cache hit does not invoke the callback.

### `record_retry`

```json
{
  "admission_id": "<lowercase SHA-256>",
  "command_type": "record_retry",
  "protocol_version": "IBAE-RUNTIME-PROTOCOL-V1"
}
```

This command performs one checked retry-counter transition. It does not request or grant more budget.

Unknown variants—including `request_lease` and `finalize`—reject without runtime mutation. Each canonical attempted command, command type, and valid admission ID remains bound into its distinct rejection receipt. Those command semantics are not reserved by implementation and require their later roadmap phase.

## Transition accounting

The logical runtime tick is a checked exact integer derived only from committed authority transitions:

| Path | Request delta | Execution delta | Cache-hit delta | Logical-tick delta |
|---|---:|---:|---:|---:|
| Accepted cold read | 1 | 1 | 0 | 3 |
| Accepted cache hit | 1 | 0 | 1 | 2 |
| Invalid observation/operation failure | 1 | 1 | 0 | 2 |
| Execution-budget rejection after request admission | 1 | 0 | 0 | 1 |
| Request-budget rejection | 0 | 0 | 0 | 0 |
| Accepted retry | 0 | 0 | 0 | 1 |
| Retry-budget rejection | 0 | 0 | 0 | 0 |
| Malformed/unsupported command | 0 | 0 | 0 | 0 |

Cold observation commit and cache-hit history commit each append the same canonical transition identity. Retained history truncates deterministically at its configured bound. Rust constructs and bounds the complete prospective outcome on an isolated candidate state before replacing authoritative state, so an output-serialization failure cannot leave a committed transition without a receipt.

## Identities

The runtime preserves the merged v0.1 identities:

- `tool_key = SHA256(canonical {arguments, dependency_fingerprint, tool_name})`;
- `observation_id = SHA256(canonical observation)`;
- `transition_id = SHA256(canonical {observation, tool_key})`.

New v0.3 identities use `SHA256(domain || NUL || canonical_record)` with these domains:

- `ibae.runtime-session-id.v1`;
- `ibae.runtime-command-id.v1`;
- `ibae.runtime-state-id.v1`;
- `ibae.runtime-receipt-id.v1`.

A command identity includes its prior state identity, so repeated requests have distinct occurrence identities even when their semantic read key is reusable. State identity includes exact counters/tick, bounded history, cache key/observation identities, limits, protocol, and session identity.

Wall-clock time, latency, build duration, worker/thread/device assignment, Python `hash()`/`id()`, and memory addresses are absent.

## Runtime receipt

Every dispatch returns a canonical outcome with a copied observation (or `null`) and one receipt. The receipt identifies:

- protocol, command type/ID, admission ID, and execution authority layer;
- session, prior-state, and resulting-state IDs;
- tool, canonical-arguments ID, dependency identity, and tool key where applicable;
- exact budget and logical-tick deltas;
- cache status (`cold_execution` or `cache_hit`);
- observation and transition IDs;
- accepted/rejected status;
- structured rejection or `null`;
- domain-separated receipt ID.

Rejections contain a stable reason code, `execution` authority layer, relevant invariant IDs, and a bounded blocking runtime-state projection. Full governance/task/final acceptance receipts are not part of v0.3.

## Rejection taxonomy

```text
IBAE-RT-REJECT-INVALID-CANONICAL-COMMAND
IBAE-RT-REJECT-INVALID-COMMAND
IBAE-RT-REJECT-UNSUPPORTED-COMMAND
IBAE-RT-REJECT-PROTOCOL-VERSION
IBAE-RT-REJECT-REQUEST-BUDGET
IBAE-RT-REJECT-EXECUTION-BUDGET
IBAE-RT-REJECT-RETRY-BUDGET
IBAE-RT-REJECT-ARITHMETIC-OVERFLOW
IBAE-RT-REJECT-INVALID-OBSERVATION
IBAE-RT-REJECT-OPERATION-FAILED
```

No rejection grants authority or promotes execution state into orchestration/governance state.
