//! LLM Sniffer guest plugin (com.open1s.llmsniff).
//!
//! The host calls `bsh_hook` with `{"point": "...", "batch": [...]}` for the
//! three observe points this package subscribes to: `http.exchange`,
//! `model.request` and `model.response`. The plugin parses each event for
//! shape only, re-redacts every string (defense in depth on top of the
//! host's own redaction), correlates records by `request_id`, and keeps the
//! newest `MAX_RECORDS` records in its private extension storage.
//!
//! Hard invariants:
//! - Conversation text (`messages`, `response_text`) is never copied into a
//!   record; only counts, byte sizes and usage numbers survive.
//! - Every stored string passes `redact()` and `bound_string()`.
//! - Capture is host-mediated traffic only; no network, process, workspace or
//!   secret capability is declared or used.

use extism_pdk::*;
use serde_json::{json, Map, Value};

const STORE_KEY: &str = "captures";
const MAX_RECORDS: usize = 200;
const MAX_RECORD_BYTES: usize = 48 * 1024;
const MAX_FIELD_CHARS: usize = 256;
/// Most body bytes one stored side keeps.
///
/// The host caps a body at 32 KiB; the store keeps a quarter of that so the
/// newest few exchanges stay inside the tool's output ceiling.
const MAX_BODY_CHARS: usize = 12 * 1024;
/// How many of the newest exchanges keep their bodies. Older records keep the
/// metadata and the headers and say that the body was dropped.
const MAX_BODY_RECORDS: usize = 12;
/// Head of a body shown on the overview panel.
const PANEL_BODY_CHARS: usize = 1200;
const POINTS: [&str; 3] = ["http.exchange", "model.request", "model.response"];

#[cfg(not(test))]
#[host_fn]
extern "ExtismHost" {
    fn bsh_host(input: String) -> String;
}

#[cfg(not(test))]
fn host(request: Value) -> Option<Value> {
    let raw = unsafe { bsh_host(request.to_string()) }.ok()?;
    let reply: Value = serde_json::from_str(&raw).ok()?;
    if reply.get("ok").and_then(Value::as_bool) != Some(true) {
        return None;
    }
    Some(reply.get("value").cloned().unwrap_or(Value::Null))
}

#[cfg(test)]
fn host(_request: Value) -> Option<Value> {
    None
}

// --- redaction and bounding -------------------------------------------------

/// Mask the value after each credential marker. Over-masking (a benign
/// substring like "task-") is accepted: this is defense in depth behind the
/// host's redaction, and a false positive is safe while a leak is not.
pub fn redact(input: &str) -> String {
    let mut out = input.to_string();
    for marker in ["sk-", "ghp_", "Bearer "] {
        out = mask_after(&out, marker);
    }
    out
}

fn mask_after(haystack: &str, marker: &str) -> String {
    let mut out = String::with_capacity(haystack.len());
    let mut rest = haystack;
    while let Some(idx) = rest.find(marker) {
        let (before, _) = rest.split_at(idx);
        let after_marker = &rest[idx + marker.len()..];
        out.push_str(before);
        out.push_str(marker);
        // Match the host's own rule: a credential runs while characters are
        // token-shaped. Stopping at whitespace alone cut a JSON body at the
        // first secret and dropped everything after it.
        let secret_len = after_marker
            .find(|character: char| {
                !(character.is_ascii_alphanumeric()
                    || matches!(character, '_' | '-' | '/' | '+' | '='))
            })
            .unwrap_or(after_marker.len());
        if secret_len > 0 {
            out.push_str("***");
        }
        rest = &after_marker[secret_len..];
    }
    out.push_str(rest);
    out
}

/// Cap a string field; long values are replaced by an honest marker, never
/// silently clipped.
pub fn bound_string(input: &str) -> String {
    let chars = input.chars().count();
    if chars <= MAX_FIELD_CHARS {
        return input.to_string();
    }
    format!("<truncated: {chars} chars>")
}

pub fn bound_value(value: &Value) -> Value {
    match value {
        Value::String(text) => Value::String(bound_string(&redact(text))),
        Value::Array(items) => Value::Array(items.iter().map(bound_value).collect()),
        Value::Object(map) => {
            let mut out = Map::new();
            for (key, item) in map {
                out.insert(bound_string(&redact(key)), bound_value(item));
            }
            Value::Object(out)
        }
        other => other.clone(),
    }
}

/// A hook value that carries a JSON document.
///
/// The host's hook payload is a `HashMap<String, String>`, so a nested
/// document arrives serialized. An already-parsed object is accepted too, so a
/// host that stops stringifying does not break the parse.
pub fn object(value: Option<&Value>) -> Option<Value> {
    match value? {
        Value::String(text) => serde_json::from_str(text).ok(),
        other => Some(other.clone()),
    }
}

/// A number the host serialized into a string.
fn number(value: &Value) -> Option<Value> {
    match value {
        Value::Number(number) => Some(Value::Number(number.clone())),
        Value::String(text) => serde_json::from_str::<u64>(text).ok().map(Value::from),
        _ => None,
    }
}

/// A boolean the host serialized into a string.
fn boolean(value: &Value) -> Option<Value> {
    match value {
        Value::Bool(_) => Some(value.clone()),
        Value::String(text) => serde_json::from_str::<bool>(text).ok().map(Value::Bool),
        _ => None,
    }
}

/// Cap one stored body, keeping its head and marking the cut.
///
/// A body is re-redacted before the cap: the host already masked credential
/// headers and redacted the payload, and this is the second pass.
pub fn bound_body(input: &str) -> String {
    let redacted = redact(input);
    let chars = redacted.chars().count();
    if chars <= MAX_BODY_CHARS {
        return redacted;
    }
    let mut out: String = redacted.chars().take(MAX_BODY_CHARS).collect();
    out.push_str(&format!("\n<truncated: {chars} chars>"));
    out
}

/// Head of a stored body for the overview panel, marked when it is cut.
fn preview(text: &str, limit: usize) -> String {
    let chars = text.chars().count();
    if chars <= limit {
        return text.to_string();
    }
    let head: String = text.chars().take(limit).collect();
    format!("{head}\n<truncated: {chars} chars>")
}

// --- record building ---------------------------------------------------------

