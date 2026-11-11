# LLM Sniffer

Capture and parse the LLM API traffic the BSH host mediates, through the host's observe hooks (`http.exchange`, `model.request`, `model.response`), with credentials redacted before anything is stored or shown.

Id: com.open1s.llmsniff  Version: 0.1.0  Runtime: extism  Domain: security

## Scope (read this first)

Capture is **host-mediated traffic only**. The plugin sees what the BSH host sends to and receives from LLM provider APIs — it is not a system-wide sniffer, and traffic from other processes is invisible to it. Records hold metadata (method, host, path, status, byte sizes, latency, token usage, message counts), the request and response headers with credential values masked, and bounded request/response bodies for the newest twelve exchanges. Credential-shaped strings in a body are masked before storage; conversation text reaches a record only as part of a captured body.

## How it works

- The host dispatches observe-hook batches to the plugin's `bsh_hook` export.
- The plugin re-redacts every string (defense in depth behind the host's own redaction), parses each event for shape, correlates records by `request_id`, and keeps the newest 200 records in its private extension storage (oldest evicted; eviction is reported, never hidden). Bodies are kept for the newest twelve exchanges, 12 KiB per side; older records keep the metadata and headers and say the body was dropped.
- Rows also cover the turn boundary (`turn.start`/`turn.end`), a skill body attached to a turn (`skill.load`), and every tool call (`tool.before`/`tool.after`, including namespaced MCP tools and bash), so one card follows a reader's request from input to answer.
- The `captures` tool lists the records (metadata and headers, `limit` 1-100, optional `point` filter); the `exchange` tool returns one record with its stored headers and bodies. The overview panel renders the newest exchange with previews and the token totals.

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

## Verify a capture

The extension stores its records in private extension storage, not in the package:

    python3 -m json.tool ~/.bos/bsh/extensions/extension-data/com.open1s.llmsniff/com.open1s.llmsniff/captures

Look for a `"point": "http.exchange"` record with `request_headers` / `request_body`. In the app, ask the agent to call `captures` and then `exchange` with a `request_id`, or open the LLM Sniffer panel (it shows the newest exchange's previews).

`bsh ext mock . captures` runs the plugin against a **scratch data directory**, so it always reports an empty store: it proves the plugin loads, not what the app captured.

## Capabilities

- hooks.observe (high) — receives observe-hook batches from the host seam
- extension.storage (low) — private KV for the bounded redacted records
- agent.tools.register, ui.commands, agent.prompts.provide, agent.context.provide, agent.skills.provide, ui.panels (low) — the captures tool and the text surfaces

### Security: why hooks.observe is required and what it cannot do

`hooks.observe` is the only way a package can receive the host's observe-hook batches; without the explicit grant the hook never fires and the plugin captures nothing. It is a request, not an authorization — the reader grants it deliberately.

What it enables: reading what the host observed for the LLM calls it makes — method, host, path, status, byte sizes, latency, token usage, message counts, the request and response headers (secret header values masked by the host as `[redacted]`), and bounded request/response bodies for the newest twelve exchanges (12 KiB per side; the host cuts a body at 32 KiB).

Privacy: a captured body can contain prompt and completion text. That is the point of the feature and why `hooks.observe` is a deliberate grant — treat captures as sensitive. The plugin masks credential-shaped strings (`sk-`, `ghp_`, `Bearer`) before storage but does not redact conversation content.

What it cannot do: it cannot see other processes' traffic, open a socket, run a process, read a file or read a secret. The plugin runs in the wasm sandbox with no network, process, workspace or secret capability, so it cannot exfiltrate what it sees.

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
