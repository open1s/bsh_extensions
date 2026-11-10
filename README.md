# bsh_extensions

The official BSH extension market. The host reads `index.json`; packages live
under `packages/<id>/<version>/` and are installed into the normal hashed store
with community trust.

~~~text
bsh ext market
bsh ext market install com.open1s.opencode
~~~

See the market and CLI contract in `docs/bsh-extension.md` in the BOS repository. Every package here uses manifest 2.0 (schema_version 2.0).

## Package details

### Computer Use

A macOS process extension that verifies the framework with real CoreGraphics
calls: a single `computer` tool with action subcommands (screen_size,
screenshot, cursor_position, mouse_move, mouse_click, mouse_drag, scroll,
type_text, key_press), a `/refresh` command, a desktop panel, a safety prompt
and skill, an inspect workflow, two integrations, and
`session.created`/`tool.completed` hooks.

It needs **Screen Recording** and **Accessibility** for BSH, and explicitly asks
for `computer.use`. That capability is an activation/audit gate for a process
runtime, not a per-call OS sandbox; review the package before installing it.

~~~text
bsh ext grant com.open1s.computer-use process.execute --scope program:python3
bsh ext grant com.open1s.computer-use computer.use
bsh ext grant com.open1s.computer-use agent.tools.register
bsh ext grant com.open1s.computer-use agent.prompts.provide
bsh ext grant com.open1s.computer-use agent.skills.provide
bsh ext grant com.open1s.computer-use agent.workflows.provide
bsh ext grant com.open1s.computer-use ui.panels
bsh ext grant com.open1s.computer-use ui.commands
bsh ext grant com.open1s.computer-use events.subscribe
bsh ext market install com.open1s.computer-use
~~~

Full details are in
[`packages/com.open1s.computer-use/1.0.0/README.md`](packages/com.open1s.computer-use/1.0.0/README.md).

### LLM Sniffer

Capture and parse the LLM API traffic the BSH host mediates through the
`http.exchange` and `model.request`/`model.response` hooks. Credentials are
redacted before storage. A single `captures` tool queries the stored traffic,
a `/start` command toggles capture, and an overview panel shows active captures.

~~~text
bsh ext grant com.open1s.llmsniff agent.tools.register
bsh ext grant com.open1s.llmsniff ui.commands
bsh ext grant com.open1s.llmsniff agent.prompts.provide
bsh ext grant com.open1s.llmsniff agent.context.provide
bsh ext grant com.open1s.llmsniff agent.skills.provide
bsh ext grant com.open1s.llmsniff ui.panels
bsh ext market install com.open1s.llmsniff
~~~

Full details are in
[`packages/com.open1s.llmsniff/0.1.0/README.md`](packages/com.open1s.llmsniff/0.1.0/README.md).

### OpenCode Zen

No account and no API key: the package contributes the **OpenCode Zen** model
provider (declared keyless), a single `relay` tool with action subcommands
(start, stop, status, models), and a context that tells the agent when to start
the relay. The provider points at a loopback relay the package runs, because a
provider descriptor cannot add the session headers, tool-name shape and streaming
body the free lane requires. It needs the BSH launch fixes that ship with this
release (provider refresh after the extension host opens, `requires_key` on a
descriptor, and the on-startup warm that binds the relay before the first
model call); the package README records all three.

~~~text
bsh ext grant com.open1s.opencode process.execute --scope program:python3 --note "OpenCode Zen relay"
bsh ext grant com.open1s.opencode network.http --scope any --note "live Zen catalog"
bsh ext market install com.open1s.opencode
~~~

Restart BSH once after installing: the package is warmed at launch and the relay
binds before the first model call. Then pick **OpenCode Zen** in the model
picker. The full contract, limits and mirror table are in
[`packages/com.open1s.opencode/1.0.3/README.md`](packages/com.open1s.opencode/1.0.3/README.md).

### Extension DevKit

