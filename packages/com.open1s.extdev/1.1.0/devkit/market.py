"""The Git-backed market: hashes, index entries and the index itself.

The host installs a market entry by copying the directory the index names and
re-hashing it, so an entry that disagrees with its directory is refused at
install time. These tools make that agreement checkable before a push.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import constants
from .util import (
    DevkitError,
    check_relative_path,
    dump_json,
    fail,
    package_hash,
    read_json,
    read_text,
    resolve_new_path,
    resolve_root,
    write_text,
)

MAX_INDEX_BYTES = 4 * 1024 * 1024


def version_key(raw: str):
    """A sortable key for the semver strings the index carries."""
    core = raw.split("+", 1)[0]
    prerelease = None
    if "-" in core:
        core, prerelease = core.split("-", 1)
    parts = []
    for piece in core.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    # A release sorts after its prereleases.
    return (parts[0], parts[1], parts[2], 0 if prerelease else 1, prerelease or "")


def manifest_of(root: Path) -> dict:
    """Read the manifest of one package directory."""
    path = root / constants.MANIFEST_FILE
    if not path.is_file():
        fail("%s has no extension.toml" % root)
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        fail("reading extension.toml needs Python 3.11+ (tomllib)")
    try:
        return tomllib.loads(read_text(path, constants.MAX_MANIFEST_BYTES))
    except Exception as error:
        fail("%s does not parse: %s" % (path, error))


def make_entry(root: Path, index_path: Path) -> dict:
    """Build the index entry that names this exact package directory."""
    manifest = manifest_of(root)
    identity = manifest.get("extension") or {}
    raw_id = identity.get("id")
    version = identity.get("version")
    if not isinstance(raw_id, str) or not isinstance(version, str):
        fail("%s has no extension.id or extension.version" % root)
    entry = {
        "id": raw_id,
        "name": identity.get("name") or raw_id,
        "version": version,
        "description": identity.get("description") or "",
        "path": root.resolve().relative_to(index_path.parent.resolve()).as_posix(),
        "hash": package_hash(root),
    }
    reason = check_relative_path(entry["path"])
    if reason:
        fail("the package path cannot be indexed: %s" % reason)
    return entry


def find_repo(root: Path, explicit) -> "Path | None":
    """The market checkout: the explicit argument, the packages/<id>/<v> shape, or None."""
    if explicit:
        candidate = resolve_new_path(explicit, "repo")
        if not candidate.is_dir():
            fail("repo %s is not a directory" % candidate)
        return candidate
    if (root.parent.parent.name == "packages"
            and (root.parent.parent.parent / constants.MARKET_INDEX).is_file()):
        return root.parent.parent.parent
    return None


def conventional_entry(root: Path) -> dict:
    """The index entry for a package that is not inside a checkout yet."""
    manifest = manifest_of(root)
    identity = manifest.get("extension") or {}
    raw_id = identity.get("id")
    version = identity.get("version")
    if not isinstance(raw_id, str) or not isinstance(version, str):
        fail("%s has no extension.id or extension.version" % root)
    return {
        "id": raw_id,
        "name": identity.get("name") or raw_id,
        "version": version,
        "description": identity.get("description") or "",
        "path": "packages/%s/%s" % (raw_id, version),
        "hash": package_hash(root),
    }


def read_index(repo: Path) -> dict:
    """Read and shape-check index.json."""
    path = repo / constants.MARKET_INDEX
    if not path.is_file():
        return {"schema_version": 1, "extensions": []}
    try:
        document = read_json(path, MAX_INDEX_BYTES)
    except DevkitError as error:
        fail(str(error))
    if not isinstance(document, dict):
        fail("%s must hold a JSON object" % path)
    if document.get("schema_version") != 1:
        fail("index.json schema_version must be 1")
    entries = document.get("extensions")
    if not isinstance(entries, list):
        fail("index.json extensions must be an array")
    for entry in entries:
        if not isinstance(entry, dict):
            fail("index.json has a non-object entry")
        for key in ("id", "name", "version", "path"):
            if not isinstance(entry.get(key), str):
                fail("index.json entry is missing %s" % key)
    return document


def write_index(repo: Path, document: dict) -> Path:
    """Write index.json in the canonical shape: sorted by id, then version."""
    entries = sorted(
        document["extensions"],
        key=lambda entry: (entry["id"], version_key(entry["version"])),
    )
    document = {"schema_version": 1, "extensions": entries}
    path = repo / constants.MARKET_INDEX
    write_text(path, dump_json(document))
    return path


def market(arguments: dict, config: dict) -> dict:
    """Dispatch one market action."""
    action = str(arguments.get("action") or "entry").strip().lower()
    if action in ("add", "publish"):
        action = "merge"
    if action in ("check", "lint"):
        action = "verify"
    if action == "list":
        repo = find_repo(
            Path(arguments.get("path") or config.get("market_path") or "."),
            arguments.get("repo") or config.get("market_path") or None,
        )
        document = read_index(repo)
        return {"index": str(repo / constants.MARKET_INDEX),
                "entries": document["extensions"]}

    root = resolve_root(arguments.get("path"))
    repo = find_repo(root, arguments.get("repo") or config.get("market_path") or None)
    if repo is None and action != "entry":
        fail(
            "cannot infer the market checkout from %s; pass repo=<absolute path to "
            "the clone that holds index.json>" % root
        )

    if action == "entry":
        entry = (make_entry(root, repo / constants.MARKET_INDEX) if repo
                 else conventional_entry(root))
        return {
            "entry": entry,
            "hash": entry["hash"],
            "json": json.dumps(entry, indent=2, ensure_ascii=False),
            "command": "bsh ext market install %s" % entry["id"],
        }

    if action == "merge":
        document = read_index(repo)
        entry = make_entry(root, repo / constants.MARKET_INDEX)
        replaced = False
        for position, existing in enumerate(document["extensions"]):
            if existing["id"] == entry["id"] and existing["version"] == entry["version"]:
                document["extensions"][position] = entry
                replaced = True
                break
        if not replaced:
            document["extensions"].append(entry)
        path = write_index(repo, document)
        return {
            "index": str(path),
            "action": "updated" if replaced else "added",
            "entry": entry,
            "entries": len(document["extensions"]),
        }

    if action == "verify":
        return verify(repo)

    if action == "readme":
        return readme(repo)

    fail("unknown market action %r; use entry, merge, verify, list or readme" % action)


def verify(repo: Path) -> dict:
    """Check every index entry against the directory it names."""
    document = read_index(repo)
    problems = []
    seen_directories = set()
    for entry in document["extensions"]:
        path = repo / entry["path"]
        seen_directories.add(entry["path"])
        if not path.is_dir():
            problems.append({
                "id": entry["id"], "version": entry["version"],
                "problem": "the directory the index names does not exist: %s" % entry["path"],
            })
            continue
        try:
            manifest = manifest_of(path)
        except DevkitError as error:
            problems.append({"id": entry["id"], "version": entry["version"],
                             "problem": str(error)})
            continue
        identity = manifest.get("extension") or {}
        if identity.get("id") != entry["id"]:
            problems.append({
                "id": entry["id"], "version": entry["version"],
                "problem": "the package id is %r, not %r"
                           % (identity.get("id"), entry["id"]),
            })
        if identity.get("version") != entry["version"]:
            problems.append({
                "id": entry["id"], "version": entry["version"],
                "problem": "the package version is %r, not %r"
                           % (identity.get("version"), entry["version"]),
            })
        declared = entry.get("hash")
        if declared:
            actual = package_hash(path)
            if actual != declared:
                problems.append({
                    "id": entry["id"], "version": entry["version"],
                    "problem": "the hash is %s but the bytes hash to %s"
                               % (declared, actual),
                })
    indexed_ids = {entry["id"] for entry in document["extensions"]}
    packages = repo / "packages"
    if packages.is_dir():
        for directory in sorted(packages.iterdir()):
            if directory.name in indexed_ids:
                # Older versions stay on disk as history; only an id with no
                # entry at all is a packaging mistake.
                continue
            if not directory.is_dir():
                continue
            for version in sorted(directory.iterdir()):
                if not version.is_dir() or not (version / constants.MANIFEST_FILE).is_file():
                    continue
                relative = version.relative_to(repo).as_posix()
                if relative not in seen_directories:
                    problems.append({
                        "id": directory.name,
                        "version": version.name,
                        "problem": "the directory is not in index.json: %s" % relative,
                    })
    return {
        "ok": not problems,
        "index": str(repo / constants.MARKET_INDEX),
        "entries": len(document["extensions"]),
        "problems": problems,
    }


README_START = "<!-- market-table:start -->"
README_END = "<!-- market-table:end -->"
BT = chr(96)


def readme(repo: Path) -> dict:
    """Rewrite the package table between the README markers."""
    document = read_index(repo)
    lines = [README_START]
    lines.append("| Id | Name | Version | What it does |")
    lines.append("|---|---|---|---|")
    for entry in sorted(document["extensions"], key=lambda item: item["id"]):
        description = entry.get("description") or ""
        lines.append(
            "| %s%s%s | %s | %s | %s |"
            % (BT, entry["id"], BT, entry.get("name") or entry["id"],
               entry["version"], description.replace("|", "\\|"))
        )
    lines.append(README_END)
    block = "\n".join(lines)
    path = repo / "README.md"
    if path.is_file():
        text = read_text(path, 1024 * 1024)
        if README_START in text and README_END in text:
            head = text.split(README_START)[0]
            tail = text.split(README_END, 1)[1]
            text = head + block + tail
        else:
            text = text.rstrip() + "\n\n## Packages\n\n" + block + "\n"
    else:
        text = "# Market\n\n## Packages\n\n" + block + "\n"
    write_text(path, text)
    return {"readme": str(path), "entries": len(document["extensions"])}
