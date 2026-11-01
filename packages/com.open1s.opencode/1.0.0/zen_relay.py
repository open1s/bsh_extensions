"""A loopback OpenAI-compatible relay in front of OpenCode Zen's free lane.

BSH's provider descriptor can name an endpoint and a model list, but it cannot
carry the wire shape the anonymous lane requires: a canonical OpenCode session
id, the CLI header set, and an agent-shaped tool list containing bash and read.
This relay adds that shape and forwards the request; it is the BSH counterpart
of the reference package's adapter mode.

The shaping rules are a port of the reference package's live measurements
(https://github.com/FishBottle7/opencode2dsh):

* a canonical ses_ id whose low 12 bits decode to a counter in [0, 63];
* the CLI header set, with x-opencode-project fixed to global;
* a streaming body;
* bash and read present in the tools array with non-empty schemas.
"""

import hashlib
import http.server
import json
import os
import platform
import threading
import time
import urllib.error
import urllib.request

DEFAULT_PORT = 18765
DEFAULT_UPSTREAM = "https://opencode.ai/inference"
DEFAULT_TIMEOUT = 300

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# A wire name BSH sends that must reach upstream under the gate's spelling.
# read_file -> read satisfies the gate and is mapped back on the way out.
WIRE_RENAMES = {"read_file": "read"}

GATE_TOOLS = {
    "bash": {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command in the project workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run."},
                    "description": {"type": "string", "description": "What the command does."},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    "read": {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a file from the filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filePath": {"type": "string", "description": "Absolute path of the file to read."},
                    "offset": {"type": "integer", "description": "Line number to start reading from."},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read."},
                },
                "required": ["filePath"],
                "additionalProperties": False,
            },
        },
    },
}


def user_agent():
    system = (platform.system() or "darwin").lower()
    machine = platform.machine() or "arm64"
    return "opencode/1.18.31 (%s %s; node24.15.0)" % (system, machine)


def inverted_timestamp_hex(now_ms=None):
    """The 12 hex characters a genuine OpenCode client puts in a session id."""
    current = int(now_ms if now_ms is not None else time.time() * 1000) * 0x1000 + 1
    return format((~current) & 0xFFFFFFFFFFFF, "012x")


def _base62(value, width):
    out = ["0"] * width
    for index in range(width - 1, -1, -1):
        out[index] = BASE62[value % 62]
        value //= 62
    return "".join(out)


def canonical_session(signal):
    """A canonical ses_ id with the conversation folded into the Base62 tail."""
    digest = hashlib.sha256(b"ses\x00" + signal.encode("utf-8", "replace")).digest()
    tail = _base62(int.from_bytes(digest[6:16], "big"), 14)
    return "ses_" + inverted_timestamp_hex() + tail


def conversation_signal(messages):
    for message in messages or []:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        encoded = json.dumps(message.get("content"), separators=(",", ":"), ensure_ascii=False)
        if encoded and encoded != "null":
            return encoded
    return "fallback:" + str(time.time_ns())


def disguise_headers(session):
    return {
        "user-agent": user_agent(),
        "x-opencode-client": "cli",
        "x-opencode-session": session,
        "x-opencode-session-id": session,
        "x-session-affinity": session,
        "X-Session-Id": session,
        "x-opencode-project": "global",
        "authorization": "Bearer public",
        "accept": "text/event-stream",
    }


def _gate_ok(tool, name):
    if not isinstance(tool, dict):
        return False
    function = tool.get("function")
    if not isinstance(function, dict) or function.get("name") != name:
        return False
    parameters = function.get("parameters")
    properties = parameters.get("properties") if isinstance(parameters, dict) else None
    return isinstance(properties, dict) and bool(properties)


