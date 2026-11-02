"""Which Google account does what. Provided.

  notes account   your calendar of notes; read only (calendar.readonly)   -> live ingest
  plans account   where approved blocks go, and whose busy time counts     -> planner free/busy, approvals

Each account has its own token in secrets/, with only the permission it needs: code holding the notes token
can't write anything. Set these once, e.g. in your shell profile:

  export CALNOTES_PLANS_ACCOUNT=you@example.com            # required: the account blocks are written to
  export CALNOTES_PLANS_CALENDAR=primary                 # optional: another calendar id in that account
  export CALNOTES_NOTES_ACCOUNT=notes@example.com      # required for live ingest

The first use of each opens a browser to sign in: pick the matching account. Both accounts must be listed
as test users on the OAuth consent screen. If the wrong account signs in, the run stops before doing
anything; delete that token file and sign in again.
"""
import os

from approve.gcal import SCOPES as EVENTS_SCOPE, GoogleCalendar

READONLY_SCOPE = ["https://www.googleapis.com/auth/calendar.readonly"]
PLANS_TOKEN, NOTES_TOKEN = "token_cal_plans.json", "token_cal_notes.json"


def plans_calendar() -> GoogleCalendar:
    return GoogleCalendar(calendar_id=os.environ.get("CALNOTES_PLANS_CALENDAR", "primary"),
                          token=PLANS_TOKEN, scopes=EVENTS_SCOPE, role="plans",
                          expect_account=os.environ.get("CALNOTES_PLANS_ACCOUNT", ""))


def notes_calendar() -> GoogleCalendar:
    return GoogleCalendar(calendar_id="primary", token=NOTES_TOKEN, scopes=READONLY_SCOPE, role="notes",
                          expect_account=os.environ.get("CALNOTES_NOTES_ACCOUNT", ""))
