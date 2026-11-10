# LLM Sniffer

Capture and parse the LLM API traffic the BSH host mediates, through the host's observe hooks (`http.exchange`, `model.request`, `model.response`), with credentials redacted before anything is stored or shown.

Id: com.open1s.llmsniff  Version: 0.1.0  Runtime: extism  Domain: security

## Scope (read this first)

Capture is **host-mediated traffic only**. The plugin sees what the BSH host sends to and receives from LLM provider APIs — it is not a system-wide sniffer, and traffic from other processes is invisible to it. Records hold metadata and redacted previews only: method, host, path, status, byte sizes, latency, token usage, message counts. Request and response bodies, header values, conversation text and credential values are never stored.

## How it works

- The host dispatches observe-hook batches to the plugin's `bsh_hook` export.
- The plugin re-redacts every string (defense in depth behind the host's own redaction), parses each event for shape, correlates records by `request_id`, and keeps the newest 200 records in its private extension storage (oldest evicted; eviction is reported, never hidden).
- The `captures` tool queries the records (`limit` 1-100, optional `point` filter); the overview panel renders the newest exchanges and token totals.

## Design

Read docs/design.md for the domain fit, the spike answers from the host source, the capability grants, the safety rules, the build order and the acceptance gates.

## Develop

    devkit validate .
    devkit lint .
    devkit check . smoke=true
    cd plugin && cargo test

Work one build-order step at a time. After each step, validate and lint before moving on.

## Install

    bsh ext install .
    bsh ext list
    bsh ext info com.open1s.llmsniff

The hook never fires without the explicit observe grant:

    bsh ext grant com.open1s.llmsniff hooks.observe
    bsh ext grant com.open1s.llmsniff extension.storage

## Capabilities

- hooks.observe (high) — receives observe-hook batches from the host seam
- extension.storage (low) — private KV for the bounded redacted records
- agent.tools.register, ui.commands, agent.prompts.provide, agent.context.provide, agent.skills.provide, ui.panels (low) — the captures tool and the text surfaces

### Security: why hooks.observe is required and what it cannot do

`hooks.observe` is the only way a package can receive the host's observe-hook batches; without the explicit grant the hook never fires and the plugin captures nothing. It is a request, not an authorization — the reader grants it deliberately.

What it enables: reading the metadata the host already redacts (method, host, path, status, byte sizes, latency, token usage, message counts) for the LLM calls the host itself makes.

What it cannot do: it delivers no request or response bodies, no header values, and no other process's traffic. The plugin runs in the wasm sandbox with no network, process, workspace or secret capability, so it cannot exfiltrate what it sees, execute anything, or read files. Conversation text and credential values are never persisted, and the stored records are re-redacted and size-bounded by the plugin.

Deliberately not requested: network, process, workspace and secret capabilities. The wasm runtime cannot use them; their absence is the design's main safety property.

## Layout

    extension.toml
    plugin/              the extism guest crate (cargo test has the leak fixtures)
    plugin.wasm          the built runtime entry
    docs/design.md       the blueprint and the implementation checklist
    tools/               declared tools only (captures)
    commands/            prompt templates
    prompts/ contexts/   model guidance
    skills/              the safe-reading workflow
    panels/              the status card
    tests/               dependency-free package checks
