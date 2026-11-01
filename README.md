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
| `com.example.hello` | Hello | 1.0.0 | A minimal declarative BSH extension: one echo tool, one command and one panel |
| `com.open1s.opencode` | OpenCode Zen | 1.0.0 | Free OpenCode Zen models in BSH through a loopback relay that speaks the anonymous lane's wire shape |

### OpenCode Zen

No account and no API key: the package contributes the **OpenCode Zen** model
provider plus `opencode__relay_start`, `opencode__relay_stop`,
`opencode__status` and `opencode__models`. The provider points at a loopback
relay the package runs, because a BSH provider descriptor cannot add the session
headers, tool-name shape and streaming body the free lane requires.

~~~text
bsh ext grant com.open1s.opencode process.execute --scope program:python3 --note "OpenCode Zen relay"
bsh ext grant com.open1s.opencode network.http --scope any --note "live Zen catalog"
bsh ext market install com.open1s.opencode
~~~

Then ask BSH to "start the OpenCode Zen relay" and pick **OpenCode Zen** in the
model picker. The full contract, limits and mirror table are in
[`packages/com.open1s.opencode/1.0.0/README.md`](packages/com.open1s.opencode/1.0.0/README.md).

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
