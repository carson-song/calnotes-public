"""Acceptance tests for planner/LIVE_SPEC.md: the planner sees live busy times, and only times."""
import json
import unittest
from datetime import datetime

from approve.calendar import CalendarError, TransientCalendarError
from approve.fake import FakeCalendar
from planner.tools import ToolBox, ToolError
from tests.test_agent import small_batch

T = datetime.fromisoformat
DAY = "2026-10-20"          # the small batch has a canary event 20:00-21:00 on this day (not on the calendar)


def tb(calendar=None, now=None):
    batch, h = small_batch()
    return ToolBox(batch, calendar=calendar, now=now), h


def slots(box, date=DAY):
    return json.loads(box.call("get_free_slots", {"date": date}))

def propose(box, h, start, minutes=30):
    return box.call("propose_block", {"handle": h["action"], "start": start, "minutes": minutes, "reason": "G1 now."})



class TestLiveBusy(unittest.TestCase):
    def test_L1_without_a_calendar_nothing_changes(self):
        box, _ = tb()
        self.assertEqual(slots(box), [["2026-10-20T09:00", "2026-10-20T20:00"]])

    def test_L2_busy_time_comes_from_the_calendar_not_the_snapshot(self):
        cal = FakeCalendar(busy=[(T("2026-10-20T12:00"), T("2026-10-20T13:00"))])
        box, _ = tb(cal)
        # the snapshot's 20:00 event is gone; the calendar's 12:00 one counts
        self.assertEqual(slots(box), [["2026-10-20T09:00", "2026-10-20T12:00"],
                                      ["2026-10-20T13:00", "2026-10-20T21:00"]])

    def test_L2_a_proposal_on_a_busy_slot_is_refused(self):
        cal = FakeCalendar(busy=[(T("2026-10-20T12:00"), T("2026-10-20T13:00"))])
        box, h = tb(cal)
        with self.assertRaises(ToolError):
            propose(box, h, "2026-10-20T12:30")

    def test_L2_earlier_proposals_still_count_as_busy(self):
        box, h = tb(FakeCalendar())
        propose(box, h, "2026-10-20T10:00", 60)
        self.assertEqual(slots(box), [["2026-10-20T09:00", "2026-10-20T10:00"],
                                      ["2026-10-20T11:00", "2026-10-20T21:00"]])

    def test_L2_the_whole_day_is_asked_for(self):
        class Spy(FakeCalendar):
            def busy(self, start, end):
                self.asked = (start, end)
                return super().busy(start, end)
        cal = Spy()
        box, _ = tb(cal)
        slots(box)
        self.assertEqual(cal.asked, (T("2026-10-20T00:00"), T("2026-10-21T00:00")))


class TestFailClosed(unittest.TestCase):
    def test_L3_a_calendar_error_is_a_tool_error_never_free_time(self):
        class Down(FakeCalendar):
            def busy(self, start, end):
                raise TransientCalendarError("503")
        box, h = tb(Down())
        with self.assertRaises(ToolError):          # not [] and not a full free day
            slots(box)
        with self.assertRaises(ToolError):
            propose(box, h, "2026-10-20T10:00")

    def test_L3_permanent_errors_too(self):
        class Refused(FakeCalendar):
            def busy(self, start, end):
                raise CalendarError("403")
        box, _ = tb(Refused())
        with self.assertRaises(ToolError):
            slots(box)


class TestNow(unittest.TestCase):
    NOW = T("2026-10-20T10:07")

    def test_L4_today_starts_at_the_next_quarter_hour(self):
        box, _ = tb(FakeCalendar(), now=self.NOW)
        self.assertEqual(slots(box), [["2026-10-20T10:15", "2026-10-20T21:00"]])

    def test_L4_past_days_and_late_evenings_have_no_free_time(self):
        box, _ = tb(FakeCalendar(), now=self.NOW)
        self.assertEqual(slots(box, "2026-10-19"), [])
        box, _ = tb(FakeCalendar(), now=T("2026-10-20T20:50"))
        self.assertEqual(slots(box), [])

    def test_L4_a_block_in_the_past_is_refused(self):
        box, h = tb(FakeCalendar(), now=self.NOW)
        with self.assertRaises(ToolError):
            propose(box, h, "2026-10-20T09:30")
        self.assertTrue(json.loads(propose(box, h, "2026-10-20T10:30"))["ok"])


class TestOnlyTimesCross(unittest.TestCase):
    def test_L5_event_content_never_reaches_the_model(self):
        cal = FakeCalendar()
        cal.insert("Dentist with SECRET_NAME", T("2026-10-20T12:00"), T("2026-10-20T13:00"), "SECRET_DESC", "k")
        box, h = tb(cal)

        out = box.call("get_free_slots", {"date": DAY}) + propose(box, h, "2026-10-20T14:00")
        self.assertNotIn("SECRET", out)
        self.assertNotIn("Dentist", out)


if __name__ == "__main__":
    unittest.main()
