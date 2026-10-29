"""Selector validation and predicate escaping."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "iphone-use" / "server"))

from selector import predicate
from wda_client import WDAError


class PredicateTest(unittest.TestCase):
    def test_exact_field_becomes_equality(self):
        self.assertEqual(predicate({"label": "Send"}), "label == 'Send'")

    def test_several_fields_are_conjoined_in_declaration_order(self):
        self.assertEqual(predicate({"name": "row", "value": "On"}), "name == 'row' AND value == 'On'")

    def test_type_is_prefixed_once(self):
        self.assertEqual(predicate({"type": "Button"}), "type == 'XCUIElementTypeButton'")
        self.assertEqual(predicate({"type": "XCUIElementTypeButton"}), "type == 'XCUIElementTypeButton'")

    def test_label_contains_uses_contains(self):
        self.assertEqual(predicate({"label_contains": "Wi"}), "label CONTAINS 'Wi'")

    def test_enabled_accepts_bool_and_tree_strings(self):
        self.assertEqual(predicate({"enabled": True}), "enabled == true")
        self.assertEqual(predicate({"enabled": "false"}), "enabled == false")

    def test_control_characters_are_escaped(self):
        self.assertEqual(predicate({"label": "a\nb"}), "label == 'a\\u000ab'")
        self.assertEqual(predicate({"label": "c\\nd"}), "label == 'c\\\\nd'")

    def test_quote_is_escaped(self):
        self.assertEqual(predicate({"label": "it's"}), "label == 'it\\'s'")

    def test_standalone_predicate_passes_through(self):
        self.assertEqual(predicate({"predicate": "label BEGINSWITH 'Se'"}), "label BEGINSWITH 'Se'")

    def test_index_alone_is_rejected(self):
        with self.assertRaises(WDAError) as caught:
            predicate({"index": 0})
        self.assertEqual(caught.exception.code, "invalid_selector")

    def test_predicate_cannot_be_mixed_with_fields(self):
        with self.assertRaises(WDAError):
            predicate({"predicate": "label == 'x'", "label": "y"})

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(WDAError):
            predicate({"labl": "typo"})

    def test_empty_selector_is_rejected(self):
        with self.assertRaises(WDAError):
            predicate({})

    def test_nul_is_rejected(self):
        with self.assertRaises(WDAError):
            predicate({"label": "a\x00b"})

    def test_index_bounds(self):
        for bad in (-1, 200, True, "1", 1.5):
            with self.assertRaises(WDAError, msg=f"index={bad!r}"):
                predicate({"label": "x", "index": bad})


if __name__ == "__main__":
    unittest.main()
