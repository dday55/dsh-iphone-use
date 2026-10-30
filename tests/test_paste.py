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


class TypingClient(FakeClient):
    """Drives the whole type_text pipeline: paste probe, clear, per-piece typing."""

    def __init__(self, value="", paste_writes_a_literal=None):
        super().__init__(value=value)
        self.value = value
        self.paste_writes_a_literal = paste_writes_a_literal
        self.clicked = []
        self.keyboards = []
        self.typed = []

    def request(self, method, path, payload=None, timeout=None):
        if path == "/wda/getPasteboard":
            return {"value": ""}
        if path == "/wda/setPasteboard":
            self.pasteboard_writes.append(payload["content"])
            return {"value": None}
        if path.endswith("/keyboardInput"):
            self.keyboards.append(payload)
            if self.paste_writes_a_literal:
                self.value += self.paste_writes_a_literal
            return {"value": None}
        raise AssertionError(f"unexpected request {method} {path}")

    def session(self, method, path, payload=None, timeout=None):
        if path.endswith("/attribute/value"):
            return self.value
        if path.endswith("/clear"):
            self.clicked.append(path)
            self.value = ""
            return {"value": None}
        if path.endswith("/value") or path == "/wda/keys":
            text = payload.get("text") or "".join(payload.get("value") or [])
            self.typed.append(text)
            self.value += text
            return {"value": None}
        if path.endswith("/click"):
            return {"value": None}
        if path == "/elements":
            return [{"element-6066-11e4-a52e-4f735466cecf": "42", "type": "XCUIElementTypeTextField",
                     "rect": {"x": 10, "y": 10, "width": 200, "height": 40}, "attribute/hittable": True}]
        if path.endswith("/attribute/hittable"):
            return True
        if path.endswith("/attribute/type"):
            return "XCUIElementTypeTextField"
        if path == "/window/size":
            return {"width": 375, "height": 667}
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

    def test_append_mode_never_touches_the_clipboard(self):
        client = TypingClient(value="原有的内容")
        controller = self.controller(client)
        controller._source_app = "com.xingin.discover"
        result = controller.type_text(selector={"label": "搜索框"}, text="追加的长文本内容示例", replace=False, verify=False)
        # Append mode must skip the paste probe: a half-working chord would leave a
        # stray character inside text the user wrote.
        self.assertEqual(client.pasteboard_writes, [])
        self.assertEqual(client.keyboards, [])
        self.assertTrue(result["action_complete"])
        self.assertEqual(client.value, "原有的内容追加的长文本内容示例")

    def test_a_rejecting_app_is_remembered_so_the_probe_is_not_repeated(self):
        client = TypingClient(value="", paste_writes_a_literal="v")
        controller = self.controller(client)
        controller._source_app = "com.xingin.discover"
        controller.type_text(selector={"label": "搜索框"}, text="长文本内容示例的文本", replace=True, verify=False)
        self.assertIn("com.xingin.discover", controller.paste_blocked_apps)
        # The stray character the chord typed was cleared, and the real text was typed.
        self.assertEqual(client.value, "长文本内容示例的文本")

    def test_append_mode_keeps_the_existing_text_when_the_paste_does_nothing(self):
        client = FakeClient(value="原有的内容")
        controller = self.controller(client)
        # The paste did not insert anything: the field still holds what it held before.
        self.assertFalse(controller.try_paste_text("追加的文本内容", "42", "/element/42",
                                                   "原有的内容追加的文本内容", replace=False, before="原有的内容"))
        self.assertIs(controller.paste_verified, False)
        self.assertEqual(client.clicked, [])  # never clear the user's text

    def test_append_mode_succeeds_when_the_readback_matches(self):
        client = FakeClient(value="原有的内容追加的文本内容")
        controller = self.controller(client)
        self.assertTrue(controller.try_paste_text("追加的文本内容", "42", "/element/42",
                                                  "原有的内容追加的文本内容", replace=False, before="原有的内容"))
        self.assertIs(controller.paste_verified, True)
        self.assertEqual(client.clicked, [])

    def test_append_mode_with_an_unexpected_field_state_stops_instead_of_clearing(self):
        client = FakeClient(value="被别的东西改过")
        controller = self.controller(client)
        with self.assertRaises(WDAError) as caught:
            controller.try_paste_text("追加的文本内容", "42", "/element/42",
                                      "原有的内容追加的文本内容", replace=False, before="原有的内容")
        self.assertEqual(caught.exception.code, "input_state_unknown")
        self.assertEqual(client.clicked, [])
        self.assertIs(caught.exception.details["recovery"]["replay_action"], False)

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
