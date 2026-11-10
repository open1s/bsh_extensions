"""Self-check for this package: no host, no dependencies.

Run it with:  python3 -m unittest discover -s tests
"""

import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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


if __name__ == "__main__":
    unittest.main()
