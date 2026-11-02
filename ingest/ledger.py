"""YOUR ASSIGNMENT: the item ledger and which notes are still open. Read ingest/SPEC.md first.

Acceptance: python3 -m unittest tests.test_ledger -v
"""
from datetime import date, datetime, time, timedelta  # noqa: F401
import re 

LATER_DEFAULT_DAYS = 3                         # "p2 reject later" with no number of days
NOT_OPEN = {"scheduled", "unconfirmed", "done", "dropped", "snoozed"}
SNOOZE_FORMAT = re.compile(r"^\s*(\d+d)\b\s*(.*)", re.IGNORECASE)


def digest_date(digest_id: str) -> date:
    """cn-20261019-0700 -> date(2026, 10, 19). Provided."""
    return datetime.strptime(digest_id[3:11], "%Y%m%d").date()


def build_ledger(states: list, now: datetime) -> dict:
    """Replay every digest's state into one status per note.

    Returns {item_id: {"status": str, "until": "YYYY-MM-DD" | None, "times_rejected": int,
                       "last_digest": digest_id}} for every item that has appeared in a digest.
    """
    ledger = {}
    
    # sort states by digest_id so later edits can overwrite in loop order
    for s in sorted(states, key=lambda s: s["digest_id"]):
        for b in s["blocks"]:
            item = b['item_id']
            # setdefault() doesn't overwrite existing edits
            entry = ledger.setdefault(item, {"status": "open", "until": None, "times_rejected": 0, "last_digest": None})
            status = "open"
            until = None
            if b["decision"] is None:
                entry.update(last_digest=s["digest_id"])
                continue
            
            if b["decision"]["action"] == "accept" or b["decision"]["action"] == "edit":
                start_datetime = datetime.fromisoformat(b["start"])
                end_datetime = start_datetime + timedelta(minutes=b["minutes"])
                match b["status"]:
                    case "written": # exists on calendar
                        if end_datetime > now:
                            status = "scheduled"
                        else:
                            status = "unconfirmed"
                    case "approved": # unsure if it made it to calendar
                        # always mark as scheduled into it's confirmed written to calendar, so it doesnt get re-proposed
                        status = "scheduled"
                    case _: pass # conflict / expired / failed: said yes, never reached the calendar → open (L10).

            if b["decision"]["action"] == "reject":
                ledger[item]['times_rejected'] += 1
                
                rejection_reason = b["decision"]['note'].strip().split()
                if len(rejection_reason) == 0:
                    rejection_reason.append("")
                match rejection_reason[0].casefold():
                    case "":
                        status = "open"
                    case "done":
                        status = "done"
                    case "drop":
                        status = "dropped"
                    case "later":
                        snooze_days = LATER_DEFAULT_DAYS
                        if len(rejection_reason) > 1:
                            match1 = SNOOZE_FORMAT.match(rejection_reason[1])
                            if match1:
                                num_days, tail = match1.groups()
                                snooze_days = int(num_days[:-1])
                            
                        # TO DO - change this to pull in the date of gmail reply, not date of digest run.
                        snooze_date = digest_date(s["digest_id"])+timedelta(days=snooze_days)
                        snooze_datetime = datetime.combine(snooze_date, time.min) #midnight of snooze_date
                        if  snooze_datetime > now:
                            snooze_date = snooze_date.strftime("%Y-%m-%d")
                            status = "snoozed"
                            until = snooze_date
            
            entry.update(status=status, until=until, last_digest=s["digest_id"])  
    return ledger


def select_open_items(events: list, ledger: dict, now: datetime, window_days: int = 14) -> list:
    """The pulled notes worth sending to triage and the planner, oldest first."""
    open_items = []
    for e in events:
        # exclude events published by the planner and all-day events
        if e["calnotes_key"] is None and not e["all_day"]:
            # exclude events that are not within the last 14 days
            event_date = datetime.fromisoformat(e["start"])

            if now - timedelta(days=window_days) <= event_date <= now:
                e_id = e["id"]
                if e_id in ledger:
                    if ledger[f"{e_id}"]["status"] not in NOT_OPEN:
                        open_items.append(e)
                else:
                    open_items.append(e)        
    
    
    open_items.sort(key=lambda x: x["start"])
    return open_items
                           
                        