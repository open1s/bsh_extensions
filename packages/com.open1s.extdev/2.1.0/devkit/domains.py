"""Domain profiles: what a good BSH extension looks like for one kind of work.

The profiles are the part of the DevKit that answers "what should I build?"
before "does this manifest validate?". A profile names the runtime the domain
actually needs, the contributions a reader expects, the tools with their scope
arguments, the capabilities and the grants they imply, the safety rules and the
build order. The design tool turns a brief plus a profile into a blueprint; the
reference exposes the catalogue; scaffold uses the same blueprint to start a
green package and write docs/design.md.

Profiles are deliberately opinionated. They are not a survey of every possible
package: each one is the smallest surface that does the domain's real work, with
the capabilities, failure modes and review questions that domain has.
"""

from __future__ import annotations

import re

from . import constants

# Reasons shared by most profiles. A profile overrides the ones where its
# reason is specific, because a generic sentence is not a review.
COMMON_REASONS = {
    "process.execute": "the package is a process runtime and starts the tools it declares",
    "workspace.read": "reads the workspace paths passed to its tools",
    "workspace.write": "writes the artifacts the reader asks for",
    "network.http": "calls the external service the domain needs",
    "secrets.read": "loads a named credential from the vault",
    "computer.use": "reads the screen or drives the keyboard and pointer",
    "agent.tools.register": "exposes the tool surface to the model",
    "agent.context.provide": "supplies workspace-scoped facts",
    "agent.prompts.provide": "supplies stable rules to the model",
    "agent.skills.provide": "ships the domain workflow as a skill",
    "agent.models.provide": "registers the model provider",
    "agent.agents.provide": "registers an agent role or strategy",
    "agent.workflows.provide": "registers a reusable workflow",
    "ui.commands": "adds the commands a reader runs",
    "ui.panels": "adds the status panel",
    "events.subscribe": "observes host events",
    "events.publish": "publishes host events",
    "hooks.observe": "receives observe-hook batches",
}

# Domain words a reader may type instead of the profile key.
ALIASES = {
    "git": "devops",
    "ci": "devops",
    "cd": "devops",
    "sre": "devops",
    "infra": "devops",
    "infrastructure": "devops",
    "release": "devops",
    "repo": "devops",
    "repository": "devops",
    "sql": "data",
    "db": "data",
    "database": "data",
    "analytics": "data",
    "warehouse": "data",
    "etl": "data",
    "api": "web",
    "http": "web",
    "jira": "web",
    "notion": "web",
    "stripe": "web",
    "linear": "web",
    "salesforce": "web",
    "hubspot": "web",
    "zendesk": "web",
    "shopify": "web",
    "rest": "web",
    "graphql": "web",
    "integration": "web",
    "saas": "web",
    "browser": "research",
    "search": "research",
    "web-research": "research",
    "crawl": "research",
    "scrape": "research",
    "docs": "documents",
    "document": "documents",
    "office": "documents",
    "pdf": "documents",
    "docx": "documents",
    "xlsx": "documents",
    "pptx": "documents",
    "video": "media",
    "audio": "media",
    "image": "media",
    "ffmpeg": "media",
    "chat": "messaging",
    "email": "messaging",
    "mail": "messaging",
    "notify": "messaging",
    "notification": "messaging",
    "slack": "messaging",
    "teams": "messaging",
    "audit": "security",
    "scan": "security",
    "compliance": "security",
    "secrets": "security",
    "llm": "model",
    "model-provider": "model",
    "provider": "model",
    "ollama": "model",
    "desktop": "system",
    "computer": "system",
    "mouse": "system",
    "keyboard": "system",
    "screen": "system",
    "documentation": "knowledge",
    "runbook": "knowledge",
    "playbook": "knowledge",
    "policy": "knowledge",
    "onboarding": "knowledge",
    "handbook": "knowledge",
    "guidance": "knowledge",
    "custom": "generic",
    "other": "generic",
}

