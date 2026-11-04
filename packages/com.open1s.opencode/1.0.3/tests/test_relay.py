import json
import os
import re
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import zen_relay  # noqa: E402

SESSION = re.compile(r"^ses_[0-9a-f]{12}[0-9A-Za-z]{14}$")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "read",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "bash",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
        },
    },
]

SSE_TOOL = [
    'data: {"id":"cmpl-1","model":"m","choices":[{"index":0,"delta":{"role":"assistant","tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"read","arguments":""}}]}}]}',
    'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"filePath\\":\\"/tmp\\"}"}}]}}]}',
    'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}',
    "data: [DONE]",
]

SSE_TEXT = [
    'data: {"id":"cmpl-2","model":"m","choices":[{"index":0,"delta":{"role":"assistant","content":"hel"}}]}',
    'data: {"choices":[{"index":0,"delta":{"content":"lo"},"finish_reason":"stop"}]}',
    "data: [DONE]",
]


class Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length))
        self.server.record = {"path": self.path, "headers": dict(self.headers), "body": body}
        if self.server.mode == "error":
            payload = b'{"type":"error","error":{"type":"FreeUsageLimitError","message":"quota"}}'
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        lines = SSE_TOOL if self.server.mode == "tool" else SSE_TEXT
        payload = ("\n\n".join(lines) + "\n\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class RelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        cls.server.record = None
        cls.server.mode = "stream"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.upstream = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.server.record = None
        self.server.mode = "text"
        self.relay = zen_relay.Relay(port=0, upstream=self.upstream, timeout=10)
        self.relay.start()
        self.addCleanup(self.relay.stop)

    def start(self):
        return self.relay.port

    def post(self, body):
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", self.relay.port, timeout=10)
        connection.request("POST", "/v1/chat/completions", body=json.dumps(body), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        return response.status, payload

    def test_session_id_shape_and_header_set(self):
        body = {"model": "m", "messages": [{"role": "user", "content": "hello"}], "tools": TOOLS}
        self.relay.start()
        status, _ = self.post(body)
        self.assertEqual(status, 200)
        headers = {key.lower(): value for key, value in self.server.record["headers"].items()}
        session = headers["x-opencode-session"]
        self.assertRegex(session, SESSION)
        self.assertEqual(headers["x-opencode-session-id"], session)
        self.assertEqual(headers["x-session-affinity"], session)
        self.assertEqual(headers["x-opencode-project"], "global")
        self.assertEqual(headers["authorization"], "Bearer public")
        self.assertTrue(headers["user-agent"].startswith("opencode/"))
        self.assertEqual(self.server.record["path"], "/v1/chat/completions")

    def test_the_same_conversation_reuses_one_session(self):
        body = {"model": "m", "messages": [{"role": "user", "content": "same"}], "tools": TOOLS}
        self.post(body)
        first = {key.lower(): value for key, value in self.server.record["headers"].items()}["x-opencode-session"]
        self.post(body)
        second = {key.lower(): value for key, value in self.server.record["headers"].items()}["x-opencode-session"]
        self.assertEqual(first, second)

    def test_read_file_is_wire_renamed_and_the_call_is_mapped_back(self):
        self.server.mode = "tool"
        body = {"model": "m", "messages": [{"role": "user", "content": "read"}], "tools": TOOLS, "stream": True}
        status, payload = self.post(body)
        self.assertEqual(status, 200)
        names = [tool["function"]["name"] for tool in self.server.record["body"]["tools"]]
        self.assertEqual(names, ["read", "bash"])
        self.assertTrue(self.server.record["body"]["stream"])
        text = payload.decode("utf-8")
        self.assertIn('"name":"read_file"', text.replace(" ", ""))
        self.assertNotIn('"name":"read"', text.replace(" ", ""))

    def test_a_body_without_tools_still_carries_the_gate_pair(self):
        body = {"model": "m", "messages": [{"role": "user", "content": "no tools"}], "stream": True}
        self.post(body)
        sent = self.server.record["body"]
        self.assertEqual([tool["function"]["name"] for tool in sent["tools"]], ["bash", "read"])
        self.assertEqual(sent["tool_choice"], "none")

    def test_a_non_streaming_caller_gets_one_aggregated_completion(self):
        body = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "tools": TOOLS, "stream": False}
        status, payload = self.post(body)
        self.assertEqual(status, 200)
        response = json.loads(payload)
        self.assertEqual(response["object"], "chat.completion")
        self.assertEqual(response["choices"][0]["message"]["content"], "hello")

    def test_upstream_errors_pass_through_with_status_and_body(self):
        self.server.mode = "error"
        body = {"model": "m", "messages": [{"role": "user", "content": "x"}]}
        status, payload = self.post(body)
        self.assertEqual(status, 429)
        self.assertIn("FreeUsageLimitError", payload.decode("utf-8"))


class ShapeTests(unittest.TestCase):
    def test_an_invalid_gate_tool_is_replaced_not_trusted(self):
        body, aliases, injected = zen_relay.shape_chat_body(
            {
                "tools": [
                    {"type": "function", "function": {"name": "bash", "parameters": {"type": "object", "properties": {}}}},
                    TOOLS[0],
                ]
            }
        )
        self.assertEqual(aliases, {"read": "read_file"})
        names = [tool["function"]["name"] for tool in body["tools"]]
        self.assertEqual(names, ["read", "bash"], "the empty bash shell is replaced, not counted")
        self.assertEqual(injected, ["bash"])

    def test_an_empty_tool_list_also_pins_the_choice(self):
        body, _, injected = zen_relay.shape_chat_body({"tools": []})
        self.assertEqual(body["tool_choice"], "none")
        self.assertEqual([tool["function"]["name"] for tool in body["tools"]], ["bash", "read"])
        self.assertEqual(injected, ["bash", "read"])

    def test_a_valid_pair_is_left_alone(self):
        body, aliases, injected = zen_relay.shape_chat_body({"tools": TOOLS})
        self.assertEqual(aliases, {"read": "read_file"})
        self.assertEqual(injected, [])
        self.assertEqual(len(body["tools"]), 2)


if __name__ == "__main__":
    unittest.main()
