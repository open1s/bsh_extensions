#!/usr/bin/env python3
"""Regenerate providers/models/zen.json from the live OpenCode Zen catalog.

Usage:
    python3 scripts/refresh_provider.py            rewrite the descriptor
    python3 scripts/refresh_provider.py --check    exit 1 when it is stale

The descriptor is the BSH model-provider document: name, base_url, api_mode,
requires_key and one flattened entry per model. It has no context field, so
context windows live in zen_catalog.STATIC_CONTEXT; this script prints the ids
whose window changed so that table can be kept honest too.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import zen_catalog  # noqa: E402

DESCRIPTOR = os.path.join(ROOT, "providers", "models", "zen.json")
BASE_URL = "http://127.0.0.1:18765/v1"


def desired():
    live = zen_catalog.fetch_live()
    entries = []
    contexts = {}
    for entry in live:
        if not zen_catalog.is_free(entry):
            continue
        model = zen_catalog.describe(entry)
        entries.append(
            (
                model["id"],
                {
                    "model": model["id"],
                    "name": model["name"],
                    "max_tokens": model["max_tokens"],
                    "input_types": [kind for kind in model["input_types"] if kind in ("text", "image")],
                },
            )
        )
        contexts[model["id"]] = model["context_window"]
    provider = {
        "name": "OpenCode Zen",
        "base_url": BASE_URL,
        "api_mode": "chat",
        "requires_key": False,
    }
    for model, leaf in sorted(entries):
        provider[model] = leaf
    return provider, contexts


def main():
    check = "--check" in sys.argv[1:]
    provider, contexts = desired()
    if check:
        try:
            with open(DESCRIPTOR, "r", encoding="utf-8") as handle:
                current = json.load(handle)
        except Exception as error:
            print("cannot read %s: %s" % (DESCRIPTOR, error))
            return 1
        if current != provider:
            print("providers/models/zen.json is stale; run scripts/refresh_provider.py")
            return 1
        print("providers/models/zen.json matches the live catalog (%d free models)" % (len(provider) - 4))
        return 0
    with open(DESCRIPTOR, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(provider, indent=2) + "\n")
    print("wrote %s (%d free models)" % (DESCRIPTOR, len(provider) - 4))
    for model, window in sorted(contexts.items()):
        if zen_catalog.STATIC_CONTEXT.get(model) != window:
            print("context window drift: %s -> %s" % (model, window))
    return 0


if __name__ == "__main__":
    sys.exit(main())
