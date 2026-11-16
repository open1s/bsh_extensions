"""The package's JSON-RPC process runtime.

The host starts this file with python3, sends one JSON object per line on
stdin and reads one per line on stdout.  The handshake must echo the token,
otherwise the host refuses the process; every tool result is a JSON value the
host turns into tool content.

Trinno performs deterministic I/O only: literature search, reading-list
maintenance, arXiv PDF download and local paper intake.  All analysis is done
by the BSH agent through the ``research-workflow`` skill.
"""

import json
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

TOOLS = ("search_literature", "intake_papers", "init_project")

OPENALEX_API = "https://api.openalex.org/works"
ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF = "https://arxiv.org/pdf/"

HTTP_TIMEOUT = 20
MAX_REDIRECTS = 3
MAX_HTTP_RETRIES = 3
MAX_API_BYTES = 4 * 1024 * 1024
MAX_PDF_BYTES = 8 * 1024 * 1024
ARXIV_DELAY_SECONDS = 3.0
# A host tool call has to answer well inside the host's own read timeout, so
# every network phase of one call shares a wall-clock budget.
MAX_CALL_SECONDS = 22.0
RETRY_BACKOFF_SECONDS = 2.0
MAX_EXTRACTED_CHARS = 200000
MAX_DOWNLOADS_PER_CALL = 2
# The download phase shares the call budget, so it can never exceed it.
MAX_DOWNLOAD_SECONDS = MAX_CALL_SECONDS
# The host rejects a tool result larger than max_output_bytes (256 KiB in the
# manifest), so the runtime bounds its own payload well below that limit.
MAX_RESULT_OUTPUT_BYTES = 180 * 1024
# An abstract in a tool result is a preview, not the full text.
MAX_ABSTRACT_CHARS = 1200
# An abstract written into reading-list.md or a note card is kept complete
# enough to be useful, but still bounded.
MAX_READING_LIST_ABSTRACT_CHARS = 4000
MAX_NOTE_ABSTRACT_CHARS = 4000

ALLOWED_HOSTS = {
    "api.openalex.org",
    "export.arxiv.org",
    "arxiv.org",
}


class ToolError(Exception):
    """A refusal that becomes a JSON-RPC error, and therefore a tool error."""


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log_error(message):
    """Diagnostics go to stderr; stdout carries JSON-RPC only."""
    sys.stderr.write("trinno: %s\n" % message)
    sys.stderr.flush()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def require_absolute_dir(value, label="path"):
    if not isinstance(value, str) or not value.strip():
        raise ToolError("%s must be a non-empty absolute path" % label)
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ToolError("%s must be absolute" % label)
    path = path.resolve()
    if not path.is_dir():
        raise ToolError("%s is not an existing directory: %s" % (label, path))
    return path