/// Build one stored record from one hook event. Shape only: no message text,
/// no response text, no bodies (the host never sends bodies anyway).
pub fn build_record(point: &str, event: &Value, ts: u64) -> Option<Value> {
    if !POINTS.contains(&point) {
        return None;
    }
    let mut record = Map::new();
    record.insert("point".into(), json!(point));
    record.insert("ts".into(), json!(ts));
    match point {
        "http.exchange" => {
            for key in [
                "source",
                "request_id",
                "method",
                "host",
                "path",
                "status",
                "request_bytes",
                "response_bytes",
                "content_type",
                "ttfb_ms",
                "total_ms",
                "error",
            ] {
                if let Some(value) = event.get(key) {
                    record.insert(key.into(), bound_value(value));
                }
            }
            // The tap masks credential header values and redacts a body before
            // it publishes the exchange; bound_value / bound_body re-redact and
            // size-cap here, so a stored record is safe whatever the host sent.
            for key in ["request_headers", "response_headers"] {
                if let Some(value) = event.get(key) {
                    record.insert(key.into(), bound_value(value));
                }
            }
            for key in ["request_body", "response_body"] {
                if let Some(text) = event.get(key).and_then(Value::as_str) {
                    if !text.is_empty() {
                        record.insert(key.into(), Value::String(bound_body(text)));
                    }
                }
            }
            if let Some(flag) = event.get("body_truncated") {
                record.insert("body_truncated".into(), flag.clone());
            }
        }
        "model.request" => {
            let data = event.get("data")?;
            for key in ["model", "request_id"] {
                if let Some(value) = data.get(key) {
                    record.insert(key.into(), bound_value(value));
                }
            }
            if let Some(agent) = event.get("agent") {
                record.insert("agent".into(), bound_value(agent));
            }
            // The host's hook values are strings, and it caps a value at 8 KiB,
            // so a large request arrives as truncated JSON. Keeping the event
            // matters more than its counts: an unparsed document is marked
            // instead of dropping the record (the raw body is on the
            // http.exchange record for the same request_id).
            let request = object(data.get("request"));
            if let Some(request) = request.as_ref() {
                for key in ["api_mode", "temperature", "max_tokens"] {
                    if let Some(value) = request.get(key) {
                        record.insert(key.into(), bound_value(value));
                    }
                }
                if let Some(bytes) = request.get("prompt_bytes").and_then(number) {
                    record.insert("prompt_bytes".into(), bytes);
                }
            } else if let Some(text) = data.get("request").and_then(Value::as_str) {
                record.insert(
                    "request_document".into(),
                    Value::String(format!(
                        "<unparsed: {} chars; the host caps a hook value at 8 KiB>",
                        text.chars().count()
                    )),
                );
            }
            let mut role_counts: Map<String, Value> = Map::new();
            let mut count = 0u64;
            if let Some(messages) = request
                .as_ref()
                .and_then(|request| request.get("messages"))
                .and_then(Value::as_array)
            {
                for message in messages {
                    count += 1;
                    if let Some(role) = message.get("role").and_then(Value::as_str) {
                        let entry = role_counts.entry(role.to_string()).or_insert(json!(0));
                        *entry = json!(entry.as_u64().unwrap_or(0) + 1);
                    }
                }
            }
            record.insert("message_count".into(), json!(count));
            record.insert("role_counts".into(), Value::Object(role_counts));
            // message text is deliberately never copied
        }
        "model.response" => {
            let data = event.get("data")?;
            for key in ["request_id", "response_type"] {
                if let Some(value) = data.get(key) {
                    record.insert(key.into(), bound_value(value));
                }
            }
            if let Some(agent) = event.get("agent") {
                record.insert("agent".into(), bound_value(agent));
            }
            // Same string envelope as the request: the react response document
            // is where the usage numbers live.
            if let Some(response) = object(data.get("response")) {
                if let Some(usage) = response.get("usage") {
                    for key in ["prompt_tokens", "completion_tokens", "total_tokens"] {
                        if let Some(value) = usage.get(key).and_then(number) {
                            record.insert(key.into(), value);
                        }
                    }
                }
                for key in ["response_bytes", "had_tool_call"] {
                    if let Some(value) = response.get(key) {
                        record.insert(key.into(), bound_value(value));
                    }
                }
            }
            // The stream event reports the size and the tool-call flag on `data`.
            if !record.contains_key("response_bytes") {
                if let Some(bytes) = data.get("response_bytes").and_then(number) {
                    record.insert("response_bytes".into(), bytes);
                }
            }
            if !record.contains_key("had_tool_call") {
                if let Some(flag) = data.get("had_tool_call").and_then(boolean) {
                    record.insert("had_tool_call".into(), flag);
                }
            }
            // response_text is deliberately never copied
        }
        _ => return None,
    }
    Some(Value::Object(record))
}

/// Cap one record's serialized size; an oversized record keeps only its point
/// and timestamp plus an honest marker.
pub fn bound_record(record: Value) -> Value {
    let size = serde_json::to_string(&record)
        .map(|text| text.len())
        .unwrap_or(usize::MAX);
    if size <= MAX_RECORD_BYTES {
        return record;
    }
    json!({
        "point": record.get("point").cloned().unwrap_or(Value::Null),
        "ts": record.get("ts").cloned().unwrap_or(Value::Null),
        "note": format!("<record too large: {size} bytes; fields dropped>"),
    })
}

// --- bounded store -----------------------------------------------------------

pub fn empty_store() -> Value {
    json!({"records": [], "evicted": 0})
}

fn read_store() -> Value {
    host(json!({"op": "storage_get", "key": STORE_KEY}))
        .and_then(|value| value.get("text").cloned())
        .and_then(|text| {
            text.as_str()
                .and_then(|text| serde_json::from_str(text).ok())
        })
        .unwrap_or_else(empty_store)
}

fn write_store(store: &Value) -> bool {
    host(json!({
        "op": "storage_set",
        "key": STORE_KEY,
        "data": store.to_string(),
    }))
    .is_some()
}

/// Append records and evict the oldest beyond MAX_RECORDS. Pure over a store
/// value so tests can exercise the bound without the host.
pub fn append_records(store: &mut Value, records: Vec<Value>) {
    let mut evicted = store.get("evicted").and_then(Value::as_u64).unwrap_or(0);
    let Some(array_value) = store.get_mut("records") else {
        return;
    };
    let Some(array) = array_value.as_array_mut() else {
        return;
    };
    for record in records {
        array.push(bound_record(record));
    }
    while array.len() > MAX_RECORDS {
        array.remove(0);
        evicted += 1;
    }
    prune_bodies(array);
    if let Some(slot) = store.get_mut("evicted") {
        *slot = json!(evicted);
    }
}

