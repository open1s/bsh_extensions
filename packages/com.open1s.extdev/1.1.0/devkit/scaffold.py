"""Scaffold a complete, validating BSH extension package.

The scaffold is not a stub: what it writes passes the same validation the host
applies, ships the file each contribution declares, and includes a
self-checking test that runs without any dependency. A developer starts from a
green package and edits one thing at a time.
"""

from __future__ import annotations

import json

from . import constants, design as design_module
from .util import (
    check_extension_id,
    check_version,
    fail,
    resolve_new_path,
    utc_stamp,
    write_text,
)

RUNTIMES = ("declarative", "process")

MIT_LICENSE = """MIT License

Copyright (c) {year} {author}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

GITIGNORE = """__pycache__/
*.pyc
.DS_Store
*.tmp
"""

PROCESS_SERVER = '''"""The package's JSON-RPC process runtime.

The host starts this file with python3, sends one JSON object per line on
stdin and reads one per line on stdout. The handshake must echo the token,
otherwise the host refuses the process; every tool result is a JSON value the
host turns into tool content.
"""

import json
import sys

TOOLS = ("describe", "echo")
COMMANDS = ("hello",)


class ToolError(Exception):
    """A refusal that becomes a JSON-RPC error, and therefore a tool error."""


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\\n")
    sys.stdout.flush()


def tool_describe(_arguments):
    return {{
        "id": "{extension_id}",
        "version": "{version}",
        "runtime": "process",
        "tools": list(TOOLS),
        "commands": list(COMMANDS),
    }}


def tool_echo(arguments):
    text = arguments.get("text")
    if not isinstance(text, str) or not text:
        raise ToolError("text must be a non-empty string")
    return {{"text": text}}


TOOL_HANDLERS = {{"describe": tool_describe, "echo": tool_echo}}


def execute_command(name, _arguments):
    if name == "hello":
        return {{"inserted": "Hello from {name}"}}
    raise ToolError("unknown command %r" % name)


def handle(request):
    method = request.get("method")
    params = request.get("params") or {{}}
    if method == "initialize":
        return {{"result": {{"protocolVersion": "1.0",
                             "token": params.get("token", ""),
                             "name": "{namespace}"}}}}, True
    if method == "shutdown":
        return {{"result": {{}}}}, False
    if method == "tools/call":
        name = str(params.get("name") or "").rsplit("__", 1)[-1]
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {{"error": {{"code": -32601, "message": "unknown tool %r" % name}}}}, True
        try:
            return {{"result": handler(params.get("arguments") or {{}})}}, True
        except ToolError as error:
            return {{"error": {{"code": -32000, "message": str(error)}}}}, True
        except Exception as error:  # a bug is reported, never a silent success
            return {{"error": {{"code": -32603,
                               "message": "%s: %s" % (type(error).__name__, error)}}}}, True
    if method == "commands/execute":
        try:
            return {{"result": execute_command(str(params.get("name") or ""),
                                              params.get("arguments") or {{}})}}, True
        except ToolError as error:
            return {{"error": {{"code": -32000, "message": str(error)}}}}, True
    return {{"error": {{"code": -32601, "message": "unsupported method %r" % method}}}}, True


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        outcome, keep_going = handle(request)
        if outcome is not None:
            envelope = {{"jsonrpc": "2.0", "id": request.get("id")}}
            envelope.update(outcome)
            emit(envelope)
        if not keep_going:
            break


if __name__ == "__main__":
    main()
'''

TEST_TEMPLATE = '''"""Self-check for this package: no host, no dependencies.