def safe_url(url):
    """Allow only plain HTTPS URLs on the fixed host allow-list.

    A URL with credentials, a non-default port or an invalid port is
    refused: the allow-list is about the host, and a port or userinfo would
    silently widen the request beyond the granted domain.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ToolError("network request refused: host is not allowed: %s" % url)
    if parsed.username or parsed.password:
        raise ToolError("network request refused: credentials in URL: %s" % url)
    try:
        port = parsed.port
    except ValueError:
        raise ToolError("network request refused: invalid port: %s" % url)
    if port is not None and port != 443:
        raise ToolError("network request refused: non-default port: %s" % url)
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are followed manually so the hop count stays bounded."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url, max_bytes, accept=None, deadline=None):
    """GET a bounded response.  Returns (bytes, content_type, final_url).

    ``deadline`` is a ``time.monotonic()`` stamp.  When it is set, the socket
    timeout, the retry backoff and the number of retries are all clamped to
    the remaining budget, so one slow or rate-limited host cannot make the
    whole tool call overrun the host's read timeout.
    """
    current = safe_url(url)
    opener = urllib.request.build_opener(_NoRedirect)
    for _hop in range(MAX_REDIRECTS + 1):
        for attempt in range(MAX_HTTP_RETRIES + 1):
            timeout = HTTP_TIMEOUT
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ToolError("time budget for this call is exhausted")
                timeout = max(1.0, min(float(HTTP_TIMEOUT), remaining))
            request = urllib.request.Request(
                current, headers={"User-Agent": "Trinno/1.0 (BSH research extension)"})
            if accept:
                request.add_header("Accept", accept)
            try:
                with opener.open(request, timeout=timeout) as response:
                    final_url = response.geturl()
                    safe_url(final_url)
                    content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip()
                    # Read in chunks so the call deadline also bounds the body
                    # download, not only the connect/read socket timeout.
                    chunks = []
                    total = 0
                    while True:
                        if deadline is not None and time.monotonic() >= deadline:
                            raise ToolError("time budget for this call is exhausted while downloading %s" % current)
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise ToolError("response body exceeded the %d byte limit" % max_bytes)
                        chunks.append(chunk)
                    return b"".join(chunks), content_type, final_url
            except urllib.error.HTTPError as error:
                if error.code in (301, 302, 303, 307, 308):
                    location = error.headers.get("Location") if error.headers else None
                    if not location:
                        raise ToolError("HTTP %s without a Location header for %s" % (error.code, current))
                    current = safe_url(urllib.parse.urljoin(current, location))
                    break
                if error.code in (429, 503) and attempt < MAX_HTTP_RETRIES:
                    delay = RETRY_BACKOFF_SECONDS * (attempt + 1)
                    retry_after = error.headers.get("Retry-After") if error.headers else None
                    try:
                        delay = max(delay, float(retry_after))
                    except (TypeError, ValueError):
                        pass
                    delay = min(delay, 30)
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= delay + 1:
                            raise ToolError("HTTP %s for %s (time budget exhausted)" % (error.code, current))
                        delay = min(delay, max(0.0, remaining - 1))
                    time.sleep(delay)
                    continue
                raise ToolError("HTTP %s for %s" % (error.code, current))
            except urllib.error.URLError as error:
                reason = error.reason
                if isinstance(reason, (TimeoutError, socket.timeout)):
                    raise ToolError("time budget for this call is exhausted while reading %s" % current)
                raise ToolError("network error for %s: %s" % (current, reason))
            except (TimeoutError, OSError) as error:
                # A socket timeout while streaming a body is a budget problem,
                # not a crash: report it so the caller can resume later.
                raise ToolError("time budget for this call is exhausted while reading %s (%s)" % (current, error))
        else:
            raise ToolError("too many retries for %s" % current)
    raise ToolError("too many redirects for %s" % url)


def clean_text(value):
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_title(title):
    text = unicodedata.normalize("NFKD", title or "").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def slugify(value, fallback="paper"):
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    text = text[:80]
    return text or fallback


def year_from_date(value):
    match = re.search(r"(\d{4})", value or "")
    return int(match.group(1)) if match else None


def openalex_search(query, limit, deadline=None):
    url = "%s?search=%s&per-page=%d" % (
        OPENALEX_API,
        urllib.parse.quote(query),
        limit,
    )
    payload, _content_type, _final = http_get(url, MAX_API_BYTES, "application/json", deadline)
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ToolError("invalid OpenAlex response: %s" % error)
    results = []
    for item in document.get("results") or []:
        authors = []
        for authorship in item.get("authorships") or []:
            name = ((authorship.get("author") or {}).get("display_name") or "").strip()
            if name:
                authors.append(name)
        location = item.get("primary_location") or {}
        source = ((location.get("source") or {}).get("display_name") or "") or ""
        doi = (item.get("doi") or "").strip()
        url_value = (location.get("landing_page_url") or item.get("id") or "").strip()
        abstract = item.get("abstract") or ""
        if not abstract and isinstance(item.get("abstract_inverted_index"), dict):
            positions = {}
            for word, indexes in item["abstract_inverted_index"].items():
                for index in indexes or []:
                    positions[index] = word
            abstract = " ".join(positions[index] for index in sorted(positions))
        results.append({
            "title": (item.get("title") or "").strip(),
            "authors": authors,
            "year": item.get("publication_year"),
            "abstract": clean_text(abstract),
            "url": url_value,
            "doi": doi,
            "cited_by_count": item.get("cited_by_count") or 0,
            "source": source,
            "provider": "openalex",
        })
    return results


def arxiv_search(query, limit, deadline=None):
    url = "%s?search_query=all:%s&start=0&max_results=%d" % (
        ARXIV_API,
        urllib.parse.quote(query),
        limit,
    )
    payload, _content_type, _final = http_get(url, MAX_API_BYTES, "application/atom+xml", deadline)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ToolError("invalid arXiv response: %s" % error)
    atom = "{http://www.w3.org/2005/Atom}"
    arxiv_ns = "{http://arxiv.org/schemas/atom}"
    results = []
    for entry in root.findall("%sentry" % atom):
        title = clean_text((entry.findtext("%stitle" % atom) or ""))
        summary = clean_text((entry.findtext("%ssummary" % atom) or ""))
        published = entry.findtext("%spublished" % atom) or ""
        updated = entry.findtext("%supdated" % atom) or ""
        arxiv_id = clean_text((entry.findtext("%sid" % atom) or ""))
        if arxiv_id.startswith("http://arxiv.org/abs/"):
            arxiv_id = arxiv_id.rsplit("/", 1)[-1]
        authors = []
        for author in entry.findall("%sauthor" % atom):
            name = clean_text(author.findtext("%sname" % atom) or "")
            if name:
                authors.append(name)
        doi = clean_text(entry.findtext("%sdoi" % arxiv_ns) or "")
        pdf_url = ""
        for link in entry.findall("%slink" % atom):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href") or ""
                break
        if not pdf_url and arxiv_id:
            pdf_url = ARXIV_PDF + urllib.parse.quote(arxiv_id)
        results.append({
            "title": title,
            "authors": authors,
            "year": year_from_date(published or updated),
            "abstract": summary,
            "url": ("https://arxiv.org/abs/" + urllib.parse.quote(arxiv_id)) if arxiv_id else "",
            "pdf_url": pdf_url,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "cited_by_count": None,
            "source": "arXiv",
            "provider": "arxiv",
        })
    return results


def normalize_doi(value):
    """Return a bare, lower-case DOI, or an empty string."""
    doi = (value or "").strip()
    if not doi:
        return ""
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.strip().lower()


def result_key(result):
    doi = normalize_doi(result.get("doi"))
    if doi:
        return "doi:" + doi
    title = normalize_title(result.get("title"))
    return "title:" + title if title else None


def existing_keys(reading_list):
    keys = set()
    if not reading_list.exists():
        return keys
    try:
        text = reading_list.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return keys
    for match in re.finditer(r"<!--\s*trinno-key:\s*(.+?)\s*-->", text):
        keys.add(match.group(1).strip().lower())
    return keys


def format_entry(result, query, timestamp):
    authors = ", ".join(result.get("authors") or [])
    abstract = result.get("abstract") or "（无摘要）"
    if len(abstract) > MAX_READING_LIST_ABSTRACT_CHARS:
        abstract = abstract[:MAX_READING_LIST_ABSTRACT_CHARS].rstrip() + "…"
    cited = result.get("cited_by_count")
    cited_text = "未知" if cited is None else str(cited)
    lines = [
        "### %s" % (result.get("title") or "（无标题）"),
        "",
        "- 作者：%s" % (authors or "未知"),
        "- 年份：%s" % (result.get("year") or "未知"),
        "- 来源：%s" % (result.get("source") or result.get("provider") or "未知"),
        "- 链接：%s" % (result.get("url") or "无"),
        "- DOI：%s" % (result.get("doi") or "无"),
        "- 引用数：%s" % cited_text,
        "- 检索词：%s" % query,
        "- 时间戳：%s" % timestamp,
        "",
        "**摘要**",
        "",
        abstract,
        "",
    ]
    return "\n".join(lines)


def append_reading_list(project_path, entries, query, timestamp):
    reading_list = project_path / "reading-list.md"
    known = existing_keys(reading_list)
    added = []
    skipped = []
    blocks = []
    for entry in entries:
        key = result_key(entry)
        if key is None:
            skipped.append({"title": entry.get("title") or "", "reason": "missing title and DOI"})
            continue
        if key.lower() in known:
            skipped.append({"title": entry.get("title") or "", "reason": "duplicate", "key": key})
            continue
        known.add(key.lower())
        added.append(entry)
        blocks.append("<!-- trinno-key: %s -->" % key)
        blocks.append(format_entry(entry, query, timestamp))
        blocks.append("")
    if blocks:
        project_path.mkdir(parents=True, exist_ok=True)
        header = ""
        if not reading_list.exists():
            header = "# Reading list\n\n"
        with reading_list.open("a", encoding="utf-8") as stream:
            stream.write(header + "\n".join(blocks))
    return reading_list, added, skipped


def download_arxiv_pdfs(project_path, entries, max_downloads=MAX_DOWNLOADS_PER_CALL, deadline=None):
    """Download a bounded number of arXiv PDFs into papers/_inbox/.

    The call is capped in count and in wall-clock time: arXiv asks for polite,
    serial access, and a host tool call has to return in time.  Entries whose
    PDF is still missing are reported as pending, so a later call resumes.
    """
    inbox = project_path / "papers" / "_inbox"
    downloaded = []
    skipped = []
    failures = []
    pending = []
    arxiv_entries = [entry for entry in entries if entry.get("provider") == "arxiv" and entry.get("arxiv_id")]
    if not arxiv_entries:
        return downloaded, skipped, failures, pending
    inbox.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    for index, entry in enumerate(arxiv_entries):
        arxiv_id = entry["arxiv_id"]
        safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", arxiv_id)
        target = inbox / ("%s.pdf" % safe_id)
        if target.exists():
            skipped.append({"title": entry.get("title") or "", "path": str(target), "reason": "already exists"})
            continue
        if len(downloaded) >= max_downloads:
            pending.append({"title": entry.get("title") or "", "arxiv_id": arxiv_id,
                            "reason": "download budget for this call is exhausted"})
            continue
        if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
            pending.append({"title": entry.get("title") or "", "arxiv_id": arxiv_id,
                            "reason": "download time budget for this call is exhausted"})
            continue
        if deadline is not None and time.monotonic() >= deadline:
            pending.append({"title": entry.get("title") or "", "arxiv_id": arxiv_id,
                            "reason": "call time budget is exhausted"})
            continue
        if index:
            time.sleep(ARXIV_DELAY_SECONDS)
        url = entry.get("pdf_url") or (ARXIV_PDF + urllib.parse.quote(arxiv_id))
        try:
            payload, content_type, _final = http_get(url, MAX_PDF_BYTES, "application/pdf", deadline)
        except ToolError as error:
            message = str(error)
            if "time budget" in message:
                # The PDF did not fit into this call's budget: report it as
                # pending so a later call can resume it.
                pending.append({"title": entry.get("title") or "", "arxiv_id": arxiv_id,
                                "url": url, "reason": message})
                break
            if "exceeded the" in message:
                failures.append({"title": entry.get("title") or "", "url": url, "error": message})
                continue
            failures.append({"title": entry.get("title") or "", "url": url, "error": message})
            continue
        if content_type and content_type != "application/pdf" and not payload.startswith(b"%PDF"):
            failures.append({"title": entry.get("title") or "", "url": url, "error": "unexpected content type %s" % content_type})
            continue
        if not payload.startswith(b"%PDF"):
            failures.append({"title": entry.get("title") or "", "url": url, "error": "response is not a PDF"})
            continue
        try:
            with target.open("xb") as stream:
                stream.write(payload)
        except FileExistsError:
            skipped.append({"title": entry.get("title") or "", "path": str(target), "reason": "already exists"})
            continue
        downloaded.append({"title": entry.get("title") or "", "path": str(target), "bytes": len(payload)})
    return downloaded, skipped, failures, pending


def bound_results(results):
    """Return a copy of the results that fits the host output ceiling.

    The host rejects a tool result larger than ``max_output_bytes``, so the
    runtime trims the payload itself: abstracts become previews, and the
    result list is shortened until the encoded value fits the budget.  The
    full abstracts still land in ``reading-list.md``.
    """
    trimmed = []
    for entry in results:
        item = dict(entry)
        abstract = item.get("abstract") or ""
        if len(abstract) > MAX_ABSTRACT_CHARS:
            item["abstract"] = abstract[:MAX_ABSTRACT_CHARS].rstrip() + "…"
        trimmed.append(item)
    while trimmed:
        encoded = len(json.dumps(trimmed, ensure_ascii=False).encode("utf-8"))
        if encoded <= MAX_RESULT_OUTPUT_BYTES:
            return trimmed
        trimmed.pop()
    return []


def tool_search_literature(arguments):
    project_path = require_absolute_dir(arguments.get("path"))
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("query must be a non-empty string")
    query = query.strip()
    limit = arguments.get("limit", 10)
    if isinstance(limit, str) and limit.strip().isdigit():
        limit = int(limit.strip())
    elif isinstance(limit, float) and float(limit).is_integer():
        limit = int(limit)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise ToolError("limit must be an integer between 1 and 50")
    download = arguments.get("download", True)
    if isinstance(download, str) and download.strip().lower() in ("true", "false"):
        download = download.strip().lower() == "true"
    if not isinstance(download, bool):
        raise ToolError("download must be a boolean")
    max_downloads = arguments.get("max_downloads", MAX_DOWNLOADS_PER_CALL)
    if isinstance(max_downloads, str) and max_downloads.strip().isdigit():
        max_downloads = int(max_downloads.strip())
    if not isinstance(max_downloads, int) or isinstance(max_downloads, bool) or max_downloads < 0:
        raise ToolError("max_downloads must be a non-negative integer")

    sources = []
    results = []
    errors = []
    deadline = time.monotonic() + MAX_CALL_SECONDS
    for name, function in (("openalex", openalex_search), ("arxiv", arxiv_search)):
        try:
            found = function(query, limit, deadline)
        except ToolError as error:
            errors.append({"source": name, "error": str(error)})
            continue
        sources.append({"source": name, "count": len(found)})
        results.extend(found)

    timestamp = utc_now()
    reading_list, added, skipped = append_reading_list(project_path, results, query, timestamp)
    downloaded = []
    download_skipped = []
    download_failures = []
    pending = []
    if download:
        # Every arXiv hit is a candidate, not only the newly added ones: an
        # earlier call may have exhausted its budget before reaching them.
        downloaded, download_skipped, download_failures, pending = download_arxiv_pdfs(
            project_path, results, max_downloads, deadline)
    skipped.extend(download_skipped)
    return {
        "path": str(project_path),
        "added": len(added),
        "skipped": len(skipped),
        "downloaded": len(downloaded),
        "sources": sources,
        "results": bound_results(results),
        "reading_list": str(reading_list),
        "skipped_entries": skipped,
        "downloaded_files": downloaded,
        "pending_downloads": pending,
        "failures": errors + download_failures,
        "timestamp": timestamp,
    }


def _decode_pdf_literal(raw):
    out = bytearray()
    index = 0
    escapes = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8,
               ord("f"): 12, ord("("): 40, ord(")"): 41, ord("\\"): 92}
    while index < len(raw):
        char = raw[index]
        if char == 92 and index + 1 < len(raw):
            nxt = raw[index + 1]
            if nxt in escapes:
                out.append(escapes[nxt])
                index += 2
                continue
            if 48 <= nxt <= 55:
                digits = raw[index + 1:index + 4]
                octal = bytes(d for d in digits if 48 <= d <= 55)
                if octal:
                    out.append(int(octal, 8) & 0xFF)
                    index += 1 + len(octal)
                    continue
            if nxt in (10, 13):
                index += 2
                continue
            out.append(nxt)
            index += 2
            continue
        out.append(char)
        index += 1
    return bytes(out)


def _fallback_pdf_text(payload):
    """Best-effort text extraction with the standard library only.

    It reads uncompressed and Flate-compressed content streams and collects
    the operands of text-showing operators.  pypdf remains the preferred and
    more accurate extractor; this fallback keeps intake working when the
    optional dependency is unavailable.
    """
    import zlib

    chunks = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", payload, re.DOTALL):
        raw = match.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        if b"Tj" not in raw and b"TJ" not in raw:
            continue
        chunks.append(raw)

    pieces = []
    for raw in chunks:
        for match in re.finditer(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>", raw):
            token = match.group(0)
            if token.startswith(b"("):
                pieces.append(_decode_pdf_literal(token[1:-1]).decode("latin-1", "replace"))
            else:
                hex_text = re.sub(rb"\s", b"", token[1:-1])
                if len(hex_text) % 2:
                    hex_text += b"0"
                try:
                    raw_bytes = bytes.fromhex(hex_text.decode("ascii"))
                except ValueError:
                    continue
                pieces.append(raw_bytes.decode("latin-1", "replace"))
        pieces.append("\n")
    joined = "".join(pieces)
    joined = "".join(char for char in joined if char in "\n\t" or 32 <= ord(char) < 127)
    return re.sub(r"[ \t]+", " ", joined).strip()


COMMON_WORDS = {
    "the", "of", "and", "in", "to", "we", "this", "that", "for", "with",
    "is", "are", "on", "by", "as", "at", "from", "or", "an", "be", "paper",
    "abstract", "introduction", "method", "methods", "results", "figure",
    "table", "using", "our", "can", "which", "these", "such", "between",
}


def looks_like_readable_text(text):
    """Heuristic check for extracted PDF text.

    A PDF with an embedded subset font can decode to printable but meaningless
    characters.  Such text must not become note metadata, so it is reported as
    a failure instead of being written into a card.
    """
    sample = (text or "")[:4000]
    words = re.findall(r"[A-Za-z]{2,}", sample.lower())
    if not words:
        return False
    hits = sum(1 for word in words if word in COMMON_WORDS)
    return hits >= 3


def extract_pdf(path):
    text = ""
    metadata = {}
    extractor = "pypdf"
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    if PdfReader is not None:
        try:
            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages[:20]:
                pages.append(page.extract_text() or "")
                if sum(len(part) for part in pages) >= MAX_EXTRACTED_CHARS:
                    break
            text = "\n".join(pages)[:MAX_EXTRACTED_CHARS]
            try:
                info = reader.metadata or {}
                metadata = {str(key).lower(): str(value) for key, value in info.items() if value}
            except Exception:
                metadata = {}
        except Exception as error:  # pypdf raises many parser-specific errors
            raise ToolError("PDF extraction failed: %s" % error)
    else:
        extractor = "stdlib-fallback"
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ToolError("cannot read PDF: %s" % error)
        if not payload.startswith(b"%PDF"):
            raise ToolError("not a PDF file: %s" % path)
        text = _fallback_pdf_text(payload)[:MAX_EXTRACTED_CHARS]
        if not looks_like_readable_text(text):
            raise ToolError(
                "PDF text could not be read reliably without pypdf; "
                "install it with 'python3 -m pip install pypdf' and retry")
    if not text.strip():
        raise ToolError("no extractable text found in PDF: %s" % path)
    return text, metadata, extractor


def plausible_title(value):
    """Return the title only when it looks like readable text.

    The standard-library PDF fallback can decode custom font encodings into
    control characters; such a string must not become the card title or the
    note file name.
    """
    text = (value or "").strip()
    if len(text) < 8 or len(text) > 300:
        return ""
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return ""
    letters = sum(1 for char in text if char.isalpha())
    if letters < max(4, len(text) // 4):
        return ""
    return text


def guess_pdf_metadata(text, metadata):
    title = plausible_title(metadata.get("/title", ""))
    author = plausible_title(metadata.get("/author", ""))
    subject = plausible_title(metadata.get("/subject", ""))
    creation = metadata.get("/creationdate", "")
    year = year_from_date(creation)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not title and lines:
        for line in lines[:12]:
            if not re.match(r"^(arxiv|doi:|abstract$)", line, re.IGNORECASE):
                candidate = plausible_title(line)
                if candidate:
                    title = candidate
                    break
    if not author:
        for line in lines[1:12]:
            if re.search(r"@|university|institute|department|\blab\b", line, re.IGNORECASE):
                continue
            candidate = plausible_title(line)
            if not candidate:
                continue
            # An author line lists personal names, separated by commas or "and".
            if not re.search(r",|\band\b|&", candidate):
                continue
            names = re.findall(r"[A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+)*", candidate)
            names = [name for name in names if not name.lower() in COMMON_WORDS]
            if names:
                author = ", ".join(names)
                break
    if not year:
        match = re.search(r"\b(19|20)\d{2}\b", text[:4000])
        if match:
            year = int(match.group(0))
    abstract = subject
    if not abstract:
        match = re.search(r"(?is)\babstract\b[\s:.—-]*(.{200,4000}?)(?:\n\s*(?:1\.?\s+)?introduction\b|\bkeywords\b)", text)
        if match:
            abstract = clean_text(match.group(1))
    return {
        "title": clean_text(title),
        "authors": [author] if author else [],
        "year": year,
        "abstract": clean_text(abstract)[:4000],
    }


def _split_bib_entries(text):
    """Yield (type, key, body) for each BibTeX entry, brace-aware."""
    index = 0
    length = len(text)
    while index < length:
        at = text.find("@", index)
        if at < 0:
            return
        match = re.match(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text[at:])
        if not match:
            index = at + 1
            continue
        body_start = at + match.end()
        depth = 1
        cursor = body_start
        while cursor < length and depth:
            char = text[cursor]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            cursor += 1
        body = text[body_start:cursor - 1] if depth == 0 else text[body_start:]
        yield match.group(1), match.group(2), body
        index = max(cursor, at + 1)


def _split_bib_fields(body):
    """Yield (name, value) pairs, honouring quoted and braced values."""
    for match in re.finditer(r"(\w+)\s*=\s*", body):
        name = match.group(1)
        cursor = match.end()
        if cursor >= len(body):
            continue
        opener = body[cursor]
        if opener in "\"{(":
            closer = "}" if opener == "{" else opener
            depth = 1
            cursor += 1
            start = cursor
            while cursor < len(body):
                char = body[cursor]
                if char == opener and opener == "{":
                    depth += 1
                elif char == closer:
                    depth -= 1
                    if depth == 0:
                        break
                cursor += 1
            yield name, body[start:cursor]
            cursor += 1
        else:
            end = body.find(",", cursor)
            if end < 0:
                end = len(body)
            yield name, body[cursor:end]
            cursor = end


def parse_bib(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ToolError("cannot read BibTeX file: %s" % error)
    entries = []
    for entry_type, key, body in _split_bib_entries(text):
        fields = {"entry_type": entry_type.lower(), "key": key.strip()}
        for name, value in _split_bib_fields(body):
            fields[name.lower()] = clean_text(value)
        if fields.get("title"):
            entries.append(fields)
    if not entries:
        raise ToolError("no BibTeX entries found")
    return entries


def _openalex_abstract(item):
    """Return the abstract text of an OpenAlex work, if it has one."""
    abstract = item.get("abstract") or ""
    if not abstract and isinstance(item.get("abstract_inverted_index"), dict):
        positions = {}
        for word, indexes in item["abstract_inverted_index"].items():
            for index in indexes or []:
                positions[index] = word
        abstract = " ".join(positions[index] for index in sorted(positions))
    return clean_text(abstract)


def _openalex_item(item):
    authors = []
    for authorship in item.get("authorships") or []:
        name = ((authorship.get("author") or {}).get("display_name") or "").strip()
        if name:
            authors.append(name)
    return {
        "title": (item.get("title") or "").strip(),
        "authors": authors,
        "year": item.get("publication_year"),
        "abstract": _openalex_abstract(item),
        "doi": (item.get("doi") or "").strip(),
        "url": ((item.get("primary_location") or {}).get("landing_page_url") or item.get("id") or "").strip(),
    }


def _openalex_lookup(url, deadline=None):
    payload, _content_type, _final = http_get(url, MAX_API_BYTES, "application/json", deadline)
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    items = document.get("results") or []
    if not items:
        return None
    return _openalex_item(items[0])


def openalex_by_title(title, deadline=None):
    url = "%s?search=%s&per-page=1" % (OPENALEX_API, urllib.parse.quote(title))
    return _openalex_lookup(url, deadline)


def openalex_by_doi(doi, deadline=None):
    bare = normalize_doi(doi)
    if not bare:
        return None
    url = "%s?filter=doi:%s&per-page=1" % (OPENALEX_API, urllib.parse.quote(bare))
    return _openalex_lookup(url, deadline)


def complete_metadata(metadata, deadline=None):
    completed = dict(metadata)
    completed.setdefault("authors", [])
    completed.setdefault("year", None)
    completed.setdefault("abstract", "")
    completed.setdefault("doi", "")
    completed.setdefault("url", "")
    title = completed.get("title") or ""
    doi = normalize_doi(completed.get("doi"))
    if not title and not doi:
        return completed, None
    needs_completion = not completed.get("authors") or not completed.get("year") or not completed.get("abstract")
    if not needs_completion:
        return completed, None
    try:
        found = openalex_by_doi(doi, deadline) if doi else None
        if found is None and title:
            found = openalex_by_title(title, deadline)
    except ToolError as error:
        return completed, "metadata lookup failed: %s" % error
    if not found:
        return completed, "no OpenAlex match"
    for key in ("title", "authors", "year", "abstract", "doi", "url"):
        if not completed.get(key) and found.get(key):
            completed[key] = found[key]
    return completed, None


def note_filename(metadata, source_path):
    base = metadata.get("title") or source_path.stem
    return slugify(base) + ".md"


def resolve_note_target(notes_dir, project_path, metadata, source_path):
    """Return (target, skip_reason) for the note card of one paper.

    A card is never overwritten.  Three cases are distinguished:

    * the file name is free -> it is used;
    * the file name belongs to another paper (its source marker names a
      different file, or another BibTeX entry of the same file) -> a numeric
      suffix is used, so both papers keep a card;
    * the file name is taken by a card of this paper, possibly edited by
      hand until its markers are gone -> the card is kept and the paper is
      reported as skipped.
    """
    base = note_filename(metadata, source_path)
    candidate = notes_dir / base
    if not candidate.exists():
        return candidate, None
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    marker = "来源文件：`%s`" % os.path.relpath(str(source_path), str(project_path))
    key = (metadata.get("key") or "").strip()
    key_marker = "来源条目：`%s`" % key if key else ""
    if marker not in text:
        # The card was edited by hand: keep it and report a skip.
        return candidate, "note already exists"
    if key and key_marker not in text:
        # Another entry of the same .bib file owns this name.
        stem = base[:-3] if base.endswith(".md") else base
        index = 2
        while True:
            candidate = notes_dir / ("%s-%d.md" % (stem, index))
            if not candidate.exists():
                return candidate, None
            index += 1
    return candidate, "note already exists"


def render_note(metadata, source_path, project_path, extraction_note, entry_key=None):
    title = metadata.get("title") or source_path.stem
    authors = ", ".join(metadata.get("authors") or []) or "待智能体补全"
    year = metadata.get("year") or "待智能体补全"
    doi = metadata.get("doi") or "无"
    url = metadata.get("url") or "无"
    abstract = metadata.get("abstract") or "待智能体补全"
    if len(abstract) > MAX_NOTE_ABSTRACT_CHARS:
        abstract = abstract[:MAX_NOTE_ABSTRACT_CHARS].rstrip() + "…"
    relative = os.path.relpath(str(source_path), str(project_path))
    entry_line = "- 来源条目：`%s`\n" % entry_key if entry_key else ""
    return """# {title}

