//! Exact, bounded deterministic execution authority and compact evidence
//! reduction for QSOL-IBAE v0.3/v0.4.
//!
//! The crate deliberately exposes one runtime command dispatcher plus one
//! opaque evidence accumulator and non-constructible source seals rather than
//! leaking implementation helpers across the Python/Rust boundary. It has no
//! network, model-provider, async-runtime, or wall-clock integration.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyModule};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::sync::Arc;

const PROTOCOL_VERSION: &str = "IBAE-RUNTIME-PROTOCOL-V1";
const COMMAND_DOMAIN: &str = "ibae.runtime-command-id.v1";
const RECEIPT_DOMAIN: &str = "ibae.runtime-receipt-id.v1";
const SESSION_DOMAIN: &str = "ibae.runtime-session-id.v1";
const STATE_DOMAIN: &str = "ibae.runtime-state-id.v1";

const EVIDENCE_PROTOCOL_VERSION: &str = "IBAE-COMPACT-EVIDENCE-V1";
const EVIDENCE_PROFILE: &str = "IBAE-COMPACT-EVIDENCE-COUNTS-AND-IDENTITIES-V1";
const EVIDENCE_ADMISSION_DOMAIN: &str = "ibae.evidence-admission-aggregate.v1";
const EVIDENCE_INPUT_DOMAIN: &str = "ibae.evidence-input-aggregate.v1";
const EVIDENCE_RESULT_DOMAIN: &str = "ibae.evidence-result-aggregate.v1";
const EVIDENCE_CASE_RECEIPT_DOMAIN: &str = "ibae.evidence-case-receipt-aggregate.v1";
const EVIDENCE_SUMMARY_DOMAIN: &str = "ibae.evidence-aggregate-summary.v1";
const EVIDENCE_AUTHORIZATION_DOMAIN: &str = "ibae.evidence-authorization-manifest.v1";
const EVIDENCE_RECEIPT_DOMAIN: &str = "ibae.compact-evidence-receipt.v1";
const EVIDENCE_EXPANSION_DOMAIN: &str = "ibae.evidence-expansion.v1";
const FAST_FOLD_ALGORITHM: &str = "fnv1a64-non-cryptographic-v1";

const MAX_CANONICAL_VALUE_BYTES: usize = 262_144;
const MAX_CANONICAL_VALUE_DEPTH: usize = 32;
const MAX_CANONICAL_VALUE_NODES: usize = 4_096;
const MAX_CANONICAL_COLLECTION_ITEMS: usize = 1_024;
const MAX_CANONICAL_STRING_BYTES: usize = 65_536;
const MAX_RUNTIME_RECORD_BYTES: usize = 2_097_152;
const MAX_RUNTIME_RECORD_DEPTH: usize = 40;
const MAX_RUNTIME_RECORD_NODES: usize = 32_768;
const MAX_RUNTIME_COLLECTION_ITEMS: usize = 4_096;
const MAX_RECORD_TEXT_BYTES: usize = 4_096;
const MAX_INTEGER_DECIMAL: &str =
    "115792089237316195423570985008687907853269984665640564039457584007913129639935";

const MAX_REQUESTS: u64 = 1_000_000;
const MAX_EXECUTIONS: u64 = 4_096;
const MAX_RETRIES: u64 = 1_000_000;
const MAX_HISTORY: u64 = 4_096;

const MAX_EVIDENCE_CASES: u64 = 1_000_000;
const MAX_EVIDENCE_FAILURE_DETAILS: u64 = 32;
const MAX_EVIDENCE_CASE_BYTES: usize = 16_384;
const MAX_EVIDENCE_FAILURE_DETAIL_BYTES: usize = 4_096;
const MAX_COMPACT_EVIDENCE_BYTES: usize = 2_048;
const MAX_EVIDENCE_EXPANSION_BYTES: usize = 262_144;
const MAX_EVIDENCE_AUTHORIZATIONS: usize = 256;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Reason {
    InvalidCanonicalCommand,
    InvalidCommand,
    UnsupportedCommand,
    ProtocolVersionMismatch,
    RequestBudgetExhausted,
    ExecutionBudgetExhausted,
    RetryBudgetExhausted,
    ArithmeticOverflow,
    InvalidObservation,
    OperationFailed,
}

impl Reason {
    fn code(self) -> &'static str {
        match self {
            Self::InvalidCanonicalCommand => "IBAE-RT-REJECT-INVALID-CANONICAL-COMMAND",
            Self::InvalidCommand => "IBAE-RT-REJECT-INVALID-COMMAND",
            Self::UnsupportedCommand => "IBAE-RT-REJECT-UNSUPPORTED-COMMAND",
            Self::ProtocolVersionMismatch => "IBAE-RT-REJECT-PROTOCOL-VERSION",
            Self::RequestBudgetExhausted => "IBAE-RT-REJECT-REQUEST-BUDGET",
            Self::ExecutionBudgetExhausted => "IBAE-RT-REJECT-EXECUTION-BUDGET",
            Self::RetryBudgetExhausted => "IBAE-RT-REJECT-RETRY-BUDGET",
            Self::ArithmeticOverflow => "IBAE-RT-REJECT-ARITHMETIC-OVERFLOW",
            Self::InvalidObservation => "IBAE-RT-REJECT-INVALID-OBSERVATION",
            Self::OperationFailed => "IBAE-RT-REJECT-OPERATION-FAILED",
        }
    }

    fn invariant_ids(self) -> &'static [&'static str] {
        match self {
            Self::InvalidCanonicalCommand | Self::InvalidCommand => &["IBAE-RT-002", "IBAE-RT-005"],
            Self::UnsupportedCommand | Self::ProtocolVersionMismatch => &["IBAE-RT-002"],
            Self::RequestBudgetExhausted => &["IBAE-BND-001", "IBAE-CLK-004"],
            Self::ExecutionBudgetExhausted => &["IBAE-BND-002", "IBAE-DET-003"],
            Self::RetryBudgetExhausted => &["IBAE-BND-003"],
            Self::ArithmeticOverflow => &["IBAE-BND-007", "IBAE-CLK-001"],
            Self::InvalidObservation => &["IBAE-REUSE-004", "IBAE-RT-005"],
            Self::OperationFailed => &["IBAE-DET-003", "IBAE-RT-001"],
        }
    }
}

#[derive(Debug)]
struct CanonicalError;

#[derive(Default)]
struct CanonicalStats {
    nodes: usize,
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        write!(&mut output, "{byte:02x}").expect("writing to String cannot fail");
    }
    output
}

fn domain_fingerprint(domain: &str, canonical_payload: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(domain.as_bytes());
    hasher.update([0]);
    hasher.update(canonical_payload.as_bytes());
    let digest = hasher.finalize();
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        write!(&mut output, "{byte:02x}").expect("writing to String cannot fail");
    }
    output
}

fn is_fingerprint(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn python_float_repr(value: f64) -> Result<String, CanonicalError> {
    if !value.is_finite() {
        return Err(CanonicalError);
    }
    if value == 0.0 {
        return Ok(if value.is_sign_negative() {
            "-0.0".to_owned()
        } else {
            "0.0".to_owned()
        });
    }

    let negative = value.is_sign_negative();
    let absolute = value.abs();
    let mut buffer = ryu::Buffer::new();
    let rendered = buffer.format_finite(absolute);
    let exponent_index = rendered.find('e').or_else(|| rendered.find('E'));
    let (mantissa, explicit_exponent) = match exponent_index {
        Some(index) => (
            &rendered[..index],
            rendered[index + 1..]
                .parse::<i32>()
                .map_err(|_| CanonicalError)?,
        ),
        None => (rendered, 0),
    };
    let (integer, fraction) = match mantissa.split_once('.') {
        Some(parts) => parts,
        None => (mantissa, ""),
    };
    let joined = format!("{integer}{fraction}");
    let first = joined
        .bytes()
        .position(|byte| byte != b'0')
        .ok_or(CanonicalError)?;
    let last = joined
        .bytes()
        .rposition(|byte| byte != b'0')
        .ok_or(CanonicalError)?;
    let digits = &joined[first..=last];
    let exponent = i32::try_from(integer.len()).map_err(|_| CanonicalError)?
        - i32::try_from(first).map_err(|_| CanonicalError)?
        - 1
        + explicit_exponent;

    let mut output = String::new();
    if negative {
        output.push('-');
    }
    if !(-4..16).contains(&exponent) {
        output.push_str(&digits[..1]);
        if digits.len() > 1 {
            output.push('.');
            output.push_str(&digits[1..]);
        }
        output.push('e');
        if exponent >= 0 {
            output.push('+');
        } else {
            output.push('-');
        }
        let magnitude = exponent.unsigned_abs();
        if magnitude < 10 {
            output.push('0');
        }
        output.push_str(&magnitude.to_string());
        return Ok(output);
    }

    let decimal_position = exponent + 1;
    if decimal_position <= 0 {
        output.push_str("0.");
        output.push_str(&"0".repeat(decimal_position.unsigned_abs() as usize));
        output.push_str(digits);
    } else {
        let position = usize::try_from(decimal_position).map_err(|_| CanonicalError)?;
        if position >= digits.len() {
            output.push_str(digits);
            output.push_str(&"0".repeat(position - digits.len()));
            output.push_str(".0");
        } else {
            output.push_str(&digits[..position]);
            output.push('.');
            output.push_str(&digits[position..]);
        }
    }
    Ok(output)
}

fn canonical_number(raw: &str) -> Result<String, CanonicalError> {
    if raw.contains('.') || raw.contains('e') || raw.contains('E') {
        let value = raw.parse::<f64>().map_err(|_| CanonicalError)?;
        return python_float_repr(value);
    }

    let negative = raw.starts_with('-');
    let magnitude = if negative { &raw[1..] } else { raw };
    if magnitude.is_empty() || !magnitude.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(CanonicalError);
    }
    if magnitude.len() > MAX_INTEGER_DECIMAL.len()
        || (magnitude.len() == MAX_INTEGER_DECIMAL.len() && magnitude > MAX_INTEGER_DECIMAL)
    {
        return Err(CanonicalError);
    }
    if magnitude == "0" {
        return Ok("0".to_owned());
    }
    Ok(raw.to_owned())
}

fn render_canonical(
    value: &Value,
    depth: usize,
    stats: &mut CanonicalStats,
    max_depth: usize,
    max_nodes: usize,
    max_collection_items: usize,
) -> Result<String, CanonicalError> {
    if depth > max_depth {
        return Err(CanonicalError);
    }
    stats.nodes = stats.nodes.checked_add(1).ok_or(CanonicalError)?;
    if stats.nodes > max_nodes {
        return Err(CanonicalError);
    }

    match value {
        Value::Null => Ok("null".to_owned()),
        Value::Bool(flag) => Ok(flag.to_string()),
        Value::Number(number) => canonical_number(&number.to_string()),
        Value::String(text) => {
            if text.len() > MAX_CANONICAL_STRING_BYTES {
                return Err(CanonicalError);
            }
            serde_json::to_string(text).map_err(|_| CanonicalError)
        }
        Value::Array(items) => {
            if items.len() > max_collection_items {
                return Err(CanonicalError);
            }
            let mut output = String::from("[");
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                output.push_str(&render_canonical(
                    item,
                    depth + 1,
                    stats,
                    max_depth,
                    max_nodes,
                    max_collection_items,
                )?);
            }
            output.push(']');
            Ok(output)
        }
        Value::Object(mapping) => {
            if mapping.len() > max_collection_items {
                return Err(CanonicalError);
            }
            let mut entries: Vec<_> = mapping.iter().collect();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            let mut output = String::from("{");
            for (index, (key, nested)) in entries.into_iter().enumerate() {
                if key.len() > MAX_CANONICAL_STRING_BYTES {
                    return Err(CanonicalError);
                }
                if index > 0 {
                    output.push(',');
                }
                output.push_str(&serde_json::to_string(key).map_err(|_| CanonicalError)?);
                output.push(':');
                output.push_str(&render_canonical(
                    nested,
                    depth + 1,
                    stats,
                    max_depth,
                    max_nodes,
                    max_collection_items,
                )?);
            }
            output.push('}');
            Ok(output)
        }
    }
}

fn canonical_value_with_limits(
    value: &Value,
    max_bytes: usize,
    max_depth: usize,
    max_nodes: usize,
    max_collection_items: usize,
) -> Result<String, CanonicalError> {
    let mut stats = CanonicalStats::default();
    let output = render_canonical(
        value,
        0,
        &mut stats,
        max_depth,
        max_nodes,
        max_collection_items,
    )?;
    if output.len() > max_bytes {
        return Err(CanonicalError);
    }
    Ok(output)
}

fn canonical_value(value: &Value) -> Result<String, CanonicalError> {
    canonical_value_with_limits(
        value,
        MAX_CANONICAL_VALUE_BYTES,
        MAX_CANONICAL_VALUE_DEPTH,
        MAX_CANONICAL_VALUE_NODES,
        MAX_CANONICAL_COLLECTION_ITEMS,
    )
}

fn canonical_runtime_value(value: &Value) -> Result<String, CanonicalError> {
    canonical_value_with_limits(
        value,
        MAX_RUNTIME_RECORD_BYTES,
        MAX_RUNTIME_RECORD_DEPTH,
        MAX_RUNTIME_RECORD_NODES,
        MAX_RUNTIME_COLLECTION_ITEMS,
    )
}

fn parse_canonical(input: &str) -> Result<Value, CanonicalError> {
    if input.len() > MAX_CANONICAL_VALUE_BYTES {
        return Err(CanonicalError);
    }
    let value: Value = serde_json::from_str(input).map_err(|_| CanonicalError)?;
    if canonical_value(&value)? != input {
        return Err(CanonicalError);
    }
    Ok(value)
}

fn parse_runtime_canonical(input: &str) -> Result<Value, CanonicalError> {
    if input.len() > MAX_RUNTIME_RECORD_BYTES {
        return Err(CanonicalError);
    }
    let value: Value = serde_json::from_str(input).map_err(|_| CanonicalError)?;
    if canonical_runtime_value(&value)? != input {
        return Err(CanonicalError);
    }
    Ok(value)
}

fn canonical_json_string(value: &str) -> String {
    serde_json::to_string(value).expect("Rust strings are valid JSON strings")
}

fn object_has_exact_keys(mapping: &Map<String, Value>, expected: &[&str]) -> bool {
    mapping.len() == expected.len()
        && expected
            .iter()
            .all(|expected_key| mapping.contains_key(*expected_key))
}

#[derive(Clone, Copy)]
struct Limits {
    requests: u64,
    executions: u64,
    retries: u64,
    history: u64,
}

impl Limits {
    fn validate(self) -> Result<Self, &'static str> {
        for (name, value, hard_limit) in [
            ("max_requests", self.requests, MAX_REQUESTS),
            ("max_executions", self.executions, MAX_EXECUTIONS),
            ("max_retries", self.retries, MAX_RETRIES),
            ("max_history", self.history, MAX_HISTORY),
        ] {
            if value == 0 {
                return Err(match name {
                    "max_requests" => "max_requests must be positive",
                    "max_executions" => "max_executions must be positive",
                    "max_retries" => "max_retries must be positive",
                    _ => "max_history must be positive",
                });
            }
            if value > hard_limit {
                return Err(match name {
                    "max_requests" => "max_requests exceeds the runtime hard limit",
                    "max_executions" => "max_executions exceeds the runtime hard limit",
                    "max_retries" => "max_retries exceeds the runtime hard limit",
                    _ => "max_history exceeds the runtime hard limit",
                });
            }
        }
        Ok(self)
    }

    fn value(self) -> Value {
        json!({
            "max_executions": self.executions,
            "max_history": self.history,
            "max_requests": self.requests,
            "max_retries": self.retries,
        })
    }
}

#[derive(Clone)]
struct CachedObservation {
    canonical: Arc<str>,
    observation_id: String,
}

#[derive(Clone, Copy)]
struct Counters {
    requests: u64,
    executions: u64,
    cache_hits: u64,
    retries: u64,
    logical_tick: u64,
}

impl Counters {
    fn zero() -> Self {
        Self {
            requests: 0,
            executions: 0,
            cache_hits: 0,
            retries: 0,
            logical_tick: 0,
        }
    }

    fn value(self) -> Value {
        json!({
            "cache_hits": self.cache_hits,
            "executions": self.executions,
            "requests": self.requests,
            "retries": self.retries,
        })
    }
}

struct ExecuteRead {
    admission_id: String,
    arguments_canonical: String,
    dependency_fingerprint: String,
    tool_name: String,
}

struct RecordRetry {
    admission_id: String,
}

enum Command {
    ExecuteRead(ExecuteRead),
    RecordRetry(RecordRetry),
}

