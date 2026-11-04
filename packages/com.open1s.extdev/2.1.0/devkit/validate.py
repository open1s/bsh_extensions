"""Validate a BSH extension package against the 2.0 standard.

This is the offline mirror of what the host refuses: manifest 2.0 envelope,
identity grammar, semver ranges, runtime requirements, the capability
vocabulary, every contribution's declared file and that file's shape. The
result is one structured report the caller (and the model) can act on.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import constants
from .util import (
    check_contribution_id,
    check_extension_id,
    check_relative_path,
    check_requirement,
    check_version,
    DevkitError,
    fail,
    parse_frontmatter,
    read_text,
    rel,
)

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - the host ships 3.11+
    tomllib = None

SEVERITIES = ("error", "warning", "note")


class Report:
    """One validation pass: findings plus the facts other tools reuse."""

    def __init__(self, root: Path):
        self.root = root
        self.findings = []
        self.facts = {}

    def error(self, rule, message, path=None, fix=None):
        self._add("error", rule, message, path, fix)

    def warning(self, rule, message, path=None, fix=None):
        self._add("warning", rule, message, path, fix)

    def note(self, rule, message, path=None, fix=None):
        self._add("note", rule, message, path, fix)

    def _add(self, severity, rule, message, path, fix):
        finding = {"severity": severity, "rule": rule, "message": message}
        if path is not None:
            finding["path"] = str(path)
        if fix is not None:
            finding["fix"] = fix
        self.findings.append(finding)

    def errors(self):
        return [finding for finding in self.findings if finding["severity"] == "error"]

    def warnings(self):
        return [finding for finding in self.findings if finding["severity"] == "warning"]

    def ok(self):
        return not self.errors()


def load_manifest(root: Path, report: Report):
    """Read extension.toml and parse it, recording the failure if any."""
    path = root / constants.MANIFEST_FILE
    if not path.is_file():
        report.error(
            "manifest.missing",
            "every package must ship extension.toml at its root",
            constants.MANIFEST_FILE,
            "run scaffold to generate a complete package skeleton",
        )
        return None
    try:
        text = read_text(path, constants.MAX_MANIFEST_BYTES + 1)
    except DevkitError as error:
        report.error("manifest.unreadable", str(error), constants.MANIFEST_FILE)
        return None
    if len(text.encode("utf-8")) > constants.MAX_MANIFEST_BYTES:
        report.error(
            "manifest.too-large",
            "extension.toml is larger than %d bytes" % constants.MAX_MANIFEST_BYTES,
            constants.MANIFEST_FILE,
        )
        return None
    if tomllib is None:
        report.error(
            "manifest.tomllib",
            "parsing extension.toml needs Python 3.11+ (tomllib)",
            constants.MANIFEST_FILE,
        )
        return None
    try:
        data = tomllib.loads(text)
    except Exception as error:  # tomllib.TOMLDecodeError; keep the message
        report.error("manifest.toml", "extension.toml does not parse: %s" % error,
                     constants.MANIFEST_FILE)
        return None
    if not isinstance(data, dict):
        report.error("manifest.shape", "extension.toml must be a table",
                     constants.MANIFEST_FILE)
        return None
    return data


def _unknown_fields(table, allowed, where, report, path):
    for key in sorted(table):
        if key not in allowed:
            report.error(
                "manifest.unknown-field",
                "%s has unknown field %r; the host refuses unknown fields" % (where, key),
                path,
                "remove it or move it into the field the standard defines",
            )


def _string(table, key, where, report, path, required=True, allow_empty=False):
    if key not in table:
        if required:
            report.error("manifest.missing-field", "%s.%s is required" % (where, key), path)
        return None
    value = table[key]
    if not isinstance(value, str):
        report.error("manifest.type", "%s.%s must be a string" % (where, key), path)
        return None
    if not allow_empty and not value.strip():
        report.error("manifest.empty", "%s.%s must not be empty" % (where, key), path)
        return None
    return value


def _string_list(table, key, where, report, path, required=False, allowed=None):
    if key not in table:
        if required:
            report.error("manifest.missing-field", "%s.%s is required" % (where, key), path)
        return []
    value = table[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        report.error("manifest.type", "%s.%s must be a list of strings" % (where, key), path)
        return []
    problems = []
    seen = set()
    for item in value:
        if allowed is not None and item not in allowed:
            problems.append("%r is not in the host vocabulary" % item)
        if item in seen:
            problems.append("%r appears twice" % item)
        seen.add(item)
    for problem in problems:
        report.error("manifest.value", "%s.%s: %s" % (where, key, problem), path)
    return value


def validate_identity(report, manifest):
    path = constants.MANIFEST_FILE
    identity = manifest.get("extension")
    if not isinstance(identity, dict):
        report.error("manifest.missing-field", "the [extension] table is required", path)
        return
    _unknown_fields(identity, constants.IDENTITY_FIELDS, "[extension]", report, path)
    raw_id = _string(identity, "id", "extension", report, path)
    if raw_id is not None:
        reason = check_extension_id(raw_id)
        if reason:
            report.error("id.grammar", reason, path,
                         "use a reverse-domain id such as com.example.toolkit")
        else:
            report.facts["id"] = raw_id
            report.facts["namespace"] = raw_id.rsplit(".", 1)[-1]
    name = _string(identity, "name", "extension", report, path)
    if name is not None and len(name) > 128:
        report.error("extension.name", "extension.name must be at most 128 characters", path)
    version = _string(identity, "version", "extension", report, path)
    if version is not None:
        reason = check_version(version)
        if reason:
            report.error("version.semver", reason, path, "use MAJOR.MINOR.PATCH")
        else:
            report.facts["version"] = version
    description = _string(identity, "description", "extension", report, path)
    if description is not None:
        if len(description.encode("utf-8")) > 4096:
            report.error(
                "extension.description",
                "extension.description must be at most 4096 bytes",
                path,
            )
        elif len(description) > 1024:
            report.warning(
                "manifest.description-length",
                "extension.description is %d characters; keep it to a paragraph (<=1024)"
                % len(description),
                path,
            )
    if "authors" in identity:
        authors = _string_list(identity, "authors", "extension", report, path)
        if len(authors) > 32:
            report.error("extension.authors", "extension.authors allows at most 32 entries",
                         path)
    for key in ("license", "repository", "homepage"):
        if key in identity and not isinstance(identity[key], str):
            report.error("manifest.type", "extension.%s must be a string" % key, path)
    license_value = identity.get("license")
    if isinstance(license_value, str) and len(license_value.encode("utf-8")) > 2048:
        report.error("extension.license", "extension.license must be at most 2048 bytes",
                     path)


def validate_compatibility(report, manifest):
    path = constants.MANIFEST_FILE
    block = manifest.get("compatibility")
    if not isinstance(block, dict):
        report.error("manifest.missing-field", "the [compatibility] table is required", path)
        return
    _unknown_fields(block, constants.COMPATIBILITY_FIELDS, "[compatibility]", report, path)
    for key in ("host", "extension_api"):
        value = _string(block, key, "compatibility", report, path)
        if value is None:
            continue
        reason = check_requirement(value)
        if reason:
            report.error("compatibility.range", reason, path,
                         "a range looks like '>=3.0.0, <4.0.0' or '^1.0'")
        elif key == "extension_api" and value.strip() == "*":
            report.warning(
                "compatibility.loose",
                "compatibility.extension_api is '*' which claims every future API",
                path,
            )
    if "ui_api" in block:
        report.error(
            "compatibility.unknown-field",
            "compatibility.ui_api was removed from the 2.0 envelope",
            path,
            "the UI schema generation is declared by the panel document itself",
        )


def validate_runtime(report, manifest):
    path = constants.MANIFEST_FILE
    block = manifest.get("runtime")
    if not isinstance(block, dict):
        report.error("manifest.missing-field", "the [runtime] table is required", path)
        return
    _unknown_fields(block, constants.RUNTIME_FIELDS, "[runtime]", report, path)
    kind = _string(block, "kind", "runtime", report, path)
    if kind is None:
        return
    if kind not in constants.RUNTIME_KINDS:
        report.error(
            "runtime.kind",
            "runtime.kind %r is not one the host registers (%s)"
            % (kind, ", ".join(constants.RUNTIME_KINDS)),
            path,
        )
        return
    if kind == "builtin":
        report.error(
            "runtime.builtin",
            "the builtin runtime is linked into the host; a package may not claim it",
            path,
        )
        return
    report.facts["runtime"] = kind
    config = block.get("config", {})
    if not isinstance(config, dict):
        report.error("runtime.config", "runtime.config must be a table", path)
        return
    startup = config.get("startup", "on-demand")
    if startup not in constants.STARTUP_POLICIES:
        report.error(
            "runtime.startup",
            "runtime.config.startup must be one of %s" % ", ".join(constants.STARTUP_POLICIES),
            path,
        )
    entry = config.get("entry")
    if kind == "declarative":
        if entry is not None:
            report.error(
                "runtime.entry",
                "the declarative runtime forbids runtime.config.entry; it reads package files",
                path,
            )
        if config.get("args") or config.get("env") or config.get("protocol"):
            report.warning(
                "runtime.declarative-config",
                "args, env and protocol are ignored by the declarative runtime",
                path,
            )
        return
    if kind in constants.RUNTIME_ENTRY_REQUIRED:
        if not isinstance(entry, str) or not entry.strip():
            report.error(
                "runtime.entry",
                "the %s runtime requires runtime.config.entry" % kind,
                path,
            )
        elif kind in ("process", "mcp") and entry in constants.ALLOWLISTED_COMMANDS:
            report.facts["entry"] = entry
        else:
            reason = check_relative_path(entry)
            if reason:
                report.error("runtime.entry", reason, path)
            else:
                target = report.root / entry
                if not target.is_file():
                    report.error(
                        "runtime.entry-missing",
                        "runtime.config.entry %r does not exist in the package" % entry,
                        entry,
                        "ship the entry file or fix the path",
                    )
                report.facts["entry"] = entry
    args = config.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        report.error("runtime.args", "runtime.config.args must be a list of strings", path)
    elif len(args) > 64:
        report.error("runtime.args", "runtime.config.args allows at most 64 entries", path)
    else:
        for index, argument in enumerate(args):
            if len(argument.encode("utf-8")) > 4096 or "\0" in argument:
                report.error(
                    "runtime.args",
                    "runtime.config.args[%d] must be at most 4096 bytes and contain no NUL"
                    % index,
                    path,
                )
    env = config.get("env", {})
    if not isinstance(env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        report.error("runtime.env", "runtime.config.env must be a table of strings", path)
    else:
        if len(env) > 64:
            report.error("runtime.env", "runtime.config.env allows at most 64 variables", path)
        for key, value in env.items():
            if not key or key[0].isdigit() or not all(
                character.isascii() and (character.isalnum() or character == "_")
                for character in key
            ):
                report.error(
                    "runtime.env",
                    "runtime.config.env %r: names use ASCII letters, digits and '_' and "
                    "cannot start with a digit" % key,
                    path,
                )
            if _dangerous_env(key):
                report.error(
                    "runtime.env",
                    "runtime.config.env %r can change how the process loads code and is "
                    "not settable by a package" % key,
                    path,
                )
            if len(value.encode("utf-8")) > 4096 or "\0" in value:
                report.error(
                    "runtime.env",
                    "runtime.config.env %r must be at most 4096 bytes and contain no NUL" % key,
                    path,
                )
    protocol = config.get("protocol")
    if kind == "process":
        if protocol is None:
            report.warning(
                "runtime.protocol",
                "a process runtime should declare protocol = 'jsonrpc-2.0'",
                path,
            )
        elif protocol != "jsonrpc-2.0":
            report.error(
                "runtime.protocol",
                "runtime.config.protocol %r is not supported; the host speaks 'jsonrpc-2.0'"
                % protocol,
                path,
            )
    for key in ("entry", "protocol", "startup"):
        if key in config and not isinstance(config[key], str):
            report.error("runtime.type", "runtime.config.%s must be a string" % key, path)
    if kind == "extism" and isinstance(entry, str) and not entry.endswith(".wasm"):
        report.error("runtime.entry", "the Extism runtime needs a package-relative .wasm plugin",
                     path)
    if kind == "cordis" and isinstance(entry, str) and not entry.endswith(
        (".js", ".cjs", ".mjs")
    ):
        report.error("runtime.entry",
                     "the Cordis runtime needs a package-relative .js, .cjs or .mjs entry",
                     path)



def validate_capabilities(report, manifest):
    path = constants.MANIFEST_FILE
    block = manifest.get("capabilities", {})
    if not isinstance(block, dict):
        report.error("capabilities.shape", "capabilities must be a table", path)
        return
    _unknown_fields(block, ("required",), "[capabilities]", report, path)
    declared = _string_list(block, "required", "capabilities", report, path)
    normalized = []
    for capability in declared:
        name = constants.CAPABILITY_ALIASES.get(capability, capability)
        if name not in constants.CAPABILITY_NAMES:
            report.error(
                "capabilities.unknown",
                "capability %r is not in the host vocabulary (see capabilities tool)" % capability,
                path,
            )
            continue
        if capability in constants.CAPABILITY_ALIASES:
            report.note(
                "capabilities.alias",
                "%r is a historical alias; declare %r" % (capability, name),
                path,
            )
        normalized.append(name)
    report.facts["capabilities"] = normalized
    runtime = report.facts.get("runtime")
    if runtime in ("process", "cordis") and "process.execute" not in normalized:
        report.error(
            "capabilities.process",
            "the %s runtime starts a child process and must declare process.execute" % runtime,
            path,
            "add process.execute to capabilities.required",
        )
    if report.facts.get("hooks") and "hooks.observe" not in normalized:
        report.error(
            "capabilities.hooks",
            "observe hooks require the hooks.observe capability",
            path,
        )


def _dangerous_env(name: str) -> bool:
    upper = name.upper()
    return (
        upper in ("PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
                  "DYLD_LIBRARY_PATH", "PYTHONPATH", "NODE_OPTIONS")
        or upper.startswith("DYLD_")
    )


def _topic_problem(topic: str, allow_wildcard: bool) -> "str | None":
    if not topic or len(topic) > 128:
        return "a topic must be 1..=128 bytes"
    segments = topic.split(".")
    if all(segment == "*" for segment in segments):
        return "a topic needs at least one non-wildcard segment"
    for index, segment in enumerate(segments):
        if segment == "*":
            if not allow_wildcard or index != len(segments) - 1:
                return "'*' is only allowed as the final segment of a subscription topic"
            continue
        if not segment:
            return "topic segments must not be empty"
        if not all(
            character.isascii()
            and (character.islower() or character.isdigit() or character in "-_")
            for character in segment
        ):
            return ("topic segment %r may only contain lowercase letters, digits, "
                    "'-' and '_'" % segment)
    return None


def validate_contributions(report, manifest):
    path = constants.MANIFEST_FILE
    entries = manifest.get("contribution", [])
    if not isinstance(entries, list):
        report.error("contribution.shape", "[[contribution]] must be an array of tables", path)
        return
    seen = set()
    declared = {}
    for index, entry in enumerate(entries, start=1):
        where = "contribution[%d]" % index
        if not isinstance(entry, dict):
            report.error("contribution.shape", "%s must be a table" % where, path)
            continue
        _unknown_fields(entry, constants.CONTRIBUTION_FIELDS, where, report, path)
        kind = _string(entry, "kind", where, report, path)
        raw_id = _string(entry, "id", where, report, path)
        if kind is None or raw_id is None:
            continue
        if kind not in constants.CONTRIBUTION_KINDS:
            report.error(
                "contribution.kind",
                "%s: %r is not a contribution kind the host projects" % (where, kind),
                path,
            )
            continue
        reason = check_contribution_id(raw_id)
        if reason:
            report.error("contribution.id", "%s: %s" % (where, reason), path)
            continue
        if kind == "hook" and raw_id not in constants.HOOK_POINTS:
            report.error(
                "contribution.hook",
                "%s: hook %r is not a host hook point (%s)"
                % (where, raw_id, ", ".join(constants.HOOK_POINTS)),
                path,
            )
        key = (kind, raw_id)
        if key in seen:
            report.error(
                "contribution.duplicate",
                "%s: %s %r is declared twice" % (where, kind, raw_id),
                path,
            )
            continue
        seen.add(key)
        owners = report.facts.setdefault("owners", {})
        if raw_id in owners and owners[raw_id] != kind:
            report.error(
                "contribution.duplicate",
                "%s: contribution id %r is declared as both %s and %s; ids are unique "
                "across kinds" % (where, raw_id, owners[raw_id], kind),
                path,
            )
        else:
            owners[raw_id] = kind
        payload = entry.get("payload", {})
        if not isinstance(payload, dict):
            report.error("contribution.payload", "%s.payload must be a table" % where, path)
            payload = {}
        if kind in ("event.subscribe", "event.publish"):
            reason = _topic_problem(raw_id, allow_wildcard=kind == "event.subscribe")
            if reason:
                report.error("contribution.topic", "%s: %s" % (where, reason), path)
        declared.setdefault(kind, []).append(raw_id)
        report.facts.setdefault("contributions", []).append(
            {"kind": kind, "id": raw_id, "payload": payload}
        )
    limits = {"skill": 256, "workflow": 256, "theme": 256, "preset": 256,
              "language": 256, "integration": 256, "tool": 256, "command": 256,
              "panel": 256, "prompt": 256, "context": 256}
    for kind, limit in limits.items():
        if len(declared.get(kind, [])) > limit:
            report.error(
                "contribution.count",
                "%d %s contributions is above the host ceiling of %d"
                % (len(declared[kind]), kind, limit),
                path,
            )
    for kind, limit in (("event.subscribe", 256), ("event.publish", 256), ("hook", 32)):
        if len(declared.get(kind, [])) > limit:
            report.error(
                "contribution.count",
                "%d %s declarations is above the host ceiling of %d"
                % (len(declared[kind]), kind, limit),
                path,
            )
    if declared.get("hook"):
        report.facts["hooks"] = True
        if "hooks.observe" not in report.facts.get("capabilities", []):
            report.error(
                "capabilities.hooks",
                "observe hooks require the hooks.observe capability",
                path,
            )
        if report.facts.get("runtime") != "extism":
            report.error(
                "contribution.hook",
                "observe hooks are delivered by the extism runtime in this build",
                path,
            )
    report.facts["declared"] = declared


def validate_configuration(report, manifest):
    path = constants.MANIFEST_FILE
    block = manifest.get("configuration")
    if block is None:
        return
    if not isinstance(block, dict):
        report.error("configuration.shape", "[configuration] must be a table", path)
        return
    _unknown_fields(block, ("schema", "defaults"), "[configuration]", report, path)
    schema = block.get("schema")
    if schema is not None:
        if not isinstance(schema, str):
            report.error("configuration.schema", "configuration.schema must be a string", path)
        else:
            reason = check_relative_path(schema)
            if reason:
                report.error("configuration.schema", reason, path)
            elif not schema.endswith(".json"):
                report.error("configuration.schema",
                             "configuration.schema must name a .json schema", path)
            elif not (report.root / schema).is_file():
                report.error(
                    "configuration.schema-missing",
                    "configuration.schema %r does not exist in the package" % schema,
                    schema,
                )
    defaults = block.get("defaults")
    if defaults is not None:
        if not isinstance(defaults, dict):
            report.error("configuration.defaults",
                         "configuration.defaults must be a table", path)
        elif len(json.dumps(defaults).encode("utf-8")) > 64 * 1024:
            report.error("configuration.defaults",
                         "configuration.defaults must be at most 64 KiB", path)


def validate_resources(report, manifest):
    path = constants.MANIFEST_FILE
    block = manifest.get("resources", {})
    if not isinstance(block, dict):
        report.error("resources.shape", "[resources] must be a table", path)
        return
    _unknown_fields(block, constants.RESOURCE_FIELDS, "[resources]", report, path)
    ceilings = {
        "max_memory_mb": constants.HARD_MAX_MEMORY_MB,
        "max_execution_ms": constants.HARD_MAX_EXECUTION_MS,
        "max_concurrent_calls": constants.HARD_MAX_CONCURRENT_CALLS,
        "max_output_bytes": constants.HARD_MAX_OUTPUT_BYTES,
    }
    defaults = {
        "max_memory_mb": constants.DEFAULT_MEMORY_MB,
        "max_execution_ms": constants.DEFAULT_EXECUTION_MS,
        "max_concurrent_calls": constants.DEFAULT_CONCURRENT_CALLS,
        "max_output_bytes": constants.DEFAULT_OUTPUT_BYTES,
    }
    for key, ceiling in ceilings.items():
        if key not in block:
            continue
        value = block[key]
        if isinstance(value, bool) or not isinstance(value, int):
            report.error("resources.type", "resources.%s must be an integer" % key, path)
            continue
        if value <= 0:
            report.error("resources.value", "resources.%s must be positive" % key, path)
        elif value > ceiling:
            report.error(
                "resources.ceiling",
                "resources.%s %d exceeds the host ceiling of %d" % (key, value, ceiling),
                path,
            )
        elif value > defaults[key]:
            report.note(
                "resources.raised",
                "resources.%s is above the default %d" % (key, defaults[key]),
                path,
            )


def validate_dependencies(report, manifest):
    path = constants.MANIFEST_FILE
    block = manifest.get("dependencies", {})
    if not isinstance(block, dict):
        report.error("dependencies.shape", "[dependencies] must be a table", path)
        return
    own = report.facts.get("id")
    for raw_id, requirement in block.items():
        reason = check_extension_id(raw_id)
        if reason:
            report.error("dependencies.id", reason, path)
        elif raw_id == own:
            report.error("dependencies.self", "a package cannot depend on itself", path)
        if not isinstance(requirement, str):
            report.error("dependencies.range", "%r must map to a version requirement" % raw_id,
                         path)
            continue
        reason = check_requirement(requirement)
        if reason:
            report.error("dependencies.range", "%s: %s" % (raw_id, reason), path)


def validate_services(report, manifest):
    path = constants.MANIFEST_FILE
    block = manifest.get("services")
    if block is None:
        return
    if not isinstance(block, dict):
        report.error("services.shape", "[services] must be a table", path)
        return
    _unknown_fields(block, ("provides", "requires"), "[services]", report, path)
    for section, fields, versioned in (
        ("provides", constants.SERVICE_PROVIDE_FIELDS, True),
        ("requires", constants.SERVICE_REQUIRE_FIELDS, False),
    ):
        entries = block.get(section, [])
        if not isinstance(entries, list):
            report.error("services.shape", "services.%s must be an array of tables" % section,
                         path)
            continue
        for index, entry in enumerate(entries, start=1):
            where = "services.%s[%d]" % (section, index)
            if not isinstance(entry, dict):
                report.error("services.shape", "%s must be a table" % where, path)
                continue
            _unknown_fields(entry, fields, where, report, path)
            for key in ("name", "contract"):
                _string(entry, key, where, report, path)
            version = _string(entry, "version", where, report, path)
            if version is not None:
                check = check_version(version) if versioned else check_requirement(version)
                if check:
                    report.error("services.version", "%s: %s" % (where, check), path)
            scope = _string(entry, "scope", where, report, path)
            if scope is not None and scope not in constants.SERVICE_SCOPES:
                report.error(
                    "services.scope",
                    "%s.scope %r must be one of %s"
                    % (where, scope, ", ".join(constants.SERVICE_SCOPES)),
                    path,
                )
            if section == "provides":
                _string_list(entry, "capabilities", where, report, path,
                             allowed=constants.CAPABILITY_NAMES)
            elif "optional" in entry and not isinstance(entry["optional"], bool):
                report.error("services.optional", "%s.optional must be a boolean" % where, path)


# --- contribution files ----------------------------------------------------


def _contribution_path(report, kind, contribution_id):
    template = constants.CONTRIBUTION_KINDS[kind]["file"]
    if template is None:
        return None
    relative = template.format(id=contribution_id)
    reason = check_relative_path(relative)
    if reason:
        report.error("contribution.path", reason, constants.MANIFEST_FILE)
        return None
    return relative


def _read_contribution(report, kind, contribution_id, relative):
    path = report.root / relative
    if not path.is_file():
        report.error(
            "contribution.file-missing",
            "%s %r declares %r, which is missing" % (kind, contribution_id, relative),
            relative,
            "create the file, or remove the declaration from extension.toml",
        )
        return None
    try:
        size = path.stat().st_size
    except OSError as error:
        report.error("contribution.unreadable", str(error), relative)
        return None
    if size > constants.MAX_CONTRIBUTION_BYTES:
        report.error(
            "contribution.too-large",
            "%s is %d bytes; the host reads at most %d"
            % (relative, size, constants.MAX_CONTRIBUTION_BYTES),
            relative,
        )
        return None
    return path


def _read_json_contribution(report, kind, contribution_id, relative):
    path = _read_contribution(report, kind, contribution_id, relative)
    if path is None:
        return None
    try:
        value = json.loads(read_text(path))
    except ValueError as error:
        report.error("contribution.json", "%s is not valid JSON: %s" % (relative, error), relative)
        return None
    if not isinstance(value, dict):
        report.error("contribution.shape", "%s must hold a JSON object" % relative, relative)
        return None
    return value


def _read_text_contribution(report, kind, contribution_id, relative):
    path = _read_contribution(report, kind, contribution_id, relative)
    if path is None:
        return None
    try:
        text = read_text(path)
    except DevkitError as error:
        report.error("contribution.encoding", str(error), relative)
        return None
    if not text.strip():
        report.error("contribution.empty", "%s is empty" % relative, relative)
        return None
    return text


def _check_tool(report, contribution_id, relative, payload, runtime):
    file = _read_json_contribution(report, "tool", contribution_id, relative)
    if file is None:
        return
    if "description" in file:
        description = file["description"]
        if not isinstance(description, str):
            report.error("tool.description", "tools/%s.json: description must be a string"
                         % contribution_id, relative)
        elif len(description.encode("utf-8")) > constants.MAX_TOOL_DESCRIPTION_BYTES:
            report.error(
                "tool.description",
                "tools/%s.json: description exceeds %d bytes"
                % (contribution_id, constants.MAX_TOOL_DESCRIPTION_BYTES),
                relative,
            )
    else:
        report.note(
            "tool.description-missing",
            "tools/%s.json has no description; the model sees the extension name instead"
            % contribution_id,
            relative,
        )
    schema = file.get("input_schema")
    if schema is None:
        report.note(
            "tool.schema-missing",
            "tools/%s.json has no input_schema; the host advertises an empty object"
            % contribution_id,
            relative,
        )
    elif not isinstance(schema, dict):
        report.error("tool.schema", "tools/%s.json: input_schema must be a JSON object"
                     % contribution_id, relative)
    elif schema.get("type") not in (None, "object"):
        report.error("tool.schema", "tools/%s.json: input_schema.type must be 'object'"
                     % contribution_id, relative)
    capabilities = file.get("capabilities", [])
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        report.error("tool.capabilities",
                     "tools/%s.json: capabilities must be a list of strings"
                     % contribution_id, relative)
    else:
        for capability in capabilities:
            name = constants.CAPABILITY_ALIASES.get(capability, capability)
            if name not in constants.CAPABILITY_NAMES:
                report.error(
                    "tool.capabilities",
                    "tools/%s.json: %r is not a capability" % (contribution_id, capability),
                    relative,
                )
    implementation = file.get("implementation")
    if runtime == "declarative":
        if not isinstance(implementation, dict):
            report.error(
                "tool.implementation",
                "tools/%s.json needs an implementation for a declarative package"
                % contribution_id,
                relative,
                "one of echo_arguments, constant or template",
            )
            return
        kind = implementation.get("kind")
        if kind not in constants.IMPLEMENTATIONS:
            report.error(
                "tool.implementation",
                "tools/%s.json: implementation.kind %r must be one of %s"
                % (contribution_id, kind, ", ".join(constants.IMPLEMENTATIONS)),
                relative,
            )
        elif kind == "constant" and "value" not in implementation:
            report.error(
                "tool.implementation",
                "tools/%s.json: a constant implementation needs a value" % contribution_id,
                relative,
            )
        elif kind == "template" and not isinstance(implementation.get("text"), str):
            report.error(
                "tool.implementation",
                "tools/%s.json: a template implementation needs text" % contribution_id,
                relative,
            )
    elif implementation is not None:
        report.warning(
            "tool.implementation-ignored",
            "tools/%s.json ships an implementation, which the %s runtime ignores"
            % (contribution_id, runtime),
            relative,
        )



def _check_markdown(report, kind, contribution_id, relative, require_body=True):
    text = _read_text_contribution(report, kind, contribution_id, relative)
    if text is None:
        return
    metadata, body = parse_frontmatter(text)
    if require_body and not body.strip():
        report.error("contribution.body", "%s has no body" % relative, relative)
    if "description" not in metadata and "name" not in metadata:
        report.note(
            "contribution.description",
            "%s has no frontmatter description; the first line is used" % relative,
            relative,
        )
    paths = metadata.get("paths")
    if paths is not None:
        for pattern in paths.split(","):
            if not pattern.strip():
                report.error("contribution.paths", "%s: frontmatter paths has an empty entry"
                             % relative, relative)


def _check_ui_node(report, node, relative, where, depth, counter):
    if not isinstance(node, dict):
        report.error("panel.node", "%s: %s must be a JSON object" % (relative, where), relative)
        return
    counter[0] += 1
    if counter[0] > constants.MAX_UI_NODES:
        report.error("panel.nodes", "%s has more than %d nodes"
                     % (relative, constants.MAX_UI_NODES), relative)
        return
    if depth > constants.MAX_UI_DEPTH:
        report.error("panel.depth", "%s nests deeper than %d levels"
                     % (relative, constants.MAX_UI_DEPTH), relative)
        return
    kind = node.get("type")
    if kind not in constants.UI_NODE_REQUIRED:
        report.error(
            "panel.node-type",
            "%s: %s has unknown node type %r" % (relative, where, kind),
            relative,
        )
        return
    for field in constants.UI_NODE_REQUIRED[kind]:
        if field not in node:
            report.error(
                "panel.node-field",
                "%s: %s (%s) needs %r" % (relative, where, kind, field),
                relative,
            )
    if kind in ("text", "markdown", "heading"):
        if not isinstance(node.get("text"), str):
            report.error("panel.node-field", "%s: %s.text must be a string" % (relative, where),
                         relative)
    if kind == "heading":
        level = node.get("level", 2)
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 6:
            report.error("panel.node-field", "%s: %s.level must be 1..6" % (relative, where),
                         relative)
    if kind in ("button", "input", "select", "checkbox"):
        action = node.get("action")
        if not isinstance(action, str) or not action.strip():
            report.error("panel.action", "%s: %s.action must be a non-empty string"
                         % (relative, where), relative)
    if kind == "button" and node.get("style", "secondary") not in constants.BUTTON_STYLES:
        report.error(
            "panel.button-style",
            "%s: %s.style must be one of %s"
            % (relative, where, ", ".join(constants.BUTTON_STYLES)),
            relative,
        )
    if kind == "notification" and node.get("level") not in constants.NOTIFICATION_LEVELS:
        report.error(
            "panel.notification",
            "%s: %s.level must be one of %s"
            % (relative, where, ", ".join(constants.NOTIFICATION_LEVELS)),
            relative,
        )
    if kind == "table":
        columns = node.get("columns")
        if not isinstance(columns, list) or not all(isinstance(item, str) for item in columns):
            report.error("panel.node-field", "%s: %s.columns must be a list of strings"
                         % (relative, where), relative)
        else:
            for row in node.get("rows", []):
                if not isinstance(row, list) or len(row) != len(columns):
                    report.error(
                        "panel.node-field",
                        "%s: %s has a row whose width does not match its columns"
                        % (relative, where),
                        relative,
                    )
                    break
    if kind == "select":
        options = node.get("options")
        if not isinstance(options, list) or not all(
            isinstance(item, dict) and isinstance(item.get("value"), str)
            for item in options
        ):
            report.error("panel.node-field", "%s: %s.options must be a list of {value,label}"
                         % (relative, where), relative)
    if kind == "list":
        items = node.get("items", [])
        if not isinstance(items, list) or not all(
            isinstance(item, dict) and isinstance(item.get("title"), str) for item in items
        ):
            report.error("panel.node-field", "%s: %s.items must be a list of {title}"
                         % (relative, where), relative)
    if kind == "code" and not isinstance(node.get("value"), str):
        report.error("panel.node-field", "%s: %s.value must be a string" % (relative, where),
                     relative)
    if kind == "image":
        src = node.get("src")
        reason = check_relative_path(src) if isinstance(src, str) else "must be a string"
        if reason:
            report.error("panel.image", "%s: %s.src %s" % (relative, where, reason), relative)
        elif not src.startswith("asset/"):
            report.error(
                "panel.image",
                "%s: %s.src must live under asset/; the host has no remote image loader"
                % (relative, where),
                relative,
            )
    if kind == "progress":
        value = node.get("value", 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            report.error("panel.node-field", "%s: %s.value must be 0.0..1.0" % (relative, where),
                         relative)
    if kind == "tabs":
        tabs = node.get("tabs", [])
        if not isinstance(tabs, list):
            report.error("panel.node-field", "%s: %s.tabs must be a list" % (relative, where),
                         relative)
        else:
            for index, tab in enumerate(tabs):
                if not isinstance(tab, dict) or "content" not in tab:
                    report.error("panel.node-field",
                                 "%s: %s.tabs[%d] needs content" % (relative, where, index),
                                 relative)
                    continue
                _check_ui_node(report, tab["content"], relative,
                               "%s.tabs[%d].content" % (where, index), depth + 1, counter)
    children = node.get("children", [])
    if children:
        if not isinstance(children, list):
            report.error("panel.node-field", "%s: %s.children must be a list" % (relative, where),
                         relative)
        else:
            for index, child in enumerate(children):
                _check_ui_node(report, child, relative, "%s.children[%d]" % (where, index),
                               depth + 1, counter)


def _check_panel(report, contribution_id, relative, payload):
    file = _read_json_contribution(report, "panel", contribution_id, relative)
    if file is None:
        return
    title = file.get("title")
    if not isinstance(title, str) or not title.strip():
        report.error("panel.title", "%s needs a title" % relative, relative)
    elif len(title) > constants.MAX_PANEL_TITLE_CHARS:
        report.error("panel.title", "%s: title exceeds %d characters"
                     % (relative, constants.MAX_PANEL_TITLE_CHARS), relative)
    if "icon" in file and file["icon"] is not None:
        reason = check_relative_path(file["icon"]) if isinstance(file["icon"], str) else \
            "must be a string"
        if reason:
            report.error("panel.icon", "%s: icon %s" % (relative, reason), relative)
    location = file.get("location", "right")
    if location not in constants.PANEL_LOCATIONS:
        report.error("panel.location", "%s: location %r must be one of %s"
                     % (relative, location, ", ".join(constants.PANEL_LOCATIONS)), relative)
    visibility = file.get("default_visibility", "visible")
    if visibility not in constants.PANEL_VISIBILITIES:
        report.error("panel.visibility", "%s: default_visibility %r must be one of %s"
                     % (relative, visibility, ", ".join(constants.PANEL_VISIBILITIES)),
                     relative)
    view = file.get("view")
    if not isinstance(view, dict):
        report.error("panel.view", "%s needs a view document" % relative, relative)
        return
    if view.get("schema_version") != constants.UI_SCHEMA_VERSION:
        report.error(
            "panel.schema-version",
            "%s: view.schema_version must be %r"
            % (relative, constants.UI_SCHEMA_VERSION),
            relative,
        )
    if "root" not in view:
        report.error("panel.view", "%s: view.root is required" % relative, relative)
        return
    _check_ui_node(report, view["root"], relative, "view.root", 1, [0])


def _check_skill(report, contribution_id, relative, payload):
    text = _read_text_contribution(report, "skill", contribution_id, relative)
    if text is None:
        return
    metadata, body = parse_frontmatter(text)
    if "name" not in metadata:
        report.error("skill.name", "%s needs frontmatter name:" % relative, relative)
    if "description" not in metadata:
        report.error("skill.description", "%s needs frontmatter description:" % relative,
                     relative)
    if not body.strip():
        report.error("skill.body", "%s has no body" % relative, relative)


def _check_workflow(report, contribution_id, relative, payload, declared_tools):
    file = _read_json_contribution(report, "workflow", contribution_id, relative)
    if file is None:
        return
    steps = file.get("steps")
    if not isinstance(steps, list) or not steps:
        report.error("workflow.steps", "%s needs a non-empty steps array" % relative, relative)
        return
    for index, step in enumerate(steps, start=1):
        where = "steps[%d]" % index
        if not isinstance(step, dict):
            report.error("workflow.steps", "%s: %s must be a table" % (relative, where), relative)
            continue
        extra = set(step) - {"name", "tool", "arguments"}
        if extra:
            report.error("workflow.steps", "%s: %s has unknown keys %s"
                         % (relative, where, ", ".join(sorted(extra))), relative)
        name = step.get("name")
        tool = step.get("tool")
        if not isinstance(name, str) or not name.strip():
            report.error("workflow.steps", "%s: %s.name must be a string" % (relative, where),
                         relative)
        if not isinstance(tool, str) or not tool.strip():
            report.error("workflow.steps", "%s: %s.tool must be a string" % (relative, where),
                         relative)
        elif tool not in declared_tools:
            report.error(
                "workflow.tool",
                "%s: %s calls %r, which this package does not declare as a tool"
                % (relative, where, tool),
                relative,
                "a workflow may only call its own package's tools",
            )
        if "arguments" in step and not isinstance(step["arguments"], dict):
            report.error("workflow.steps", "%s: %s.arguments must be a table" % (relative, where),
                         relative)


def _check_language(report, contribution_id, relative, payload, declared_tools):
    file = _read_json_contribution(report, "language", contribution_id, relative)
    if file is None:
        return
    name = file.get("name")
    if not isinstance(name, str) or not name.strip():
        report.error("language.name", "%s needs a name" % relative, relative)
    extensions = file.get("extensions")
    if not isinstance(extensions, list) or not 1 <= len(extensions) <= 64:
        report.error("language.extensions", "%s needs 1..64 file extensions" % relative,
                     relative)
    elif not all(isinstance(item, str) for item in extensions):
        report.error("language.extensions", "%s: extensions must be strings" % relative,
                     relative)
    else:
        for item in extensions:
            if not item or item.startswith(".") or not all(
                character.isascii()
                and (character.isalnum() or character in "_-+.")
                for character in item
            ):
                report.error(
                    "language.extensions",
                    "%s: extension %r must be bare and alphanumeric" % (relative, item),
                    relative,
                )
    tool = file.get("tool")
    if not isinstance(tool, str):
        report.error("language.tool", "%s needs a tool id" % relative, relative)
    elif tool not in declared_tools:
        report.error(
            "language.tool",
            "%s: tool %r is not a declared tool" % (relative, tool),
            relative,
        )
    syntax = file.get("syntax")
    if syntax is not None:
        if not isinstance(syntax, str):
            report.error("language.syntax", "%s: syntax must be a string" % relative, relative)
        elif syntax not in constants.LANGUAGE_SYNTAXES:
            report.warning("language.syntax", "%s: syntax %r is not a known grammar"
                           % (relative, syntax), relative)


def _check_integration(report, contribution_id, relative, payload,
                       declared_tools, declared_commands):
    file = _read_json_contribution(report, "integration", contribution_id, relative)
    if file is None:
        return
    name = file.get("name")
    if not isinstance(name, str) or not name.strip():
        report.error("integration.name", "%s needs a name" % relative, relative)
    kind = file.get("kind")
    if kind not in constants.INTEGRATION_KINDS:
        report.error("integration.kind", "%s: kind %r must be one of %s"
                     % (relative, kind, ", ".join(constants.INTEGRATION_KINDS)), relative)
    action = file.get("action")
    if not isinstance(action, str):
        report.error("integration.action", "%s needs an action" % relative, relative)
    elif action not in declared_tools and action not in declared_commands:
        report.error(
            "integration.action",
            "%s: action %r is not a declared tool or command" % (relative, action),
            relative,
        )


def _check_named_json(report, kind, contribution_id, relative, payload):
    file = _read_json_contribution(report, kind, contribution_id, relative)
    if file is None:
        return
    name = file.get("name")
    if not isinstance(name, str) or not name.strip():
        report.error("%s.name" % kind, "%s needs a name" % relative, relative)


def validate_contribution_files(report, manifest):
    declared = report.facts.get("declared", {})
    runtime = report.facts.get("runtime", "declarative")
    declared_tools = declared.get("tool", [])
    declared_commands = declared.get("command", [])
    for entry in report.facts.get("contributions", []):
        kind = entry["kind"]
        contribution_id = entry["id"]
        relative = _contribution_path(report, kind, contribution_id)
        if relative is None:
            continue
        entry["file"] = relative
        if kind == "tool":
            _check_tool(report, contribution_id, relative, entry["payload"], runtime)
        elif kind in ("command", "prompt", "context"):
            _check_markdown(report, kind, contribution_id, relative)
        elif kind == "panel":
            _check_panel(report, contribution_id, relative, entry["payload"])
        elif kind == "skill":
            _check_skill(report, contribution_id, relative, entry["payload"])
        elif kind == "workflow":
            _check_workflow(report, contribution_id, relative, entry["payload"],
                            declared_tools)
        elif kind == "language":
            _check_language(report, contribution_id, relative, entry["payload"],
                            declared_tools)
        elif kind == "integration":
            _check_integration(report, contribution_id, relative, entry["payload"],
                               declared_tools, declared_commands)
        elif kind in ("theme", "preset", "model-provider", "agent-provider"):
            _check_named_json(report, kind, contribution_id, relative, entry["payload"])
    # A package must be self-contained: the host refuses symbolic links.
    for relative in _walk(report.root):
        if (report.root / relative).is_symlink():
            report.error(
                "package.symlink",
                "%s is a symbolic link; packages must be self-contained" % relative,
                relative,
            )


def _walk(root: Path):
    import os

    for current, directories, names in os.walk(root):
        directories[:] = sorted(
            name for name in directories if name not in constants.IGNORED_DIRECTORIES
        )
        for name in sorted(names):
            yield rel(root, Path(current) / name)


def validate(root: Path) -> dict:
    """Validate one package directory and return the structured report."""
    if not root.is_dir():
        fail("%s is not a directory" % root)
    report = Report(root)
    manifest = load_manifest(root, report)
    if manifest is not None:
        for key in sorted(manifest):
            if key not in constants.MANIFEST_FIELDS:
                report.error(
                    "manifest.unknown-field",
                    "extension.toml has unknown top-level field %r" % key,
                    constants.MANIFEST_FILE,
                )
        schema = manifest.get("schema_version")
        if not isinstance(schema, str):
            report.error("manifest.schema-version", "schema_version is required",
                         constants.MANIFEST_FILE)
        elif schema != constants.SCHEMA_VERSION:
            hint = ""
            if schema.startswith("1."):
                hint = "this is a 1.x manifest; run the migrate tool to rewrite it as 2.0"
            report.error(
                "manifest.schema-version",
                "schema_version must be %r, found %r" % (constants.SCHEMA_VERSION, schema),
                constants.MANIFEST_FILE,
                hint or None,
            )
        validate_identity(report, manifest)
        validate_compatibility(report, manifest)
        validate_runtime(report, manifest)
        validate_capabilities(report, manifest)
        validate_contributions(report, manifest)
        validate_configuration(report, manifest)
        validate_resources(report, manifest)
        validate_dependencies(report, manifest)
        validate_services(report, manifest)
        validate_contribution_files(report, manifest)
    counts = {}
    for entry in report.facts.get("contributions", []):
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    return {
        "path": str(root),
        "ok": report.ok(),
        "id": report.facts.get("id"),
        "version": report.facts.get("version"),
        "runtime": report.facts.get("runtime"),
        "capabilities": report.facts.get("capabilities", []),
        "contributions": counts,
        "declared": [
            {"kind": entry["kind"], "id": entry["id"], "file": entry.get("file")}
            for entry in report.facts.get("contributions", [])
        ],
        "summary": {
            "errors": len(report.errors()),
            "warnings": len(report.warnings()),
        },
        "findings": report.findings,
    }
