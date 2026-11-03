"""The extension standard, as the model can read it.

The reference is generated from the same tables the validator uses, so the
answer a reader gets and the answer the checker enforces cannot drift apart.
"""

from __future__ import annotations

from . import constants


def capability_table() -> str:
    lines = ["| Capability | Risk | Meaning |", "|---|---|---|"]
    for name, risk, description in constants.CAPABILITIES:
        lines.append("| %s | %s | %s |" % (name, risk, description))
    return "\n".join(lines)


def contribution_table() -> str:
    lines = ["| Kind | File | Paired capability |", "|---|---|---|"]
    for kind, spec in constants.CONTRIBUTION_KINDS.items():
        file = spec["file"] or "(declaration only)"
        capability = spec["capability"] or "(none)"
        lines.append("| %s | %s | %s |" % (kind, file, capability))
    return "\n".join(lines)


def runtime_table() -> str:
    return "\n".join(
        [
            "| Kind | Payload | Notes |",
            "|---|---|---|",
            "| declarative | package files | pure tool bodies; executes nothing |",
            "| process | server executable | JSON-RPC over stdin/stdout, one object per line |",
            "| mcp | MCP server over stdio | the host is the MCP client |",
            "| extism | Extism PDK plugin | wasm plugin, metered |",
            "| wasm-component | WebAssembly component | WIT contract in crates/bsh/wit |",
            "| cordis | JS/TS apply(ctx, config) | DSH/Cordis package |",
            "| builtin | linked into the host | a package may not claim it |",
        ]
    )


def node_table() -> str:
    lines = ["| Node type | Required fields |", "|---|---|"]
    for kind, fields in constants.UI_NODE_REQUIRED.items():
        lines.append("| %s | %s |" % (kind, ", ".join(fields) or "(none)"))
    return "\n".join(lines)