fn parse_command_value(value: &Value) -> Result<Command, Reason> {
    let mapping = value.as_object().ok_or(Reason::InvalidCommand)?;
    let version = mapping
        .get("protocol_version")
        .and_then(Value::as_str)
        .ok_or(Reason::InvalidCommand)?;
    if version != PROTOCOL_VERSION {
        return Err(Reason::ProtocolVersionMismatch);
    }
    let command_type = mapping
        .get("command_type")
        .and_then(Value::as_str)
        .ok_or(Reason::InvalidCommand)?;

    match command_type {
        "execute_read" => {
            if !object_has_exact_keys(
                mapping,
                &[
                    "admission_id",
                    "arguments",
                    "command_type",
                    "dependency_fingerprint",
                    "protocol_version",
                    "tool_name",
                ],
            ) {
                return Err(Reason::InvalidCommand);
            }
            let admission_id = mapping
                .get("admission_id")
                .and_then(Value::as_str)
                .filter(|item| is_fingerprint(item))
                .ok_or(Reason::InvalidCommand)?
                .to_owned();
            let arguments = mapping
                .get("arguments")
                .cloned()
                .ok_or(Reason::InvalidCommand)?;
            let arguments_canonical =
                canonical_value(&arguments).map_err(|_| Reason::InvalidCommand)?;
            let dependency_fingerprint = mapping
                .get("dependency_fingerprint")
                .and_then(Value::as_str)
                .filter(|item| !item.is_empty() && item.len() <= MAX_RECORD_TEXT_BYTES)
                .ok_or(Reason::InvalidCommand)?
                .to_owned();
            let tool_name = mapping
                .get("tool_name")
                .and_then(Value::as_str)
                .filter(|item| !item.is_empty() && item.len() <= MAX_RECORD_TEXT_BYTES)
                .ok_or(Reason::InvalidCommand)?
                .to_owned();
            Ok(Command::ExecuteRead(ExecuteRead {
                admission_id,
                arguments_canonical,
                dependency_fingerprint,
                tool_name,
            }))
        }
        "record_retry" => {
            if !object_has_exact_keys(
                mapping,
                &["admission_id", "command_type", "protocol_version"],
            ) {
                return Err(Reason::InvalidCommand);
            }
            let admission_id = mapping
                .get("admission_id")
                .and_then(Value::as_str)
                .filter(|item| is_fingerprint(item))
                .ok_or(Reason::InvalidCommand)?
                .to_owned();
            Ok(Command::RecordRetry(RecordRetry { admission_id }))
        }
        _ => Err(Reason::UnsupportedCommand),
    }
}

fn parse_command(command_json: &str) -> Result<(Command, Value), (Reason, Option<Value>)> {
    let value = parse_runtime_canonical(command_json)
        .map_err(|_| (Reason::InvalidCanonicalCommand, None))?;
    match parse_command_value(&value) {
        Ok(command) => Ok((command, value)),
        Err(reason) => Err((reason, Some(value))),
    }
}

enum Invocation {
    Observation(String),
    InvalidObservation,
    OperationFailed,
}

fn parse_invocation_envelope(envelope: &str) -> Invocation {
    let Ok(value) = parse_runtime_canonical(envelope) else {
        return Invocation::InvalidObservation;
    };
    let Some(mapping) = value.as_object() else {
        return Invocation::InvalidObservation;
    };
    match mapping.get("status").and_then(Value::as_str) {
        Some("ok") if object_has_exact_keys(mapping, &["observation", "status"]) => {
            let Some(observation) = mapping.get("observation") else {
                return Invocation::InvalidObservation;
            };
            match canonical_value(observation) {
                Ok(canonical) => Invocation::Observation(canonical),
                Err(_) => Invocation::InvalidObservation,
            }
        }
        Some("rejected") if object_has_exact_keys(mapping, &["reason_code", "status"]) => {
            match mapping.get("reason_code").and_then(Value::as_str) {
                Some("invalid_observation") => Invocation::InvalidObservation,
                Some("operation_failed") => Invocation::OperationFailed,
                _ => Invocation::InvalidObservation,
            }
        }
        _ => Invocation::InvalidObservation,
    }
}

#[derive(Clone)]
struct RuntimeCore {
    limits: Limits,
    session_id: String,
    counters: Counters,
    cache: BTreeMap<String, CachedObservation>,
    history: VecDeque<String>,
}

impl RuntimeCore {
    fn new(session_key: &str, limits: Limits) -> Result<Self, &'static str> {
        if session_key.is_empty() || session_key.len() > MAX_RECORD_TEXT_BYTES {
            return Err("session_key must be non-empty and bounded");
        }
        let session_record = json!({
            "limits": limits.value(),
            "protocol_version": PROTOCOL_VERSION,
            "session_key": session_key,
        });
        let canonical = canonical_value(&session_record)
            .expect("the internally constructed session record is canonicalizable");
        Ok(Self {
            limits,
            session_id: domain_fingerprint(SESSION_DOMAIN, &canonical),
            counters: Counters::zero(),
            cache: BTreeMap::new(),
            history: VecDeque::new(),
        })
    }

    fn state_record(&self) -> Value {
        let cache_entries: Vec<Value> = self
            .cache
            .iter()
            .map(|(tool_key, cached)| {
                json!({
                    "observation_id": cached.observation_id,
                    "tool_key": tool_key,
                })
            })
            .collect();
        json!({
            "cache": cache_entries,
            "counters": self.counters.value(),
            "history": self.history.iter().cloned().collect::<Vec<_>>(),
            "limits": self.limits.value(),
            "logical_tick": self.counters.logical_tick,
            "protocol_version": PROTOCOL_VERSION,
            "session_id": self.session_id,
        })
    }

    fn state_id(&self) -> Result<String, CanonicalError> {
        let canonical = canonical_runtime_value(&self.state_record())?;
        Ok(domain_fingerprint(STATE_DOMAIN, &canonical))
    }

    fn snapshot_value(&self) -> Result<Value, CanonicalError> {
        let mut value = self.state_record();
        value
            .as_object_mut()
            .expect("state record is an object")
            .insert("state_id".to_owned(), Value::String(self.state_id()?));
        Ok(value)
    }

    fn snapshot_json(&self) -> Result<String, CanonicalError> {
        canonical_runtime_value(&self.snapshot_value()?)
    }

    fn increment_request(&mut self) -> Result<(), Reason> {
        if self.counters.requests >= self.limits.requests {
            return Err(Reason::RequestBudgetExhausted);
        }
        let requests = self
            .counters
            .requests
            .checked_add(1)
            .ok_or(Reason::ArithmeticOverflow)?;
        let tick = self
            .counters
            .logical_tick
            .checked_add(1)
            .ok_or(Reason::ArithmeticOverflow)?;
        self.counters.requests = requests;
        self.counters.logical_tick = tick;
        Ok(())
    }

    fn increment_execution(&mut self) -> Result<(), Reason> {
        if self.counters.executions >= self.limits.executions {
            return Err(Reason::ExecutionBudgetExhausted);
        }
        let executions = self
            .counters
            .executions
            .checked_add(1)
            .ok_or(Reason::ArithmeticOverflow)?;
        let tick = self
            .counters
            .logical_tick
            .checked_add(1)
            .ok_or(Reason::ArithmeticOverflow)?;
        self.counters.executions = executions;
        self.counters.logical_tick = tick;
        Ok(())
    }

    fn commit_cache_hit(&mut self, transition_id: &str) -> Result<(), Reason> {
        let cache_hits = self
            .counters
            .cache_hits
            .checked_add(1)
            .ok_or(Reason::ArithmeticOverflow)?;
        let tick = self
            .counters
            .logical_tick
            .checked_add(1)
            .ok_or(Reason::ArithmeticOverflow)?;
        self.counters.cache_hits = cache_hits;
        self.counters.logical_tick = tick;
        self.append_history(transition_id);
        Ok(())
    }

    fn commit_observation(
        &mut self,
        tool_key: String,
        cached: CachedObservation,
        transition_id: &str,
    ) -> Result<(), Reason> {
        let tick = self
            .counters
            .logical_tick
            .checked_add(1)
            .ok_or(Reason::ArithmeticOverflow)?;
        if self.cache.len() >= usize::try_from(self.limits.executions).unwrap_or(usize::MAX) {
            return Err(Reason::ExecutionBudgetExhausted);
        }
        self.counters.logical_tick = tick;
        self.cache.insert(tool_key, cached);
        self.append_history(transition_id);
        Ok(())
    }

    fn increment_retry(&mut self) -> Result<(), Reason> {
        if self.counters.retries >= self.limits.retries {
            return Err(Reason::RetryBudgetExhausted);
        }
        let retries = self
            .counters
            .retries
            .checked_add(1)
            .ok_or(Reason::ArithmeticOverflow)?;
        let tick = self
            .counters
            .logical_tick
            .checked_add(1)
            .ok_or(Reason::ArithmeticOverflow)?;
        self.counters.retries = retries;
        self.counters.logical_tick = tick;
        Ok(())
    }

    fn append_history(&mut self, transition_id: &str) {
        let limit = usize::try_from(self.limits.history)
            .expect("validated max_history fits in usize on supported targets");
        if self.history.len() == limit {
            self.history.pop_front();
        }
        self.history.push_back(transition_id.to_owned());
    }

    fn terminal_cycle_period(&self) -> Option<u8> {
        for period in 1..=3_usize {
            let width = period * 2;
            if self.history.len() < width {
                continue;
            }
            let history: Vec<_> = self.history.iter().collect();
            let split = history.len() - width;
            if history[split..split + period] == history[split + period..] {
                return u8::try_from(period).ok();
            }
        }
        None
    }

    fn tool_key(command: &ExecuteRead) -> String {
        let record = format!(
            "{{\"arguments\":{},\"dependency_fingerprint\":{},\"tool_name\":{}}}",
            command.arguments_canonical,
            canonical_json_string(&command.dependency_fingerprint),
            canonical_json_string(&command.tool_name),
        );
        sha256_hex(record.as_bytes())
    }

    fn transition_id(tool_key: &str, observation_id: &str) -> String {
        let record = format!(
            "{{\"observation\":{},\"tool_key\":{}}}",
            canonical_json_string(observation_id),
            canonical_json_string(tool_key),
        );
        sha256_hex(record.as_bytes())
    }

    fn command_id(&self, command: &Value, prior_state_id: &str) -> Result<String, CanonicalError> {
        let record = json!({
            "command": command,
            "prior_state_id": prior_state_id,
            "session_id": self.session_id,
        });
        let canonical = canonical_runtime_value(&record)?;
        Ok(domain_fingerprint(COMMAND_DOMAIN, &canonical))
    }

    fn budget_delta(before: Counters, after: Counters) -> Value {
        json!({
            "cache_hits": after.cache_hits - before.cache_hits,
            "executions": after.executions - before.executions,
            "requests": after.requests - before.requests,
            "retries": after.retries - before.retries,
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn outcome(
        &self,
        before: Counters,
        prior_state_id: String,
        command_id: Option<String>,
        command_type: Option<&str>,
        admission_id: Option<&str>,
        tool_name: Option<&str>,
        arguments_id: Option<String>,
        dependency_fingerprint: Option<&str>,
        tool_key: Option<&str>,
        observation: Option<&str>,
        observation_id: Option<&str>,
        transition_id: Option<&str>,
        cache_status: Option<&str>,
        rejection: Option<Reason>,
    ) -> Result<String, CanonicalError> {
        let resulting_state_id = self.state_id()?;
        let rejection_value = rejection.map(|reason| {
            json!({
                "authority_layer": "execution",
                "blocking_runtime_state": {
                    "counters": self.counters.value(),
                    "limits": self.limits.value(),
                    "logical_tick": self.counters.logical_tick,
                    "state_id": resulting_state_id,
                },
                "invariant_ids": reason.invariant_ids(),
                "reason_code": reason.code(),
            })
        });
        let receipt_without_id = json!({
            "admission_id": admission_id,
            "arguments_id": arguments_id,
            "authority_layer": "execution",
            "budget_delta": Self::budget_delta(before, self.counters),
            "cache_status": cache_status,
            "command_id": command_id,
            "command_type": command_type,
            "dependency_fingerprint": dependency_fingerprint,
            "logical_tick": self.counters.logical_tick,
            "logical_tick_delta": self.counters.logical_tick - before.logical_tick,
            "observation_id": observation_id,
            "prior_state_id": prior_state_id,
            "protocol_version": PROTOCOL_VERSION,
            "rejection": rejection_value,
            "resulting_state_id": resulting_state_id,
            "session_id": self.session_id,
            "status": if rejection.is_none() { "accepted" } else { "rejected" },
            "tool_key": tool_key,
            "tool_name": tool_name,
            "transition_id": transition_id,
        });
        let receipt_canonical = canonical_runtime_value(&receipt_without_id)?;
        let receipt_id = domain_fingerprint(RECEIPT_DOMAIN, &receipt_canonical);
        let mut receipt = receipt_without_id;
        receipt
            .as_object_mut()
            .expect("receipt is an object")
            .insert("receipt_id".to_owned(), Value::String(receipt_id));

        let observation_value = observation
            .and_then(|canonical| parse_canonical(canonical).ok())
            .unwrap_or(Value::Null);
        canonical_runtime_value(&json!({
            "observation": observation_value,
            "receipt": receipt,
        }))
    }

    fn rejected_unparsed(
        &self,
        before: Counters,
        prior_state_id: String,
        reason: Reason,
    ) -> Result<String, CanonicalError> {
        self.outcome(
            before,
            prior_state_id,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            Some(reason),
        )
    }

    fn rejected_parsed(
        &self,
        before: Counters,
        prior_state_id: String,
        command_value: &Value,
        reason: Reason,
    ) -> Result<String, CanonicalError> {
        let command_id = self.command_id(command_value, &prior_state_id)?;
        let mapping = command_value.as_object();
        let command_type = mapping
            .and_then(|item| item.get("command_type"))
            .and_then(Value::as_str)
            .map(str::to_owned);
        let admission_id = mapping
            .and_then(|item| item.get("admission_id"))
            .and_then(Value::as_str)
            .filter(|item| is_fingerprint(item))
            .map(str::to_owned);
        self.outcome(
            before,
            prior_state_id,
            Some(command_id),
            command_type.as_deref(),
            admission_id.as_deref(),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            Some(reason),
        )
    }

    fn dispatch<F>(&mut self, command_json: &str, invoke: F) -> Result<String, CanonicalError>
    where
        F: FnOnce() -> Invocation,
    {
        let mut candidate = self.clone();
        let outcome = candidate.dispatch_in_place(command_json, invoke)?;
        *self = candidate;
        Ok(outcome)
    }

    fn dispatch_in_place<F>(
        &mut self,
        command_json: &str,
        invoke: F,
    ) -> Result<String, CanonicalError>
    where
        F: FnOnce() -> Invocation,
    {
        let before = self.counters;
        let prior_state_id = self.state_id()?;
        let (command, command_value) = match parse_command(command_json) {
            Ok(parsed) => parsed,
            Err((reason, None)) => return self.rejected_unparsed(before, prior_state_id, reason),
            Err((reason, Some(command_value))) => {
                return self.rejected_parsed(before, prior_state_id, &command_value, reason)
            }
        };
        let command_id = self.command_id(&command_value, &prior_state_id)?;

        match command {
            Command::RecordRetry(command) => {
                let rejection = self.increment_retry().err();
                self.outcome(
                    before,
                    prior_state_id,
                    Some(command_id),
                    Some("record_retry"),
                    Some(&command.admission_id),
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    rejection,
                )
            }
            Command::ExecuteRead(command) => {
                let tool_key = Self::tool_key(&command);
                let arguments_id = sha256_hex(command.arguments_canonical.as_bytes());
                if let Err(reason) = self.increment_request() {
                    return self.outcome(
                        before,
                        prior_state_id,
                        Some(command_id),
                        Some("execute_read"),
                        Some(&command.admission_id),
                        Some(&command.tool_name),
                        Some(arguments_id),
                        Some(&command.dependency_fingerprint),
                        Some(&tool_key),
                        None,
                        None,
                        None,
                        None,
                        Some(reason),
                    );
                }

                if let Some(cached) = self.cache.get(&tool_key).cloned() {
                    let transition_id = Self::transition_id(&tool_key, &cached.observation_id);
                    let rejection = self.commit_cache_hit(&transition_id).err();
                    return self.outcome(
                        before,
                        prior_state_id,
                        Some(command_id),
                        Some("execute_read"),
                        Some(&command.admission_id),
                        Some(&command.tool_name),
                        Some(arguments_id),
                        Some(&command.dependency_fingerprint),
                        Some(&tool_key),
                        if rejection.is_none() {
                            Some(cached.canonical.as_ref())
                        } else {
                            None
                        },
                        if rejection.is_none() {
                            Some(&cached.observation_id)
                        } else {
                            None
                        },
                        if rejection.is_none() {
                            Some(&transition_id)
                        } else {
                            None
                        },
                        if rejection.is_none() {
                            Some("cache_hit")
                        } else {
                            None
                        },
                        rejection,
                    );
                }

                if let Err(reason) = self.increment_execution() {
                    return self.outcome(
                        before,
                        prior_state_id,
                        Some(command_id),
                        Some("execute_read"),
                        Some(&command.admission_id),
                        Some(&command.tool_name),
                        Some(arguments_id),
                        Some(&command.dependency_fingerprint),
                        Some(&tool_key),
                        None,
                        None,
                        None,
                        None,
                        Some(reason),
                    );
                }

                let observation = match invoke() {
                    Invocation::Observation(canonical) => canonical,
                    Invocation::InvalidObservation => {
                        return self.outcome(
                            before,
                            prior_state_id,
                            Some(command_id),
                            Some("execute_read"),
                            Some(&command.admission_id),
                            Some(&command.tool_name),
                            Some(arguments_id),
                            Some(&command.dependency_fingerprint),
                            Some(&tool_key),
                            None,
                            None,
                            None,
                            None,
                            Some(Reason::InvalidObservation),
                        );
                    }
                    Invocation::OperationFailed => {
                        return self.outcome(
                            before,
                            prior_state_id,
                            Some(command_id),
                            Some("execute_read"),
                            Some(&command.admission_id),
                            Some(&command.tool_name),
                            Some(arguments_id),
                            Some(&command.dependency_fingerprint),
                            Some(&tool_key),
                            None,
                            None,
                            None,
                            None,
                            Some(Reason::OperationFailed),
                        );
                    }
                };
                let observation_id = sha256_hex(observation.as_bytes());
                let transition_id = Self::transition_id(&tool_key, &observation_id);
                let cached = CachedObservation {
                    canonical: Arc::from(observation.as_str()),
                    observation_id: observation_id.clone(),
                };
                let rejection = self
                    .commit_observation(tool_key.clone(), cached, &transition_id)
                    .err();
                self.outcome(
                    before,
                    prior_state_id,
                    Some(command_id),
                    Some("execute_read"),
                    Some(&command.admission_id),
                    Some(&command.tool_name),
                    Some(arguments_id),
                    Some(&command.dependency_fingerprint),
                    Some(&tool_key),
                    if rejection.is_none() {
                        Some(&observation)
                    } else {
                        None
                    },
                    if rejection.is_none() {
                        Some(&observation_id)
                    } else {
                        None
                    },
                    if rejection.is_none() {
                        Some(&transition_id)
                    } else {
                        None
                    },
                    if rejection.is_none() {
                        Some("cold_execution")
                    } else {
                        None
                    },
                    rejection,
                )
            }
        }
    }
}

fn exact_u64(value: Option<&Bound<'_, PyAny>>, default: u64, name: &str) -> PyResult<u64> {
    let Some(value) = value else {
        return Ok(default);
    };
    if value.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(format!(
            "{name} must be an exact positive integer"
        )));
    }
    value
        .extract::<u64>()
        .map_err(|_| PyValueError::new_err(format!("{name} must be an exact positive integer")))
}