- 作者：{authors}
- 年份：{year}
- DOI：{doi}
- 来源文件：`{relative}`
{entry_line}- 证据链接：{url}
- 抽取说明：{extraction_note}

## 摘要

{abstract}

## 研究问题

<!-- 待智能体填写 -->

## 方法

<!-- 待智能体填写 -->

## 结论

<!-- 待智能体填写 -->

## 局限

<!-- 待智能体填写 -->

## 证据链接

- {url}

## 智能体补全笔记

<!-- 待智能体填写 -->
""".format(
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        relative=relative,
        entry_line=entry_line,
        url=url,
        extraction_note=extraction_note,
        abstract=abstract,
    )


def existing_note_for_source(notes_dir, project_path, source, entry_key=None, title=None):
    """Return the note card already built for this source file, if any.

    The source path is written into every card, so a card can be matched to
    its paper even when the title (and therefore the file name) changes after
    a metadata completion.  A .bib file may hold several entries, so the
    stable BibTeX key is used as a second key when it is known.
    """
    if not notes_dir.is_dir():
        return None
    marker = "来源文件：`%s`" % os.path.relpath(str(source), str(project_path))
    key = (entry_key or "").strip()
    wanted = (title or "").strip()
    key_marker = "来源条目：`%s`" % key if key else ""
    matches = []
    for candidate in sorted(notes_dir.glob("*.md")):
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if marker not in text:
            continue
        matches.append((candidate, text))
    if key:
        for candidate, text in matches:
            if key_marker in text:
                return candidate
        if wanted:
            for candidate, text in matches:
                heading = text.lstrip().splitlines()[0] if text.strip() else ""
                if heading.lstrip("# ").strip() == wanted:
                    return candidate
            # The card may have been edited by hand, so its heading and entry
            # marker can be gone; the file name still identifies it.
            named = notes_dir / (slugify(wanted) + ".md")
            if named.is_file():
                try:
                    text = named.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                if marker in text:
                    return named
        # The key is known and no card carries it: this entry is new.
        return None
    if wanted:
        for candidate, text in matches:
            heading = text.lstrip().splitlines()[0] if text.strip() else ""
            if heading.lstrip("# ").strip() == wanted:
                return candidate
    for candidate, text in matches:
        if "来源条目：" not in text:
            # A card written before the entry marker existed: it belongs to
            # this source and to this entry.
            return candidate
    # A card written before the entry marker existed still belongs to this
    # source; accept it only when it is unambiguous.
    if len(matches) == 1:
        return matches[0][0]
    return None


def collect_files(project_path, files):
    if files is not None:
        if not isinstance(files, list):
            raise ToolError("files must be a list of absolute paths")
        selected = []
        for value in files:
            if not isinstance(value, str) or not value.strip():
                raise ToolError("files entries must be non-empty absolute paths")
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                raise ToolError("files entries must be absolute: %s" % value)
            candidate = candidate.resolve()
            if not candidate.is_file():
                raise ToolError("file does not exist: %s" % candidate)
            if candidate.suffix.lower() not in (".pdf", ".bib"):
                raise ToolError("only PDF and .bib files are supported: %s" % candidate)
            selected.append(candidate)
        return selected
    papers = project_path / "papers"
    if not papers.is_dir():
        return []
    found = []
    for candidate in sorted(papers.rglob("*")):
        if candidate.is_file() and candidate.suffix.lower() in (".pdf", ".bib"):
            found.append(candidate)
    return found


def _bib_entry_metadata(entry, source):
    """Turn one parsed BibTeX entry into the note-card metadata shape."""
    metadata = dict(entry)
    authors = []
    for chunk in re.split(r"\s+and\s+", metadata.get("author", "")):
        chunk = chunk.strip()
        if chunk:
            authors.append(chunk)
    metadata["authors"] = authors
    metadata["title"] = metadata.get("title") or source.stem
    metadata["year"] = year_from_date(metadata.get("year", ""))
    metadata["doi"] = metadata.get("doi", "")
    metadata["url"] = metadata.get("url", "")
    metadata["abstract"] = metadata.get("abstract", "")
    return metadata


def tool_intake_papers(arguments):
    project_path = require_absolute_dir(arguments.get("path"))
    files = collect_files(project_path, arguments.get("files"))
    notes_dir = project_path / "notes"
    processed = []
    skipped = []
    failures = []
    notes = []
    deadline = time.monotonic() + MAX_CALL_SECONDS
    for source in files:
        try:
            if source.suffix.lower() == ".pdf":
                text, raw_metadata, extractor = extract_pdf(source)
                candidates = [guess_pdf_metadata(text, raw_metadata)]
                extraction_note = "PDF 文本由 %s 抽取，字段为候选值" % extractor
            else:
                # A .bib file may hold many entries: each one becomes its own
                # note card, and a broken entry does not lose the others.
                candidates = [_bib_entry_metadata(entry, source)
                              for entry in parse_bib(source)]
                extraction_note = "BibTeX 字段解析"
            notes_dir.mkdir(parents=True, exist_ok=True)
            for metadata in candidates:
                try:
                    existing = existing_note_for_source(
                        notes_dir, project_path, source, metadata.get("key"),
                        metadata.get("title"))
                    if existing is not None:
                        skipped.append({"source": str(source), "note": str(existing),
                                        "reason": "note already exists"})
                        continue
                    metadata, lookup_note = complete_metadata(metadata, deadline)
                    note_text = extraction_note
                    if lookup_note:
                        note_text += "；OpenAlex 补全：%s" % lookup_note
                    # A slug collision (truncated or empty title) gets a
                    # numeric suffix; an existing card is never overwritten.
                    target, skip_reason = resolve_note_target(
                        notes_dir, project_path, metadata, source)
                    if skip_reason:
                        skipped.append({"source": str(source), "note": str(target),
                                        "reason": skip_reason})
                        continue
                    with target.open("x", encoding="utf-8") as stream:
                        stream.write(render_note(metadata, source, project_path, note_text,
                                                metadata.get("key")))
                    notes.append(str(target))
                    processed.append(str(source))
                except FileExistsError:
                    skipped.append({"source": str(source),
                                    "reason": "note already exists"})
                except (ToolError, OSError) as error:
                    failures.append({"source": str(source), "error": str(error)})
        except (ToolError, OSError) as error:
            failures.append({"source": str(source), "error": str(error)})
    return {
        "path": str(project_path),
        "processed": len(processed),
        "skipped": len(skipped),
        "notes": notes,
        "failures": failures,
        "processed_files": processed,
        "skipped_files": skipped,
    }


# ---------------------------------------------------------------------------
# init_project: deterministic scaffolding for the methodology and ARIZ/TRIZ
# workspaces.  No network, no overwrite, no delete: an existing file is always
# skipped and reported, so the call is idempotent.
# ---------------------------------------------------------------------------

PROJECT_DIRECTORIES = (
    ("papers",),
    ("papers", "_inbox"),
    ("notes",),
    ("innovation",),
)

PROJECT_SKELETONS = {
    "protocol.md": """# 研究方案（Protocol）

