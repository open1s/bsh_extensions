"""Self-check for this package: no host, no network.

Run it with:  python3 -m unittest discover -s tests
"""

import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402

CONTRIBUTION_FILES = {
    "tool": "tools/{id}.json",
    "command": "commands/{id}.md",
    "panel": "panels/{id}.json",
    "prompt": "prompts/{id}.md",
    "context": "contexts/{id}.md",
    "skill": "skills/{id}/SKILL.md",
    "workflow": "workflows/{id}.json",
    "theme": "themes/{id}.json",
    "preset": "presets/{id}.json",
    "model-provider": "providers/models/{id}.json",
    "agent-provider": "providers/agents/{id}.json",
    "language": "languages/{id}.json",
    "integration": "integrations/{id}.json",
}


def manifest():
    with (ROOT / "extension.toml").open("rb") as stream:
        return tomllib.load(stream)


class PackageTest(unittest.TestCase):
    def test_schema_version(self):
        self.assertEqual(manifest()["schema_version"], "2.0")

    def test_identity(self):
        identity = manifest()["extension"]
        for key in ("id", "name", "version", "description"):
            self.assertTrue(identity.get(key), key)

    def test_declared_files_exist(self):
        for contribution in manifest().get("contribution", []):
            template = CONTRIBUTION_FILES.get(contribution["kind"])
            if template is None:
                continue
            path = ROOT / template.format(id=contribution["id"])
            self.assertTrue(path.is_file(), str(path))

    def test_every_json_contribution_parses(self):
        for contribution in manifest().get("contribution", []):
            template = CONTRIBUTION_FILES.get(contribution["kind"])
            if template is None or not template.endswith(".json"):
                continue
            path = ROOT / template.format(id=contribution["id"])
            json.loads(path.read_text(encoding="utf-8"))

    def test_contribution_surface(self):
        kinds = sorted((item["kind"], item["id"]) for item in manifest().get("contribution", []))
        self.assertEqual(kinds, [
            ("skill", "ariz-triz"),
            ("skill", "research-methodology"),
            ("skill", "research-workflow"),
            ("tool", "analyze_gaps"),
            ("tool", "init_project"),
            ("tool", "intake_papers"),
            ("tool", "search_literature"),
        ])

    def test_runtime_catalogue_matches_manifest(self):
        listed = {tool["name"] for tool in server.tool_list()["tools"]}
        declared = {item["id"] for item in manifest().get("contribution", [])
                    if item["kind"] == "tool"}
        self.assertEqual(listed, declared)

    def test_tool_schemas_use_path_argument(self):
        for tool_id in ("search_literature", "intake_papers", "init_project", "analyze_gaps"):
            document = json.loads((ROOT / "tools" / (tool_id + ".json")).read_text(encoding="utf-8"))
            properties = document["input_schema"]["properties"]
            self.assertIn("path", properties, tool_id)
            self.assertIn("path", document["input_schema"]["required"], tool_id)

    def test_no_delete_operations_in_code(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        for forbidden in ("os.remove", "os.rmdir", "shutil.rmtree", "unlink(", "rm -rf"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_only_allowed_hosts(self):
        self.assertEqual(server.ALLOWED_HOSTS, {
            "api.openalex.org", "export.arxiv.org", "arxiv.org"})

    def test_url_allow_list(self):
        server.safe_url("https://api.openalex.org/works?search=x")
        with self.assertRaises(server.ToolError):
            server.safe_url("https://example.com/works")
        with self.assertRaises(server.ToolError):
            server.safe_url("http://api.openalex.org/works")


class ReadingListTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def entries(self):
        return [
            {"title": "A Study of Widgets", "authors": ["Doe, J."], "year": 2020,
             "abstract": "Widgets.", "url": "https://example.org/a", "doi": "https://doi.org/10.1/a",
             "cited_by_count": 3, "source": "Journal", "provider": "openalex"},
            {"title": "Another Study", "authors": ["Roe, R."], "year": 2021,
             "abstract": "More.", "url": "https://example.org/b", "doi": "",
             "cited_by_count": 0, "source": "arXiv", "provider": "arxiv"},
        ]

    def test_append_and_dedupe(self):
        reading, added, skipped = server.append_reading_list(
            self.project, self.entries(), "widgets", "2026-01-01T00:00:00+00:00")
        self.assertEqual(len(added), 2)
        self.assertEqual(skipped, [])
        first = reading.read_text(encoding="utf-8")
        self.assertIn("A Study of Widgets", first)
        self.assertIn("Widgets.", first)

        _reading, added2, skipped2 = server.append_reading_list(
            self.project, self.entries(), "widgets", "2026-01-02T00:00:00+00:00")
        self.assertEqual(added2, [])
        self.assertEqual(len(skipped2), 2)
        self.assertEqual(reading.read_text(encoding="utf-8"), first)

    def test_dedupe_by_normalized_title(self):
        entries = self.entries()
        entries[1]["title"] = "another   study"
        _reading, added, _skipped = server.append_reading_list(
            self.project, entries, "q", "2026-01-01T00:00:00+00:00")
        self.assertEqual(len(added), 2)
        _reading, added2, _skipped2 = server.append_reading_list(
            self.project, entries, "q", "2026-01-01T00:00:00+00:00")
        self.assertEqual(len(added2), 0)

    def test_existing_handwritten_notes_are_kept(self):
        reading = self.project / "reading-list.md"
        reading.write_text("# Reading list\n\n手写批注：请关注实验设置。\n", encoding="utf-8")
        server.append_reading_list(self.project, self.entries(), "q", "2026-01-01T00:00:00+00:00")
        text = reading.read_text(encoding="utf-8")
        self.assertIn("手写批注", text)
        self.assertIn("A Study of Widgets", text)


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        (self.project / "papers" / "_inbox").mkdir(parents=True)
        self.addCleanup(self.temp.cleanup)
        # The unit tests never touch the network: OpenAlex completion is stubbed.
        self.lookup = server.openalex_by_title
        server.openalex_by_title = lambda _title, deadline=None: None
        self.addCleanup(self._restore_lookup)

    def _restore_lookup(self):
        server.openalex_by_title = self.lookup

    def test_bibtex_intake_creates_note(self):
        bib = self.project / "papers" / "sample.bib"
        bib.write_text(
            "@article{key2020,\n"
            "  title = {Deep Widget Learning},\n"
            "  author = {Doe, Jane and Roe, Richard},\n"
            "  year = {2020},\n"
            "  doi = {10.1000/widget},\n"
            "  abstract = {A study about widgets.}\n"
            "}\n", encoding="utf-8")
        result = server.tool_intake_papers({"path": str(self.project)})
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["failures"], [])
        note = Path(result["notes"][0])
        self.assertTrue(note.is_file())
        text = note.read_text(encoding="utf-8")
        self.assertIn("Deep Widget Learning", text)
        self.assertIn("待智能体填写", text)
        self.assertIn("10.1000/widget", text)

    def test_second_intake_makes_no_metadata_lookup(self):
        bib = self.project / "papers" / "sample.bib"
        bib.write_text("@article{k, title={T}, author={A}, year={2020}}\n", encoding="utf-8")
        calls = []

        def _lookup(title, deadline=None):
            calls.append(title)
            return None

        server.openalex_by_title = _lookup
        first = server.tool_intake_papers({"path": str(self.project)})
        self.assertEqual(first["processed"], 1)
        self.assertEqual(len(calls), 1)

        second = server.tool_intake_papers({"path": str(self.project)})
        self.assertEqual(second["processed"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(calls, ["T"], "an already-intaken paper must not trigger another lookup")

    def test_existing_note_is_not_overwritten(self):
        bib = self.project / "papers" / "sample.bib"
        bib.write_text("@article{k, title={T}, author={A}, year={2020}}\n", encoding="utf-8")
        first = server.tool_intake_papers({"path": str(self.project)})
        note = Path(first["notes"][0])
        note.write_text("手写内容\n", encoding="utf-8")
        second = server.tool_intake_papers({"path": str(self.project)})
        self.assertEqual(second["processed"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(note.read_text(encoding="utf-8"), "手写内容\n")

    def test_papers_directory_is_not_modified(self):
        bib = self.project / "papers" / "sample.bib"
        bib.write_text("@article{k, title={T}, author={A}, year={2020}}\n", encoding="utf-8")
        before = bib.read_bytes()
        server.tool_intake_papers({"path": str(self.project)})
        self.assertEqual(bib.read_bytes(), before)

    def test_relative_path_is_refused(self):
        with self.assertRaises(server.ToolError):
            server.tool_intake_papers({"path": "relative/path"})

    def test_missing_path_is_refused(self):
        with self.assertRaises(server.ToolError):
            server.tool_intake_papers({"path": "/nonexistent/project/folder"})


class SearchArgumentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        # Argument validation must not depend on the network: OpenAlex gets
        # JSON, arXiv gets a minimal valid Atom feed.
        self.original = server.http_get
        atom = (b'<feed xmlns="http://www.w3.org/2005/Atom">'
                b'<entry><title>stub</title></entry></feed>')
        def _stub(_url, _max_bytes, accept=None, _deadline=None):
            if accept == "application/atom+xml":
                return atom, "application/atom+xml", ""
            return b'{"results": []}', "application/json", ""
        server.http_get = _stub
        self.addCleanup(self._restore)

    def _restore(self):
        server.http_get = self.original

    def test_limit_range(self):
        with self.assertRaises(server.ToolError):
            server.tool_search_literature({"path": str(self.project), "query": "x", "limit": 0})
        with self.assertRaises(server.ToolError):
            server.tool_search_literature({"path": str(self.project), "query": "x", "limit": 51})

    def test_query_required(self):
        with self.assertRaises(server.ToolError):
            server.tool_search_literature({"path": str(self.project)})

    def test_max_downloads_must_be_a_non_negative_integer(self):
        with self.assertRaises(server.ToolError):
            server.tool_search_literature({
                "path": str(self.project), "query": "x", "download": False, "max_downloads": -1})
        with self.assertRaises(server.ToolError):
            server.tool_search_literature({
                "path": str(self.project), "query": "x", "download": False, "max_downloads": "many"})

    def test_max_downloads_is_bounded_by_the_declared_maximum(self):
        with self.assertRaises(server.ToolError):
            server.tool_search_literature({
                "path": str(self.project), "query": "x", "download": False, "max_downloads": 51})
        result = server.tool_search_literature({
            "path": str(self.project), "query": "x", "download": False, "max_downloads": 50})
        self.assertEqual(result["failures"], [])


class InitProjectTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_creates_directories_and_skeletons(self):
        result = server.tool_init_project({"path": str(self.project)})
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(len(result["created"]), 7)
        for relative in ("protocol.md", "screening-log.md", "quality-appraisal.md",
                         "reproducibility.md", "innovation/triz-analysis.md",
                         "innovation/ariz-worksheet.md", "innovation/solutions.md"):
            target = self.project / relative
            self.assertTrue(target.is_file(), relative)
            self.assertIn("待智能体填写", target.read_text(encoding="utf-8"), relative)
        for relative in ("papers/_inbox", "notes", "innovation"):
            self.assertTrue((self.project / relative).is_dir(), relative)

    def test_idempotent_and_never_overwrites(self):
        first = server.tool_init_project({"path": str(self.project)})
        protocol = self.project / "protocol.md"
        protocol.write_text("手写方案\n", encoding="utf-8")
        second = server.tool_init_project({"path": str(self.project)})
        self.assertEqual(second["created"], [])
        self.assertEqual(len(second["skipped"]), len(first["created"]))
        self.assertEqual(second["failures"], [])
        self.assertEqual(protocol.read_text(encoding="utf-8"), "手写方案\n")

    def test_no_network_access(self):
        original = server.http_get

        def _refuse(*_args, **_kwargs):
            raise AssertionError("init_project must not touch the network")

        server.http_get = _refuse
        try:
            result = server.tool_init_project({"path": str(self.project)})
        finally:
            server.http_get = original
        self.assertEqual(result["failures"], [])

    def test_relative_path_is_refused(self):
        with self.assertRaises(server.ToolError):
            server.tool_init_project({"path": "relative/path"})

    def test_missing_path_is_refused(self):
        with self.assertRaises(server.ToolError):
            server.tool_init_project({"path": "/nonexistent/project/folder"})

    def test_skeletons_cover_ariz_parts_and_triz_concepts(self):
        server.tool_init_project({"path": str(self.project)})
        worksheet = (self.project / "innovation" / "ariz-worksheet.md").read_text(encoding="utf-8")
        for part in ("Part 1", "Part 2", "Part 3", "Part 4", "Part 5",
                     "Part 6", "Part 7", "Part 8", "Part 9"):
            self.assertIn(part, worksheet)
        analysis = (self.project / "innovation" / "triz-analysis.md").read_text(encoding="utf-8")
        for concept in ("IFR", "技术矛盾", "物理矛盾", "资源"):
            self.assertIn(concept, analysis)


class AnalyzeGapsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.notes_dir = self.project / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.temp.cleanup)

    def test_analyze_gaps_creates_gaps_md(self):
        # Create a sample note card
        note_content = """# Test Paper

- 作者：Doe, Jane
- 年份：2020
- DOI：10.1000/test
- 来源文件：`papers/sample.pdf`
- 证据链接：https://example.org/test

## 摘要

This is a test paper about widgets.

## 研究问题

如何提高小部件的性能？

## 方法

实验方法

## 结论

该方法有效

## 局限

样本量有限
"""
        note_path = self.notes_dir / "test-paper.md"
        note_path.write_text(note_content, encoding="utf-8")

        result = server.tool_analyze_gaps({"path": str(self.project)})
        self.assertEqual(result["cards_analyzed"], 1)
        self.assertTrue(result["gaps_file"].endswith("gaps.md"))
        self.assertIn("has_gaps", result)
        self.assertTrue(result["has_gaps"])

        gaps_file = Path(result["gaps_file"])
        self.assertTrue(gaps_file.exists())
        content = gaps_file.read_text(encoding="utf-8")
        self.assertIn("# 研究缺口分析", content)
        self.assertIn("主题：性能", content)

    def test_analyze_gaps_requires_notes(self):
        with self.assertRaises(server.ToolError) as context:
            server.tool_analyze_gaps({"path": str(self.project)})
        self.assertIn("没有找到笔记卡", str(context.exception))

    def test_analyze_gaps_fails_if_gaps_md_exists(self):
        # Create a sample note card
        note_content = """# Test Paper

- 作者：Doe, Jane
- 年份：2020
- DOI：10.1000/test
- 来源文件：`papers/sample.pdf`
- 证据链接：https://example.org/test

## 摘要

This is a test paper about widgets.
"""
        note_path = self.notes_dir / "test-paper.md"
        note_path.write_text(note_content, encoding="utf-8")

        # First call creates gaps.md
        server.tool_analyze_gaps({"path": str(self.project)})

        # Second call should fail
        with self.assertRaises(server.ToolError) as context:
            server.tool_analyze_gaps({"path": str(self.project)})
        self.assertIn("gaps.md 已存在", str(context.exception))

    def test_analyze_gaps_relative_path_refused(self):
        with self.assertRaises(server.ToolError):
            server.tool_analyze_gaps({"path": "relative/path"})

    def test_analyze_gaps_missing_path_refused(self):
        with self.assertRaises(server.ToolError):
            server.tool_analyze_gaps({"path": "/nonexistent/project/folder"})


class DownloadBudgetTest(unittest.TestCase):
    """The PDF download budget is bounded so a tool call returns in time."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.entries = [
            {"title": "Paper %d" % index, "provider": "arxiv", "arxiv_id": "2501.%05d" % index,
             "pdf_url": "https://arxiv.org/pdf/2501.%05d" % index}
            for index in range(4)
        ]

    def _stub_http(self, calls):
        def _http_get(url, max_bytes, accept=None, deadline=None):
            calls.append(url)
            return b"%PDF-1.4 fake", "application/pdf", url
        return _http_get

    def test_download_budget_is_respected_and_resumable(self):
        calls = []
        original = server.http_get
        server.http_get = self._stub_http(calls)
        try:
            downloaded, skipped, failures, pending = server.download_arxiv_pdfs(
                self.project, self.entries, max_downloads=2)
        finally:
            server.http_get = original
        self.assertEqual(len(downloaded), 2)
        self.assertEqual(failures, [])
        self.assertEqual(len(pending), 2)
        self.assertEqual(len(calls), 2)
        inbox = self.project / "papers" / "_inbox"
        self.assertEqual(len(list(inbox.glob("*.pdf"))), 2)

        # A second call continues where the first stopped.
        calls = []
        server.http_get = self._stub_http(calls)
        try:
            downloaded2, _skipped, _failures, pending2 = server.download_arxiv_pdfs(
                self.project, self.entries, max_downloads=2)
        finally:
            server.http_get = original
        self.assertEqual(len(downloaded2), 2)
        self.assertEqual(pending2, [])
        self.assertEqual(len(list(inbox.glob("*.pdf"))), 4)

    def test_existing_pdf_is_not_downloaded_again(self):
        calls = []
        original = server.http_get
        server.http_get = self._stub_http(calls)
        try:
            server.download_arxiv_pdfs(self.project, self.entries[:1], max_downloads=1)
            downloaded, skipped, _failures, _pending = server.download_arxiv_pdfs(
                self.project, self.entries[:1], max_downloads=1)
        finally:
            server.http_get = original
        self.assertEqual(downloaded, [])
        self.assertEqual(skipped[0]["reason"], "already exists")
        self.assertEqual(len(calls), 1)

    def test_polite_sleep_is_clamped_to_the_call_deadline(self):
        calls = []
        original = server.http_get
        server.http_get = self._stub_http(calls)
        sleeps = []
        original_sleep = server.time.sleep
        server.time.sleep = lambda seconds: sleeps.append(seconds)
        try:
            # A deadline that is already nearly exhausted: the 3 s polite
            # delay must be clamped instead of sleeping past the budget.
            deadline = server.time.monotonic() + 0.5
            _downloaded, _skipped, _failures, pending = server.download_arxiv_pdfs(
                self.project, self.entries, max_downloads=4, deadline=deadline)
        finally:
            server.http_get = original
            server.time.sleep = original_sleep
        self.assertTrue(all(delay <= 0.5 for delay in sleeps), sleeps)
        self.assertTrue(pending, "entries that did not fit the budget must be reported pending")


class ProtocolTest(unittest.TestCase):
    """The JSON-RPC loop must survive malformed input and keep serving."""

    def test_non_string_method_is_rejected(self):
        outcome, keep_going = server.handle({"method": 42, "params": {}})
        self.assertIn("error", outcome)
        self.assertTrue(keep_going)

    def test_non_object_params_are_rejected(self):
        outcome, keep_going = server.handle({"method": "tools/call", "params": ["x"]})
        self.assertIn("error", outcome)
        self.assertTrue(keep_going)

    def test_non_object_arguments_are_rejected(self):
        outcome, keep_going = server.handle(
            {"method": "tools/call", "params": {"name": "init_project", "arguments": [1, 2]}})
        self.assertIn("error", outcome)
        self.assertEqual(outcome["error"]["code"], -32602)
        self.assertTrue(keep_going)

    def test_unknown_tool_is_reported_not_raised(self):
        outcome, keep_going = server.handle(
            {"method": "tools/call", "params": {"name": "nope", "arguments": {}}})
        self.assertEqual(outcome["error"]["code"], -32601)
        self.assertTrue(keep_going)

    def test_handle_never_raises_on_a_bug(self):
        original = server.TOOL_HANDLERS["init_project"]
        server.TOOL_HANDLERS["init_project"] = lambda _args: 1 / 0
        try:
            outcome, keep_going = server.handle(
                {"method": "tools/call",
                 "params": {"name": "init_project", "arguments": {}}})
        finally:
            server.TOOL_HANDLERS["init_project"] = original
        self.assertEqual(outcome["error"]["code"], -32603)
        self.assertTrue(keep_going)


class ArxivParseTest(unittest.TestCase):
    def test_dtd_entity_expansion_is_defused(self):
        payload = (b'<?xml version="1.0"?>'
                   b'<!DOCTYPE feed [<!ENTITY xxe "boom">]>'
                   b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                   b'<title>&xxe;</title></entry></feed>')
        original = server.http_get
        server.http_get = lambda *_a, **_k: (payload, "application/atom+xml", "")
        try:
            with self.assertRaises(server.ToolError):
                server.arxiv_search("x", 5)
        finally:
            server.http_get = original

    def test_arxiv_search_rejects_invalid_xml(self):
        original = server.http_get
        server.http_get = lambda *_a, **_k: (b"not xml at all", "application/atom+xml", "")
        try:
            with self.assertRaises(server.ToolError):
                server.arxiv_search("x", 5)
        finally:
            server.http_get = original


if __name__ == "__main__":
    unittest.main()