/// Keep bodies on the newest exchanges only.
///
/// Bodies are the largest thing a record carries, and a body that outlives its
/// usefulness still costs every later store rewrite. The metadata and headers
/// stay; the record says the body was dropped rather than pretending it never
/// existed.
fn prune_bodies(records: &mut [Value]) {
    let mut kept = 0;
    for record in records.iter_mut().rev() {
        let Some(map) = record.as_object_mut() else {
            continue;
        };
        if !map.contains_key("request_body") && !map.contains_key("response_body") {
            continue;
        }
        if kept < MAX_BODY_RECORDS {
            kept += 1;
            continue;
        }
        map.remove("request_body");
        map.remove("response_body");
        map.insert(
            "bodies".into(),
            Value::String(format!(
                "<dropped: only the newest {MAX_BODY_RECORDS} exchanges keep bodies>"
            )),
        );
    }
}

// --- host entry points -------------------------------------------------------

#[plugin_fn]
pub fn bsh_hook(input: String) -> FnResult<String> {
    let payload: Value = serde_json::from_str(&input).unwrap_or(Value::Null);
    let point = payload
        .get("point")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    if POINTS.contains(&point.as_str()) {
        let ts = host(json!({"op": "now_millis"}))
            .and_then(|value| value.as_u64())
            .unwrap_or(0);
        let empty = Vec::new();
        let batch = payload
            .get("batch")
            .and_then(Value::as_array)
            .unwrap_or(&empty);
        let mut store = read_store();
        let records: Vec<Value> = batch
            .iter()
            .filter_map(|event| build_record(&point, event, ts))
            .collect();
        let added = records.len();
        append_records(&mut store, records);
        if added > 0 && !write_store(&store) {
            // Never fail the host's send because capture storage hiccuped.
            let _ = host(json!({
                "op": "log",
                "message": "llmsniff: storage_set failed; batch not persisted",
            }));
        }
    }
    Ok(json!({"action": "continue"}).to_string())
}

#[plugin_fn]
pub fn bsh_tools(_input: String) -> FnResult<String> {
    Ok(json!([
        {
            "id": "captures",
            "description": format!(
                "List the newest redacted LLM-traffic records captured from the BSH host's observe hooks (host-mediated traffic only). Each row carries metadata and the masked request/response headers; bodies are read one exchange at a time with the `exchange` tool, and the newest {MAX_BODY_RECORDS} exchanges keep them."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many records to return, newest first (1-100, default 20).",
                        "minimum": 1,
                        "maximum": 100
                    },
                    "point": {
                        "type": "string",
                        "enum": ["http.exchange", "model.request", "model.response"],
                        "description": "Only records from this hook point."
                    }
                },
                "additionalProperties": false
            },
            "capabilities": []
        },
        {
            "id": "exchange",
            "description": format!(
                "Return one captured LLM exchange with its stored request and response headers and bodies (up to {MAX_BODY_CHARS} characters per side; the host cut a body at 32 KiB and body_truncated says so). Pass a request_id from `captures`; without one the newest exchange is returned. Exchanges older than the newest {MAX_BODY_RECORDS} no longer keep bodies."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "string",
                        "description": "The exchange to read. Defaults to the newest http.exchange record."
                    },
                    "include_headers": {
                        "type": "boolean",
                        "description": "Include request and response headers. Default true."
                    }
                },
                "additionalProperties": false
            },
            "capabilities": []
        }
    ])
    .to_string())
}

#[plugin_fn]
pub fn bsh_call_tool(input: String) -> FnResult<String> {
    let input: Value = serde_json::from_str(&input).unwrap_or(json!({}));
    let name = input
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let args = input.get("arguments").cloned().unwrap_or(json!({}));
    let result = match name {
        "captures" => captures_result(&args),
        "exchange" => exchange_result(&args),
        other => error_result(format!(
            "unknown tool '{other}': this plugin serves 'captures' and 'exchange'"
        )),
    };
    Ok(result.to_string())
}

/// The `captures` envelope: listing rows with metadata and headers, no bodies.
fn captures_result(args: &Value) -> Value {
    let limit = args
        .get("limit")
        .and_then(Value::as_u64)
        .unwrap_or(20)
        .clamp(1, 100) as usize;
    let point = args.get("point").and_then(Value::as_str);
    if let Some(point) = point {
        if !POINTS.contains(&point) {
            return error_result(format!(
                "unknown point '{point}': expected one of http.exchange, model.request, model.response"
            ));
        }
    }
    let store = read_store();
    let records_array = store
        .get("records")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let total = records_array.len();
    let evicted = store.get("evicted").and_then(Value::as_u64).unwrap_or(0);
    let with_bodies = records_array
        .iter()
        .filter(|record| has_bodies(record))
        .count();
    let records: Vec<Value> = records_array
        .iter()
        .rev()
        .filter(|record| point.is_none() || record.get("point").and_then(Value::as_str) == point)
        .take(limit)
        .map(strip_bodies)
        .collect();
    ok_result(&json!({
        "capture": format!(
            "host-mediated LLM traffic only (BSH observe hooks); metadata and masked headers. Bodies: call `exchange` with a request_id (the newest {MAX_BODY_RECORDS} exchanges keep up to {MAX_BODY_CHARS} characters per side)"
        ),
        "stored": total,
        "evicted_oldest": evicted,
        "with_bodies": with_bodies,
        "body_limit_chars": MAX_BODY_CHARS,
        "bodies_kept_for": MAX_BODY_RECORDS,
        "returned": records.len(),
        "records": records,
    }))
}

/// The `exchange` envelope: one record with everything it still holds.
fn exchange_result(args: &Value) -> Value {
    let request_id = args.get("request_id").and_then(Value::as_str);
    let include_headers = args
        .get("include_headers")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let store = read_store();
    let records = store
        .get("records")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let Some(mut record) = select_exchange(&records, request_id) else {
        let recent: Vec<&str> = records
            .iter()
            .rev()
            .filter(|record| record.get("point").and_then(Value::as_str) == Some("http.exchange"))
            .filter_map(|record| record.get("request_id").and_then(Value::as_str))
            .take(5)
            .collect();
        return error_result(format!(
            "no http.exchange record{}; recent request ids: {}",
            request_id
                .map(|id| format!(" for '{id}'"))
                .unwrap_or_default(),
            if recent.is_empty() {
                "none".to_string()
            } else {
                recent.join(", ")
            },
        ));
    };
    if !include_headers {
        if let Some(map) = record.as_object_mut() {
            map.remove("request_headers");
            map.remove("response_headers");
        }
    }
    ok_result(&json!({
        "capture": "one host-mediated LLM exchange",
        "body_limit_chars": MAX_BODY_CHARS,
        "record": record,
    }))
}

