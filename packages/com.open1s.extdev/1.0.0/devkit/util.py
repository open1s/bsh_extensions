"""Small, dependency-free helpers the DevKit tools share.

Everything here is deliberately boring: bounded reads, atomic writes, stable
serialisation and path checks. A development tool must never be the reason a
package is wrong, so the helpers refuse rather than guess.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import constants


class DevkitError(Exception):
    """A refusal with a message the caller can act on."""


def fail(message: str) -> "None":
    """Raise a DevkitError with a single actionable sentence."""
    raise DevkitError(message)


def utc_stamp() -> str:
    """The current UTC date, the form a changelog entry carries."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# --- paths -----------------------------------------------------------------


def resolve_root(raw: object, label: str = "path") -> Path:
    """Resolve a package path argument and insist it is absolute.

    The extension process runs with its cwd set to its own installed package
    directory, so a relative path would silently name the wrong tree. The host
    also resolves the call scope against the workspace, which only matches the
    grant when the argument is the absolute path.
    """
    if not isinstance(raw, str) or not raw.strip():
        fail("%s must be a non-empty string naming a package directory" % label)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        fail(
            "%s must be an absolute path (the extension process runs with cwd "
            "set to the package root, so a relative path would resolve there)" % label
        )
    if not path.exists():
        fail("%s does not exist: %s" % (label, path))
    return path


def resolve_new_path(raw: object, label: str = "path") -> Path:
    """Resolve a path that may not exist yet."""
    if not isinstance(raw, str) or not raw.strip():
        fail("%s must be a non-empty string" % label)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        fail("%s must be an absolute path" % label)
    return path


def rel(root: Path, path: Path) -> str:
    """The package-relative POSIX spelling of one path."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def is_within(root: Path, path: Path) -> bool:
    """Whether path stays inside root after lexical normalisation."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def safe_join(root: Path, relative: str) -> Path:
    """Join a package-relative path, refusing escapes and absolute names."""
    if not relative or relative.startswith("/") or "\\" in relative:
        fail("package-relative path %r is unsafe" % relative)
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        fail("package-relative path %r is unsafe" % relative)
    candidate = root.joinpath(*parts)
    if not is_within(root, candidate.parent):
        fail("package-relative path %r escapes the package" % relative)
    return candidate


def ignored(relative: str) -> bool:
    """Whether the package hash skips this relative path."""
    parts = relative.split("/")
    if any(part in constants.IGNORED_DIRECTORIES for part in parts[:-1]):
        return True
    name = parts[-1]
    if name in constants.IGNORED_FILES:
        return True
    return any(name.endswith(suffix) for suffix in constants.IGNORED_SUFFIXES)


def walk_files(root: Path) -> "list[str]":
    """Every hashable package file as a sorted POSIX relative path."""
    files = []
    for current, directories, names in os.walk(root):
        directories[:] = sorted(
            name for name in directories if name not in constants.IGNORED_DIRECTORIES
        )
        for name in names:
            relative = rel(root, Path(current) / name)
            if not ignored(relative):
                files.append(relative)
    return sorted(files)


# --- reading and writing ---------------------------------------------------


def read_bytes(path: Path, limit: int = 8 * 1024 * 1024) -> bytes:
    """Read a file, refusing anything above the bytes the tool will handle."""
    try:
        size = path.stat().st_size
    except OSError as error:
        fail("cannot read %s: %s" % (path, error))
    if size > limit:
        fail("%s is %d bytes; this tool reads at most %d" % (path, size, limit))
    try:
        return path.read_bytes()
    except OSError as error:
        fail("cannot read %s: %s" % (path, error))


def read_text(path: Path, limit: int = 4 * 1024 * 1024) -> str:
    """Read UTF-8 text; invalid encoding is a readable refusal."""
    try:
        return read_bytes(path, limit).decode("utf-8")
    except UnicodeDecodeError as error:
        fail("%s is not valid UTF-8: %s" % (path, error))


def read_json(path: Path, limit: int = 4 * 1024 * 1024):
    """Read one JSON document."""
    text = read_text(path, limit)
    try:
        return json.loads(text)
    except ValueError as error:
        fail("%s is not valid JSON: %s" % (path, error))


def dump_json(value, indent: int = 2) -> str:
    """Serialise JSON the way the market index is written."""
    return json.dumps(value, indent=indent, ensure_ascii=False, sort_keys=False) + "\n"


def write_text(path: Path, text: str) -> None:
    """Write text atomically: a sibling temp file, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


# --- digests ---------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    """Lowercase hex SHA-256."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 of UTF-8 text."""
    return sha256_bytes(text.encode("utf-8"))


