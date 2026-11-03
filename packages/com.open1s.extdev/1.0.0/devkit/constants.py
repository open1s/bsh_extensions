"""The BSH extension standard's vocabulary, in one place.

Every table here mirrors the host (ferris-core / crates/bsh): the capability
enum, the runtime kinds, the contribution kinds, the manifest envelope, the UI
node set and the host ceilings. The DevKit validates against this copy so a
package can be checked before the host ever sees it; when the standard grows,
this module grows with it.
"""

# The only manifest generation this host accepts.
SCHEMA_VERSION = "2.0"
MANIFEST_FILE = "extension.toml"
SIGNATURE_FILE = "package.sig"
MARKET_INDEX = "index.json"

# Top-level manifest tables. Unknown keys are refused by the host parser.
MANIFEST_FIELDS = (
    "schema_version",
    "extension",
    "compatibility",
    "runtime",
    "capabilities",
    "contribution",
    "configuration",
    "resources",
    "dependencies",
    "services",
)

IDENTITY_FIELDS = (
    "id",
    "name",
    "version",
    "description",
    "authors",
    "license",
    "repository",
    "homepage",
)

COMPATIBILITY_FIELDS = ("host", "extension_api")
RUNTIME_FIELDS = ("kind", "config")
RESOURCE_FIELDS = (
    "max_memory_mb",
    "max_execution_ms",
    "max_concurrent_calls",
    "max_output_bytes",
)
SERVICE_PROVIDE_FIELDS = ("name", "contract", "version", "scope", "capabilities")
SERVICE_REQUIRE_FIELDS = ("name", "contract", "version", "scope", "optional")
CONTRIBUTION_FIELDS = ("kind", "id", "payload")

# name -> (risk, description); the order matches `bsh ext capabilities`.
CAPABILITIES = (
    ("workspace.read", "low", "read files inside the current workspace"),
    ("workspace.write", "high", "write, create or remove files inside the current workspace"),
    ("network.http", "high", "make outbound HTTP requests"),
    ("process.execute", "critical", "start and manage an external process"),
    ("computer.use", "critical", "read the screen or control the keyboard and pointer"),
    ("secrets.read", "critical", "read a named secret from the vault"),
    ("extension.storage", "low", "use this extension's private storage namespace"),
    ("agent.tools.register", "low", "register tools the agent can call"),
    ("agent.context.provide", "low", "supply scoped context to the agent"),
    ("agent.prompts.provide", "low", "supply prompt fragments to the agent"),
    ("agent.skills.provide", "medium", "supply SKILL.md skills to the agent"),
    ("agent.models.provide", "medium", "register model or provider adapters"),
    ("agent.agents.provide", "medium", "register agent roles or execution strategies"),
    ("agent.workflows.provide", "medium", "register reusable workflows"),
    ("events.publish", "low", "publish events on the host bus"),
    ("events.subscribe", "low", "subscribe to events on the host bus"),
    ("ui.panels", "low", "contribute host-managed panels"),
    ("ui.commands", "low", "contribute host commands and keybindings"),
    ("ui.theme", "low", "contribute visual theme resources"),
    ("hooks.observe", "high", "receive observe-hook batches from host seams"),
    ("agent.intercept", "high", "intercept and rewrite host events or requests"),
)

CAPABILITY_NAMES = tuple(name for name, _, _ in CAPABILITIES)
CAPABILITY_RISK = {name: risk for name, risk, _ in CAPABILITIES}
CAPABILITY_DOC = {name: doc for name, _, doc in CAPABILITIES}

# The historical alias the host still accepts.
CAPABILITY_ALIASES = {"terminal.execute": "process.execute"}

RUNTIME_KINDS = ("builtin", "declarative", "process", "mcp", "extism", "wasm-component", "cordis")
# Runtimes that need a package-relative entry point.
RUNTIME_ENTRY_REQUIRED = ("process", "mcp", "extism", "wasm-component", "cordis")
STARTUP_POLICIES = ("on-startup", "on-demand", "on-workspace-open", "manual")
# Bare commands a process or MCP runtime may start without a package-relative
# path; every one still needs an explicit process.execute grant.
ALLOWLISTED_COMMANDS = ("python3", "python", "node", "bun", "deno", "sh", "bash")

HOOK_POINTS = ("model.request", "model.response", "tool.before", "tool.after", "http.exchange")

