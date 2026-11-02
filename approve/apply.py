"""YOUR ASSIGNMENT, part 2: apply decisions to the digest state and write to the calendar.

Read approve/SPEC.md first. Acceptance: the TestApply tests in tests/test_approve.py.
"""
from dataclasses import dataclass, field
from datetime import datetime  # noqa: F401
from datetime import timedelta  # noqa: F401

from approve.calendar import CalendarError, TransientCalendarError  # noqa: F401

MAX_ATTEMPTS = 3   # transient failures before a block is marked failed


@dataclass
class ApplyReport:
    """Proposal ids by what happened to them in this run."""
    written: list = field(default_factory=list)    # on the calendar now (including found from an earlier run)
    rejected: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)  # the slot is no longer free
    expired: list = field(default_factory=list)    # its start time has passed
    retry: list = field(default_factory=list)      # transient failure; a later run will try again
    failed: list = field(default_factory=list)     # permanent failure, or out of attempts
    unchanged: list = field(default_factory=list)  # same decision as before: nothing to do
    errors: list = field(default_factory=list)     # messages: unknown block, conflicting decision


def apply_decisions(state: dict, decisions: list, calendar, now: datetime, save) -> ApplyReport:
    """Update state in place, write approved blocks through calendar, call save(state) as you go."""
    rep = ApplyReport()
    blocks = {b["proposal_id"]: b for b in state["blocks"]}

    # loop through decisions and 'approve' before trying to write to calendar 
    for d in decisions:
        #check for existence in state
        b = blocks.get(d.proposal_id)
        if b is None:
            #error
            rep.errors.append(f"{d.proposal_id} no such block")
            # print(f"no proposal exists for instruction {d}")
            continue
        
        # there is a block for this proposal
        
        # review for approval 
        
        if b["decision"] is None:
            #check if decision type
            match d.action:
                case "reject":
                    rep.rejected.append(d.proposal_id)
                    b["status"] = "rejected"
                    b["decision"] = as_record(d)
                    save(state)
                    continue
                # case "accept":
                #     meeting_mins = b["minutes"]
                case "edit":
                    # meeting_mins = d.minutes
                    b["minutes"] = d.minutes
            
            b["status"] = "approved"
            b["decision"] = as_record(d)
            save(state)
            
            
        else:
            if b["decision"] == as_record(d):
                rep.unchanged.append(d.proposal_id)
                # print("error, event already processed")
            else:
                rep.errors.append(f"{d.proposal_id}, mismatched requests for that block")
                # print("error, mismatched requests for that proposal id")
    
    for b in sorted(state["blocks"], key=lambda b: b["start"]):
        if b["status"] != "approved":
            continue

        # check if event already exists on calendar
        key = f"{state['digest_id']}:{b['proposal_id']}"
            
            
        try:
            e_id = calendar.find_by_key(key)
            if e_id is None:
                # check if busy
                start = datetime.fromisoformat(b["start"])          # "2026-10-15T09:00" → datetime
                end   = start + timedelta(minutes=b["minutes"])
                
                if end <= now:
                    b["status"] = "expired"
                    rep.expired.append(b["proposal_id"])
                    # print("meeting time has already passed")
                
                else:
                    busy = calendar.busy(start, end)
                    
                    if len(busy) != 0:      # → [] (free)
                        rep.conflicts.append(b["proposal_id"])
                        b["status"] = "conflict"
                        # print("error, time slot is 'busy'")
                    else:
                        # try to add it
                        # print("attempt #: ", b["attempts"])
                        
                        event_id = calendar.insert(b["title"], start, end, b["reason"], key)   # → "ev1"
                        # succeeded
                        b["event_id"] = event_id
                        rep.written.append(b["proposal_id"])
                        b["status"] = "written"
                        
                        
            
            
            else:
                # succeeded without confirmation receipt, update state
                rep.written.append(b["proposal_id"])
                b["event_id"] = e_id
                b["status"] = "written"
        

        except TransientCalendarError:
            b["attempts"] += 1
            if b["attempts"] >= MAX_ATTEMPTS:
                b["status"] = "failed"
                
                rep.failed.append(b["proposal_id"])
            else:
                rep.retry.append(b["proposal_id"])
            
        except CalendarError:
            b["status"] = "failed"
            
            rep.failed.append(b["proposal_id"])
            
        save(state)
    return rep

def as_record(d):
    return {"action": d.action, "minutes": d.minutes, "note": d.note}