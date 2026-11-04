import json
import os
import socket
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class ProcessProtocolTests(unittest.TestCase):
    def test_handshake_start_status_stop_shutdown(self):
        port = free_port()
        process = subprocess.Popen(
            [sys.executable, "-B", "server.py"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1.0", "token": "tok-1"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "opencode__relay_start", "arguments": {"port": port}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "status", "arguments": {"check": False}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "relay_stop", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": {}},
        ]
        payload = "".join(json.dumps(request) + "\n" for request in requests)
        stdout, stderr = process.communicate(payload, timeout=30)
        self.assertEqual(process.returncode, 0, stderr)
        lines = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        by_id = {line.get("id"): line for line in lines}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "1.0")
        self.assertEqual(by_id[1]["result"]["token"], "tok-1")
        self.assertTrue(by_id[2]["result"]["ok"], by_id[2])
        self.assertTrue(by_id[2]["result"]["status"]["running"])
        self.assertEqual(by_id[2]["result"]["status"]["port"], port)
        self.assertTrue(by_id[3]["result"]["relay"]["running"])
        self.assertFalse(by_id[4]["result"]["status"]["running"])

    def test_an_unknown_tool_is_a_jsonrpc_error(self):
        process = subprocess.Popen(
            [sys.executable, "-B", "server.py"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        payload = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"token": "t"}})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope", "arguments": {}}})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}})
            + "\n"
        )
        stdout, stderr = process.communicate(payload, timeout=30)
        self.assertEqual(process.returncode, 0, stderr)
        lines = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        by_id = {line.get("id"): line for line in lines}
        self.assertEqual(by_id[2]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
