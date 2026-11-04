import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class AutostartTests(unittest.TestCase):
    def test_the_process_binds_the_relay_before_the_first_tool_call(self):
        port = free_port()
        env = dict(os.environ)
        env["OPENCODE_RELAY_AUTOSTART"] = "1"
        env["OPENCODE_RELAY_PORT"] = str(port)
        process = subprocess.Popen(
            [sys.executable, "-B", "server.py"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            process.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"token": "t"}})
                + "\n"
            )
            process.stdin.flush()
            first = json.loads(process.stdout.readline())
            self.assertEqual(first["result"]["token"], "t")
            deadline = time.time() + 5
            health = None
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=1) as response:
                        health = json.loads(response.read())
                    break
                except Exception:
                    time.sleep(0.05)
            self.assertIsNotNone(health, "the relay did not bind without a tool call")
            self.assertTrue(health["running"])
            self.assertEqual(health["port"], port)
            process.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "status", "arguments": {"check": False}}})
                + "\n"
            )
            process.stdin.flush()
            status = json.loads(process.stdout.readline())
            self.assertTrue(status["result"]["relay"]["running"])
            process.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}}) + "\n"
            )
            process.stdin.flush()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()


if __name__ == "__main__":
    unittest.main()
