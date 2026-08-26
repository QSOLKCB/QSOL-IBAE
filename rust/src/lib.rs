//! Exact, bounded, deterministic execution authority for QSOL-IBAE v0.3.
//!
//! The crate deliberately exposes one command dispatcher rather than leaking
//! implementation helpers across the Python/Rust boundary. It has no network,
//! model-provider, async-runtime, or wall-clock integration.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyModule};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, VecDeque};

const PROTOCOL_VERSION: &str = "IBAE-RUNTIME-PROTOCOL-V1";
const COMMAND_DOMAIN: &str = "ibae.runtime-command-id.v1";
const RECEIPT_DOMAIN: &str = "ibae.runtime-receipt-id.v1";
const SESSION_DOMAIN: &str = "ibae.runtime-session-id.v1";
const STATE_DOMAIN: &str = "ibae.runtime-state-id.v1";

const MAX_CANONICAL_VALUE_BYTES: usize = 262_144;
const MAX_CANONICAL_VALUE_DEPTH: usize = 32;
const MAX_CANONICAL_VALUE_NODES: usize = 4_096;
const MAX_CANONICAL_COLLECTION_ITEMS: usize = 1_024;
const MAX_CANONICAL_STRING_BYTES: usize = 65_536;
const MAX_RECORD_TEXT_BYTES: usize = 4_096;
const MAX_INTEGER_DECIMAL: &str =
    "115792089237316195423570985008687907853269984665640564039457584007913129639935";

const MAX_REQUESTS: u64 = 1_000_000;
const MAX_EXECUTIONS: u64 = 4_096;
const MAX_RETRIES: u64 = 1_000_000;
const MAX_HISTORY: u64 = 4_096;

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
            Self::InvalidCanonicalCommand | Self::InvalidCommand => {
                &["IBAE-RT-002", "IBAE-RT-005"]
            }
            Self::UnsupportedCommand | Self::ProtocolVersionMismatch => &["IBAE-RT-002"],
            Self::RequestBudgetExhausted => &["IBAE-BND-001", "IBAE-CLK-004"],
            Self::ExecutionBudgetExhausted => &["IBAE-BND-002", "IBAE-DET-003"],
            Self::RetryBudgetExhausted => &["IBAE-BND-003"],
            Self::ArithmeticOverflow => &["IBAE-BND-007", "IBAE-CLK-001"],
            Self::InvalidObservation => &["IBAE-CCH-004", "IBAE-RT-005"],
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
) -> Result<String, CanonicalError> {
    if depth > MAX_CANONICAL_VALUE_DEPTH {
        return Err(CanonicalError);
    }
    stats.nodes = stats.nodes.checked_add(1).ok_or(CanonicalError)?;
    if stats.nodes > MAX_CANONICAL_VALUE_NODES {
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
            if items.len() > MAX_CANONICAL_COLLECTION_ITEMS {
                return Err(CanonicalError);
            }
            let mut output = String::from("[");
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                output.push_str(&render_canonical(item, depth + 1, stats)?);
            }
            output.push(']');
            Ok(output)
        }
        Value::Object(mapping) => {
            if mapping.len() > MAX_CANONICAL_COLLECTION_ITEMS {
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
                output.push_str(&render_canonical(nested, depth + 1, stats)?);
            }
            output.push('}');
            Ok(output)
        }
    }
}

fn canonical_value(value: &Value) -> Result<String, CanonicalError> {
    let mut stats = CanonicalStats::default();
    let output = render_canonical(value, 0, &mut stats)?;
    if output.len() > MAX_CANONICAL_VALUE_BYTES {
        return Err(CanonicalError);
    }
    Ok(output)
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
    canonical: String,
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

fn parse_command(command_json: &str) -> Result<(Command, Value), Reason> {
    let value = parse_canonical(command_json).map_err(|_| Reason::InvalidCanonicalCommand)?;
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
            let arguments = mapping.get("arguments").cloned().ok_or(Reason::InvalidCommand)?;
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
            Ok((
                Command::ExecuteRead(ExecuteRead {
                    admission_id,
                    arguments_canonical,
                    dependency_fingerprint,
                    tool_name,
                }),
                value,
            ))
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
            Ok((Command::RecordRetry(RecordRetry { admission_id }), value))
        }
        _ => Err(Reason::UnsupportedCommand),
    }
}

