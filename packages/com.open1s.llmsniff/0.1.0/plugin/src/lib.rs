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
const MAX_RECORD_BYTES: usize = 4096;
const MAX_FIELD_CHARS: usize = 256;
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
        let secret_len = after_marker
            .find(char::is_whitespace)
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
            let request = data.get("request")?;
            for key in ["api_mode", "temperature", "max_tokens", "prompt_bytes"] {
                if let Some(value) = request.get(key) {
                    record.insert(key.into(), bound_value(value));
                }
            }
            let mut role_counts: Map<String, Value> = Map::new();
            let mut count = 0u64;
            if let Some(messages) = request.get("messages").and_then(Value::as_array) {
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
            if let Some(response) = data.get("response") {
                if let Some(usage) = response.get("usage") {
                    for key in ["prompt_tokens", "completion_tokens", "total_tokens"] {
                        if let Some(value) = usage.get(key) {
                            record.insert(key.into(), bound_value(value));
                        }
                    }
                }
                for key in ["response_bytes", "had_tool_call"] {
                    if let Some(value) = response.get(key) {
                        record.insert(key.into(), bound_value(value));
                    }
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
        .and_then(|text| text.as_str().and_then(|text| serde_json::from_str(text).ok()))
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
    let mut evicted = store
        .get("evicted")
        .and_then(Value::as_u64)
        .unwrap_or(0);
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
    if let Some(slot) = store.get_mut("evicted") {
        *slot = json!(evicted);
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
    Ok(json!([{
        "id": "captures",
        "description": "Read the newest redacted LLM-traffic records captured from the BSH host's observe hooks. Host-mediated traffic only: metadata and redacted previews, never request or response bodies or conversation text.",
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
    }])
    .to_string())
}

#[plugin_fn]
pub fn bsh_call_tool(input: String) -> FnResult<String> {
    let input: Value = serde_json::from_str(&input).unwrap_or(json!({}));
    let name = input
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    if name != "captures" {
        return Ok(json!({
            "content": [{
                "type": "text",
                "text": format!("unknown tool '{name}': this plugin serves 'captures' only")
            }],
            "isError": true
        })
        .to_string());
    }
    let args = input.get("arguments").cloned().unwrap_or(json!({}));
    let limit = args
        .get("limit")
        .and_then(Value::as_u64)
        .unwrap_or(20)
        .clamp(1, 100) as usize;
    let point = args.get("point").and_then(Value::as_str);
    if let Some(point) = point {
        if !POINTS.contains(&point) {
            return Ok(json!({
                "content": [{
                    "type": "text",
                    "text": format!("unknown point '{point}': expected one of http.exchange, model.request, model.response")
                }],
                "isError": true
            })
            .to_string());
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
    let records: Vec<Value> = records_array
        .iter()
        .rev()
        .filter(|record| {
            point.is_none() || record.get("point").and_then(Value::as_str) == point
        })
        .take(limit)
        .cloned()
        .collect();
    let summary = json!({
        "capture": "host-mediated LLM traffic only (BSH observe hooks); metadata and redacted previews, never bodies or conversation text",
        "stored": total,
        "evicted_oldest": evicted,
        "returned": records.len(),
        "records": records,
    });
    Ok(json!({
        "content": [{
            "type": "text",
            "text": serde_json::to_string_pretty(&summary).unwrap_or_default()
        }],
        "structuredContent": summary,
        "isError": false
    })
    .to_string())
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
        json!({"type": "text", "text": "Host-mediated LLM traffic only (BSH observe hooks). Metadata and redacted previews; never request or response bodies or conversation text."}),
        json!({"type": "text", "text": format!("Stored: {} records ({} oldest evicted; bound is {MAX_RECORDS})", records.len(), evicted)}),
    ];
    let mut counts: Map<String, Value> = Map::new();
    for record in &records {
        if let Some(point) = record.get("point").and_then(Value::as_str) {
            let entry = counts.entry(point.to_string()).or_insert(json!(0));
            *entry = json!(entry.as_u64().unwrap_or(0) + 1);
        }
    }
    if !counts.is_empty() {
        children.push(json!({"type": "text", "text": format!("By point: {counts:?}")}));
    }
    let mut rows = Vec::new();
    for record in records.iter().rev() {
        if record.get("point").and_then(Value::as_str) != Some("http.exchange") {
            continue;
        }
        if rows.len() >= 8 {
            break;
        }
        rows.push(json!([
            record.get("method").cloned().unwrap_or(json!("?")),
            record.get("host").cloned().unwrap_or(json!("?")),
            record.get("path").cloned().unwrap_or(json!("?")),
            record.get("status").cloned().unwrap_or(json!("?")),
            format!("{} ms", record.get("total_ms").and_then(Value::as_u64).unwrap_or(0)),
        ]));
    }
    if !rows.is_empty() {
        children.push(json!({
            "type": "table",
            "columns": ["Method", "Host", "Path", "Status", "Latency"],
            "rows": rows
        }));
    }
    let mut prompt_tokens = 0u64;
    let mut completion_tokens = 0u64;
    let mut total_tokens = 0u64;
    for record in &records {
        if record.get("point").and_then(Value::as_str) != Some("model.response") {
            continue;
        }
        prompt_tokens += record.get("prompt_tokens").and_then(Value::as_u64).unwrap_or(0);
        completion_tokens += record
            .get("completion_tokens")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        total_tokens += record.get("total_tokens").and_then(Value::as_u64).unwrap_or(0);
    }
    if total_tokens > 0 {
        children.push(json!({"type": "text", "text": format!("Tokens (captured responses): {prompt_tokens} prompt / {completion_tokens} completion / {total_tokens} total")}));
    }
    if records.is_empty() {
        children.push(json!({"type": "text", "text": "No captures yet. Capture needs the hooks.observe grant: bsh ext grant com.open1s.llmsniff hooks.observe"}));
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
        assert!(!out.contains("tok_abcdefgh1234567890"), "bearer leaked: {out}");
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
        assert!(!serialized.contains(FAKE_KEY), "message text leaked: {serialized}");
        assert!(!serialized.contains("you are a test"), "preview text leaked: {serialized}");
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
        assert!(!serialized.contains(FAKE_KEY), "response text leaked: {serialized}");
        assert!(!serialized.contains("answer with"), "response text leaked: {serialized}");
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
            "error": "y".repeat(20_000)
        });
        let bound = bound_record(record);
        let serialized = bound.to_string();
        assert!(serialized.len() < MAX_RECORD_BYTES, "record not bounded");
        assert!(serialized.contains("record too large"));
    }
}