> 由 Trinno `init_project` 生成的骨架；由智能体在 `research-methodology` skill 引导下补全。
> 方案先于检索定稿；此后的任何修改都应在「修订记录」中注明日期与理由（预注册式实践）。

## 1. 研究问题

- 研究问题（一句话）：<!-- 待智能体填写 -->
- 问题框架（定量干预类用 PICO：Population / Intervention / Comparison / Outcome；
  定性或综述类用 SPIDER：Sample / Phenomenon of Interest / Design / Evaluation / Research type）：
  <!-- 待智能体填写 -->
- 子问题列表：<!-- 待智能体填写 -->

## 2. 纳入与排除标准

| 维度 | 纳入 | 排除 |
|------|------|------|
| 研究对象 | <!-- 待智能体填写 --> | <!-- 待智能体填写 --> |
| 方法/设计 | <!-- 待智能体填写 --> | <!-- 待智能体填写 --> |
| 时间范围 | <!-- 待智能体填写 --> | <!-- 待智能体填写 --> |
| 语言 | <!-- 待智能体填写 --> | <!-- 待智能体填写 --> |
| 出版类型 | <!-- 待智能体填写 --> | <!-- 待智能体填写 --> |

## 3. 检索策略（可复现）

对每个检索式记录：概念块、同义词、布尔组合、目标源、执行日期、命中数。