/// The newest exchange, or the newest one for a given request id.
fn select_exchange(records: &[Value], request_id: Option<&str>) -> Option<Value> {
    records
        .iter()
        .rev()
        .find(|record| {
            record.get("point").and_then(Value::as_str) == Some("http.exchange")
                && request_id.map_or(true, |id| {
                    record.get("request_id").and_then(Value::as_str) == Some(id)
                })
        })
        .cloned()
}

fn has_bodies(record: &Value) -> bool {
    record.get("request_body").is_some() || record.get("response_body").is_some()
}

/// A listing row: bodies out, a flag saying the exchange still has them.
fn strip_bodies(record: &Value) -> Value {
    let mut record = record.clone();
    let had_bodies = has_bodies(&record);
    if let Some(map) = record.as_object_mut() {
        map.remove("request_body");
        map.remove("response_body");
        if had_bodies {
            map.insert("has_bodies".into(), Value::Bool(true));
        }
    }
    record
}

fn ok_result(summary: &Value) -> Value {
    json!({
        "content": [{
            "type": "text",
            "text": serde_json::to_string_pretty(summary).unwrap_or_default()
        }],
        "structuredContent": summary,
        "isError": false
    })
}

fn error_result(message: String) -> Value {
    json!({
        "content": [{
            "type": "text",
            "text": message
        }],
        "isError": true
    })
}

/// One table cell: numbers and flags are legal content, and a structured value
/// is compacted so one odd field cannot reject the whole panel document.
fn cell(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(text)) => text.clone(),
        Some(Value::Null) | None => "—".to_string(),
        Some(other) => {
            let text = other.to_string();
            let chars = text.chars().count();
            if chars > 120 {
                format!("{}…", text.chars().take(120).collect::<String>())
            } else {
                text
            }
        }
    }
}

fn table(columns: &[&str], rows: Vec<Vec<String>>) -> Value {
    json!({"type": "table", "columns": columns, "rows": rows})
}

fn text_node(text: String) -> Value {
    json!({"type": "text", "text": text})
}

fn heading_node(text: &str, level: u8) -> Value {
    json!({"type": "heading", "text": text, "level": level})
}

/// The text of a message's `content`, whether it is a string or a list of parts.
fn content_text(content: &Value) -> String {
    match content {
        Value::String(text) => text.clone(),
        Value::Array(parts) => parts
            .iter()
            .filter_map(|part| part.get("text").and_then(Value::as_str))
            .collect::<Vec<_>>()
            .join(" "),
        _ => String::new(),
    }
}

/// A one-line preview of message text, cut on a character boundary.
fn line_preview(text: &str, limit: usize) -> String {
    let flat: String = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= limit {
        return flat;
    }
    format!("{}…", flat.chars().take(limit).collect::<String>())
}

fn header_rows(headers: Option<&Value>, limit: usize) -> Vec<Vec<String>> {
    let Some(map) = headers.and_then(Value::as_object) else {
        return Vec::new();
    };
    map.iter()
        .take(limit)
        .map(|(name, value)| vec![name.clone(), cell(Some(value))])
        .collect()
}

/// The request a provider received, read back into a structure.
#[derive(Default)]
struct RequestShape {
    model: Option<String>,
    stream: Option<bool>,
    temperature: Option<String>,
    max_tokens: Option<u64>,
    count: usize,
    roles: std::collections::BTreeMap<String, usize>,
    chars: usize,
    tools: usize,
    /// The first few messages, as (role, characters, preview).
    messages: Vec<(String, usize, String)>,
}

fn request_shape(body: &str) -> RequestShape {
    let mut shape = RequestShape::default();
    let Ok(value) = serde_json::from_str::<Value>(body) else {
        return shape;
    };
    shape.model = value
        .get("model")
        .and_then(Value::as_str)
        .map(str::to_string);
    shape.stream = value.get("stream").and_then(Value::as_bool);
    shape.temperature = value.get("temperature").map(|value| cell(Some(value)));
    shape.max_tokens = value.get("max_tokens").and_then(Value::as_u64);
    shape.tools = value
        .get("tools")
        .and_then(Value::as_array)
        .map_or(0, Vec::len);
    if let Some(messages) = value.get("messages").and_then(Value::as_array) {
        for message in messages {
            let role = message
                .get("role")
                .and_then(Value::as_str)
                .unwrap_or("?")
                .to_string();
            let content = message.get("content").cloned().unwrap_or(Value::Null);
            let text = content_text(&content);
            let chars = text.chars().count();
            shape.chars += chars;
            *shape.roles.entry(role.clone()).or_insert(0) += 1;
            shape.count += 1;
            if shape.messages.len() < 6 {
                shape.messages.push((role, chars, line_preview(&text, 80)));
            }
        }
    }
    shape
}

/// The response a provider returned, read back into a structure: a whole JSON
/// document, or the SSE events a streamed answer is made of.
#[derive(Default)]
struct ResponseShape {
    streaming: bool,
    parsed: bool,
    events: usize,
    done: bool,
    finish_reason: Option<String>,
    content_chars: usize,
    tool_calls: usize,
    usage: Option<(u64, u64, u64)>,
    model: Option<String>,
}

