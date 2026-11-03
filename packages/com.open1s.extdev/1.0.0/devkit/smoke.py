"""A local dry run: declared tools, called once, without the host.

Declarative packages are executed exactly as the host executes them (the three
pure bodies). Process packages are started the way the host starts them
(initialize with a token, then one call per tool) and stopped again. The
report says what worked and what refused, never that something "probably"
works.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import constants
from .util import fail, read_json, read_text
from .validate import validate

MAX_PREVIEW = 400
MAX_STDERR_LINES = 40


def smoke(root: Path, config: dict, tool=None, arguments=None) -> dict:
    """Run one package's declared tools locally."""
    report = validate(root)
    if not report["ok"]:
        return {
            "ok": False,
            "reason": "the package does not validate, so nothing was run",
            "errors": [
                finding["message"] for finding in report["findings"]
                if finding["severity"] == "error"
            ],
        }
    if tool is not None:
        declared = {entry["id"] for entry in report["declared"] if entry["kind"] == "tool"}
        if tool not in declared:
            fail("%r is not a declared tool of this package (%s)"
                 % (tool, ", ".join(sorted(declared)) or "none"))
    timeout_ms = _timeout(config)
    if report["runtime"] == "declarative":
        return _smoke_declarative(root, report, tool, arguments)
    if report["runtime"] == "process":
        return _smoke_process(root, report, tool, arguments, timeout_ms)
    return {
        "ok": False,
        "runtime": report["runtime"],
        "reason": "this runtime cannot be smoke-tested locally; use bsh ext mock",
    }


def _timeout(config: dict) -> int:
    raw = config.get("smoke_timeout_ms", 5000)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 5000
    return max(500, min(value, 30000))


def _tools(root: Path, report: dict):
    """The declared tool descriptors, in declaration order."""
    tools = []
    for entry in report["declared"]:
        if entry["kind"] != "tool" or not entry.get("file"):
            continue
        descriptor = read_json(root / entry["file"])
        tools.append((entry["id"], descriptor))
    return tools


def _preview(value) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= MAX_PREVIEW else text[: MAX_PREVIEW - 3] + "..."


def _smoke_declarative(root: Path, report: dict, selected, arguments) -> dict:
    declared_arguments = arguments if isinstance(arguments, dict) else {}
    ceiling = _output_ceiling(root)
    results = []
    for tool_id, descriptor in _tools(root, report):
        if selected is not None and tool_id != selected:
            continue
        if selected is None and _required(descriptor):
            results.append({
                "tool": tool_id,
                "status": "skipped",
                "reason": "the input schema requires arguments; pass tool and arguments",
            })
            continue
        started = time.time()
        try:
            value = _run_implementation(
                descriptor.get("implementation"),
                declared_arguments if selected is not None else {},
            )
            encoded = len(json.dumps(value).encode("utf-8"))
            if encoded > ceiling:
                raise RuntimeError(
                    "output is %d bytes, above resources.max_output_bytes %d"
                    % (encoded, ceiling)
                )
            results.append({
                "tool": tool_id,
                "status": "ok",
                "duration_ms": round((time.time() - started) * 1000, 1),
                "output": _preview(value),
            })
        except Exception as error:
            results.append({
                "tool": tool_id,
                "status": "error",
                "duration_ms": round((time.time() - started) * 1000, 1),
                "error": str(error),
            })
    ok = all(item["status"] in ("ok", "skipped") for item in results)
    return {
        "ok": ok and bool(results),
        "runtime": "declarative",
        "tools": results,
        "note": "executed exactly as the host's declarative runtime does",
    }


def _required(descriptor: dict) -> "list[str]":
    schema = descriptor.get("input_schema")
    if not isinstance(schema, dict):
        return []
    required = schema.get("required")
    return required if isinstance(required, list) else []


def _output_ceiling(root: Path) -> int:
    manifest = _manifest(root)
    resources = manifest.get("resources") or {}
    value = resources.get("max_output_bytes")
    if isinstance(value, int) and value > 0:
        return min(value, constants.HARD_MAX_OUTPUT_BYTES)
    return constants.DEFAULT_OUTPUT_BYTES


def _manifest(root: Path) -> dict:
    import tomllib

    return tomllib.loads(read_text(root / constants.MANIFEST_FILE))


def _run_implementation(implementation, arguments):
    if not isinstance(implementation, dict):
        raise RuntimeError("the tool has no declarative implementation")
    kind = implementation.get("kind")
    if kind == "echo_arguments":
        return arguments
    if kind == "constant":
        return implementation.get("value")
    if kind == "template":
        return render_template(str(implementation.get("text") or ""), arguments)
    raise RuntimeError("unknown implementation %r" % kind)


def render_template(template: str, arguments) -> str:
    """The host's top-level placeholder rule: missing renders empty."""
    output = []
    rest = template
    while "{{" in rest:
        start = rest.index("{{")
        output.append(rest[:start])
        after = rest[start + 2:]
        if "}}" not in after:
            output.append(rest[start:])
            return "".join(output)
        end = after.index("}}")
        key = after[:end].strip()
        value = arguments.get(key) if isinstance(arguments, dict) else None
        if isinstance(value, str):
            output.append(value)
        elif value is not None:
            output.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        rest = after[end + 2:]
    output.append(rest)
    return "".join(output)


