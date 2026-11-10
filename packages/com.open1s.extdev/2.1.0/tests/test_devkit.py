"""The DevKit's own suite: no host, no dependencies.

Run it with:  python3 -m unittest discover -s tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from devkit import constants, domains, reference, util
from devkit.design import design
from devkit.handlers import dispatch
from devkit.lint import lint
from devkit.market import make_entry, market, verify
from devkit.release import bump, migrate, package
from devkit.scaffold import scaffold
from devkit.smoke import render_template, smoke
from devkit.validate import validate


class Scratch:
    """A temporary directory that cleans up after the test."""

    def __init__(self):
        self.path = Path(tempfile.mkdtemp(prefix="extdev-test-"))

    def __enter__(self):
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class IdentityTest(unittest.TestCase):
    def test_valid_extension_ids(self):
        for value in ("com.example.toolkit", "io.2code.tool", "a.b_c-d"):
            self.assertIsNone(util.check_extension_id(value), value)

    def test_invalid_extension_ids(self):
        for value in ("one-segment", "Com.Example", "com..example", "com/example/tool",
                      "com.example.-tool", ""):
            self.assertIsNotNone(util.check_extension_id(value), value)

    def test_valid_contribution_ids(self):
        for value in ("echo", "git.status", "ext-dev.check"):
            self.assertIsNone(util.check_contribution_id(value), value)

    def test_invalid_contribution_ids(self):
        for value in ("Git.Status", "git/status", ".git", "git.", ""):
            self.assertIsNotNone(util.check_contribution_id(value), value)

    def test_versions_and_ranges(self):
        self.assertIsNone(util.check_version("1.2.3"))
        self.assertIsNone(util.check_version("1.2.3-rc.1+build"))
        self.assertIsNotNone(util.check_version("1.2"))
        self.assertIsNone(util.check_requirement(">=3.0.0, <4.0.0"))
        self.assertIsNone(util.check_requirement("^1.0"))
        self.assertIsNotNone(util.check_requirement(">=3.0.0, "))

    def test_templates_render_like_the_host(self):
        self.assertEqual(render_template("hello {{name}}", {"name": "world"}), "hello world")
        self.assertEqual(render_template("{{missing}}x", {}), "x")
        self.assertEqual(render_template("{{n}}", {"n": 2}), "2")
        self.assertEqual(render_template("{{unfinished", {}), "{{unfinished")


class WalkOrderTest(unittest.TestCase):
    def test_walk_order_matches_the_host(self):
        with Scratch() as root:
            write(root, "a/x.txt", "x")
            write(root, "a.txt", "x")
            write(root, "b/y.txt", "y")
            self.assertEqual(util.walk_files(root),
                             ["a/x.txt", "a.txt", "b/y.txt"])


class ScaffoldTest(unittest.TestCase):
    def test_a_declarative_scaffold_validates_and_lints_clean(self):
        with Scratch() as root:
            scaffold({"path": str(root / "hello"), "id": "com.example.hello"})
            report = validate(root / "hello")
            self.assertTrue(report["ok"], report["findings"])
            self.assertEqual(report["runtime"], "declarative")
            self.assertEqual(report["contributions"]["tool"], 2)
            review = lint(root / "hello")
            self.assertEqual(review["summary"]["errors"], 0)

    def test_a_process_scaffold_validates(self):
        with Scratch() as root:
            scaffold({"path": str(root / "proc"), "id": "com.example.proc",
                      "runtime": "process"})
            report = validate(root / "proc")
            self.assertTrue(report["ok"], report["findings"])
            self.assertTrue((root / "proc" / "server.py").is_file())

    def test_a_non_empty_directory_needs_force(self):
        with Scratch() as root:
            target = root / "busy"
            (target).mkdir()
            write(target, "keep.txt", "x")
            with self.assertRaises(util.DevkitError):
                scaffold({"path": str(target), "id": "com.example.busy"})
            scaffold({"path": str(target), "id": "com.example.busy", "force": True})
            self.assertTrue((target / "extension.toml").is_file())

    def test_scaffold_refuses_a_relative_path(self):
        with self.assertRaises(util.DevkitError):
            scaffold({"path": "relative/hello", "id": "com.example.hello"})


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.scratch = Scratch()
        self.root = self.scratch.path / "pkg"
        scaffold({"path": str(self.root), "id": "com.example.checks"})

    def tearDown(self):
        self.scratch.__exit__()

    def codes(self):
        return {finding["rule"] for finding in validate(self.root)["findings"]}

    def test_a_clean_package_has_no_errors(self):
        self.assertTrue(validate(self.root)["ok"])

    def test_schema_version_is_enforced(self):
        path = self.root / "extension.toml"
        path.write_text(path.read_text().replace('schema_version = "2.0"',
                                                 'schema_version = "1.0"'))
        self.assertIn("manifest.schema-version", self.codes())

    def test_unknown_top_level_field_is_refused(self):
        path = self.root / "extension.toml"
        path.write_text(path.read_text() + '\n[extra]\nvalue = 1\n')
        self.assertIn("manifest.unknown-field", self.codes())

    def test_a_missing_tool_file_is_refused(self):
        (self.root / "tools" / "echo.json").unlink()
        self.assertIn("contribution.file-missing", self.codes())

    def test_declaring_the_same_id_twice_across_kinds_is_refused(self):
        path = self.root / "extension.toml"
        write(self.root, "commands/echo.md", "---\ndescription: twin\n---\n\nBody\n")
        path.write_text(path.read_text().replace(
            "[[contribution]]\nkind = \"command\"\nid = \"greet\"",
            "[[contribution]]\nkind = \"command\"\nid = \"echo\"",
        ))
        self.assertIn("contribution.duplicate", self.codes())

    def test_a_panel_node_must_have_its_fields(self):
        write(self.root, "panels/status.json",
              json.dumps({"title": "Status",
                          "view": {"schema_version": "1.0",
                                   "root": {"type": "button"}}}))
        self.assertIn("panel.node-field", self.codes())

    def test_a_process_runtime_must_ask_for_process_execute(self):
        manifest = (self.root / "extension.toml").read_text()
        manifest = manifest.replace(
            'kind = "declarative"', 'kind = "process"'
        ).replace(
            'required = ["agent.tools.register"]',
            'required = ["agent.tools.register"]'
        )
        write(self.root, "server.py", "print('x')\n")
        manifest = manifest.replace(
            "[runtime.config]\nstartup = \"on-demand\"",
            "[runtime.config]\nstartup = \"on-demand\"\nentry = \"python3\"\n"
            "protocol = \"jsonrpc-2.0\"\nargs = [\"-B\", \"server.py\"]",
        )
        (self.root / "extension.toml").write_text(manifest)
        self.assertIn("capabilities.process", self.codes())

    def test_a_symlink_is_refused(self):
        target = self.root / "README.md"
        link = self.root / "linked-readme"
        try:
            os.symlink(target, link)
        except OSError:
            self.skipTest("this platform cannot create symlinks")
        self.assertIn("package.symlink", self.codes())


class LintTest(unittest.TestCase):
    def test_an_orphan_contribution_file_is_reported(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.lint"})
            write(root / "pkg", "tools/orphan.json",
                  json.dumps({"description": "nobody declared me"}))
            review = lint(root / "pkg")
            self.assertIn("EXT060", {finding["rule"] for finding in review["findings"]})

    def test_a_credential_looking_string_is_reported(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.secret"})
            write(root / "pkg", "notes.txt", "token ghp_" + "a" * 24 + "\n")
            review = lint(root / "pkg")
            self.assertIn("EXT120", {finding["rule"] for finding in review["findings"]})

    def test_a_missing_readme_is_a_warning(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.docs"})
            (root / "pkg" / "README.md").unlink()
            review = lint(root / "pkg")
            self.assertIn("EXT001", {finding["rule"] for finding in review["findings"]})


class MarketTest(unittest.TestCase):
    def test_entry_merge_and_verify_round_trip(self):
        with Scratch() as repo:
            package_root = repo / "packages" / "com.example.hello" / "1.0.0"
            scaffold({"path": str(package_root), "id": "com.example.hello"})
            write(repo, "index.json", json.dumps({"schema_version": 1, "extensions": []}))

            entry = make_entry(package_root, repo / "index.json")
            self.assertEqual(entry["id"], "com.example.hello")
            self.assertEqual(entry["path"], "packages/com.example.hello/1.0.0")

            merged = market({"path": str(package_root), "action": "merge"}, {})
            self.assertEqual(merged["entries"], 1)
            self.assertTrue(verify(repo)["ok"], verify(repo)["problems"])

            write(package_root, "notes.txt", "one more byte\n")
            problems = verify(repo)["problems"]
            self.assertTrue(any("hash" in problem["problem"] for problem in problems),
                            problems)


    @staticmethod
    def _git(repo, *arguments):
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True, capture_output=True, text=True,
        )

    def _repo_with_package(self, root, extension_id):
        """A committed market checkout holding one scaffolded package."""
        self._git(root, "init", "-q", "-b", "main")
        self._git(root, "config", "user.email", "dev@example.test")
        self._git(root, "config", "user.name", "Dev")
        package_root = root / "packages" / extension_id / "1.0.0"
        scaffold({"path": str(package_root), "id": extension_id})
        write(root, ".gitignore", "__pycache__/\n*.pyc\n")
        write(root, "index.json", json.dumps({"schema_version": 1, "extensions": []}))
        self._git(root, "add", "-A")
        self._git(root, "commit", "-q", "-m", "the package")
        return package_root

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_the_index_hash_is_the_commit_a_clone_carries(self):
        # The reported failure: a test run left __pycache__ in the package, the
        # index was hashed from the working tree, and every install was denied
        # because a clone never has the bytecode.
        with Scratch() as repo, Scratch() as elsewhere:
            package_root = self._repo_with_package(repo, "com.example.commit")
            write(package_root, "__pycache__/devkit.cpython-313.pyc", "bytecode")
            self.assertNotEqual(util.package_hash(package_root),
                                util.head_package_hash(package_root),
                                "the premise: disk and HEAD must differ here")
            entry = market({"path": str(package_root), "action": "entry"}, {})
            self.assertEqual(entry["hash_source"], "HEAD")
            self.assertEqual(entry["hash"], util.head_package_hash(package_root))
            subprocess.run(
                ["git", "clone", "-q", str(repo), str(elsewhere / "clone")],
                check=True, capture_output=True,
            )
            checkout = elsewhere / "clone" / "packages" / "com.example.commit" / "1.0.0"
            self.assertEqual(
                util.package_hash(checkout), entry["hash"],
                "the host hashes the clone, so the index must carry that digest",
            )

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_verify_rejects_an_index_hashed_from_the_working_tree(self):
        with Scratch() as repo:
            package_root = self._repo_with_package(repo, "com.example.stale")
            write(package_root, "__pycache__/devkit.cpython-313.pyc", "bytecode")
            entry = make_entry(package_root, repo / "index.json")
            # Exactly what the old tool wrote: the hash of the files on disk.
            entry["hash"] = util.package_hash(package_root)
            write(repo, "index.json",
                  json.dumps({"schema_version": 1, "extensions": [entry]}))
            report = verify(repo)
            self.assertFalse(report["ok"], "a disk hash must not pass verification")
            self.assertTrue(
                any("hashes to" in problem["problem"] for problem in report["problems"]),
                report["problems"],
            )
            entry["hash"] = util.head_package_hash(package_root)
            write(repo, "index.json",
                  json.dumps({"schema_version": 1, "extensions": [entry]}))
            self.assertTrue(verify(repo)["ok"], verify(repo)["problems"])

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_merge_refuses_a_package_with_uncommitted_changes(self):
        with Scratch() as repo:
            package_root = self._repo_with_package(repo, "com.example.dirty")
            readme = package_root / "README.md"
            readme.write_text(readme.read_text() + "\nmore\n", encoding="utf-8")
            with self.assertRaises(util.DevkitError) as raised:
                market({"path": str(package_root), "action": "merge"}, {})
            self.assertIn("uncommitted", str(raised.exception))

    def test_a_package_outside_git_is_hashed_from_disk(self):
        with Scratch() as repo:
            package_root = repo / "packages" / "com.example.plain" / "1.0.0"
            scaffold({"path": str(package_root), "id": "com.example.plain"})
            write(repo, "index.json", json.dumps({"schema_version": 1, "extensions": []}))
            entry = market({"path": str(package_root), "action": "entry"}, {})
            self.assertEqual(entry["hash_source"], "working tree")
            self.assertEqual(entry["hash"], util.package_hash(package_root))
            self.assertTrue(entry["warnings"], "the result must say what it hashed")

    def test_verify_reports_an_unindexed_package(self):
        with Scratch() as repo:
            package_root = repo / "packages" / "com.example.missing" / "1.0.0"
            scaffold({"path": str(package_root), "id": "com.example.missing"})
            write(repo, "index.json", json.dumps({"schema_version": 1, "extensions": []}))
            report = verify(repo)
            self.assertFalse(report["ok"])
            self.assertTrue(any("not in index.json" in problem["problem"]
                                for problem in report["problems"]))


class ReleaseTest(unittest.TestCase):
    def test_bump_raises_the_version_and_writes_the_changelog(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.bump"})
            result = bump({"path": str(root / "pkg"), "release": "minor"})
            self.assertEqual(result["from"], "1.0.0")
            self.assertEqual(result["to"], "1.1.0")
            manifest = (root / "pkg" / "extension.toml").read_text()
            self.assertIn('version = "1.1.0"', manifest)
            self.assertIn("1.1.0", (root / "pkg" / "CHANGELOG.md").read_text())

    def test_package_is_deterministic(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.archive"})
            first = package({"path": str(root / "pkg"), "out": str(root / "out")})
            second = package({"path": str(root / "pkg"), "out": str(root / "out")})
            self.assertEqual(first["archive_sha256"], second["archive_sha256"])
            self.assertGreater(first["bytes"], 0)
            import tarfile
            with tarfile.open(first["archive"]) as tar:
                names = tar.getnames()
            self.assertIn("extension.toml", names)

    def test_migrate_rewrites_a_1x_manifest(self):
        with Scratch() as root:
            write(root, "pkg/extension.toml", '''
schema_version = "1.0"

[extension]
id = "com.example.legacy"
name = "Legacy"
version = "1.0.0"
description = "A 1.x manifest"

[compatibility]
bsh = ">=3.0.0, <4.0.0"
extension_api = "^1.0"

[runtime]
kind = "declarative"

[capabilities]
required = ["agent.tools.register"]

[contributes]
tools = ["echo"]
commands = ["hello"]
''')
            result = migrate({"path": str(root / "pkg"), "write": True})
            self.assertTrue(result["migrated"])
            text = (root / "pkg" / "extension.toml").read_text()
            self.assertIn('schema_version = "2.0"', text)
            self.assertIn("[compatibility]\nhost = ", text)
            self.assertIn('kind = "tool"\nid = "echo"', text)
            self.assertTrue((root / "pkg" / "extension.toml.v1").is_file())
            again = migrate({"path": str(root / "pkg")})
            self.assertFalse(again["migrated"])


class SmokeTest(unittest.TestCase):
    def test_declarative_tools_run(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.dry"})
            report = smoke(root / "pkg", {}, tool="echo", arguments={"text": "hi"})
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["tools"][0]["tool"], "echo")

    def test_process_tools_run_and_echo_the_token(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.dryproc",
                      "runtime": "process"})
            report = smoke(root / "pkg", {}, tool="echo", arguments={"text": "hi"})
            self.assertTrue(report["ok"], report)
            self.assertTrue(report["protocol"]["token_echoed"])


class ReferenceTest(unittest.TestCase):
    def test_every_topic_renders(self):
        for topic in reference.topics():
            rendered = reference.explain(topic)["markdown"]
            self.assertGreater(len(rendered), 200, topic)
            self.assertTrue(rendered.startswith("#"), topic)

    def test_the_design_topics_render(self):
        for topic in ("design", "domains", "commands", "skills", "security"):
            rendered = reference.explain(topic)["markdown"]
            self.assertGreater(len(rendered), 200, topic)
            self.assertTrue(rendered.startswith("#"), topic)
        domains_topic = reference.explain("domains")["markdown"]
        self.assertIn("knowledge", domains_topic)
        self.assertIn("generic", domains_topic)

    def test_an_unknown_topic_lists_the_known_ones(self):
        result = reference.explain("nonsense")
        self.assertIsNone(result["topic"])
        self.assertIn("manifest", result["topics"])


class DesignTest(unittest.TestCase):
    def test_every_profile_designs_a_consistent_blueprint(self):
        self.assertGreaterEqual(len(domains.PROFILES), 12)
        for key in domains.PROFILES:
            plan = design({"domain": key, "brief": "a small extension",
                           "id": "com.example.sample"})
            self.assertEqual(plan["domain"]["key"], key)
            self.assertEqual(plan["extension"]["id"], "com.example.sample")
            self.assertTrue(plan["markdown"].startswith("# Extension design:"))
            ids = [(row["kind"], row["id"]) for row in plan["contributions"]]
            self.assertEqual(len(ids), len({cid for _kind, cid in ids}), key)
            for row in plan["contributions"]:
                self.assertIsNone(util.check_contribution_id(row["id"]), row)
            for row in plan["capabilities"]:
                self.assertIn(row["name"], constants.CAPABILITY_NAMES)
                self.assertTrue(row["grants"], row)
            for tool in plan["tools"]:
                self.assertEqual(tool["input_schema"]["type"], "object")
                self.assertEqual(tool["file"], "tools/%s.json" % tool["id"])

    def test_domain_matching_is_explicit_about_confidence(self):
        self.assertEqual(domains.match("jira", "")[0], "web")
        self.assertEqual(domains.match("a team playbook", "")[0], "knowledge")
        key, confidence, _score, _signals = domains.match("an unheard-of thing", "")
        self.assertEqual(key, "generic")
        self.assertEqual(confidence, "none")

    def test_an_invalid_id_is_refused(self):
        with self.assertRaises(util.DevkitError):
            design({"domain": "data", "id": "Not.Reverse"})

    def test_a_package_is_compared_with_the_blueprint(self):
        with Scratch() as root:
            package = root / "pkg"
            scaffold({"path": str(package), "id": "com.example.warehouse",
                      "domain": "data", "brief": "Read warehouse data"})
            plan = design({"domain": "data", "brief": "Read warehouse data",
                           "id": "com.example.warehouse", "path": str(package)})
            self.assertEqual(plan["existing"]["status"], "in-progress")
            missing = {item["id"] for item in plan["existing"]["missing_contributions"]}
            self.assertIn("query", missing)
            self.assertTrue(plan["existing"]["design_file"])
            self.assertTrue(plan["existing"]["next_actions"])

    def test_blueprint_writes_docs_design(self):
        with Scratch() as root:
            package = root / "pkg"
            plan = design({"domain": "web", "brief": "Read Jira issues",
                           "id": "com.example.jira", "path": str(package),
                           "write": True})
            target = package / "docs" / "design.md"
            self.assertEqual(plan["design_file"], str(target))
            self.assertTrue(target.is_file())
            self.assertIn("Implementation checklist", target.read_text())

    def test_a_declarative_override_drops_process_capabilities(self):
        plan = design({"domain": "data", "runtime": "declarative",
                       "id": "com.example.data"})
        names = {row["name"] for row in plan["capabilities"]}
        self.assertNotIn("process.execute", names)
        self.assertNotIn("secrets.read", names)
        self.assertTrue(any(not tool["supported_by_runtime"] for tool in plan["tools"]))
        self.assertTrue(plan["warnings"])


class DomainScaffoldTest(unittest.TestCase):
    def test_a_data_package_is_green_and_declares_only_existing_tools(self):
        with Scratch() as root:
            package = root / "pkg"
            result = scaffold({"path": str(package), "id": "com.example.warehouse",
                               "domain": "data", "brief": "Read warehouse data"})
            self.assertEqual(result["domain"], "data")
            report = validate(package)
            self.assertTrue(report["ok"], report["findings"])
            manifest = (package / "extension.toml").read_text()
            self.assertNotIn('id = "query"', manifest)
            self.assertFalse((package / "tools" / "query.json").exists())
            self.assertTrue((package / "docs" / "design.md").is_file())
            self.assertIn("Implementation checklist",
                          (package / "docs" / "design.md").read_text())
            self.assertIn("Planned tools", (package / "README.md").read_text())

    def test_a_knowledge_package_ships_its_declarative_tools(self):
        with Scratch() as root:
            package = root / "pkg"
            scaffold({"path": str(package), "id": "com.example.playbook",
                      "domain": "knowledge", "brief": "Team onboarding playbook"})
            report = validate(package)
            self.assertTrue(report["ok"], report["findings"])
            self.assertTrue((package / "tools" / "checklist.json").is_file())
            manifest = (package / "extension.toml").read_text()
            self.assertIn('id = "checklist"', manifest)
            outcome = smoke(package, {}, tool="checklist",
                            arguments={"task": "onboarding"})
            self.assertTrue(outcome["ok"], outcome)

    def test_a_domain_package_records_the_build_order(self):
        with Scratch() as root:
            package = root / "pkg"
            scaffold({"path": str(package), "id": "com.example.docs",
                      "domain": "documents", "brief": "Convert office files"})
            design_doc = (package / "docs" / "design.md").read_text()
            self.assertIn("## Build order", design_doc)
            self.assertIn("## Acceptance gates", design_doc)
            self.assertIn("convert", design_doc)


class ServerTest(unittest.TestCase):
    def test_the_server_answers_the_handshake_and_a_tool_call(self):
        token = "test-token"
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"token": token, "config": "{}"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "com.open1s.extdev__explain",
                        "arguments": {"topic": "manifest"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
        payload = "\n".join(json.dumps(request) for request in requests) + "\n"
        process = subprocess.run(
            [sys.executable, "-B", "server.py"],
            cwd=str(ROOT), input=payload, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        messages = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
        by_id = {message.get("id"): message for message in messages if "id" in message}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "1.0")
        self.assertEqual(by_id[1]["result"]["token"], token)
        self.assertIn("# extension.toml", by_id[2]["result"]["markdown"])


class SelfTest(unittest.TestCase):
    def test_the_devkit_validates_and_lints_itself(self):
        report = validate(ROOT)
        self.assertTrue(report["ok"], report["findings"])
        self.assertEqual(report["id"], "com.open1s.extdev")
        review = lint(ROOT)
        self.assertEqual(review["summary"]["errors"], 0, review["findings"])


class BumpGuardTest(unittest.TestCase):
    def test_bump_refuses_a_downgrade(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.down"})
            with self.assertRaises(util.DevkitError) as raised:
                bump({"path": str(root / "pkg"), "release": "0.9.0"})
            self.assertIn("downgrade", str(raised.exception))
            manifest = (root / "pkg" / "extension.toml").read_text()
            self.assertIn('version = "1.0.0"', manifest)

    def test_bump_still_accepts_an_explicit_raise(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.up"})
            result = bump({"path": str(root / "pkg"), "release": "2.0.0"})
            self.assertEqual(result["to"], "2.0.0")


class MarketGuardTest(unittest.TestCase):
    def test_entry_outside_the_checkout_fails_with_a_named_message(self):
        with Scratch() as root:
            package_root = root / "pkg"
            scaffold({"path": str(package_root), "id": "com.example.outside"})
            with self.assertRaises(util.DevkitError) as raised:
                make_entry(package_root, root / "elsewhere" / "index.json")
            self.assertIn("not inside the market checkout", str(raised.exception))

    def test_list_fails_with_a_named_message_without_a_repo(self):
        with Scratch() as root:
            with self.assertRaises(util.DevkitError) as raised:
                market({"path": str(root), "action": "list"}, {})
            self.assertIn("cannot find", str(raised.exception))

    def test_list_accepts_a_path_that_holds_the_index(self):
        with Scratch() as repo:
            write(repo, "index.json",
                  json.dumps({"schema_version": 1, "extensions": []}))
            report = market({"path": str(repo), "action": "list"}, {})
            self.assertEqual(report["entries"], [])


class CheckSmokeTest(unittest.TestCase):
    def test_naming_a_tool_implies_a_smoke_run(self):
        with Scratch() as root:
            scaffold({"path": str(root / "pkg"), "id": "com.example.check"})
            outcome = dispatch("check", {
                "path": str(root / "pkg"),
                "tool": "describe",
                "arguments": {},
            }, {}, {})
            self.assertIn("smoke", outcome)
            self.assertTrue(outcome["smoke"]["ok"], outcome["smoke"])


if __name__ == "__main__":
    unittest.main()