TOPICS = {
    "overview": """# The BSH extension standard in one page

A BSH extension is a package directory with a validated `extension.toml`
(manifest 2.0) plus the files its contributions declare. The host installs it
into a hashed store, resolves dependencies and services, grants capabilities,
starts the runtime and attaches the contributions to one agent build.

Layers, from the package's point of view:

- `ferris-core`       manifest, package store, manager, capability policy, events, UI
- `ferris-runtime`    declarative, process, MCP, Extism, Wasm-component, Cordis
- `ferris-sdk`        the author API and host facade
- `crates/bsh`        the BSH host adapter (CLI, UI, agent wiring)

Lifecycle: `available -> installed -> resolved -> applied -> active`, with
`failed` and `quarantined` as the refusal states.

Facts worth remembering:

- schema_version is exactly "2.0"; 1.x is refused, not migrated silently.
- Unknown top-level manifest fields are refused.
- Declaring a capability does not grant it.
- Registration is not authorization: every tool call re-checks its declared
  capabilities against the grants and against the call's scope.
- Only files a contribution declares are read; a file nobody declares is
  ignored, and a declaration without its file fails the package.
""",
    "manifest": """# extension.toml (manifest 2.0)

`@toml
schema_version = "2.0"

[extension]
id = "com.example.toolkit"
name = "Toolkit"
version = "1.0.0"
description = "One paragraph a reader can trust"
authors = ["Example"]
license = "MIT"
repository = "https://example.com/toolkit"
homepage = "https://example.com"

[compatibility]
host = ">=3.0.0, <4.0.0"
extension_api = "^1.0"

[runtime]
kind = "declarative"

[runtime.config]
startup = "on-demand"

[capabilities]
required = ["agent.tools.register"]

[[contribution]]
kind = "tool"
id = "echo"

[contribution.payload]

[configuration]
schema = "schemas/config.schema.json"

[configuration.defaults]
verbose = false

[resources]
max_memory_mb = 256
max_execution_ms = 30000
max_concurrent_calls = 4
max_output_bytes = 1048576

[dependencies]
"com.example.base" = "^1.0"

[services]
provides = []
requires = []
`@

Top-level fields: `MANIFEST_FIELDS`.

Identity fields: `IDENTITY_FIELDS`.

Rules the host enforces:

- `schema_version` must be exactly "2.0".
- `extension.id` is a reverse-domain id: at least two lowercase segments,
  digits/'-'/'_', starting and ending alphanumeric, at most 128 bytes.
- `extension.version` is a semantic version; `compatibility.host` and
  `compatibility.extension_api` are semver ranges.
- `[runtime]` has exactly `kind` and `config`; `config` is opaque to
  the manifest parser and validated by the runtime adapter.
- `capabilities` has exactly `required`; it is a required-only list.
- every `[[contribution]]` has `kind` and `id`, and an optional
  `payload` table; the pair must be unique.
- `resources` may not exceed the host ceilings: memory %d MiB, execution %d
  ms, concurrency %d, output %d bytes.
""",
    "runtime": """# Runtime kinds

`RUNTIME_TABLE`

## Declarative

The host reads and runs pure tool bodies. No process, no wasm, no network.

`@json
{"description": "Echo", "input_schema": {"type": "object"},
 "implementation": {"kind": "echo_arguments"}}
{"implementation": {"kind": "constant", "value": {"ok": true}}}
{"implementation": {"kind": "template", "text": "hello {{name}}"}}
`@

`startup` is one of `STARTUP`. The declarative runtime forbids
`runtime.config.entry`.

## Process

`runtime.config` carries `entry`, `args`, `env`, `protocol` and
`startup`. The host starts the entry with its declared arguments, in the
package directory, with a cleared environment plus PATH, HOME, TMPDIR, LANG,
LC_ALL, the declared `env` and `BSH_IPC_TOKEN`. It requires the
`process.execute` capability; on macOS it wraps the child in a sandbox
profile that allows writes only inside the package, the workspace, the
extension data root and /tmp.

## MCP, Extism, Wasm-component, Cordis

All require `runtime.config.entry`. MCP speaks the MCP stdio protocol; Extism
loads a PDK plugin; the wasm component implements the WIT contract; Cordis
loads a JS/TS package whose default export is `apply(ctx, config)`.
""",
    "capabilities": """# Capabilities

`CAPABILITY_TABLE`

`terminal.execute` is a historical alias for `process.execute`; declare the
canonical name.

Registration is not authorization. A declared capability is a request; the user
grants it per extension, and a call is checked against the grant and against
the call's scope (path, domain, program, secret). Community packages get
low-risk capabilities automatically and need an explicit grant for anything
higher:

`@text
bsh ext grant com.example.toolkit process.execute --scope program:python3
bsh ext grant com.example.toolkit workspace.write
bsh ext grant com.example.toolkit network.http --scope domain:api.example.com
bsh ext grant com.example.toolkit secrets.read --scope secret:API_TOKEN
`@

A process package that omits `process.execute` from
`capabilities.required` still cannot start; the runtime authorization fails
at activation. That is why the validator reports it as an error rather than a
warning.
""",
    "contributions": """# Contributions

`CONTRIBUTION_TABLE`

Every declared contribution must have its file (except event and hook
declarations, which are topics and points). The file name is the full
contribution id, so `git.status` is `tools/git.status.json`.

Contribution ids are dotted, lowercase, 1..=96 bytes, each segment 1..=63.

## Text contributions

Commands, prompts and contexts are Markdown with optional frontmatter:

`@markdown
---
description: One line the command palette shows
paths: src/**/*.rs, tests
---

The body the host contributes.
`@

`paths` scopes a context to matching workspace globs; unknown keys are
ignored.

## Model-facing names

Two packages may both contribute `echo`. The host qualifies tool names with
the extension's last id segment: `com.example.toolkit` + `echo` becomes
`toolkit__echo`, capped at 64 characters with a stable digest suffix.
""",

    "tools": """# Tool descriptors

`tools/<id>.json` is what the model sees:

`@json
{
  "description": "One sentence: what it does and when to call it",
  "input_schema": {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
    "additionalProperties": false
  },
  "capabilities": ["workspace.read"]
}
`@

- `description` is capped at 4096 bytes and defaults to the extension name.
- `input_schema` must be a JSON object; a missing one is replaced by an empty
  object schema.
- `capabilities` are re-checked on every call, using the call's scope. The
  scope reads `path`, `url`, `method` and `secret` from the arguments,
  so name your path argument `path`, your URL `url`, and so on, or the
  grant cannot match and the call is denied.
- The declarative runtime additionally needs `implementation`.

Path arguments must be absolute: the scope is resolved against the workspace,
and a relative name would be resolved against the extension's package
directory by the process itself.
""",
    "panels": """# Panels and the UI document

`panels/<id>.json`:

`@json
{
  "title": "Toolkit",
  "icon": null,
  "location": "right",
  "default_visibility": "visible",
  "view": {"schema_version": "1.0", "root": {"type": "text", "text": "Ready"}}
}
`@

`location` is one of `PANEL_LOCATIONS`; `default_visibility` is
`PANEL_VISIBILITIES`.

Nodes:

`NODE_TABLE`

Limits: %d nodes, %d levels, 256 KiB serialized. `image.src` must be an
`asset/`-relative path; the host has no remote image loader. A button, input,
select or checkbox carries an `action` that the host dispatches back to the
runtime (a process package answers `commands/execute`).
""",
    "workflows": """# Workflows

`workflows/<id>.json` chains calls to the same package's tools:

`@json
{
  "description": "Check then publish",
  "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
  "steps": [
    {"name": "validate", "tool": "validate", "arguments": {"path": "{{input.path}}"}},
    {"name": "entry", "tool": "market", "arguments": {"path": "{{input.path}}", "action": "entry"}}
  ]
}
`@

- One workflow becomes one tool, named after the workflow.
- A step may only call a tool this package declares; the wrapper never reaches
  another package.
- Templates: `{{input.x}}` and `{{steps.<name>.x}}`.
- Each step's arguments are authorized immediately before it dispatches, so a
  scoped grant is evaluated against the resource the step will actually touch.
""",
    "protocol": """# The process wire protocol

One JSON object per line on stdin and stdout, JSON-RPC 2.0 shaped.

Handshake (sent by the host, 5000 ms deadline):

`@json
{"jsonrpc":"2.0","id":1,"method":"initialize",
 "params":{"protocolVersion":"1.0","extensionId":"com.example.x",
           "host":{"name":"bsh","version":"3.0.2"},
           "config":"{...}","token":"<uuid>"}}
`@

The answer must be:

`@json
{"jsonrpc":"2.0","id":1,
 "result":{"protocolVersion":"1.0","token":"<the same uuid>"}}
`@

If `protocolVersion` does not start with "1." or the token does not match,
the host kills the child and refuses the package.

Then:

- `tools/call` with `{"name": "<contribution id>", "arguments": {...}}`
  returns `{"result": <json>}` or
  `{"error": {"code": -32000, "message": "..."}}`.
- `commands/execute` with `{"name": "<command id>", "arguments": {...}}`
  returns a command result or a fresh UI document.
- Notifications use the progress method and carry no id; the host forwards them
  as live tool progress.
- `shutdown` ends the session.

Read one line per request from stdin in a loop, write one line per response,
and print nothing else on stdout: diagnostics go to stderr, which the host
logs.
""",

    "market": """# The market

The market is a Git repository, not a service:

`@text
bsh_extensions/
  index.json
  packages/<id>/<version>/...
`@

`index.json`:

`@json
{
  "schema_version": 1,
  "extensions": [
    {
      "id": "com.example.toolkit",
      "name": "Toolkit",
      "version": "1.0.0",
      "description": "One line",
      "path": "packages/com.example.toolkit/1.0.0",
      "hash": "<canonical package hash>"
    }
  ]
}
`@

The host clones the provider shallowly, reads the index, and installs an entry
into the normal hashed store with community trust. It checks that the package
ids and versions match the entry, and, when `hash` is present, that the
installed bytes hash to it.

Publishing checklist:

1. `validate` and `lint` are clean.
2. `bump` moved the version and wrote the changelog entry.
3. The package sits at `packages/<id>/<version>/`.
4. `market` with `action=merge` added the index entry with the current hash.
5. `market` with `action=verify` passes for every entry.
6. Commit and push; users run `bsh ext market install <id>`.

A signature (`bsh ext sign`) proves publisher identity and package integrity;
it does not replace capability review.
""",
    "ids": """# Identity grammar

Extension id (reverse domain):

- 1..=128 bytes, at least two dot-separated segments
- each segment 1..=63 bytes
- lowercase ASCII letters, digits, `-` and `_`
- a segment starts with a letter or digit and ends with a letter or digit

Valid: `com.example.toolkit`, `io.2code.tool`, `com.bos.bsh.hello`.
Invalid: `one-segment`, `Com.Example`, `com..example`,
`com/example/tool`.

Contribution id:

- 1..=96 bytes, dot-separated segments of 1..=63 bytes
- each segment starts with a lowercase letter or digit
- lowercase letters, digits, `-` and `_`

Valid: `echo`, `git.status`, `ext-dev.check`.
Invalid: `Git.Status`, `git/status`, `.git`, `git.`.

Version: semantic version, `MAJOR.MINOR.PATCH` with optional prerelease and
build metadata. Ranges use the semver grammar: `>=3.0.0, <4.0.0`, `^1.0`,
`~1.2`, `1.2.*`, `*`.
""",
    "cli": """# bsh ext

Scaffolding and validation:

`@text
bsh ext new <id> --dir <path>
bsh ext validate <path>
bsh ext test <path>
bsh ext mock <path> [tool] [json]
bsh ext migrate <path> [--write]
bsh ext hash <path>
bsh ext build <path> [--out <dir>]
`@

Lifecycle:

`@text
bsh ext install <path|archive|git+url>
bsh ext list / info / plan / graph / why <id> / effects <id>
bsh ext enable / disable / reload <id>
bsh ext versions / rollback / update <path> / retry <id>
bsh ext uninstall <id> [--purge-data]
bsh ext reproduce <lock>
`@

Policy and audit:

`@text
bsh ext grant <id> <capability> [--scope ...] [--note ...]
bsh ext revoke <id> <capability>
bsh ext capabilities
bsh ext logs <id> / metrics / doctor
bsh ext config <id> [set <json|file>|schema]
`@

Publishing:

`@text
bsh ext keygen <publisher>
bsh ext sign <path> --publisher <name> --key <file-or-base64>
bsh ext verify <path>
bsh ext trust <publisher> <public-key>
bsh ext market [query]
bsh ext market install <id>
bsh ext registry add/list
`@
""",
    "checklist": """# Release checklist

Before a package is published:

- [ ] `schema_version = "2.0"` and a reverse-domain id that is stable forever.
- [ ] `compatibility.host` and `extension_api` are ranges, not wishes.
- [ ] Every declared contribution has its file, and every file is declared.
- [ ] Every tool has a description and a typed `input_schema`.
- [ ] Path arguments are named `path` and documented as absolute.
- [ ] The manifest asks only for the capabilities the package really uses, and
      the README explains each high-risk one.
- [ ] `[resources]` ceilings are proportional to the work (output bytes, ms).
- [ ] A process package answers `initialize` with the echoed token and speaks
      one JSON object per line on stdout.
- [ ] `tests/` runs without the host
      (`python3 -m unittest discover -s tests`).
- [ ] `bsh ext validate`, `bsh ext test` and `bsh ext mock` pass.
- [ ] `README.md`, `LICENSE`, `CHANGELOG.md` exist and agree with the
      manifest.
- [ ] The market index entry carries the current canonical hash.
- [ ] The version was bumped, not reused.
""",
    "errors": """# Reading validator findings

Validation rules are dotted ids; lint rules are `EXT###`. The most common
ones:

| Rule | Meaning | Usual fix |
|---|---|---|
| `manifest.unknown-field` | a field the host refuses | remove it or use the defined one |
| `manifest.schema-version` | not 2.0 | run the migrate tool |
| `id.grammar` | id is not reverse-domain | `com.example.name` |
| `version.semver` / `compatibility.range` | not a version or range | `1.0.0`, `>=3.0.0, <4.0.0` |
| `runtime.entry` | missing or forbidden entry | declarative: remove; process: add |
| `runtime.entry-missing` | the entry file is absent | ship it |
| `capabilities.unknown` | not in the vocabulary | see the capabilities topic |
| `capabilities.process` | process runtime without process.execute | add it |
| `contribution.duplicate` | same kind and id twice | rename one |
| `contribution.file-missing` | declaration without a file | create the file |
| `tool.implementation` | declarative tool without a body | add implementation |
| `panel.schema-version` | view is not 1.0 | fix the document |
| `package.symlink` | package contains a symlink | copy the target in |
| `EXT060` | a file nobody declared | declare or delete it |
| `EXT120` | a credential-looking string | rotate it, load from the vault |

Every finding carries `severity`, `rule`, `message`, and usually `path`
and `fix`; the report is a JSON object so a caller can filter on severity.
""",
}


