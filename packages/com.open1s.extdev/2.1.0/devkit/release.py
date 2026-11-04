"""Release chores: version bump, deterministic archive, 1.x migration."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

from . import constants
from .util import (
    check_version,
    fail,
    package_hash,
    resolve_root,
    utc_stamp,
    walk_files,
    write_text,
)
from .validate import validate


def bump(arguments: dict) -> dict:
    """Raise the version in extension.toml and open a changelog entry."""
    root = resolve_root(arguments.get("path"))
    release = str(arguments.get("release") or "patch").strip().lower()
    path = root / constants.MANIFEST_FILE
    text = path.read_text(encoding="utf-8")
    current = _manifest_version(text)
    if current is None:
        fail("extension.toml has no [extension] version field")
    if release in ("major", "minor", "patch"):
        major, minor, patch = _split_version(current)
        if release == "major":
            target = "%d.0.0" % (major + 1)
        elif release == "minor":
            target = "%d.%d.0" % (major, minor + 1)
        else:
            target = "%d.%d.%d" % (major, minor, patch + 1)
    else:
        target = release
        reason = check_version(target)
        if reason:
            fail("release must be major, minor, patch or a semantic version: %s" % reason)
        if target == current:
            fail("the package is already at %s" % current)
    if _split_version(target) < _split_version(current):
        fail(
            "bump would downgrade the version from %s to %s; bump only raises "
            "the version, edit extension.toml by hand to move backwards"
            % (current, target)
        )
    updated = _replace_version(text, target)
    if updated is None:
        fail("could not find the version line inside [extension]")
    write_text(path, updated)

    changelog_path = root / "CHANGELOG.md"
    entry = "## %s - %s\n\n- Release %s.\n" % (target, utc_stamp(), target)
    if changelog_path.is_file():
        changelog = changelog_path.read_text(encoding="utf-8")
        if changelog.startswith("# Changelog"):
            _, _, tail = changelog.partition("\n")
            rest = tail.lstrip("\n")
            changelog = "# Changelog\n\n" + entry + ("\n" + rest if rest else "")
        else:
            changelog = "# Changelog\n\n" + entry + "\n" + changelog
    else:
        changelog = "# Changelog\n\n" + entry
    write_text(changelog_path, changelog)
    return {
        "path": str(root),
        "from": current,
        "to": target,
        "manifest": str(path),
        "changelog": str(changelog_path),
        "next": ["edit CHANGELOG.md", "validate %s" % root,
                 "market %s action=merge" % root],
    }


def _split_version(raw: str):
    core = raw.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        fail("%r is not a semantic version" % raw)


def _manifest_version(text: str):
    block = _extension_block(text)
    if block is None:
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', block, re.MULTILINE)
    return match.group(1) if match else None


def _extension_block(text: str):
    start = text.find("[extension]")
    if start == -1:
        return None
    rest = text[start + len("[extension]"):]
    match = re.search(r"^\[", rest, re.MULTILINE)
    end = start + len("[extension]") + (match.start() if match else len(rest))
    return text[start:end]


def _replace_version(text: str, version: str):
    start = text.find("[extension]")
    if start == -1:
        return None
    rest = text[start + len("[extension]"):]
    match = re.search(r"^\[", rest, re.MULTILINE)
    end = start + len("[extension]") + (match.start() if match else len(rest))
    block = text[start:end]
    replaced, count = re.subn(
        r'^version\s*=\s*"[^"]*"',
        'version = "%s"' % version,
        block,
        count=1,
        flags=re.MULTILINE,
    )
    if count == 0:
        return None
    return text[:start] + replaced + text[end:]


def package(arguments: dict) -> dict:
    """Build a deterministic .tar.gz and report both digests."""
    root = resolve_root(arguments.get("path"))
    report = validate(root)
    if not report["ok"]:
        errors = [
            finding["message"] for finding in report["findings"]
            if finding["severity"] == "error"
        ]
        fail("the package does not validate: " + "; ".join(errors[:5]))
    out = arguments.get("out")
    if out:
        destination = Path(str(out)).expanduser()
        if not destination.is_absolute():
            fail("out must be an absolute directory")
    else:
        destination = root.parent
    resolved = destination.resolve()
    if resolved == root.resolve() or root.resolve() in resolved.parents:
        fail(
            "out %s is inside the package; the archive would be hashed with it and "
            "change the package hash. Pass an out directory outside the package."
            % destination
        )
    destination.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    identity = report.get("id")
    version = report.get("version")
    archive = destination / ("%s-%s.tar.gz" % (identity, version))
    files = walk_files(root)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as gzip_stream:
        with tarfile.open(fileobj=gzip_stream, mode="w", format=tarfile.PAX_FORMAT) as tar:
            directories = set()
            for relative in files:
                parent = Path(relative).parent.as_posix()
                while parent and parent != ".":
                    directories.add(parent)
                    parent = Path(parent).parent.as_posix()
            for directory in sorted(directories):
                info = tarfile.TarInfo(directory)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info)
            for relative in files:
                data = (root / relative).read_bytes()
                info = tarfile.TarInfo(relative)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(data))
    payload = buffer.getvalue()
    archive.write_bytes(payload)
    hashed_build = sorted(
        relative for relative in files
        if any(part in constants.BUILD_DIRECTORIES
               for part in Path(relative).parts[:-1])
        or relative.endswith(".tar.gz")
    )
    report = {
        "archive": str(archive),
        "bytes": len(payload),
        "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "package_hash": package_hash(root),
        "files": len(files),
    }
    if hashed_build:
        report["hashed_build_output"] = hashed_build
        report["note"] = (
            "%d hashed path(s) look like build output; delete them and rebuild, "
            "or the package hash depends on who ran the tests" % len(hashed_build)
        )
    return report


CONTRIBUTION_GROUPS = (
    ("tool", "tools"),
    ("command", "commands"),
    ("panel", "panels"),
    ("prompt", "prompts"),
    ("context", "contexts"),
    ("skill", "skills"),
    ("workflow", "workflows"),
    ("language", "languages"),
    ("integration", "integrations"),
    ("model-provider", "model_providers"),
    ("agent-provider", "agent_providers"),
    ("theme", "themes"),
    ("preset", "presets"),
    ("event.subscribe", "events"),
    ("event.publish", "publishes"),
    ("hook", "hooks"),
)


def migrate(arguments: dict) -> dict:
    """Rewrite a 1.x manifest as the 2.0 envelope."""
    root = resolve_root(arguments.get("path"))
    path = root / constants.MANIFEST_FILE
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        fail("reading extension.toml needs Python 3.11+ (tomllib)")
    try:
        legacy = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        fail("%s does not parse: %s" % (path, error))
    if legacy.get("schema_version") == constants.SCHEMA_VERSION:
        return {"migrated": False, "reason": "already manifest 2.0", "path": str(root)}
    if "extension" not in legacy:
        fail("%s has no [extension] table" % path)
    modern = _to_v2(legacy)
    text = emit_toml(modern)
    written = None
    if arguments.get("write"):
        backup = root / "extension.toml.v1"
        if not backup.exists():
            write_text(backup, path.read_text(encoding="utf-8"))
        write_text(path, text)
        written = str(path)
    return {
        "migrated": True,
        "path": str(root),
        "written": written,
        "text": text,
        "notes": [
            "compatibility.bsh became compatibility.host",
            "runtime entry/args/env/protocol/startup moved under runtime.config",
            "contributes.* became [[contribution]] entries with empty payloads",
            "events, publishes and hooks became event.subscribe, event.publish and hook",
        ],
    }


def _to_v2(legacy: dict) -> dict:
    identity = dict(legacy.get("extension") or {})
    compatibility = legacy.get("compatibility") or {}
    runtime = legacy.get("runtime") or {}
    config = {}
    for key in ("entry", "args", "env", "protocol"):
        if runtime.get(key) not in (None, [], {}):
            config[key] = runtime[key]
    config["startup"] = runtime.get("startup") or "on-demand"
    if runtime.get("kind", "declarative") == "declarative" and "entry" in config:
        # The declarative runtime reads package files and forbids an entry.
        del config["entry"]
    contributions = []
    contributes = legacy.get("contributes") or {}
    for kind, key in CONTRIBUTION_GROUPS:
        values = contributes.get(key) or []
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if isinstance(value, dict):
                # 1.x tables carried their payload inline: {"id": "x", ...}.
                # Emit the id as the contribution id and keep the rest under
                # [contribution.payload] instead of nesting the table into id.
                raw_id = value.get("id")
                if not isinstance(raw_id, str) or not raw_id:
                    fail(
                        "a 1.x contributes.%s table needs a non-empty string 'id'; "
                        "found %r" % (key, raw_id)
                    )
                payload = {
                    name: item for name, item in value.items() if name != "id"
                }
                entry = {"kind": kind, "id": raw_id}
                if payload:
                    entry["payload"] = payload
                contributions.append(entry)
            elif isinstance(value, str):
                contributions.append({"kind": kind, "id": value})
            else:
                fail(
                    "a 1.x contributes.%s entry must be a string id or a table "
                    "with an 'id'; found %r" % (key, value)
                )
    capabilities = (legacy.get("capabilities") or {}).get("required") or []
    modern = {
        "schema_version": constants.SCHEMA_VERSION,
        "extension": identity,
        "compatibility": {
            "host": compatibility.get("bsh") or ">=3.0.0, <4.0.0",
            "extension_api": compatibility.get("extension_api") or "^1.0",
        },
        "runtime": {"kind": runtime.get("kind") or "declarative", "config": config},
        "capabilities": {"required": capabilities},
        "contribution": contributions,
    }
    for key in ("configuration", "resources", "dependencies", "services"):
        if legacy.get(key):
            modern[key] = legacy[key]
    return modern


def emit_toml(data: dict) -> str:
    """Serialise the small shape a manifest uses, deterministically."""
    lines = []
    _emit_table(lines, [], data)
    return "\n".join(lines).strip("\n") + "\n"


def _emit_table(lines, path, table):
    scalars = []
    tables = []
    arrays = []
    for key, value in table.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            arrays.append((key, value))
        else:
            scalars.append((key, value))
    for key, value in scalars:
        lines.append("%s = %s" % (_toml_key(key), _toml_value(value)))
    for key, value in tables:
        child = path + [key]
        lines.append("")
        lines.append("[%s]" % ".".join(_toml_key(part) for part in child))
        _emit_table(lines, child, value)
    for key, values in arrays:
        child = path + [key]
        for item in values:
            lines.append("")
            lines.append("[[%s]]" % ".".join(_toml_key(part) for part in child))
            _emit_table(lines, child, item)


def _toml_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(
            "%s = %s" % (_toml_key(key), _toml_value(item)) for key, item in value.items()
        ) + " }"
    return json.dumps(str(value), ensure_ascii=False)