#[derive(Clone, Copy, Default)]
struct EvidenceCounters {
    requests: u64,
    actual_executions: u64,
    cache_hits: u64,
    retries: u64,
    mutations: u64,
    invariant_violations: u64,
    canonical_mismatches: u64,
    receipt_mismatches: u64,
}

impl EvidenceCounters {
    fn checked_add(self, other: Self) -> Result<Self, &'static str> {
        Ok(Self {
            requests: self
                .requests
                .checked_add(other.requests)
                .ok_or("evidence request counter overflow")?,
            actual_executions: self
                .actual_executions
                .checked_add(other.actual_executions)
                .ok_or("evidence execution counter overflow")?,
            cache_hits: self
                .cache_hits
                .checked_add(other.cache_hits)
                .ok_or("evidence cache-hit counter overflow")?,
            retries: self
                .retries
                .checked_add(other.retries)
                .ok_or("evidence retry counter overflow")?,
            mutations: self
                .mutations
                .checked_add(other.mutations)
                .ok_or("evidence mutation counter overflow")?,
            invariant_violations: self
                .invariant_violations
                .checked_add(other.invariant_violations)
                .ok_or("evidence invariant-violation counter overflow")?,
            canonical_mismatches: self
                .canonical_mismatches
                .checked_add(other.canonical_mismatches)
                .ok_or("evidence canonical-mismatch counter overflow")?,
            receipt_mismatches: self
                .receipt_mismatches
                .checked_add(other.receipt_mismatches)
                .ok_or("evidence receipt-mismatch counter overflow")?,
        })
    }

    fn value(self) -> Value {
        json!({
            "actual_executions": self.actual_executions,
            "cache_hits": self.cache_hits,
            "canonical_mismatches": self.canonical_mismatches,
            "invariant_violations": self.invariant_violations,
            "mutations": self.mutations,
            "receipt_mismatches": self.receipt_mismatches,
            "requests": self.requests,
            "retries": self.retries,
        })
    }
}

#[derive(Clone, Copy, Default)]
struct EvidenceCaseCounts {
    total: u64,
    passed: u64,
    failed: u64,
    rejected: u64,
}

impl EvidenceCaseCounts {
    fn checked_add(self, other: Self) -> Result<Self, &'static str> {
        let next = Self {
            total: self
                .total
                .checked_add(other.total)
                .ok_or("evidence case counter overflow")?,
            passed: self
                .passed
                .checked_add(other.passed)
                .ok_or("evidence pass counter overflow")?,
            failed: self
                .failed
                .checked_add(other.failed)
                .ok_or("evidence failure counter overflow")?,
            rejected: self
                .rejected
                .checked_add(other.rejected)
                .ok_or("evidence rejection counter overflow")?,
        };
        let classified = next
            .passed
            .checked_add(next.failed)
            .and_then(|value| value.checked_add(next.rejected))
            .ok_or("evidence case counter overflow")?;
        if next.total != classified {
            return Err("evidence case counts are inconsistent");
        }
        Ok(next)
    }

    fn failure_count(self) -> Result<u64, &'static str> {
        self.failed
            .checked_add(self.rejected)
            .ok_or("evidence failure counter overflow")
    }

    fn value(self) -> Value {
        json!({
            "failed": self.failed,
            "passed": self.passed,
            "rejected": self.rejected,
            "total": self.total,
        })
    }
}

#[derive(Clone)]
struct EvidenceFailureDetail {
    case_id: String,
    case_index: u64,
    detail: Value,
    reason_code: String,
    receipt_id: String,
    status: String,
}

impl EvidenceFailureDetail {
    fn value(&self) -> Value {
        json!({
            "case_id": self.case_id,
            "case_index": self.case_index,
            "detail": self.detail,
            "reason_code": self.reason_code,
            "receipt_id": self.receipt_id,
            "status": self.status,
        })
    }
}

struct EvidenceCase {
    admission_id: String,
    case_id: String,
    counters: EvidenceCounters,
    failure: Option<(String, Value)>,
    input_id: String,
    receipt_id: String,
    result_id: String,
    runtime_source: Option<RuntimeEvidenceSource>,
    status: String,
}

struct RuntimeEvidenceSource {
    prior_state_id: String,
    resulting_state_id: String,
    runtime_receipt_id: String,
    session_id: String,
}

#[derive(Clone)]
struct EvidenceRuntimeBoundary {
    final_state_id: String,
    first_runtime_receipt_id: String,
    initial_state_id: String,
    last_runtime_receipt_id: String,
    session_id: String,
}

impl EvidenceRuntimeBoundary {
    fn value(&self) -> Value {
        json!({
            "final_state_id": self.final_state_id,
            "first_runtime_receipt_id": self.first_runtime_receipt_id,
            "initial_state_id": self.initial_state_id,
            "last_runtime_receipt_id": self.last_runtime_receipt_id,
            "session_id": self.session_id,
        })
    }
}

/// Non-constructible proof that one exact runtime receipt came from a live
/// native dispatch in this process. It is not producer authentication.
#[pyclass(
    name = "NativeRuntimeReceiptSeal",
    module = "ibae._runtime",
    unsendable
)]
struct NativeRuntimeReceiptSeal {
    admission_id: String,
    // v0.3 record_retry receipts intentionally omit tool/argument/dependency
    // fields. Their known admission membership is checked below, but only an
    // execute_read transition can satisfy authorization-manifest coverage.
    arguments_id: Option<String>,
    canonical_receipt: Arc<str>,
    cache_status: Option<String>,
    command_type: String,
    command_id: String,
    counters: EvidenceCounters,
    dependency_fingerprint: Option<String>,
    prior_state_id: String,
    receipt_id: String,
    rejection: Option<Value>,
    result_id: String,
    resulting_state_id: String,
    session_id: String,
    status: String,
    tool_name: Option<String>,
}

impl NativeRuntimeReceiptSeal {
    fn from_outcome(outcome: &str) -> Result<Self, CanonicalError> {
        let value = parse_runtime_canonical(outcome)?;
        let receipt = value
            .get("receipt")
            .and_then(Value::as_object)
            .ok_or(CanonicalError)?;
        let canonical_receipt = canonical_value(&Value::Object(receipt.clone()))?;
        let identity = |name: &str| -> Result<String, CanonicalError> {
            receipt
                .get(name)
                .and_then(Value::as_str)
                .filter(|value| is_fingerprint(value))
                .map(str::to_owned)
                .ok_or(CanonicalError)
        };
        let budget = receipt
            .get("budget_delta")
            .and_then(Value::as_object)
            .ok_or(CanonicalError)?;
        let budget_value = |name: &str| -> Result<u64, CanonicalError> {
            budget
                .get(name)
                .and_then(Value::as_u64)
                .ok_or(CanonicalError)
        };
        let status = receipt
            .get("status")
            .and_then(Value::as_str)
            .filter(|status| matches!(*status, "accepted" | "rejected"))
            .ok_or(CanonicalError)?
            .to_owned();
        let result_id = receipt
            .get("transition_id")
            .and_then(Value::as_str)
            .filter(|value| is_fingerprint(value))
            .map(str::to_owned)
            .unwrap_or(identity("resulting_state_id")?);
        let rejection = match receipt.get("rejection") {
            Some(Value::Null) if status == "accepted" => None,
            Some(Value::Object(value)) if status == "rejected" => {
                Some(Value::Object(value.clone()))
            }
            _ => return Err(CanonicalError),
        };
        let command_type = receipt
            .get("command_type")
            .and_then(Value::as_str)
            .filter(|value| matches!(*value, "execute_read" | "record_retry"))
            .map(str::to_owned)
            .ok_or(CanonicalError)?;
        let optional_identity = |name: &str| -> Result<Option<String>, CanonicalError> {
            match receipt.get(name) {
                Some(Value::Null) => Ok(None),
                Some(Value::String(value)) if is_fingerprint(value) => Ok(Some(value.to_owned())),
                _ => Err(CanonicalError),
            }
        };
        let optional_text = |name: &str| -> Result<Option<String>, CanonicalError> {
            match receipt.get(name) {
                Some(Value::Null) => Ok(None),
                Some(Value::String(value))
                    if !value.is_empty() && value.len() <= MAX_RECORD_TEXT_BYTES =>
                {
                    Ok(Some(value.to_owned()))
                }
                _ => Err(CanonicalError),
            }
        };
        let arguments_id = optional_identity("arguments_id")?;
        let dependency_fingerprint = optional_text("dependency_fingerprint")?;
        let tool_name = optional_text("tool_name")?;
        let cache_status = match receipt.get("cache_status") {
            Some(Value::Null) => None,
            Some(Value::String(value))
                if matches!(value.as_str(), "cache_hit" | "cold_execution") =>
            {
                Some(value.to_owned())
            }
            _ => return Err(CanonicalError),
        };
        if command_type == "execute_read"
            && (arguments_id.is_none() || dependency_fingerprint.is_none() || tool_name.is_none())
        {
            return Err(CanonicalError);
        }
        if command_type == "record_retry"
            && (arguments_id.is_some() || dependency_fingerprint.is_some() || tool_name.is_some())
        {
            return Err(CanonicalError);
        }
        Ok(Self {
            admission_id: identity("admission_id")?,
            arguments_id,
            canonical_receipt: Arc::from(canonical_receipt.as_str()),
            cache_status,
            command_type,
            command_id: identity("command_id")?,
            counters: EvidenceCounters {
                requests: budget_value("requests")?,
                actual_executions: budget_value("executions")?,
                cache_hits: budget_value("cache_hits")?,
                retries: budget_value("retries")?,
                mutations: 0,
                invariant_violations: 0,
                canonical_mismatches: 0,
                receipt_mismatches: 0,
            },
            dependency_fingerprint,
            prior_state_id: identity("prior_state_id")?,
            receipt_id: identity("receipt_id")?,
            rejection,
            result_id,
            resulting_state_id: identity("resulting_state_id")?,
            session_id: identity("session_id")?,
            status,
            tool_name,
        })
    }

    fn validates_case(&self, item: &EvidenceCase) -> bool {
        let Some(source) = &item.runtime_source else {
            return false;
        };
        if item.admission_id != self.admission_id
            || item.case_id != self.command_id
            || item.input_id != self.command_id
            || item.result_id != self.result_id
            || item.receipt_id != self.receipt_id
            || source.prior_state_id != self.prior_state_id
            || source.resulting_state_id != self.resulting_state_id
            || source.runtime_receipt_id != self.receipt_id
            || source.session_id != self.session_id
            || item.counters.requests != self.counters.requests
            || item.counters.actual_executions != self.counters.actual_executions
            || item.counters.cache_hits != self.counters.cache_hits
            || item.counters.retries != self.counters.retries
            || item.counters.mutations != 0
            || item.counters.invariant_violations != 0
            || item.counters.canonical_mismatches != 0
            || item.counters.receipt_mismatches != 0
        {
            return false;
        }
        match (
            &self.rejection,
            &item.failure,
            self.status.as_str(),
            item.status.as_str(),
        ) {
            (None, None, "accepted", "passed") => true,
            (Some(expected), Some((reason, detail)), "rejected", "rejected") => {
                expected.get("reason_code").and_then(Value::as_str) == Some(reason.as_str())
                    && detail.get("runtime_rejection") == Some(expected)
            }
            _ => false,
        }
    }
}

#[pymethods]
impl NativeRuntimeReceiptSeal {
    fn validates(&self, canonical_receipt: &str) -> bool {
        self.canonical_receipt.as_ref() == canonical_receipt
    }
}

fn parse_runtime_boundary(value: &Value) -> Result<Option<EvidenceRuntimeBoundary>, &'static str> {
    let Value::Object(mapping) = value else {
        return if value.is_null() {
            Ok(None)
        } else {
            Err("evidence runtime boundary must be an object or null")
        };
    };
    if !object_has_exact_keys(
        mapping,
        &[
            "final_state_id",
            "first_runtime_receipt_id",
            "initial_state_id",
            "last_runtime_receipt_id",
            "session_id",
        ],
    ) {
        return Err("evidence runtime boundary does not match the v1 schema");
    }
    let identity = |name: &str| -> Result<String, &'static str> {
        mapping
            .get(name)
            .and_then(Value::as_str)
            .filter(|value| is_fingerprint(value))
            .map(str::to_owned)
            .ok_or("evidence runtime boundary identity is invalid")
    };
    Ok(Some(EvidenceRuntimeBoundary {
        final_state_id: identity("final_state_id")?,
        first_runtime_receipt_id: identity("first_runtime_receipt_id")?,
        initial_state_id: identity("initial_state_id")?,
        last_runtime_receipt_id: identity("last_runtime_receipt_id")?,
        session_id: identity("session_id")?,
    }))
}

struct ChildEvidence {
    aggregate_admission_identity: String,
    aggregate_input_identity: String,
    aggregate_receipt_identity: String,
    aggregate_result_identity: String,
    case_counts: EvidenceCaseCounts,
    counters: EvidenceCounters,
    authorization_manifest_count: u64,
    authorization_manifest_identity: String,
    governance_identity: String,
    orchestration_identity: String,
    receipt_id: String,
    status: String,
    task_identity: String,
}

enum EvidenceItem {
    Case(EvidenceCase),
    Child(Box<ChildEvidence>),
}

#[derive(Clone)]
struct EvidenceAuthorization {
    action_id: String,
    arguments_id: String,
    authority_class: String,
    cache_reuse_permitted: bool,
    dependency_fingerprint: String,
    tool_name: String,
}

impl EvidenceAuthorization {
    fn matches_runtime(&self, seal: &NativeRuntimeReceiptSeal) -> bool {
        if self.action_id != seal.admission_id
            || !matches!(self.authority_class.as_str(), "PURE_READ" | "SNAPSHOT_READ")
        {
            return false;
        }
        match seal.command_type.as_str() {
            "execute_read" => {
                seal.arguments_id.as_deref() == Some(self.arguments_id.as_str())
                    && seal.dependency_fingerprint.as_deref()
                        == Some(self.dependency_fingerprint.as_str())
                    && seal.tool_name.as_deref() == Some(self.tool_name.as_str())
                    && (self.cache_reuse_permitted
                        || seal.cache_status.as_deref() != Some("cache_hit"))
            }
            "record_retry" => true,
            _ => false,
        }
    }
}

