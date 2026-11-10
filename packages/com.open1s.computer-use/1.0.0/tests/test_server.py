import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def converse(requests):
    process = subprocess.Popen(
        [sys.executable, "-B", "server.py"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = "".join(json.dumps(request) + "\n" for request in requests)
    stdout, stderr = process.communicate(payload, timeout=30)
    lines = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    return process, stderr, lines


class ProcessProtocolTests(unittest.TestCase):
    def test_handshake_safe_tools_command_and_shutdown(self):
        # Only non-invasive tools are exercised: screen_size, cursor_position
        # and the panel command. Mouse, keyboard and screenshot tools act on
        # the real desktop and need OS permissions, so the tests leave them
        # alone on purpose.
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1.0", "token": "tok-1"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "computer", "arguments": {"action": "screen_size"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "computer", "arguments": {"action": "cursor_position"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "commands/execute", "params": {"name": "refresh", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": {}},
        ]
        process, stderr, lines = converse(requests)
        self.assertEqual(process.returncode, 0, stderr)
        by_id = {line.get("id"): line for line in lines}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "1.0")
        self.assertEqual(by_id[1]["result"]["token"], "tok-1")
        if sys.platform == "darwin":
            self.assertTrue(by_id[2]["result"]["ok"], by_id[2])
            self.assertGreater(by_id[2]["result"]["width"], 0)
            self.assertGreater(by_id[2]["result"]["height"], 0)
            self.assertTrue(by_id[3]["result"]["ok"], by_id[3])
            self.assertIn("x", by_id[3]["result"])
            self.assertIn("y", by_id[3]["result"])
            panel = by_id[4]["result"]
            self.assertEqual(panel["schema_version"], "1.0")
            self.assertEqual(panel["root"]["type"], "column")
        else:
            for rid in (2, 3, 4):
                self.assertFalse(by_id[rid]["result"]["ok"], by_id[rid])

    def test_an_unknown_tool_returns_ok_false(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"token": "t"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
        process, stderr, lines = converse(requests)
        self.assertEqual(process.returncode, 0, stderr)
        by_id = {line.get("id"): line for line in lines}
        self.assertFalse(by_id[2]["result"]["ok"])
        self.assertIn("unknown tool", by_id[2]["result"]["error"])

    def test_an_unknown_method_is_a_jsonrpc_error(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"token": "t"}},
            {"jsonrpc": "2.0", "id": 2, "method": "nope/nope", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
        process, stderr, lines = converse(requests)
        self.assertEqual(process.returncode, 0, stderr)
        by_id = {line.get("id"): line for line in lines}
        self.assertEqual(by_id[2]["error"]["code"], -32000)

    def test_events_are_accepted_without_a_reply(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"token": "t"}},
            {"jsonrpc": "2.0", "id": 2, "method": "events/event", "params": {"event": {"event_type": "session.created", "payload": {}}}},
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
        process, stderr, lines = converse(requests)
        self.assertEqual(process.returncode, 0, stderr)
        answered = {line.get("id") for line in lines}
        self.assertIn(1, answered)
        self.assertIn(3, answered)
        self.assertNotIn(2, answered)


if __name__ == "__main__":
    unittest.main()
