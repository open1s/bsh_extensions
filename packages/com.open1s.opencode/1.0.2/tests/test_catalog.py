import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import zen_catalog  # noqa: E402


def entry(model, input_price, output_price, inputs=("text",), output=8000, context=100000, reasoning=True):
    return {
        "id": model,
        "name": model.upper(),
        "modalities": {"input": list(inputs)},
        "limit": {"output": output, "context": context},
        "capabilities": {"reasoning": {"supported": reasoning}},
        "cost": {
            "text": {
                "input": {"price": input_price},
                "output": {"price": output_price},
            }
        },
    }


CATALOG = {
    "object": "list",
    "data": [
        entry("free-chat", 0, 0),
        entry("free-vision", 0, 0, inputs=("text", "image/png")),
        entry("free-dead", 0, 0),
        entry("paid-chat", 3, 15),
    ],
}
CATALOG["data"][2]["deprecated"] = True


class Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        body = json.dumps(CATALOG).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.upstream = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        zen_catalog._CACHE.update({"at": 0.0, "models": [], "total": 0})

    def test_free_decision_uses_prices_not_the_name(self):
        self.assertTrue(zen_catalog.is_free(entry("free", 0, 0)))
        self.assertFalse(zen_catalog.is_free(entry("paid", 1, 1)))
        self.assertFalse(zen_catalog.is_free(entry("deprecated-free", 0, 0) | {"deprecated": True}))
        self.assertFalse(zen_catalog.is_free(entry("jev-1.13-free", 0, 0)))

    def test_live_roster_filters_paid_and_dead_models(self):
        result = zen_catalog.load(upstream=self.upstream)
        self.assertEqual(result["source"], "live", result)
        self.assertEqual(result["error"], "")
        self.assertEqual([model["id"] for model in result["free"]], ["free-chat", "free-vision"])
        vision = result["free"][1]
        self.assertEqual(vision["input_types"], ["text", "image"])
        self.assertEqual(vision["max_tokens"], 8000)
        self.assertEqual(vision["context_window"], 100000)
        self.assertTrue(vision["reasoning"])

    def test_paid_models_are_reported_only_on_request(self):
        result = zen_catalog.load(upstream=self.upstream, include_paid=True)
        paid = [model["id"] for model in result["paid"]]
        self.assertIn("paid-chat", paid)
        self.assertNotIn("free-chat", paid)

    def test_a_failed_catalog_falls_back_to_the_package_roster(self):
        result = zen_catalog.load(upstream="http://127.0.0.1:9/nothing", timeout=2)
        self.assertEqual(result["source"], "static")
        self.assertTrue(result["error"])
        ids = [model["id"] for model in result["free"]]
        self.assertIn("deepseek-v4.1-flash-free", ids)
        self.assertEqual(len(ids), 8)
        by_id = {model["id"]: model for model in result["free"]}
        self.assertEqual(by_id["glm-5.3-flash-free"]["input_types"], ["text", "image"])
        self.assertEqual(by_id["big-pickle"]["context_window"], 200000)


if __name__ == "__main__":
    unittest.main()