fn parse_authorization_manifest(
    canonical_manifest: &str,
) -> Result<(BTreeMap<String, EvidenceAuthorization>, String), &'static str> {
    let value = parse_canonical(canonical_manifest)
        .map_err(|_| "evidence authorization manifest is not canonical JSON")?;
    let entries = value
        .as_array()
        .ok_or("evidence authorization manifest must be an array")?;
    if entries.len() > MAX_EVIDENCE_AUTHORIZATIONS {
        return Err("evidence authorization manifest exceeds its hard bound");
    }
    let mut manifest = BTreeMap::new();
    let mut previous: Option<String> = None;
    for value in entries {
        let entry = value
            .as_object()
            .filter(|entry| {
                object_has_exact_keys(
                    entry,
                    &[
                        "action_id",
                        "arguments_id",
                        "authority_class",
                        "cache_reuse_permitted",
                        "dependency_fingerprint",
                        "tool_admission_receipt_id",
                        "tool_name",
                    ],
                )
            })
            .ok_or("evidence authorization entry does not match the v1 schema")?;
        let fingerprint = |name: &str| -> Result<String, &'static str> {
            entry
                .get(name)
                .and_then(Value::as_str)
                .filter(|identity| is_fingerprint(identity))
                .map(str::to_owned)
                .ok_or("evidence authorization identity is invalid")
        };
        let action_id = fingerprint("action_id")?;
        if previous
            .as_ref()
            .is_some_and(|prior| prior.as_str() >= action_id.as_str())
        {
            return Err("evidence authorization entries must be sorted and unique");
        }
        previous = Some(action_id.clone());
        let authority_class = entry
            .get("authority_class")
            .and_then(Value::as_str)
            .filter(|value| matches!(*value, "PURE_READ" | "SNAPSHOT_READ"))
            .ok_or("evidence authorization class is not runtime-finalizable")?
            .to_owned();
        let dependency_fingerprint = fingerprint("dependency_fingerprint")?;
        let cache_reuse_permitted = entry
            .get("cache_reuse_permitted")
            .and_then(Value::as_bool)
            .ok_or("evidence authorization cache reuse flag is invalid")?;
        let tool_name = entry
            .get("tool_name")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty() && value.len() <= MAX_RECORD_TEXT_BYTES)
            .ok_or("evidence authorization tool name is invalid")?
            .to_owned();
        let _tool_admission_receipt_id = fingerprint("tool_admission_receipt_id")?;
        let authorization = EvidenceAuthorization {
            action_id: action_id.clone(),
            arguments_id: fingerprint("arguments_id")?,
            authority_class,
            cache_reuse_permitted,
            dependency_fingerprint,
            tool_name,
        };
        manifest.insert(action_id, authorization);
    }
    let record = json!({"entries": entries});
    let canonical = canonical_value(&record)
        .map_err(|_| "evidence authorization manifest is not canonicalizable")?;
    Ok((
        manifest,
        domain_fingerprint(EVIDENCE_AUTHORIZATION_DOMAIN, &canonical),
    ))
}

fn exact_json_u64(mapping: &Map<String, Value>, name: &str) -> Result<u64, &'static str> {
    mapping
        .get(name)
        .and_then(Value::as_u64)
        .ok_or("evidence counters must be exact unsigned 64-bit integers")
}

fn parse_evidence_counters(value: &Value) -> Result<EvidenceCounters, &'static str> {
    let mapping = value
        .as_object()
        .ok_or("evidence counters must be an object")?;
    if !object_has_exact_keys(
        mapping,
        &[
            "actual_executions",
            "cache_hits",
            "canonical_mismatches",
            "invariant_violations",
            "mutations",
            "receipt_mismatches",
            "requests",
            "retries",
        ],
    ) {
        return Err("evidence counters do not match the v1 schema");
    }
    Ok(EvidenceCounters {
        actual_executions: exact_json_u64(mapping, "actual_executions")?,
        cache_hits: exact_json_u64(mapping, "cache_hits")?,
        canonical_mismatches: exact_json_u64(mapping, "canonical_mismatches")?,
        invariant_violations: exact_json_u64(mapping, "invariant_violations")?,
        mutations: exact_json_u64(mapping, "mutations")?,
        receipt_mismatches: exact_json_u64(mapping, "receipt_mismatches")?,
        requests: exact_json_u64(mapping, "requests")?,
        retries: exact_json_u64(mapping, "retries")?,
    })
}

fn parse_case_counts(value: &Value) -> Result<EvidenceCaseCounts, &'static str> {
    let mapping = value
        .as_object()
        .ok_or("evidence case counts must be an object")?;
    if !object_has_exact_keys(mapping, &["failed", "passed", "rejected", "total"]) {
        return Err("evidence case counts do not match the v1 schema");
    }
    let counts = EvidenceCaseCounts {
        failed: exact_json_u64(mapping, "failed")?,
        passed: exact_json_u64(mapping, "passed")?,
        rejected: exact_json_u64(mapping, "rejected")?,
        total: exact_json_u64(mapping, "total")?,
    };
    if counts.total == 0
        || counts.total
            != counts
                .passed
                .checked_add(counts.failed)
                .and_then(|value| value.checked_add(counts.rejected))
                .ok_or("evidence case counter overflow")?
    {
        return Err("evidence case counts are inconsistent");
    }
    Ok(counts)
}

fn evidence_chain_seed(domain: &str) -> String {
    domain_fingerprint(
        domain,
        "{\"profile\":\"IBAE-COMPACT-EVIDENCE-COUNTS-AND-IDENTITIES-V1\"}",
    )
}

fn evidence_chain_update(
    domain: &str,
    prior: &str,
    ordinal: u64,
    item_type: &str,
    identity: &str,
) -> Result<String, &'static str> {
    let record = json!({
        "identity": identity,
        "item_type": item_type,
        "ordinal": ordinal,
        "prior": prior,
    });
    let canonical = canonical_value(&record).map_err(|_| "evidence chain record is invalid")?;
    Ok(domain_fingerprint(domain, &canonical))
}

fn update_fast_fold(mut state: u64, item_type: &str, canonical_item: &str) -> u64 {
    for byte in item_type
        .bytes()
        .chain([0_u8])
        .chain(canonical_item.bytes())
    {
        state ^= u64::from(byte);
        state = state.wrapping_mul(1_099_511_628_211);
    }
    state
}

fn parse_case_item(value: &Value) -> Result<EvidenceCase, &'static str> {
    let mapping = value.as_object().ok_or("evidence case must be an object")?;
    if !object_has_exact_keys(
        mapping,
        &[
            "case_id",
            "admission_id",
            "counters",
            "failure",
            "input_id",
            "item_type",
            "protocol_version",
            "receipt_id",
            "result_id",
            "runtime_source",
            "status",
        ],
    ) {
        return Err("evidence case does not match the v1 schema");
    }
    if mapping.get("item_type").and_then(Value::as_str) != Some("case")
        || mapping.get("protocol_version").and_then(Value::as_str)
            != Some(EVIDENCE_PROTOCOL_VERSION)
    {
        return Err("unsupported evidence case variant");
    }
    let fingerprint = |name: &str| -> Result<String, &'static str> {
        mapping
            .get(name)
            .and_then(Value::as_str)
            .filter(|identity| is_fingerprint(identity))
            .map(str::to_owned)
            .ok_or("evidence identities must be lowercase SHA-256 fingerprints")
    };
    let status = mapping
        .get("status")
        .and_then(Value::as_str)
        .filter(|status| matches!(*status, "passed" | "failed" | "rejected"))
        .ok_or("evidence case status is unsupported")?
        .to_owned();
    let counters = parse_evidence_counters(
        mapping
            .get("counters")
            .ok_or("evidence case counters are required")?,
    )?;
    let failure = match mapping.get("failure") {
        Some(Value::Null) if status == "passed" => None,
        Some(Value::Object(failure)) if status != "passed" => {
            if !object_has_exact_keys(failure, &["detail", "reason_code"]) {
                return Err("evidence failure does not match the v1 schema");
            }
            let reason_code = failure
                .get("reason_code")
                .and_then(Value::as_str)
                .filter(|text| !text.is_empty() && text.len() <= 256)
                .ok_or("evidence failure reason is invalid")?
                .to_owned();
            let detail = failure
                .get("detail")
                .cloned()
                .ok_or("evidence failure detail is required")?;
            let detail_canonical =
                canonical_value(&detail).map_err(|_| "evidence failure detail is invalid")?;
            if detail_canonical.len() > MAX_EVIDENCE_FAILURE_DETAIL_BYTES {
                return Err("evidence failure detail exceeds its hard byte limit");
            }
            Some((reason_code, detail))
        }
        _ => return Err("evidence case failure state is inconsistent with status"),
    };
    if status == "passed"
        && (counters.invariant_violations != 0
            || counters.canonical_mismatches != 0
            || counters.receipt_mismatches != 0)
    {
        return Err("passing evidence cannot report a correctness mismatch");
    }
    let runtime_source = match mapping.get("runtime_source") {
        Some(Value::Null) => None,
        Some(Value::Object(source))
            if object_has_exact_keys(
                source,
                &[
                    "prior_state_id",
                    "resulting_state_id",
                    "runtime_receipt_id",
                    "session_id",
                ],
            ) =>
        {
            let source_identity = |name: &str| -> Result<String, &'static str> {
                source
                    .get(name)
                    .and_then(Value::as_str)
                    .filter(|identity| is_fingerprint(identity))
                    .map(str::to_owned)
                    .ok_or("runtime evidence source identity is invalid")
            };
            Some(RuntimeEvidenceSource {
                prior_state_id: source_identity("prior_state_id")?,
                resulting_state_id: source_identity("resulting_state_id")?,
                runtime_receipt_id: source_identity("runtime_receipt_id")?,
                session_id: source_identity("session_id")?,
            })
        }
        _ => return Err("runtime evidence source does not match the v1 schema"),
    };
    Ok(EvidenceCase {
        admission_id: fingerprint("admission_id")?,
        case_id: fingerprint("case_id")?,
        counters,
        failure,
        input_id: fingerprint("input_id")?,
        receipt_id: fingerprint("receipt_id")?,
        result_id: fingerprint("result_id")?,
        runtime_source,
        status,
    })
}

fn parse_child_receipt(value: &Value) -> Result<ChildEvidence, &'static str> {
    let mapping = value
        .as_object()
        .ok_or("child evidence receipt must be an object")?;
    if !object_has_exact_keys(
        mapping,
        &[
            "aggregate_identities",
            "authorization_manifest",
            "bound_identities",
            "case_counts",
            "counter_totals",
            "evidence_profile",
            "failure_summary",
            "item_counts",
            "limits",
            "protocol_version",
            "receipt_id",
            "runtime_boundary",
            "status",
        ],
    ) {
        return Err("child evidence receipt does not match the v1 schema");
    }
    if mapping.get("protocol_version").and_then(Value::as_str) != Some(EVIDENCE_PROTOCOL_VERSION)
        || mapping.get("evidence_profile").and_then(Value::as_str) != Some(EVIDENCE_PROFILE)
    {
        return Err("child evidence profile is unsupported");
    }
    let full_canonical =
        canonical_value(value).map_err(|_| "child evidence receipt is not canonicalizable")?;
    if full_canonical.len() > MAX_COMPACT_EVIDENCE_BYTES {
        return Err("child evidence receipt exceeds its fixed byte ceiling");
    }
    let receipt_id = mapping
        .get("receipt_id")
        .and_then(Value::as_str)
        .filter(|identity| is_fingerprint(identity))
        .ok_or("child evidence receipt identity is invalid")?
        .to_owned();
    let mut without_id = mapping.clone();
    without_id.remove("receipt_id");
    let canonical = canonical_value(&Value::Object(without_id))
        .map_err(|_| "child evidence receipt is not canonicalizable")?;
    if domain_fingerprint(EVIDENCE_RECEIPT_DOMAIN, &canonical) != receipt_id {
        return Err("child evidence receipt identity does not match its record");
    }
    let aggregates = mapping
        .get("aggregate_identities")
        .and_then(Value::as_object)
        .filter(|item| {
            object_has_exact_keys(item, &["admissions", "inputs", "receipts", "results"])
        })
        .ok_or("child evidence aggregate identities are invalid")?;
    let aggregate = |name: &str| -> Result<String, &'static str> {
        aggregates
            .get(name)
            .and_then(Value::as_str)
            .filter(|identity| is_fingerprint(identity))
            .map(str::to_owned)
            .ok_or("child evidence aggregate identity is invalid")
    };
    let authorization_manifest = mapping
        .get("authorization_manifest")
        .and_then(Value::as_object)
        .filter(|item| object_has_exact_keys(item, &["count", "manifest_id"]))
        .ok_or("child evidence authorization manifest is invalid")?;
    let authorization_manifest_count = exact_json_u64(authorization_manifest, "count")?;
    if authorization_manifest_count > MAX_EVIDENCE_AUTHORIZATIONS as u64 {
        return Err("child evidence authorization manifest exceeds its hard bound");
    }
    let authorization_manifest_identity = authorization_manifest
        .get("manifest_id")
        .and_then(Value::as_str)
        .filter(|identity| is_fingerprint(identity))
        .map(str::to_owned)
        .ok_or("child evidence authorization manifest identity is invalid")?;
    let bound = mapping
        .get("bound_identities")
        .and_then(Value::as_object)
        .filter(|item| {
            object_has_exact_keys(item, &["execution", "governance", "orchestration", "task"])
        })
        .ok_or("child evidence bound identities are invalid")?;
    if bound
        .values()
        .any(|identity| !identity.as_str().is_some_and(is_fingerprint))
    {
        return Err("child evidence bound identity is invalid");
    }
    let bound_identity = |name: &str| -> Result<String, &'static str> {
        bound
            .get(name)
            .and_then(Value::as_str)
            .map(str::to_owned)
            .ok_or("child evidence bound identity is invalid")
    };
    let case_counts = parse_case_counts(
        mapping
            .get("case_counts")
            .ok_or("child evidence case counts are required")?,
    )?;
    let counters = parse_evidence_counters(
        mapping
            .get("counter_totals")
            .ok_or("child evidence counters are required")?,
    )?;
    let failure_count = case_counts.failure_count()?;
    let failure = mapping
        .get("failure_summary")
        .and_then(Value::as_object)
        .filter(|item| {
            object_has_exact_keys(
                item,
                &[
                    "count",
                    "details_available",
                    "details_truncated",
                    "first_index",
                ],
            )
        })
        .ok_or("child evidence failure summary is invalid")?;
    let details_available = exact_json_u64(failure, "details_available")?;
    let details_truncated = failure
        .get("details_truncated")
        .and_then(Value::as_bool)
        .ok_or("child evidence failure truncation flag is invalid")?;
    if exact_json_u64(failure, "count")? != failure_count || details_available > failure_count {
        return Err("child evidence failure summary is inconsistent");
    }
    let _first_failure_index = match failure.get("first_index") {
        Some(Value::Null) if failure_count == 0 => None,
        Some(value) if failure_count > 0 => value
            .as_u64()
            .filter(|index| *index < case_counts.total)
            .map(Some)
            .ok_or("child first-failure index is invalid")?,
        _ => return Err("child first-failure index is inconsistent"),
    };
    let status = mapping
        .get("status")
        .and_then(Value::as_str)
        .filter(|status| {
            (*status == "complete_no_failures" && failure_count == 0)
                || (*status == "complete_with_failures" && failure_count > 0)
        })
        .ok_or("child evidence status is inconsistent")?
        .to_owned();
    let items = mapping
        .get("item_counts")
        .and_then(Value::as_object)
        .filter(|item| object_has_exact_keys(item, &["case_records", "child_receipts"]))
        .ok_or("child evidence item counts are invalid")?;
    let child_items = exact_json_u64(items, "case_records")?
        .checked_add(exact_json_u64(items, "child_receipts")?)
        .ok_or("child evidence item counter overflow")?;
    if child_items == 0 || child_items > case_counts.total {
        return Err("child evidence item counts are inconsistent");
    }
    let limits = mapping
        .get("limits")
        .and_then(Value::as_object)
        .filter(|item| object_has_exact_keys(item, &["max_cases", "max_failure_details"]))
        .ok_or("child evidence limits are invalid")?;
    let max_cases = exact_json_u64(limits, "max_cases")?;
    let max_failure_details = exact_json_u64(limits, "max_failure_details")?;
    if max_cases == 0
        || max_cases > MAX_EVIDENCE_CASES
        || case_counts.total > max_cases
        || max_failure_details == 0
        || max_failure_details > MAX_EVIDENCE_FAILURE_DETAILS
        || details_available != failure_count.min(max_failure_details)
        || details_truncated != (details_available < failure_count)
    {
        return Err("child evidence limits are inconsistent");
    }
    if status == "complete_no_failures"
        && (counters.invariant_violations != 0
            || counters.canonical_mismatches != 0
            || counters.receipt_mismatches != 0)
    {
        return Err("failure-free child evidence cannot report a correctness mismatch");
    }
    parse_runtime_boundary(
        mapping
            .get("runtime_boundary")
            .ok_or("child evidence runtime boundary is required")?,
    )?;
    Ok(ChildEvidence {
        aggregate_input_identity: aggregate("inputs")?,
        aggregate_admission_identity: aggregate("admissions")?,
        aggregate_receipt_identity: aggregate("receipts")?,
        aggregate_result_identity: aggregate("results")?,
        case_counts,
        counters,
        authorization_manifest_count,
        authorization_manifest_identity,
        governance_identity: bound_identity("governance")?,
        orchestration_identity: bound_identity("orchestration")?,
        receipt_id,
        status,
        task_identity: bound_identity("task")?,
    })
}

