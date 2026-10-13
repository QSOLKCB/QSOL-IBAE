//! v0.6D closed synthetic effects.  This is deliberately separate from the
//! read runtime and its continuation lease/resource/receipt schemas.
//!
//! No Python callback, filesystem, network, credential, or arbitrary executor
//! is accepted. The original task commits the entire bounded profile. Native
//! per-instance approvals and an occurrence journal establish in-process
//! provenance only, never human approval, durable resume, or external truth.

use super::*;
use std::cell::Cell;

pub(super) const VERSION: &str = "IBAE-EFFECT-RUNTIME-V1";
const PROFILE_VERSION: &str = "IBAE-EFFECT-PROFILE-V1";
const MAX_ENTRIES: usize = 64;
const MAX_OUTCOMES: usize = 16;
const MAX_EFFECT_RECORD_BYTES: usize = 1_048_576;
type Result<T> = std::result::Result<T, &'static str>;

fn object<'a>(value: &'a Value, keys: &[&str]) -> Result<&'a Map<String, Value>> {
    let mapping = value.as_object().ok_or("effect record must be an object")?;
    if !object_has_exact_keys(mapping, keys) {
        return Err("effect record has unknown or missing fields");
    }
    Ok(mapping)
}
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or("effect field must be text")
}
fn symbol(value: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 128
        || !value.as_bytes()[0].is_ascii_lowercase()
        || !value
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"._:/-".contains(&c))
    {
        return Err("effect symbol is invalid or exceeds its bound");
    }
    Ok(())
}
fn fingerprint(value: &Value, key: &str) -> Result<String> {
    let value = text(value, key)?;
    if !is_fingerprint(value) {
        return Err("effect identity must be a SHA-256 fingerprint");
    }
    Ok(value.to_owned())
}
fn canonical(value: &Value) -> Result<String> {
    let encoded =
        canonical_runtime_value(value).map_err(|_| "effect record exceeds canonical bounds")?;
    if encoded.len() > MAX_EFFECT_RECORD_BYTES {
        return Err("effect record exceeds the one-MiB profile bound");
    }
    Ok(encoded)
}
fn parse_effect_canonical(input: &str) -> Result<Value> {
    if input.len() > MAX_EFFECT_RECORD_BYTES {
        return Err("effect record exceeds the one-MiB profile bound");
    }
    parse_runtime_canonical(input).map_err(|_| "effect record must be bounded canonical JSON")
}
fn identity(domain: &str, value: &Value) -> Result<String> {
    Ok(domain_fingerprint(domain, &canonical(value)?))
}
fn selected(value: &Value, fields: &[&str]) -> Value {
    Value::Object(
        fields
            .iter()
            .map(|key| ((*key).to_owned(), value[*key].clone()))
            .collect(),
    )
}
fn signed(value: &Value, key: &str) -> Result<i64> {
    value
        .get(key)
        .and_then(Value::as_i64)
        .ok_or("effect integer must be signed 64-bit")
}
fn eq_text(value: &Value, key: &str, expected: &str) -> Result<()> {
    if text(value, key)? != expected {
        return Err("effect record has inconsistent authority or identity");
    }
    Ok(())
}
fn receipt(value: &Value, domain: &str) -> Result<()> {
    let mut body = value
        .as_object()
        .ok_or("effect receipt must be an object")?
        .clone();
    let claimed = body
        .remove("receipt_id")
        .ok_or("effect receipt identity is missing")?;
    if claimed != Value::String(identity(domain, &Value::Object(body))?) {
        return Err("effect receipt identity is invalid");
    }
    Ok(())
}
fn sorted_symbols(value: &Value) -> Result<Vec<String>> {
    let items = value
        .as_array()
        .ok_or("effect declaration must be an array")?;
    if items.len() > 128 {
        return Err("effect declaration exceeds its bound");
    }
    let mut result = Vec::new();
    for item in items {
        let item = item
            .as_str()
            .ok_or("effect declaration must contain strings")?;
        symbol(item)?;
        if result
            .last()
            .is_some_and(|prior: &String| prior.as_str() >= item)
        {
            return Err("effect declaration must be sorted and unique");
        }
        result.push(item.to_owned());
    }
    Ok(result)
}

