"""Extension DevKit: the process runtime the host talks to.

One JSON object per line on stdin and stdout. The handshake echoes the token
the host sent; every tool call dispatches to a pure function in devkit and its
result is returned as JSON. The panel actions run the same code the tools run,
so the card is never a mock-up of the behaviour.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "1.1.0"
ID = "com.open1s.extdev"

CONFIG = {}
EVENTS = []
STARTED = time.time()
LAST_CHECK = {}


class ToolError(Exception):
    """A refusal that becomes a JSON-RPC error, and therefore a tool error."""


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def progress(message, percent=None):
    params = {"message": message}
    if percent is not None:
        params["percent"] = percent
    emit({"jsonrpc": "2.0", "method": "$/progress", "params": params})


def uptime():
    return round(time.time() - STARTED, 1)


def state():
    return {"config": CONFIG, "events": EVENTS, "uptime": uptime, "check": LAST_CHECK}


# --- panel -----------------------------------------------------------------


def panel_document() -> dict:
    """The live card: facts about this package plus its last self-check."""
    rows = [
        ["extension", ID],
        ["version", VERSION],
        ["runtime", "process (python3)"],
        ["python", sys.version.split()[0]],
        ["tools", "14"],
        ["commands", "9"],
        ["skills", "4"],
        ["domain profiles", "12"],
        ["events received", str(len(EVENTS))],
        ["uptime", "%ss" % uptime()],
    ]
    children = [
        {"type": "heading", "text": "Extension DevKit", "level": 2},
        {
            "type": "markdown",
            "text": "Design a domain extension, then scaffold, validate, lint, "
                    "smoke-test, package and publish it. Every action below runs "
                    "the same code the tools run.",
        },
        {"type": "table", "columns": ["Key", "Value"], "rows": rows},
        {"type": "divider"},
    ]
    check = LAST_CHECK or {}
    if check:
        level = "success" if check.get("ok") else "error"
        children.append({
            "type": "notification",
            "level": level,
            "text": "self-check %s: %s errors, %s warnings, %s notes"
                    % ("passed" if check.get("ok") else "failed",
                       check.get("summary", {}).get("errors", 0),
                       check.get("summary", {}).get("warnings", 0),
                       check.get("summary", {}).get("notes", 0)),
        })
        findings = check.get("findings", [])[:6]
        if findings:
            children.append({
                "type": "list",
                "items": [
                    {
                        "title": "%s %s" % (finding.get("severity"), finding.get("rule")),
                        "detail": finding.get("message", ""),
                    }
                    for finding in findings
                ],
            })
    else:
        children.append({
            "type": "text",
            "text": "No self-check yet. Press Run self-check to validate this package.",
        })
    children += [
        {"type": "divider"},
        {
            "type": "button",
            "label": "Run self-check",
            "action": "selfcheck",
            "style": "primary",
        },
        {"type": "button", "label": "Domain recipes", "action": "domains"},
        {"type": "button", "label": "Reference topics", "action": "topics"},
        {"type": "button", "label": "Refresh", "action": "refresh"},
        {"type": "spacer", "size": 8},
        {
            "type": "text",
            "text": "The card is returned by server.py on every action; the host "
                    "replaces it at the next revision.",
        },
    ]
    return {"schema_version": "1.0", "root": {"type": "column", "children": children}}


def topics_document() -> dict:
    from devkit import reference

    items = []
    for name in reference.topics():
        items.append({
            "title": name,
            "detail": "ask the agent to run explain with topic=" + name,
            "action": "refresh",
        })
    return {
        "schema_version": "1.0",
        "root": {
            "type": "column",
            "children": [
                {"type": "heading", "text": "Reference topics", "level": 2},
                {"type": "text", "text": "The explain tool returns each topic as markdown."},
                {"type": "list", "items": items},
                {"type": "button", "label": "Back", "action": "refresh"},
            ],
        },
    }


def domains_document() -> dict:
    """The domain catalogue as a live card."""
    from devkit import domains

    rows = [
        [entry["domain"], entry["runtime"], ", ".join(entry["tools"])]
        for entry in domains.catalog()
    ]
    return {
        "schema_version": "1.0",
        "root": {
            "type": "column",
            "children": [
                {"type": "heading", "text": "Domain profiles", "level": 2},
                {
                    "type": "text",
                    "text": "Call design with a domain and one sentence of brief; "
                            "the blueprint names the runtime, tools, grants, safety "
                            "rules and build order. scaffold starts the package.",
                },
                {
                    "type": "table",
                    "columns": ["Domain", "Runtime", "Tools"],
                    "rows": rows,
                },
                {"type": "button", "label": "Back", "action": "refresh"},
            ],
        },
    }


def run_self_check() -> dict:
    """Lint this very package, so the card reflects real behaviour."""
    from devkit.lint import lint

    global LAST_CHECK
    LAST_CHECK = lint(ROOT)
    return LAST_CHECK


# --- dispatch --------------------------------------------------------------


def handle_tools_call(params):
    from devkit.handlers import dispatch
    from devkit.util import DevkitError

    name = str(params.get("name") or "").rsplit("__", 1)[-1]
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ToolError("arguments must be a JSON object")
    try:
        value = dispatch(name, arguments, CONFIG, state())
    except DevkitError as error:
        raise ToolError(str(error))
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        raise ToolError("%s: %s" % (type(error).__name__, error))
    return value


def handle_command(params):
    name = str(params.get("name") or "").rsplit("__", 1)[-1]
    if name in ("refresh", "panel", ""):
        return panel_document()
    if name == "selfcheck":
        progress("linting this package")
        run_self_check()
        return panel_document()
    if name == "topics":
        return topics_document()
    if name == "domains":
        return domains_document()
    raise ToolError("unknown command %r" % name)


def handle(request):
    """Return (payload or None, keep_going)."""
    method = request.get("method")
    params = request.get("params") or {}
    request_id = request.get("id")
    if method == "initialize":
        global CONFIG
        raw = params.get("config")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                CONFIG = parsed
        elif isinstance(raw, dict):
            CONFIG = raw
        return {"result": {"protocolVersion": "1.0",
                           "token": params.get("token", ""),
                           "name": "extdev",
                           "version": VERSION}}, True
    if method == "shutdown":
        return {"result": {}}, False
    if method == "tools/call":
        try:
            return {"result": handle_tools_call(params)}, True
        except ToolError as error:
            return {"error": {"code": -32000, "message": str(error)}}, True
    if method == "commands/execute":
        try:
            return {"result": handle_command(params)}, True
        except ToolError as error:
            return {"error": {"code": -32000, "message": str(error)}}, True
    if method == "events/event":
        event = params.get("event") or {}
        if isinstance(event, dict):
            EVENTS.append({
                "topic": event.get("event_type"),
                "source": event.get("source"),
                "timestamp": event.get("timestamp"),
                "payload": event.get("payload"),
            })
            del EVENTS[:-40]
        return None, True
    if isinstance(method, str) and method.startswith("$/"):
        return None, True
    if request_id is None:
        return None, True
    return {"error": {"code": -32601, "message": "unsupported method %r" % method}}, True


def main():
    if sys.version_info < (3, 11):
        sys.stderr.write(
            "the Extension DevKit needs Python 3.11 or newer for tomllib; "
            "this interpreter is %s\n" % sys.version.split()[0]
        )
        sys.exit(1)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        if not isinstance(request, dict):
            continue
        try:
            outcome, keep_going = handle(request)
        except Exception as error:  # a bug is reported, never a silent success
            traceback.print_exc(file=sys.stderr)
            outcome = {"error": {"code": -32603,
                                 "message": "%s: %s" % (type(error).__name__, error)}}
            keep_going = True
        if outcome is not None:
            envelope = {"jsonrpc": "2.0", "id": request.get("id")}
            envelope.update(outcome)
            emit(envelope)
        if not keep_going:
            break


if __name__ == "__main__":
    main()