def topics() -> "list[str]":
    """Every topic name the reference answers."""
    return sorted(TOPICS)


def render(topic: str) -> str:
    """Render one topic with the live tables substituted."""
    body = TOPICS[topic]
    body = body.replace("`MANIFEST_FIELDS`", ", ".join(
        "`%s`" % name for name in constants.MANIFEST_FIELDS))
    body = body.replace("`IDENTITY_FIELDS`", ", ".join(
        "`%s`" % name for name in constants.IDENTITY_FIELDS))
    body = body.replace("`RUNTIME_TABLE`", runtime_table())
    body = body.replace("`CAPABILITY_TABLE`", capability_table())
    body = body.replace("`CONTRIBUTION_TABLE`", contribution_table())
    body = body.replace("`NODE_TABLE`", node_table())
    body = body.replace("`STARTUP`", ", ".join(
        "`%s`" % value for value in constants.STARTUP_POLICIES))
    body = body.replace("`PANEL_LOCATIONS`", ", ".join(
        "`%s`" % value for value in constants.PANEL_LOCATIONS))
    body = body.replace("`PANEL_VISIBILITIES`", ", ".join(
        "`%s`" % value for value in constants.PANEL_VISIBILITIES))
    if "%d" in body:
        if topic == "panels":
            body = body % (constants.MAX_UI_NODES, constants.MAX_UI_DEPTH)
        else:
            body = body % (
                constants.HARD_MAX_MEMORY_MB,
                constants.HARD_MAX_EXECUTION_MS,
                constants.HARD_MAX_CONCURRENT_CALLS,
                constants.HARD_MAX_OUTPUT_BYTES,
            )
    return body


def explain(topic=None) -> dict:
    """Return the markdown reference for one topic, or the index."""
    name = (topic or "overview").strip().lower()
    aliases = {
        "index": "overview",
        "start": "overview",
        "manifest-v2": "manifest",
        "v2": "manifest",
        "capability": "capabilities",
        "contribution": "contributions",
        "tool": "tools",
        "panel": "panels",
        "ui": "panels",
        "workflow": "workflows",
        "process": "protocol",
        "jsonrpc": "protocol",
        "publish": "market",
        "id": "ids",
        "rules": "errors",
        "lint": "errors",
        "release": "checklist",
    }
    name = aliases.get(name, name)
    if name not in TOPICS:
        return {
            "topic": None,
            "topics": topics(),
            "markdown": "# Unknown topic\n\nKnown topics: " + ", ".join(topics()),
        }
    return {"topic": name, "topics": topics(), "markdown": render(name)}

