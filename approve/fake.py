"""An in-memory calendar with failure injection: used by the tests and by approve_run.py dry runs."""
from approve.calendar import CalendarError, TransientCalendarError


class FakeCalendar:
    """
    FakeCalendar(busy=[(start, end), ...])        existing events (not ours)
    fail={2: TransientCalendarError("429")}        the 2nd insert call raises before creating anything
    lose_response={1}                              the 1st insert creates the event, then raises
                                                   TransientCalendarError, like a timeout after success
    """

    def __init__(self, busy=(), fail=None, lose_response=()):
        self.events = {}          # event_id -> dict
        self.fixed_busy = list(busy)
        self.fail = dict(fail or {})
        self.lose_response = set(lose_response)
        self.insert_calls = 0

    def find_by_key(self, key):
        return next((eid for eid, e in self.events.items() if e["key"] == key), None)

    def busy(self, start, end):
        periods = self.fixed_busy + [(e["start"], e["end"]) for e in self.events.values()]
        return [(s, e) for s, e in periods if s < end and start < e]

    def insert(self, summary, start, end, description, key):
        self.insert_calls += 1
        n = self.insert_calls
        if n in self.fail:
            raise self.fail[n]
        if not summary or end <= start:
            raise CalendarError("invalid event")
        eid = f"ev{n}"
        self.events[eid] = {"summary": summary, "start": start, "end": end, "description": description, "key": key}
        if n in self.lose_response:
            raise TransientCalendarError("timed out waiting for the response")
        return eid