def shape_chat_body(payload):
    """Rewrite one chat-completions body for the free lane.

    Returns (body, aliases, injected) where aliases maps a wire tool name back
    to the name the host knows, and injected lists the gate stubs added.
    """
    body = dict(payload) if isinstance(payload, dict) else {}
    original = body.get("tools")
    tools = list(original) if isinstance(original, list) else []
    aliases = {}
    shaped = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        wire = WIRE_RENAMES.get(name)
        if wire and _gate_ok(tool, name):
            renamed = dict(function)
            renamed["name"] = wire
            replacement = dict(tool)
            replacement["function"] = renamed
            shaped.append(replacement)
            aliases[wire] = name
        else:
            shaped.append(tool)

    missing = [name for name in ("bash", "read") if not any(_gate_ok(tool, name) for tool in shaped)]
    if missing:
        # An empty-schema shell of a gate name does not satisfy the gate: it is
        # replaced, never trusted.
        shaped = [
            tool
            for tool in shaped
            if (tool.get("function") or {}).get("name") not in missing
        ]
    shaped.extend(GATE_TOOLS[name] for name in missing)
    body["tools"] = shaped
    if not original:
        body["tool_choice"] = "none"
    body["stream"] = True
    return body, aliases, missing


def _map_name(name, aliases):
    return aliases.get(name, name)


def rewrite_event(line, aliases):
    """Map a replayed tool name back inside one SSE line; other lines pass."""
    if not line.startswith(b"data:"):
        return line
    data = line[5:].strip()
    if not data or data == b"[DONE]":
        return line
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        return line
    changed = False
    for choice in payload.get("choices") or []:
        for key in ("delta", "message"):
            block = choice.get(key)
            if not isinstance(block, dict):
                continue
            for call in block.get("tool_calls") or []:
                function = call.get("function") if isinstance(call, dict) else None
                if isinstance(function, dict) and function.get("name") in aliases:
                    function["name"] = _map_name(function["name"], aliases)
                    changed = True
    if not changed:
        return line
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return b"data: " + encoded + b"\n"


def aggregate_stream(lines, aliases):
    """Fold an SSE stream into one chat.completion for a non-streaming caller."""
    content = []
    reasoning = []
    calls = {}
    finish = None
    usage = None
    meta = {}
    for line in lines:
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if not data or data == b"[DONE]":
            if data == b"[DONE]":
                break
            continue
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            continue
        for key in ("id", "model", "created"):
            if meta.get(key) is None and payload.get(key) is not None:
                meta[key] = payload[key]
        if payload.get("usage"):
            usage = payload["usage"]
        for choice in payload.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            if delta.get("content"):
                content.append(delta["content"])
            if delta.get("reasoning_content"):
                reasoning.append(delta["reasoning_content"])
            for call in delta.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                index = call.get("index", 0)
                slot = calls.setdefault(
                    index, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}
                )
                if call.get("id"):
                    slot["id"] = call["id"]
                function = call.get("function") or {}
                if function.get("name"):
                    slot["function"]["name"] = _map_name(function["name"], aliases)
                if function.get("arguments"):
                    slot["function"]["arguments"] += function["arguments"]
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    message = {"role": "assistant", "content": "".join(content) if content else None}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if calls:
        message["tool_calls"] = [calls[index] for index in sorted(calls)]
        if message["content"] is None:
            message["content"] = ""
    response = {
        "id": meta.get("id") or "chatcmpl-opencode-relay",
        "object": "chat.completion",
        "created": meta.get("created") or int(time.time()),
        "model": meta.get("model") or "",
        "choices": [{"index": 0, "message": message, "finish_reason": finish or "stop"}],
    }
    if usage:
        response["usage"] = usage
    return response


class Relay:
    """One loopback relay, started and stopped by the extension process."""

    def __init__(self, port=DEFAULT_PORT, upstream=None, timeout=DEFAULT_TIMEOUT):
        self.port = int(port)
        self.upstream = (upstream or os.environ.get("OPENCODE_ZEN_UPSTREAM") or DEFAULT_UPSTREAM).rstrip("/")
        self.timeout = timeout
        self.started_at = None
        self.requests = 0
        self.failures = 0
        self.last_error = ""
        self.last_status = 0
        self._memo = {}
        self._server = None
        self._thread = None

    @property
    def running(self):
        return self._server is not None

    def start(self):
        if self._server is not None:
            return self.status()
        handler = _handler_for(self)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        server.daemon_threads = True
        self._server = server
        self.port = server.server_address[1]
        self.started_at = time.time()
        self._thread = threading.Thread(target=server.serve_forever, name="opencode-relay", daemon=True)
        self._thread.start()
        return self.status()

    def stop(self):
        server = self._server
        if server is None:
            return self.status()
        self._server = None
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        self._thread = None
        return self.status()

    def session_for(self, messages):
        signal = conversation_signal(messages)
        session = self._memo.get(signal)
        if session is None:
            session = canonical_session(signal)
            if len(self._memo) >= 1024:
                self._memo.pop(next(iter(self._memo)))
            self._memo[signal] = session
        return session

    def note_error(self, message, status=0):
        self.last_error = str(message)[:800]
        self.last_status = status
        self.failures += 1

    def status(self):
        return {
            "running": self.running,
            "port": self.port,
            "base_url": "http://127.0.0.1:%d/v1" % self.port,
            "upstream": self.upstream,
            "started_at": self.started_at,
            "uptime_seconds": round(time.time() - self.started_at, 1) if self.started_at else 0,
            "requests": self.requests,
            "failures": self.failures,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "sessions": len(self._memo),
        }


