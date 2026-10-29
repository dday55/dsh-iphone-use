"""Tree parsing, compaction and pruning, exercised without a phone.

These run on recorded WDA XML, so the model-facing node shape and the pruning
rules stay pinned even when the device is unavailable.
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "iphone-use" / "server"))

import tree

SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<AppiumAUT>
  <XCUIElementTypeApplication type="XCUIElementTypeApplication" label="Settings" bundleId="com.apple.Preferences" x="0" y="0" width="375" height="667">
    <XCUIElementTypeWindow type="XCUIElementTypeWindow" x="0" y="0" width="375" height="667">
      <XCUIElementTypeOther type="XCUIElementTypeOther" label="Wi-Fi" x="16" y="100" width="343" height="44">
        <XCUIElementTypeButton type="XCUIElementTypeButton" label="Wi-Fi" name="wifi" value="On" enabled="true" x="16" y="100" width="343" height="44"/>
      </XCUIElementTypeOther>
      <XCUIElementTypeOther type="XCUIElementTypeOther" x="0" y="0" width="10" height="10"/>
      <XCUIElementTypeButton type="XCUIElementTypeButton" label="Settings 12:30" x="0" y="660" width="375" height="7"/>
      <XCUIElementTypeStaticText type="XCUIElementTypeStaticText" label="Offscreen" x="0" y="900" width="100" height="20"/>
      <XCUIElementTypeAlert type="XCUIElementTypeAlert" x="20" y="200" width="335" height="200"/>
      <XCUIElementTypeButton type="XCUIElementTypeButton" label="Broken" x="nope" y="0" width="10" height="10"/>
    </XCUIElementTypeWindow>
  </XCUIElementTypeApplication>
</AppiumAUT>
"""


class ParseSourceTest(unittest.TestCase):
    def setUp(self):
        self.root, self.nodes = tree.parse_source(SOURCE)
        self.labels = [node.get("label") for node in self.nodes]

    def test_root_attributes_carry_the_foreground_app(self):
        self.assertEqual(self.root.get("bundleId"), "com.apple.Preferences")

    def test_application_and_window_are_not_nodes(self):
        self.assertFalse([n for n in self.nodes if n["type"] in ("XCUIElementTypeApplication", "XCUIElementTypeWindow")])

    def test_textless_rows_are_dropped_but_alerts_survive(self):
        # The alert has no text at all and must still reach the model.
        self.assertIn("XCUIElementTypeAlert", [n["type"] for n in self.nodes])
        self.assertIn("Wi-Fi", self.labels)

    def test_broken_geometry_is_skipped_not_fatal(self):
        self.assertNotIn("Broken", self.labels)

    def test_every_node_carries_numeric_rect(self):
        for node in self.nodes:
            self.assertEqual(set(node["rect"]), {"x", "y", "width", "height"})
            for value in node["rect"].values():
                self.assertIsInstance(value, float)

    def test_malformed_xml_raises_for_the_caller_to_report(self):
        with self.assertRaises(ET.ParseError):
            tree.parse_source("<AppiumAUT><unclosed>")


class CompactNodeTest(unittest.TestCase):
    def test_defaults_are_omitted(self):
        compacted = tree.compact_node({"type": "XCUIElementTypeButton", "label": "Wi-Fi", "name": "Wi-Fi",
                                      "enabled": "true", "rect": {"x": 1.4, "y": 2.6, "width": 3.5, "height": 4.5}})
        self.assertEqual(compacted, {"type": "Button", "label": "Wi-Fi", "rect": [1, 3, 4, 4]})

    def test_distinct_text_is_kept_once(self):
        compacted = tree.compact_node({"label": "Send", "name": "send", "value": "Send", "type": "XCUIElementTypeButton"})
        self.assertEqual(compacted["name"], "send")
        self.assertNotIn("value", compacted)

    def test_explicit_false_flags_are_visible(self):
        compacted = tree.compact_node({"enabled": "false", "visible": False, "in_viewport": False})
        self.assertEqual(compacted, {"enabled": False, "visible": False, "in_viewport": False})


class PruneNodesTest(unittest.TestCase):
    def test_generic_container_duplicating_a_button_is_pruned(self):
        nodes = [{"type": "XCUIElementTypeOther", "label": "Wi-Fi", "rect": {"x": 16, "y": 100, "width": 343, "height": 44}},
                 {"type": "XCUIElementTypeButton", "label": "Wi-Fi", "rect": {"x": 16, "y": 100, "width": 343, "height": 44}}]
        self.assertEqual([n["type"] for n in tree.prune_nodes(nodes)], ["XCUIElementTypeButton"])

    def test_container_with_its_own_text_is_kept(self):
        nodes = [{"type": "XCUIElementTypeOther", "label": "Section", "rect": {"x": 0, "y": 0, "width": 10, "height": 10}},
                 {"type": "XCUIElementTypeButton", "label": "Row", "rect": {"x": 0, "y": 0, "width": 10, "height": 10}}]
        self.assertEqual(len(tree.prune_nodes(nodes)), 2)

    def test_single_node_and_empty_lists_pass_through(self):
        self.assertEqual(tree.prune_nodes([]), [])
        one = [{"type": "XCUIElementTypeOther", "label": "x"}]
        self.assertEqual(tree.prune_nodes(one), one)


class TreeDigestTest(unittest.TestCase):
    def test_same_screen_hashes_the_same(self):
        a = [tree.compact_node({"type": "XCUIElementTypeButton", "label": "Go", "rect": {"x": 1, "y": 2, "width": 3, "height": 4}})]
        self.assertEqual(tree.tree_digest(a), tree.tree_digest(list(a)))

    def test_geometry_change_changes_the_digest(self):
        a = [{"type": "Button", "label": "Go", "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}]
        b = [{"type": "Button", "label": "Go", "rect": {"x": 1, "y": 9, "width": 3, "height": 4}}]
        self.assertNotEqual(tree.tree_digest(a), tree.tree_digest(b))

    def test_unknown_input_is_not_a_digest(self):
        self.assertIsNone(tree.tree_digest(None))
        self.assertIsNone(tree.tree_digest("nodes"))


if __name__ == "__main__":
    unittest.main()