fn parse_evidence_item(canonical_item: &str) -> Result<EvidenceItem, &'static str> {
    if canonical_item.len() > MAX_EVIDENCE_CASE_BYTES {
        return Err("evidence item exceeds its hard byte limit");
    }
    let value =
        parse_canonical(canonical_item).map_err(|_| "evidence item is not canonical JSON")?;
    let mapping = value.as_object().ok_or("evidence item must be an object")?;
    match mapping.get("item_type").and_then(Value::as_str) {
        Some("case") => parse_case_item(&value).map(EvidenceItem::Case),
        Some("child_receipt") => {
            if !object_has_exact_keys(mapping, &["item_type", "protocol_version", "receipt"])
                || mapping.get("protocol_version").and_then(Value::as_str)
                    != Some(EVIDENCE_PROTOCOL_VERSION)
            {
                return Err("child evidence item does not match the v1 schema");
            }
            parse_child_receipt(
                mapping
                    .get("receipt")
                    .ok_or("child evidence receipt is required")?,
            )
            .map(|child| EvidenceItem::Child(Box::new(child)))
        }
        _ => Err("unsupported evidence item variant"),
    }
}

#[derive(Clone)]
struct EvidenceCore {
    aggregate_admission_identity: String,
    aggregate_input_identity: String,
    aggregate_receipt_identity: String,
    aggregate_result_identity: String,
    all_sources_bound: bool,
    authorization_manifest: BTreeMap<String, EvidenceAuthorization>,
    authorization_manifest_identity: String,
    case_counts: EvidenceCaseCounts,
    case_records: u64,
    child_receipts: u64,
    counters: EvidenceCounters,
    failure_details: Vec<EvidenceFailureDetail>,
    first_failure_index: Option<u64>,
    governance_identity: String,
    max_cases: u64,
    max_failure_details: u64,
    orchestration_identity: String,
    observed_authorizations: BTreeSet<String>,
    runtime_boundary: Option<EvidenceRuntimeBoundary>,
    fast_fold: Option<u64>,
    sealed_summary: Option<Arc<str>>,
    finalized: Option<Arc<str>>,
    task_identity: String,
}

impl EvidenceCore {
    #[allow(clippy::too_many_arguments)]
    fn new(
        task_identity: &str,
        governance_identity: &str,
        orchestration_identity: &str,
        authorization_manifest_json: &str,
        max_cases: u64,
        max_failure_details: u64,
        enable_fast_fold: bool,
    ) -> Result<Self, &'static str> {
        for identity in [task_identity, governance_identity, orchestration_identity] {
            if !is_fingerprint(identity) {
                return Err("evidence bound identities must be lowercase SHA-256 fingerprints");
            }
        }
        if max_cases == 0 || max_cases > MAX_EVIDENCE_CASES {
            return Err("max_cases is outside the compact-evidence hard bounds");
        }
        if max_failure_details == 0 || max_failure_details > MAX_EVIDENCE_FAILURE_DETAILS {
            return Err("max_failure_details is outside the compact-evidence hard bounds");
        }
        let (authorization_manifest, authorization_manifest_identity) =
            parse_authorization_manifest(authorization_manifest_json)?;
        Ok(Self {
            aggregate_admission_identity: evidence_chain_seed(EVIDENCE_ADMISSION_DOMAIN),
            aggregate_input_identity: evidence_chain_seed(EVIDENCE_INPUT_DOMAIN),
            aggregate_receipt_identity: evidence_chain_seed(EVIDENCE_CASE_RECEIPT_DOMAIN),
            aggregate_result_identity: evidence_chain_seed(EVIDENCE_RESULT_DOMAIN),
            all_sources_bound: true,
            authorization_manifest,
            authorization_manifest_identity,
            case_counts: EvidenceCaseCounts::default(),
            case_records: 0,
            child_receipts: 0,
            counters: EvidenceCounters::default(),
            failure_details: Vec::with_capacity(max_failure_details as usize),
            first_failure_index: None,
            governance_identity: governance_identity.to_owned(),
            max_cases,
            max_failure_details,
            orchestration_identity: orchestration_identity.to_owned(),
            observed_authorizations: BTreeSet::new(),
            runtime_boundary: None,
            fast_fold: enable_fast_fold.then_some(14_695_981_039_346_656_037),
            sealed_summary: None,
            finalized: None,
            task_identity: task_identity.to_owned(),
        })
    }

    fn ingest_structural(&mut self, canonical_item: &str) -> Result<(), &'static str> {
        if self.sealed_summary.is_some() || self.finalized.is_some() {
            return Err("sealed compact evidence cannot admit more items");
        }
        let item = parse_evidence_item(canonical_item)?;
        if !matches!(&item, EvidenceItem::Case(case) if case.runtime_source.is_none()) {
            return Err("structural evidence admits only unbound case records");
        }
        let mut candidate = self.clone();
        candidate.all_sources_bound = false;
        candidate.ingest_validated(item, canonical_item)?;
        *self = candidate;
        Ok(())
    }

    fn ingest_runtime(
        &mut self,
        canonical_item: &str,
        seal: &NativeRuntimeReceiptSeal,
    ) -> Result<(), &'static str> {
        if self.sealed_summary.is_some() || self.finalized.is_some() {
            return Err("sealed compact evidence cannot admit more items");
        }
        let item = parse_evidence_item(canonical_item)?;
        let case = match &item {
            EvidenceItem::Case(case) if seal.validates_case(case) => case,
            _ => return Err("runtime evidence does not match its opaque receipt seal"),
        };
        let authorization = self
            .authorization_manifest
            .get(&case.admission_id)
            .ok_or("runtime admission is absent from the authorization manifest")?;
        if !authorization.matches_runtime(seal) {
            return Err("runtime evidence does not match the authorization manifest");
        }
        if seal.command_type == "execute_read"
            && seal.cache_status.as_deref() == Some("cache_hit")
            && !self.observed_authorizations.contains(&case.admission_id)
        {
            return Err("cache hit lacks a prior cold execution for its admission");
        }
        let mut candidate = self.clone();
        // The v0.3 cache key intentionally predates governed capability IDs.
        // Only an accepted cold transition in this exact direct stream proves
        // that a later hit belongs to the same governed admission. Retries and
        // first-seen hits cannot establish manifest execution coverage.
        if seal.command_type == "execute_read"
            && seal.status == "accepted"
            && seal.cache_status.as_deref() == Some("cold_execution")
        {
            candidate
                .observed_authorizations
                .insert(case.admission_id.clone());
        }
        candidate.ingest_validated(item, canonical_item)?;
        *self = candidate;
        Ok(())
    }

    fn ingest_child(
        &mut self,
        canonical_item: &str,
        seal: &NativeEvidenceReceiptSeal,
    ) -> Result<(), &'static str> {
        if self.sealed_summary.is_some() || self.finalized.is_some() {
            return Err("sealed compact evidence cannot admit more items");
        }
        if !seal.source_bound {
            return Err("structural-only child evidence cannot bind a live parent");
        }
        let item = parse_evidence_item(canonical_item)?;
        let child = match &item {
            EvidenceItem::Child(child) => child.as_ref(),
            _ => return Err("child evidence admission requires a child receipt"),
        };
        if child.receipt_id != seal.receipt_id {
            return Err("child evidence does not match its opaque receipt seal");
        }
        let value =
            parse_canonical(canonical_item).map_err(|_| "child evidence item is not canonical")?;
        let receipt = value
            .get("receipt")
            .ok_or("child evidence receipt is required")?;
        let canonical_receipt = canonical_value(receipt)
            .map_err(|_| "child evidence receipt is not canonicalizable")?;
        if !seal.validates_receipt(&canonical_receipt) {
            return Err("child evidence does not match its opaque receipt seal");
        }
        let mut candidate = self.clone();
        candidate.ingest_validated(item, canonical_item)?;
        *self = candidate;
        Ok(())
    }

    fn ingest_validated(
        &mut self,
        item: EvidenceItem,
        canonical_item: &str,
    ) -> Result<(), &'static str> {
        let ordinal = self
            .case_records
            .checked_add(self.child_receipts)
            .ok_or("evidence item counter overflow")?;
        match item {
            EvidenceItem::Case(item) => {
                let next_counts = match item.status.as_str() {
                    "passed" => EvidenceCaseCounts {
                        total: 1,
                        passed: 1,
                        failed: 0,
                        rejected: 0,
                    },
                    "failed" => EvidenceCaseCounts {
                        total: 1,
                        passed: 0,
                        failed: 1,
                        rejected: 0,
                    },
                    "rejected" => EvidenceCaseCounts {
                        total: 1,
                        passed: 0,
                        failed: 0,
                        rejected: 1,
                    },
                    _ => return Err("evidence case status is unsupported"),
                };
                let prospective_counts = self.case_counts.checked_add(next_counts)?;
                if prospective_counts.total > self.max_cases {
                    return Err("compact evidence case bound exhausted");
                }
                let prospective_counters = self.counters.checked_add(item.counters)?;
                let input_aggregate = evidence_chain_update(
                    EVIDENCE_INPUT_DOMAIN,
                    &self.aggregate_input_identity,
                    ordinal,
                    "case",
                    &item.input_id,
                )?;
                let admission_aggregate = evidence_chain_update(
                    EVIDENCE_ADMISSION_DOMAIN,
                    &self.aggregate_admission_identity,
                    ordinal,
                    "case",
                    &item.admission_id,
                )?;
                let result_aggregate = evidence_chain_update(
                    EVIDENCE_RESULT_DOMAIN,
                    &self.aggregate_result_identity,
                    ordinal,
                    "case",
                    &item.result_id,
                )?;
                let receipt_aggregate = evidence_chain_update(
                    EVIDENCE_CASE_RECEIPT_DOMAIN,
                    &self.aggregate_receipt_identity,
                    ordinal,
                    "case",
                    &item.receipt_id,
                )?;
                match &item.runtime_source {
                    None => {}
                    Some(source) => {
                        if source.runtime_receipt_id != item.receipt_id {
                            return Err("runtime evidence source receipt identity is inconsistent");
                        }
                        match &mut self.runtime_boundary {
                            Some(boundary) => {
                                if boundary.session_id != source.session_id
                                    || boundary.final_state_id != source.prior_state_id
                                {
                                    return Err("runtime evidence source continuity is invalid");
                                }
                                boundary.final_state_id = source.resulting_state_id.clone();
                                boundary.last_runtime_receipt_id =
                                    source.runtime_receipt_id.clone();
                            }
                            None => {
                                self.runtime_boundary = Some(EvidenceRuntimeBoundary {
                                    final_state_id: source.resulting_state_id.clone(),
                                    first_runtime_receipt_id: source.runtime_receipt_id.clone(),
                                    initial_state_id: source.prior_state_id.clone(),
                                    last_runtime_receipt_id: source.runtime_receipt_id.clone(),
                                    session_id: source.session_id.clone(),
                                });
                            }
                        }
                    }
                }
                if let Some((reason_code, detail)) = item.failure {
                    if self.first_failure_index.is_none() {
                        self.first_failure_index = Some(self.case_counts.total);
                    }
                    if self.failure_details.len() < self.max_failure_details as usize {
                        self.failure_details.push(EvidenceFailureDetail {
                            case_id: item.case_id,
                            case_index: self.case_counts.total,
                            detail,
                            reason_code,
                            receipt_id: item.receipt_id.clone(),
                            status: item.status,
                        });
                    }
                }
                self.case_counts = prospective_counts;
                self.counters = prospective_counters;
                self.case_records = self
                    .case_records
                    .checked_add(1)
                    .ok_or("evidence item counter overflow")?;
                self.aggregate_input_identity = input_aggregate;
                self.aggregate_admission_identity = admission_aggregate;
                self.aggregate_result_identity = result_aggregate;
                self.aggregate_receipt_identity = receipt_aggregate;
            }
            EvidenceItem::Child(item) => {
                let item = *item;
                if item.task_identity != self.task_identity
                    || item.governance_identity != self.governance_identity
                    || item.orchestration_identity != self.orchestration_identity
                {
                    return Err("child evidence authority context does not match its parent");
                }
                if item.authorization_manifest_identity != self.authorization_manifest_identity
                    || item.authorization_manifest_count != self.authorization_manifest.len() as u64
                {
                    return Err("child evidence authorization manifest does not match its parent");
                }
                if item.status != "complete_no_failures" {
                    return Err("failed child evidence requires its own bounded expansion");
                }
                let prospective_counts = self.case_counts.checked_add(item.case_counts)?;
                if prospective_counts.total > self.max_cases {
                    return Err("compact evidence case bound exhausted");
                }
                let prospective_counters = self.counters.checked_add(item.counters)?;
                let input_aggregate = evidence_chain_update(
                    EVIDENCE_INPUT_DOMAIN,
                    &self.aggregate_input_identity,
                    ordinal,
                    "child_receipt",
                    &item.aggregate_input_identity,
                )?;
                let admission_aggregate = evidence_chain_update(
                    EVIDENCE_ADMISSION_DOMAIN,
                    &self.aggregate_admission_identity,
                    ordinal,
                    "child_receipt",
                    &item.aggregate_admission_identity,
                )?;
                let result_aggregate = evidence_chain_update(
                    EVIDENCE_RESULT_DOMAIN,
                    &self.aggregate_result_identity,
                    ordinal,
                    "child_receipt",
                    &item.aggregate_result_identity,
                )?;
                let receipt_aggregate = evidence_chain_update(
                    EVIDENCE_CASE_RECEIPT_DOMAIN,
                    &self.aggregate_receipt_identity,
                    ordinal,
                    "child_receipt",
                    &item.aggregate_receipt_identity,
                )?;
                self.case_counts = prospective_counts;
                self.counters = prospective_counters;
                self.child_receipts = self
                    .child_receipts
                    .checked_add(1)
                    .ok_or("evidence item counter overflow")?;
                self.observed_authorizations =
                    self.authorization_manifest.keys().cloned().collect();
                self.aggregate_input_identity = input_aggregate;
                self.aggregate_admission_identity = admission_aggregate;
                self.aggregate_result_identity = result_aggregate;
                self.aggregate_receipt_identity = receipt_aggregate;
            }
        }
        if let Some(fold) = self.fast_fold {
            self.fast_fold = Some(update_fast_fold(fold, "ordered_item", canonical_item));
        }
        Ok(())
    }

    fn aggregate_summary_without_id(&self) -> Result<Value, &'static str> {
        if self.case_counts.total == 0 {
            return Err("compact evidence requires at least one admitted case");
        }
        if self.all_sources_bound
            && self.observed_authorizations.len() != self.authorization_manifest.len()
        {
            return Err("not every authorized runtime action has evidence");
        }
        Ok(json!({
            "aggregate_identities": {
                "admissions": self.aggregate_admission_identity,
                "inputs": self.aggregate_input_identity,
                "receipts": self.aggregate_receipt_identity,
                "results": self.aggregate_result_identity,
            },
            "authorization_manifest": {
                "count": self.authorization_manifest.len(),
                "manifest_id": self.authorization_manifest_identity,
            },
            "bound_identities": {
                "governance": self.governance_identity,
                "orchestration": self.orchestration_identity,
                "task": self.task_identity,
            },
            "case_counts": self.case_counts.value(),
            "counter_totals": self.counters.value(),
            "evidence_profile": EVIDENCE_PROFILE,
            "item_counts": {
                "case_records": self.case_records,
                "child_receipts": self.child_receipts,
            },
            "protocol_version": EVIDENCE_PROTOCOL_VERSION,
            "runtime_boundary": if self.all_sources_bound && self.child_receipts == 0 {
                self.runtime_boundary.as_ref().map(EvidenceRuntimeBoundary::value)
            } else {
                None
            },
        }))
    }

    fn aggregate_summary(&mut self) -> Result<String, &'static str> {
        if let Some(summary) = &self.sealed_summary {
            return Ok(summary.to_string());
        }
        let without_id = self.aggregate_summary_without_id()?;
        let canonical = canonical_value(&without_id)
            .map_err(|_| "compact evidence summary is not canonicalizable")?;
        let summary_id = domain_fingerprint(EVIDENCE_SUMMARY_DOMAIN, &canonical);
        let mut summary = without_id;
        summary
            .as_object_mut()
            .expect("evidence summary is an object")
            .insert("summary_id".to_owned(), Value::String(summary_id));
        let canonical = canonical_value(&summary)
            .map_err(|_| "compact evidence summary is not canonicalizable")?;
        if canonical.len() > MAX_COMPACT_EVIDENCE_BYTES {
            return Err("compact evidence summary exceeds its fixed byte ceiling");
        }
        self.sealed_summary = Some(Arc::from(canonical.as_str()));
        Ok(canonical)
    }

    fn receipt_without_id(&self, execution_identity: &str) -> Result<Value, &'static str> {
        if self.sealed_summary.is_none() {
            return Err("compact evidence must be sealed before finalization");
        }
        if !is_fingerprint(execution_identity) {
            return Err("execution identity must be a lowercase SHA-256 fingerprint");
        }
        let failure_count = self.case_counts.failure_count()?;
        let details_available = u64::try_from(self.failure_details.len())
            .map_err(|_| "failure detail count is not representable")?;
        Ok(json!({
            "aggregate_identities": {
                "admissions": self.aggregate_admission_identity,
                "inputs": self.aggregate_input_identity,
                "receipts": self.aggregate_receipt_identity,
                "results": self.aggregate_result_identity,
            },
            "bound_identities": {
                "execution": execution_identity,
                "governance": self.governance_identity,
                "orchestration": self.orchestration_identity,
                "task": self.task_identity,
            },
            "authorization_manifest": {
                "count": self.authorization_manifest.len(),
                "manifest_id": self.authorization_manifest_identity,
            },
            "case_counts": self.case_counts.value(),
            "counter_totals": self.counters.value(),
            "evidence_profile": EVIDENCE_PROFILE,
            "failure_summary": {
                "count": failure_count,
                "details_available": details_available,
                "details_truncated": details_available < failure_count,
                "first_index": self.first_failure_index,
            },
            "item_counts": {
                "case_records": self.case_records,
                "child_receipts": self.child_receipts,
            },
            "limits": {
                "max_cases": self.max_cases,
                "max_failure_details": self.max_failure_details,
            },
            "protocol_version": EVIDENCE_PROTOCOL_VERSION,
            "runtime_boundary": if self.all_sources_bound && self.child_receipts == 0 {
                self.runtime_boundary.as_ref().map(EvidenceRuntimeBoundary::value)
            } else {
                None
            },
            "status": if failure_count == 0 {
                "complete_no_failures"
            } else {
                "complete_with_failures"
            },
        }))
    }

    fn finalize(&mut self, execution_identity: &str) -> Result<String, &'static str> {
        if let Some(finalized) = &self.finalized {
            let value = parse_canonical(finalized)
                .map_err(|_| "finalized compact evidence is not canonical")?;
            if value["bound_identities"]["execution"].as_str() != Some(execution_identity) {
                return Err("compact evidence is already bound to another execution identity");
            }
            return Ok(finalized.to_string());
        }
        let without_id = self.receipt_without_id(execution_identity)?;
        let canonical = canonical_value(&without_id)
            .map_err(|_| "compact evidence receipt is not canonicalizable")?;
        let receipt_id = domain_fingerprint(EVIDENCE_RECEIPT_DOMAIN, &canonical);
        let mut receipt = without_id;
        receipt
            .as_object_mut()
            .expect("evidence receipt is an object")
            .insert("receipt_id".to_owned(), Value::String(receipt_id));
        let canonical = canonical_value(&receipt)
            .map_err(|_| "compact evidence receipt is not canonicalizable")?;
        if canonical.len() > MAX_COMPACT_EVIDENCE_BYTES {
            return Err("compact evidence receipt exceeds its fixed byte ceiling");
        }
        self.finalized = Some(Arc::from(canonical.as_str()));
        Ok(canonical)
    }

    fn fast_regression_observation(&self) -> Option<String> {
        self.fast_fold.map(|fold| {
            canonical_value(&json!({
                "algorithm": FAST_FOLD_ALGORITHM,
                "correctness_authority": false,
                "protocol_version": EVIDENCE_PROTOCOL_VERSION,
                "value": format!("{fold:016x}"),
            }))
            .expect("the fixed-shape fast-fold observation is canonicalizable")
        })
    }

    fn expand(&self, canonical_request: &str) -> Result<String, &'static str> {
        let finalized = self
            .finalized
            .as_ref()
            .ok_or("compact evidence must be finalized before expansion")?;
        let receipt = parse_canonical(finalized)
            .map_err(|_| "finalized compact evidence is not canonical")?;
        let receipt_id = receipt["receipt_id"]
            .as_str()
            .ok_or("finalized compact evidence has no receipt identity")?;
        let request = parse_canonical(canonical_request)
            .map_err(|_| "evidence expansion request is not canonical JSON")?;
        let mapping = request
            .as_object()
            .ok_or("evidence expansion request must be an object")?;
        if !object_has_exact_keys(
            mapping,
            &[
                "evidence_receipt_id",
                "max_details",
                "protocol_version",
                "start_case_index",
            ],
        ) || mapping.get("protocol_version").and_then(Value::as_str)
            != Some(EVIDENCE_PROTOCOL_VERSION)
            || mapping.get("evidence_receipt_id").and_then(Value::as_str) != Some(receipt_id)
        {
            return Err("evidence expansion request is not bound to its compact parent");
        }
        let start = exact_json_u64(mapping, "start_case_index")?;
        let max_details = exact_json_u64(mapping, "max_details")?;
        if max_details == 0 || max_details > self.max_failure_details {
            return Err("evidence expansion size is outside the declared bound");
        }
        let details: Vec<Value> = self
            .failure_details
            .iter()
            .filter(|detail| detail.case_index >= start)
            .take(max_details as usize)
            .map(EvidenceFailureDetail::value)
            .collect();
        let without_id = json!({
            "details": details,
            "evidence_receipt_id": receipt_id,
            "protocol_version": EVIDENCE_PROTOCOL_VERSION,
            "start_case_index": start,
        });
        let canonical = canonical_value(&without_id)
            .map_err(|_| "evidence expansion is not canonicalizable")?;
        let expansion_id = domain_fingerprint(EVIDENCE_EXPANSION_DOMAIN, &canonical);
        let mut expansion = without_id;
        expansion
            .as_object_mut()
            .expect("evidence expansion is an object")
            .insert("expansion_id".to_owned(), Value::String(expansion_id));
        let canonical =
            canonical_value(&expansion).map_err(|_| "evidence expansion is not canonicalizable")?;
        if canonical.len() > MAX_EVIDENCE_EXPANSION_BYTES {
            return Err("evidence expansion exceeds its hard byte limit");
        }
        Ok(canonical)
    }
}

