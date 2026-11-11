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
import subprocess
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
    """Every hashable package file in the host's walk order.

    The store hashes files in WalkDir's pre-order with per-directory name
    sorting, not in one flat lexicographic list. Keeping the same order here
    is what makes the DevKit's hash equal the host's; a different order hashes
    the same bytes to a different digest.
    """
    files = []

    def visit(directory: Path) -> None:
        names = sorted(os.listdir(directory))
        for name in names:
            path = directory / name
            if name in constants.IGNORED_DIRECTORIES and path.is_dir():
                continue
            if path.is_dir() and not path.is_symlink():
                visit(path)
                continue
            relative = rel(root, path)
            if not ignored(relative):
                files.append(relative)

    visit(root)
    return files


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


# --- the committed tree -----------------------------------------------------
#
# The market ships commits, not working trees: the host clones the provider and
# hashes that checkout, and a clone never carries an ignored file. Hashing the
# working tree instead is how an index ends up declaring bytes no clone can
# have - a __pycache__ left by a test run is the usual one - and the host then
# refuses the install with a package.integrity denial. These helpers read HEAD,
# so the index describes exactly what a clone yields.

GIT_TIMEOUT_SECONDS = 120


def _git(root: Path, *arguments: str, payload: "bytes | None" = None):
    """Run git in `root`; None when git itself cannot run."""
    try:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            input=payload,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_worktree(root: Path) -> "Path | None":
    """The Git work tree `root` belongs to, or None when it is not in one."""
    result = _git(root, "rev-parse", "--show-toplevel")
    if result is None or result.returncode != 0:
        return None
    top = result.stdout.decode("utf-8", "replace").strip()
    if not top:
        return None
    try:
        return Path(top).resolve()
    except OSError:  # pragma: no cover - a path that cannot be resolved
        return Path(top)


def _repo_relative(root: Path, repo: Path) -> "str | None":
    try:
        return root.resolve().relative_to(repo).as_posix()
    except ValueError:
        return None


def _git_failure(action: str, result) -> "None":
    stderr = result.stderr.decode("utf-8", "replace").strip()
    fail("git %s failed: %s" % (action, stderr or "no output"))


def _walk_order(files: "list[str]") -> "list[str]":
    """Order package-relative paths the way the host's WalkDir visits them."""
    tree: dict = {}
    for relative in files:
        node = tree
        for part in relative.split("/"):
            node = node.setdefault(part, {})
    ordered: "list[str]" = []

    def visit(node: dict, prefix: str) -> None:
        for name in sorted(node):
            child = node[name]
            path = prefix + name
            if child:
                visit(child, path + "/")
            else:
                ordered.append(path)

    visit(tree, "")
    return ordered


def _head_entries(root: Path) -> "list[tuple[str, str]] | None":
    """HEAD's (package-relative path, blob id) pairs, in the host's walk order.

    None means `root` is not inside a Git work tree. Inside one, a package Git
    does not carry is refused rather than hashed from disk: a clone could never
    install it.
    """
    repo = git_worktree(root)
    if repo is None:
        return None
    relative = _repo_relative(root, repo)
    if relative is None:
        return None
    result = _git(repo, "ls-tree", "-r", "-z", "--full-tree", "HEAD", "--", relative or ".")
    if result is None:
        return None
    if result.returncode != 0:
        _git_failure("ls-tree", result)
    prefix = relative + "/" if relative else ""
    entries: "list[tuple[str, str]]" = []
    for record in result.stdout.split(b"\x00"):
        if not record:
            continue
        meta, raw_path = record.split(b"\t", 1)
        mode, kind, sha = meta.split(b" ")
        path = raw_path.decode("utf-8", "surrogateescape")
        if prefix and not path.startswith(prefix):
            continue
        inner = path[len(prefix):] if prefix else path
        if mode == b"120000":
            fail(
                "package contains a symbolic link at %s; packages must be "
                "self-contained" % inner
            )
        if kind != b"blob":
            fail(
                "HEAD carries %s at %s, which is not a file; a package must be "
                "self-contained" % (kind.decode("ascii", "replace"), inner)
            )
        if ignored(inner) or inner == constants.SIGNATURE_FILE:
            continue
        entries.append((inner, sha.decode("ascii")))
    if not entries:
        fail(
            "the package has no committed files in %s; commit %s before "
            "building a market index" % (repo, root)
        )
    order = {
        path: position
        for position, path in enumerate(_walk_order([path for path, _ in entries]))
    }
    entries.sort(key=lambda entry: order[entry[0]])
    return entries


def _read_blobs(repo: Path, shas: "list[str]") -> "list[bytes]":
    """Read committed blobs in one `git cat-file --batch` call."""
    if not shas:
        return []
    result = _git(repo, "cat-file", "--batch", payload=("\n".join(shas) + "\n").encode("ascii"))
    if result is None:
        fail("git cat-file could not run; install Git or run outside a work tree")
    if result.returncode != 0:
        _git_failure("cat-file", result)
    output = result.stdout
    blobs: "list[bytes]" = []
    position = 0
    for sha in shas:
        newline = output.find(b"\n", position)
        if newline < 0:
            fail("git cat-file returned a short object stream")
        header = output[position:newline].decode("ascii", "replace").split(" ")
        if len(header) != 3 or header[1] != "blob":
            fail("git cat-file could not read %s: %s" % (sha, " ".join(header)))
        size = int(header[2])
        start = newline + 1
        blobs.append(output[start:start + size])
        position = start + size + 1
    return blobs


def head_package_files(root: Path) -> "list[str] | None":
    """The package's committed files at HEAD, in the host's walk order."""
    entries = _head_entries(root)
    if entries is None:
        return None
    return [relative for relative, _sha in entries]


def head_package_hash(root: Path) -> "str | None":
    """The canonical hash of the package as HEAD commits it.

    None means `root` is not inside a Git work tree, so there is no commit to
    describe. The digest is the same recipe as [`package_hash`], over the
    committed blobs instead of the files on disk.
    """
    entries = _head_entries(root)
    if entries is None:
        return None
    repo = git_worktree(root)
    if repo is None:  # pragma: no cover - _head_entries already resolved one
        return None
    blobs = _read_blobs(repo, [sha for _relative, sha in entries])
    digest = hashlib.sha256()
    for (relative, _sha), data in zip(entries, blobs):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(len(data).to_bytes(8, "little"))
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def head_package_changes(root: Path) -> "list[str]":
    """Paths under `root` that differ from HEAD, per `git status`.

    Ignored files are not reported: a clone never carries them, so they do not
    change what the market installs. Everything else here means the working
    copy and the commit the market ships disagree.
    """
    repo = git_worktree(root)
    if repo is None:
        return []
    relative = _repo_relative(root, repo)
    if relative is None:
        return []
    result = _git(repo, "status", "--porcelain", "-z", "--", relative or ".")
    if result is None or result.returncode != 0:
        return []
    records = [record for record in result.stdout.split(b"\x00") if record]
    changes: "list[str]" = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        status = record[:2]
        if len(record) <= 3:
            continue
        changes.append(record[3:].decode("utf-8", "surrogateescape"))
        if status[:1] in (b"R", b"C") and index < len(records):
            changes.append(records[index][3:].decode("utf-8", "surrogateescape"))
            index += 1
    return changes


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
