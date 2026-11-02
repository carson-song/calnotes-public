"""Contract tests for the Google Calendar adapter: the request it builds, checked without calling Google.

The fake calendar takes datetime objects, so the adapter's formatting code never runs in the other
tests. That's how a missing-seconds bug reached the real API (HTTP 400 on every insert).
"""
import re
import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

try:                                            # installed on your Mac; stubbed where it isn't
    import googleapiclient.errors  # noqa: F401
except ImportError:
    errors = types.ModuleType("googleapiclient.errors")
    errors.HttpError = type("HttpError", (Exception,), {})
    sys.modules["googleapiclient"] = types.ModuleType("googleapiclient")
    sys.modules["googleapiclient.errors"] = errors

from approve.gcal import KEY_PROP, GoogleCalendar

RFC3339_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")   # seconds required


class Recorder:
    """Stands in for the googleapiclient service: records the body instead of sending it."""
    def __init__(self):
        self.bodies = []

    def events(self):
        return self

    def insert(self, calendarId, body):
        self.bodies.append(body)
        return self

    def execute(self, num_retries=0):
        return {"id": "ev1"}


def adapter():
    cal = GoogleCalendar.__new__(GoogleCalendar)        # skip __init__: no sign-in, no network
    cal.cal_id, cal.tz, cal.api = "primary", ZoneInfo("America/Los_Angeles"), Recorder()
    return cal


class TestInsertBody(unittest.TestCase):
    def test_times_are_full_rfc3339_with_a_time_zone(self):
        cal = adapter()
        cal.insert("Text Nico", datetime(2026, 10, 16, 10, 0), datetime(2026, 10, 16, 10, 20), "why", "cn-x:p1")
        body = cal.api.bodies[0]
        for side in ("start", "end"):
            self.assertRegex(body[side]["dateTime"], RFC3339_LOCAL)
            self.assertEqual(body[side]["timeZone"], "America/Los_Angeles")

    def test_the_idempotency_key_is_a_private_property(self):
        cal = adapter()
        cal.insert("t", datetime(2026, 10, 16, 10), datetime(2026, 10, 16, 11), "d", "cn-x:p1")
        self.assertEqual(cal.api.bodies[0]["extendedProperties"], {"private": {KEY_PROP: "cn-x:p1"}})


if __name__ == "__main__":
    unittest.main()