fn response_shape(body: &str) -> ResponseShape {
    let mut shape = ResponseShape::default();
    if !body
        .lines()
        .any(|line| line.trim_start().starts_with("data:"))
    {
        if let Ok(value) = serde_json::from_str::<Value>(body) {
            shape.parsed = true;
            shape.usage = usage_of(&value);
            shape.model = value
                .get("model")
                .and_then(Value::as_str)
                .map(str::to_string);
            if let Some(choices) = value.get("choices").and_then(Value::as_array) {
                for choice in choices {
                    if let Some(reason) = choice.get("finish_reason").and_then(Value::as_str) {
                        shape.finish_reason = Some(reason.to_string());
                    }
                    if let Some(message) = choice.get("message") {
                        shape.content_chars += message
                            .get("content")
                            .map(|content| content_text(content).chars().count())
                            .unwrap_or(0);
                        shape.tool_calls += message
                            .get("tool_calls")
                            .and_then(Value::as_array)
                            .map_or(0, Vec::len);
                    }
                }
            }
        }
        return shape;
    }
    shape.streaming = true;
    shape.parsed = true;
    for line in body.lines() {
        let Some(payload) = line.trim_start().strip_prefix("data:") else {
            continue;
        };
        let payload = payload.trim();
        if payload.is_empty() {
            continue;
        }
        shape.events += 1;
        if payload == "[DONE]" {
            shape.done = true;
            continue;
        }
        let Ok(value) = serde_json::from_str::<Value>(payload) else {
            continue;
        };
        if shape.model.is_none() {
            shape.model = value
                .get("model")
                .and_then(Value::as_str)
                .map(str::to_string);
        }
        if let Some(usage) = usage_of(&value) {
            shape.usage = Some(usage);
        }
        if let Some(choices) = value.get("choices").and_then(Value::as_array) {
            for choice in choices {
                if let Some(reason) = choice.get("finish_reason").and_then(Value::as_str) {
                    shape.finish_reason = Some(reason.to_string());
                }
                let delta = choice.get("delta").or_else(|| choice.get("message"));
                if let Some(content) = delta.and_then(|delta| delta.get("content")) {
                    shape.content_chars += content_text(content).chars().count();
                }
                if let Some(calls) = delta
                    .and_then(|delta| delta.get("tool_calls"))
                    .and_then(Value::as_array)
                {
                    shape.tool_calls += calls.len();
                }
            }
        }
    }
    shape
}

fn usage_of(value: &Value) -> Option<(u64, u64, u64)> {
    let usage = value.get("usage")?;
    Some((
        usage
            .get("prompt_tokens")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        usage
            .get("completion_tokens")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        usage
            .get("total_tokens")
            .and_then(Value::as_u64)
            .unwrap_or(0),
    ))
}

