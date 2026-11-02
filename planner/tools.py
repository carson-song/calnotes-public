"""Tools the planner agent may call. Provided for you: do not change them for the assignment.

They only ever see the sanitized EgressBatch, never raw calendar data. Every tool returns a JSON
string (what goes back to the model) or raises ToolError (which your loop must turn into an
is_error tool_result, not a crash).
"""
import json
from datetime import datetime, timedelta

from boundary import policy as P
from boundary.export import EgressBatch
from triage import schema as S
from approve.calendar import CalendarError, TransientCalendarError  # noqa: F401

DAY_START, DAY_END = 9, 21           # plan between 09:00 and 21:00
PLANNABLE = P.ACTIONABLE - {"event"}  # events are already on the calendar; reflections are never planned
MAX_PROPOSALS = 5
SECONDS_IN_15_MINS = 15 * 60

# Goal definitions cross the boundary on purpose: a planner can't prioritize without them.
# They are written in general terms, with no names, places or companies.
GOALS_SUMMARY = {
    "G1": "Get a job in power electronics or AI: job leads, networking, AI portfolio projects, AI learning.",
    "G2": "Finish a friend's apartment build-out: making and finishing physical projects.",
    "G3": "Furniture curation and fulfillment: designers, makers, showrooms, the art scene, selling.",
}


class ToolError(Exception):
    """A tool refused the request. Report it to the model; don't crash."""