/// Non-constructible seal for one exact aggregate summary emitted by Rust.
#[pyclass(
    name = "NativeEvidenceSummarySeal",
    module = "ibae._runtime",
    unsendable
)]
struct NativeEvidenceSummarySeal {
    canonical: Arc<str>,
    source_bound: bool,
}

#[pymethods]
impl NativeEvidenceSummarySeal {
    fn validates(&self, canonical_summary: &str) -> bool {
        self.canonical.as_ref() == canonical_summary
    }

    fn source_bound(&self) -> bool {
        self.source_bound
    }
}

/// Non-constructible seal for one exact compact receipt emitted by Rust.
#[pyclass(
    name = "NativeEvidenceReceiptSeal",
    module = "ibae._runtime",
    unsendable
)]
struct NativeEvidenceReceiptSeal {
    canonical: Arc<str>,
    receipt_id: String,
    source_bound: bool,
}

impl NativeEvidenceReceiptSeal {
    fn validates_receipt(&self, canonical_receipt: &str) -> bool {
        self.canonical.as_ref() == canonical_receipt
    }
}

#[pymethods]
impl NativeEvidenceReceiptSeal {
    fn validates(&self, canonical_receipt: &str) -> bool {
        self.validates_receipt(canonical_receipt)
    }

    fn source_bound(&self) -> bool {
        self.source_bound
    }
}

/// Opaque, bounded streaming reducer for compact deterministic evidence.
#[pyclass(
    name = "NativeEvidenceAccumulator",
    module = "ibae._runtime",
    unsendable
)]
struct NativeEvidenceAccumulator {
    core: EvidenceCore,
}

#[pymethods]
impl NativeEvidenceAccumulator {
    #[new]
    #[pyo3(signature = (
        task_identity,
        governance_identity,
        orchestration_identity,
        authorization_manifest_json,
        max_cases=None,
        max_failure_details=None,
        enable_fast_fold=None
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        task_identity: &str,
        governance_identity: &str,
        orchestration_identity: &str,
        authorization_manifest_json: &str,
        max_cases: Option<&Bound<'_, PyAny>>,
        max_failure_details: Option<&Bound<'_, PyAny>>,
        enable_fast_fold: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let enable_fast_fold = match enable_fast_fold {
            None => false,
            Some(value) if value.is_instance_of::<PyBool>() => value.extract::<bool>()?,
            Some(_) => {
                return Err(PyValueError::new_err(
                    "enable_fast_fold must be an exact boolean",
                ))
            }
        };
        let core = EvidenceCore::new(
            task_identity,
            governance_identity,
            orchestration_identity,
            authorization_manifest_json,
            exact_u64(max_cases, 100_000, "max_cases")?,
            exact_u64(max_failure_details, 8, "max_failure_details")?,
            enable_fast_fold,
        )
        .map_err(PyValueError::new_err)?;
        Ok(Self { core })
    }

    fn ingest_structural(&mut self, canonical_item: &str) -> PyResult<()> {
        self.core
            .ingest_structural(canonical_item)
            .map_err(PyValueError::new_err)
    }

    fn ingest_runtime(
        &mut self,
        canonical_item: &str,
        runtime_seal: PyRef<'_, NativeRuntimeReceiptSeal>,
    ) -> PyResult<()> {
        self.core
            .ingest_runtime(canonical_item, &runtime_seal)
            .map_err(PyValueError::new_err)
    }

    fn ingest_child(
        &mut self,
        canonical_item: &str,
        child_seal: PyRef<'_, NativeEvidenceReceiptSeal>,
    ) -> PyResult<()> {
        self.core
            .ingest_child(canonical_item, &child_seal)
            .map_err(PyValueError::new_err)
    }

    fn aggregate_summary(
        &mut self,
        py: Python<'_>,
    ) -> PyResult<(String, Py<NativeEvidenceSummarySeal>)> {
        let canonical = self
            .core
            .aggregate_summary()
            .map_err(PyValueError::new_err)?;
        let seal = Py::new(
            py,
            NativeEvidenceSummarySeal {
                canonical: Arc::from(canonical.as_str()),
                source_bound: self.core.all_sources_bound,
            },
        )?;
        Ok((canonical, seal))
    }

    fn finalize(
        &mut self,
        py: Python<'_>,
        execution_identity: &str,
    ) -> PyResult<(String, Py<NativeEvidenceReceiptSeal>)> {
        let canonical = self
            .core
            .finalize(execution_identity)
            .map_err(PyValueError::new_err)?;
        let value = parse_canonical(&canonical)
            .map_err(|_| PyValueError::new_err("finalized compact evidence is not canonical"))?;
        let receipt_id = value["receipt_id"]
            .as_str()
            .ok_or_else(|| PyValueError::new_err("compact evidence has no receipt identity"))?
            .to_owned();
        let seal = Py::new(
            py,
            NativeEvidenceReceiptSeal {
                canonical: Arc::from(canonical.as_str()),
                receipt_id,
                source_bound: self.core.all_sources_bound,
            },
        )?;
        Ok((canonical, seal))
    }

    fn fast_regression_observation(&self) -> Option<String> {
        self.core.fast_regression_observation()
    }

    fn expand(&self, canonical_request: &str) -> PyResult<String> {
        self.core
            .expand(canonical_request)
            .map_err(PyValueError::new_err)
    }
}

/// Opaque Python-owned handle whose authoritative fields remain Rust-private.
#[pyclass(name = "NativeRuntimeSession", module = "ibae._runtime", unsendable)]
struct NativeRuntimeSession {
    core: RuntimeCore,
}

#[pymethods]
impl NativeRuntimeSession {
    #[new]
    #[pyo3(signature = (
        session_key,
        max_requests=None,
        max_executions=None,
        max_retries=None,
        max_history=None
    ))]
    fn new(
        session_key: &str,
        max_requests: Option<&Bound<'_, PyAny>>,
        max_executions: Option<&Bound<'_, PyAny>>,
        max_retries: Option<&Bound<'_, PyAny>>,
        max_history: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let limits = Limits {
            requests: exact_u64(max_requests, 32, "max_requests")?,
            executions: exact_u64(max_executions, 16, "max_executions")?,
            retries: exact_u64(max_retries, 4, "max_retries")?,
            history: exact_u64(max_history, 32, "max_history")?,
        }
        .validate()
        .map_err(PyValueError::new_err)?;
        let core = RuntimeCore::new(session_key, limits).map_err(PyValueError::new_err)?;
        Ok(Self { core })
    }

    #[pyo3(signature = (command_json, operation=None))]
    fn dispatch(
        &mut self,
        py: Python<'_>,
        command_json: &str,
        operation: Option<Py<PyAny>>,
    ) -> PyResult<(String, Option<Py<NativeRuntimeReceiptSeal>>)> {
        let outcome = self
            .core
            .dispatch(command_json, || {
                let Some(callback) = operation else {
                    return Invocation::OperationFailed;
                };
                let result = match callback.call0(py) {
                    Ok(result) => result,
                    Err(_) => return Invocation::OperationFailed,
                };
                let envelope = match result.extract::<String>(py) {
                    Ok(envelope) => envelope,
                    Err(_) => return Invocation::InvalidObservation,
                };
                parse_invocation_envelope(&envelope)
            })
            .map_err(|_| {
                PyValueError::new_err("runtime record exceeds the declared deterministic envelope")
            })?;
        let seal = match NativeRuntimeReceiptSeal::from_outcome(&outcome) {
            Ok(seal) => Some(Py::new(py, seal)?),
            Err(_) => None,
        };
        Ok((outcome, seal))
    }

    fn snapshot(&self) -> PyResult<String> {
        self.core.snapshot_json().map_err(|_| {
            PyValueError::new_err("runtime snapshot exceeds the declared deterministic envelope")
        })
    }

    fn terminal_cycle_period(&self) -> Option<u8> {
        self.core.terminal_cycle_period()
    }
}

#[pyfunction]
fn canonicalize_json(canonical_json: &str) -> PyResult<String> {
    let value = parse_canonical(canonical_json)
        .map_err(|_| PyValueError::new_err("value is not admitted canonical JSON"))?;
    canonical_value(&value)
        .map_err(|_| PyValueError::new_err("value is not admitted canonical JSON"))
}

