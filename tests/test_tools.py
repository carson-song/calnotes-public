import json
import unittest

from planner.tools import ToolBox, ToolError
from tests.test_agent import small_batch


class TestTools(unittest.TestCase):
    def setUp(self):
        self.batch, self.h = small_batch()
        self.tb = ToolBox(self.batch)

    def test_rejects_raw_data(self):
        with self.assertRaises(TypeError):
            ToolBox([{"title": "raw"}])

    def test_list_items_filters(self):
        out = json.loads(self.tb.call("list_items", {"type": "action"}))
        self.assertEqual([r["handle"] for r in out], [self.h["action"]])

    def test_free_slots_skip_events(self):
        # the canary event is 20:00-21:00 on 2026-10-20
        self.assertEqual(json.loads(self.tb.call("get_free_slots", {"date": "2026-10-20"})),
                         [["2026-10-20T09:00", "2026-10-20T20:00"]])

    def test_propose_and_overlap(self):
        args = {"handle": self.h["action"], "start": "2026-10-20T10:00", "minutes": 60, "reason": "G1 first."}
        self.assertTrue(json.loads(self.tb.call("propose_block", args))["ok"])
        with self.assertRaises(ToolError):
            self.tb.call("propose_block", args)  # same item twice

    def test_refusals(self):
        bad = [
            ("no_such_tool", {}),
            ("propose_block", {"handle": self.h["musing"], "start": "2026-10-20T10:00", "minutes": 30, "reason": "x"}),
            ("propose_block", {"handle": self.h["event"], "start": "2026-10-20T10:00", "minutes": 30, "reason": "x"}),
            ("propose_block", {"handle": self.h["action"], "start": "2026-10-20T20:30", "minutes": 30, "reason": "x"}),
            ("propose_block", {"handle": self.h["action"], "start": "2026-10-20T08:00", "minutes": 30, "reason": "x"}),
            ("propose_block", {"handle": "h_0000000000", "start": "2026-10-20T10:00", "minutes": 30, "reason": "x"}),
            ("get_free_slots", {"day": "2026-10-20"}),
        ]
        for name, args in bad:
            with self.subTest(name=name, args=args):
                with self.assertRaises(ToolError):
                    self.tb.call(name, args)


if __name__ == "__main__":
    unittest.main()