class _Reader:
    """A line reader on a background thread, so reads can time out."""

    def __init__(self, stream):
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._pump, args=(stream,), daemon=True)
        self.thread.start()

    def _pump(self, stream):
        try:
            for line in stream:
                self.queue.put(line)
        except Exception:
            pass
        finally:
            self.queue.put(None)

    def line(self, deadline: float):
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError("the process did not answer in time")
        try:
            value = self.queue.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError("the process did not answer in time")
        if value is None:
            raise RuntimeError("the process closed stdout")
        return value


def _smoke_process(root: Path, report: dict, selected, arguments, timeout_ms) -> dict:
    manifest = _manifest(root)
    runtime = manifest.get("runtime") or {}
    config = runtime.get("config") or {}
    entry = config.get("entry")
    args = config.get("args") or []
    if not isinstance(entry, str):
        fail("the process runtime has no entry")
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
        if key in os.environ
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for key, value in (config.get("env") or {}).items():
        environment[str(key)] = str(value)
    command = [entry] + [str(argument) for argument in args]
    token = str(uuid.uuid4())
    started = time.time()
    stderr_lines = []

    try:
        child = subprocess.Popen(
            command,
            cwd=str(root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=environment,
        )
    except OSError as error:
        return {"ok": False, "runtime": "process",
                "reason": "could not start %s: %s" % (" ".join(command), error)}

    def drain():
        try:
            for line in child.stderr:
                stderr_lines.append(line.rstrip())
                if len(stderr_lines) > MAX_STDERR_LINES:
                    del stderr_lines[0]
        except Exception:
            pass

    threading.Thread(target=drain, daemon=True).start()
    reader = _Reader(child.stdout)
    protocol = {}
    results = []

    def send(payload):
        child.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        child.stdin.flush()

    def request(request_id, method, params, deadline):
        send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        noise = 0
        while True:
            line = reader.line(deadline).strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                noise += 1
                continue
            if not isinstance(message, dict):
                noise += 1
                continue
            if "id" not in message:
                continue
            if message.get("id") != request_id:
                noise += 1
                continue
            return message, noise

    try:
        deadline = time.time() + timeout_ms / 1000.0
        message, noise = request(
            1,
            "initialize",
            {
                "protocolVersion": "1.0",
                "extensionId": report.get("id"),
                "host": {"name": "extdev", "version": "1.0.0"},
                "config": json.dumps(manifest.get("configuration", {}).get("defaults") or {}),
                "token": token,
            },
            deadline,
        )
        result = message.get("result") or {}
        protocol = {
            "protocolVersion": result.get("protocolVersion"),
            "token_echoed": result.get("token") == token,
            "stdout_noise": noise,
        }
        if not str(result.get("protocolVersion") or "").startswith("1."):
            return {
                "ok": False,
                "runtime": "process",
                "protocol": protocol,
                "reason": "initialize did not answer protocolVersion 1.x",
                "stderr": stderr_lines,
            }
        if result.get("token") != token:
            return {
                "ok": False,
                "runtime": "process",
                "protocol": protocol,
                "reason": "initialize did not echo the handshake token",
                "stderr": stderr_lines,
            }
        next_id = 2
        for tool_id, descriptor in _tools(root, report):
            if selected is not None and tool_id != selected:
                continue
            if selected is None and _required(descriptor):
                results.append({
                    "tool": tool_id,
                    "status": "skipped",
                    "reason": "the input schema requires arguments; pass tool and arguments",
                })
                continue
            call_arguments = (
                arguments
                if selected is not None and isinstance(arguments, dict)
                else {}
            )
            call_started = time.time()
            call_deadline = time.time() + timeout_ms / 1000.0
            try:
                answer, noise = request(
                    next_id, "tools/call",
                    {"name": tool_id, "arguments": call_arguments}, call_deadline)
            except (TimeoutError, RuntimeError) as error:
                results.append({"tool": tool_id, "status": "error",
                                "duration_ms": round((time.time() - call_started) * 1000, 1),
                                "error": str(error)})
                next_id += 1
                break
            next_id += 1
            if "error" in answer:
                results.append({
                    "tool": tool_id,
                    "status": "error",
                    "duration_ms": round((time.time() - call_started) * 1000, 1),
                    "error": str((answer.get("error") or {}).get("message")),
                })
            else:
                results.append({
                    "tool": tool_id,
                    "status": "ok",
                    "duration_ms": round((time.time() - call_started) * 1000, 1),
                    "output": _preview(answer.get("result")),
                })
        try:
            send({"jsonrpc": "2.0", "id": next_id, "method": "shutdown", "params": {}})
            reader.line(time.time() + 1.0)
        except Exception:
            pass
    finally:
        try:
            child.stdin.close()
        except Exception:
            pass
        try:
            child.terminate()
            child.wait(timeout=2)
        except Exception:
            try:
                child.kill()
            except Exception:
                pass
        for stream in (child.stdout, child.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

    ok = bool(results) and all(item["status"] in ("ok", "skipped") for item in results)
    return {
        "ok": ok,
        "runtime": "process",
        "protocol": protocol,
        "tools": results,
        "stderr": stderr_lines,
        "duration_ms": round((time.time() - started) * 1000, 1),
        "note": "the package ran inside the extension's sandbox; review code before "
                "smoke-testing a package you do not trust",
    }