#[pymodule]
fn _runtime(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<NativeRuntimeSession>()?;
    module.add_class::<NativeRuntimeReceiptSeal>()?;
    module.add_class::<NativeEvidenceAccumulator>()?;
    module.add_class::<NativeEvidenceSummarySeal>()?;
    module.add_class::<NativeEvidenceReceiptSeal>()?;
    module.add_function(wrap_pyfunction!(canonicalize_json, module)?)?;
    module.add("PROTOCOL_VERSION", PROTOCOL_VERSION)?;
    module.add("EVIDENCE_PROTOCOL_VERSION", EVIDENCE_PROTOCOL_VERSION)?;
    module.add("EVIDENCE_PROFILE", EVIDENCE_PROFILE)?;
    module.add("MAX_COMPACT_EVIDENCE_BYTES", MAX_COMPACT_EVIDENCE_BYTES)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const ADMISSION: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    fn core(requests: u64, executions: u64, retries: u64, history: u64) -> RuntimeCore {
        RuntimeCore::new(
            "rust-test",
            Limits {
                requests,
                executions,
                retries,
                history,
            }
            .validate()
            .unwrap(),
        )
        .unwrap()
    }

    fn read_command(path: &str, dependency: &str) -> String {
        canonical_value(&json!({
            "admission_id": ADMISSION,
            "arguments": {"path": path},
            "command_type": "execute_read",
            "dependency_fingerprint": dependency,
            "protocol_version": PROTOCOL_VERSION,
            "tool_name": "read",
        }))
        .unwrap()
    }

    fn outcome_receipt(outcome: &str) -> Value {
        parse_runtime_canonical(outcome).unwrap()["receipt"].clone()
    }

    fn run<F>(runtime: &mut RuntimeCore, command: &str, invoke: F) -> String
    where
        F: FnOnce() -> Invocation,
    {
        runtime.dispatch(command, invoke).unwrap()
    }

    #[test]
    fn canonical_mapping_order_and_unicode_match_python_profile() {
        assert_eq!(
            parse_canonical("{\"a\":{\"x\":1,\"y\":2},\"b\":\"λ雪🚀\"}")
                .and_then(|value| canonical_value(&value))
                .unwrap(),
            "{\"a\":{\"x\":1,\"y\":2},\"b\":\"λ雪🚀\"}"
        );
    }

    #[test]
    fn canonical_float_profile_matches_python_thresholds() {
        for value in ["1.0", "-0.0", "0.0001", "1e-05", "1e+16", "1.25"] {
            assert_eq!(
                parse_canonical(value)
                    .and_then(|parsed| canonical_value(&parsed))
                    .unwrap(),
                value
            );
        }
    }

    #[test]
    fn rejects_noncanonical_json_forms() {
        for value in [
            "{\"b\":1,\"a\":2}",
            "{\"a\": 1}",
            "1e0",
            "-0",
            "{\"a\":1,\"a\":1}",
        ] {
            assert!(parse_canonical(value).is_err(), "accepted {value}");
        }
    }

    #[test]
    fn accepts_256_bit_boundary_and_rejects_next_integer() {
        assert!(parse_canonical(MAX_INTEGER_DECIMAL).is_ok());
        assert!(parse_canonical(
            "115792089237316195423570985008687907853269984665640564039457584007913129639936"
        )
        .is_err());
    }

    #[test]
    fn repeated_read_executes_once_and_hits_cache_twice() {
        let mut runtime = core(3, 2, 1, 8);
        let command = read_command("x", "commit-a");
        let mut calls = 0;
        for _ in 0..3 {
            let outcome = run(&mut runtime, &command, || {
                calls += 1;
                Invocation::Observation("{\"value\":42}".to_owned())
            });
            assert_eq!(outcome_receipt(&outcome)["status"], "accepted");
        }
        assert_eq!(calls, 1);
        assert_eq!(runtime.counters.requests, 3);
        assert_eq!(runtime.counters.executions, 1);
        assert_eq!(runtime.counters.cache_hits, 2);
    }

    #[test]
    fn dependency_change_forces_second_execution() {
        let mut runtime = core(3, 3, 1, 8);
        let mut calls = 0;
        for dependency in ["commit-a", "commit-b"] {
            run(&mut runtime, &read_command("x", dependency), || {
                calls += 1;
                Invocation::Observation(format!("{{\"call\":{calls}}}"))
            });
        }
        assert_eq!(calls, 2);
        assert_eq!(runtime.counters.executions, 2);
    }

    #[test]
    fn invalid_observation_is_not_cached() {
        let mut runtime = core(3, 3, 1, 8);
        let command = read_command("x", "c");
        let first = run(&mut runtime, &command, || Invocation::InvalidObservation);
        assert_eq!(
            outcome_receipt(&first)["rejection"]["reason_code"],
            Reason::InvalidObservation.code()
        );
        assert_eq!(
            outcome_receipt(&first)["rejection"]["invariant_ids"],
            json!(["IBAE-REUSE-004", "IBAE-RT-005"])
        );
        let second = run(&mut runtime, &command, || {
            Invocation::Observation("{\"valid\":true}".to_owned())
        });
        assert_eq!(outcome_receipt(&second)["cache_status"], "cold_execution");
        assert_eq!(runtime.counters.cache_hits, 0);
    }

    #[test]
    fn request_limit_includes_cache_hits() {
        let mut runtime = core(2, 2, 1, 8);
        let command = read_command("x", "c");
        run(&mut runtime, &command, || {
            Invocation::Observation("1".to_owned())
        });
        run(&mut runtime, &command, || {
            panic!("cache hit must not invoke")
        });
        let rejected = run(&mut runtime, &command, || {
            panic!("budget must reject first")
        });
        assert_eq!(
            outcome_receipt(&rejected)["rejection"]["reason_code"],
            Reason::RequestBudgetExhausted.code()
        );
    }

    #[test]
    fn execution_limit_fails_before_invocation_but_consumes_request() {
        let mut runtime = core(3, 1, 1, 8);
        run(&mut runtime, &read_command("a", "c"), || {
            Invocation::Observation("1".to_owned())
        });
        let rejected = run(&mut runtime, &read_command("b", "c"), || {
            panic!("execution budget must reject first")
        });
        assert_eq!(runtime.counters.requests, 2);
        assert_eq!(runtime.counters.executions, 1);
        assert_eq!(
            outcome_receipt(&rejected)["rejection"]["reason_code"],
            Reason::ExecutionBudgetExhausted.code()
        );
    }

    #[test]
    fn retry_limit_is_exact() {
        let mut runtime = core(1, 1, 1, 1);
        let command = canonical_value(&json!({
            "admission_id": ADMISSION,
            "command_type": "record_retry",
            "protocol_version": PROTOCOL_VERSION,
        }))
        .unwrap();
        assert_eq!(
            outcome_receipt(&run(&mut runtime, &command, || Invocation::OperationFailed))["status"],
            "accepted"
        );
        let rejected = run(&mut runtime, &command, || Invocation::OperationFailed);
        assert_eq!(
            outcome_receipt(&rejected)["rejection"]["reason_code"],
            Reason::RetryBudgetExhausted.code()
        );
    }

    #[test]
    fn history_is_bounded_and_cache_cold_paths_share_transition_identity() {
        let mut runtime = core(8, 4, 1, 2);
        let first = run(&mut runtime, &read_command("a", "c"), || {
            Invocation::Observation("{\"v\":\"a\"}".to_owned())
        });
        run(&mut runtime, &read_command("b", "c"), || {
            Invocation::Observation("{\"v\":\"b\"}".to_owned())
        });
        let cached = run(&mut runtime, &read_command("a", "c"), || {
            panic!("cache hit must not invoke")
        });
        assert_eq!(runtime.history.len(), 2);
        assert_eq!(
            outcome_receipt(&first)["transition_id"],
            outcome_receipt(&cached)["transition_id"]
        );
    }

    #[test]
    fn detects_period_two_cycle() {
        let mut runtime = core(8, 4, 1, 8);
        for path in ["a", "b", "a", "b"] {
            run(&mut runtime, &read_command(path, "c"), || {
                Invocation::Observation(format!("\"{path}\""))
            });
        }
        assert_eq!(runtime.terminal_cycle_period(), Some(2));
    }

    #[test]
    fn unsupported_commands_do_not_mutate_authority_state() {
        let mut runtime = core(2, 2, 1, 2);
        let prior = runtime.state_id().unwrap();
        let command = canonical_value(&json!({
            "admission_id": ADMISSION,
            "command_type": "request_lease",
            "protocol_version": PROTOCOL_VERSION,
        }))
        .unwrap();
        let rejected = run(&mut runtime, &command, || Invocation::OperationFailed);
        assert_eq!(prior, runtime.state_id().unwrap());
        assert_eq!(
            outcome_receipt(&rejected)["rejection"]["reason_code"],
            Reason::UnsupportedCommand.code()
        );
    }

    #[test]
    fn unsupported_canonical_commands_have_distinct_bound_receipts() {
        let mut runtime = core(2, 2, 1, 2);
        let prior = runtime.state_id().unwrap();
        let mut receipts = Vec::new();
        for command_type in ["request_lease", "finalize"] {
            let command = canonical_value(&json!({
                "admission_id": ADMISSION,
                "command_type": command_type,
                "protocol_version": PROTOCOL_VERSION,
            }))
            .unwrap();
            let outcome = run(&mut runtime, &command, || Invocation::OperationFailed);
            let receipt = outcome_receipt(&outcome);
            assert_eq!(receipt["command_type"], command_type);
            assert_eq!(receipt["admission_id"], ADMISSION);
            assert!(receipt["command_id"].as_str().is_some_and(is_fingerprint));
            receipts.push(receipt);
        }
        assert_ne!(receipts[0]["command_id"], receipts[1]["command_id"]);
        assert_ne!(receipts[0]["receipt_id"], receipts[1]["receipt_id"]);
        assert_eq!(prior, runtime.state_id().unwrap());
    }

    #[test]
    fn maximum_observation_envelope_is_representable_before_commit() {
        let mut runtime = core(2, 2, 1, 2);
        let text = "x".repeat(65_500);
        let observation = canonical_value(&json!({
            "a": text,
            "b": text,
            "c": text,
            "d": text,
        }))
        .unwrap();
        assert!(observation.len() < MAX_CANONICAL_VALUE_BYTES);
        let outcome = run(&mut runtime, &read_command("large", "c"), || {
            Invocation::Observation(observation)
        });
        assert!(outcome.len() > MAX_CANONICAL_VALUE_BYTES);
        assert!(outcome.len() < MAX_RUNTIME_RECORD_BYTES);
        assert_eq!(outcome_receipt(&outcome)["status"], "accepted");
        assert_eq!(runtime.counters.requests, 1);
        assert_eq!(runtime.counters.executions, 1);
        assert_eq!(runtime.cache.len(), 1);
    }

    #[test]
    fn maximum_observation_depth_remains_representable_when_wrapped() {
        let mut runtime = core(2, 2, 1, 2);
        let mut observation = json!(0);
        for _ in 0..MAX_CANONICAL_VALUE_DEPTH {
            observation = Value::Array(vec![observation]);
        }
        let canonical = canonical_value(&observation).unwrap();
        let outcome = run(&mut runtime, &read_command("deep", "c"), || {
            Invocation::Observation(canonical)
        });
        assert_eq!(outcome_receipt(&outcome)["status"], "accepted");
        assert!(parse_runtime_canonical(&outcome).is_ok());
        assert_eq!(runtime.counters.executions, 1);
        assert_eq!(runtime.cache.len(), 1);
    }

    #[test]
    fn maximum_argument_depth_remains_representable_when_command_is_wrapped() {
        let mut runtime = core(2, 2, 1, 2);
        let mut arguments = json!(0);
        for _ in 0..MAX_CANONICAL_VALUE_DEPTH {
            arguments = Value::Array(vec![arguments]);
        }
        assert!(canonical_value(&arguments).is_ok());
        let command = canonical_runtime_value(&json!({
            "admission_id": ADMISSION,
            "arguments": arguments,
            "command_type": "execute_read",
            "dependency_fingerprint": "c",
            "protocol_version": PROTOCOL_VERSION,
            "tool_name": "read",
        }))
        .unwrap();
        let outcome = run(&mut runtime, &command, || {
            Invocation::Observation("1".to_owned())
        });
        assert_eq!(outcome_receipt(&outcome)["status"], "accepted");
        assert_eq!(runtime.counters.executions, 1);
        assert_eq!(runtime.cache.len(), 1);
    }

    #[test]
    fn maximum_declared_history_is_representable_on_cache_hit() {
        let mut runtime = core(2, 1, 1, MAX_HISTORY);
        let command = read_command("history", "c");
        let cold = run(&mut runtime, &command, || {
            Invocation::Observation("1".to_owned())
        });
        let transition_id = outcome_receipt(&cold)["transition_id"]
            .as_str()
            .unwrap()
            .to_owned();
        runtime.history = VecDeque::from(vec![transition_id; MAX_HISTORY as usize]);
        let cached = run(&mut runtime, &command, || panic!("must use cache"));
        assert_eq!(outcome_receipt(&cached)["status"], "accepted");
        assert_eq!(runtime.history.len(), MAX_HISTORY as usize);
        let snapshot = runtime.snapshot_json().unwrap();
        assert!(snapshot.len() > MAX_CANONICAL_VALUE_BYTES);
        assert!(parse_runtime_canonical(&snapshot).is_ok());
    }

    #[test]
    fn maximum_declared_cache_is_representable_in_state_identity() {
        let mut runtime = core(MAX_EXECUTIONS, MAX_EXECUTIONS, 1, 1);
        for index in 0..MAX_EXECUTIONS {
            let identity = format!("{index:064x}");
            runtime.cache.insert(
                identity.clone(),
                CachedObservation {
                    canonical: Arc::from("null"),
                    observation_id: identity,
                },
            );
        }
        runtime.counters.requests = MAX_EXECUTIONS;
        runtime.counters.executions = MAX_EXECUTIONS;
        let snapshot = runtime.snapshot_json().unwrap();
        assert!(snapshot.len() > MAX_CANONICAL_VALUE_BYTES);
        assert!(snapshot.len() < MAX_RUNTIME_RECORD_BYTES);
        assert!(parse_runtime_canonical(&snapshot).is_ok());
        assert!(is_fingerprint(&runtime.state_id().unwrap()));
    }

    #[test]
    fn state_identity_has_no_wall_clock_input() {
        let left = core(2, 2, 1, 2);
        let right = core(2, 2, 1, 2);
        assert_eq!(left.state_id().unwrap(), right.state_id().unwrap());
        assert!(!left.snapshot_json().unwrap().contains("timestamp"));
    }

    fn evidence_identity(byte: char) -> String {
        std::iter::repeat(byte).take(64).collect()
    }

    fn evidence_core(max_cases: u64, max_details: u64, fold: bool) -> EvidenceCore {
        EvidenceCore::new(
            &evidence_identity('1'),
            &evidence_identity('2'),
            &evidence_identity('3'),
            "[]",
            max_cases,
            max_details,
            fold,
        )
        .unwrap()
    }

    fn runtime_evidence_core(
        outcome: &str,
        max_cases: u64,
        cache_reuse_permitted: bool,
    ) -> EvidenceCore {
        let receipt = outcome_receipt(outcome);
        let manifest = canonical_value(&json!([{
            "action_id": receipt["admission_id"],
            "arguments_id": receipt["arguments_id"],
            "authority_class": "PURE_READ",
            "cache_reuse_permitted": cache_reuse_permitted,
            "dependency_fingerprint": receipt["dependency_fingerprint"],
            "tool_admission_receipt_id": evidence_identity('9'),
            "tool_name": receipt["tool_name"],
        }]))
        .unwrap();
        EvidenceCore::new(
            &evidence_identity('1'),
            &evidence_identity('2'),
            &evidence_identity('3'),
            &manifest,
            max_cases,
            2,
            false,
        )
        .unwrap()
    }

    fn runtime_evidence_item(outcome: &str) -> String {
        let receipt = outcome_receipt(outcome);
        let rejected = receipt["status"] == "rejected";
        let result_id = receipt["transition_id"]
            .as_str()
            .unwrap_or(receipt["resulting_state_id"].as_str().unwrap());
        let failure = if rejected {
            json!({
                "detail": {"runtime_rejection": receipt["rejection"]},
                "reason_code": receipt["rejection"]["reason_code"],
            })
        } else {
            Value::Null
        };
        canonical_value(&json!({
            "admission_id": receipt["admission_id"],
            "case_id": receipt["command_id"],
            "counters": {
                "actual_executions": receipt["budget_delta"]["executions"],
                "cache_hits": receipt["budget_delta"]["cache_hits"],
                "canonical_mismatches": 0,
                "invariant_violations": 0,
                "mutations": 0,
                "receipt_mismatches": 0,
                "requests": receipt["budget_delta"]["requests"],
                "retries": receipt["budget_delta"]["retries"],
            },
            "failure": failure,
            "input_id": receipt["command_id"],
            "item_type": "case",
            "protocol_version": EVIDENCE_PROTOCOL_VERSION,
            "receipt_id": receipt["receipt_id"],
            "result_id": result_id,
            "runtime_source": {
                "prior_state_id": receipt["prior_state_id"],
                "resulting_state_id": receipt["resulting_state_id"],
                "runtime_receipt_id": receipt["receipt_id"],
                "session_id": receipt["session_id"],
            },
            "status": if rejected { "rejected" } else { "passed" },
        }))
        .unwrap()
    }

    fn ingest_runtime_outcome(
        evidence: &mut EvidenceCore,
        outcome: &str,
    ) -> Result<(), &'static str> {
        let seal = NativeRuntimeReceiptSeal::from_outcome(outcome)
            .expect("native runtime outcomes are sealable");
        evidence.ingest_runtime(&runtime_evidence_item(outcome), &seal)
    }

    fn seal_and_finalize(evidence: &mut EvidenceCore) -> String {
        evidence.aggregate_summary().unwrap();
        evidence.finalize(&evidence_identity('4')).unwrap()
    }

    fn evidence_case(seed: u64, status: &str) -> String {
        let failure = if status == "passed" {
            Value::Null
        } else {
            json!({
                "detail": {"seed": seed},
                "reason_code": "synthetic_failure",
            })
        };
        canonical_value(&json!({
            "admission_id": format!("{:064x}", seed + 4),
            "case_id": format!("{seed:064x}"),
            "counters": {
                "actual_executions": 1,
                "cache_hits": 0,
                "canonical_mismatches": if status == "passed" { 0 } else { 1 },
                "invariant_violations": 0,
                "mutations": 0,
                "receipt_mismatches": 0,
                "requests": 1,
                "retries": 0,
            },
            "failure": failure,
            "input_id": format!("{:064x}", seed + 1),
            "item_type": "case",
            "protocol_version": EVIDENCE_PROTOCOL_VERSION,
            "receipt_id": format!("{:064x}", seed + 2),
            "result_id": format!("{:064x}", seed + 3),
            "runtime_source": null,
            "status": status,
        }))
        .unwrap()
    }

    #[test]
    fn compact_evidence_success_state_and_receipt_remain_bounded() {
        let mut one = evidence_core(MAX_EVIDENCE_CASES, 8, true);
        one.ingest_structural(&evidence_case(1, "passed")).unwrap();
        let one_receipt = seal_and_finalize(&mut one);

        let mut many = evidence_core(MAX_EVIDENCE_CASES, 8, true);
        for seed in 1..=50_000 {
            many.ingest_structural(&evidence_case(seed, "passed"))
                .unwrap();
        }
        let many_receipt = seal_and_finalize(&mut many);
        assert!(one_receipt.len() <= MAX_COMPACT_EVIDENCE_BYTES);
        assert!(many_receipt.len() <= MAX_COMPACT_EVIDENCE_BYTES);
        assert!(many.failure_details.is_empty());
        assert_eq!(many.case_counts.total, 50_000);
        assert_eq!(many.case_counts.passed, 50_000);
        assert!(!many_receipt.contains("synthetic_failure"));
    }

    #[test]
    fn compact_evidence_ceiling_covers_maximum_decimal_counter_width() {
        let mut evidence = evidence_core(MAX_EVIDENCE_CASES, MAX_EVIDENCE_FAILURE_DETAILS, true);
        evidence.case_counts = EvidenceCaseCounts {
            total: MAX_EVIDENCE_CASES,
            passed: MAX_EVIDENCE_CASES,
            failed: 0,
            rejected: 0,
        };
        evidence.case_records = MAX_EVIDENCE_CASES;
        evidence.counters = EvidenceCounters {
            requests: u64::MAX,
            actual_executions: u64::MAX,
            cache_hits: u64::MAX,
            retries: u64::MAX,
            mutations: u64::MAX,
            invariant_violations: 0,
            canonical_mismatches: 0,
            receipt_mismatches: 0,
        };
        let receipt = seal_and_finalize(&mut evidence);
        assert!(receipt.len() <= MAX_COMPACT_EVIDENCE_BYTES);
        assert_eq!(
            parse_canonical(&receipt).unwrap()["counter_totals"]["requests"],
            u64::MAX
        );
    }

    #[test]
    fn empty_evidence_cannot_seal_and_sealing_prevents_late_ingestion() {
        let mut empty = evidence_core(1, 1, false);
        assert!(empty.aggregate_summary().is_err());
        assert!(empty.finalize(&evidence_identity('4')).is_err());

        empty
            .ingest_structural(&evidence_case(1, "passed"))
            .unwrap();
        let summary = empty.aggregate_summary().unwrap();
        assert!(parse_canonical(&summary).unwrap()["summary_id"]
            .as_str()
            .is_some_and(is_fingerprint));
        assert!(empty
            .ingest_structural(&evidence_case(2, "passed"))
            .is_err());
        assert!(empty.finalize(&evidence_identity('4')).is_ok());
        assert!(empty.finalize(&evidence_identity('5')).is_err());
    }

    #[test]
    fn compact_evidence_order_is_identity_bearing() {
        let first = evidence_case(1, "passed");
        let second = evidence_case(10, "passed");
        let mut left = evidence_core(2, 1, false);
        left.ingest_structural(&first).unwrap();
        left.ingest_structural(&second).unwrap();
        let left = parse_canonical(&seal_and_finalize(&mut left)).unwrap();
        let mut right = evidence_core(2, 1, false);
        right.ingest_structural(&second).unwrap();
        right.ingest_structural(&first).unwrap();
        let right = parse_canonical(&seal_and_finalize(&mut right)).unwrap();
        assert_ne!(left["aggregate_identities"], right["aggregate_identities"]);
        assert_ne!(left["receipt_id"], right["receipt_id"]);
    }

    #[test]
    fn compact_evidence_admission_is_atomic_on_overflow_and_malformed_input() {
        let valid = evidence_case(1, "passed");
        let mut overflow = evidence_core(2, 1, false);
        overflow.counters.requests = u64::MAX;
        let before = overflow.aggregate_input_identity.clone();
        assert!(overflow.ingest_structural(&valid).is_err());
        assert_eq!(overflow.case_counts.total, 0);
        assert_eq!(overflow.aggregate_input_identity, before);

        let mut malformed_then_valid = evidence_core(1, 1, false);
        assert!(malformed_then_valid
            .ingest_structural("{\"unknown\":true}")
            .is_err());
        malformed_then_valid.ingest_structural(&valid).unwrap();
        let recovered = seal_and_finalize(&mut malformed_then_valid);
        let mut clean = evidence_core(1, 1, false);
        clean.ingest_structural(&valid).unwrap();
        assert_eq!(recovered, seal_and_finalize(&mut clean));
    }

    #[test]
    fn sealed_runtime_retry_is_counted_and_preserves_continuity() {
        let dependency = evidence_identity('d');
        let command = read_command("retry", &dependency);
        let retry_command = canonical_value(&json!({
            "admission_id": ADMISSION,
            "command_type": "record_retry",
            "protocol_version": PROTOCOL_VERSION,
        }))
        .unwrap();
        let mut runtime = core(3, 2, 2, 8);
        let first = run(&mut runtime, &command, || {
            Invocation::Observation("1".to_owned())
        });
        let retry = run(&mut runtime, &retry_command, || Invocation::OperationFailed);
        let cached = run(&mut runtime, &command, || {
            panic!("cache reuse must not invoke the operation")
        });
        let mut evidence = runtime_evidence_core(&first, 3, true);
        ingest_runtime_outcome(&mut evidence, &first).unwrap();
        ingest_runtime_outcome(&mut evidence, &retry).unwrap();
        ingest_runtime_outcome(&mut evidence, &cached).unwrap();
        let receipt = parse_canonical(&seal_and_finalize(&mut evidence)).unwrap();
        assert!(evidence.all_sources_bound);
        assert_eq!(receipt["case_counts"]["total"], 3);
        assert_eq!(receipt["counter_totals"]["requests"], 2);
        assert_eq!(receipt["counter_totals"]["actual_executions"], 1);
        assert_eq!(receipt["counter_totals"]["cache_hits"], 1);
        assert_eq!(receipt["counter_totals"]["retries"], 1);
        assert_eq!(
            receipt["runtime_boundary"]["first_runtime_receipt_id"],
            outcome_receipt(&first)["receipt_id"]
        );
        assert_eq!(
            receipt["runtime_boundary"]["last_runtime_receipt_id"],
            outcome_receipt(&cached)["receipt_id"]
        );
    }

    #[test]
    fn retry_alone_cannot_cover_manifest_and_unknown_retry_is_atomic() {
        let dependency = evidence_identity('d');
        let command = read_command("retry-coverage", &dependency);
        let mut runtime = core(2, 2, 2, 8);
        let first = run(&mut runtime, &command, || {
            Invocation::Observation("1".to_owned())
        });
        let retry_command = canonical_value(&json!({
            "admission_id": ADMISSION,
            "command_type": "record_retry",
            "protocol_version": PROTOCOL_VERSION,
        }))
        .unwrap();
        let retry = run(&mut runtime, &retry_command, || Invocation::OperationFailed);
        let mut retry_only = runtime_evidence_core(&first, 1, true);
        ingest_runtime_outcome(&mut retry_only, &retry).unwrap();
        assert!(retry_only.aggregate_summary().is_err());

        let unknown_command = canonical_value(&json!({
            "admission_id": evidence_identity('b'),
            "command_type": "record_retry",
            "protocol_version": PROTOCOL_VERSION,
        }))
        .unwrap();
        let unknown = run(&mut runtime, &unknown_command, || {
            Invocation::OperationFailed
        });
        let mut guarded = runtime_evidence_core(&first, 2, true);
        ingest_runtime_outcome(&mut guarded, &first).unwrap();
        let prior_root = guarded.aggregate_receipt_identity.clone();
        assert!(ingest_runtime_outcome(&mut guarded, &unknown).is_err());
        assert_eq!(guarded.case_counts.total, 1);
        assert_eq!(guarded.aggregate_receipt_identity, prior_root);
    }

    #[test]
    fn cache_hit_requires_manifest_reuse_permission() {
        let dependency = evidence_identity('d');
        let command = read_command("cache-policy", &dependency);
        let mut runtime = core(2, 2, 1, 8);
        let first = run(&mut runtime, &command, || {
            Invocation::Observation("1".to_owned())
        });
        let cached = run(&mut runtime, &command, || {
            panic!("cache reuse must not invoke the operation")
        });
        let mut evidence = runtime_evidence_core(&first, 2, false);
        ingest_runtime_outcome(&mut evidence, &first).unwrap();
        let prior_root = evidence.aggregate_receipt_identity.clone();
        assert!(ingest_runtime_outcome(&mut evidence, &cached).is_err());
        assert_eq!(evidence.case_counts.total, 1);
        assert_eq!(evidence.aggregate_receipt_identity, prior_root);
    }

    #[test]
    fn cache_hit_requires_prior_cold_execution_for_same_admission() {
        let dependency = evidence_identity('d');
        let first_command = read_command("same", &dependency);
        let second_admission = evidence_identity('b');
        let second_command = canonical_value(&json!({
            "admission_id": second_admission,
            "arguments": {"path": "same"},
            "command_type": "execute_read",
            "dependency_fingerprint": dependency,
            "protocol_version": PROTOCOL_VERSION,
            "tool_name": "read",
        }))
        .unwrap();
        let mut stale_runtime = core(2, 2, 1, 8);
        run(&mut stale_runtime, &first_command, || {
            Invocation::Observation("1".to_owned())
        });
        let first_seen_hit = run(&mut stale_runtime, &second_command, || {
            panic!("the v0.3 cache reuses the earlier semantic read")
        });
        assert_eq!(
            outcome_receipt(&first_seen_hit)["cache_status"],
            "cache_hit"
        );
        let mut evidence = runtime_evidence_core(&first_seen_hit, 1, true);
        let prior_root = evidence.aggregate_receipt_identity.clone();
        assert!(ingest_runtime_outcome(&mut evidence, &first_seen_hit).is_err());
        assert_eq!(evidence.case_counts.total, 0);
        assert_eq!(evidence.aggregate_receipt_identity, prior_root);

        let mut clean_runtime = core(1, 1, 1, 8);
        let cold = run(&mut clean_runtime, &second_command, || {
            Invocation::Observation("2".to_owned())
        });
        ingest_runtime_outcome(&mut evidence, &cold).unwrap();
        assert!(evidence.aggregate_summary().is_ok());
    }

    #[test]
    fn failure_expansion_is_bounded_and_bound_to_parent() {
        let mut evidence = evidence_core(8, 2, false);
        evidence
            .ingest_structural(&evidence_case(1, "passed"))
            .unwrap();
        for seed in 2..=6 {
            evidence
                .ingest_structural(&evidence_case(seed, "failed"))
                .unwrap();
        }
        let receipt = parse_canonical(&seal_and_finalize(&mut evidence)).unwrap();
        assert_eq!(receipt["failure_summary"]["count"], 5);
        assert_eq!(receipt["failure_summary"]["first_index"], 1);
        assert_eq!(receipt["failure_summary"]["details_available"], 2);
        assert_eq!(receipt["failure_summary"]["details_truncated"], true);
        let receipt_id = receipt["receipt_id"].as_str().unwrap();
        let request = canonical_value(&json!({
            "evidence_receipt_id": receipt_id,
            "max_details": 2,
            "protocol_version": EVIDENCE_PROTOCOL_VERSION,
            "start_case_index": 0,
        }))
        .unwrap();
        let expansion = parse_canonical(&evidence.expand(&request).unwrap()).unwrap();
        assert_eq!(expansion["details"].as_array().unwrap().len(), 2);
        assert!(expansion["details"]
            .as_array()
            .unwrap()
            .iter()
            .all(|detail| detail["status"] != "passed"));
        let wrong_parent = request.replace(receipt_id, &evidence_identity('a'));
        assert!(evidence.expand(&wrong_parent).is_err());
        assert_eq!(
            evidence.finalize(&evidence_identity('4')).unwrap(),
            canonical_value(&receipt).unwrap()
        );
    }

    #[test]
    fn validated_child_receipts_compose_counts_but_not_execution_identity() {
        let mut child = evidence_core(2, 1, true);
        child
            .ingest_structural(&evidence_case(1, "passed"))
            .unwrap();
        child
            .ingest_structural(&evidence_case(2, "passed"))
            .unwrap();
        let child_receipt = parse_canonical(&seal_and_finalize(&mut child)).unwrap();
        let child_receipt_text = canonical_value(&child_receipt).unwrap();
        let child_receipt_id = child_receipt["receipt_id"].as_str().unwrap().to_owned();
        let child_aggregate_admission_identity = child_receipt["aggregate_identities"]
            ["admissions"]
            .as_str()
            .unwrap()
            .to_owned();
        let child_aggregate_input_identity = child_receipt["aggregate_identities"]["inputs"]
            .as_str()
            .unwrap()
            .to_owned();
        let child_aggregate_receipt_identity = child_receipt["aggregate_identities"]["receipts"]
            .as_str()
            .unwrap()
            .to_owned();
        let child_aggregate_result_identity = child_receipt["aggregate_identities"]["results"]
            .as_str()
            .unwrap()
            .to_owned();
        let expected_parent_admission_aggregate = evidence_chain_update(
            EVIDENCE_ADMISSION_DOMAIN,
            &evidence_chain_seed(EVIDENCE_ADMISSION_DOMAIN),
            0,
            "child_receipt",
            &child_aggregate_admission_identity,
        )
        .unwrap();
        let expected_parent_input_aggregate = evidence_chain_update(
            EVIDENCE_INPUT_DOMAIN,
            &evidence_chain_seed(EVIDENCE_INPUT_DOMAIN),
            0,
            "child_receipt",
            &child_aggregate_input_identity,
        )
        .unwrap();
        let expected_parent_receipt_aggregate = evidence_chain_update(
            EVIDENCE_CASE_RECEIPT_DOMAIN,
            &evidence_chain_seed(EVIDENCE_CASE_RECEIPT_DOMAIN),
            0,
            "child_receipt",
            &child_aggregate_receipt_identity,
        )
        .unwrap();
        let transport_receipt_aggregate = evidence_chain_update(
            EVIDENCE_CASE_RECEIPT_DOMAIN,
            &evidence_chain_seed(EVIDENCE_CASE_RECEIPT_DOMAIN),
            0,
            "child_receipt",
            &child_receipt_id,
        )
        .unwrap();
        let expected_parent_result_aggregate = evidence_chain_update(
            EVIDENCE_RESULT_DOMAIN,
            &evidence_chain_seed(EVIDENCE_RESULT_DOMAIN),
            0,
            "child_receipt",
            &child_aggregate_result_identity,
        )
        .unwrap();
        let child_item = canonical_value(&json!({
            "item_type": "child_receipt",
            "protocol_version": EVIDENCE_PROTOCOL_VERSION,
            "receipt": child_receipt,
        }))
        .unwrap();
        let child_seal = NativeEvidenceReceiptSeal {
            canonical: Arc::from(child_receipt_text.as_str()),
            receipt_id: child_receipt_id,
            source_bound: true,
        };
        let mut parent = evidence_core(2, 1, false);
        parent.ingest_child(&child_item, &child_seal).unwrap();
        let parent = parse_canonical(&seal_and_finalize(&mut parent)).unwrap();
        assert_eq!(parent["case_counts"]["total"], 2);
        assert_eq!(parent["item_counts"]["child_receipts"], 1);
        assert_eq!(
            parent["aggregate_identities"]["admissions"],
            expected_parent_admission_aggregate
        );
        assert_eq!(
            parent["aggregate_identities"]["inputs"],
            expected_parent_input_aggregate
        );
        assert_eq!(
            parent["aggregate_identities"]["receipts"],
            expected_parent_receipt_aggregate
        );
        assert_eq!(
            parent["aggregate_identities"]["results"],
            expected_parent_result_aggregate
        );
        assert_ne!(
            parent["aggregate_identities"]["receipts"],
            transport_receipt_aggregate
        );
        assert_eq!(
            parent["bound_identities"]["execution"],
            evidence_identity('4')
        );
        assert_ne!(
            parent["receipt_id"],
            parent["bound_identities"]["execution"]
        );
    }

    #[test]
    fn fast_fold_cannot_substitute_for_sha256_receipt_identity() {
        let case = evidence_case(1, "passed");
        let mut with_fold = evidence_core(1, 1, true);
        with_fold.ingest_structural(&case).unwrap();
        let with_fold_receipt = seal_and_finalize(&mut with_fold);
        let observation =
            parse_canonical(&with_fold.fast_regression_observation().unwrap()).unwrap();
        assert_eq!(observation["correctness_authority"], false);
        let fold = observation["value"].as_str().unwrap().to_owned();

        let mut without_fold = evidence_core(1, 1, false);
        without_fold.ingest_structural(&case).unwrap();
        assert_eq!(with_fold_receipt, seal_and_finalize(&mut without_fold));

        let mut receipt = parse_canonical(&with_fold_receipt).unwrap();
        receipt["receipt_id"] = Value::String(fold.repeat(4));
        assert!(parse_child_receipt(&receipt).is_err());
    }
}