| # | 概念块与同义词 | 检索式（原样） | 源 | 执行日期 | 命中数 |
|---|----------------|----------------|-----|----------|--------|
| 1 | <!-- 待智能体填写 --> | <!-- 待智能体填写 --> | OpenAlex / arXiv | <!-- 待智能体填写 --> | <!-- 待智能体填写 --> |

## 4. 筛选与数据抽取计划

- 筛选流程：题录去重 → 标题/摘要初筛 → 全文复筛（记录于 `screening-log.md`）。
- 每篇纳入文献抽取：问题、方法、数据、结论、局限（写入 `notes/` 摘要卡）。

## 5. 质量评估计划

- 评估工具（按研究类型选择，见 `quality-appraisal.md`）：<!-- 待智能体填写 -->
- 证据分级方法：<!-- 待智能体填写 -->

## 6. 修订记录

| 日期 | 修改内容 | 理由 |
|------|----------|------|
| <!-- 待智能体填写 --> | | |
""",
    "screening-log.md": """# 筛选日志（PRISMA 式）

> 由 Trinno `init_project` 生成的骨架；由智能体在 `research-methodology` skill 引导下补全。
> 只追加记录；每条排除必须给出理由，理由须对应 `protocol.md` 的纳入/排除标准。

## 1. 流程计数（PRISMA flow）

