"""Transport policy: a dead keep-alive socket may be retried for reads only.

Resending a write can duplicate a phone action, so a write that fails mid-send
must surface as action_uncertain instead of being replayed silently.
"""
import http.client
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "iphone-use" / "server"))

import wda_client
from wda_client import WDAClient, WDAError


class FakeResponse:
    status = 200

    def __init__(self, body=b'{"value":{}}'):
        self.body = body

    def read1(self, _size):
        body, self.body = self.body, b""
        return body

    def isclosed(self):
        return False

    def close(self):
        return None


class FlakyConnection:
    """First write fails like a stale socket; later ones succeed."""

    instances = []

    def __init__(self, host, port, timeout=None):
        self.writes = 0
        self.sock = None
        FlakyConnection.instances.append(self)

    def request(self, method, path, body=None, headers=None):
        self.writes += 1
        if len(FlakyConnection.instances) == 1:
            raise BrokenPipeError("stale keep-alive socket")

    def getresponse(self):
        return FakeResponse()

    def close(self):
        return None


class TransportRetryTest(unittest.TestCase):
    def setUp(self):
        FlakyConnection.instances = []
        patcher = mock.patch.object(http.client, "HTTPConnection", FlakyConnection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = WDAClient("http://127.0.0.1:18100", timeout=5)

    def test_read_is_retried_on_a_fresh_connection(self):
        self.assertEqual(self.client.request("GET", "/status"), {"value": {}})
        self.assertEqual(len(FlakyConnection.instances), 2)
        self.assertEqual([connection.writes for connection in FlakyConnection.instances], [1, 1])

    def test_write_is_not_replayed_and_becomes_uncertain(self):
        with self.assertRaises(WDAError) as caught:
            self.client.request("POST", "/wda/tap", {"x": 10, "y": 20})
        error = caught.exception
        self.assertEqual(error.code, "action_uncertain")
        self.assertTrue(error.uncertain)
        self.assertEqual(error.details.get("transport_error"), "pua_unreachable")
        self.assertIn("Never blindly replay", str(error))
        self.assertEqual(sum(connection.writes for connection in FlakyConnection.instances), 1)

    def test_read_only_routes_are_classified_before_dispatch(self):
        self.assertTrue(WDAClient.is_read("GET", "/source"))
        self.assertTrue(WDAClient.is_read("POST", "/element"))
        self.assertFalse(WDAClient.is_read("POST", "/wda/tap"))


if __name__ == "__main__":
    unittest.main()
