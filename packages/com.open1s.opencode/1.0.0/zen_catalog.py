"""OpenCode Zen catalog: the live free roster, with the package's baked list as
the offline fallback.

The live endpoint is https://opencode.ai/inference/v1/models. An entry is free
when both the input and the output text price are 0. The static fallback is the
provider descriptor this package ships (providers/models/zen.json) plus the
context windows measured against the live catalog on 2026-11-01.
"""

import json
import os
import time
import urllib.request
import urllib.error

DEFAULT_UPSTREAM = "https://opencode.ai/inference"
USER_AGENT = "opencode/1.18.31"


def _user_agent():
    import platform
    system = platform.system().lower() or "darwin"
    machine = platform.machine() or "arm64"
    return "%s (%s %s; node24.15.0)" % (USER_AGENT, system, machine)


# Ids the free lane can never serve (protocol mismatch), from the reference
# package's live matrix. They stay out of every roster even if /models lists them.
BLOCKLIST = frozenset(["jev-1.13-free"])

# Context windows measured against the live catalog. The provider descriptor
# cannot carry them (ModelEntry has no context field), and the static fallback
# has no wire metadata of its own.
STATIC_CONTEXT = {
    "big-pickle": 200000,
    "beam-free": 1048576,
    "flint-40b-free": 262144,
    "mimo-v2.6-flash-free": 200000,
    "nemotron-3.5-super-vl-free": 1048576,
    "nemotron-3.5-lightning-free": 262144,
    "deepseek-v4.1-flash-free": 200000,
    "glm-5.3-flash-free": 200000,
}

# A long-lived process caches the last good live answer so a transient DNS or
# proxy failure does not empty the roster the tools report.
_CACHE = {"at": 0.0, "models": [], "total": 0}


class CatalogError(Exception):
    """The live catalog could not be read."""


def _headers():
    return {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
        "x-opencode-client": "cli",
        "x-opencode-project": "global",
    }


def fetch_live(upstream=None, timeout=15):
    """Return the raw /models entries.

    Raises CatalogError when the endpoint cannot be read or its body is not the
    documented {"data": [...]} shape.
    """
    base = (upstream or os.environ.get("OPENCODE_ZEN_UPSTREAM") or DEFAULT_UPSTREAM).rstrip("/")
    url = base + "/v1/models"
    request = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise CatalogError("HTTP %s from %s: %s" % (error.code, url, detail or error.reason))
    except Exception as error:  # transport, DNS, TLS, timeout
        raise CatalogError("%s: %s" % (url, error))
    try:
        body = json.loads(payload.decode("utf-8"))
    except Exception as error:
        raise CatalogError("%s returned invalid JSON: %s" % (url, error))
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise CatalogError("%s returned no data array" % url)
    return data


def _price(entry, kind):
    cost = entry.get("cost") or {}
    text = cost.get("text") or {}
    node = text.get(kind) or {}
    value = node.get("price")
    return value if isinstance(value, (int, float)) else None


def is_free(entry):
    if not isinstance(entry, dict):
        return False
    model = str(entry.get("id") or "")
    if not model or model in BLOCKLIST:
        return False
    status = str(entry.get("status") or entry.get("lifecycle") or "").lower()
    if entry.get("deprecated") is True or status in ("deprecated", "retired", "disabled"):
        return False
    return _price(entry, "input") == 0 and _price(entry, "output") == 0


def input_types(entry):
    modalities = entry.get("modalities") or {}
    declared = modalities.get("input") or []
    kinds = ["text"]
    for kind in declared:
        if isinstance(kind, str) and (kind == "image" or kind.startswith("image/")):
            if "image" not in kinds:
                kinds.append("image")
    if not declared:
        kinds.append("image")  # undeclared stays permissive, like BSH's own rule
    return kinds


def describe(entry):
    limit = entry.get("limit") or {}
    capabilities = entry.get("capabilities") or {}
    reasoning = capabilities.get("reasoning") or {}
    return {
        "id": entry.get("id"),
        "name": entry.get("name") or entry.get("id"),
        "input_types": input_types(entry),
        "max_tokens": limit.get("output"),
        "context_window": limit.get("context"),
        "reasoning": bool(reasoning.get("supported")),
        "free": is_free(entry),
        "input_price": _price(entry, "input"),
        "output_price": _price(entry, "output"),
    }


def static_models():
    """The package's own roster, used when the live endpoint is unreachable."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers", "models", "zen.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            provider = json.load(handle)
    except Exception:
        return []
    models = []
    for nickname, leaf in provider.items():
        if not isinstance(leaf, dict) or not leaf.get("model"):
            continue
        model = leaf["model"]
        models.append(
            {
                "id": model,
                "name": leaf.get("name") or model,
                "input_types": leaf.get("input_types") or ["text", "image"],
                "max_tokens": leaf.get("max_tokens"),
                "context_window": STATIC_CONTEXT.get(model),
                "reasoning": True,
                "free": True,
                "input_price": 0,
                "output_price": 0,
            }
        )
    models.sort(key=lambda item: item["id"] or "")
    return models


def load(upstream=None, include_paid=False, timeout=15):
    """Load the roster through the live endpoint, then the package fallback.

    Returns a dict with source, checked_at, total, free, paid and error. A live
    failure is reported in error even when the static roster answers, so a
    caller can tell a stale list from a fresh one.
    """
    error = ""
    try:
        raw = fetch_live(upstream=upstream, timeout=timeout)
        free = [describe(entry) for entry in raw if is_free(entry)]
        if free:
            _CACHE["at"] = time.time()
            _CACHE["models"] = free
            _CACHE["total"] = len(raw)
            result = {
                "source": "live",
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "total": len(raw),
                "free": free,
                "error": "",
            }
            if include_paid:
                result["paid"] = [
                    describe(entry)
                    for entry in raw
                    if isinstance(entry, dict) and not is_free(entry)
                ]
            return result
        error = "the live catalog listed no free model"
    except CatalogError as failure:
        error = str(failure)

    if _CACHE["models"]:
        result = {
            "source": "cache",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_CACHE["at"])),
            "total": _CACHE["total"],
            "free": _CACHE["models"],
            "error": error,
        }
    else:
        result = {
            "source": "static",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total": len(static_models()),
            "free": static_models(),
            "error": error,
        }
    if include_paid:
        result["paid"] = []
    return result