| 阶段 | 数量 | 备注 |
|------|------|------|
| 检索命中（各源合计） | <!-- 待智能体填写 --> | |
| 去重后 | <!-- 待智能体填写 --> | reading-list.md 已按 DOI/标题去重 |
| 标题/摘要初筛排除 | <!-- 待智能体填写 --> | |
| 全文复筛排除 | <!-- 待智能体填写 --> | |
| 最终纳入 | <!-- 待智能体填写 --> | |

## 2. 初筛决定（标题/摘要）

| 题录（reading-list 链接或 DOI） | 决定（纳入/排除） | 理由（对应标准编号） | 日期 |
|--------------------------------|-------------------|----------------------|------|
| <!-- 待智能体填写 --> | | | |

## 3. 全文复筛决定

| 题录 | 决定 | 理由 | 日期 |
|------|------|------|------|
| <!-- 待智能体填写 --> | | | |

## 4. 分歧与备注

<!-- 待智能体填写：判断存疑的条目、需要读者裁定的边界情况 -->
""",
    "quality-appraisal.md": """# 证据质量评估

> 由 Trinno `init_project` 生成的骨架；由智能体在 `research-methodology` skill 引导下补全。
> 按研究类型选择评估思路：随机对照试验 → RoB 2 维度；非随机干预研究 → ROBINS-I 维度；
> 定性研究 → CASP 定性清单；方法类/工程类论文 → 内部效度、外部效度、可复现性三问。

