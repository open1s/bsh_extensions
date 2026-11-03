"""Turn a domain brief into a reviewable extension blueprint.

The design tool is the DevKit's first step, not a scaffold: it names the domain
profile, the runtime that domain actually needs, the contributions, the tools
with their scope arguments, the capabilities and grants, the safety rules, the
build order and the review questions. It can compare an existing package with
the blueprint and write the result to docs/design.md.

The blueprint is derived from the same profile tables the reference and the
scaffold read, so the guide, the generated package and the review cannot drift
apart.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import constants, domains
from .util import (
    check_contribution_id,
    check_extension_id,
    fail,
    package_hash,
    read_text,
    resolve_new_path,
    utc_stamp,
    write_text,
)

BT = chr(96)
FENCE = BT * 3

RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "with",
    "that", "this", "these", "those", "is", "are", "be", "want", "need",
    "make", "create", "build", "help", "helps", "extension", "plugin", "bsh",
    "tool", "tools", "app", "apps", "some", "any", "from", "into", "about",
    "using", "use", "uses", "let", "lets", "should", "would", "could", "can",
    "my", "our", "their", "its", "it", "we", "i", "you", "they",
    "read", "write", "query", "search", "fetch", "list", "get", "send",
    "scan", "convert", "extract", "probe", "run", "track", "manage",
    "monitor", "review", "analyze", "summarize", "sync", "pull", "push",
    "update", "delete", "edit", "draft", "notify", "publish",
}

# Capabilities a declarative runtime cannot exercise. A declarative package is
# text and pure transformations; asking for one of these would be a false
# claim, so the design drops them and says why.
DECLARATIVE_FORBIDDEN = (
    "process.execute", "network.http", "secrets.read", "computer.use",
    "workspace.read", "workspace.write", "hooks.observe", "agent.intercept",
)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        return ""
    if slug[0].isdigit():
        slug = "x-" + slug
    return slug[:40].strip("-")


def _title(slug: str) -> str:
    words = [word for word in slug.split("-") if word]
    return " ".join(word[:1].upper() + word[1:] for word in words) or "Extension"


def _brief_words(brief: str, domain: str) -> "list[str]":
    text = "%s %s" % (brief or "", domain or "")
    words = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", text):
        word = raw.lower()
        if word in STOPWORDS:
            continue
        if word in words:
            continue
        words.append(word)
    return words


def _identity(raw_id, domain: str, brief: str, profile_key: str):
    """Return (id, name, placeholder) after validating an explicit id."""
    if isinstance(raw_id, str) and raw_id.strip():
        raw_id = raw_id.strip()
        reason = check_extension_id(raw_id)
        if reason:
            fail("id %r is invalid: %s" % (raw_id, reason))
        namespace = raw_id.rsplit(".", 1)[-1]
        return raw_id, _title(namespace), raw_id.startswith("com.example.")
    words = _brief_words(brief, domain)
    slug = _slug(words[0]) if words else ""
    if not slug:
        slug = _slug(profile_key) or "extension"
    raw_id = "com.example." + slug
    return raw_id, _title(slug), True


def _schema(args) -> dict:
    properties = {}
    required = []
    for arg in args or ():
        schema = {"type": arg.get("type") or "string"}
        if arg.get("description"):
            schema["description"] = arg["description"]
        if arg.get("enum"):
            schema["enum"] = list(arg["enum"])
        if "minimum" in arg:
            schema["minimum"] = arg["minimum"]
        if "maximum" in arg:
            schema["maximum"] = arg["maximum"]
        if "default" in arg:
            schema["default"] = arg["default"]
        properties[arg["name"]] = schema
        if arg.get("required"):
            required.append(arg["name"])
    document = {"type": "object", "properties": properties}
    if required:
        document["required"] = required
    document["additionalProperties"] = False
    return document


def _contribution_file(kind: str, contribution_id: str):
    spec = constants.CONTRIBUTION_KINDS.get(kind)
    if spec is None or spec["file"] is None:
        return None
    return spec["file"].format(id=contribution_id)


def _clamp_contribution_id(raw: str) -> str:
    """Keep a generated id inside the 96-byte contribution grammar."""
    if len(raw) <= 96 and check_contribution_id(raw) is None:
        return raw
    trimmed = raw[:96].rstrip("-_.")
    while trimmed and check_contribution_id(trimmed) is not None:
        trimmed = trimmed[:-1]
    return trimmed or "skill"


def _capability_union(profile: dict, runtime: str, contributions, tools) -> "list[str]":
    names = set(profile.get("capabilities") or ())
    for contribution in contributions:
        paired = constants.CONTRIBUTION_KINDS.get(contribution["kind"], {}).get("capability")
        if paired:
            names.add(paired)
    for tool in tools:
        names.add("agent.tools.register")
        for capability in tool.get("capabilities") or ():
            names.add(constants.CAPABILITY_ALIASES.get(capability, capability))
    if runtime == "process":
        names.add("process.execute")
    if runtime == "declarative":
        names -= set(DECLARATIVE_FORBIDDEN)
    return sorted(
        (name for name in names if name in constants.CAPABILITY_NAMES),
        key=lambda name: (RISK_ORDER.get(constants.CAPABILITY_RISK.get(name, "low"), 9), name),
    )


def _grant_commands(extension_id: str, capability: str, scopes) -> "list[str]":
    commands = []
    scopes = list(scopes or ())
    if not scopes:
        if capability == "network.http":
            scopes = ["domain:<api-host>"]
        elif capability == "secrets.read":
            scopes = ["secret:<SECRET_NAME>"]
        elif capability == "process.execute":
            scopes = ["program:python3"]
    for scope in scopes:
        commands.append(
            "bsh ext grant %s %s --scope %s" % (extension_id, capability, scope)
        )
    if not commands:
        commands.append("bsh ext grant %s %s" % (extension_id, capability))
    return commands


def _scope_todo(scopes) -> bool:
    return any("<" in str(scope) for scope in (scopes or ()))


def _capability_rows(extension_id: str, profile: dict, names, runtime: str):
    rows = []
    for name in names:
        risk = constants.CAPABILITY_RISK.get(name, "low")
        why = (profile.get("reasons") or {}).get(name)
        if not why:
            why = domains.COMMON_REASONS.get(name, constants.CAPABILITY_DOC.get(name, ""))
        scopes = (profile.get("grant_scopes") or {}).get(name, ())
        if runtime == "declarative" and name in DECLARATIVE_FORBIDDEN:
            continue
        rows.append({
            "name": name,
            "risk": risk,
            "meaning": constants.CAPABILITY_DOC.get(name, ""),
            "why": why,
            "explicit": risk in ("high", "critical"),
            "scopes": list(scopes),
            "scope_todo": _scope_todo(scopes),
            "grants": _grant_commands(extension_id, name, scopes),
        })
    return rows


def _contribution_rows(profile: dict, namespace: str, tools):
    rows = []
    for tool in tools:
        rows.append({
            "kind": "tool",
            "id": tool["id"],
            "file": tool["file"],
            "purpose": tool["description"],
            "capability": "agent.tools.register",
        })
    for contribution in profile.get("contributions") or ():
        kind = contribution["kind"]
        rows.append({
            "kind": kind,
            "id": contribution["id"],
            "file": _contribution_file(kind, contribution["id"]),
            "purpose": contribution.get("purpose") or "",
            "capability": constants.CONTRIBUTION_KINDS.get(kind, {}).get("capability"),
        })
    skill = profile.get("skill") or {}
    if skill:
        base = skill.get("id", "skill")
        if base == namespace or base.startswith(namespace + "-"):
            skill_id = _clamp_contribution_id(base)
        else:
            skill_id = _clamp_contribution_id("%s-%s" % (namespace, base))
        rows.append({
            "kind": "skill",
            "id": skill_id,
            "file": _contribution_file("skill", skill_id),
            "purpose": skill.get("purpose") or "",
            "capability": "agent.skills.provide",
        })
    panel = profile.get("panel") or {}
    if panel:
        rows.append({
            "kind": "panel",
            "id": panel.get("id", "status"),
            "file": _contribution_file("panel", panel.get("id", "status")),
            "purpose": panel.get("purpose") or "",
            "capability": "ui.panels",
        })
    return rows


def _tool_rows(profile: dict, runtime: str):
    rows = []
    for tool in profile.get("tools") or ():
        capabilities = list(tool.get("capabilities") or ())
        implementation = tool.get("implementation")
        supported = True
        note = ""
        if runtime == "declarative" and not implementation:
            supported = False
            note = (
                "A declarative runtime cannot implement this tool. Replace it with "
                "a pure transformation or change the runtime to process."
            )
        if runtime == "process" and implementation:
            implementation = None
        row = {
            "id": tool["id"],
            "description": tool.get("description") or "",
            "file": "tools/%s.json" % tool["id"],
            "input_schema": _schema(tool.get("args")),
            "capabilities": capabilities,
            "returns": tool.get("returns") or "",
            "runs": tool.get("runs") or "",
            "scope_arguments": [
                arg["name"] for arg in tool.get("args") or () if arg.get("scope")
            ],
            "supported_by_runtime": supported,
            "note": note,
        }
        if implementation:
            row["implementation"] = implementation
        rows.append(row)
    return rows


def _describe_contract(name: str) -> str:
    return "%s is the manifest 2.0 identifier; keep it stable after the first release." % name


def _compare(path: Path, plan: dict) -> dict:
    """Compare a package on disk with the blueprint."""
    manifest_path = path / constants.MANIFEST_FILE
    result = {
        "present": path.exists(),
        "path": str(path),
        "has_manifest": manifest_path.is_file(),
        "status": "no-package",
        "design_file": (path / "docs" / "design.md").is_file(),
    }
    if not result["has_manifest"]:
        result["note"] = (
            "No extension.toml yet. Scaffold the package from this blueprint "
            "before implementing a tool."
        )
        return result
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        result["status"] = "error"
        result["error"] = "reading extension.toml needs Python 3.11+ (tomllib)"
        return result
    try:
        manifest = tomllib.loads(read_text(manifest_path, constants.MAX_MANIFEST_BYTES))
    except Exception as error:
        result["status"] = "error"
        result["error"] = "%s does not parse: %s" % (manifest_path, error)
        return result

    identity = manifest.get("extension") or {}
    declared = []
    for contribution in manifest.get("contribution") or ():
        if isinstance(contribution, dict):
            declared.append((contribution.get("kind"), contribution.get("id")))
    declared_set = set(declared)
    planned_set = {(row["kind"], row["id"]) for row in plan["contributions"]}
    missing_contributions = sorted(planned_set - declared_set)
    extra_contributions = sorted(declared_set - planned_set)

    manifest_capabilities = {
        constants.CAPABILITY_ALIASES.get(name, name)
        for name in (manifest.get("capabilities") or {}).get("required") or ()
        if isinstance(name, str)
    }
    planned_capabilities = {row["name"] for row in plan["capabilities"]}
    missing_capabilities = sorted(planned_capabilities - manifest_capabilities)
    extra_capabilities = sorted(
        name for name in manifest_capabilities - planned_capabilities
        if constants.CAPABILITY_RISK.get(name) in ("high", "critical")
    )

    missing_tool_files = []
    for tool in plan["tools"]:
        if ("tool", tool["id"]) in declared_set and not (path / tool["file"]).is_file():
            missing_tool_files.append(tool["file"])

    runtime = (manifest.get("runtime") or {}).get("kind")
    runtime_match = runtime == plan["extension"]["runtime"]
    id_match = identity.get("id") == plan["extension"]["id"]
    placeholder = plan["extension"].get("placeholder_id")
    result.update({
        "id": identity.get("id"),
        "version": identity.get("version"),
        "runtime": runtime,
        "runtime_match": runtime_match,
        "id_match": id_match,
        "declared_contributions": len(declared),
        "planned_contributions": len(planned_set),
        "missing_contributions": [
            {"kind": kind, "id": cid, "file": _contribution_file(kind, cid)}
            for kind, cid in missing_contributions
        ],
        "extra_contributions": [
            {"kind": kind, "id": cid} for kind, cid in extra_contributions
        ],
        "missing_capabilities": missing_capabilities,
        "extra_high_risk_capabilities": extra_capabilities,
        "missing_tool_files": missing_tool_files,
        "placeholder_id": placeholder,
    })
    next_actions = []
    if not id_match:
        next_actions.append(
            "The package id is %r but the blueprint is %r; decide which one is "
            "stable before publishing." % (identity.get("id"), plan["extension"]["id"])
        )
    if not runtime_match:
        next_actions.append(
            "The package runtime is %r but the blueprint recommends %r."
            % (runtime, plan["extension"]["runtime"])
        )
    for item in result["missing_contributions"]:
        next_actions.append(
            "Declare and create the %s contribution %r." % (item["kind"], item["id"])
        )
    for relative in missing_tool_files:
        next_actions.append("Create the declared tool file %s." % relative)
    for name in missing_capabilities:
        next_actions.append(
            "Decide whether the package needs %s; if it does, add it to "
            "capabilities.required and grant it." % name
        )
    for name in extra_capabilities:
        next_actions.append(
            "The package asks for %s, which is not in the blueprint; justify it "
            "or remove it." % name
        )
    result["next_actions"] = next_actions
    complete = (not missing_contributions and not missing_capabilities
                and not missing_tool_files and not extra_capabilities
                and runtime_match and id_match)
    result["status"] = "matches-blueprint" if complete else "in-progress"
    return result


def _cell(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")


def _render_markdown(plan: dict) -> str:
    extension = plan["extension"]
    domain = plan["domain"]
    lines = []
    lines.append("# Extension design: %s" % extension["name"])
    lines.append("")
    lines.append("> %s" % plan["description"])
    lines.append("")
    lines.append(
        "Id: %s%s%s  |  Version: %s  |  Runtime: %s%s%s"
        % (BT, extension["id"], BT, extension["version"], BT,
           extension["runtime"], BT)
    )
    if extension.get("placeholder_id"):
        lines.append("")
        lines.append(
            "The id uses the %s placeholder. Replace %s with the publisher's "
            "reverse-domain name before the first release." % (BT + "com.example" + BT,
                                                                 BT + "example" + BT)
        )
    lines.append("")
    lines.append("This is a blueprint, not a verified package. It records the "
                 "smallest surface that does the domain's work; every claim below "
                 "still has to be implemented and tested.")
    lines.append("")

    lines.append("## Domain fit")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append("| Domain | %s |" % _cell(domain["key"]))
    lines.append("| Confidence | %s |" % _cell(domain["confidence"]))
    lines.append("| Matched signals | %s |"
                 % _cell(", ".join(domain.get("signals") or []) or "none"))
    lines.append("| Runtime | %s |" % _cell(plan["extension"]["runtime"]))
    lines.append("| Why this changes the design | %s |"
                 % _cell(plan["runtime_reason"]))
    lines.append("")
    if domain.get("catalogued"):
        lines.append("The brief matched the %s profile: %s"
                     % (BT + domain["key"] + BT, domain["summary"]))
    else:
        lines.append("The brief did not match a catalogued domain. Answer the open "
                     "questions below before committing to more than one tool.")
    lines.append("")

    lines.append("## Contributions")
    lines.append("")
    lines.append("| Kind | Id | File | Capability | Purpose |")
    lines.append("|---|---|---|---|---|")
    for row in plan["contributions"]:
        lines.append("| %s | %s | %s | %s | %s |"
                     % (_cell(row["kind"]), _cell(row["id"]),
                        _cell(row["file"] or "(declaration only)"),
                        _cell(row["capability"] or "(none)"),
                        _cell(row["purpose"])))
    lines.append("")

    lines.append("## Tool surface")
    lines.append("")
    lines.append("Each tool's path or URL argument must be named %s or %s so the "
                 "call scope matches a grant." % (BT + "path" + BT, BT + "url" + BT))
    lines.append("")
    for tool in plan["tools"]:
        lines.append("### %s" % tool["id"])
        lines.append("")
        lines.append(tool["description"])
        lines.append("")
        lines.append("- File: %s" % (BT + tool["file"] + BT))
        if tool.get("scope_arguments"):
            lines.append("- Scope argument: %s"
                         % ", ".join(BT + name + BT for name in tool["scope_arguments"]))
        if tool.get("returns"):
            lines.append("- Returns: %s" % tool["returns"])
        if tool.get("runs"):
            lines.append("- Runs: %s" % tool["runs"])
        lines.append("- Capabilities: %s"
                     % (", ".join(BT + name + BT for name in tool["capabilities"])
                        or "(none beyond registration)"))
        if tool.get("note"):
            lines.append("- Runtime note: %s" % tool["note"])
        descriptor = {
            "description": tool["description"],
            "input_schema": tool["input_schema"],
            "capabilities": tool["capabilities"],
        }
        if tool.get("implementation"):
            descriptor["implementation"] = tool["implementation"]
        lines.append("")
        lines.append(FENCE + "json")
        lines.append(json.dumps(descriptor, indent=2, ensure_ascii=False))
        lines.append(FENCE)
        lines.append("")

    lines.append("## Capabilities and grants")
    lines.append("")
    lines.append("| Capability | Risk | Why this package needs it | Grant |")
    lines.append("|---|---|---|---|")
    for row in plan["capabilities"]:
        grant = row["grants"][0] if row["grants"] else ""
        lines.append("| %s | %s | %s | %s |"
                     % (_cell(row["name"]), _cell(row["risk"]),
                        _cell(row["why"]), _cell(grant)))
    lines.append("")
    todo = [row for row in plan["capabilities"] if row.get("scope_todo")]
    if todo:
        lines.append("Replace every %s placeholder in a scope with a real host, "
                     "secret name or path before running the grant. The host "
                     "evaluates the scope, so a placeholder never matches."
                     % (BT + "<...>" + BT))
        lines.append("")
    explicit = [row for row in plan["capabilities"] if row["explicit"]]
    if explicit:
        lines.append("These capabilities need an explicit grant; declaring them in "
                     "the manifest is a request, not an authorization:")
        lines.append("")
        lines.append(FENCE + "text")
        for row in explicit:
            for command in row["grants"]:
                lines.append(command)
        lines.append(FENCE)
        lines.append("")

    lines.append("## Safety rules")
    lines.append("")
    for rule in plan["safety"]:
        lines.append("- %s" % rule)
    lines.append("")

    lines.append("## Build order")
    lines.append("")
    for index, step in enumerate(plan["build_order"], start=1):
        lines.append("%d. %s" % (index, step))
    lines.append("")

    lines.append("## Acceptance gates")
    lines.append("")
    for gate in plan["gates"]:
        lines.append("- [ ] %s" % gate)
    lines.append("")

    lines.append("## Open questions")
    lines.append("")
    for question in plan["open_questions"]:
        lines.append("- %s" % question)
    lines.append("")

    existing = plan.get("existing")
    if existing:
        lines.append("## Existing package check")
        lines.append("")
        if not existing.get("present"):
            lines.append("No package exists at %s yet." % (BT + existing["path"] + BT))
            lines.append("")
        elif not existing.get("has_manifest"):
            lines.append("The directory exists but has no extension.toml yet.")
        elif existing.get("error"):
            lines.append("The manifest could not be read: %s" % existing["error"])
        else:
            lines.append("| Field | Package | Blueprint |")
            lines.append("|---|---|---|")
            lines.append("| Id | %s | %s |"
                         % (_cell(existing.get("id")), _cell(extension["id"])))
            lines.append("| Runtime | %s | %s |"
                         % (_cell(existing.get("runtime")), _cell(extension["runtime"])))
            lines.append("| Contributions | %s | %s |"
                         % (_cell(existing.get("declared_contributions")),
                            _cell(existing.get("planned_contributions"))))
            lines.append("")
            lines.append("Status: %s" % BT + str(existing.get("status")) + BT)
            lines.append("")
            if existing.get("missing_contributions"):
                lines.append("Missing surfaces:")
                lines.append("")
                for item in existing["missing_contributions"]:
                    lines.append("- %s %s" % (item["kind"], BT + str(item["id"]) + BT))
                lines.append("")
            if existing.get("missing_capabilities"):
                lines.append("Missing capabilities: %s"
                             % ", ".join(BT + name + BT
                                         for name in existing["missing_capabilities"]))
                lines.append("")
            if existing.get("extra_high_risk_capabilities"):
                lines.append("High-risk capabilities not in the blueprint: %s"
                             % ", ".join(BT + name + BT
                                         for name in existing["extra_high_risk_capabilities"]))
                lines.append("")
            if existing.get("next_actions"):
                lines.append("Next actions:")
                lines.append("")
                for action in existing["next_actions"]:
                    lines.append("- %s" % action)
                lines.append("")
    lines.append("## Next")
    lines.append("")
    for command in plan.get("next") or ():
        lines.append("- %s" % command)
    lines.append("")
    lines.append("Generated by the Extension DevKit on %s." % utc_stamp())
    return "\n".join(lines)


def _blueprint_checklist(plan: dict) -> str:
    """The implementation checklist appended to a written blueprint."""
    lines = ["", "## Implementation checklist", ""]
    for tool in plan["tools"]:
        lines.append("- [ ] Tool %s (%s) — add the file and declare the "
                     "contribution" % (tool["id"], tool["file"]))
    lines.append("")
    for row in plan["capabilities"]:
        if not row["explicit"]:
            continue
        lines.append("- [ ] Grant %s (%s)" % (row["name"], row["risk"]))
        for command in row["grants"]:
            lines.append("      %s" % command)
    lines.append("")
    lines.append("The acceptance gates above are the release gates. Run them "
                 "before the market entry.")
    return "\n".join(lines) + "\n"


def design(arguments: dict) -> dict:
    """Build a domain blueprint, optionally compared with a package on disk."""
    raw_domain = arguments.get("domain")
    brief = arguments.get("brief") or ""
    if not isinstance(raw_domain, str) or not raw_domain.strip():
        if not brief:
            fail("domain is required: a profile key such as data, devops or web, "
                 "or a sentence that names the domain")
        raw_domain = brief
    if not isinstance(brief, str):
        fail("brief must be a string")
    key, confidence, score, signals = domains.match(raw_domain, brief)
    profile = domains.profile_for(key)

    runtime = arguments.get("runtime") or profile["runtime"]
    if runtime not in ("declarative", "process"):
        fail("runtime must be declarative or process (the runtime the scaffold can "
             "write); got %r" % (runtime,))
    raw_path = arguments.get("path")
    path = resolve_new_path(raw_path) if isinstance(raw_path, str) and raw_path.strip() else None

    raw_id = arguments.get("id")
    extension_id, name, placeholder = _identity(raw_id, raw_domain, brief, key)
    namespace = extension_id.rsplit(".", 1)[-1]
    description = (brief.strip() or profile["summary"])[:512]

    tools = _tool_rows(profile, runtime)
    contributions = _contribution_rows(profile, namespace, tools)
    capabilities = _capability_union(profile, runtime, contributions, profile.get("tools") or ())
    capability_rows = _capability_rows(extension_id, profile, capabilities, runtime)

    warnings = []
    if runtime != profile["runtime"]:
        warnings.append(
            "The %s profile recommends the %s runtime; the blueprint uses %s."
            % (key, profile["runtime"], runtime)
        )
    if runtime == "declarative" and profile["runtime"] == "process":
        warnings.append(
            "A declarative package cannot run the process tools below. Keep the "
            "text surfaces and replace the tools with pure transformations, or "
            "switch the runtime to process."
        )

    plan = {
        "domain": {
            "key": key,
            "title": profile["title"],
            "summary": profile["summary"],
            "confidence": confidence,
            "score": score,
            "signals": signals,
            "catalogued": key != "generic",
            "recommended_runtime": profile["runtime"],
        },
        "extension": {
            "id": extension_id,
            "name": name,
            "version": "1.0.0",
            "runtime": runtime,
            "recommended_runtime": profile["runtime"],
            "runtime_reason": profile["runtime_reason"],
            "placeholder_id": placeholder,
            "namespace": namespace,
        },
        "description": description,
        "runtime_reason": profile["runtime_reason"],
        "contributions": contributions,
        "tools": tools,
        "capabilities": capability_rows,
        "safety": list(profile["guardrails"]),
        "build_order": list(profile["build_order"]),
        "gates": list(profile["gates"]),
        "open_questions": list(profile["open_questions"]),
        "warnings": warnings,
        "existing": None,
        "design_file": None,
    }

    if path is not None:
        plan["existing"] = _compare(path, plan)

    next_steps = []
    if path is None:
        next_steps.append("Choose an absolute package path, then run scaffold with "
                          "domain=%s." % key)
    elif not plan["existing"] or not plan["existing"].get("has_manifest"):
        next_steps.append(
            "scaffold %s %s domain=%s" % (path, extension_id, key)
        )
    else:
        for action in (plan["existing"].get("next_actions") or [])[:6]:
            next_steps.append(action)
        next_steps.append("validate %s" % path)
        next_steps.append("lint %s" % path)
        next_steps.append("check %s smoke=true" % path)
    for row in capability_rows:
        if row["explicit"]:
            next_steps.append(row["grants"][0])
            break
    next_steps.append("bsh ext install %s" % (path or "<absolute package path>"))
    plan["next"] = next_steps

    if path is not None and arguments.get("write"):
        target = path / "docs" / "design.md"
        markdown = _render_markdown(plan) + _blueprint_checklist(plan)
        write_text(target, markdown)
        plan["design_file"] = str(target)

    plan["markdown"] = _render_markdown(plan)
    return plan


def catalog_markdown() -> str:
    """The catalogue as a reference topic."""
    lines = [
        "# Domain profiles",
        "",
        "The DevKit carries a small, opinionated catalogue. A profile is the "
        "smallest surface that does the domain's real work, not a survey of "
        "every possible package.",
        "",
        domains.catalog_table(),
        "",
        "## How to choose",
        "",
        "- Pick the domain that names the work, not the technology: a Jira "
        "extension is 'web', a SQL helper is 'data', a playbook is 'knowledge'.",
        "- If two profiles fit, pick the one whose tools you can actually "
        "implement this week.",
        "- If none fits, use 'generic' and answer its open questions before "
        "adding a second tool.",
        "",
        "Then call design with the domain and a one-sentence brief. The "
        "blueprint names the runtime, contributions, tools, grants, safety "
        "rules and build order; scaffold can start the package from it.",
    ]
    return "\n".join(lines)