class ToolBox:
    def __init__(self, batch: EgressBatch, calendar=None, now=None):
        if not isinstance(batch, EgressBatch):
            raise TypeError("ToolBox only accepts an EgressBatch from boundary.export_batch")
        self.batch = batch
        self.items = {r["handle"]: r for r in batch.records}
        self.proposals: list[dict] = []
        self.calendar = calendar
        self.now = now

    # --- what the model sees --------------------------------------------------
    @property
    def definitions(self) -> list[dict]:
        return [
            {
                "name": "list_items",
                "description": (
                    "List the user's sanitized calendar items. Each item has an opaque handle, a type, "
                    "a date, goal links (G1-G3) and, for actionable items, placeholder people like "
                    "[PERSON_3] and a next action. Filter by type or goal to keep results short. "
                    "Items with pending_clarification=true are uncertain; prefer not to schedule them."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": S.TYPES, "description": "Only items of this type."},
                        "goal": {"type": "string", "enum": S.GOALS, "description": "Only items linked to this goal."},
                        "include_pending": {"type": "boolean", "description": "Include uncertain items. Default true."},
                    },
                },
            },
            {
                "name": "get_free_slots",
                "description": (
                    "Return free time windows on one date between 09:00 and 21:00, after removing existing "
                    "events and blocks you already proposed. Call this before proposing a block on a date."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "YYYY-MM-DD"},
                        "min_minutes": {"type": "integer", "description": "Shortest window to return. Default 30."},
                    },
                    "required": ["date"],
                },
            },
            {
                "name": "propose_block",
                "description": (
                    "Propose a time block to work on one item. This does NOT change the calendar; the user "
                    "approves proposals later. Only actions, ideas, learning topics and goals can be planned "
                    "(not events, musings, good words or friends' goals). At most 5 proposals, one per item, "
                    "15-240 minutes, inside a free window. Returns an error explaining any problem."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "handle": {"type": "string", "description": "The item's handle, e.g. h_3fa9c01b2e"},
                        "start": {"type": "string", "description": "YYYY-MM-DDTHH:MM"},
                        "minutes": {"type": "integer"},
                        "reason": {"type": "string", "description": "One sentence: why this item, why now."},
                    },
                    "required": ["handle", "start", "minutes", "reason"],
                },
            },
        ]

    def call(self, name: str, args: dict) -> str:
        fn = {"list_items": self.list_items, "get_free_slots": self.get_free_slots,
              "propose_block": self.propose_block}.get(name)
        if fn is None:
            raise ToolError(f"unknown tool {name!r}")
        try:
            return json.dumps(fn(**(args or {})), ensure_ascii=False)
        except TypeError as e:  # wrong or missing arguments
            raise ToolError(f"bad arguments for {name}: {e}") from e

    # --- implementations --------------------------------------------------------
    def list_items(self, type=None, goal=None, include_pending=True):
        out = []
        for r in self.batch.records:
            if type and r["type"] != type:
                continue
            if goal and goal not in r.get("goal_links", []):
                continue
            if not include_pending and r.get("pending_clarification"):
                continue
            out.append(r)
        return out

    def _busy(self, date: str):
        spans = []
        #checks live calendar for a latest blocks
        
        if self.calendar is not None:
            
            try: 
                start_date = datetime.fromisoformat(date)
                end_date = start_date + timedelta(days=1)
                busy_times = self.calendar.busy(start_date, end_date)
                
                spans += busy_times
            
            except TransientCalendarError:
                raise ToolError("transient calendar error")
                
            except CalendarError:
                raise ToolError("permanent calendar error")
        
        else:
            #adds existing blocks from json dump (static)
            for r in self.batch.records:
                if r["type"] == "event" and r["start"][:10] == date:
                    spans.append((datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])))

        #adds already proposed blocks to prevent overlapping proposals in a single run
        for p in self.proposals:
            if p["start"][:10] == date:
                s = datetime.fromisoformat(p["start"])
                spans.append((s, s + timedelta(minutes=p["minutes"])))
        
        #returns a sorted list of datetime objects where consecutive pairs are 'start', 'end' times of cal blocks.
        return sorted(spans)

    def get_free_slots(self, date, min_minutes=30):
        try:
            day = datetime.fromisoformat(date)
        except ValueError as e:
            raise ToolError(f"date must be YYYY-MM-DD, got {date!r}") from e
        def _round_to_next_15(dt):
            #add one microsecond to ensure we start at 'next' 15m
            dt = dt+timedelta(microseconds=1)

            # Total seconds past the hour
            seconds = (dt - dt.replace(minute=0, second=0, microsecond=0)).total_seconds()   
            # Calculate how many seconds to add to reach the next 15-minute mark
            remainder = seconds % SECONDS_IN_15_MINS
            if remainder == 0:
                return dt
            delta_seconds = SECONDS_IN_15_MINS - remainder
            return dt + timedelta(seconds=delta_seconds) 
        
        cur = day.replace(hour=DAY_START)
        if self.now is not None:
            next_15 = _round_to_next_15(self.now)
            # set cur to start of working hours of date or next whole 15min mark if date == today()
            cur = max(next_15, cur)
            
        
        # cur, end = day.replace(hour=DAY_START), day.replace(hour=DAY_END)
        end = day.replace(hour=DAY_END)
        free = []
        for s, e in self._busy(date):
            if s > cur and (s - cur) >= timedelta(minutes=min_minutes):
                free.append([cur.isoformat(timespec="minutes"), min(s, end).isoformat(timespec="minutes")])
            cur = max(cur, e)
        if end > cur and (end - cur) >= timedelta(minutes=min_minutes):
            free.append([cur.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")])
        return free

    def propose_block(self, handle, start, minutes, reason):
        item = self.items.get(handle)
        if item is None:
            raise ToolError(f"no item with handle {handle!r}")
        if item["type"] not in PLANNABLE:
            raise ToolError(f"items of type {item['type']!r} can't be planned")
        if any(p["handle"] == handle for p in self.proposals):
            raise ToolError("this item already has a proposed block")
        if len(self.proposals) >= MAX_PROPOSALS:
            raise ToolError(f"limit of {MAX_PROPOSALS} proposals reached")
        if not isinstance(minutes, int) or not 15 <= minutes <= 240:
            raise ToolError("minutes must be an integer from 15 to 240")
        if not reason or len(reason) > 200:
            raise ToolError("reason must be one sentence, under 200 characters")
        try:
            s = datetime.fromisoformat(start)
        except ValueError as e:
            raise ToolError(f"start must be YYYY-MM-DDTHH:MM, got {start!r}") from e
        if self.now is not None:
            if s < self.now:
                raise ToolError(f"start must be after current time of {self.now}")
        e = s + timedelta(minutes=minutes)
        if s.hour < DAY_START or e > s.replace(hour=DAY_END, minute=0):
            raise ToolError("block must fit between 09:00 and 21:00")
        for bs, be in self._busy(start[:10]):
            if s < be and bs < e:
                raise ToolError(f"overlaps a busy period {bs:%H:%M}-{be:%H:%M}")
        p = {"proposal_id": f"p{len(self.proposals) + 1}", "handle": handle,
             "start": s.isoformat(timespec="minutes"), "minutes": minutes, "reason": reason}
        self.proposals.append(p)
        return {"ok": True, **p}

    