enum Invocation {
    Observation(String),
    InvalidObservation,
    OperationFailed,
}

fn parse_invocation_envelope(envelope: &str) -> Invocation {
    let Ok(value) = parse_canonical(envelope) else {
        return Invocation::InvalidObservation;
    };
    let Some(mapping) = value.as_object() else {
        return Invocation::InvalidObservation;
    };
    match mapping.get("status").and_then(Value::as_str) {
        Some("ok")
            if object_has_exact_keys(mapping, &["observation", "status"]) =>
        {
            let Some(observation) = mapping.get("observation") else {
                return Invocation::InvalidObservation;
            };
            match canonical_value(observation) {
                Ok(canonical) => Invocation::Observation(canonical),
                Err(_) => Invocation::InvalidObservation,
            }
        }
        Some("rejected")
            if object_has_exact_keys(mapping, &["reason_code", "status"]) =>
        {
            match mapping.get("reason_code").and_then(Value::as_str) {
                Some("invalid_observation") => Invocation::InvalidObservation,
                Some("operation_failed") => Invocation::OperationFailed,
                _ => Invocation::InvalidObservation,
            }
        }
        _ => Invocation::InvalidObservation,
    }
}

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

    fn state_id(&self) -> String {
        let canonical = canonical_value(&self.state_record())
            .expect("the internally constructed state record is canonicalizable");
        domain_fingerprint(STATE_DOMAIN, &canonical)
    }

    fn snapshot_value(&self) -> Value {
        let mut value = self.state_record();
        value
            .as_object_mut()
            .expect("state record is an object")
            .insert("state_id".to_owned(), Value::String(self.state_id()));
        value
    }

    fn snapshot_json(&self) -> String {
        canonical_value(&self.snapshot_value())
            .expect("the internally constructed snapshot is canonicalizable")
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

    fn command_id(&self, command: &Value, prior_state_id: &str) -> String {
        let record = json!({
            "command": command,
            "prior_state_id": prior_state_id,
            "session_id": self.session_id,
        });
        let canonical = canonical_value(&record)
            .expect("a validated command identity record is canonicalizable");
        domain_fingerprint(COMMAND_DOMAIN, &canonical)
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
    ) -> String {
        let resulting_state_id = self.state_id();
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
        let receipt_canonical = canonical_value(&receipt_without_id)
            .expect("the internally constructed receipt is canonicalizable");
        let receipt_id = domain_fingerprint(RECEIPT_DOMAIN, &receipt_canonical);
        let mut receipt = receipt_without_id;
        receipt
            .as_object_mut()
            .expect("receipt is an object")
            .insert("receipt_id".to_owned(), Value::String(receipt_id));

        let observation_value = observation
            .and_then(|canonical| parse_canonical(canonical).ok())
            .unwrap_or(Value::Null);
        canonical_value(&json!({
            "observation": observation_value,
            "receipt": receipt,
        }))
        .expect("the internally constructed outcome is canonicalizable")
    }

    fn rejected_unparsed(&self, before: Counters, prior_state_id: String, reason: Reason) -> String {
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

    fn dispatch<F>(&mut self, command_json: &str, invoke: F) -> String
    where
        F: FnOnce() -> Invocation,
    {
        let before = self.counters;
        let prior_state_id = self.state_id();
        let (command, command_value) = match parse_command(command_json) {
            Ok(parsed) => parsed,
            Err(reason) => return self.rejected_unparsed(before, prior_state_id, reason),
        };
        let command_id = self.command_id(&command_value, &prior_state_id);

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
                            Some(&cached.canonical)
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
                    canonical: observation.clone(),
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

fn exact_u64(
    value: Option<&Bound<'_, PyAny>>,
    default: u64,
    name: &str,
) -> PyResult<u64> {
    let Some(value) = value else {
        return Ok(default);
    };
    if value.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(format!(
            "{name} must be an exact positive integer"
        )));
    }
    value.extract::<u64>().map_err(|_| {
        PyValueError::new_err(format!("{name} must be an exact positive integer"))
    })
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
    ) -> String {
        self.core.dispatch(command_json, || {
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
    }

    fn snapshot(&self) -> String {
        self.core.snapshot_json()
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
    module.add_function(wrap_pyfunction!(canonicalize_json, module)?)?;
    module.add("PROTOCOL_VERSION", PROTOCOL_VERSION)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const ADMISSION: &str =
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

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
        parse_canonical(outcome).unwrap()["receipt"].clone()
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
            let outcome = runtime.dispatch(&command, || {
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
            runtime.dispatch(&read_command("x", dependency), || {
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
        let first = runtime.dispatch(&command, || Invocation::InvalidObservation);
        assert_eq!(
            outcome_receipt(&first)["rejection"]["reason_code"],
            Reason::InvalidObservation.code()
        );
        let second = runtime.dispatch(&command, || {
            Invocation::Observation("{\"valid\":true}".to_owned())
        });
        assert_eq!(outcome_receipt(&second)["cache_status"], "cold_execution");
        assert_eq!(runtime.counters.cache_hits, 0);
    }

    #[test]
    fn request_limit_includes_cache_hits() {
        let mut runtime = core(2, 2, 1, 8);
        let command = read_command("x", "c");
        runtime.dispatch(&command, || Invocation::Observation("1".to_owned()));
        runtime.dispatch(&command, || panic!("cache hit must not invoke"));
        let rejected = runtime.dispatch(&command, || panic!("budget must reject first"));
        assert_eq!(
            outcome_receipt(&rejected)["rejection"]["reason_code"],
            Reason::RequestBudgetExhausted.code()
        );
    }

    #[test]
    fn execution_limit_fails_before_invocation_but_consumes_request() {
        let mut runtime = core(3, 1, 1, 8);
        runtime.dispatch(&read_command("a", "c"), || {
            Invocation::Observation("1".to_owned())
        });
        let rejected = runtime.dispatch(&read_command("b", "c"), || {
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
            outcome_receipt(&runtime.dispatch(&command, || Invocation::OperationFailed))["status"],
            "accepted"
        );
        let rejected = runtime.dispatch(&command, || Invocation::OperationFailed);
        assert_eq!(
            outcome_receipt(&rejected)["rejection"]["reason_code"],
            Reason::RetryBudgetExhausted.code()
        );
    }

    #[test]
    fn history_is_bounded_and_cache_cold_paths_share_transition_identity() {
        let mut runtime = core(8, 4, 1, 2);
        let first = runtime.dispatch(&read_command("a", "c"), || {
            Invocation::Observation("{\"v\":\"a\"}".to_owned())
        });
        runtime.dispatch(&read_command("b", "c"), || {
            Invocation::Observation("{\"v\":\"b\"}".to_owned())
        });
        let cached = runtime.dispatch(&read_command("a", "c"), || {
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
            runtime.dispatch(&read_command(path, "c"), || {
                Invocation::Observation(format!("\"{path}\""))
            });
        }
        assert_eq!(runtime.terminal_cycle_period(), Some(2));
    }

    #[test]
    fn unsupported_commands_do_not_mutate_authority_state() {
        let mut runtime = core(2, 2, 1, 2);
        let prior = runtime.state_id();
        let command = canonical_value(&json!({
            "admission_id": ADMISSION,
            "command_type": "request_lease",
            "protocol_version": PROTOCOL_VERSION,
        }))
        .unwrap();
        let rejected = runtime.dispatch(&command, || Invocation::OperationFailed);
        assert_eq!(prior, runtime.state_id());
        assert_eq!(
            outcome_receipt(&rejected)["rejection"]["reason_code"],
            Reason::UnsupportedCommand.code()
        );
    }

    #[test]
    fn state_identity_has_no_wall_clock_input() {
        let left = core(2, 2, 1, 2);
        let right = core(2, 2, 1, 2);
        assert_eq!(left.state_id(), right.state_id());
        assert!(!left.snapshot_json().contains("timestamp"));
    }
}