PROFILES = {
    "knowledge": {
        "title": "Knowledge and operating guidance",
        "summary": (
            "Turns a team's playbooks, policies and checklists into scoped "
            "context, prompt rules, commands and a skill. No code, no network, "
            "no process: the smallest useful package to review and install."
        ),
        "signals": (
            "knowledge", "runbook", "playbook", "policy", "documentation",
            "onboarding", "checklist", "standard", "guide", "handbook", "faq",
            "prompt", "context", "training", "convention",
        ),
        "runtime": "declarative",
        "runtime_reason": (
            "The package only contributes text and pure transformations. A "
            "declarative runtime needs no process grant, executes no code and "
            "is the smallest possible review surface."
        ),
        "capabilities": (
            "agent.context.provide", "agent.prompts.provide",
            "agent.skills.provide", "agent.tools.register", "ui.commands",
            "ui.panels",
        ),
        "reasons": {
            "agent.context.provide": "adds the playbook facts only under docs/, README.md and *.md",
            "agent.prompts.provide": "adds the stable rules the model should follow",
            "agent.skills.provide": "ships the checklist and escalation workflow",
            "agent.tools.register": "adds two pure tools that render or cite the guidance",
            "ui.commands": "adds /checklist and /lookup",
            "ui.panels": "adds a panel that shows the source documents",
        },
        "grant_scopes": {},
        "contributions": (
            {"kind": "command", "id": "show-checklist",
             "purpose": "Render the team checklist for a named task."},
            {"kind": "command", "id": "lookup",
             "purpose": "Name the source document and heading for a topic."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Stable rules: cite the source, never invent policy."},
            {"kind": "context", "id": "playbook",
             "purpose": "Scoped facts from docs/, README.md and *.md."},
        ),
        "skill": {
            "id": "runbook",
            "purpose": "Find the owning document, quote it, and escalate when it is silent.",
        },
        "panel": {"id": "overview", "purpose": "Source documents and the last reviewed date."},
        "tools": (
            {
                "id": "checklist",
                "description": (
                    "Return the location of the checklist for a task. The body is "
                    "maintained in docs/, so the tool points at the source instead "
                    "of duplicating it."
                ),
                "args": (
                    {"name": "task", "type": "string", "required": True,
                     "description": "The task or change the checklist covers."},
                ),
                "returns": "A short pointer to docs/playbook.md plus the task name.",
                "capabilities": (),
                "implementation": {
                    "kind": "template",
                    "text": (
                        "The checklist for {{task}} is maintained in "
                        "docs/playbook.md. Read that file, quote the applicable "
                        "items, and name the heading you used."
                    ),
                },
            },
            {
                "id": "cite",
                "description": (
                    "Point at the source of truth for a topic. Use it so an answer "
                    "names a file and heading instead of reconstructing policy."
                ),
                "args": (
                    {"name": "topic", "type": "string", "required": True,
                     "description": "The policy or runbook topic to find."},
                ),
                "returns": "A search instruction naming the allowed source files.",
                "capabilities": (),
                "implementation": {
                    "kind": "template",
                    "text": (
                        "Source of truth for {{topic}}: search docs/, README.md "
                        "and *.md under the workspace. Name the file and heading; "
                        "if none applies, say so and ask the owner."
                    ),
                },
            },
        ),
        "guardrails": (
            "Scope the context with paths: so it does not follow the model into unrelated workspaces.",
            "Keep each prompt under 8 KiB and prefer a context for facts that change by directory.",
            "Every policy line needs an owner and a date; an undated rule is a rumour.",
            "Never paste credentials, customer data or private URLs into a prompt or context.",
            "A declarative package executes nothing, so do not claim it enforces a rule; it informs.",
        ),
        "build_order": (
            "Write docs/playbook.md with the source documents and owners.",
            "Add the scoped context and check the paths glob against the real tree.",
            "Add the prompt rules; keep them short enough to survive the prompt budget.",
            "Write the skill: when to use the playbook, how to quote it, when to escalate.",
            "Add the two declarative tool descriptors and verify their templates.",
            "Add the panel and commands, then run validate, lint and check.",
        ),
        "gates": (
            "The context does not load in an unrelated workspace (test the paths glob).",
            "No process, network, secret or workspace-write capability is requested.",
            "Every answer can name a source file and heading.",
            "The prompt and context together stay under the host budget.",
        ),
        "open_questions": (
            "Which directories hold the authoritative documents?",
            "Who reviews a policy change, and how is the date recorded?",
            "What should the model do when the playbook is silent?",
        ),
    },
    "devops": {
        "title": "Repository, CI and release operations",
        "summary": (
            "Reads a repository and runs the project's own checks. The useful "
            "surface is small: status, diff and a fixed set of declared checks, "
            "with no arbitrary shell and no force push."
        ),
        "signals": (
            "git", "github", "gitlab", "ci", "pipeline", "build", "deploy",
            "release", "repo", "repository", "branch", "commit", "pr", "pull request",
            "devops", "sre", "infrastructure", "terraform", "k8s", "kubernetes",
            "docker", "monorepo", "changelog",
        ),
        "runtime": "process",
        "runtime_reason": (
            "The tools run git and the project's own check commands. A "
            "declarative runtime cannot start a process, so the honest runtime "
            "for this domain is process."
        ),
        "capabilities": (
            "process.execute", "workspace.read", "workspace.write",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide", "agent.context.provide",
        ),
        "reasons": {
            "process.execute": "starts git and the project's declared check commands",
            "workspace.read": "reads repository files and diffs",
            "workspace.write": "writes a release note or report only when asked",
            "agent.tools.register": "exposes repo_status, repo_diff and run_check",
            "ui.commands": "adds /status and /changes",
            "ui.panels": "adds the repository panel",
            "agent.skills.provide": "ships the release-hygiene workflow",
            "agent.context.provide": "adds branch and repository conventions",
        },
        "grant_scopes": {
            "process.execute": ("program:python3", "program:git"),
            "workspace.write": ("path:<absolute workspace root>",),
        },
        "contributions": (
            {"kind": "command", "id": "status",
             "purpose": "Summarise branch, head and dirty files in the open repository."},
            {"kind": "command", "id": "changes",
             "purpose": "Review the working diff before a commit."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Read-only by default; never force-push or rewrite history."},
            {"kind": "context", "id": "repository",
             "purpose": "Branch, check and release conventions for this repository."},
        ),
        "skill": {
            "id": "release-hygiene",
            "purpose": "Inspect, verify and prepare a change without rewriting history.",
        },
        "panel": {"id": "overview", "purpose": "Branch, dirty count and the last check result."},
        "tools": (
            {
                "id": "repo_status",
                "description": (
                    "Read the repository's branch, head, ahead/behind and dirty "
                    "file count. Read-only; it never stages or commits."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to the repository root.", "scope": "path"},
                ),
                "returns": "{branch, head, ahead, behind, dirty_count, detached}",
                "capabilities": ("workspace.read", "process.execute"),
                "runs": "git status --porcelain=v1 --branch",
            },
            {
                "id": "repo_diff",
                "description": (
                    "Return a bounded working-tree diff so the reader can review a "
                    "change before committing. Never writes to the repository."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to the repository root.", "scope": "path"},
                    {"name": "staged", "type": "boolean", "required": False,
                     "description": "Show the index diff instead of the working tree."},
                    {"name": "limit", "type": "integer", "required": False,
                     "description": "Maximum diff lines to return.", "minimum": 20,
                     "maximum": 2000},
                ),
                "returns": "{diff, truncated, files_changed}",
                "capabilities": ("workspace.read", "process.execute"),
                "runs": "git diff [--cached] --no-color",
            },
            {
                "id": "run_check",
                "description": (
                    "Run one named project check (build, test or lint) through a "
                    "script declared in the package configuration. The command is "
                    "an allowlist entry, never a free-form shell string."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to the repository root.", "scope": "path"},
                    {"name": "check", "type": "string", "required": True,
                     "description": "Which declared check to run.",
                     "enum": ("build", "test", "lint")},
                ),
                "returns": "{check, exit_code, duration_ms, tail}",
                "capabilities": ("workspace.read", "process.execute"),
                "runs": "the configured script for the check",
            },
        ),
        "guardrails": (
            "Default to read-only. A write tool is a separate, explicitly named action.",
            "Never expose a free-form shell argument; allowlist the programs and the checks.",
            "Never force-push, amend a published commit or rewrite history from a tool.",
            "Bound diff and log output; a 10 MB diff is not a review.",
            "Redact tokens from command output before returning it.",
            "Scope process.execute to program:git and program:python3, not to any program.",
        ),
        "build_order": (
            "Implement repo_status and prove it handles a detached HEAD and a non-repository path.",
            "Add repo_diff with a line limit and truncation field.",
            "Add run_check with an allowlist from the package configuration.",
            "Write the status command and panel; both read the same functions.",
            "Add the release-hygiene skill and the repository context.",
            "Run smoke with one real repository, then check with smoke=true.",
        ),
        "gates": (
            "A path outside a repository returns a clear error, not a traceback.",
            "The diff is truncated and says so.",
            "No tool accepts an arbitrary command string.",
            "The process grant names the programs the package actually runs.",
        ),
        "open_questions": (
            "Which checks are authoritative, and where are their scripts?",
            "Is the repository a monorepo with per-package checks?",
            "Which branch policy must a release note follow?",
        ),
    },
    "data": {
        "title": "Database and dataset work",
        "summary": (
            "Answers schema and query questions against one configured "
            "connection. Read-only by default, row-limited, with the DSN kept in "
            "the vault and never echoed."
        ),
        "signals": (
            "sql", "database", "db", "query", "dataset", "analytics", "warehouse",
            "postgres", "postgresql", "sqlite", "mysql", "duckdb", "csv", "parquet",
            "etl", "metrics", "bi", "table", "schema", "bigquery", "snowflake",
        ),
        "runtime": "process",
        "runtime_reason": (
            "The package needs a database driver or CLI and a vaulted credential. "
            "A declarative runtime cannot connect, so process is the smallest "
            "runtime that can do the work."
        ),
        "capabilities": (
            "process.execute", "secrets.read", "workspace.read", "workspace.write",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide", "agent.context.provide",
        ),
        "reasons": {
            "process.execute": "runs the database client or driver",
            "secrets.read": "loads the connection credential by name from the vault",
            "workspace.read": "reads a local dataset or a saved SQL file",
            "workspace.write": "writes an export to the path the reader names",
            "agent.tools.register": "exposes tables, schema, query and export",
            "ui.commands": "adds /schema and /query",
            "ui.panels": "adds the dataset panel",
            "agent.skills.provide": "ships the query-safety workflow",
            "agent.context.provide": "adds dialect and read-only conventions",
        },
        "grant_scopes": {
            "process.execute": ("program:python3", "program:psql"),
            "secrets.read": ("secret:<CONNECTION_SECRET_NAME>",),
            "workspace.write": ("path:<absolute export directory>",),
        },
        "contributions": (
            {"kind": "command", "id": "show-schema",
             "purpose": "Describe one table without selecting its rows."},
            {"kind": "command", "id": "run-query",
             "purpose": "Run one read-only query with a row limit."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Read-only SQL, row limits and PII redaction."},
            {"kind": "context", "id": "dataset",
             "purpose": "Dialect, connection names and table ownership."},
        ),
        "skill": {
            "id": "query-safety",
            "purpose": "Ask before a write, bound every result, never print a DSN.",
        },
        "panel": {"id": "overview", "purpose": "Configured connection, dialect and last query time."},
        "tools": (
            {
                "id": "tables",
                "description": (
                    "List the tables visible to one configured connection, with "
                    "schema and approximate size where the dialect reports it."
                ),
                "args": (
                    {"name": "connection", "type": "string", "required": True,
                     "description": "Configured connection name, never a DSN."},
                ),
                "returns": "[{schema, table, kind, row_estimate}]",
                "capabilities": ("secrets.read", "process.execute"),
                "runs": "the configured client's table listing",
            },
            {
                "id": "schema",
                "description": (
                    "Describe one table: columns, types, nullability and keys. It "
                    "reads metadata, not rows."
                ),
                "args": (
                    {"name": "connection", "type": "string", "required": True,
                     "description": "Configured connection name."},
                    {"name": "table", "type": "string", "required": True,
                     "description": "Table name, optionally schema-qualified."},
                ),
                "returns": "{table, columns: [{name, type, nullable}], keys}",
                "capabilities": ("secrets.read", "process.execute"),
                "runs": "the configured client's describe statement",
            },
            {
                "id": "query",
                "description": (
                    "Run one read-only SELECT/WITH/EXPLAIN query and return at most "
                    "the requested rows. DDL, DML and multiple statements are refused."
                ),
                "args": (
                    {"name": "connection", "type": "string", "required": True,
                     "description": "Configured connection name."},
                    {"name": "sql", "type": "string", "required": True,
                     "description": "One read-only SQL statement."},
                    {"name": "limit", "type": "integer", "required": False,
                     "description": "Maximum rows to return.", "minimum": 1,
                     "maximum": 1000},
                ),
                "returns": "{columns, rows, row_count, truncated}",
                "capabilities": ("secrets.read", "process.execute"),
                "runs": "the configured client with a read-only session",
            },
            {
                "id": "export",
                "description": (
                    "Run one read-only query and write the result to a new file. "
                    "The source data is never modified and the target is never "
                    "overwritten without an explicit flag."
                ),
                "args": (
                    {"name": "connection", "type": "string", "required": True,
                     "description": "Configured connection name."},
                    {"name": "sql", "type": "string", "required": True,
                     "description": "One read-only SQL statement."},
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute output path.", "scope": "path"},
                ),
                "returns": "{path, bytes, rows, columns}",
                "capabilities": ("secrets.read", "workspace.write", "process.execute"),
                "runs": "the configured client, then a bounded file write",
            },
        ),
        "guardrails": (
            "Use a read-only role and a read-only session; a SELECT-only parser is a second gate, not the first.",
            "Always apply a row limit and report truncation.",
            "Keep the DSN and password in the vault; the tool takes a connection name, never a URL.",
            "Never print a secret in an error, a log line or a tool result; redact before raising.",
            "Do not run DDL or DML from a tool named query. A write is a separate tool with a separate review.",
            "Redact PII columns by policy; a result set is data leaving the database.",
        ),
        "build_order": (
            "Write the connection configuration schema with names, not DSNs.",
            "Implement tables and schema against a local fixture database.",
            "Add query with a parser that accepts only SELECT/WITH/EXPLAIN.",
            "Add the row limit and the truncated flag; test a 10k-row table.",
            "Add export with a target that can never equal the source.",
            "Add the command, panel, skill and context, then smoke each tool.",
        ),
        "gates": (
            "A DELETE or multiple statements is refused before it reaches the client.",
            "The row limit applies even when the SQL has no LIMIT.",
            "The credential never appears in output, stderr or an error message.",
            "A cancelled query releases the connection.",
        ),
        "open_questions": (
            "Which dialect and which client binary will run the queries?",
            "Is there a read-only role, and what is its name?",
            "Which columns are PII, and who owns the redaction list?",
        ),
    },
    "web": {
        "title": "HTTP API and SaaS integration",
        "summary": (
            "Wraps one external API behind a small authenticated surface. "
            "Domain-scoped network access, vaulted credentials, explicit "
            "pagination and errors a reader can act on."
        ),
        "signals": (
            "api", "http", "rest", "graphql", "webhook", "endpoint", "saas",
            "integration", "stripe", "jira", "notion", "github api", "crm",
            "service", "client", "sdk", "oauth", "token",
        ),
        "runtime": "process",
        "runtime_reason": (
            "Authenticated HTTP with retries, pagination and response shaping "
            "needs code. A declarative runtime makes no network requests, so "
            "process is the honest runtime."
        ),
        "capabilities": (
            "network.http", "secrets.read", "workspace.read", "workspace.write",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide", "agent.context.provide",
        ),
        "reasons": {
            "network.http": "calls the one API host the package is for",
            "secrets.read": "loads the API token by name from the vault",
            "workspace.read": "reads a request body or a saved fixture",
            "workspace.write": "writes a sync report or a downloaded artifact",
            "agent.tools.register": "exposes get, list and sync",
            "ui.commands": "adds /fetch and /sync",
            "ui.panels": "adds the API panel",
            "agent.skills.provide": "ships the api-etiquette workflow",
            "agent.context.provide": "adds base URL, auth and rate-limit facts",
        },
        "grant_scopes": {
            "network.http": ("domain:<api-host>",),
            "secrets.read": ("secret:<API_TOKEN_NAME>",),
            "workspace.write": ("path:<absolute output directory>",),
        },
        "contributions": (
            {"kind": "command", "id": "fetch",
             "purpose": "Read one resource and summarise the fields that matter."},
            {"kind": "command", "id": "pull",
             "purpose": "Pull a bounded page set into a local report."},
            {"kind": "prompt", "id": "rules",
             "purpose": "One host, one token, no secrets in output."},
            {"kind": "context", "id": "api",
             "purpose": "Base URL, auth shape, pagination and rate limits."},
        ),
        "skill": {
            "id": "api-etiquette",
            "purpose": "Page safely, respect limits and never leak a credential.",
        },
        "panel": {"id": "overview", "purpose": "Host, auth state and the last request result."},
        "tools": (
            {
                "id": "get",
                "description": (
                    "Read one resource by path from the configured API host and "
                    "return a bounded JSON shape. The host is fixed by the package, "
                    "not by the argument."
                ),
                "args": (
                    {"name": "url", "type": "string", "required": True,
                     "description": "Path or URL under the configured API host.",
                     "scope": "url"},
                    {"name": "fields", "type": "string", "required": False,
                     "description": "Comma-separated fields to keep in the result."},
                ),
                "returns": "{status, data, truncated, request_id}",
                "capabilities": ("network.http", "secrets.read"),
                "runs": "an authenticated GET against the allowlisted host",
            },
            {
                "id": "list",
                "description": (
                    "List one collection with a page size and a hard page cap. It "
                    "reports the next cursor instead of looping forever."
                ),
                "args": (
                    {"name": "resource", "type": "string", "required": True,
                     "description": "Collection name, for example issues or users."},
                    {"name": "limit", "type": "integer", "required": False,
                     "description": "Items per page.", "minimum": 1, "maximum": 100},
                    {"name": "page", "type": "string", "required": False,
                     "description": "Cursor or page token from a previous call."},
                ),
                "returns": "{items, next_page, count, truncated}",
                "capabilities": ("network.http", "secrets.read"),
                "runs": "an authenticated paginated GET",
            },
            {
                "id": "sync",
                "description": (
                    "Pull a bounded set of resources into a local JSON report. It "
                    "reads the remote side and writes only the report path."
                ),
                "args": (
                    {"name": "resource", "type": "string", "required": True,
                     "description": "Collection to pull."},
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute output path for the report.", "scope": "path"},
                    {"name": "limit", "type": "integer", "required": False,
                     "description": "Maximum records to write.", "minimum": 1,
                     "maximum": 5000},
                ),
                "returns": "{path, records, bytes, next_page}",
                "capabilities": ("network.http", "secrets.read", "workspace.write"),
                "runs": "paginated GETs, then one bounded file write",
            },
        ),
        "guardrails": (
            "Allowlist the host and schema; never accept an arbitrary URL.",
            "Scope network.http to domain:<api-host>, and secrets.read to the one secret name.",
            "Never put a token in a URL, a query string or an error message.",
            "Respect Retry-After and 429; back off with a cap instead of retrying immediately.",
            "Default to GET. A write needs an explicit tool and an explicit confirmation.",
            "Bound pages and body size; report truncation rather than silently cutting data.",
        ),
        "build_order": (
            "Write the configuration schema: base URL, auth mode, secret name, page size.",
            "Implement get against one real fixture and prove a 401 is a clear error.",
            "Add list with cursor handling and a hard page cap.",
            "Add sync with a report path and a record limit.",
            "Add the command, panel, skill and API context.",
            "Run smoke against a recorded fixture; verify no secret reaches the output.",
        ),
        "gates": (
            "A URL outside the allowlisted host is refused before the request.",
            "401, 403, 404 and 429 each produce an actionable message.",
            "The token does not appear in stdout, stderr, tool results or events.",
            "Pagination ends, and the end is reported.",
        ),
        "open_questions": (
            "What is the exact API host and auth flow?",
            "Which endpoints may write, and who confirms a write?",
            "What are the rate limits and the retention rules for synced data?",
        ),
    },
    "documents": {
        "title": "Documents, reports and file conversion",
        "summary": (
            "Extracts, outlines and converts office documents without touching "
            "the source. Writes a new artifact, reports what it changed, and "
            "refuses encrypted or oversized input."
        ),
        "signals": (
            "document", "docx", "pdf", "markdown", "office", "spreadsheet",
            "xlsx", "pptx", "convert", "extract", "summarize", "report",
            "template", "doc", "word", "excel", "powerpoint",
        ),
        "runtime": "process",
        "runtime_reason": (
            "Parsing and rendering office formats needs libraries and file IO. A "
            "declarative runtime can only transform JSON, so process is required."
        ),
        "capabilities": (
            "process.execute", "workspace.read", "workspace.write",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide", "agent.context.provide",
        ),
        "reasons": {
            "process.execute": "runs the document library or converter",
            "workspace.read": "reads the source document",
            "workspace.write": "writes a new converted or extracted artifact",
            "agent.tools.register": "exposes extract, outline and convert",
            "ui.commands": "adds /extract and /convert",
            "ui.panels": "adds the documents panel",
            "agent.skills.provide": "ships the document-safety workflow",
            "agent.context.provide": "adds format and naming conventions",
        },
        "grant_scopes": {
            "process.execute": ("program:python3",),
            "workspace.write": ("path:<absolute output directory>",),
        },
        "contributions": (
            {"kind": "command", "id": "read-document",
             "purpose": "Extract text and structure from a document."},
            {"kind": "command", "id": "convert-document",
             "purpose": "Convert a document to a new file in a named format."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Never modify the source; write a sibling artifact."},
            {"kind": "context", "id": "documents",
             "purpose": "Formats, naming and template locations."},
        ),
        "skill": {
            "id": "document-safety",
            "purpose": "Preserve the source, verify the output and report fidelity.",
        },
        "panel": {"id": "overview", "purpose": "Last source, output format and output path."},
        "tools": (
            {
                "id": "extract",
                "description": (
                    "Extract text blocks, headings and tables from a document into "
                    "a structured result. It never writes to the source."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to the source document.", "scope": "path"},
                    {"name": "format", "type": "string", "required": False,
                     "description": "How to shape the result.",
                     "enum": ("text", "outline", "tables")},
                ),
                "returns": "{source, format, blocks, tables, truncated}",
                "capabilities": ("workspace.read", "process.execute"),
                "runs": "the configured parser for the file type",
            },
            {
                "id": "outline",
                "description": (
                    "Return the heading and page structure of a document so the "
                    "reader can navigate it before extracting everything."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to the source document.", "scope": "path"},
                ),
                "returns": "[{level, title, page, offset}]",
                "capabilities": ("workspace.read", "process.execute"),
                "runs": "the configured parser in outline mode",
            },
            {
                "id": "convert",
                "description": (
                    "Convert a document to a new file. The output path must differ "
                    "from the source and must not exist unless overwrite is true."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to the source document.", "scope": "path"},
                    {"name": "out", "type": "string", "required": True,
                     "description": "Absolute output path.", "scope": "path"},
                    {"name": "format", "type": "string", "required": True,
                     "description": "Target format.", "enum": ("docx", "pdf", "md", "xlsx")},
                    {"name": "overwrite", "type": "boolean", "required": False,
                     "description": "Replace an existing output file."},
                ),
                "returns": "{source, out, format, bytes, source_unchanged}",
                "capabilities": ("workspace.read", "workspace.write", "process.execute"),
                "runs": "the configured converter, then a verified write",
            },
        ),
        "guardrails": (
            "Never write in place; refuse when out resolves to the source path.",
            "Refuse encrypted or password-protected files with a clear message.",
            "Bound input size and page/row count; a 500 MB workbook is not a tool call.",
            "Do not fetch remote images or follow external relationships while converting.",
            "Report fidelity: what was dropped (macros, comments, fonts) and what was kept.",
            "Never execute macros or embedded scripts.",
        ),
        "build_order": (
            "Implement outline first; it proves the parser without writing files.",
            "Add extract with text, outline and tables modes and a size cap.",
            "Add convert with a source/out inequality check and overwrite flag.",
            "Add the command, panel, skill and context.",
            "Test an encrypted file, an oversized file and a path with spaces.",
            "Run check with smoke on a small fixture.",
        ),
        "gates": (
            "The source file hash is unchanged after every tool.",
            "out == source is refused before any write.",
            "Encrypted and oversized files fail with a readable error.",
            "The result says which structures were dropped.",
        ),
        "open_questions": (
            "Which formats must round-trip, and which may be lossy?",
            "Where do templates live and who owns them?",
            "Are documents confidential, and where may converted output be stored?",
        ),
    },
    "media": {
        "title": "Audio, video and image processing",
        "summary": (
            "Probes and transforms media into new files. Long-running work with "
            "bounded timeouts, explicit codecs and a source that is never "
            "overwritten."
        ),
        "signals": (
            "video", "audio", "image", "media", "ffmpeg", "transcode", "clip",
            "subtitle", "caption", "thumbnail", "podcast", "recording", "codec",
            "frame", "waveform",
        ),
        "runtime": "process",
        "runtime_reason": (
            "Media work means invoking ffmpeg or an image library and streaming "
            "large files. A declarative runtime cannot start a process."
        ),
        "capabilities": (
            "process.execute", "workspace.read", "workspace.write",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide", "agent.context.provide",
        ),
        "reasons": {
            "process.execute": "runs ffmpeg or the image tool",
            "workspace.read": "reads the source media",
            "workspace.write": "writes a new render or probe report",
            "agent.tools.register": "exposes probe, clip and transcode",
            "ui.commands": "adds /probe and /clip",
            "ui.panels": "adds the media panel",
            "agent.skills.provide": "ships the media-safety workflow",
            "agent.context.provide": "adds codec and storage conventions",
        },
        "grant_scopes": {
            "process.execute": ("program:python3", "program:ffmpeg"),
            "workspace.write": ("path:<absolute output directory>",),
        },
        "contributions": (
            {"kind": "command", "id": "inspect-media",
             "purpose": "Report duration, streams, codecs and size before a render."},
            {"kind": "command", "id": "cut-clip",
             "purpose": "Cut a time range into a new file."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Never overwrite the source; estimate before encoding."},
            {"kind": "context", "id": "media",
             "purpose": "Container, codec, storage and naming conventions."},
        ),
        "skill": {
            "id": "media-safety",
            "purpose": "Probe, estimate, render to a new path, verify the result.",
        },
        "panel": {"id": "overview", "purpose": "Duration, codecs, output size and last render time."},
        "tools": (
            {
                "id": "probe",
                "description": (
                    "Read a media file's duration, streams, codecs, resolution and "
                    "size without modifying it."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to the media file.", "scope": "path"},
                ),
                "returns": "{duration_s, streams: [...], size_bytes, container}",
                "capabilities": ("workspace.read", "process.execute"),
                "runs": "ffprobe",
            },
            {
                "id": "clip",
                "description": (
                    "Cut one time range into a new file. Timestamps are validated "
                    "against the probed duration and the source is never touched."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to the source media.", "scope": "path"},
                    {"name": "start", "type": "string", "required": True,
                     "description": "Start timestamp, HH:MM:SS or seconds."},
                    {"name": "end", "type": "string", "required": True,
                     "description": "End timestamp, HH:MM:SS or seconds."},
                    {"name": "out", "type": "string", "required": True,
                     "description": "Absolute output path.", "scope": "path"},
                ),
                "returns": "{out, duration_s, bytes, source_unchanged}",
                "capabilities": ("workspace.read", "workspace.write", "process.execute"),
                "runs": "ffmpeg with stream copy where possible",
            },
            {
                "id": "transcode",
                "description": (
                    "Transcode to a named format and quality preset. It reports the "
                    "estimated size before encoding and refuses to overwrite the source."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to the source media.", "scope": "path"},
                    {"name": "out", "type": "string", "required": True,
                     "description": "Absolute output path.", "scope": "path"},
                    {"name": "format", "type": "string", "required": True,
                     "description": "Target container.", "enum": ("mp4", "webm", "mp3", "wav")},
                    {"name": "quality", "type": "string", "required": False,
                     "description": "Named quality preset.", "enum": ("draft", "standard", "high")},
                ),
                "returns": "{out, codec, bytes, duration_s, elapsed_s}",
                "capabilities": ("workspace.read", "workspace.write", "process.execute"),
                "runs": "ffmpeg with the configured preset",
            },
        ),
        "guardrails": (
            "Never overwrite the source; refuse when out equals path.",
            "Validate timestamps against the probed duration before starting ffmpeg.",
            "Estimate output size and check free space before a long encode.",
            "Set a hard timeout and report partial output; do not leave a temp file behind.",
            "Allowlist containers and codecs; no arbitrary ffmpeg arguments.",
            "Keep renders local unless the reader explicitly asks for an upload.",
        ),
        "build_order": (
            "Implement probe and print a stable summary for an empty and a real file.",
            "Add clip with timestamp validation and a stream-copy fast path.",
            "Add transcode with a preset table, timeout and output size check.",
            "Add the command, panel, skill and media context.",
            "Test a bad timestamp, a source/out collision and a long render.",
            "Run check with smoke on a one-second fixture.",
        ),
        "gates": (
            "A bad or reversed timestamp is refused before ffmpeg starts.",
            "The source remains byte-identical.",
            "A timeout leaves no partial file at the requested output path.",
            "The result reports elapsed time and output size.",
        ),
        "open_questions": (
            "Which codecs and containers must be supported?",
            "Where may large output live, and how long is it retained?",
            "Is hardware acceleration available?",
        ),
    },
    "messaging": {
        "title": "Chat, email and notifications",
        "summary": (
            "Drafts and reads messages, and sends only after an explicit "
            "confirmation. Vaulted credentials, channel allowlists and an "
            "idempotency key for every send."
        ),
        "signals": (
            "message", "chat", "slack", "teams", "email", "mail", "notify",
            "notification", "webhook", "sms", "channel", "inbox", "mention",
            "send", "draft", "outbox", "newsletter",
        ),
        "runtime": "process",
        "runtime_reason": (
            "Authenticated messaging APIs and their formatting rules need code. "
            "A declarative runtime cannot call them."
        ),
        "capabilities": (
            "network.http", "secrets.read", "workspace.read",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide", "agent.context.provide",
        ),
        "reasons": {
            "network.http": "calls the messaging provider's API",
            "secrets.read": "loads the bot or user token from the vault",
            "workspace.read": "reads a draft or an attachment path",
            "agent.tools.register": "exposes draft, read_thread and send",
            "ui.commands": "adds /draft and /send",
            "ui.panels": "adds the outbox panel",
            "agent.skills.provide": "ships the message-safety workflow",
            "agent.context.provide": "adds channel and tone conventions",
        },
        "grant_scopes": {
            "network.http": ("domain:<messaging-host>",),
            "secrets.read": ("secret:<MESSAGING_TOKEN_NAME>",),
        },
        "contributions": (
            {"kind": "command", "id": "compose",
             "purpose": "Compose a message and show it without sending."},
            {"kind": "command", "id": "deliver",
             "purpose": "Send the reviewed draft after an explicit confirmation."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Draft first; never send without confirmation."},
            {"kind": "context", "id": "messaging",
             "purpose": "Channels, audience and tone rules."},
        ),
        "skill": {
            "id": "message-safety",
            "purpose": "Draft, confirm, send idempotently, and never leak a token.",
        },
        "panel": {"id": "overview", "purpose": "Last draft, target channel and send state."},
        "tools": (
            {
                "id": "draft",
                "description": (
                    "Compose a message for a channel and return it with a draft id. "
                    "Drafting never sends anything."
                ),
                "args": (
                    {"name": "channel", "type": "string", "required": True,
                     "description": "Configured channel or address name."},
                    {"name": "text", "type": "string", "required": True,
                     "description": "The message body to stage."},
                ),
                "returns": "{draft_id, channel, text, warnings}",
                "capabilities": ("workspace.read",),
                "runs": "local validation and formatting only",
            },
            {
                "id": "read_thread",
                "description": (
                    "Read the most recent messages from one configured channel, "
                    "bounded by count and age."
                ),
                "args": (
                    {"name": "channel", "type": "string", "required": True,
                     "description": "Configured channel name."},
                    {"name": "limit", "type": "integer", "required": False,
                     "description": "Maximum messages to return.", "minimum": 1,
                     "maximum": 100},
                ),
                "returns": "{channel, messages: [{author, timestamp, text}], truncated}",
                "capabilities": ("network.http", "secrets.read"),
                "runs": "an authenticated channel history read",
            },
            {
                "id": "send",
                "description": (
                    "Send one previously drafted message. It requires the draft id "
                    "and an explicit confirm=true, and uses an idempotency key."
                ),
                "args": (
                    {"name": "draft_id", "type": "string", "required": True,
                     "description": "The id returned by draft."},
                    {"name": "confirm", "type": "boolean", "required": True,
                     "description": "Must be true; the reader confirms the send."},
                ),
                "returns": "{sent, message_id, channel, at}",
                "capabilities": ("network.http", "secrets.read"),
                "runs": "an authenticated idempotent send",
            },
        ),
        "guardrails": (
            "Draft and send are separate calls; send refuses without confirm=true.",
            "Never auto-send from a hook, a workflow or a scheduler without a named human decision.",
            "Use an idempotency key so a retry cannot double-post.",
            "Allowlist channels; never enumerate a whole workspace.",
            "Redact tokens and private message content from logs and errors.",
            "Respect Retry-After and rate limits; queue, do not hammer.",
        ),
        "build_order": (
            "Implement draft with local formatting and a draft store.",
            "Add read_thread with a message and age cap.",
            "Add send with confirm and idempotency; test a repeated call.",
            "Add the command, outbox panel, skill and messaging context.",
            "Test a 429, a missing token and an unconfirmed send.",
            "Run check with smoke against a recorded response.",
        ),
        "gates": (
            "send without confirm=true is refused.",
            "A repeated send with the same draft id does not post twice.",
            "The token never appears in a draft, a result or an error.",
            "Channel enumeration is impossible.",
        ),
        "open_questions": (
            "Which channels are in scope, and who approves a send?",
            "Is the token a bot token or a user token?",
            "What retention or audit rule applies to sent messages?",
        ),
    },
    "security": {
        "title": "Security review and secret scanning",
        "summary": (
            "Runs a bounded scan and reports findings with a fingerprint instead "
            "of the secret. Read-only, redacted, and explicit about what it "
            "cannot see."
        ),
        "signals": (
            "security", "audit", "scan", "vulnerability", "secrets", "cve",
            "compliance", "pentest", "policy", "leak", "sbom", "dependency",
            "redact", "finding",
        ),
        "runtime": "process",
        "runtime_reason": (
            "The package runs scanners over a repository and must bound and "
            "redact their output. A declarative runtime cannot execute a scanner."
        ),
        "capabilities": (
            "process.execute", "workspace.read", "workspace.write",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide", "agent.context.provide",
        ),
        "reasons": {
            "process.execute": "runs the configured scanner",
            "workspace.read": "reads repository files for the scan",
            "workspace.write": "writes the report the reader asks for",
            "agent.tools.register": "exposes scan, findings and report",
            "ui.commands": "adds /scan and /report",
            "ui.panels": "adds the findings panel",
            "agent.skills.provide": "ships the redaction workflow",
            "agent.context.provide": "adds severity and ownership conventions",
        },
        "grant_scopes": {
            "process.execute": ("program:python3", "program:<scanner>"),
            "workspace.write": ("path:<absolute report directory>",),
        },
        "contributions": (
            {"kind": "command", "id": "run-scan",
             "purpose": "Run one scanner profile over a path."},
            {"kind": "command", "id": "write-report",
             "purpose": "Turn findings into a report with owners and severities."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Never print a secret; report a fingerprint."},
            {"kind": "context", "id": "security",
             "purpose": "Scanner profiles, severity policy and ownership."},
        ),
        "skill": {
            "id": "redaction",
            "purpose": "Scan read-only, redact before reporting, escalate by severity.",
        },
        "panel": {"id": "overview", "purpose": "Last scan, finding counts by severity, report path."},
        "tools": (
            {
                "id": "scan",
                "description": (
                    "Run one named scanner profile over a path and return bounded "
                    "findings. It never prints a matched secret, only a fingerprint."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to scan.", "scope": "path"},
                    {"name": "profile", "type": "string", "required": False,
                     "description": "Scanner profile from the configuration.",
                     "enum": ("secrets", "dependencies", "repo")},
                ),
                "returns": "{profile, findings: [{rule, severity, path, line, fingerprint}], truncated}",
                "capabilities": ("workspace.read", "process.execute"),
                "runs": "the configured scanner with redacted output",
            },
            {
                "id": "findings",
                "description": (
                    "Read the findings from the last scan, filtered by severity and "
                    "path. It does not rescan."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path the scan covered.", "scope": "path"},
                    {"name": "severity", "type": "string", "required": False,
                     "description": "Minimum severity to return.",
                     "enum": ("low", "medium", "high", "critical")},
                ),
                "returns": "{findings, counts, scan_at}",
                "capabilities": ("workspace.read",),
                "runs": "a read of the stored findings",
            },
            {
                "id": "report",
                "description": (
                    "Write the findings to a new Markdown or JSON report with "
                    "severity, owner and remediation. It never includes a secret value."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path the scan covered.", "scope": "path"},
                    {"name": "out", "type": "string", "required": True,
                     "description": "Absolute output path.", "scope": "path"},
                    {"name": "format", "type": "string", "required": False,
                     "description": "Report format.", "enum": ("md", "json")},
                ),
                "returns": "{out, findings, bytes, redacted}",
                "capabilities": ("workspace.read", "workspace.write"),
                "runs": "a redacting renderer over stored findings",
            },
        ),
        "guardrails": (
            "Read-only by default; a scanner must not modify the repository.",
            "Never print a secret value, a private key or a full token. Use a stable fingerprint.",
            "Do not follow symlinks out of the scanned root.",
            "Bound file count, file size and runtime; report what was skipped.",
            "Do not send findings or code to a remote service without an explicit, scoped grant.",
            "A finding is not a fix: name the owner and the remediation step.",
        ),
        "build_order": (
            "Implement scan with a fixture and a redaction test that fails if a secret appears.",
            "Add findings with severity filtering.",
            "Add report with a deterministic renderer and no secret values.",
            "Add the command, panel, skill and security context.",
            "Test a symlink, a binary file and a 429 from the scanner.",
            "Run check with smoke on a deliberately unsafe fixture.",
        ),
        "gates": (
            "A fake token in the fixture never appears in any output.",
            "A symlink outside the root is skipped and reported.",
            "The scan has a runtime cap and reports truncation.",
            "The report names an owner for every high finding.",
        ),
        "open_questions": (
            "Which scanner and which profile is authoritative?",
            "Who owns a finding, and where does it get ticketed?",
            "May code or findings leave the machine?",
        ),
    },
    "research": {
        "title": "Web research and source capture",
        "summary": (
            "Searches, fetches and extracts sources with citations, rate limits "
            "and a local capture. It respects robots and terms, and never "
            "bypasses a paywall."
        ),
        "signals": (
            "research", "search", "web", "article", "news", "citation", "source",
            "browser", "crawl", "scrape", "page", "url", "fetch", "extract",
            "summarize", "report",
        ),
        "runtime": "process",
        "runtime_reason": (
            "Fetching pages, extracting text and caching sources needs HTTP and "
            "parsing code. A declarative runtime makes no network requests."
        ),
        "capabilities": (
            "network.http", "workspace.read", "workspace.write",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide", "agent.context.provide",
        ),
        "reasons": {
            "network.http": "fetches search results and pages",
            "workspace.read": "reads a saved capture or a URL list",
            "workspace.write": "writes a capture or a notes file",
            "agent.tools.register": "exposes search, fetch and notes",
            "ui.commands": "adds /fetch and /notes",
            "ui.panels": "adds the research panel",
            "agent.skills.provide": "ships the citation workflow",
            "agent.context.provide": "adds source and citation conventions",
        },
        "grant_scopes": {
            "network.http": ("domain:<search-host>", "domain:<target-host>"),
            "workspace.write": ("path:<absolute notes directory>",),
        },
        "contributions": (
            {"kind": "command", "id": "capture",
             "purpose": "Fetch one URL and capture the readable text."},
            {"kind": "command", "id": "write-notes",
             "purpose": "Write a sourced note with links and timestamps."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Cite every claim; respect robots and terms."},
            {"kind": "context", "id": "research",
             "purpose": "Allowed sources, citation style and retention."},
        ),
        "skill": {
            "id": "citations",
            "purpose": "Search, fetch, quote and cite without laundering a source.",
        },
        "panel": {"id": "overview", "purpose": "Fetched sources, capture paths and last fetch time."},
        "tools": (
            {
                "id": "search",
                "description": (
                    "Search the configured provider and return titles, URLs and "
                    "snippets. It does not fetch the result pages."
                ),
                "args": (
                    {"name": "query", "type": "string", "required": True,
                     "description": "The search query."},
                    {"name": "limit", "type": "integer", "required": False,
                     "description": "Maximum results.", "minimum": 1, "maximum": 20},
                ),
                "returns": "{results: [{title, url, snippet}], count}",
                "capabilities": ("network.http",),
                "runs": "the configured search endpoint",
            },
            {
                "id": "fetch",
                "description": (
                    "Fetch one URL, extract its readable text and return a capture "
                    "id. It reports the status and content type instead of guessing."
                ),
                "args": (
                    {"name": "url", "type": "string", "required": True,
                     "description": "Absolute http(s) URL.", "scope": "url"},
                    {"name": "max_chars", "type": "integer", "required": False,
                     "description": "Maximum extracted characters.", "minimum": 500,
                     "maximum": 200000},
                ),
                "returns": "{status, content_type, title, text, truncated, capture_id}",
                "capabilities": ("network.http",),
                "runs": "an HTTP GET, then a readable-text extraction",
            },
            {
                "id": "notes",
                "description": (
                    "Write a sourced note: claims with the URL and capture id they "
                    "came from. It refuses to write an uncited claim."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute output path for the note.", "scope": "path"},
                    {"name": "capture_id", "type": "string", "required": True,
                     "description": "A capture id returned by fetch."},
                ),
                "returns": "{path, bytes, citations}",
                "capabilities": ("workspace.write",),
                "runs": "a bounded, citation-checked write",
            },
        ),
        "guardrails": (
            "Cite the exact URL and access time for every factual claim.",
            "Respect robots.txt, terms of service and rate limits; do not bypass a paywall.",
            "Do not fetch private or internal URLs unless the reader names them and the grant covers the host.",
            "Bound response size, redirects and time; report what was skipped.",
            "Keep captures local; do not upload them to another service.",
            "A summary is not a source: link the capture, not only the prose.",
        ),
        "build_order": (
            "Implement search and print stable results.",
            "Add fetch with redirect, size and content-type limits.",
            "Add notes with a citation check that refuses an uncited claim.",
            "Add the command, panel, skill and research context.",
            "Test a 404, a PDF, a redirect loop and robots denial.",
            "Run check with smoke against a local fixture server.",
        ),
        "gates": (
            "Every note line names a URL or a capture id.",
            "A redirect loop and an oversized body are refused.",
            "robots.txt and rate limits are honoured.",
            "Captures stay under the workspace path the grant covers.",
        ),
        "open_questions": (
            "Which search provider and which domains are allowed?",
            "What citation style does the team require?",
            "How long may a capture be retained?",
        ),
    },
    "model": {
        "title": "Model and agent provider",
        "summary": (
            "Adds a model or agent provider, usually with a small local relay "
            "when the upstream wire shape does not match the host's. Keyless or "
            "keyed, declared honestly, with no credential in logs."
        ),
        "signals": (
            "model", "provider", "llm", "inference", "relay", "token",
            "completion", "local model", "ollama", "openai", "anthropic",
            "agent", "prompt", "streaming",
        ),
        "runtime": "process",
        "runtime_reason": (
            "A provider descriptor alone cannot add headers, reshape a stream or "
            "hold a key. When the upstream needs any of that, a process relay is "
            "the honest runtime; a pure descriptor is better when it does not."
        ),
        "capabilities": (
            "network.http", "process.execute", "secrets.read",
            "agent.models.provide", "agent.agents.provide",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide",
        ),
        "reasons": {
            "network.http": "forwards model calls to the upstream provider",
            "process.execute": "runs the local relay",
            "secrets.read": "loads the upstream key when the provider needs one",
            "agent.models.provide": "registers the model provider descriptor",
            "agent.agents.provide": "registers the agent role when the package offers one",
            "agent.tools.register": "exposes models, status and refresh",
            "ui.commands": "adds /models and /status",
            "ui.panels": "adds the provider panel",
            "agent.skills.provide": "ships the provider-safety workflow",
        },
        "grant_scopes": {
            "network.http": ("domain:<upstream-host>",),
            "process.execute": ("program:python3",),
            "secrets.read": ("secret:<UPSTREAM_API_KEY_NAME>",),
        },
        "contributions": (
            {"kind": "command", "id": "list-models",
             "purpose": "List the models the provider exposes."},
            {"kind": "command", "id": "provider-status",
             "purpose": "Show relay health and the bound upstream host."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Never print a key; fail closed when the relay is down."},
            {"kind": "context", "id": "provider",
             "purpose": "Upstream host, wire shape and key policy."},
        ),
        "skill": {
            "id": "provider-safety",
            "purpose": "Bind the relay, prove the key path and never log a credential.",
        },
        "panel": {"id": "overview", "purpose": "Relay state, upstream host, model count."},
        "tools": (
            {
                "id": "models",
                "description": (
                    "List the models the configured provider exposes, with the "
                    "wire protocol and whether a key is required."
                ),
                "args": (),
                "returns": "{models: [{id, name, context}], requires_key, upstream}",
                "capabilities": ("network.http",),
                "runs": "a provider model listing, cached for the session",
            },
            {
                "id": "status",
                "description": (
                    "Report relay and provider health: bind address, upstream host, "
                    "last error and whether a key is configured, never the key."
                ),
                "args": (),
                "returns": "{bound, upstream, key_present, last_error, models}",
                "capabilities": ("network.http", "secrets.read"),
                "runs": "a local health check",
            },
            {
                "id": "refresh",
                "description": (
                    "Refresh the model list and rebind the relay. It refuses to run "
                    "while a model call is in flight."
                ),
                "args": (),
                "returns": "{refreshed, models, bound, duration_ms}",
                "capabilities": ("network.http", "secrets.read"),
                "runs": "a cache refresh and a loopback rebind",
            },
        ),
        "guardrails": (
            "Never log or return an API key; report key_present, not the value.",
            "Declare requires_key honestly; a keyless provider must not ask for secrets.read.",
            "Bind the relay to 127.0.0.1 only, with a random port and a per-process token.",
            "Fail closed: a relay that is down is an error, not a silent fallback to another provider.",
            "Do not retain prompts or completions beyond the call.",
            "Scope network.http to the upstream host and no wider.",
        ),
        "build_order": (
            "Start with the provider descriptor; prove it loads without a relay.",
            "Add the relay only for the wire-shape gaps the descriptor cannot fill.",
            "Implement models, status and refresh against a fixture.",
            "Add the panel and commands; show key_present, never the key.",
            "Add the skill and provider context.",
            "Test a missing key, a down upstream and an in-flight refresh.",
        ),
        "gates": (
            "The key never appears in output, logs, events or an error.",
            "The relay binds only to loopback.",
            "A keyless provider declares no secrets.read.",
            "A down relay produces an actionable error.",
        ),
        "open_questions": (
            "Does the upstream require a key, and who supplies it?",
            "Which wire shape differs from the host's provider contract?",
            "Where may prompts and completions be retained?",
        ),
    },
    "system": {
        "title": "Desktop and device control",
        "summary": (
            "Reads the screen or drives the pointer and keyboard. Critical risk: "
            "explicit confirmation before any input, bounded coordinates and no "
            "typing of secrets."
        ),
        "signals": (
            "screen", "screenshot", "mouse", "keyboard", "click", "desktop",
            "computer use", "automation", "window", "accessibility", "clipboard",
            "pointer", "type",
        ),
        "runtime": "process",
        "runtime_reason": (
            "Screen capture and input injection need native calls and OS "
            "permissions. A declarative runtime cannot do either."
        ),
        "capabilities": (
            "computer.use", "process.execute", "workspace.write",
            "agent.tools.register", "ui.commands", "ui.panels",
            "agent.skills.provide", "agent.context.provide",
        ),
        "reasons": {
            "computer.use": "reads the screen and drives the pointer and keyboard",
            "process.execute": "runs the process runtime and its native calls",
            "workspace.write": "saves screenshots the reader asks for",
            "agent.tools.register": "exposes screen_size, screenshot, click and type_text",
            "ui.commands": "adds /screen and /click",
            "ui.panels": "adds the control panel",
            "agent.skills.provide": "ships the safe-control workflow",
            "agent.context.provide": "adds the platform and permission facts",
        },
        "grant_scopes": {
            "process.execute": ("program:python3",),
            "workspace.write": ("path:<absolute screenshot directory>",),
        },
        "contributions": (
            {"kind": "command", "id": "capture-screen",
             "purpose": "Capture the screen after confirming the target window."},
            {"kind": "command", "id": "click-point",
             "purpose": "Click one confirmed coordinate."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Confirm before input; never type a secret."},
            {"kind": "context", "id": "desktop",
             "purpose": "Platform, permissions and the safe-control policy."},
        ),
        "skill": {
            "id": "safe-control",
            "purpose": "Look, confirm, act once, verify; never act blind.",
        },
        "panel": {"id": "overview", "purpose": "Permission state, last screenshot and last input."},
        "tools": (
            {
                "id": "screen_size",
                "description": (
                    "Return the logical and pixel size of the main display. Read-only "
                    "and safe to call before any capture."
                ),
                "args": (),
                "returns": "{width, height, scale, displays}",
                "capabilities": ("computer.use",),
                "runs": "a native display query",
            },
            {
                "id": "screenshot",
                "description": (
                    "Capture the screen or one window to a new file. It reports the "
                    "path and size and never uploads the image."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute output path for the PNG.", "scope": "path"},
                    {"name": "window", "type": "string", "required": False,
                     "description": "Window title or id; defaults to the main display."},
                ),
                "returns": "{path, width, height, bytes}",
                "capabilities": ("computer.use", "workspace.write"),
                "runs": "a native screen capture",
            },
            {
                "id": "click",
                "description": (
                    "Click one screen coordinate. It requires confirm=true and "
                    "refuses coordinates outside the display."
                ),
                "args": (
                    {"name": "x", "type": "integer", "required": True,
                     "description": "Horizontal coordinate.", "minimum": 0},
                    {"name": "y", "type": "integer", "required": True,
                     "description": "Vertical coordinate.", "minimum": 0},
                    {"name": "confirm", "type": "boolean", "required": True,
                     "description": "Must be true; the reader confirmed the target."},
                ),
                "returns": "{clicked, x, y, at}",
                "capabilities": ("computer.use",),
                "runs": "a native pointer click",
            },
            {
                "id": "type_text",
                "description": (
                    "Type text into the focused control. It refuses when the text "
                    "looks like a credential and requires confirm=true."
                ),
                "args": (
                    {"name": "text", "type": "string", "required": True,
                     "description": "Text to type; never a password or token."},
                    {"name": "confirm", "type": "boolean", "required": True,
                     "description": "Must be true; the reader confirmed the target."},
                ),
                "returns": "{typed_chars, redacted, at}",
                "capabilities": ("computer.use",),
                "runs": "native text input",
            },
        ),
        "guardrails": (
            "Ask before the first click or keystroke, and show the target first.",
            "Never type a password, token, seed phrase or private key.",
            "Refuse coordinates outside the display and windows that are not frontmost.",
            "Capture only what the reader asked for; screenshots can contain private data.",
            "Stop on user input; an automation loop must yield to a human.",
            "computer.use is an activation and audit gate, not an OS sandbox: review the package.",
        ),
        "build_order": (
            "Implement screen_size and check the permission prompt is explained.",
            "Add screenshot with a path and a size report.",
            "Add click with bounds and confirm checks.",
            "Add type_text with a credential-looking-string refusal.",
            "Add the command, panel, skill and desktop context.",
            "Test denial, a second display and an out-of-bounds coordinate.",
        ),
        "gates": (
            "Click and type refuse without confirm=true.",
            "An out-of-bounds coordinate is refused.",
            "A credential-looking string is refused before typing.",
            "A denied permission produces the OS-specific fix.",
        ),
        "open_questions": (
            "Which OS and which permissions are required?",
            "How does the reader confirm a destructive action?",
            "What data must never appear in a screenshot?",
        ),
    },
    "generic": {
        "title": "Uncatalogued domain",
        "summary": (
            "No profile matched the brief. Start from the smallest process "
            "package and answer the discovery questions before committing to a "
            "tool surface."
        ),
        "signals": (),
        "runtime": "process",
        "runtime_reason": (
            "An unknown domain usually needs code. Start with a process runtime "
            "and the smallest surface; move to declarative only if the work turns "
            "out to be pure text."
        ),
        "capabilities": (
            "process.execute", "workspace.read", "agent.tools.register",
            "ui.commands", "ui.panels", "agent.skills.provide",
            "agent.context.provide",
        ),
        "reasons": {
            "process.execute": "runs the package's own code",
            "workspace.read": "reads the paths its tools receive",
            "agent.tools.register": "exposes the first useful tool",
            "ui.commands": "adds a discovery command",
            "ui.panels": "adds a status panel",
            "agent.skills.provide": "ships the workflow once it is known",
            "agent.context.provide": "adds the facts the model needs",
        },
        "grant_scopes": {"process.execute": ("program:python3",)},
        "contributions": (
            {"kind": "command", "id": "start",
             "purpose": "Walk the reader through the discovery questions."},
            {"kind": "prompt", "id": "rules",
             "purpose": "Ask before inventing a tool or a capability."},
            {"kind": "context", "id": "workspace",
             "purpose": "What this package is for, once known."},
        ),
        "skill": {
            "id": "domain-discovery",
            "purpose": "Turn an unclear brief into a reviewed tool surface.",
        },
        "panel": {"id": "overview", "purpose": "Discovery state and open questions."},
        "tools": (
            {
                "id": "describe",
                "description": (
                    "Describe this package's identity, runtime and current "
                    "contributions so the reader can see what exists."
                ),
                "args": (),
                "returns": "{id, version, runtime, tools, commands, skills}",
                "capabilities": (),
                "runs": "a local metadata read",
            },
            {
                "id": "inspect",
                "description": (
                    "Summarise one file or directory: path, kind, size and a "
                    "bounded text preview. It is a discovery aid, not a search tool."
                ),
                "args": (
                    {"name": "path", "type": "string", "required": True,
                     "description": "Absolute path to inspect.", "scope": "path"},
                ),
                "returns": "{path, kind, bytes, preview, truncated}",
                "capabilities": ("workspace.read",),
                "runs": "a bounded local read",
            },
        ),
        "guardrails": (
            "Answer the open questions before adding a second tool.",
            "Ask for the smallest capability set that does the job.",
            "Keep the first version read-only.",
            "Name the failure mode for every tool: bad input, missing permission, timeout.",
            "Do not copy a profile's capabilities wholesale; justify each one.",
        ),
        "build_order": (
            "Answer the open questions and write them into docs/design.md.",
            "Pick one user action and one tool; implement only that.",
            "Add the command, prompt and context that frame the action.",
            "Validate, lint and smoke; then add the next action.",
            "Review the capability list against what the code actually calls.",
        ),
        "gates": (
            "Every tool has a named caller and a failure mode.",
            "Every capability is used by at least one code path.",
            "The package validates and lints with no errors.",
            "The first version is read-only.",
        ),
        "open_questions": (
            "Who is the reader, and what will they ask for first?",
            "Which systems does the extension read or write?",
            "What must it never do?",
            "Which runtime can actually do that work: declarative, process, MCP or a plugin?",
        ),
    },
}

PROFILE_ORDER = tuple(PROFILES)


def normalise(value: str) -> str:
    """Lowercase a domain spelling and fold separators to hyphens."""
    return re.sub(r"[\s/_]+", "-", str(value or "").strip().lower()).strip("-")


def catalog() -> "list[dict]":
    """The catalogue the reference and the commands show."""
    entries = []
    for key in PROFILE_ORDER:
        profile = PROFILES[key]
        entries.append({
            "domain": key,
            "title": profile["title"],
            "summary": profile["summary"],
            "runtime": profile["runtime"],
            "tools": [tool["id"] for tool in profile["tools"]],
            "capabilities": list(profile["capabilities"]),
        })
    return entries


def catalog_table() -> str:
    """The catalogue as a Markdown table."""
    lines = ["| Domain | Runtime | Tools | What it is for |", "|---|---|---|---|"]
    for key in PROFILE_ORDER:
        profile = PROFILES[key]
        tools = ", ".join("'%s'" % tool["id"] for tool in profile["tools"])
        lines.append(
            "| '%s' | %s | %s | %s |"
            % (key, profile["runtime"], tools, profile["summary"])
        )
    return "\n".join(lines)


_TOKEN = re.compile(r"[a-z0-9][a-z0-9+.#-]*")


def _score(profile: dict, text: str, tokens: set) -> int:
    score = 0
    seen = set()
    for signal in profile.get("signals", ()):
        signal = signal.lower()
        if signal in seen:
            continue
        seen.add(signal)
        if " " in signal or "-" in signal:
            if signal in text:
                score += 2
        elif signal in tokens:
            score += 1
    return score


def match(domain: str, brief: str = "") -> "tuple[str, str, int, list]":
    """Return (profile key, confidence, score, matched signals)."""
    raw = normalise(domain)
    text = ("%s %s" % (domain, brief)).lower()
    tokens = set(_TOKEN.findall(text))
    direct = ALIASES.get(raw)
    if direct is None and raw in PROFILES:
        direct = raw
    if direct is not None:
        signals = sorted({signal for signal in PROFILES[direct]["signals"]
                          if signal in text or signal in tokens})
        return direct, "high", 100, signals[:8]

    best = ("generic", "none", 0, [])
    for key in PROFILE_ORDER:
        profile = PROFILES[key]
        score = _score(profile, text, tokens)
        if score > best[2]:
            matched = [
                signal for signal in profile["signals"]
                if signal in text or signal in tokens
            ]
            best = (key, "", score, matched[:8])
    key, _, score, signals = best
    if key == "generic":
        return key, "none", 0, []
    if score >= 4:
        confidence = "high"
    elif score >= 2:
        confidence = "medium"
    else:
        confidence = "low"
    return key, confidence, score, signals


def profile_for(key: str) -> dict:
    """One profile by key, with the generic fallback."""
    return PROFILES.get(key) or PROFILES["generic"]


def profile_of_tool(profile: dict) -> dict:
    """Index a profile's tools by id."""
    return {tool["id"]: tool for tool in profile["tools"]}