#[plugin_fn]
pub fn bsh_panel(_input: String) -> FnResult<String> {
    let store = read_store();
    let records = store
        .get("records")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let evicted = store.get("evicted").and_then(Value::as_u64).unwrap_or(0);
    let mut children = vec![
        json!({"type": "heading", "text": "LLM Sniffer", "level": 2}),
        text_node(format!(
            "Host-mediated LLM traffic only (BSH observe hooks). Metadata, masked headers and request/response bodies (newest {MAX_BODY_RECORDS} exchanges, {MAX_BODY_CHARS} chars per side); credentials are redacted before storage."
        )),
        text_node(format!(
            "Stored: {} records ({} oldest evicted; bound is {MAX_RECORDS})",
            records.len(),
            evicted
        )),
    ];
    let mut counts: Map<String, Value> = Map::new();
    for record in &records {
        if let Some(point) = record.get("point").and_then(Value::as_str) {
            let entry = counts.entry(point.to_string()).or_insert(json!(0));
            *entry = json!(entry.as_u64().unwrap_or(0) + 1);
        }
    }
    if !counts.is_empty() {
        let summary = counts
            .iter()
            .map(|(point, count)| format!("{point} {}", count.as_u64().unwrap_or(0)))
            .collect::<Vec<_>>()
            .join(" · ");
        children.push(text_node(format!("By point: {summary}")));
    }

    // The recent list: metadata only, one row per exchange.
    let mut rows = Vec::new();
    for record in records.iter().rev() {
        if record.get("point").and_then(Value::as_str) != Some("http.exchange") {
            continue;
        }
        if rows.len() >= 8 {
            break;
        }
        rows.push(vec![
            cell(record.get("method")),
            cell(record.get("host")),
            cell(record.get("path")),
            cell(record.get("status")),
            format!(
                "{} ms",
                record.get("total_ms").and_then(Value::as_u64).unwrap_or(0)
            ),
        ]);
    }
    if !rows.is_empty() {
        children.push(table(
            &["Method", "Host", "Path", "Status", "Latency"],
            rows,
        ));
    }

    let mut prompt_tokens = 0u64;
    let mut completion_tokens = 0u64;
    let mut total_tokens = 0u64;
    for record in &records {
        if record.get("point").and_then(Value::as_str) != Some("model.response") {
            continue;
        }
        prompt_tokens += record
            .get("prompt_tokens")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        completion_tokens += record
            .get("completion_tokens")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        total_tokens += record
            .get("total_tokens")
            .and_then(Value::as_u64)
            .unwrap_or(0);
    }
    if total_tokens > 0 {
        children.push(text_node(format!(
            "Tokens (captured responses): {prompt_tokens} prompt / {completion_tokens} completion / {total_tokens} total"
        )));
    }
    if records.is_empty() {
        children.push(text_node(
            "No captures yet. Capture needs the hooks.observe grant: bsh ext grant com.open1s.llmsniff hooks.observe"
                .to_string(),
        ));
    }

    if let Some(newest) = records
        .iter()
        .rev()
        .find(|record| record.get("point").and_then(Value::as_str) == Some("http.exchange"))
    {
        children.push(json!({"type": "divider"}));
        children.push(heading_node("Newest exchange", 3));
        children.push(text_node(format!(
            "{} {}{} → {} · {} ms · {} B request / {} B response{}",
            cell(newest.get("method")),
            cell(newest.get("host")),
            cell(newest.get("path")),
            cell(newest.get("status")),
            newest.get("total_ms").and_then(Value::as_u64).unwrap_or(0),
            newest
                .get("request_bytes")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            newest
                .get("response_bytes")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            if newest.get("body_truncated").and_then(Value::as_bool) == Some(true) {
                " · the host cut a body at 32 KiB"
            } else {
                ""
            },
        )));

        if let Some(body) = newest.get("request_body").and_then(Value::as_str) {
            let shape = request_shape(body);
            let rows = vec![
                vec![
                    "Model".to_string(),
                    shape.model.clone().unwrap_or_else(|| "—".to_string()),
                ],
                vec![
                    "Stream".to_string(),
                    shape
                        .stream
                        .map(|stream| stream.to_string())
                        .unwrap_or_else(|| "—".to_string()),
                ],
                vec![
                    "Temperature".to_string(),
                    shape.temperature.clone().unwrap_or_else(|| "—".to_string()),
                ],
                vec![
                    "Max tokens".to_string(),
                    shape
                        .max_tokens
                        .map(|tokens| tokens.to_string())
                        .unwrap_or_else(|| "—".to_string()),
                ],
                vec!["Messages".to_string(), shape.count.to_string()],
                vec![
                    "Roles".to_string(),
                    shape
                        .roles
                        .iter()
                        .map(|(role, count)| format!("{role} {count}"))
                        .collect::<Vec<_>>()
                        .join(" · "),
                ],
                vec!["Content".to_string(), format!("{} chars", shape.chars)],
                vec!["Tools".to_string(), shape.tools.to_string()],
            ];
            children.push(heading_node("Request structure", 4));
            children.push(table(&["Field", "Value"], rows));

            if shape.count > 0 {
                let shown = shape.messages.len();
                let title = if shown < shape.count {
                    format!("Messages (first {shown} of {})", shape.count)
                } else {
                    format!("Messages ({shown})")
                };
                children.push(heading_node(&title, 4));
                let mut message_rows = Vec::new();
                for (index, (role, chars, preview)) in shape.messages.iter().enumerate() {
                    message_rows.push(vec![
                        format!("{}", index + 1),
                        role.clone(),
                        chars.to_string(),
                        preview.clone(),
                    ]);
                }
                children.push(table(&["#", "Role", "Chars", "Preview"], message_rows));
                if shape.count > shown {
                    children.push(text_node(format!(
                        "…and {} more messages; the exchange tool has the full body.",
                        shape.count - shown
                    )));
                }
            }
        } else if let Some(marker) = newest.get("bodies").and_then(Value::as_str) {
            children.push(text_node(marker.to_string()));
        }

        if let Some(body) = newest.get("response_body").and_then(Value::as_str) {
            let shape = response_shape(body);
            let mut rows = vec![
                vec!["Status".to_string(), cell(newest.get("status"))],
                vec!["Content type".to_string(), cell(newest.get("content_type"))],
                vec![
                    "Bytes".to_string(),
                    format!(
                        "{} B",
                        newest
                            .get("response_bytes")
                            .and_then(Value::as_u64)
                            .unwrap_or(0)
                    ),
                ],
                vec![
                    "TTFB".to_string(),
                    format!(
                        "{} ms",
                        newest.get("ttfb_ms").and_then(Value::as_u64).unwrap_or(0)
                    ),
                ],
                vec![
                    "Total".to_string(),
                    format!(
                        "{} ms",
                        newest.get("total_ms").and_then(Value::as_u64).unwrap_or(0)
                    ),
                ],
                vec![
                    "Streaming".to_string(),
                    if shape.streaming { "yes" } else { "no" }.to_string(),
                ],
            ];
            if shape.streaming {
                rows.push(vec!["SSE events".to_string(), shape.events.to_string()]);
                rows.push(vec![
                    "Done marker".to_string(),
                    if shape.done { "yes" } else { "no" }.to_string(),
                ]);
            }
            if let Some(reason) = shape.finish_reason.clone() {
                rows.push(vec!["Finish reason".to_string(), reason]);
            }
            rows.push(vec![
                "Content".to_string(),
                format!("{} chars", shape.content_chars),
            ]);
            if shape.tool_calls > 0 {
                rows.push(vec!["Tool calls".to_string(), shape.tool_calls.to_string()]);
            }
            if let Some((prompt, completion, total)) = shape.usage {
                rows.push(vec![
                    "Tokens".to_string(),
                    format!("{prompt} prompt / {completion} completion / {total} total"),
                ]);
            }
            if let Some(model) = shape.model.clone() {
                rows.push(vec!["Model".to_string(), model]);
            }
            children.push(heading_node("Response structure", 4));
            children.push(table(&["Field", "Value"], rows));
        }

        for (label, key) in [
            ("Request headers", "request_headers"),
            ("Response headers", "response_headers"),
        ] {
            let rows = header_rows(newest.get(key), 10);
            if !rows.is_empty() {
                children.push(heading_node(label, 4));
                children.push(table(&["Header", "Value"], rows));
            }
        }

        children.push(text_node(
            "Full bodies: call the exchange tool with a request_id.".to_string(),
        ));
        for (label, key) in [
            ("Request body", "request_body"),
            ("Response body", "response_body"),
        ] {
            if let Some(body) = newest.get(key).and_then(Value::as_str) {
                children.push(heading_node(label, 4));
                children.push(json!({
                    "type": "code",
                    "language": if key == "request_body" { "json" } else { "text" },
                    "value": preview(body, PANEL_BODY_CHARS),
                }));
            }
        }
    }

    Ok(json!({
        "schema_version": "1.0",
        "revision": 1,
        "root": {"type": "column", "children": children}
    })
    .to_string())
}

#[plugin_fn]
pub fn bsh_event(_input: String) -> FnResult<String> {
    Ok("{}".to_string())
}