# kind -> package-relative file template, and the capability the kind is
# normally paired with. The file is None for declaration-only kinds.
CONTRIBUTION_KINDS = {
    "tool": {"file": "tools/{id}.json", "capability": "agent.tools.register"},
    "command": {"file": "commands/{id}.md", "capability": "ui.commands"},
    "panel": {"file": "panels/{id}.json", "capability": "ui.panels"},
    "prompt": {"file": "prompts/{id}.md", "capability": "agent.prompts.provide"},
    "context": {"file": "contexts/{id}.md", "capability": "agent.context.provide"},
    "skill": {"file": "skills/{id}/SKILL.md", "capability": "agent.skills.provide"},
    "workflow": {"file": "workflows/{id}.json", "capability": "agent.workflows.provide"},
    "theme": {"file": "themes/{id}.json", "capability": "ui.theme"},
    "preset": {"file": "presets/{id}.json", "capability": None},
    "model-provider": {"file": "providers/models/{id}.json", "capability": "agent.models.provide"},
    "agent-provider": {"file": "providers/agents/{id}.json", "capability": "agent.agents.provide"},
    "language": {"file": "languages/{id}.json", "capability": None},
    "integration": {"file": "integrations/{id}.json", "capability": None},
    "event.subscribe": {"file": None, "capability": "events.subscribe"},
    "event.publish": {"file": None, "capability": "events.publish"},
    "hook": {"file": None, "capability": "hooks.observe"},
}

# Hard host ceilings a manifest cannot raise.
HARD_MAX_MEMORY_MB = 4096
HARD_MAX_EXECUTION_MS = 600_000
HARD_MAX_CONCURRENT_CALLS = 64
HARD_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
# Defaults the host applies when a field is omitted.
DEFAULT_MEMORY_MB = 256
DEFAULT_EXECUTION_MS = 30_000
DEFAULT_CONCURRENT_CALLS = 4
DEFAULT_OUTPUT_BYTES = 1024 * 1024

# Host parsers' size limits.
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CONTRIBUTION_BYTES = 256 * 1024
MAX_TOOL_DESCRIPTION_BYTES = 4096
MAX_PANEL_TITLE_CHARS = 120

# UI schema.
UI_SCHEMA_VERSION = "1.0"
MAX_UI_BYTES = 256 * 1024
MAX_UI_NODES = 500
MAX_UI_DEPTH = 32

PANEL_LOCATIONS = ("right", "left", "bottom", "center")
PANEL_VISIBILITIES = ("visible", "hidden")
BUTTON_STYLES = ("primary", "secondary", "danger", "ghost")
NOTIFICATION_LEVELS = ("info", "warning", "error", "success")
LANGUAGE_SYNTAXES = (
    "rust", "python", "javascript", "typescript", "go", "java", "c", "cpp",
    "ruby", "php", "bash", "json", "toml", "yaml", "markdown", "html", "css",
)
INTEGRATION_KINDS = ("github", "browser", "terminal", "custom")
SERVICE_SCOPES = ("host", "workspace", "session", "extension")

# Directory names the store never copies or hashes. This is the host's list,
# exactly: it does not skip Python bytecode, so a package with a __pycache__
# directory hashes differently from the same package without one.
IGNORED_DIRECTORIES = (".git", "target", "node_modules", ".jj")
IGNORED_FILES = (".DS_Store",)
IGNORED_SUFFIXES = (".tmp",)

# Local build output the DevKit warns about: it is hashed like any other file,
# so shipping it makes a release hash depend on who ran the tests.
BUILD_DIRECTORIES = ("__pycache__",)

# Declarative tool bodies.
IMPLEMENTATIONS = ("echo_arguments", "constant", "template")

# UiNode variants and their required fields; children are walked recursively.
UI_NODE_REQUIRED = {
    "container": (),
    "row": (),
    "column": (),
    "text": ("text",),
    "heading": ("text",),
    "markdown": ("text",),
    "button": ("label", "action"),
    "input": ("label", "action"),
    "select": ("label", "options", "action"),
    "checkbox": ("label", "action"),
    "list": (),
    "table": ("columns",),
    "tree": (),
    "tabs": ("tabs",),
    "progress": (),
    "code": ("value",),
    "image": ("src",),
    "notification": ("level", "text"),
    "divider": (),
    "spacer": (),
}
UI_CHILD_LISTS = ("children",)