def _handler_for(relay):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "opencode-relay/1.0"

        def log_message(self, fmt, *args):
            # stderr is the extension's diagnostic channel; stdout is JSON-RPC.
            import sys
            sys.stderr.write("opencode-relay: " + (fmt % args) + "\n")
            sys.stderr.flush()

        def _json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def _error(self, status, message):
            self._json(status, {"type": "error", "error": {"type": "relay_error", "message": message}})

        def do_GET(self):
            route = self.path.split("?", 1)[0]
            if route in ("/health", "/v1/health"):
                self._json(200, relay.status())
                return
            if route in ("/v1/models", "/models"):
                self._proxy_models()
                return
            self._error(404, "unknown path " + route)

        def do_POST(self):
            route = self.path.split("?", 1)[0]
            if route not in ("/v1/chat/completions", "/chat/completions"):
                self._error(404, "unknown path " + route)
                return
            self._chat()

        def _read_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        def _proxy_models(self):
            request = urllib.request.Request(relay.upstream + "/v1/models", headers=disguise_headers(canonical_session("models:" + str(time.time_ns()))))
            try:
                with urllib.request.urlopen(request, timeout=20) as upstream:
                    body = upstream.read()
                    self.send_response(upstream.status)
                    self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                    self.close_connection = True
            except urllib.error.HTTPError as error:
                body = error.read()
                self.send_response(error.code)
                self.send_header("Content-Type", error.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True
            except Exception as error:
                relay.note_error(str(error))
                self._error(502, "the upstream catalog could not be reached: %s" % error)

        def _chat(self):
            try:
                payload = json.loads(self._read_body().decode("utf-8"))
            except Exception as error:
                self._error(400, "invalid JSON request body: %s" % error)
                return
            want_stream = bool(payload.get("stream"))
            messages = payload.get("messages") or []
            body, aliases, injected = shape_chat_body(payload)
            session = relay.session_for(messages)
            headers = disguise_headers(session)
            headers["content-type"] = "application/json"
            request = urllib.request.Request(
                relay.upstream + "/v1/chat/completions",
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            relay.requests += 1
            try:
                upstream = urllib.request.urlopen(request, timeout=relay.timeout)
            except urllib.error.HTTPError as error:
                detail = error.read()
                relay.note_error(detail.decode("utf-8", "replace")[:400], error.code)
                self.send_response(error.code)
                self.send_header("Content-Type", error.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(detail)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(detail)
                self.close_connection = True
                return
            except Exception as error:
                relay.note_error(str(error))
                self._error(502, "the OpenCode Zen lane could not be reached: %s" % error)
                return

            try:
                if not want_stream:
                    response = aggregate_stream(upstream, aliases)
                    relay.last_status = 200
                    self._json(200, response)
                    return
                content_type = upstream.headers.get("Content-Type", "text/event-stream")
                if "text/event-stream" not in content_type:
                    response = aggregate_stream(upstream, aliases)
                    self._json(200, response)
                    return
                self.send_response(upstream.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                relay.last_status = 200
                for line in upstream:
                    self.wfile.write(rewrite_event(line, aliases))
                    self.wfile.flush()
            except Exception as error:
                relay.note_error(str(error))
                try:
                    self._error(502, "streaming failed: %s" % error)
                except Exception:
                    pass
            finally:
                try:
                    upstream.close()
                except Exception:
                    pass
                self.close_connection = True

    return Handler