## 1. 逐篇评估

| 摘要卡（notes/ 路径） | 研究类型 | 评估工具 | 主要偏倚风险/局限 | 总体评级（高/中/低） |
|----------------------|----------|----------|--------------------|----------------------|
| <!-- 待智能体填写 --> | | | | |

## 2. 评估依据

对每篇「低」或「中」评级，写明具体依据（样本、对照、测量、混杂、报告选择性等），并链接证据位置。

<!-- 待智能体填写 -->

## 3. 证据体结论

- 各主题结论的证据强度（强/中/弱/仅个案）：<!-- 待智能体填写 -->
- 对 `gaps.md` 缺口强度标注的输入：<!-- 待智能体填写 -->
""",
    os.path.join("innovation", "triz-analysis.md"): """# TRIZ 系统分析

> 由 Trinno `init_project` 生成的骨架；由智能体在 `ariz-triz` skill 引导下补全。
> 输入来自 `gaps.md` 的缺口与 `notes/` 的证据；术语保留英文原词。

## 1. 系统定义

- 工程/研究系统及其主要功能（Main Useful Function）：<!-- 待智能体填写 -->
- 系统边界、超系统（supersystem）、子系统：<!-- 待智能体填写 -->
- 当前实现该功能的工作原理（一句话 + 证据链接）：<!-- 待智能体填写 -->

## 2. 最终理想解（IFR, Ideal Final Result）

- IFR 表述（系统自身消除有害作用/自行实现所需功能，不引入新代价）：<!-- 待智能体填写 -->
- 与 IFR 的差距（是什么阻碍了它）：<!-- 待智能体填写 -->

## 3. 矛盾

### 3.1 技术矛盾（Technical Contradiction）

| # | 改善的参数 | 恶化的参数 | 证据链接 | 候选发明原理（40 principles 编号） |
|---|-----------|-----------|----------|-----------------------------------|
| 1 | <!-- 待智能体填写 --> | | | |

### 3.2 物理矛盾（Physical Contradiction）

| # | 同一参数的相反要求（既要 A 又要非 A） | 分离思路（时间/空间/条件/整体-部分） |
|---|----------------------------------------|--------------------------------------|
| 1 | <!-- 待智能体填写 --> | |

## 4. 资源分析（Resources）

| 类别 | 可用资源 | 来源/证据 |
|------|----------|-----------|
| 物质资源（系统内/超系统闲置物） | <!-- 待智能体填写 --> | |
| 能量/场资源 | <!-- 待智能体填写 --> | |
| 信息资源（数据、先验、结构） | <!-- 待智能体填写 --> | |
| 时间/空间资源 | <!-- 待智能体填写 --> | |
| 功能资源（现有部件的副功能） | <!-- 待智能体填写 --> | |

## 5. 进化趋势（Trends of Evolution）

- 本系统适用的趋势（理想化程度提升、动态化、向微观级、协调性、S 曲线位置等）：<!-- 待智能体填写 -->
""",
    os.path.join("innovation", "ariz-worksheet.md"): """# ARIZ-85C 工作单

> 由 Trinno `init_project` 生成的骨架；由智能体在 `ariz-triz` skill 引导下逐步推演。
> 每一步先写结论再写依据；推演卡住时按 ARIZ 规则回溯到更早步骤修改问题表述，回溯记入第 10 节。

## Part 1 问题分析（从模糊情境到最小问题）

- 1.1 迷你问题（mini-problem）：系统在不复杂化的前提下消除有害作用/获得所需性质：<!-- 待智能体填写 -->
- 1.2 冲突对：工具（tool）— 制品（artifact）：<!-- 待智能体填写 -->
- 1.3 两种作用图式（现状 vs 期望）：<!-- 待智能体填写 -->
- 1.4 选择更容易实现的那对冲突：<!-- 待智能体填写 -->
- 1.5 强化冲突（极端化表述）：<!-- 待智能体填写 -->
- 1.6 模型化问题：作用区（operative zone）、作用时间（operative time）、物质-场资源：<!-- 待智能体填写 -->
- 1.7 可否用标准解（standards）直接求解：<!-- 待智能体填写 -->

## Part 2 问题模型分析

- 2.1 IFR（引用 triz-analysis.md 第 2 节或改写）：<!-- 待智能体填写 -->
- 2.2 物理矛盾（作用区内同一要素的相反要求）：<!-- 待智能体填写 -->
- 2.3 若物理矛盾可解 → 跳到 Part 7；否则继续。

## Part 3 IFR 与物理矛盾的表述

- 3.1 宏观物理矛盾：<!-- 待智能体填写 -->
- 3.2 IFR 的操作性表述（X 元素自行…）：<!-- 待智能体填写 -->

## Part 4 物质-场资源动员

- 4.1–4.5 系统内、超系统、派生资源清单与组合（引用 triz-analysis.md 第 4 节）：<!-- 待智能体填写 -->

## Part 5 知识库应用

- 5.1 标准解 / 40 发明原理 / 分离原理的候选（编号 + 映射理由）：<!-- 待智能体填写 -->
- 5.2 类似问题的已知解法（文献证据链接）：<!-- 待智能体填写 -->
- 5.3 若得到物理解 → 跳到 Part 7。

## Part 6 变换或替换问题

- 若未得解：改写问题（换冲突对、换层级、反问题），记录新表述并回到 Part 1：<!-- 待智能体填写 -->

## Part 7 解法评估

- 7.1 对照 IFR 检查（是否自消矛盾、是否引入新代价）：<!-- 待智能体填写 -->
- 7.2 专利/文献新颖性初查（用 search_literature 验证，记录检索式）：<!-- 待智能体填写 -->
- 7.3 子问题清单（实现该解还缺什么）：<!-- 待智能体填写 -->

## Part 8 解法利用

- 8.1 该解可推广到的其他问题/超系统变化：<!-- 待智能体填写 -->

## Part 9 过程复盘

- 9.1 各步实际路径、卡点与回溯：<!-- 待智能体填写 -->

## 10. 回溯记录

| 日期 | 从哪一步回到哪一步 | 原因 | 修改后的表述 |
|------|--------------------|------|--------------|
| <!-- 待智能体填写 --> | | | |
""",
    os.path.join("innovation", "solutions.md"): """# 候选创新点与验证计划

> 由 Trinno `init_project` 生成的骨架；由智能体在 `ariz-triz` skill 引导下补全。
> 每个候选解必须可验证：写明假设、验证实验/分析与成功判据；通过评估的解回写 `proposal-draft.md` 的「创新点」。

