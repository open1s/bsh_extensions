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
calls: nine tools (screen size, screenshot, cursor, move, click, drag, scroll,
type, key press), a right panel, a `/refresh` command, a safety prompt and skill,
a workflow, two integrations, and `session.created`/`tool.completed` hooks.

It needs **Screen Recording** and **Accessibility** for BSH, and explicitly asks
for `computer.use`. That capability is an activation/audit gate for a process
runtime, not a per-call OS sandbox; review the package before installing it.

~~~text
bsh ext market install com.example.computer-use
bsh ext grant com.example.computer-use process.execute --scope program:python3
bsh ext grant com.example.computer-use computer.use
bsh ext grant com.example.computer-use agent.tools.register
bsh ext grant com.example.computer-use agent.prompts.provide
bsh ext grant com.example.computer-use agent.skills.provide
bsh ext grant com.example.computer-use agent.workflows.provide
bsh ext grant com.example.computer-use ui.panels
bsh ext grant com.example.computer-use ui.commands
bsh ext grant com.example.computer-use events.subscribe
bsh ext retry com.example.computer-use
~~~

Safe first calls: `screen_size`, `cursor_position`, then `screenshot` or the
`inspect` workflow. Do not click or type until the target is visible and
confirmed. Full details are in
[`packages/com.example.computer-use/1.0.0/README.md`](packages/com.example.computer-use/1.0.0/README.md).

### OpenCode Zen

No account and no API key: the package contributes the **OpenCode Zen** model
provider (declared keyless) plus `opencode__relay_start`,
`opencode__relay_stop`, `opencode__status` and `opencode__models`. The provider
points at a loopback relay the package runs, because a provider descriptor cannot
add the session headers, tool-name shape and streaming body the free lane
requires. It needs the BSH launch fixes that ship with this release (provider
refresh after the extension host opens, `requires_key` on a descriptor, and the
on-startup warm that binds the relay before the first model call); the package
README records all three.

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
rest in an implementation checklist. Fourteen tools compile a manifest the way
the host does, review it with stable rules, run every declared tool locally,
build reproducible archives, edit this index and migrate a 1.x manifest. Nine
commands, four skills, a self-checking panel, a scoped context, a prompt, a
release workflow and a configuration schema come with it.

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
2. Append the entry to `index.json` and keep the array sorted by id.
3. Run `bsh ext validate packages/<id>/<version>` and `bsh ext test
   packages/<id>/<version>`; the DevKit package adds a review, a smoke run and
   a canonical hash check in one call.
4. Commit both the package and the index entry in one change.

Do not commit `__pycache__`, build output, or installed package data.

## Packages

<!-- market-table:start -->
| Id | Name | Version | What it does |
|---|---|---|---|
| `com.example.computer-use` | Computer Use | 1.0.0 | Real macOS screen, pointer and keyboard tools, panel, workflow and hooks built as a BSH process extension |
| `com.open1s.extdev` | Extension DevKit | 2.1.0 | Design and ship BSH extensions from inside BSH: a domain-first blueprint, a validating scaffold, a manifest compiler, a review with stable rule ids, a dry run of every declared tool, deterministic archives and a Git market index editor. Commands and skills guide a specific extension for a specific domain, and grill-me interrogates an ambiguous brief before code is written. |
| `com.open1s.opencode` | OpenCode Zen | 1.0.3 | Free OpenCode Zen models for BSH through a local relay that speaks the anonymous lane wire shape |
<!-- market-table:end -->
