"""Clipboard fast path: it must prove the text landed, or say it could not.

A paste that silently does nothing looked exactly like success over HTTP, so a
long input could be reported as completed while the field stayed empty.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "iphone-use" / "server"))

from wda_client import WDAError
from wda_controller import PhoneController


class FakeClient:
    session_id = "session-1"

    def __init__(self, value="Pasted text", unreadable=False, old_clipboard="b2xk"):
        self.value = value
        self.unreadable = unreadable
        self.old_clipboard = old_clipboard
        self.pasteboard_writes = []
        self.clicked = []
        self.keyboards = []

    def request(self, method, path, payload=None, timeout=None):
        if path == "/wda/getPasteboard":
            if self.old_clipboard is None:
                raise WDAError("http_error", "getPasteboard unavailable")
            return {"value": self.old_clipboard}
        if path == "/wda/setPasteboard":
            self.pasteboard_writes.append(payload["content"])
            return {"value": None}
        if path.endswith("/keyboardInput"):
            self.keyboards.append(payload)
            return {"value": None}
        raise AssertionError(f"unexpected request {method} {path}")

    def session(self, method, path, payload=None, timeout=None):
        if path.endswith("/attribute/value"):
            if self.unreadable:
                raise WDAError("invalid_response", "no value attribute")
            return self.value
        if path.endswith("/clear"):
            self.clicked.append(path)
            return {"value": None}
        raise AssertionError(f"unexpected session {method} {path}")


class PasteVerificationTest(unittest.TestCase):
    def controller(self, client):
        directory = tempfile.mkdtemp(prefix="iphone-use-test-")
        return PhoneController(client, directory)

    def test_verified_paste_reports_an_exact_readback(self):
        client = FakeClient(value="Pasted text")
        controller = self.controller(client)
        self.assertTrue(controller.try_paste_text("Pasted text", "42", "/element/42", "Pasted text"))
        self.assertIs(controller.paste_verified, True)
        self.assertEqual(len(client.keyboards), 1)
        self.assertEqual(client.keyboards[0]["keys"][0]["modifierFlags"], 1048576)
        # The user's clipboard is put back after the paste.
        self.assertEqual(client.pasteboard_writes[-1], "b2xk")

    def test_mismatched_paste_falls_back_and_clears_the_field(self):
        client = FakeClient(value="something else")
        controller = self.controller(client)
        self.assertFalse(controller.try_paste_text("Pasted text", "42", "/element/42", "Pasted text"))
        self.assertIs(controller.paste_verified, False)
        self.assertTrue(client.clicked)

    def test_unreadable_field_keeps_the_paste_but_admits_it_is_unverified(self):
        client = FakeClient(unreadable=True)
        controller = self.controller(client)
        self.assertTrue(controller.try_paste_text("Pasted text", "42", "/element/42", "Pasted text"))
        self.assertIs(controller.paste_verified, False)

    def test_missing_clipboard_read_still_pastes(self):
        client = FakeClient(old_clipboard=None)
        controller = self.controller(client)
        self.assertTrue(controller.try_paste_text("Pasted text", "42", "/element/42", "Pasted text"))
        self.assertEqual(len(client.pasteboard_writes), 1)

    def test_finish_input_reports_the_paste_verdict(self):
        client = FakeClient(value="Pasted text")
        controller = self.controller(client)
        controller.try_paste_text("Pasted text", "42", "/element/42", "Pasted text")
        result = controller.finish_input({"path": "/element/42", "expected": "Pasted text", "verify": False,
                                          "submit": False, "expect": None, "observe": "none",
                                          "typed": 11, "total": 11, "paste": True,
                                          "paste_verified": controller.paste_verified})
        self.assertEqual(result["input_method"], "clipboard-paste")
        self.assertTrue(result["exact_readback"])
        self.assertTrue(result["verified"])

    def test_unverified_paste_is_not_reported_as_exact(self):
        client = FakeClient(unreadable=True)
        controller = self.controller(client)
        controller.try_paste_text("Pasted text", "42", "/element/42", "Pasted text")
        result = controller.finish_input({"path": "/element/42", "expected": "Pasted text", "verify": False,
                                          "submit": False, "expect": None, "observe": "none",
                                          "typed": 11, "total": 11, "paste": True,
                                          "paste_verified": controller.paste_verified})
        self.assertFalse(result["exact_readback"])
        self.assertFalse(result["verified"])
        self.assertIn("could not be read back", result["verification_required"])


if __name__ == "__main__":
    unittest.main()