Run it with:  python3 -m unittest discover -s tests
"""

import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONTRIBUTION_FILES = {
    "tool": "tools/{id}.json",
    "command": "commands/{id}.md",
    "panel": "panels/{id}.json",
    "prompt": "prompts/{id}.md",
    "context": "contexts/{id}.md",
    "skill": "skills/{id}/SKILL.md",
    "workflow": "workflows/{id}.json",
    "theme": "themes/{id}.json",
    "preset": "presets/{id}.json",
    "model-provider": "providers/models/{id}.json",
    "agent-provider": "providers/agents/{id}.json",
    "language": "languages/{id}.json",
    "integration": "integrations/{id}.json",
}


def manifest():
    with (ROOT / "extension.toml").open("rb") as stream:
        return tomllib.load(stream)


class PackageTest(unittest.TestCase):
    def test_schema_version(self):
        self.assertEqual(manifest()["schema_version"], "2.0")

    def test_identity(self):
        identity = manifest()["extension"]
        for key in ("id", "name", "version", "description"):
            self.assertTrue(identity.get(key), key)

    def test_declared_files_exist(self):
        for contribution in manifest().get("contribution", []):
            template = CONTRIBUTION_FILES.get(contribution["kind"])
            if template is None:
                continue
            path = ROOT / template.format(id=contribution["id"])
            self.assertTrue(path.is_file(), str(path))

    def test_every_json_contribution_parses(self):
        for contribution in manifest().get("contribution", []):
            template = CONTRIBUTION_FILES.get(contribution["kind"])
            if template is None or not template.endswith(".json"):
                continue
            path = ROOT / template.format(id=contribution["id"])
            json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
'''


def toml_string(value: str) -> str:
    """A TOML basic string; JSON escaping is the same subset."""
    return json.dumps(value, ensure_ascii=False)


def title_case(raw: str) -> str:
    words = raw.replace("_", "-").split("-")
    return " ".join(word[:1].upper() + word[1:] for word in words if word) or raw


def scaffold(arguments: dict) -> dict:
    """Create a package skeleton and return the files it wrote."""
    path = resolve_new_path(arguments.get("path"))
    raw_id = arguments.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        fail("id is required: a reverse-domain id such as com.example.toolkit")
    reason = check_extension_id(raw_id)
    if reason:
        fail(reason)
    version = arguments.get("version") or "1.0.0"
    reason = check_version(version)
    if reason:
        fail(reason)
    raw_domain = arguments.get("domain")
    brief = arguments.get("brief") or ""
    plan = None
    runtime = arguments.get("runtime")
    if isinstance(raw_domain, str) and raw_domain.strip():
        plan = design_module.design({
            "domain": raw_domain,
            "brief": brief,
            "id": raw_id,
            "path": str(path),
            "runtime": runtime,
        })
        if not runtime:
            runtime = plan["extension"]["runtime"]
    else:
        runtime = runtime or "declarative"
    if runtime not in RUNTIMES:
        fail("runtime must be one of %s" % ", ".join(RUNTIMES))
    namespace = raw_id.rsplit(".", 1)[-1]
    name = arguments.get("name") or (
        plan["extension"]["name"] if plan else title_case(namespace)
    )
    description = arguments.get("description") or (
        plan["description"] if plan
        else "A BSH extension scaffolded by the Extension DevKit"
    )
    author = arguments.get("author") or "BSH Extension Author"
    license_name = arguments.get("license") or "MIT"
    force = bool(arguments.get("force"))
    if not isinstance(name, str) or not name.strip():
        fail("name must be a non-empty string")

    if path.exists() and any(path.iterdir()) and not force:
        fail("%s already exists and is not empty; pass force=true to write into it" % path)

    if plan is not None:
        files, contributions, capabilities = _domain_bundle(
            plan, raw_id, name, version, runtime, namespace, license_name, author
        )
        files["extension.toml"] = _manifest_text(
            raw_id, name, version, description, author, license_name, runtime,
            contributions=contributions, capabilities=capabilities,
        )
        files["README.md"] = _domain_readme(
            plan, raw_id, name, version, runtime, description, capabilities
        )
        files["CHANGELOG.md"] = "# Changelog\n\n## %s - %s\n\n- First release, scaffolded from the %s blueprint.\n" % (
            version, utc_stamp(), plan["domain"]["key"]
        )
        files[".gitignore"] = GITIGNORE
        files["LICENSE"] = MIT_LICENSE.format(year=utc_stamp()[:4], author=author)
        files["schemas/config.schema.json"] = _domain_config_schema()
        files["tests/test_package.py"] = TEST_TEMPLATE
        written = []
        for relative in sorted(files):
            write_text(path / relative, files[relative])
            written.append(relative)
        design_file = str(path / "docs" / "design.md")
        return {
            "path": str(path),
            "id": raw_id,
            "version": version,
            "runtime": runtime,
            "domain": plan["domain"]["key"],
            "design": {
                "domain": plan["domain"]["key"],
                "confidence": plan["domain"]["confidence"],
                "file": design_file,
                "planned_tools": [tool["id"] for tool in plan["tools"]],
                "declared_tools": [cid for kind, cid in contributions if kind == "tool"],
                "warnings": plan.get("warnings") or [],
            },
            "files": written,
            "next": [
                "Read %s and work its checklist one item at a time." % design_file,
                "devkit validate %s" % path,
                "devkit lint %s" % path,
                "devkit check %s smoke=true" % path,
                "bsh ext install %s" % path,
            ],
        }

    skill_id = namespace
    files = {}

    files["extension.toml"] = _manifest_text(
        raw_id, name, version, description, author, license_name, runtime
    )
    files["README.md"] = _readme_text(raw_id, name, version, runtime, description)
    files["CHANGELOG.md"] = "# Changelog\n\n## %s - %s\n\n- First release.\n" % (
        version,
        utc_stamp(),
    )
    files[".gitignore"] = GITIGNORE
    files["LICENSE"] = MIT_LICENSE.format(year=utc_stamp()[:4], author=author)
    files["schemas/config.schema.json"] = json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "greeting": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Greeting the package appends to its output.",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Include extra fields in the describe tool.",
                },
            },
            "additionalProperties": False,
        },
        indent=2,
    ) + "\n"
    files["commands/greet.md"] = (
        "---\ndescription: Greet through %s\n---\n\n"
        "Call the %s extension's tools and report the result in one short sentence.\n"
        % (name, name)
    )
    files["prompts/guide.md"] = (
        "---\ndescription: %s instruction\n---\n\n"
        "This workspace can use the %s extension. When the reader asks what it "
        "does, call its tools rather than guessing from the manifest.\n" % (name, name)
    )
    files["contexts/workspace.md"] = (
        "---\ndescription: %s scoped context\npaths: extension.toml, **/extension.toml\n---\n\n"
        "This workspace contains a BSH extension package (%s).\n" % (name, raw_id)
    )
    files["panels/status.json"] = json.dumps(
        {
            "title": name,
            "icon": None,
            "location": "right",
            "default_visibility": "visible",
            "view": {
                "schema_version": constants.UI_SCHEMA_VERSION,
                "root": {
                    "type": "column",
                    "children": [
                        {"type": "heading", "text": name, "level": 2},
                        {
                            "type": "text",
                            "text": "Scaffolded by the Extension DevKit. Edit "
                                    "panels/status.json to change this card.",
                        },
                        {"type": "divider"},
                        {
                            "type": "button",
                            "label": "Say hello",
                            "action": "hello",
                            "style": "primary",
                        },
                    ],
                },
            },
        },
        indent=2,
    ) + "\n"
    files["skills/%s/SKILL.md" % skill_id] = (
        "---\nname: %s\ndescription: Use the %s extension\nversion: 1.0.0\n---\n\n"
        "# %s\n\nUse this skill when the reader works with the %s extension.\n\n"
        "1. Call the describe tool to show identity and version.\n"
        "2. Call the echo tool to prove arguments reach the package.\n"
        % (skill_id, name, name, name)
    )
    files["tests/test_package.py"] = TEST_TEMPLATE

    if runtime == "declarative":
        files["tools/echo.json"] = json.dumps(
            {
                "description": "Echo the arguments unchanged",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to echo."}
                    },
                    "additionalProperties": True,
                },
                "implementation": {"kind": "echo_arguments"},
            },
            indent=2,
        ) + "\n"
        files["tools/describe.json"] = json.dumps(
            {
                "description": "Describe this extension package",
                "input_schema": {"type": "object", "properties": {}},
                "implementation": {
                    "kind": "template",
                    "text": raw_id + " " + version + " (declarative)",
                },
            },
            indent=2,
        ) + "\n"
    else:
        files["server.py"] = PROCESS_SERVER.format(
            extension_id=raw_id, version=version, name=name, namespace=namespace
        )
        files["tools/echo.json"] = json.dumps(
            {
                "description": "Echo the text argument",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to echo."}
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
            indent=2,
        ) + "\n"
        files["tools/describe.json"] = json.dumps(
            {
                "description": "Describe this extension package",
                "input_schema": {"type": "object", "properties": {}},
            },
            indent=2,
        ) + "\n"

    written = []
    for relative in sorted(files):
        target = path / relative
        write_text(target, files[relative])
        written.append(relative)

    return {
        "path": str(path),
        "id": raw_id,
        "version": version,
        "runtime": runtime,
        "files": written,
        "next": [
            "devkit validate %s" % path,
            "devkit lint %s" % path,
            "devkit check %s" % path,
            "bsh ext validate %s" % path,
            'bsh ext mock %s echo {"text": "hi"}' % path,
        ],
    }


def _manifest_text(raw_id, name, version, description, author, license_name, runtime,
                   contributions=None, capabilities=None):
    lines = [
        'schema_version = "2.0"',
        "",
        "[extension]",
        "id = %s" % toml_string(raw_id),
        "name = %s" % toml_string(name),
        "version = %s" % toml_string(version),
        "description = %s" % toml_string(description),
        "authors = [%s]" % toml_string(author),
        "license = %s" % toml_string(license_name),
        "",
        "[compatibility]",
        'host = ">=3.0.0, <4.0.0"',
        'extension_api = "^1.0"',
        "",
        "[runtime]",
        "kind = %s" % toml_string(runtime),
        "",
        "[runtime.config]",
        'startup = "on-demand"',
    ]
    if runtime == "process":
        lines += [
            'entry = "python3"',
            'protocol = "jsonrpc-2.0"',
            'args = ["-B", "server.py"]',
            "",
            "[runtime.config.env]",
            'PYTHONDONTWRITEBYTECODE = "1"',
        ]
    if capabilities is None:
        capabilities = ["agent.tools.register"]
        if runtime == "process":
            capabilities.append("process.execute")
    lines += ["", "[capabilities]", "required = [%s]"
              % ", ".join(toml_string(name) for name in capabilities)]
    if contributions is None:
        contributions = [
            ("tool", "describe"),
            ("tool", "echo"),
            ("command", "greet"),
            ("panel", "status"),
            ("prompt", "guide"),
            ("context", "workspace"),
            ("skill", raw_id.rsplit(".", 1)[-1]),
        ]
    for kind, contribution_id in contributions:
        lines += [
            "",
            "[[contribution]]",
            "kind = %s" % toml_string(kind),
            "id = %s" % toml_string(contribution_id),
            "",
            "[contribution.payload]",
        ]
    lines += [
        "",
        "[configuration]",
        'schema = "schemas/config.schema.json"',
        "",
        "[configuration.defaults]",
        'greeting = "hello from %s"' % name.replace('"', "'"),
        "verbose = false",
        "",
        "[resources]",
        "max_memory_mb = 128",
        "max_execution_ms = 5000",
        "max_output_bytes = 262144",
        "",
        "[dependencies]",
        "",
        "[services]",
        "provides = []",
        "requires = []",
        "",
    ]
    return "\n".join(lines)


def _readme_text(raw_id, name, version, runtime, description):
    if runtime == "process":
        runtime_note = (
            "A process package: the host starts 'python3 -B server.py' and speaks one\n"
            "JSON object per line. It needs the process.execute capability.\n"
        )
    else:
        runtime_note = (
            "A declarative package: the host executes no code, it reads the declared\n"
            "tool bodies, commands, prompts, contexts, panel and skill.\n"
        )
    lines = [
        "# " + name,
        "",
        description,
        "",
        "Id: " + raw_id + "  Version: " + version,
        "",
        "## Runtime",
        "",
        runtime_note,
        "## Develop",
        "",
        "    bsh ext validate .",
        "    bsh ext test .",
        "    bsh ext mock . describe",
        "    python3 -m unittest discover -s tests",
        "",
        "## Install",
        "",
        "    bsh ext install .",
        "    bsh ext list",
        "    bsh ext info " + raw_id,
        "",
        "## Contributes",
        "",
        "- tools: describe, echo",
        "- command: /greet",
        "- panel: " + name,
        "- prompt and workspace context",
        "- skill",
        "- configuration schema in schemas/config.schema.json",
        "",
        "Edit extension.toml and the matching file together: the host refuses a",
        "declared contribution whose file is missing, and ignores a file nobody",
        "declared.",
        "",
    ]
    return "\n".join(lines)

# --- domain-aware scaffold -------------------------------------------------


def _domain_config_schema() -> str:
    """The configuration schema a domain scaffold starts from."""
    return json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "greeting": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Greeting the package appends to its output.",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Include extra fields in the describe tool.",
                },
            },
            "additionalProperties": False,
        },
        indent=2,
    ) + "\n"


def _domain_bundle(plan, raw_id, name, version, runtime, namespace, license_name, author):
    """Write the domain surfaces and return (files, contributions, capabilities)."""
    files = {}
    contributions = []
    executable = runtime == "process"
    planned_tools = [tool for tool in plan["tools"]
                     if executable or tool.get("implementation")]
    declared_tools = []

    if executable:
        files["server.py"] = PROCESS_SERVER.format(
            extension_id=raw_id, version=version, name=name, namespace=namespace
        )
        files["tools/describe.json"] = json.dumps(
            {
                "description": "Describe this extension package",
                "input_schema": {"type": "object", "properties": {}},
            },
            indent=2,
        ) + "\n"
        files["tools/echo.json"] = json.dumps(
            {
                "description": "Echo the text argument",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to echo."}
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
            indent=2,
        ) + "\n"
        declared_tools = ["describe", "echo"]
        contributions += [("tool", "describe"), ("tool", "echo")]
    else:
        for tool in planned_tools:
            if tool["id"] == "describe":
                continue
            descriptor = {
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            }
            if tool.get("capabilities"):
                descriptor["capabilities"] = tool["capabilities"]
            if tool.get("implementation"):
                descriptor["implementation"] = tool["implementation"]
            files[tool["file"]] = json.dumps(descriptor, indent=2) + "\n"
            declared_tools.append(tool["id"])
            contributions.append(("tool", tool["id"]))
        files["tools/describe.json"] = json.dumps(
            {
                "description": "Describe this extension package",
                "input_schema": {"type": "object", "properties": {}},
                "implementation": {
                    "kind": "template",
                    "text": raw_id + " " + version + " (declarative)",
                },
            },
            indent=2,
        ) + "\n"
        declared_tools.append("describe")
        contributions.append(("tool", "describe"))

    command_rows = [row for row in plan["contributions"] if row["kind"] == "command"]
    purpose_by_id = {row["id"]: row["purpose"] for row in command_rows}
    command_ids = [row["id"] for row in command_rows]
    if "start" not in command_ids:
        command_ids.insert(0, "start")
    for command_id in command_ids:
        files["commands/%s.md" % command_id] = _domain_command(
            command_id, name, purpose_by_id.get(command_id, "")
        )
        contributions.append(("command", command_id))

    prompt = next((row for row in plan["contributions"] if row["kind"] == "prompt"), None)
    if prompt is None:
        prompt = {"id": "rules", "purpose": "Rules for this package"}
    files["prompts/%s.md" % prompt["id"]] = _domain_prompt(plan, name, raw_id)
    contributions.append(("prompt", prompt["id"]))

    context = next((row for row in plan["contributions"] if row["kind"] == "context"), None)
    if context is None:
        context = {"id": "workspace", "purpose": "Workspace facts"}
    files["contexts/%s.md" % context["id"]] = _domain_context(plan, name, raw_id)
    contributions.append(("context", context["id"]))

    skill = next((row for row in plan["contributions"] if row["kind"] == "skill"), None)
    if skill is None:
        skill = {"id": namespace, "purpose": "Build this extension"}
    files["skills/%s/SKILL.md" % skill["id"]] = _domain_skill(
        plan, name, raw_id, skill["id"], declared_tools
    )
    contributions.append(("skill", skill["id"]))

    panel = next((row for row in plan["contributions"] if row["kind"] == "panel"), None)
    if panel is None:
        panel = {"id": "overview", "purpose": "Package status"}
    files["panels/%s.json" % panel["id"]] = _domain_panel(
        plan, name, runtime, declared_tools
    )
    contributions.append(("panel", panel["id"]))

    capabilities = ["agent.tools.register"]
    if runtime == "process":
        capabilities.append("process.execute")
    for kind, _contribution_id in contributions:
        paired = constants.CONTRIBUTION_KINDS.get(kind, {}).get("capability")
        if paired and paired not in capabilities:
            capabilities.append(paired)

    files["docs/design.md"] = _domain_design_doc(plan, declared_tools, capabilities)
    return files, contributions, capabilities


def _domain_command(command_id, name, purpose):
    if command_id == "start":
        body = (
            "Read docs/design.md. Choose the first unchecked item in the "
            "implementation checklist, implement only that item, then call "
            "validate and lint on this package. Report rule ids and file paths. "
            "Do not add a capability the blueprint does not justify.\n"
        )
        description = "Continue building %s from its design" % name
    else:
        body = (
            "%s\n\n"
            "Read docs/design.md first and find the tool that implements this "
            "command. If the tool is not implemented yet, say which build-order "
            "step is next and implement only that step; never pretend the "
            "command ran.\n\n"
            "When the tool exists, call it and report the result with the file "
            "or rule it came from. Use absolute paths, and keep the path/url "
            "argument names the blueprint gives.\n" % purpose
        )
        description = purpose or "Run the %s workflow" % name
    return "---\ndescription: %s\n---\n\n%s" % (description, body)


def _domain_prompt(plan, name, raw_id):
    rules = list(plan["safety"])[:6]
    lines = [
        "---",
        "description: %s extension rules" % name,
        "---",
        "",
        "This workspace holds %s (%s), a %s extension under construction. "
        "Read docs/design.md before editing." % (name, raw_id, plan["domain"]["key"]),
        "",
        "Rules:",
    ]
    for rule in rules:
        lines.append("- %s" % rule)
    lines += [
        "- Add a capability only when a code path uses it; registration is not authorization.",
        "- Call validate and lint after every change, and quote their rule ids.",
    ]
    return "\n".join(lines) + "\n"


def _domain_context(plan, name, raw_id):
    lines = [
        "---",
        "description: %s package facts" % name,
        "paths: extension.toml, **/extension.toml, docs/design.md",
        "---",
        "",
        "%s is a %s extension package (%s) scaffolded from the %s blueprint."
        % (name, plan["domain"]["key"], raw_id, plan["domain"]["key"]),
        "",
        "The planned tools are %s."
        % (", ".join(tool["id"] for tool in plan["tools"]) or "none"),
        "The build order and acceptance gates live in docs/design.md.",
    ]
    return "\n".join(lines) + "\n"


def _domain_skill(plan, name, raw_id, skill_id, declared_tools):
    lines = [
        "---",
        "name: %s" % skill_id,
        "description: Build and use the %s extension for %s work"
        % (name, plan["domain"]["key"]),
        "version: 1.0.0",
        "---",
        "",
        "# %s" % name,
        "",
        "Use this skill when the reader asks to build, extend or use the %s "
        "extension (%s). Read docs/design.md before changing the package." % (name, raw_id),
        "",
        "## What it is for",
        "",
        plan["description"],
        "",
        "## Build order",
        "",
    ]
    for index, step in enumerate(plan["build_order"], start=1):
        lines.append("%d. %s" % (index, step))
    lines += ["", "## Tool surface", ""]
    for tool in plan["tools"]:
        state = "implemented" if tool["id"] in declared_tools else "planned"
        lines.append("- %s: %s (%s)" % (tool["id"], tool["description"], state))
    lines += ["", "## Acceptance gates", ""]
    for gate in plan["gates"]:
        lines.append("- %s" % gate)
    lines += [
        "",
        "Work one slice at a time: edit, validate, lint, smoke, then continue. "
        "Never claim a planned tool works before its file exists and is declared.",
    ]
    return "\n".join(lines) + "\n"


def _domain_panel(plan, name, runtime, declared_tools):
    planned = ", ".join(tool["id"] for tool in plan["tools"]) or "none"
    items = []
    for tool in plan["tools"]:
        items.append({
            "title": tool["id"],
            "detail": "implemented" if tool["id"] in declared_tools else "planned",
        })
    document = {
        "title": name,
        "icon": None,
        "location": "right",
        "default_visibility": "visible",
        "view": {
            "schema_version": constants.UI_SCHEMA_VERSION,
            "root": {
                "type": "column",
                "children": [
                    {"type": "heading", "text": name, "level": 2},
                    {
                        "type": "text",
                        "text": "%s extension under construction. Read "
                                "docs/design.md, then run the start command."
                                % plan["domain"]["key"],
                    },
                    {
                        "type": "table",
                        "columns": ["Key", "Value"],
                        "rows": [
                            ["domain", plan["domain"]["key"]],
                            ["runtime", runtime],
                            ["planned tools", planned],
                        ],
                    },
                    {"type": "divider"},
                    {"type": "list", "items": items},
                    {"type": "divider"},
                    {
                        "type": "button",
                        "label": "Say hello",
                        "action": "hello",
                        "style": "primary",
                    },
                ],
            },
        },
    }
    return json.dumps(document, indent=2) + "\n"


def _domain_design_doc(plan, declared_tools, capabilities):
    lines = [plan["markdown"], "", "## Implementation checklist", ""]
    lines.append("- [x] A validating manifest 2.0 skeleton exists.")
    lines.append("- [x] The commands, prompt, context, skill and panel are scaffolded.")
    for tool in plan["tools"]:
        state = "x" if tool["id"] in declared_tools else " "
        note = "" if tool["id"] in declared_tools else (
            " — add the file and declare the contribution"
        )
        lines.append("- [%s] Tool %s (%s)%s" % (state, tool["id"], tool["file"], note))
    lines.append("")
    lines.append("The scaffold declares only the tools whose files exist. A "
                 "declaration without a file fails validation, and a file "
                 "without a declaration is ignored by the host.")
    lines.append("")
    missing = [row for row in plan["capabilities"] if row["name"] not in capabilities]
    if missing:
        lines.append("### Capabilities still to decide")
        lines.append("")
        for row in missing:
            lines.append("- [ ] %s (%s): %s" % (row["name"], row["risk"], row["why"]))
            for command in row["grants"]:
                lines.append("      %s" % command)
        lines.append("")
    lines.append("The acceptance gates above are the release gates. Run them "
                 "before the market entry.")
    return "\n".join(lines) + "\n"


def _domain_readme(plan, raw_id, name, version, runtime, description, capabilities):
    tools = ", ".join(tool["id"] for tool in plan["tools"]) or "none"
    lines = [
        "# %s" % name,
        "",
        description,
        "",
        "Id: %s  Version: %s  Runtime: %s  Domain: %s"
        % (raw_id, version, runtime, plan["domain"]["key"]),
        "",
        "## Status",
        "",
        "Scaffolded from the %s blueprint. The commands, prompt, context, skill "
        "and panel are real. The tools below are planned; the scaffold declares "
        "only the tools whose files already exist." % plan["domain"]["key"],
        "",
        "## Design",
        "",
        "Read docs/design.md for the domain fit, the tool surface, the capability "
        "grants, the safety rules, the build order and the acceptance gates.",
        "",
        "Planned tools: %s" % tools,
        "",
        "## Develop",
        "",
        "    devkit validate .",
        "    devkit lint .",
        "    devkit check . smoke=true",
        "    python3 -m unittest discover -s tests",
        "",
        "Work one build-order step at a time. After each step, validate and "
        "lint before moving on.",
        "",
        "## Install",
        "",
        "    bsh ext install .",
        "    bsh ext list",
        "    bsh ext info %s" % raw_id,
        "",
        "## Capabilities",
        "",
        "The scaffold requests:",
        "",
    ]
    for capability in capabilities:
        lines.append("- %s (%s)" % (
            capability, constants.CAPABILITY_RISK.get(capability, "low")))
    explicit = [row for row in plan["capabilities"]
                if row["explicit"] and row["name"] not in capabilities]
    if explicit:
        lines += ["", "The blueprint will need these grants as its tools are implemented:", ""]
        for row in explicit:
            for command in row["grants"]:
                lines.append("    %s" % command)
    lines += [
        "",
        "## Layout",
        "",
        "    extension.toml",
        "    docs/design.md       the blueprint and the implementation checklist",
        "    tools/               declared tools only",
        "    commands/            prompt templates",
        "    prompts/ contexts/   model guidance",
        "    skills/              the build-and-use workflow",
        "    panels/              the status card",
        "    tests/               dependency-free package checks",
        "",
    ]
    return "\n".join(lines)