// --- leak-detecting fixture tests --------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    const FAKE_KEY: &str = "sk-fake1234567890abcdef";
    const FAKE_BEARER: &str = "Bearer tok_abcdefgh1234567890";

    #[test]
    fn redact_masks_markers() {
        let out = redact(&format!("auth: {FAKE_KEY} and {FAKE_BEARER}"));
        assert!(!out.contains(FAKE_KEY), "sk- value leaked: {out}");
        assert!(
            !out.contains("tok_abcdefgh1234567890"),
            "bearer leaked: {out}"
        );
        assert!(out.contains("sk-***"));
        assert!(out.contains("Bearer ***"));
    }

    #[test]
    fn bound_string_caps_long_values() {
        let long = "x".repeat(10_000);
        let out = bound_string(&long);
        assert_eq!(out, format!("<truncated: 10000 chars>"));
        assert!(out.len() < 100);
    }

    #[test]
    fn http_exchange_record_keeps_shape() {
        let event = json!({
            "source": "llm",
            "request_id": "req-1",
            "method": "POST",
            "host": "api.openai.com",
            "path": "/v1/chat/completions",
            "status": 200,
            "request_bytes": 1024,
            "response_bytes": 2048,
            "content_type": "application/json",
            "ttfb_ms": 120,
            "total_ms": 340,
            "error": ""
        });
        let record = build_record("http.exchange", &event, 7).expect("record");
        assert_eq!(record["request_id"], "req-1");
        assert_eq!(record["status"], 200);
        assert_eq!(record["total_ms"], 340);
        assert_eq!(record["ts"], 7);
    }

    #[test]
    fn model_request_record_never_stores_message_text() {
        let event = json!({
            "agent": "main",
            "data": {
                "model": "gpt-test",
                "request_id": "req-2",
                "request": {
                    "model": "gpt-test",
                    "api_mode": "chat",
                    "temperature": 0.7,
                    "max_tokens": 512,
                    "prompt_bytes": 4096,
                    "messages": [
                        {"role": "system", "bytes": 64, "preview": format!("you are a test, key {FAKE_KEY}")},
                        {"role": "user", "bytes": 32, "preview": "hello"},
                        {"role": "assistant", "bytes": 16, "preview": "hi"}
                    ]
                }
            }
        });
        let record = build_record("model.request", &event, 9).expect("record");
        let serialized = record.to_string();
        assert!(
            !serialized.contains(FAKE_KEY),
            "message text leaked: {serialized}"
        );
        assert!(
            !serialized.contains("you are a test"),
            "preview text leaked: {serialized}"
        );
        assert_eq!(record["message_count"], 3);
        assert_eq!(record["role_counts"]["user"], 1);
        assert_eq!(record["role_counts"]["assistant"], 1);
        assert_eq!(record["role_counts"]["system"], 1);
        assert_eq!(record["prompt_bytes"], 4096);
    }

    #[test]
    fn model_response_record_never_stores_response_text() {
        let event = json!({
            "agent": "main",
            "data": {
                "request_id": "req-3",
                "response_type": "stream",
                "response": {
                    "response_bytes": 2048,
                    "response_text": format!("answer with {FAKE_KEY} inside"),
                    "had_tool_call": false
                }
            }
        });
        let record = build_record("model.response", &event, 11).expect("record");
        let serialized = record.to_string();
        assert!(
            !serialized.contains(FAKE_KEY),
            "response text leaked: {serialized}"
        );
        assert!(
            !serialized.contains("answer with"),
            "response text leaked: {serialized}"
        );
        assert_eq!(record["response_bytes"], 2048);
        assert_eq!(record["had_tool_call"], false);
    }

    #[test]
    fn model_response_record_keeps_usage() {
        let event = json!({
            "agent": "main",
            "data": {
                "request_id": "req-4",
                "response_type": "react",
                "response": {
                    "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}
                }
            }
        });
        let record = build_record("model.response", &event, 13).expect("record");
        assert_eq!(record["prompt_tokens"], 100);
        assert_eq!(record["completion_tokens"], 40);
        assert_eq!(record["total_tokens"], 140);
    }

    /// The host sends hook values as strings, so the request document arrives
    /// serialized. This is the shape that actually reaches the plugin.
    #[test]
    fn model_request_record_parses_the_host_string_payload() {
        let request = json!({
            "request_id": "req-5",
            "model": "gpt-test",
            "api_mode": "chat",
            "temperature": 0.2,
            "max_tokens": 256,
            "prompt_bytes": 999,
            "messages": [
                {"role": "user", "bytes": 3},
                {"role": "assistant", "bytes": 4}
            ]
        })
        .to_string();
        let event = json!({
            "agent": "main",
            "data": {"model": "gpt-test", "request_id": "req-5", "request": request}
        });
        let record = build_record("model.request", &event, 21).expect("record");
        assert_eq!(record["message_count"], 2);
        assert_eq!(record["role_counts"]["user"], 1);
        assert_eq!(record["role_counts"]["assistant"], 1);
        assert_eq!(record["prompt_bytes"], 999);
        assert_eq!(record["api_mode"], "chat");
        assert_eq!(record["max_tokens"], 256);
    }

    /// The host caps a hook value at 8 KiB, so a real request arrives as
    /// truncated JSON. The record must survive; only the counts are lost.
    #[test]
    fn a_truncated_request_document_still_records_the_event() {
        let request = format!("{{\"messages\":[{}", "{\"role\":\"user\"},".repeat(600));
        let event = json!({
            "agent": "main",
            "data": {"model": "gpt-test", "request_id": "req-9", "request": request}
        });
        let record = build_record("model.request", &event, 33).expect("the event is kept");
        assert_eq!(record["model"], "gpt-test");
        assert_eq!(record["request_id"], "req-9");
        assert_eq!(record["message_count"], 0);
        assert!(record["request_document"]
            .as_str()
            .expect("a marker instead of counts")
            .contains("unparsed"));
    }

    #[test]
    fn model_response_record_parses_usage_from_the_host_string_payload() {
        let response = json!({
            "response_type": "react",
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}
        })
        .to_string();
        let event = json!({
            "agent": "main",
            "data": {"request_id": "req-6", "response_type": "react", "response": response}
        });
        let record = build_record("model.response", &event, 22).expect("record");
        assert_eq!(record["prompt_tokens"], 10);
        assert_eq!(record["completion_tokens"], 4);
        assert_eq!(record["total_tokens"], 14);
    }

    /// A streamed step reports its size and tool-call flag on `data`, not
    /// inside a response document.
    #[test]
    fn model_response_record_reads_the_stream_shape() {
        let event = json!({
            "agent": "main",
            "data": {
                "request_id": "req-7",
                "response_type": "stream",
                "response_bytes": "13",
                "response_text": "hi there",
                "had_tool_call": "false"
            }
        });
        let record = build_record("model.response", &event, 23).expect("record");
        assert_eq!(record["response_bytes"], 13);
        assert_eq!(record["had_tool_call"], false);
        let serialized = record.to_string();
        assert!(
            !serialized.contains("hi there"),
            "response text leaked: {serialized}"
        );
    }

    #[test]
    fn http_exchange_record_stores_masked_headers_and_redacted_bodies() {
        let event = json!({
            "source": "llm",
            "request_id": "req-8",
            "method": "POST",
            "host": "api.openai.com",
            "path": "/v1/chat/completions",
            "status": 200,
            "request_bytes": 120,
            "response_bytes": 240,
            "request_headers": {
                "content-type": "application/json",
                "authorization": "[redacted]"
            },
            "response_headers": {"content-type": "text/event-stream"},
            "request_body": format!("{{\"messages\":[{{\"content\":\"key {FAKE_KEY}\"}}]}}"),
            "response_body": "data: {\"choices\":[]}\n\n",
            "body_truncated": false
        });
        let record = build_record("http.exchange", &event, 31).expect("record");
        assert_eq!(
            record["request_headers"]["content-type"],
            "application/json"
        );
        assert_eq!(record["request_headers"]["authorization"], "[redacted]");
        assert_eq!(
            record["response_headers"]["content-type"],
            "text/event-stream"
        );
        let request = record["request_body"].as_str().expect("request body");
        assert!(!request.contains(FAKE_KEY), "credential leaked: {request}");
        assert!(request.contains("sk-***"));
        assert!(
            request.ends_with("\"}]}"),
            "the structure after the secret is kept: {request}"
        );
        assert!(record["response_body"]
            .as_str()
            .expect("response body")
            .contains("choices"));
        assert_eq!(record["body_truncated"], false);
    }

    #[test]
    fn a_long_body_keeps_its_head_and_marks_the_cut() {
        let long = "x".repeat(MAX_BODY_CHARS + 100);
        let bounded = bound_body(&long);
        assert!(bounded.starts_with("xxxx"));
        assert!(bounded.contains("<truncated:"));
        assert!(bounded.len() < long.len());
    }

    #[test]
    fn only_the_newest_exchanges_keep_bodies() {
        let mut store = empty_store();
        let records: Vec<Value> = (0..MAX_BODY_RECORDS + 3)
            .map(|index| {
                json!({
                    "point": "http.exchange",
                    "ts": index,
                    "request_id": format!("req-{index}"),
                    "request_body": format!("body-{index}")
                })
            })
            .collect();
        append_records(&mut store, records);
        let array = store["records"].as_array().expect("array");
        let kept: Vec<&Value> = array
            .iter()
            .filter(|record| record.get("request_body").is_some())
            .collect();
        assert_eq!(kept.len(), MAX_BODY_RECORDS);
        assert_eq!(
            kept.last().expect("newest")["request_id"],
            format!("req-{}", MAX_BODY_RECORDS + 2)
        );
        let dropped = array
            .iter()
            .find(|record| record.get("bodies").is_some())
            .expect("the oldest records say the body was dropped");
        assert!(dropped.get("request_body").is_none());
    }

    #[test]
    fn exchange_picks_the_newest_or_the_named_request() {
        let records = vec![
            json!({"point": "http.exchange", "request_id": "req-1", "request_body": "a"}),
            json!({"point": "model.request", "request_id": "req-2"}),
            json!({"point": "http.exchange", "request_id": "req-3", "request_body": "c"}),
        ];
        assert_eq!(
            select_exchange(&records, None).expect("newest")["request_id"],
            "req-3"
        );
        assert_eq!(
            select_exchange(&records, Some("req-1")).expect("named")["request_id"],
            "req-1"
        );
        assert!(
            select_exchange(&records, Some("req-2")).is_none(),
            "model records are not exchanges"
        );
    }

    #[test]
    fn a_listing_strips_bodies_and_flags_them() {
        let record = json!({
            "point": "http.exchange",
            "request_id": "req-1",
            "request_body": "x",
            "response_body": "y"
        });
        let listed = strip_bodies(&record);
        assert!(listed.get("request_body").is_none());
        assert!(listed.get("response_body").is_none());
        assert_eq!(listed["has_bodies"], true);
        let metadata = json!({"point": "model.request", "request_id": "req-2"});
        assert!(strip_bodies(&metadata).get("has_bodies").is_none());
    }

    #[test]
    fn request_shape_reads_the_wire_document() {
        let body = json!({
            "model": "gpt-test",
            "stream": true,
            "temperature": 0.2,
            "max_tokens": 512,
            "tools": [{"type": "function"}, {"type": "function"}],
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": [{"type": "text", "text": "hello there"}]}
            ]
        })
        .to_string();
        let shape = request_shape(&body);
        assert_eq!(shape.model.as_deref(), Some("gpt-test"));
        assert_eq!(shape.stream, Some(true));
        assert_eq!(shape.max_tokens, Some(512));
        assert_eq!(shape.count, 2);
        assert_eq!(shape.roles["system"], 1);
        assert_eq!(shape.roles["user"], 1);
        assert_eq!(shape.tools, 2);
        assert_eq!(shape.messages[1].2, "hello there");
    }

    #[test]
    fn response_shape_reads_sse_and_plain_bodies() {
        let sse = "data: {\"model\":\"gpt-test\",\"choices\":[{\"delta\":{\"content\":\"he\"}}]}\n\n\
                   data: {\"choices\":[{\"delta\":{\"content\":\"llo\"},\"finish_reason\":\"stop\"}]}\n\n\
                   data: {\"usage\":{\"prompt_tokens\":3,\"completion_tokens\":2,\"total_tokens\":5}}\n\n\
                   data: [DONE]\n\n";
        let shape = response_shape(sse);
        assert!(shape.streaming);
        assert!(shape.done);
        assert_eq!(shape.events, 4);
        assert_eq!(shape.content_chars, 5);
        assert_eq!(shape.finish_reason.as_deref(), Some("stop"));
        assert_eq!(shape.usage, Some((3, 2, 5)));

        let plain = json!({
            "model": "m",
            "choices": [{"message": {"content": "hi", "tool_calls": [{"id": "1"}]}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        })
        .to_string();
        let shape = response_shape(&plain);
        assert!(!shape.streaming);
        assert_eq!(shape.content_chars, 2);
        assert_eq!(shape.tool_calls, 1);
        assert_eq!(shape.finish_reason.as_deref(), Some("tool_calls"));
    }

    #[test]
    fn unknown_point_is_dropped() {
        let event = json!({"anything": true});
        assert!(build_record("tool.before", &event, 1).is_none());
    }

    #[test]
    fn store_bound_evicts_oldest() {
        let mut store = empty_store();
        let records: Vec<Value> = (0..250)
            .map(|index| json!({"point": "http.exchange", "ts": index, "seq": index}))
            .collect();
        append_records(&mut store, records);
        let array = store["records"].as_array().expect("array");
        assert_eq!(array.len(), MAX_RECORDS);
        assert_eq!(array[0]["ts"], 50, "oldest records must be evicted first");
        assert_eq!(array.last().expect("last")["ts"], 249);
        assert_eq!(store["evicted"], 50);
    }

    #[test]
    fn oversized_record_is_reduced_with_marker() {
        let record = json!({
            "point": "http.exchange",
            "ts": 1,
            "error": "y".repeat(MAX_RECORD_BYTES + 1_000)
        });
        let bound = bound_record(record);
        let serialized = bound.to_string();
        assert!(serialized.len() < MAX_RECORD_BYTES, "record not bounded");
        assert!(serialized.contains("record too large"));
    }
}
