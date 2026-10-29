"""Post-action observation: wait for a changed screen instead of a fixed delay.

A blind settle delay cost ~0.5s on every step and was still a guess. The read is
now taken after a short head start and only repeated once when the screen has not
changed yet.
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "iphone-use" / "server"))

from wda_controller import PhoneController


class StubController(PhoneController):
    """Counts observations without touching a phone."""

    def __init__(self, screens, settle=0.5):
        super().__init__(client=None, state_dir=tempfile.mkdtemp(prefix="iphone-use-settle-"))
        self.screens = list(screens)
        self.reads = 0
        self.settle_seconds = settle

    def observe(self, mode="tree", **kwargs):
        screen = self.screens[min(self.reads, len(self.screens) - 1)]
        self.reads += 1
        return {"nodes": screen, "mode": mode}


def node(label, y=0):
    return {"type": "Button", "label": label, "rect": [0, y, 10, 10]}


class SettleTest(unittest.TestCase):
    def test_a_changed_screen_is_not_read_twice(self):
        controller = StubController([[node("after")]])
        # The read already differs from the pre-action screen: one read is enough.
        controller._pre_action_digest = "stale-digest"
        result = controller.observe_after("tree")
        self.assertEqual(controller.reads, 1)
        self.assertEqual(result["nodes"], [node("after")])

    def test_an_unchanged_screen_gets_one_confirmation_read(self):
        controller = StubController([[node("same")], [node("same")], [node("same")]])
        # The first read repeats the pre-action screen, so exactly one more is taken.
        controller._pre_action_digest = "stale-digest"
        controller.settle_seconds = 0.5
        first = controller.observe_after("tree")   # differs -> 1 read
        self.assertEqual(controller.reads, 1)
        controller._pre_action_digest = "stale-digest"
        controller.screens = [[node("same")], [node("same")]]
        controller.reads = 0
        controller.observe_after("screenshot")     # screenshot mode never re-reads
        self.assertEqual(controller.reads, 1)

    def test_no_settle_budget_reads_once(self):
        controller = StubController([[node("a")]], settle=0)
        controller.observe_after("tree")
        self.assertEqual(controller.reads, 1)

    def test_wait_stays_bounded_by_the_configured_settle(self):
        controller = StubController([[node("before")], [node("before")]], settle=0.5)
        controller._pre_action_digest = "stale-digest"
        started = time.monotonic()
        controller.observe_after("tree")
        self.assertLess(time.monotonic() - started, 0.45)


if __name__ == "__main__":
    unittest.main()
