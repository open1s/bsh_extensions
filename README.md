# bsh_extensions

The official BSH extension market. The host reads `index.json`; packages live
under `packages/<id>/<version>/` and are installed into the normal hashed store
with community trust.

~~~text
bsh ext market
bsh ext market install com.open1s.opencode
~~~

See `docs/bsh-extension-market.md` in the BOS repository for the index contract.

## Packages

| Id | Name | Version | What it does |
|---|---|---|---|
| `com.example.allinone` | All-in-One Exam Demo | 1.0.0 | Every extension contribution in one self-checking package: 7 tools, commands, panel, prompt, context, skill, language, integrations, theme, presets, providers, workflow, events, configuration |
| `com.example.computer-use` | Computer Use | 1.0.0 | Real macOS screen, pointer and keyboard tools, panel, workflow, hooks and two integrations, built as a process extension |
| `com.example.hello` | Hello | 1.0.0 | A minimal declarative BSH extension: one echo tool, one command and one panel |
| `com.open1s.opencode` | OpenCode Zen | 1.0.2 | Free OpenCode Zen models in BSH through a loopback relay that speaks the anonymous lane's wire shape |

### All-in-One Exam Demo

A teaching package and its grader: it contributes seven process tools,
two commands, a panel with live actions, a prompt, a scoped context, a skill,
a language descriptor, two integrations, a theme, a preset, model and agent
providers, a workflow, 18 event subscriptions and a configuration schema.

~~~text
bsh ext grant com.example.allinone process.execute --scope program:python3 --note "all-in-one demo"
bsh ext market install com.example.allinone
python3 packages/com.example.allinone/1.0.0/scripts/exam.py
~~~

The exam checks the manifest, every contribution file, the process protocol,
panel actions, progress, deliberate failures, the developer CLI and a throwaway
install, then prints a `PASS`/`FAIL` score. The full walkthrough and exam
questions are in
[`packages/com.example.allinone/1.0.0/README.md`](packages/com.example.allinone/1.0.0/README.md).

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
[`packages/com.open1s.opencode/1.0.2/README.md`](packages/com.open1s.opencode/1.0.2/README.md).

## Layout

~~~text
bsh_extensions/
  index.json
  packages/
    <id>/
      <version>/            one package root (extension.toml, tools/, ...)
~~~

`index.json` is the only document the host reads. Every entry needs
`schema_version` 1, a reverse-domain `id`, a SemVer `version`, and a relative
`path` whose root holds `extension.toml`. `hash` is optional; the host computes
the package hash itself.

## Publishing a package

1. Add `packages/<id>/<version>/` with a valid `extension.toml`.
2. Append the entry to `index.json` and keep the array sorted by id.
3. Run `bsh ext validate packages/<id>/<version>` and `bsh ext test
   packages/<id>/<version>`.
4. Commit both the package and the index entry in one change.

Do not commit `__pycache__`, build output, or installed package data.