## 1. 候选解列表

| # | 解法（一句话） | 来源（ARIZ 步骤/发明原理编号） | 消除的矛盾 | 新颖性证据（检索式 + 结果链接） | 状态（候选/采纳/放弃） |
|---|----------------|--------------------------------|------------|----------------------------------|------------------------|
| 1 | <!-- 待智能体填写 --> | | | | |

## 2. 采纳解的验证计划

对每个「采纳」的解：

- 假设（可证伪表述）：<!-- 待智能体填写 -->
- 验证方法（实验/仿真/理论证明）与数据：<!-- 待智能体填写 -->
- 成功判据（量化阈值）：<!-- 待智能体填写 -->
- 风险与备选：<!-- 待智能体填写 -->

## 3. 回写记录

| 日期 | 回写到 proposal-draft.md 的创新点编号 | 备注 |
|------|----------------------------------------|------|
| <!-- 待智能体填写 --> | | |
""",
    "reproducibility.md": """# 可复现性清单

> 由 Trinno `init_project` 生成的骨架；由智能体在 `research-methodology` skill 引导下补全。
> 目标：第三方仅凭本课题文件夹即可重跑检索、复核筛选并追踪每条结论的证据。

## 1. 检索可复现

- [ ] 每条检索式、源、执行日期、命中数已记入 `protocol.md` 第 3 节
- [ ] `reading-list.md` 保留了检索词与时间戳（工具自动记录）
- [ ] 去重规则已知（DOI 优先，其次归一化标题）

## 2. 筛选可复核

- [ ] 每条排除在 `screening-log.md` 有理由且对应纳排标准
- [ ] PRISMA 流程计数与各文件一致

## 3. 结论可追溯

- [ ] `notes/` 每张卡的结论有证据位置（页码/章节/DOI）
- [ ] `gaps.md` 每条缺口有证据链接与强度标注
- [ ] `proposal-draft.md` 每条事实性论断回指 notes/reading-list/DOI

## 4. 数据与代码（如适用）

- 数据来源与获取方式：<!-- 待智能体填写 -->
- 代码/脚本位置与运行方式：<!-- 待智能体填写 -->
- 环境（语言、版本、依赖）：<!-- 待智能体填写 -->
- 随机种子/超参数：<!-- 待智能体填写 -->

## 5. 偏差自查

- 检索偏差（仅英文、仅两个源）与缓解：<!-- 待智能体填写 -->
- 智能体分析偏差（幻觉、过度概括）的复核方式：<!-- 待智能体填写 -->
""",
}


def tool_init_project(arguments):
    project_path = require_absolute_dir(arguments.get("path"))
    directories = []
    for parts in PROJECT_DIRECTORIES:
        target = project_path.joinpath(*parts)
        target.mkdir(parents=True, exist_ok=True)
        directories.append(str(target))
    created = []
    skipped = []
    failures = []
    for relative, content in PROJECT_SKELETONS.items():
        target = project_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Exclusive create: an existing file is never overwritten.
            with target.open("x", encoding="utf-8") as stream:
                stream.write(content)
            created.append(str(target))
        except FileExistsError:
            skipped.append({"path": str(target), "reason": "already exists"})
        except OSError as error:
            failures.append({"path": str(target), "error": str(error)})
    return {
        "path": str(project_path),
        "created": created,
        "skipped": skipped,
        "directories": directories,
        "failures": failures,
    }


TOOL_HANDLERS = {
    "search_literature": tool_search_literature,
    "intake_papers": tool_intake_papers,
    "init_project": tool_init_project,
}

TOOL_DESCRIPTORS = {
    "search_literature": {
        "name": "search_literature",
        "description": "Search OpenAlex and arXiv for literature on a research topic, append the "
                       "deduplicated results to the project's reading-list.md, and optionally "
                       "download arXiv PDFs into papers/_inbox/.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Absolute path to the research project folder."},
                "query": {"type": "string", "description": "Search query."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10,
                          "description": "Maximum results per source."},
                "download": {"type": "boolean", "default": True,
                             "description": "Download arXiv PDFs into papers/_inbox/."},
                "max_downloads": {"type": "integer", "minimum": 0, "maximum": 50, "default": 2,
                                  "description": "Maximum number of PDFs downloaded in this call."},
            },
            "required": ["path", "query"],
            "additionalProperties": False,
        },
    },
    "intake_papers": {
        "name": "intake_papers",
        "description": "Turn local PDF and BibTeX papers into per-paper markdown note card "
                       "skeletons under the project's notes/ directory, completing missing "
                       "metadata from OpenAlex. Existing notes are never overwritten.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Absolute path to the research project folder."},
                "files": {"type": "array", "items": {"type": "string"},
                          "description": "Optional list of absolute PDF or .bib file paths."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "init_project": {
        "name": "init_project",
        "description": "Create the research project skeleton: papers/_inbox/, notes/ and "
                       "innovation/ directories plus markdown skeletons for the study "
                       "protocol, PRISMA screening log, quality appraisal, TRIZ analysis, "
                       "ARIZ-85C worksheet, solutions log and reproducibility checklist. "
                       "Existing files are never overwritten; the call is idempotent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Absolute path to the research project folder."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def tool_list():
    """Describe the declared tools for a client that asks for the catalogue."""
    return {"tools": [TOOL_DESCRIPTORS[name] for name in TOOLS if name in TOOL_DESCRIPTORS]}


def handle(request):
    method = request.get("method")
    params = request.get("params") or {}
    if method == "initialize":
        return {"result": {"protocolVersion": "1.0",
                           "token": params.get("token", ""),
                           "name": "trinno"}}, True
    if method == "shutdown":
        return {"result": {}}, False
    if method in ("tools/list", "tools.list"):
        return {"result": tool_list()}, True
    if method == "tools/call":
        name = str(params.get("name") or "").rsplit("__", 1)[-1]
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {"error": {"code": -32601, "message": "unknown tool %r" % name}}, True
        try:
            return {"result": handler(params.get("arguments") or {})}, True
        except ToolError as error:
            log_error("tool %s refused: %s" % (name, error))
            return {"error": {"code": -32000, "message": str(error)}}, True
        except Exception as error:  # a bug is reported, never a silent success
            log_error("tool %s failed: %s: %s" % (name, type(error).__name__, error))
            return {"error": {"code": -32603,
                               "message": "%s: %s" % (type(error).__name__, error)}}, True
    log_error("unsupported method %r" % method)
    return {"error": {"code": -32601, "message": "unsupported method %r" % method}}, True


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError as error:
            # A malformed line is a protocol error, not a silent skip.
            log_error("ignoring malformed JSON line: %s" % error)
            continue
        if not isinstance(request, dict):
            log_error("ignoring non-object JSON line")
            continue
        outcome, keep_going = handle(request)
        if outcome is not None:
            envelope = {"jsonrpc": "2.0", "id": request.get("id")}
            envelope.update(outcome)
            emit(envelope)
        if not keep_going:
            break


if __name__ == "__main__":
    main()