def package_hash(root: Path) -> str:
    """The store's canonical package hash.

    It covers each file's relative path, byte length and content digest in
    sorted order; directory metadata, mtimes and modes are excluded so two
    copies of one package hash the same. package.sig is skipped because the
    signature covers the tree it cannot be part of.
    """
    digest = hashlib.sha256()
    for relative in walk_files(root):
        if relative == constants.SIGNATURE_FILE:
            continue
        data = read_bytes(root / relative, limit=constants.HARD_MAX_OUTPUT_BYTES * 16)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(len(data).to_bytes(8, "little"))
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


# --- identifiers -----------------------------------------------------------

SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

_COMPARATOR = re.compile(
    r"^(\^|~=|~|=|>=|<=|>|<)?\s*v?"
    r"(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$"
)


def check_extension_id(raw: str) -> "str | None":
    """Return the reason an extension id is invalid, or None."""
    if not isinstance(raw, str) or not raw:
        return "an extension id must be a non-empty string"
    if len(raw) > 128:
        return "an extension id must be at most 128 bytes"
    segments = raw.split(".")
    if len(segments) < 2:
        return "an extension id needs at least two dot-separated segments"
    for segment in segments:
        if not segment or len(segment) > 63:
            return "each id segment must be 1..=63 bytes"
        for index, character in enumerate(segment):
            allowed = (
                character.isascii()
                and (character.islower() or character.isdigit())
            ) or (character in "-_" and index > 0)
            if not allowed:
                return (
                    "segment %r may only contain lowercase ASCII letters, digits, "
                    "'-' and '_', and must start with a letter or digit" % segment
                )
        if segment[-1] in "-_":
            return "segment %r must end with a letter or digit" % segment
    return None


def check_contribution_id(raw: str) -> "str | None":
    """Return the reason a contribution id is invalid, or None."""
    if not isinstance(raw, str) or not raw:
        return "a contribution id must be a non-empty string"
    if len(raw) > 96:
        return "a contribution id must be at most 96 bytes"
    for segment in raw.split("."):
        if not segment or len(segment) > 63:
            return "each contribution segment must be 1..=63 bytes"
        if not (segment[0].islower() or segment[0].isdigit()) or not segment[0].isascii():
            return "segment %r must start with a lowercase letter or digit" % segment
        for character in segment:
            if not character.isascii():
                return "segment %r must be ASCII" % segment
            if not (character.islower() or character.isdigit() or character in "-_"):
                return (
                    "segment %r may only contain lowercase letters, digits, "
                    "'-' and '_'" % segment
                )
    return None


def check_version(raw: str) -> "str | None":
    """Return the reason a semantic version is invalid, or None."""
    if not isinstance(raw, str) or not SEMVER.match(raw):
        return "%r is not a semantic version (expected MAJOR.MINOR.PATCH)" % (raw,)
    return None


def check_requirement(raw: str) -> "str | None":
    """Return the reason a semver range is invalid, or None.

    The host parses ranges with the semver crate: comma-separated comparators,
    each optionally carrying ^, ~, =, >, <, >= or <=, with partial versions and
    x/X/* wildcards.
    """
    if not isinstance(raw, str) or not raw.strip():
        return "a version requirement must be a non-empty string"
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            return "version requirement %r has an empty comparator" % raw
        if not _COMPARATOR.match(piece):
            return "version requirement %r is not a semver range" % raw
    return None


def check_relative_path(raw: str) -> "str | None":
    """Return the reason a package-relative path is unsafe, or None."""
    if not isinstance(raw, str) or not raw:
        return "a package-relative path must be a non-empty string"
    if raw.startswith("/") or "\\" in raw:
        return "path %r must be package-relative" % raw
    if any(part in ("", ".", "..") for part in raw.split("/")):
        return "path %r must not contain empty, '.' or '..' components" % raw
    return None


# --- markdown --------------------------------------------------------------


def parse_frontmatter(text: str):
    """Split optional YAML frontmatter from a Markdown contribution.

    Only the keys this standard defines are read (description, name, paths);
    unknown keys are ignored so a shared frontmatter vocabulary still loads.
    Returns (metadata, body).
    """
    metadata = {}
    body = text.lstrip("\ufeff")
    if body.startswith("---"):
        rest = body[3:]
        if rest.startswith("\r\n"):
            rest = rest[2:]
        elif rest.startswith("\n"):
            rest = rest[1:]
        end = rest.find("\n---")
        if end != -1:
            for line in rest[:end].splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip('"').strip("'")
            after = rest[end + 4:]
            body = after.lstrip("\r\n")
    return metadata, body.strip()