A design-first toolkit as a process extension. The design tool turns a domain
and a one-sentence brief into a blueprint: the runtime the domain needs, the
contribution and tool surface, capability grants, safety rules, a build order
and acceptance gates. Twelve domain profiles cover knowledge, devops, data,
web, documents, media, messaging, security, research, model, system and the
uncategorized case. The scaffold then writes a package that already validates
plus docs/design.md, declares only the tools whose files exist and leaves the
rest in an implementation checklist. The design tool (with modes: check, lint,
smoke, publish, package, bump, hash, explain, migrate, validate, scaffold,
blueprint) replaces 14 tools + 9 commands with a unified interface. One command
(publish) and one workflow (release) complete the 3 usage entries.

~~~text
bsh ext market install com.open1s.extdev
bsh ext grant com.open1s.extdev process.execute --scope program:python3
bsh ext grant com.open1s.extdev agent.workflows.provide
bsh ext grant com.open1s.extdev workspace.write
~~~

Then ask the agent to design a domain extension with `/plan`, or run the
tools directly: `design`, `blueprint`, `scaffold`, `validate`, `lint`,
`check`, `smoke`, `explain`, `hash`, `market`, `bump`, `package` and
`migrate`. `check` is the release gate:
validation, review, the canonical hash and, with `smoke`, one real call per
declared tool. The panel's self-check lints the DevKit itself.

The package is unsigned and asks for `process.execute` because it is a Python
runtime; it makes no network requests and reads no secrets. The full contract
is in
[`packages/com.open1s.extdev/2.1.0/README.md`](packages/com.open1s.extdev/2.1.0/README.md).

## Layout

~~~text
bsh_extensions/
  index.json
  packages/
    <id>/
      <version>/            one package root (extension.toml, tools/, ...)
~~~

`index.json` is the only document the host reads. Every entry needs
`schema_version` 1 (the index format), a reverse-domain `id`, a SemVer `version`,
and a relative `path` whose root holds a manifest 2.0 `extension.toml`
(`schema_version = "2.0"`). `hash` is optional; the host computes the package
hash itself.

## Publishing a package

1. Add `packages/<id>/<version>/` with a valid manifest 2.0 `extension.toml`.
2. Commit the package first. The index hash is the commit's, because the host
   installs from a clone and a clone carries committed files only: the DevKit
   hashes `HEAD` and refuses a dirty package, so an index built before the
   commit would declare a digest no clone can reproduce.
3. Append the entry to `index.json` and keep the array sorted by id
   (`market action=merge` does this).
4. Run `bsh ext validate packages/<id>/<version>` and `bsh ext test
   packages/<id>/<version>`; the DevKit package adds a review, a smoke run and
   a canonical hash check in one call.
5. Commit the index entry.

Do not commit `__pycache__`, build output, or installed package data.

## Packages

<!-- market-table:start -->
| Id | Name | Version | What it does |
|---|---|---|---|
| `com.open1s.computer-use` | Computer Use | 1.0.0 | Real macOS screen, pointer and keyboard tools, panel, workflow and hooks built as a BSH process extension |
| `com.open1s.extdev` | Extension DevKit | 2.1.0 | Design and ship BSH extensions from inside BSH: a domain-first blueprint, a validating scaffold, a manifest compiler, a review with stable rule ids, a dry run of every declared tool, deterministic archives and a Git market index editor. Commands and skills guide a specific extension for a specific domain, and grill-me interrogates an ambiguous brief before code is written. |
| `com.open1s.llmsniff` | LLM Sniffer | 0.1.0 | Capture and parse the LLM API traffic the BSH host mediates, through the http.exchange and model observe hooks, with credentials redacted before storage. |
| `com.open1s.opencode` | OpenCode Zen | 1.0.3 | Free OpenCode Zen models for BSH through a local relay that speaks the anonymous lane wire shape |
<!-- market-table:end -->
