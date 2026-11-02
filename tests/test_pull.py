"""Turning Google events into the project's event shape. No network."""
import unittest
from zoneinfo import ZoneInfo

from ingest.pull import normalize

LA = ZoneInfo("America/Los_Angeles")


class TestNormalize(unittest.TestCase):
    def test_timed_event_becomes_local_naive_minutes(self):
        e = normalize({"id": "g1", "summary": " text nico ", "colorId": "3",
                       "start": {"dateTime": "2026-10-19T16:30:00Z"}, "end": {"dateTime": "2026-10-19T17:30:00Z"}}, LA)
        self.assertEqual((e["id"], e["title"], e["start"], e["end"], e["color_id"]),
                         ("g1", "text nico", "2026-10-19T09:30", "2026-10-19T10:30", "3"))
        self.assertEqual((e["all_day"], e["calnotes_key"], e["description"], e["location"]), (False, None, "", ""))

    def test_all_day_event_is_flagged(self):
        e = normalize({"id": "g2", "summary": "trip", "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-21"}}, LA)
        self.assertEqual((e["start"], e["all_day"]), ("2026-10-20T00:00", True))

    def test_our_own_blocks_carry_their_key(self):
        e = normalize({"id": "g3", "summary": "Text Nico", "start": {"dateTime": "2026-10-20T09:00:00-07:00"},
                       "end": {"dateTime": "2026-10-20T09:20:00-07:00"},
                       "extendedProperties": {"private": {"calnotes_key": "cn-x:p1"}}}, LA)
        self.assertEqual(e["calnotes_key"], "cn-x:p1")

    def test_missing_title_is_empty_not_none(self):
        e = normalize({"id": "g4", "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-21"}}, LA)
        self.assertEqual(e["title"], "")


if __name__ == "__main__":
    unittest.main()
