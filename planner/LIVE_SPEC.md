# Assignment: the planner sees your live calendar

Today the planner works out busy time from the snapshot in `data/events_v0.jsonl`, so it believes every
future day is empty and proposes blocks that collide with real events. They're caught at approval time
(`conflicts: p2, p3`), but each one is a wasted proposal. Fix it at the source.

You change `planner/tools.py` (the `ToolBox`), your `planner/agent.py` and `plan_demo.py`.
Acceptance: `python3 -m unittest tests.test_tools_live tests.test_tools -v`.

## Why only times cross

The planner needs to know *when* you're busy, not *what* you're doing. `calendar.busy()` returns
`(start, end)` pairs, no titles, no people, so busy time can go to the model at every privacy level,
including 0. Keep it that way: never pass event objects or titles through a tool result.

## Requirements

- **L1.** `ToolBox(batch, calendar=None, now=None)`. With neither given, behavior is exactly as today
  (the existing `tests.test_tools` keep passing).
- **L2.** With a `calendar`, busy time for a date comes from `calendar.busy(day 00:00, next day 00:00)`
  instead of the batch's event records. Blocks already proposed in this run still count as busy.
- **L3.** **Fail closed.** If the calendar raises any `CalendarError` (transient or not), the tool raises
  `ToolError` saying the calendar is unavailable. Never treat "couldn't check" as "free": that's how a
  planner books over your dentist appointment.
- **L4.** With `now`: today's free time starts at the next quarter hour after `now` (10:07 becomes 10:15);
  days before today have no free time; `propose_block` refuses a start before `now`.
- **L5.** Nothing from an event's content appears in any tool result.
- **L6 (wiring, no unit test).**
  - `run_agent` takes optional `calendar=None, now=None` and passes them to `ToolBox`. Your
    `tests.test_agent` must still pass.
  - `plan_demo.py`: build `TASK` from `date.today()` (plan today plus the next two days), and pass
    `GoogleCalendar()` and `datetime.now()` to `run_agent`. Add `--calendar snapshot` to keep the old
    behavior for offline runs.

## How to work

L1 is the constructor. L2 and L3 both live in `_busy()`; that's the only place busy time is computed, so
`get_free_slots` and `propose_block` get the live data and the fail-closed behavior for free. L4 touches
`get_free_slots` (where the window starts) and `propose_block` (one more check).

## What I'll look at in review

- **L3:** what does the model see when the calendar is down, and what would it do next? Read the error
  message you return as if you were the model.
- **Two checks, on purpose:** the approval step still checks the calendar right before writing. Why keep
  that check now that the planner sees live data? (Hint: time passes between the plan and your reply.)
- **The cost:** each `get_free_slots` call is now an API call. How many does a planning run make?

## Hints (read only if stuck)

<details><summary>1. Catching both error types</summary>
<code>TransientCalendarError</code> is a subclass of <code>CalendarError</code>, so one
<code>except CalendarError as e:</code> catches both. Re-raise as <code>ToolError(...) from e</code>.
</details>

<details><summary>2. Rounding up to the quarter hour</summary>
<code>t += timedelta(minutes=(-t.minute) % 15)</code> after zeroing seconds. Then start the day's window at
<code>max(09:00, that)</code>.
</details>
