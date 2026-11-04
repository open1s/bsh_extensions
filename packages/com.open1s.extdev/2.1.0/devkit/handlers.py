"""The tool bodies, one function each.

Every tool returns plain JSON: the host serialises it into tool content, and
the same functions are importable from a test without a host. Failures raise
DevkitError with a sentence the reader can act on; the server turns that into a
JSON-RPC error, which the host shows as a tool error.
"""

from __future__ import annotations

import sys

from . import reference
from .design import design
from .lint import lint
from .market import market
from .release import bump, migrate, package
from .scaffold import scaffold
from .smoke import smoke
from .util import (
    fail,
    package_hash,
    read_bytes,
    resolve_root,
    walk_files,
)
from .validate import validate

DEFAULT_CONFIG = {
    "author": "BSH Extension Author",
    "license": "MIT",
    "default_runtime": "declarative",
    "market_path": "",
    "smoke_timeout_ms": 5000,
    "strict_lint": False,
    "default_domain": "",
}

TOOL_NAMES = (
    "scaffold",
    "validate",
    "lint",
    "check",
    "smoke",
    "explain",
    "hash",
    "market",
    "bump",
    "package",
    "migrate",
    "events",
    "design",
    "blueprint",
)


def merge_config(raw) -> dict:
    """Merge the host-supplied configuration over the defaults."""
    config = dict(DEFAULT_CONFIG)
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in config and value is not None:
                config[key] = value
    return config


def dispatch(name: str, arguments: dict, config: dict, state: dict):
    """Run one tool by its contribution id."""
    handlers = {
        "scaffold": tool_scaffold,
        "validate": tool_validate,
        "lint": tool_lint,
        "check": tool_check,
        "smoke": tool_smoke,
        "explain": tool_explain,
        "hash": tool_hash,
        "market": tool_market,
        "bump": tool_bump,
        "package": tool_package,
        "migrate": tool_migrate,
        "events": tool_events,
        "design": tool_design,
        "blueprint": tool_blueprint,
    }
    handler = handlers.get(name)
    if handler is None:
        fail("unknown tool %r; this extension offers %s"
             % (name, ", ".join(TOOL_NAMES)))
    return handler(arguments, config, state)


def tool_scaffold(arguments, config, state):
    """Create a validating package skeleton."""
    merged = dict(arguments)
    merged.setdefault("author", config.get("author"))
    merged.setdefault("license", config.get("license"))
    if not merged.get("runtime") and not merged.get("domain"):
        merged["runtime"] = config.get("default_runtime")
    return scaffold(merged)


def tool_validate(arguments, config, state):
    """Validate one package."""
    return validate(resolve_root(arguments.get("path")))


def tool_lint(arguments, config, state):
    """Validate and review one package."""
    report = lint(resolve_root(arguments.get("path")))
    if config.get("strict_lint"):
        for finding in report["findings"]:
            if finding["severity"] == "note":
                finding["severity"] = "warning"
        report["strict"] = True
    return report


def tool_check(arguments, config, state):
    """Validation, review, hash and (optionally) a smoke run in one report."""
    root = resolve_root(arguments.get("path"))
    report = lint(root)
    digest = package_hash(root)
    files = walk_files(root)
    total = sum((root / relative).stat().st_size for relative in files)
    result = {
        "path": str(root),
        "id": report.get("id"),
        "version": report.get("version"),
        "runtime": report.get("runtime"),
        "python": sys.version.split()[0],
        "hash": digest,
        "files": len(files),
        "bytes": total,
        "ok": report["ok"],
        "summary": report["summary"],
        "findings": report["findings"],
    }
    # Naming a tool asks for a smoke run of that tool, so it implies smoke.
    if arguments.get("smoke") or arguments.get("tool"):
        outcome = smoke(
            root,
            config,
            tool=arguments.get("tool"),
            arguments=arguments.get("arguments"),
        )
        result["smoke"] = outcome
        if not outcome.get("ok"):
            result["ok"] = False
    return result


def tool_smoke(arguments, config, state):
    """Run the declared tools against a local dry run."""
    return smoke(
        resolve_root(arguments.get("path")),
        config,
        tool=arguments.get("tool"),
        arguments=arguments.get("arguments"),
    )


def tool_explain(arguments, config, state):
    """Return the standard's reference for one topic."""
    return reference.explain(arguments.get("topic"))


def tool_hash(arguments, config, state):
    """Print the canonical package hash the market index carries."""
    root = resolve_root(arguments.get("path"))
    files = walk_files(root)
    return {
        "path": str(root),
        "hash": package_hash(root),
        "files": len(files),
        "bytes": sum(len(read_bytes(root / relative)) for relative in files),
    }


def tool_market(arguments, config, state):
    """Build, merge, verify or document a market index entry."""
    return market(arguments, config)


def tool_bump(arguments, config, state):
    """Raise the version and open a changelog entry."""
    return bump(arguments)


def tool_package(arguments, config, state):
    """Build a deterministic release archive."""
    return package(arguments)


def tool_migrate(arguments, config, state):
    """Rewrite a 1.x manifest as the 2.0 envelope."""
    return migrate(arguments)


def tool_design(arguments, config, state):
    """Turn a domain brief into a blueprint, optionally compared with a package."""
    merged = dict(arguments)
    if not merged.get("domain") and not merged.get("brief"):
        if config.get("default_domain"):
            merged["domain"] = config["default_domain"]
    return design(merged)


def tool_blueprint(arguments, config, state):
    """Design a package and write the blueprint to docs/design.md."""
    merged = dict(arguments)
    if not merged.get("path"):
        fail("path is required: the blueprint is written under <path>/docs/design.md")
    merged["write"] = True
    if not merged.get("domain") and not merged.get("brief"):
        if config.get("default_domain"):
            merged["domain"] = config["default_domain"]
    return design(merged)


def tool_events(arguments, config, state):
    """Report the host events this process has observed."""
    journal = state.get("events", [])
    limit = arguments.get("limit")
    if isinstance(limit, str) and limit.strip().isdigit():
        limit = int(limit)
    if not isinstance(limit, int) or limit <= 0:
        limit = 20
    topics = sorted({event.get("topic") or "" for event in journal if event.get("topic")})
    return {
        "count": len(journal),
        "topics": topics,
        "recent": journal[-limit:],
        "uptime_seconds": state.get("uptime")(),
    }
