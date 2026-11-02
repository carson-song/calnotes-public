"""The calendar interface the approval step writes through. Provided: don't change it for the assignment.

Two implementations share it:
  FakeCalendar    (approve/fake.py) in memory, with failure injection
  GoogleCalendar  (approve/gcal.py) the real API, scope calendar.events only

Times are naive local datetimes ("2026-10-15T09:00" means 9am in your time zone), like the rest of the
project. The adapter handles the time zone.
"""
from datetime import datetime
from typing import Protocol


class CalendarError(Exception):
    """The write was refused and retrying won't help (bad request, no permission)."""


class TransientCalendarError(CalendarError):
    """Might work if tried again later (rate limit, server error, timeout, lost connection).

    Careful: after a timeout you don't know whether the event was created. That is the case
    idempotency keys exist for.
    """


class Calendar(Protocol):
    def find_by_key(self, key: str) -> str | None:
        """The event id of an event we wrote earlier with this key, or None."""

    def busy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        """Busy periods (start, end) overlapping [start, end), from every event on the calendar."""

    def insert(self, summary: str, start: datetime, end: datetime, description: str, key: str) -> str:
        """Create an event tagged with key; return its event id."""
