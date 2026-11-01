"""JSON-RPC process runtime for the OpenCode Zen extension.

The host spawns this once and keeps it: the relay thread started by
opencode__relay_start stays up between tool calls, so BSH's contributed provider
(which points at the loopback port) keeps answering.
"""

import json
import sys
import traceback

import zen_catalog
from zen_relay import DEFAULT_PORT, Relay

EXTENSION_ID = "com.open1s.opencode"
PROVIDER_ID = "ext." + EXTENSION_ID + ".zen"

RELAY = Relay()


def _provider_hint():
    return {
        "extension_id": EXTENSION_ID,
        "provider_id": PROVIDER_ID,
        "provider_name": "OpenCode Zen",
        "base_url": "http://127.0.0.1:%d/v1" % DEFAULT_PORT,
        "credential": "none; the relay supplies the public credential the lane expects",
    }


def tool_relay_start(arguments):
    port = arguments.get("port") or DEFAULT_PORT
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError("port must be an integer")
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    if RELAY.running and RELAY.port != port:
        return {
            "ok": False,
            "error": "the relay already listens on port %d; stop it before moving it" % RELAY.port,
            "status": RELAY.status(),
            "provider": _provider_hint(),
        }
    if not RELAY.running:
        RELAY.port = port
        RELAY.start()
    status = RELAY.status()
    return {
        "ok": True,
        "status": status,
        "provider": _provider_hint(),
        "next": [
            "select the provider \"OpenCode Zen\" in the model picker",
            "pick a free model such as deepseek-v4.1-flash-free",
        ],
    }


def tool_relay_stop(arguments):
    del arguments
    return {"ok": True, "status": RELAY.stop()}


def tool_status(arguments):
    check = arguments.get("check", True)
    payload = {"ok": True, "relay": RELAY.status(), "provider": _provider_hint()}
    if check:
        catalog = zen_catalog.load(include_paid=False, timeout=8)
        payload["upstream"] = {
            "source": catalog["source"],
            "free": len(catalog["free"]),
            "total": catalog["total"],
            "checked_at": catalog["checked_at"],
            "error": catalog["error"],
        }
    if not RELAY.running:
        payload["hint"] = "the relay is not running; call opencode__relay_start before selecting an OpenCode Zen model"
    return payload


def tool_models(arguments):
    catalog = zen_catalog.load(include_paid=bool(arguments.get("include_paid")), timeout=15)
    return catalog


TOOLS = {
    "relay_start": tool_relay_start,
    "relay_stop": tool_relay_stop,
    "status": tool_status,
    "models": tool_models,
}


def _emit(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _reply(request_id, result):
    _emit({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id, code, message):
    _emit({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _tool_name(raw):
    name = str(raw or "")
    if "__" in name:
        name = name.rsplit("__", 1)[-1]
    return name


def handle(request):
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}
    if method == "initialize":
        return _reply(request_id, {"protocolVersion": "1.0", "token": params.get("token", "")}), True
    if method == "shutdown":
        RELAY.stop()
        _reply(request_id, {})
        return None, False
    if method == "tools/call":
        name = _tool_name(params.get("name"))
        handler = TOOLS.get(name)
        if handler is None:
            _error(request_id, -32601, "unknown tool %r" % name)
            return None, True
        try:
            result = handler(params.get("arguments") or {})
        except ValueError as error:
            _error(request_id, -32602, str(error))
            return None, True
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            _error(request_id, -32000, "%s: %s" % (type(error).__name__, error))
            return None, True
        _reply(request_id, result)
        return None, True
    if method and method.startswith("$/progress"):
        return None, True
    _error(request_id, -32601, "unsupported method %r" % method)
    return None, True


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception:
            _error(None, -32700, "invalid JSON")
            continue
        if not isinstance(request, dict):
            _error(None, -32600, "invalid request")
            continue
        _, keep_going = handle(request)
        if not keep_going:
            break


if __name__ == "__main__":
    try:
        main()
    finally:
        RELAY.stop()
