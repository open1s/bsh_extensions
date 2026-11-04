"""Opinionated review on top of validation.

Validation answers "will the host load this?". Lint answers "will a reader
trust, install and maintain it?". Every rule has a stable id so a finding can
be cited in a review, and a fix the caller can apply without reading this file.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import constants
from .util import read_json, read_text, rel
from .validate import Report, load_manifest, validate

# Files a package may ship outside the declared contributions.
ALLOWED_TOP_LEVEL = (
    "extension.toml",
    "package.sig",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    ".gitignore",
    ".gitattributes",
    "tests",
    "scripts",
    "schemas",
    "asset",
    "assets",
    "docs",
    "src",
    "devkit",
)

SECRET_PATTERNS = (
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "a GitHub personal access token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "an API key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key id"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "a Slack token"),
)

TEXT_SUFFIXES = (
    ".py", ".md", ".json", ".toml", ".txt", ".rs", ".js", ".ts", ".sh",
    ".yaml", ".yml", ".html", ".css",
)

# Which declared capability a contribution kind is normally paired with is a
# documentation fact only: registration is not authorization, so a package may
# contribute a surface without listing the low-risk capability that shapes it.
INFORMATIONAL_PAIRS = {
    "command": "ui.commands",
    "panel": "ui.panels",
    "prompt": "agent.prompts.provide",
    "context": "agent.context.provide",
    "skill": "agent.skills.provide",
    "workflow": "agent.workflows.provide",
    "theme": "ui.theme",
    "model-provider": "agent.models.provide",
    "agent-provider": "agent.agents.provide",
    "event.subscribe": "events.subscribe",
    "event.publish": "events.publish",
    "hook": "hooks.observe",
}

CRITICAL_CAPABILITIES = ("process.execute", "network.http", "secrets.read", "computer.use")


def lint(root: Path) -> dict:
    """Run validation, then the review rules, and return one finding list."""
    base = validate(root)
    findings = list(base["findings"])
    manifest = _manifest(root)
    if manifest is None:
        return _result(base, findings)
    declared = {(entry["kind"], entry["id"]) for entry in base["declared"]}
    capabilities = base.get("capabilities") or []
    runtime = base.get("runtime")

    _documentation(root, manifest, findings)
    _contributions(root, manifest, base, findings)
    _panels(root, declared, findings)
    _tools(root, declared, findings)
    _secrets(root, findings)
    _build_output(root, findings)
    _orphans(root, manifest, declared, findings)
    _market(root, base, findings)
    _capability_notes(capabilities, declared, findings)

    if runtime == "process":
        _process_checks(root, manifest, capabilities, findings)
    return _result(base, findings)


def _manifest(root: Path):
    report = Report(root)
    return load_manifest(root, report)


def _result(base, findings):
    errors = [finding for finding in findings if finding["severity"] == "error"]
    warnings = [finding for finding in findings if finding["severity"] == "warning"]
    notes = [finding for finding in findings if finding["severity"] == "note"]
    return {
        "path": base["path"],
        "ok": not errors,
        "id": base.get("id"),
        "version": base.get("version"),
        "runtime": base.get("runtime"),
        "contributions": base.get("contributions", {}),
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "notes": len(notes),
        },
        "findings": findings,
    }


def _add(findings, severity, rule, message, path=None, fix=None):
    finding = {"severity": severity, "rule": rule, "message": message}
    if path is not None:
        finding["path"] = str(path)
    if fix is not None:
        finding["fix"] = fix
    findings.append(finding)


def _documentation(root, manifest, findings):
    identity = manifest.get("extension", {})
    if not (root / "README.md").is_file():
        _add(findings, "warning", "EXT001",
             "README.md is missing; a package nobody can read is a package nobody installs",
             "README.md", "document the runtime, the contributions and the grants it needs")
    if identity.get("license") and not (root / "LICENSE").is_file():
        _add(findings, "warning", "EXT002",
             "the manifest declares a license but the package ships no LICENSE file",
             "LICENSE", "add the licence text the manifest names")
    if not (root / "CHANGELOG.md").is_file():
        _add(findings, "note", "EXT003",
             "CHANGELOG.md is missing; the bump tool appends to it",
             "CHANGELOG.md")
    if not identity.get("repository") and not identity.get("homepage"):
        _add(findings, "note", "EXT004",
             "neither repository nor homepage is declared",
             "extension.toml", "add repository so a reader can review the source")
    description = identity.get("description") or ""
    if len(description) > 512:
        _add(findings, "note", "EXT005",
             "extension.description is %d characters; a paragraph is enough" % len(description),
             "extension.toml")
    readme = root / "README.md"
    if readme.is_file():
        text = read_text(readme, 1 * 1024 * 1024)
        for capability in CRITICAL_CAPABILITIES:
            if capability in text:
                break
        else:
            declared = manifest.get("capabilities", {}).get("required", [])
            critical = [
                name for name in declared
                if constants.CAPABILITY_RISK.get(name) in ("high", "critical")
            ]
            if critical:
                _add(
                    findings, "warning", "EXT006",
                    "the package requires %s but the README never explains why"
                    % ", ".join(critical),
                    "README.md",
                    "add a Security section: what the capability enables and what it cannot do",
                )


def _contributions(root, manifest, base, findings):
    counts = base.get("contributions", {})
    if not counts.get("command"):
        _add(findings, "note", "EXT041",
             "no command is contributed; commands are how a reader discovers the package",
             constants.MANIFEST_FILE)
    if not counts.get("tool"):
        _add(findings, "warning", "EXT042",
             "no tool is contributed; the agent has no way to use the package",
             constants.MANIFEST_FILE)
    if not counts.get("prompt") and not counts.get("context"):
        _add(findings, "note", "EXT043",
             "no prompt or context is contributed; the model will not know when to use it",
             constants.MANIFEST_FILE)
    if not counts.get("skill"):
        _add(findings, "note", "EXT044",
             "no skill is contributed; a SKILL.md tells the agent the workflow",
             constants.MANIFEST_FILE)
    resources = manifest.get("resources", {})
    if not resources:
        _add(findings, "note", "EXT045",
             "no [resources] ceilings are declared; the host defaults apply",
             constants.MANIFEST_FILE)
    output = resources.get("max_output_bytes")
    if isinstance(output, int) and output < 4096:
        _add(findings, "warning", "EXT046",
             "resources.max_output_bytes is %d bytes, too small for useful tool output" % output,
             constants.MANIFEST_FILE)


def _panels(root, declared, findings):
    for kind, contribution_id in sorted(declared):
        if kind != "panel":
            continue
        relative = _contribution_path_kind(kind, contribution_id)
        path = root / relative
        if not path.is_file():
            continue
        try:
            document = read_json(path)
        except Exception:
            continue
        view = document.get("view") or {}
        actions = _count_actions(view.get("root") if isinstance(view, dict) else None)
        if actions == 0:
            _add(findings, "note", "EXT050",
                 "%s has no actionable node; a panel that never dispatches is a static card"
                 % relative, relative, "add a button or input with an action")


def _count_actions(node):
    if not isinstance(node, dict):
        return 0
    count = 1 if isinstance(node.get("action"), str) else 0
    for child in node.get("children", []) or []:
        count += _count_actions(child)
    for tab in node.get("tabs", []) or []:
        if isinstance(tab, dict):
            count += _count_actions(tab.get("content"))
    return count


def _contribution_path_kind(kind, contribution_id):
    template = constants.CONTRIBUTION_KINDS[kind]["file"]
    return template.format(id=contribution_id) if template else None


def _tools(root, declared, findings):
    for kind, contribution_id in sorted(declared):
        if kind != "tool":
            continue
        relative = _contribution_path_kind(kind, contribution_id)
        path = root / relative
        if not path.is_file():
            continue
        try:
            file = read_json(path)
        except Exception:
            continue
        if not str(file.get("description") or "").strip():
            _add(findings, "warning", "EXT010",
                 "%s has no description; the model sees a generated placeholder" % relative,
                 relative, "describe what the tool does and when to call it")
        schema = file.get("input_schema")
        if not isinstance(schema, dict) or not schema.get("properties"):
            _add(findings, "note", "EXT011",
                 "%s has no typed input_schema; the model guesses the arguments" % relative,
                 relative, "declare type, properties and required")
        for capability in file.get("capabilities", []) or []:
            name = constants.CAPABILITY_ALIASES.get(capability, capability)
            if name not in constants.CAPABILITY_NAMES:
                continue
            if constants.CAPABILITY_RISK.get(name) in ("high", "critical"):
                _add(findings, "note", "EXT013",
                     "%s declares %s, which needs an explicit grant before the tool can run"
                     % (relative, name), relative)


def _capability_notes(capabilities, declared, findings):
    kinds = {kind for kind, _ in declared}
    for kind, capability in sorted(INFORMATIONAL_PAIRS.items()):
        if kind in kinds and capability not in capabilities:
            _add(findings, "note", "EXT020",
                 "the package contributes %s but does not list %s; registration is not "
                 "authorization, so this is a documentation gap rather than a failure"
                 % (kind, capability), constants.MANIFEST_FILE)


def _secrets(root, findings):
    for relative in _text_files(root):
        try:
            text = read_text(root / relative, 2 * 1024 * 1024)
        except Exception:
            continue
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                _add(findings, "warning", "EXT120",
                     "%s looks like it contains %s; never publish a credential in a package"
                     % (relative, label), relative,
                     "rotate the credential and load it from the vault instead")


def _build_output(root, findings):
    import os

    for current, directories, names in os.walk(root):
        for name in sorted(directories):
            if name in constants.BUILD_DIRECTORIES:
                findings.append({
                    "severity": "warning",
                    "rule": "EXT062",
                    "message": "%s is build output; it is hashed with the package and "
                               "would make the release hash depend on who ran the tests"
                               % rel(root, Path(current) / name),
                    "path": rel(root, Path(current) / name),
                    "fix": "delete it (and add it to .gitignore) before hashing or publishing",
                })
        for name in sorted(names):
            if name.endswith(".tar.gz"):
                findings.append({
                    "severity": "warning",
                    "rule": "EXT062",
                    "message": "%s looks like a built archive; it is hashed with the "
                               "package and would change on every release build"
                               % rel(root, Path(current) / name),
                    "path": rel(root, Path(current) / name),
                    "fix": "delete it (and add it to .gitignore) before hashing or publishing",
                })
        directories[:] = [name for name in directories
                          if name not in constants.IGNORED_DIRECTORIES]


def _text_files(root):
    import os

    for current, directories, names in os.walk(root):
        directories[:] = sorted(
            name for name in directories if name not in constants.IGNORED_DIRECTORIES
        )
        for name in sorted(names):
            if name.endswith(TEXT_SUFFIXES):
                yield rel(root, Path(current) / name)


def _orphans(root, manifest, declared, findings):
    import os

    patterns = {
        "tool": ("tools", ".json"),
        "command": ("commands", ".md"),
        "panel": ("panels", ".json"),
        "prompt": ("prompts", ".md"),
        "context": ("contexts", ".md"),
        "workflow": ("workflows", ".json"),
        "theme": ("themes", ".json"),
        "preset": ("presets", ".json"),
        "model-provider": ("providers/models", ".json"),
        "agent-provider": ("providers/agents", ".json"),
        "language": ("languages", ".json"),
        "integration": ("integrations", ".json"),
    }
    for kind, (directory, suffix) in patterns.items():
        base = root / directory
        if not base.is_dir():
            continue
        for name in sorted(os.listdir(base)):
            path = base / name
            if not path.is_file() or not name.endswith(suffix):
                continue
            contribution_id = name[: -len(suffix)]
            if (kind, contribution_id) not in declared:
                _add(findings, "warning", "EXT060",
                     "%s is not declared in extension.toml, so the host ignores it"
                     % rel(root, path), rel(root, path),
                     "declare it as a %s contribution, or delete the file" % kind)
    skills = root / "skills"
    if skills.is_dir():
        for name in sorted(os.listdir(skills)):
            path = skills / name
            if path.is_dir() and ("skill", name) not in declared:
                _add(findings, "warning", "EXT060",
                     "skills/%s is not declared in extension.toml, so the host ignores it"
                     % name, "skills/%s" % name)
    runtime_files = set()
    runtime = manifest.get("runtime") if isinstance(manifest, dict) else None
    if isinstance(runtime, dict):
        config = runtime.get("config")
        if isinstance(config, dict):
            entry = config.get("entry")
            if isinstance(entry, str) and entry not in constants.ALLOWLISTED_COMMANDS:
                runtime_files.add(entry)
            for argument in config.get("args") or []:
                if isinstance(argument, str) and (root / argument).is_file():
                    runtime_files.add(argument)
    contribution_directories = {
        constants.CONTRIBUTION_KINDS[kind]["file"].split("/")[0]
        for kind in constants.CONTRIBUTION_KINDS
        if constants.CONTRIBUTION_KINDS[kind]["file"]
    }
    for name in sorted(os.listdir(root)):
        if name.startswith(".") or name in constants.IGNORED_DIRECTORIES:
            continue
        if name in constants.BUILD_DIRECTORIES:
            continue
        if name in ALLOWED_TOP_LEVEL or name in runtime_files:
            continue
        if name in contribution_directories:
            continue
        _add(findings, "note", "EXT061",
             "%s sits at the package root and no contribution reads it" % name, name,
             "move it under tests/, scripts/ or docs/ so a reader knows it is not a surface")


def _market(root, base, findings):
    repo = root.parents[2] if len(root.parents) > 2 else root.parent
    index = repo / constants.MARKET_INDEX
    if not index.is_file():
        return
    try:
        document = read_json(index)
    except Exception:
        return
    entries = document.get("extensions") or []
    matching = [
        entry for entry in entries
        if entry.get("id") == base.get("id") and entry.get("version") == base.get("version")
    ]
    if not matching:
        _add(findings, "note", "EXT090",
             "this version is not in the market index at %s" % index, None,
             "run market with action=merge to add it before publishing")
        return
    path = root.relative_to(repo).as_posix()
    for entry in matching:
        if entry.get("path") != path:
            _add(findings, "warning", "EXT091",
                 "the market index points %s %s at %r, not %r"
                 % (base.get("id"), base.get("version"), entry.get("path"), path), None)


def _process_checks(root, manifest, capabilities, findings):
    config = manifest.get("runtime", {}).get("config", {})
    entry = config.get("entry")
    if entry and (root / entry).is_file():
        text = read_text(root / entry, 512 * 1024)
        if "initialize" not in text:
            _add(findings, "warning", "EXT070",
                 "%s never mentions the initialize handshake" % entry, entry,
                 "answer initialize with protocolVersion and the echoed token")
        if "token" not in text:
            _add(findings, "warning", "EXT071",
                 "%s does not echo the handshake token; the host will refuse the process"
                 % entry, entry)
    if "process.execute" not in capabilities:
        _add(findings, "error", "EXT072",
             "the process runtime needs the process.execute capability",
             constants.MANIFEST_FILE)
    if not (root / "tests").is_dir():
        _add(findings, "note", "EXT073",
             "a process package ships code; add a tests/ directory that calls the protocol",
             "tests")
