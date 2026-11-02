"""The real calendar, through the Google Calendar API. Provided.

Scope: chosen per account (see approve/accounts.py): calendar.events for the plans account (read and
write events; can't change settings or sharing), calendar.readonly for the notes account.
Each account has its own token file, and expect_account refuses to run if the wrong account signed in.

What it maps:
  idempotency key  -> a private extended property on the event (invisible in the UI, searchable by API)
  busy periods     -> timed events that aren't marked "free"; all-day events are ignored
  HTTP 429 / 5xx, timeouts, lost connections -> TransientCalendarError (retry later)
  any other refusal (400, 401, 404, ...)    -> CalendarError (don't retry)
"""
import os
import socket
from datetime import datetime
from zoneinfo import ZoneInfo

from approve.calendar import CalendarError, TransientCalendarError

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
KEY_PROP = "calnotes_key"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def check_account(actual: str, expected: str, role: str) -> None:
    """Fail closed when the signed-in calendar isn't the one you said to use."""
    if not expected:
        raise SystemExit(f"Set the expected account for the {role} calendar (see approve/accounts.py).")
    if (actual or "").strip().lower() != expected.strip().lower():
        raise SystemExit(f"The {role} calendar is {actual!r}, not {expected!r}. Wrong Google account signed in? "
                         f"Delete its token in secrets/ and sign in again with {expected}.")


class GoogleCalendar:
    def __init__(self, calendar_id="primary", tz=None, token="token_calendar.json", scopes=SCOPES,
                 expect_account=None, role="calendar"):
        import gauth
        self.cal_id = calendar_id
        self.tz = ZoneInfo(tz or os.environ.get("CALNOTES_TZ", "America/Los_Angeles"))
        self.api = gauth.service("calendar", "v3", scopes, token)
        self.account = self._account()
        if expect_account is not None:
            check_account(self.account, expect_account, role)

    def _account(self) -> str:
        """The calendar's name; for a primary calendar Google sets it to the account's email address."""
        return self._call(self.api.events().list(calendarId=self.cal_id, maxResults=1)).get("summary", "")

    def list_events(self, start, end):
        """Every event overlapping [start, end), raw Google dicts, all pages. Used by live ingest."""
        items, page = [], None
        while True:
            r = self._call(self.api.events().list(calendarId=self.cal_id, singleEvents=True, orderBy="startTime",
                                                  timeMin=self._iso(start), timeMax=self._iso(end),
                                                  maxResults=250, pageToken=page))
            items += r.get("items", [])
            page = r.get("nextPageToken")
            if not page:
                return items

    def find_by_key(self, key):
        r = self._call(self.api.events().list(calendarId=self.cal_id, maxResults=1,
                                              privateExtendedProperty=f"{KEY_PROP}={key}"))
        items = r.get("items", [])
        return items[0]["id"] if items else None

    def busy(self, start, end):
        r = self._call(self.api.events().list(calendarId=self.cal_id, singleEvents=True, orderBy="startTime",
                                              timeMin=self._iso(start), timeMax=self._iso(end)))
        out = []
        for e in r.get("items", []):
            if e.get("transparency") == "transparent" or "dateTime" not in e.get("start", {}):
                continue
            out.append((self._local(e["start"]["dateTime"]), self._local(e["end"]["dateTime"])))
        return out

    def insert(self, summary, start, end, description, key):
        body = {
            "summary": summary,
            "description": f"{description}\n\nProposed by calnotes, approved by you.",
            "start": {"dateTime": start.isoformat(timespec="seconds"), "timeZone": str(self.tz)},
            "end": {"dateTime": end.isoformat(timespec="seconds"), "timeZone": str(self.tz)},
            "extendedProperties": {"private": {KEY_PROP: key}},
        }
        return self._call(self.api.events().insert(calendarId=self.cal_id, body=body))["id"]

    def _call(self, request):
        from googleapiclient.errors import HttpError
        try:
            return request.execute(num_retries=0)
        except HttpError as e:
            status = getattr(e.resp, "status", 0)
            rate_limited = status == 403 and b"rateLimitExceeded" in (e.content or b"")
            if status in RETRYABLE_STATUS or rate_limited:
                raise TransientCalendarError(f"HTTP {status}") from e
            raise CalendarError(f"HTTP {status}: {e}") from e
        except (socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            raise TransientCalendarError(type(e).__name__) from e

    def _iso(self, dt: datetime) -> str:
        return dt.replace(tzinfo=self.tz).isoformat()

    def _local(self, s: str) -> datetime:
        return datetime.fromisoformat(s).astimezone(self.tz).replace(tzinfo=None)