#[derive(Clone, Copy, Debug, Default)]
struct Counters {
    requests: u64,
    executions: u64,
    retries: u64,
    reconciliations: u64,
}
impl Counters {
    fn value(self) -> Value {
        json!({"requests":self.requests,"executions":self.executions,"retries":self.retries,"reconciliations":self.reconciliations})
    }
}
#[derive(Clone, Copy, Debug)]
struct EffectLimits {
    requests: u64,
    executions: u64,
    retries: u64,
    reconciliations: u64,
}
impl EffectLimits {
    fn parse(value: &Value) -> Result<Self> {
        object(
            value,
            &[
                "max_requests",
                "max_executions",
                "max_retries",
                "max_reconciliations",
            ],
        )?;
        let get = |key: &str, cap: u64, positive: bool| {
            let v = value[key]
                .as_u64()
                .ok_or("effect limit must be an exact unsigned integer")?;
            if v > cap || (positive && v == 0) {
                return Err("effect limit is outside its finite hard bound");
            }
            Ok(v)
        };
        Ok(Self {
            requests: get("max_requests", 4096, true)?,
            executions: get("max_executions", 1024, true)?,
            retries: get("max_retries", 1024, false)?,
            reconciliations: get("max_reconciliations", 1024, false)?,
        })
    }
    fn value(self) -> Value {
        json!({"max_requests":self.requests,"max_executions":self.executions,"max_retries":self.retries,"max_reconciliations":self.reconciliations})
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Operation {
    Set,
    Increment,
}
impl Operation {
    fn parse(name: &str) -> Result<Self> {
        match name {
            "synthetic_set" => Ok(Self::Set),
            "synthetic_increment" => Ok(Self::Increment),
            _ => Err("only closed synthetic effect tools are supported"),
        }
    }
    fn class(self) -> &'static str {
        match self {
            Self::Set => "idempotent_mutation",
            Self::Increment => "non_idempotent_mutation",
        }
    }
    fn keys(self) -> &'static [&'static str] {
        match self {
            Self::Set => &["expected_value", "key", "value"],
            Self::Increment => &["delta", "expected_value", "key"],
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Scenario {
    Success,
    FailBefore,
    CrashAfter,
    CrashBefore,
    Unknown,
}
impl Scenario {
    fn parse(value: &Value) -> Result<Self> {
        match value.as_str() {
            Some("success") => Ok(Self::Success),
            Some("fail_before") => Ok(Self::FailBefore),
            Some("crash_after") => Ok(Self::CrashAfter),
            Some("crash_before") => Ok(Self::CrashBefore),
            Some("ambiguous_unknown") => Ok(Self::Unknown),
            _ => Err("unknown synthetic effect outcome"),
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Status {
    Pending,
    NotApplied,
    Applied,
    Ambiguous,
    Cancelled,
    ReconciledApplied,
    ReconciledNotApplied,
}
impl Status {
    fn code(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::NotApplied => "not_applied",
            Self::Applied => "applied",
            Self::Ambiguous => "ambiguous",
            Self::Cancelled => "cancelled",
            Self::ReconciledApplied => "reconciled_applied",
            Self::ReconciledNotApplied => "reconciled_not_applied",
        }
    }
    fn completed(self) -> bool {
        matches!(
            self,
            Self::Applied | Self::Cancelled | Self::ReconciledApplied
        )
    }
}
#[derive(Clone, Copy, Debug)]
enum Witness {
    None,
    NotApplied(i64),
    Applied(i64),
    Unknown,
}
#[derive(Clone, Debug)]
struct Entry {
    action_id: String,
    occurrence: String,
    admission_id: String,
    arguments_id: String,
    operation: Operation,
    key: String,
    operand: i64,
    expected: i64,
    outcomes: Vec<Scenario>,
    status: Status,
    attempts: u64,
    cancel_requested: bool,
    last_event_id: Option<String>,
    witness: Witness,
}

impl Entry {
    fn sequence_terminal(&self) -> bool {
        self.status.completed()
            || (self.cancel_requested && self.status == Status::ReconciledNotApplied)
    }
}

/// Verify the *existing* governance and v0.2 identities independently. This
/// does not turn hash consistency into issuance: only the original native
/// task binding and its non-constructible supervisor capability can attach it.
fn parse_entry(
    value: &Value,
    admission: &Value,
    policy: &Value,
    task_id: &str,
    governance_id: &str,
    governance_receipt_id: &str,
) -> Result<Entry> {
    object(
        value,
        &[
            "capability",
            "proposal",
            "admission_decision",
            "dependency_state_id",
            "outcomes",
        ],
    )?;
    let cap = &value["capability"];
    let prop = &value["proposal"];
    let decision = &value["admission_decision"];
    object(
        cap,
        &[
            "argument_schema",
            "available",
            "capability_id",
            "contract_version",
            "description",
            "name",
            "replay_evidence_id",
            "replay_safety",
            "required_state_keys",
            "semantic_argument_keys",
        ],
    )?;
    eq_text(cap, "argument_schema", "IBAE-CAPABILITY-ARGUMENTS-V1")?;
    eq_text(cap, "replay_safety", "occurrence_sensitive")?;
    if cap["available"] != true
        || !cap["replay_evidence_id"].is_null()
        || cap["contract_version"]
            .as_u64()
            .filter(|v| *v > 0)
            .is_none()
        || cap["description"]
            .as_str()
            .filter(|v| !v.is_empty() && v.trim() == *v && v.len() <= 4096)
            .is_none()
    {
        return Err("effect capability is unavailable or malformed");
    }
    let tool = text(cap, "name")?;
    let operation = Operation::parse(tool)?;
    let capability_id = identity(
        "ibae.capability-id.v1",
        &selected(
            cap,
            &[
                "argument_schema",
                "contract_version",
                "name",
                "replay_evidence_id",
                "replay_safety",
                "required_state_keys",
                "semantic_argument_keys",
            ],
        ),
    )?;
    eq_text(cap, "capability_id", &capability_id)?;
    let semantic = sorted_symbols(&cap["semantic_argument_keys"])?;
    if semantic.iter().map(String::as_str).collect::<Vec<_>>() != operation.keys() {
        return Err("effect capability must declare the exact closed argument schema");
    }
    let cap_deps = sorted_symbols(&cap["required_state_keys"])?;
    object(
        prop,
        &[
            "arguments",
            "capability",
            "epistemic_class",
            "occurrence_key",
            "proposal_key",
            "required_state_keys",
            "target_obligation_ids",
        ],
    )?;
    eq_text(prop, "capability", tool)?;
    eq_text(prop, "epistemic_class", "model_proposed")?;
    symbol(text(prop, "proposal_key")?)?;
    let occurrence = text(prop, "occurrence_key")?.to_owned();
    symbol(&occurrence)?;
    let prop_deps = sorted_symbols(&prop["required_state_keys"])?;
    let targets = prop["target_obligation_ids"]
        .as_array()
        .ok_or("effect proposal targets must be an array")?;
    if targets.is_empty() || targets.len() > 128 {
        return Err("effect proposal target bound is invalid");
    }
    let mut previous = "";
    for target in targets {
        let target = target
            .as_str()
            .filter(|v| is_fingerprint(v))
            .ok_or("effect target identity is invalid")?;
        if target <= previous {
            return Err("effect targets must be sorted and unique");
        }
        previous = target;
    }
    let arguments = &prop["arguments"];
    object(arguments, operation.keys())?;
    let key = text(arguments, "key")?.to_owned();
    symbol(&key)?;
    let expected = signed(arguments, "expected_value")?;
    let operand = signed(
        arguments,
        if operation == Operation::Set {
            "value"
        } else {
            "delta"
        },
    )?;
    let arguments_id = sha256_hex(canonical(arguments)?.as_bytes());
    let proposal_id = identity("ibae.proposal-id.v1", prop)?;
    let dependency_id = fingerprint(value, "dependency_state_id")?;
    let action_id = identity(
        "ibae.action-id.v1",
        &json!({"arguments":arguments,"capability_id":capability_id,"dependency_state_id":dependency_id,"occurrence_key":occurrence}),
    )?;
    object(
        decision,
        &[
            "action_id",
            "authority_layer",
            "blocking_obligation_ids",
            "dependency_state_keys",
            "equivalent_proposal_id",
            "logical_tick",
            "invariant_ids",
            "proposal_id",
            "proposal_key",
            "recovery_actions",
            "rejection_reason",
            "status",
            "unresolved_state_keys",
        ],
    )?;
    for (key, expected) in [
        ("action_id", action_id.as_str()),
        ("proposal_id", proposal_id.as_str()),
        ("proposal_key", text(prop, "proposal_key")?),
        ("authority_layer", "orchestration"),
        ("status", "admitted"),
    ] {
        eq_text(decision, key, expected)?;
    }
    for key in [
        "blocking_obligation_ids",
        "unresolved_state_keys",
        "recovery_actions",
        "invariant_ids",
    ] {
        if decision[key] != json!([]) {
            return Err("effect admission cannot carry blocking or recovery state");
        }
    }
    if !decision["equivalent_proposal_id"].is_null()
        || !decision["rejection_reason"].is_null()
        || decision["logical_tick"].as_u64().is_none()
    {
        return Err("effect admission is malformed");
    }

    let deps: BTreeSet<_> = cap_deps.into_iter().chain(prop_deps).collect();
    if decision["dependency_state_keys"] != json!(deps.into_iter().collect::<Vec<_>>()) {
        return Err("effect admission dependency keys mismatch");
    }
    let permissions = policy["tool_permissions"]
        .as_array()
        .ok_or("governance permissions must be an array")?;
    let permission = permissions
        .iter()
        .find(|p| p["tool_name"] == tool)
        .ok_or("effect tool has no governed permission")?;
    if permission["allow_mutation"] != true || permission["allow_cache_reuse"] != false {
        return Err("effect tool is not explicitly authorized");
    }
    eq_text(permission, "authority_class", operation.class())?;
    let permission_id = identity("ibae.tool-permission-id.v1", permission)?;
    let decision_id = identity("ibae.governed-admission-decision-id.v1", decision)?;
    let action_record = json!({"action_id":action_id,"arguments":arguments,"arguments_id":arguments_id,"authority_class":operation.class(),"capability_id":capability_id,"decision_id":decision_id,"dependency_fingerprint":dependency_id,"governance_id":governance_id,"occurrence_key":occurrence,"permission_id":permission_id,"proposal_id":proposal_id,"replay_safety":"occurrence_sensitive","task_id":task_id,"tool_name":tool});
    let governed_action_id = identity("ibae.governed-tool-action-id.v1", &action_record)?;
    let mut expected_admission = action_record;
    let body = expected_admission.as_object_mut().expect("object");
    for (key, val) in [
        ("authority_layer", json!("governance")),
        ("cache_reuse_permitted", json!(false)),
        ("governed_action_id", json!(governed_action_id)),
        ("governance_receipt_id", json!(governance_receipt_id)),
        ("protocol_version", json!("IBAE-TOOL-ADMISSION-RECEIPT-V1")),
        ("requester", json!("deterministic_orchestrator")),
        ("status", json!("accepted")),
    ] {
        body.insert(key.into(), val);
    }
    let admission_id = identity("ibae.tool-admission-receipt-id.v1", &expected_admission)?;
    expected_admission["receipt_id"] = json!(admission_id);
    if expected_admission != *admission {
        return Err(
            "effect governed admission does not match exact native-recomputed authorization",
        );
    }
    let outcomes = value["outcomes"]
        .as_array()
        .ok_or("effect outcomes must be an array")?;
    if outcomes.is_empty() || outcomes.len() > MAX_OUTCOMES {
        return Err("effect outcome plan exceeds its finite bound");
    }
    Ok(Entry {
        action_id,
        occurrence,
        admission_id,
        arguments_id,
        operation,
        key,
        operand,
        expected,
        outcomes: outcomes
            .iter()
            .map(Scenario::parse)
            .collect::<Result<_>>()?,
        status: Status::Pending,
        attempts: 0,
        cancel_requested: false,
        last_event_id: None,
        witness: Witness::None,
    })
}

#[derive(Clone)]
struct EffectCore {
    session_id: String,
    profile_id: String,
    runtime_session_id: String,
    task_id: String,
    governance_id: String,
    limits: EffectLimits,
    counters: Counters,
    cells: BTreeMap<String, i64>,
    entries: Vec<Entry>,
    generation: u64,
}
impl EffectCore {
    fn parse(
        spec: &str,
        runtime_session_id: &str,
        task_id: &str,
        governance_id: &str,
        governance_receipt_id: &str,
    ) -> Result<Self> {
        let spec = parse_effect_canonical(spec)?;
        object(
            &spec,
            &[
                "protocol_version",
                "profile",
                "task_receipt",
                "governance_policy",
                "governance_receipt",
                "tool_admissions",
            ],
        )?;
        eq_text(&spec, "protocol_version", VERSION)?;
        let policy = &spec["governance_policy"];
        object(
            policy,
            &[
                "orchestration_authority",
                "policy_key",
                "policy_version",
                "protocol_version",
                "provider_authority",
                "required_gate_keys",
                "runtime_authority",
                "supervisor_authority",
                "task_profile",
                "task_profile_version",
                "tool_permissions",
                "worker_authority",
            ],
        )?;
        if identity("ibae.governance-id.v1", policy)? != governance_id {
            return Err("effect policy does not bind the native governance identity");
        }
        for (key, expected) in [
            ("protocol_version", "IBAE-GOVERNANCE-PROTOCOL-V1"),
            ("provider_authority", "openai"),
            ("supervisor_authority", "openai_supervisor"),
            ("worker_authority", "local_candidate_worker"),
            ("orchestration_authority", "deterministic_orchestrator"),
            ("runtime_authority", "rust_execution_runtime"),
        ] {
            eq_text(policy, key, expected)?;
        }
        for key in ["policy_key", "task_profile"] {
            symbol(text(policy, key)?)?;
        }
        for key in ["policy_version", "task_profile_version"] {
            if policy[key].as_u64().filter(|n| *n > 0).is_none() {
                return Err("effect policy version must be positive");
            }
        }
        let gates = json!([
            "compact_evidence_valid",
            "execution_receipt_valid",
            "orchestration_receipt_valid"
        ]);
        if policy["required_gate_keys"] != gates {
            return Err("effect governance gates must preserve the existing closed set");
        }
        let permissions = policy["tool_permissions"]
            .as_array()
            .ok_or("effect permissions must be an array")?;
        if permissions.len() > 256 {
            return Err("effect permission count exceeds bound");
        }
        let mut previous = "";
        for permission in permissions {
            object(
                permission,
                &[
                    "allow_cache_reuse",
                    "allow_mutation",
                    "authority_class",
                    "tool_name",
                ],
            )?;
            let name = text(permission, "tool_name")?;
            symbol(name)?;
            if name <= previous {
                return Err("effect permissions must be sorted and unique");
            }
            previous = name;
            let mutation = permission["allow_mutation"]
                .as_bool()
                .ok_or("permission flags must be boolean")?;
            let cache = permission["allow_cache_reuse"]
                .as_bool()
                .ok_or("permission flags must be boolean")?;
            match text(permission, "authority_class")? {
                "pure_read" | "snapshot_read" if !mutation => (),
                "volatile_read" if !mutation && !cache => (),
                "idempotent_mutation" | "non_idempotent_mutation" if !cache => (),
                _ => return Err("effect governance contains invalid tool authority"),
            }
        }
        let task = &spec["task_receipt"];
        object(
            task,
            &[
                "acceptance_contract",
                "authority_layer",
                "contract_version",
                "protocol_version",
                "receipt_id",
                "required_gate_keys",
                "status",
                "task_id",
                "task_key",
            ],
        )?;
        eq_text(task, "authority_layer", "governance")?;
        eq_text(task, "status", "admitted")?;
        eq_text(task, "protocol_version", "IBAE-TASK-RECEIPT-V1")?;
        symbol(text(task, "task_key")?)?;
        if task["contract_version"]
            .as_u64()
            .filter(|n| *n > 0)
            .is_none()
            || task["required_gate_keys"] != gates
            || !task["acceptance_contract"].is_object()
        {
            return Err("effect task receipt is invalid");
        }
        // TaskReceipt.acceptance_contract is a legacy CanonicalValue, not a
        // D/runtime envelope. Rehashing an oversized nested record must not
        // manufacture a task that the accepted governance schema rejects.
        canonical_value(&task["acceptance_contract"])
            .map_err(|_| "effect task acceptance contract exceeds legacy canonical bounds")?;
        if identity(
            "ibae.task-id.v1",
            &selected(
                task,
                &[
                    "acceptance_contract",
                    "contract_version",
                    "required_gate_keys",
                    "task_key",
                ],
            ),
        )? != task_id
        {
            return Err("effect profile was not committed by the original native task");
        }
        eq_text(task, "task_id", task_id)?;
        receipt(task, "ibae.task-receipt-id.v1")?;
        let governance = &spec["governance_receipt"];
        let mut expected = json!({"authority_layer":"governance","governance_id":governance_id,"policy_key":policy["policy_key"],"policy_version":policy["policy_version"],"protocol_version":"IBAE-GOVERNANCE-RECEIPT-V1","provider_authority":"openai","requester":"openai_supervisor","required_gate_keys":gates,"status":"accepted","task_id":task_id,"task_profile":policy["task_profile"],"task_profile_version":policy["task_profile_version"],"task_receipt_id":task["receipt_id"]});
        expected["receipt_id"] = json!(identity("ibae.governance-receipt-id.v1", &expected)?);
        if expected != *governance || governance["receipt_id"] != governance_receipt_id {
            return Err("effect governance receipt does not match native authority");
        }
        let profile = &spec["profile"];
        object(
            profile,
            &[
                "protocol_version",
                "governance_id",
                "limits",
                "initial_cells",
                "entries",
            ],
        )?;
        eq_text(profile, "protocol_version", PROFILE_VERSION)?;
        eq_text(profile, "governance_id", governance_id)?;
        let profile_id = identity("ibae.effect-profile-id.v1", profile)?;
        if task["acceptance_contract"]["effect_profile_id"] != profile_id {
            return Err("effect profile is not explicitly committed in the original task");
        }
        let limits = EffectLimits::parse(&profile["limits"])?;
        let input_cells = profile["initial_cells"]
            .as_object()
            .ok_or("effect cells must be a bounded object")?;
        if input_cells.is_empty() || input_cells.len() > MAX_ENTRIES {
            return Err("effect cell registry exceeds its bound");
        }
        let mut cells = BTreeMap::new();
        for (key, value) in input_cells {
            symbol(key)?;
            cells.insert(
                key.clone(),
                value.as_i64().ok_or("effect cell must be signed 64-bit")?,
            );
        }
        let declarations = profile["entries"]
            .as_array()
            .ok_or("effect entries must be an array")?;
        let admissions = spec["tool_admissions"]
            .as_array()
            .ok_or("effect admissions must be an array")?;
        if declarations.is_empty()
            || declarations.len() > MAX_ENTRIES
            || declarations.len() != admissions.len()
        {
            return Err("effect manifest coverage or bound is invalid");
        }
        let mut entries = Vec::new();
        let mut owners = BTreeSet::new();
        let mut actions = BTreeSet::new();
        let mut proposals = BTreeSet::new();
        for (declaration, admission) in declarations.iter().zip(admissions) {
            let entry = parse_entry(
                declaration,
                admission,
                policy,
                task_id,
                governance_id,
                governance_receipt_id,
            )?;
            if !owners.insert(entry.occurrence.clone())
                || !actions.insert(entry.action_id.clone())
                || !proposals.insert(text(&declaration["proposal"], "proposal_key")?.to_owned())
            {
                return Err("effect occurrence/action/proposal ownership must be unique");
            }
            if !cells.contains_key(&entry.key) {
                return Err("effect tool cannot create undeclared cells");
            }
            entries.push(entry);
        }
        let session_id = identity(
            "ibae.effect-session-id.v1",
            &json!({"effect_profile_id":profile_id,"runtime_session_id":runtime_session_id,"task_id":task_id,"governance_id":governance_id}),
        )?;
        Ok(Self {
            session_id,
            profile_id,
            runtime_session_id: runtime_session_id.to_owned(),
            task_id: task_id.to_owned(),
            governance_id: governance_id.to_owned(),
            limits,
            counters: Counters::default(),
            cells,
            entries,
            generation: 0,
        })
    }
    fn snapshot_value(&self, epoch: AuthorityEpochState) -> Result<Value> {
        let occurrences:Vec<_>=self.entries.iter().map(|entry|json!({"action_id":entry.action_id,"occurrence_key":entry.occurrence,"status":entry.status.code(),"attempts":entry.attempts,"cancel_requested":entry.cancel_requested,"last_event_id":entry.last_event_id})).collect();
        let mut value = json!({"protocol_version":"IBAE-EFFECT-SNAPSHOT-V1","effect_session_id":self.session_id,"effect_profile_id":self.profile_id,"runtime_session_id":self.runtime_session_id,"task_id":self.task_id,"governance_id":self.governance_id,"authority_epoch":epoch.epoch,"revoked":epoch.revoked,"generation":self.generation,"logical_tick":self.generation,"limits":self.limits.value(),"counters":self.counters.value(),"cells":self.cells,"occurrences":occurrences});
        value["state_id"] = json!(identity("ibae.effect-state-id.v1", &value)?);
        Ok(value)
    }
    fn check_command(
        &self,
        command: &Value,
        epoch: AuthorityEpochState,
    ) -> Result<(usize, String)> {
        object(
            command,
            &[
                "protocol_version",
                "command_type",
                "effect_session_id",
                "expected_state_id",
                "action_id",
                "occurrence_key",
            ],
        )?;
        eq_text(command, "protocol_version", VERSION)?;
        eq_text(command, "effect_session_id", &self.session_id)?;
        if epoch.revoked {
            return Err("effect authority is revoked");
        }
        let snapshot = self.snapshot_value(epoch)?;
        if command["expected_state_id"] != snapshot["state_id"] {
            return Err("effect approval or command has stale state");
        }
        let action = fingerprint(command, "action_id")?;
        let index = self
            .entries
            .iter()
            .position(|e| e.action_id == action)
            .ok_or("effect action is outside frozen authorization")?;
        let entry = &self.entries[index];
        eq_text(command, "occurrence_key", &entry.occurrence)?;
        let command_type = text(command, "command_type")?;
        if self.counters.requests >= self.limits.requests {
            return Err("effect command budget exhausted");
        }
        match command_type {
            "execute_effect" | "retry_effect" => {
                if entry.cancel_requested {
                    return Err("effect occurrence is cancelled");
                }
                if self.entries[..index].iter().any(|e| !e.sequence_terminal()) {
                    return Err("effect declared sequence predecessor is unfinished");
                }
                if command_type == "execute_effect" && entry.status != Status::Pending {
                    return Err("effect occurrence already owns an execution attempt");
                }
                if command_type == "retry_effect"
                    && !matches!(
                        entry.status,
                        Status::NotApplied | Status::ReconciledNotApplied
                    )
                {
                    return Err(
                        "effect retry requires native proof the occurrence was not applied",
                    );
                }
                if command_type == "retry_effect" && self.counters.retries >= self.limits.retries {
                    return Err("effect retry budget exhausted");
                }
                if self.counters.executions >= self.limits.executions {
                    return Err("effect execution budget exhausted");
                }
                if entry.attempts as usize >= entry.outcomes.len() {
                    return Err("effect occurrence attempt plan exhausted");
                }
                if self.cells[&entry.key] == entry.expected
                    && entry.operation == Operation::Increment
                    && !matches!(
                        entry.outcomes[entry.attempts as usize],
                        Scenario::FailBefore | Scenario::CrashBefore
                    )
                    && self.cells[&entry.key].checked_add(entry.operand).is_none()
                {
                    return Err("effect arithmetic overflow");
                }
            }
            "reconcile_effect" => {
                if entry.status != Status::Ambiguous {
                    return Err("effect reconciliation requires an ambiguous occurrence");
                }
                if self.counters.reconciliations >= self.limits.reconciliations {
                    return Err("effect reconciliation budget exhausted");
                }
            }
            "cancel_effect" => {
                if entry.cancel_requested || entry.status.completed() {
                    return Err("effect occurrence cannot be cancelled again or after completion");
                }
            }
            _ => return Err("unknown effect command family"),
        }
        Ok((index, command_type.to_owned()))
    }
    fn observation(&self, index: usize, attempt: u64, phase: &str, value: i64) -> Result<Value> {
        let entry = &self.entries[index];
        let mut observation = json!({"protocol_version":"IBAE-EFFECT-OBSERVATION-V1","effect_session_id":self.session_id,"action_id":entry.action_id,"occurrence_key":entry.occurrence,"attempt":attempt,"phase":phase,"key":entry.key,"value":value});
        observation["observation_id"] =
            json!(identity("ibae.effect-observation-id.v1", &observation)?);
        Ok(observation)
    }
    fn dispatch(&mut self, command: &Value, epoch: AuthorityEpochState) -> Result<String> {
        let (index, command_type) = self.check_command(command, epoch)?;
        let prior_state_id = self.snapshot_value(epoch)?["state_id"].clone();
        let command_id = identity("ibae.effect-command-id.v1", command)?;
        let recovery_of = self.entries[index].last_event_id.clone();
        let mut pre = Value::Null;
        let mut post = Value::Null;
        let mut applied = Value::Null;
        let mut failure: Option<&str> = None;
        self.counters.requests += 1;
        match command_type.as_str() {
            "execute_effect" | "retry_effect" => {
                self.counters.executions += 1;
                if command_type == "retry_effect" {
                    self.counters.retries += 1;
                }
                let entry = &mut self.entries[index];
                let scenario = entry.outcomes[entry.attempts as usize];
                entry.attempts += 1;
                let before = self.cells[&entry.key];
                let attempt = entry.attempts;
                if before != entry.expected {
                    entry.status = Status::NotApplied;
                    entry.witness = Witness::NotApplied(before);
                    applied = json!(false);
                    failure = Some("precondition_mismatch");
                } else {
                    match scenario {
                        Scenario::FailBefore => {
                            entry.status = Status::NotApplied;
                            entry.witness = Witness::NotApplied(before);
                            applied = json!(false);
                            failure = Some("synthetic_failure_before");
                        }
                        Scenario::CrashBefore => {
                            entry.status = Status::Ambiguous;
                            entry.witness = Witness::NotApplied(before);
                            failure = Some("acknowledgement_lost");
                        }
                        Scenario::Success | Scenario::CrashAfter | Scenario::Unknown => {
                            let after = match entry.operation {
                                Operation::Set => entry.operand,
                                Operation::Increment => before
                                    .checked_add(entry.operand)
                                    .expect("overflow checked before reservation"),
                            };
                            self.cells.insert(entry.key.clone(), after);
                            entry.witness = if scenario == Scenario::Unknown {
                                Witness::Unknown
                            } else {
                                Witness::Applied(after)
                            };
                            if scenario == Scenario::Success {
                                entry.status = Status::Applied;
                                applied = json!(true);
                            } else {
                                entry.status = Status::Ambiguous;
                                failure = Some("acknowledgement_lost");
                            }
                        }
                    }
                }
                pre = self.observation(index, attempt, "before", before)?;
                if self.entries[index].status != Status::Ambiguous {
                    post = self.observation(
                        index,
                        attempt,
                        "after",
                        self.cells[&self.entries[index].key],
                    )?;
                }
            }
            "reconcile_effect" => {
                self.counters.reconciliations += 1;
                let entry = &mut self.entries[index];
                let observed = match entry.witness {
                    Witness::Applied(value) => {
                        entry.status = Status::ReconciledApplied;
                        applied = json!(true);
                        Some(value)
                    }
                    Witness::NotApplied(value) => {
                        entry.status = Status::ReconciledNotApplied;
                        applied = json!(false);
                        Some(value)
                    }
                    Witness::Unknown => {
                        failure = Some("reconciliation_unknown");
                        None
                    }
                    Witness::None => return Err("effect journal is missing"),
                };
                if let Some(value) = observed {
                    post = self.observation(
                        index,
                        self.entries[index].attempts,
                        "reconciliation",
                        value,
                    )?;
                }
            }
            "cancel_effect" => {
                let entry = &mut self.entries[index];
                entry.cancel_requested = true;
                if entry.status != Status::Ambiguous {
                    entry.status = Status::Cancelled;
                    applied = json!(false);
                }
            }
            _ => unreachable!("validated command"),
        }
        self.generation += 1;
        let entry = &self.entries[index];
        let event = json!({"effect_session_id":self.session_id,"command_id":command_id,"generation":self.generation,"action_id":entry.action_id,"occurrence_key":entry.occurrence,"attempt":entry.attempts,"status":entry.status.code(),"effect_applied":applied,"pre_evidence":pre,"post_evidence":post,"failure_reason":failure,"cancel_requested":entry.cancel_requested});
        let event_id = identity("ibae.effect-event-id.v1", &event)?;
        self.entries[index].last_event_id = Some(event_id.clone());
        let resulting_state_id = self.snapshot_value(epoch)?["state_id"].clone();
        let entry = &self.entries[index];
        let mut output = json!({"protocol_version":"IBAE-EFFECT-RECEIPT-V1","effect_session_id":self.session_id,"effect_profile_id":self.profile_id,"runtime_session_id":self.runtime_session_id,"task_id":self.task_id,"governance_id":self.governance_id,"authority_epoch":epoch.epoch,"command_id":command_id,"command_type":command_type,"action_id":entry.action_id,"occurrence_key":entry.occurrence,"tool_admission_receipt_id":entry.admission_id,"authority_class":entry.operation.class(),"arguments_id":entry.arguments_id,"attempt":entry.attempts,"status":entry.status.code(),"ambiguous":entry.status==Status::Ambiguous,"effect_applied":applied,"pre_evidence":pre,"post_evidence":post,"recovery_of_event_id":if command_type=="execute_effect"{None}else{recovery_of},"event_id":event_id,"prior_state_id":prior_state_id,"resulting_state_id":resulting_state_id,"counters":self.counters.value(),"logical_tick":self.generation,"cancel_requested":entry.cancel_requested,"failure_reason":failure,"evidence_scope":"synthetic-native-in-process"});
        output["receipt_id"] = json!(identity("ibae.effect-receipt-id.v1", &output)?);
        canonical(&output)
    }
}

struct EffectIdentity;
#[pyclass(
    name = "NativeEffectApprovalSeal",
    module = "ibae._runtime",
    unsendable
)]
pub(super) struct NativeEffectApprovalSeal {
    owner: Arc<EffectIdentity>,
    canonical_command: String,
    epoch: u64,
    binding: Arc<ContinuationAuthorityBinding>,
    used: Cell<bool>,
}
#[pymethods]
impl NativeEffectApprovalSeal {
    fn validates(&self, canonical_command: &str) -> bool {
        !self.used.get()
            && self.binding.epoch_is_current(self.epoch)
            && self.canonical_command == canonical_command
    }
}
#[pyclass(name = "NativeEffectReceiptSeal", module = "ibae._runtime", unsendable)]
pub(super) struct NativeEffectReceiptSeal {
    owner: Arc<EffectIdentity>,
    canonical_receipt: String,
}
#[pymethods]
impl NativeEffectReceiptSeal {
    fn validates(&self, canonical_receipt: &str) -> bool {
        self.canonical_receipt == canonical_receipt
    }
}
#[pyclass(name = "NativeEffectSession", module = "ibae._runtime", unsendable)]
pub(super) struct NativeEffectSession {
    core: EffectCore,
    binding: Arc<ContinuationAuthorityBinding>,
    owner: Arc<EffectIdentity>,
    pending: Option<Py<NativeEffectApprovalSeal>>,
}
#[pymethods]
impl NativeEffectSession {
    fn snapshot(&self) -> PyResult<String> {
        canonical(
            &self
                .core
                .snapshot_value(self.binding.epoch_state()?)
                .map_err(PyValueError::new_err)?,
        )
        .map_err(PyValueError::new_err)
    }
    fn authorize(
        &mut self,
        py: Python<'_>,
        command_json: &str,
        authority: PyRef<'_, NativeContinuationSupervisorAuthority>,
    ) -> PyResult<Py<NativeEffectApprovalSeal>> {
        if !Arc::ptr_eq(&self.binding, &authority.binding) {
            return Err(PyValueError::new_err(
                "effect supervisor authority belongs to another native session",
            ));
        }
        let epoch = self.binding.epoch_state()?;
        self.binding.require_epoch(epoch.epoch)?;
        let command = parse_effect_canonical(command_json)
            .map_err(|_| PyValueError::new_err("effect command must be bounded canonical JSON"))?;
        self.core
            .check_command(&command, epoch)
            .map_err(PyValueError::new_err)?;
        // One reserved request slot can issue an execute/retry approval and
        // then, at most once, replace it with cancellation for that exact
        // occurrence. The slot is never freed by replacement. There is no
        // withdraw/reissue loop: issuance is bounded by 2 * max_requests.
        if let Some(pending) = &self.pending {
            let pending = pending.borrow(py);
            let original = parse_effect_canonical(&pending.canonical_command)
                .map_err(|_| PyValueError::new_err("native pending effect approval is invalid"))?;
            if command["command_type"] != "cancel_effect"
                || !matches!(
                    original["command_type"].as_str(),
                    Some("execute_effect" | "retry_effect")
                )
                || original["action_id"] != command["action_id"]
                || original["occurrence_key"] != command["occurrence_key"]
                || original["expected_state_id"] != command["expected_state_id"]
                || pending.used.get()
            {
                return Err(PyValueError::new_err(
                    "effect session already has its single pending approval",
                ));
            }
        }
        let seal = Py::new(
            py,
            NativeEffectApprovalSeal {
                owner: Arc::clone(&self.owner),
                canonical_command: command_json.to_owned(),
                epoch: epoch.epoch,
                binding: Arc::clone(&self.binding),
                used: Cell::new(false),
            },
        )?;
        if let Some(pending) = &self.pending {
            pending.borrow(py).used.set(true);
        }
        self.pending = Some(seal.clone_ref(py));
        Ok(seal)
    }
    fn dispatch(
        &mut self,
        py: Python<'_>,
        command_json: &str,
        approval: PyRef<'_, NativeEffectApprovalSeal>,
    ) -> PyResult<(String, Py<NativeEffectReceiptSeal>)> {
        self.binding.require_epoch(approval.epoch)?;
        if !Arc::ptr_eq(&self.owner, &approval.owner)
            || approval.used.get()
            || approval.canonical_command != command_json
            || !self
                .pending
                .as_ref()
                .is_some_and(|seal| std::ptr::eq(&*seal.borrow(py), &*approval))
        {
            return Err(PyValueError::new_err(
                "effect approval is unissued, foreign, consumed or mismatched",
            ));
        }
        let command = parse_effect_canonical(command_json)
            .map_err(|_| PyValueError::new_err("effect command must be bounded canonical JSON"))?;
        // This transaction is only a closed native in-memory synthetic world.
        // Modelled lost acknowledgements commit the journal and spent budgets.
        // It must never be generalized to rollback real external effects.
        let mut candidate = self.core.clone();
        let output = candidate
            .dispatch(&command, self.binding.epoch_state()?)
            .map_err(PyValueError::new_err)?;
        let receipt = Py::new(
            py,
            NativeEffectReceiptSeal {
                owner: Arc::clone(&self.owner),
                canonical_receipt: output.clone(),
            },
        )?;
        approval.used.set(true);
        self.pending = None;
        self.core = candidate;
        Ok((output, receipt))
    }
    fn validates_receipt(
        &self,
        canonical_receipt: &str,
        seal: PyRef<'_, NativeEffectReceiptSeal>,
    ) -> bool {
        Arc::ptr_eq(&self.owner, &seal.owner) && seal.canonical_receipt == canonical_receipt
    }
}

pub(super) fn create(
    runtime: &NativeRuntimeSession,
    py: Python<'_>,
    authority: PyRef<'_, NativeContinuationSupervisorAuthority>,
    canonical_spec: &str,
    enabled: bool,
) -> PyResult<Py<NativeEffectSession>> {
    if !enabled {
        return Err(PyValueError::new_err(
            "synthetic effects are disabled by default",
        ));
    }
    if !runtime.matches_continuation_authority(&authority.binding) {
        return Err(PyValueError::new_err(
            "effect authority does not belong to this native runtime",
        ));
    }
    let binding = &authority.binding;
    binding.active_epoch()?;
    if !matches!(
        *binding
            .live_lineage
            .lock()
            .map_err(|_| PyValueError::new_err("native lineage lock failed"))?,
        LiveContinuationLineageState::Ready(_)
    ) {
        return Err(PyValueError::new_err(
            "effect attachment requires an initialized native continuation lineage",
        ));
    }
    let core = EffectCore::parse(
        canonical_spec,
        &binding.runtime_session_id,
        &binding.task_id,
        &binding.governance_id,
        &binding.governance_receipt_id,
    )
    .map_err(PyValueError::new_err)?;
    let mut attached = binding
        .effect_session_attached
        .lock()
        .map_err(|_| PyValueError::new_err("native effect attachment lock failed"))?;
    if *attached {
        return Err(PyValueError::new_err(
            "native task already owns its one immutable effect ledger",
        ));
    }
    let session = Py::new(
        py,
        NativeEffectSession {
            core,
            binding: Arc::clone(binding),
            owner: Arc::new(EffectIdentity),
            pending: None,
        },
    )?;
    *attached = true;
    Ok(session)
}
pub(super) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<NativeEffectSession>()?;
    module.add_class::<NativeEffectApprovalSeal>()?;
    module.add_class::<NativeEffectReceiptSeal>()?;
    module.add("EFFECT_PROTOCOL_VERSION", VERSION)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn core(operation: Operation, outcomes: Vec<Scenario>) -> EffectCore {
        EffectCore {
            session_id: "a".repeat(64),
            profile_id: "b".repeat(64),
            runtime_session_id: "c".repeat(64),
            task_id: "d".repeat(64),
            governance_id: "e".repeat(64),
            limits: EffectLimits {
                requests: 8,
                executions: 4,
                retries: 2,
                reconciliations: 2,
            },
            counters: Counters::default(),
            cells: BTreeMap::from([("counter".into(), 0)]),
            entries: vec![Entry {
                action_id: "f".repeat(64),
                occurrence: "occurrence.first".into(),
                admission_id: "1".repeat(64),
                arguments_id: "2".repeat(64),
                operation,
                key: "counter".into(),
                operand: 1,
                expected: 0,
                outcomes,
                status: Status::Pending,
                attempts: 0,
                cancel_requested: false,
                last_event_id: None,
                witness: Witness::None,
            }],
            generation: 0,
        }
    }
    fn command(core: &EffectCore, index: usize, kind: &str) -> Value {
        json!({"protocol_version":VERSION,"command_type":kind,"effect_session_id":core.session_id,
            "expected_state_id":core.snapshot_value(AuthorityEpochState::default()).unwrap()["state_id"],
            "action_id":core.entries[index].action_id,"occurrence_key":core.entries[index].occurrence})
    }
    fn run(core: &mut EffectCore, index: usize, kind: &str) -> Value {
        let cmd = command(core, index, kind);
        serde_json::from_str(&core.dispatch(&cmd, AuthorityEpochState::default()).unwrap()).unwrap()
    }
    fn snapshot(core: &EffectCore) -> Value {
        core.snapshot_value(AuthorityEpochState::default()).unwrap()
    }

    #[test]
    fn effect_commands_are_separate_from_legacy_reads() {
        let core = core(Operation::Set, vec![Scenario::Success]);
        let cmd = command(&core, 0, "execute_effect");
        assert!(parse_command(&canonical(&cmd).unwrap()).is_err());
        let mut legacy = cmd;
        legacy["protocol_version"] = json!(PROTOCOL_VERSION);
        assert!(core
            .check_command(&legacy, AuthorityEpochState::default())
            .is_err());
    }
    #[test]
    fn success_is_native_observed_and_duplicate_state_neutral() {
        for operation in [Operation::Set, Operation::Increment] {
            let mut core = core(operation, vec![Scenario::Success]);
            let before = snapshot(&core);
            let stale = command(&core, 0, "execute_effect");
            let first = run(&mut core, 0, "execute_effect");
            assert_eq!(first["status"], "applied");
            assert_eq!(first["effect_applied"], true);
            assert_eq!(first["pre_evidence"]["value"], 0);
            assert_eq!(first["post_evidence"]["value"], 1);
            assert_eq!(first["prior_state_id"], before["state_id"]);
            let after = snapshot(&core);
            assert_eq!(first["resulting_state_id"], after["state_id"]);
            assert!(core
                .dispatch(&stale, AuthorityEpochState::default())
                .is_err());
            assert!(core
                .dispatch(
                    &command(&core, 0, "retry_effect"),
                    AuthorityEpochState::default()
                )
                .is_err());
            assert_eq!(snapshot(&core), after);
            receipt(&first, "ibae.effect-receipt-id.v1").unwrap();
        }
    }
    #[test]
    fn identical_idempotent_payload_preserves_distinct_ordered_occurrences() {
        let mut core = core(Operation::Set, vec![Scenario::Success]);
        core.entries[0].operand = 0;
        let mut second = core.entries[0].clone();
        second.action_id = "3".repeat(64);
        second.occurrence = "occurrence.second".into();
        core.entries.push(second);
        let before = snapshot(&core);
        assert!(core
            .dispatch(
                &command(&core, 1, "execute_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
        assert_eq!(snapshot(&core), before);
        let first = run(&mut core, 0, "execute_effect");
        let second = run(&mut core, 1, "execute_effect");
        assert_eq!(first["arguments_id"], second["arguments_id"]);
        assert_ne!(first["action_id"], second["action_id"]);
        assert_eq!(core.counters.executions, 2);
        assert_eq!(core.cells["counter"], 0);
    }
    #[test]
    fn lost_ack_after_commit_cannot_repeat_non_idempotent_occurrence() {
        let mut core = core(
            Operation::Increment,
            vec![Scenario::CrashAfter, Scenario::Success],
        );
        let lost = run(&mut core, 0, "execute_effect");
        assert_eq!(core.cells["counter"], 1);
        assert_eq!(lost["status"], "ambiguous");
        assert_eq!(lost["effect_applied"], Value::Null);
        assert!(lost["post_evidence"].is_null());
        let before = snapshot(&core);
        assert!(core
            .dispatch(
                &command(&core, 0, "retry_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
        assert_eq!(snapshot(&core), before);
        let recovered = run(&mut core, 0, "reconcile_effect");
        assert_eq!(recovered["status"], "reconciled_applied");
        assert_eq!(recovered["effect_applied"], true);
        assert_eq!(recovered["recovery_of_event_id"], lost["event_id"]);
        assert_eq!(core.counters.executions, 1);
        assert_eq!(core.counters.retries, 0);
        assert!(core
            .dispatch(
                &command(&core, 0, "retry_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
    }
    #[test]
    fn lost_ack_before_commit_requires_journal_reconciliation_before_retry() {
        let mut core = core(
            Operation::Increment,
            vec![Scenario::CrashBefore, Scenario::Success],
        );
        run(&mut core, 0, "execute_effect");
        assert_eq!(core.cells["counter"], 0);
        assert!(core
            .dispatch(
                &command(&core, 0, "retry_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
        let reconciled = run(&mut core, 0, "reconcile_effect");
        assert_eq!(reconciled["status"], "reconciled_not_applied");
        let retry = run(&mut core, 0, "retry_effect");
        assert_eq!(retry["status"], "applied");
        assert_eq!(retry["attempt"], 2);
        assert_eq!(core.counters.executions, 2);
        assert_eq!(core.counters.retries, 1);
        assert_eq!(core.cells["counter"], 1);
    }
    #[test]
    fn unknown_journal_never_becomes_success_and_reconciliation_is_bounded() {
        let mut core = core(
            Operation::Increment,
            vec![Scenario::Unknown, Scenario::Success],
        );
        run(&mut core, 0, "execute_effect");
        for _ in 0..2 {
            let unknown = run(&mut core, 0, "reconcile_effect");
            assert_eq!(unknown["status"], "ambiguous");
            assert_eq!(unknown["failure_reason"], "reconciliation_unknown");
            assert!(unknown["effect_applied"].is_null());
            assert!(unknown["post_evidence"].is_null());
        }
        let before = snapshot(&core);
        assert!(core
            .dispatch(
                &command(&core, 0, "reconcile_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
        assert_eq!(snapshot(&core), before);
        assert!(core
            .dispatch(
                &command(&core, 0, "retry_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
    }
    #[test]
    fn reconciliation_uses_occurrence_witness_not_matching_current_value() {
        let mut core = core(Operation::Increment, vec![Scenario::CrashAfter]);
        run(&mut core, 0, "execute_effect");
        // An equal final value, or later changes, cannot establish causality.
        // Reconciliation reports the private original occurrence observation.
        core.cells.insert("counter".into(), 99);
        let proof = run(&mut core, 0, "reconcile_effect");
        assert_eq!(proof["post_evidence"]["value"], 1);
        assert_eq!(core.cells["counter"], 99);
    }
    #[test]
    fn precondition_mismatch_preserves_uncommitted_world_and_finite_attempt() {
        let mut core = core(Operation::Set, vec![Scenario::Success]);
        core.cells.insert("counter".into(), 77);
        let receipt = run(&mut core, 0, "execute_effect");
        assert_eq!(receipt["failure_reason"], "precondition_mismatch");
        assert_eq!(receipt["status"], "not_applied");
        assert_eq!(receipt["effect_applied"], false);
        assert_eq!(core.cells["counter"], 77);
        assert_eq!(core.counters.executions, 1);
    }
    #[test]
    fn overflow_unknown_fields_foreign_owner_and_unsupported_commands_are_neutral() {
        let mut core = core(Operation::Increment, vec![Scenario::Success]);
        core.cells.insert("counter".into(), i64::MAX);
        core.entries[0].expected = i64::MAX;
        let before = snapshot(&core);
        assert!(core
            .dispatch(
                &command(&core, 0, "execute_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
        assert_eq!(snapshot(&core), before);
        for field in ["action_id", "occurrence_key", "effect_session_id"] {
            let mut cmd = command(&core, 0, "cancel_effect");
            cmd[field] = json!("foreign");
            assert!(core.dispatch(&cmd, AuthorityEpochState::default()).is_err());
            assert_eq!(snapshot(&core), before);
        }
        let mut cmd = command(&core, 0, "cancel_effect");
        cmd["operation"] = json!("caller_success");
        assert!(core.dispatch(&cmd, AuthorityEpochState::default()).is_err());
        assert!(core
            .dispatch(
                &command(&core, 0, "execute_read"),
                AuthorityEpochState::default()
            )
            .is_err());
        assert_eq!(snapshot(&core), before);
    }
    #[test]
    fn cancellation_prevents_execution_without_erasing_ambiguous_evidence() {
        let mut pending = core(Operation::Set, vec![Scenario::Success]);
        let cancel = run(&mut pending, 0, "cancel_effect");
        assert_eq!(cancel["status"], "cancelled");
        assert_eq!(pending.counters.executions, 0);
        assert!(pending
            .dispatch(
                &command(&pending, 0, "execute_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
        let mut ambiguous = core(
            Operation::Increment,
            vec![Scenario::CrashBefore, Scenario::Success],
        );
        run(&mut ambiguous, 0, "execute_effect");
        let cancel = run(&mut ambiguous, 0, "cancel_effect");
        assert_eq!(cancel["status"], "ambiguous");
        assert_eq!(cancel["cancel_requested"], true);
        let recovery = run(&mut ambiguous, 0, "reconcile_effect");
        assert_eq!(recovery["status"], "reconciled_not_applied");
        assert_eq!(recovery["cancel_requested"], true);
        assert!(ambiguous
            .dispatch(
                &command(&ambiguous, 0, "retry_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
    }
    #[test]
    fn cancelled_crash_before_reconciliation_unblocks_next_declared_occurrence() {
        let mut core = core(Operation::Increment, vec![Scenario::CrashBefore]);
        let mut second = core.entries[0].clone();
        second.action_id = "3".repeat(64);
        second.occurrence = "occurrence.second".into();
        second.outcomes = vec![Scenario::Success];
        core.entries.push(second);
        run(&mut core, 0, "execute_effect");
        run(&mut core, 0, "cancel_effect");
        assert!(core
            .dispatch(
                &command(&core, 1, "execute_effect"),
                AuthorityEpochState::default()
            )
            .is_err());
        let recovered = run(&mut core, 0, "reconcile_effect");
        assert_eq!(recovered["status"], "reconciled_not_applied");
        assert_eq!(recovered["cancel_requested"], true);
        assert_eq!(run(&mut core, 1, "execute_effect")["status"], "applied");
        assert_eq!(core.cells["counter"], 1);
    }

    #[test]
    fn every_budget_and_attempt_plan_are_native_finite() {
        for exhausted in ["requests", "executions", "retries", "plan"] {
            let mut core = core(
                Operation::Set,
                vec![Scenario::FailBefore, Scenario::Success],
            );
            run(&mut core, 0, "execute_effect");
            match exhausted {
                "requests" => core.limits.requests = 1,
                "executions" => core.limits.executions = 1,
                "retries" => core.limits.retries = 0,
                _ => core.entries[0].outcomes.truncate(1),
            };
            let before = snapshot(&core);
            assert!(core
                .dispatch(
                    &command(&core, 0, "retry_effect"),
                    AuthorityEpochState::default()
                )
                .is_err());
            assert_eq!(snapshot(&core), before);
        }
    }
    #[test]
    fn revocation_stops_all_effect_dispatch_and_never_changes_prior_receipts() {
        let mut core = core(Operation::Increment, vec![Scenario::CrashAfter]);
        let original = run(&mut core, 0, "execute_effect");
        let saved = original.clone();
        let mut epoch = AuthorityEpochState::default();
        epoch.revoke().unwrap();
        for kind in [
            "execute_effect",
            "retry_effect",
            "reconcile_effect",
            "cancel_effect",
        ] {
            let cmd = command(&core, 0, kind);
            assert!(core.dispatch(&cmd, epoch).is_err());
        }
        assert_eq!(original, saved);
        assert_eq!(core.cells["counter"], 1);
        assert_eq!(core.counters.requests, 1);
        assert_eq!(core.snapshot_value(epoch).unwrap()["revoked"], true);
    }
    #[test]
    fn effect_one_mib_bound_is_enforced_before_parse_and_after_canonicalization() {
        let above = json!(vec!["a".repeat(32_767); 32]);
        let legacy = canonical_runtime_value(&above).unwrap();
        assert!(legacy.len() > MAX_EFFECT_RECORD_BYTES);
        assert!(legacy.len() < MAX_RUNTIME_RECORD_BYTES);
        assert!(canonical(&above).is_err());
        assert!(parse_effect_canonical(&legacy).is_err());
        let below = json!(vec!["a".repeat(32_767); 31]);
        let encoded = canonical(&below).unwrap();
        assert_eq!(parse_effect_canonical(&encoded).unwrap(), below);
    }

    #[test]
    fn factory_preserves_legacy_task_acceptance_contract_bounds() {
        let policy = json!({
            "orchestration_authority": "deterministic_orchestrator",
            "policy_key": "effects.bounds", "policy_version": 1,
            "protocol_version": "IBAE-GOVERNANCE-PROTOCOL-V1",
            "provider_authority": "openai",
            "required_gate_keys": ["compact_evidence_valid", "execution_receipt_valid", "orchestration_receipt_valid"],
            "runtime_authority": "rust_execution_runtime",
            "supervisor_authority": "openai_supervisor",
            "task_profile": "tiny", "task_profile_version": 1,
            "tool_permissions": [], "worker_authority": "local_candidate_worker",
        });
        let governance_id = identity("ibae.governance-id.v1", &policy).unwrap();
        let mut deep = json!(0);
        for _ in 0..33 {
            deep = json!([deep]);
        }
        for contract in [
            json!({"bytes": vec!["a".repeat(8192); 33]}),
            json!({"items": vec![0; 1025]}),
            json!({"nodes": vec![vec![0; 1023]; 4]}),
            json!({"depth": deep}),
        ] {
            assert!(canonical(&contract).is_ok());
            assert!(canonical_value(&contract).is_err());
            let task = json!({
                "acceptance_contract": contract, "authority_layer": "governance",
                "contract_version": 1, "protocol_version": "IBAE-TASK-RECEIPT-V1",
                "receipt_id": "a".repeat(64), "required_gate_keys": policy["required_gate_keys"],
                "status": "admitted", "task_id": "b".repeat(64), "task_key": "effects.bounds",
            });
            let spec = canonical(&json!({
                "protocol_version": VERSION, "profile": null, "task_receipt": task,
                "governance_policy": policy, "governance_receipt": null, "tool_admissions": [],
            }))
            .unwrap();
            assert!(matches!(
                EffectCore::parse(
                    &spec,
                    &"c".repeat(64),
                    &"b".repeat(64),
                    &governance_id,
                    &"d".repeat(64)
                ),
                Err("effect task acceptance contract exceeds legacy canonical bounds")
            ));
        }
    }

    #[test]
    fn effect_limits_scenario_and_symbol_grammars_fail_closed() {
        for invalid in [json!(true), json!(-1), json!(4097), json!(0)] {
            assert!(EffectLimits::parse(&json!({"max_requests":invalid,"max_executions":1,"max_retries":0,"max_reconciliations":0})).is_err());
        }
        for invalid in ["live", "partial_after", "callback", "applied"] {
            assert!(Scenario::parse(&json!(invalid)).is_err());
        }
        for invalid in ["", "Upper", "9digit", "key space", "../escape"] {
            assert!(symbol(invalid).is_err());
        }
        assert!(symbol("cell/namespace").is_ok());
        assert!(symbol(&format!("a{}", "a".repeat(128))).is_err());
    }
}
