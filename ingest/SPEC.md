# Assignment: the item ledger (ingest/ledger.py)

## Where this sits
```
notes calendar (account 1, read-only) --pull--> data/live/<time>.jsonl
runs/digest/*.json (every digest you've answered) --build_ledger--> {item_id: status}
pulled notes + ledger --select_open_items--> open notes --> triage (local model) --> planner
```
Before this, the planner saw the same ~45 static notes every run, so it re-proposed things you'd
already scheduled or finished. The ledger is how the system remembers.

## Design decision: the ledger is derived, not stored
There is no ledger file. Each run replays every digest state file and works out each note's status.
The digest states are already the record of what you decided and what reached the calendar; a second
store would be a second copy that can drift from the first. (This is event sourcing in miniature:
the facts are the log, the status is a projection of it.) The cost: replay gets slower as digests pile up.
At one digest a day that's years away, and it would be fixed by a cache, not a new source of truth.

## Statuses
| status | meaning | sent to planner? |
|---|---|---|
| open | no decision yet, or nothing stuck | yes |
| scheduled | approved; the block is ahead of us (or not yet written) | no |
| unconfirmed | the block happened, but you haven't said whether you did it | no (step 2 asks you) |
| done | you rejected it with `done` | no |
| dropped | you rejected it with `drop` | no |
| snoozed | you rejected it with `later` / `later Nd`; comes back on its date | no, until then |

## Requirements: build_ledger(states, now)
- **L1** A block with no decision (`decision` is None) leaves its item open.
- **L2** Reject whose note starts with the word `done` → done; `drop` → dropped.
- **L3** `later Nd` → snoozed, `until` = the digest's date + N days, as `"YYYY-MM-DD"`.
  Plain `later` uses `LATER_DEFAULT_DAYS`. The digest's date comes from its id: `digest_date()`.
- **L4** A snooze ends *on* its date: snoozed on 10-20 at 23:00 with until 10-21; open at 10-21 00:01.
- **L5** Any other reject → open, and `times_rejected` goes up by one. (Every reject counts, including done/drop.)
- **L6** Reasons ignore case (`DONE` is done), but match the whole first word: `Done!` is not `done`. Don't guess.
- **L7** Accept/edit and `written`, with the block's end (start + minutes) still after now → scheduled.
- **L8** `written` and the block has ended → unconfirmed.
- **L9** `approved` (not yet written: a retry is pending) → scheduled.
- **L10** `conflict`, `expired`, `failed` → open. You said yes, but it never reached the calendar.
- **L11** The latest digest wins, whatever order the list arrives in. Digest ids sort by time.
- **L12** `times_rejected` adds up across digests.

Every item that appears in any digest gets an entry:
`{"status", "until" (None unless snoozed), "times_rejected", "last_digest"}`.

## Requirements: select_open_items(events, ledger, now, window_days=14)
- **S1** Skip events with a `calnotes_key` (our own blocks, on the notes calendar too if you ever point
  both at one account) and all-day events.
- **S2** Keep `now - window_days <= start <= now`. The edge is included.
- **S3** Skip items whose ledger status is in `NOT_OPEN`. Items never proposed are open.
- **S4** Return them sorted by start.

## Hints (read only if stuck)
1. Sort states by `digest_id` once, then walk them; later writes to the same item overwrite earlier ones.
   That's all L11 is.
2. Keep `times_rejected` separate from the rest of the entry, or a later digest's overwrite resets it (L12).
3. `note.split()` gives words; `[0]` of an empty list raises. What's `"".split()`?
4. For `later 5d`, a regex like `r"(\d+)d"` on the second word is enough. Decide what `later soon` means
   (the tests don't say; pick something and write it in a comment).
5. Snooze expiry (L4) is easiest as one pass *after* the replay, comparing `until` with `now.date()`.
6. Starts are strings; `datetime.fromisoformat` handles `"2026-10-19T09:00"`.

## Review questions (answer before the PR)
1. Why does L10 send a `failed` block back to open instead of keeping it failed?
2. `unconfirmed` items aren't sent to the planner. What breaks if step 2 (check-ins) never ships?
3. A note's title changes on the calendar after it was proposed. What does the ledger do, and is that right?
4. What happens to the ledger if you delete one digest state file? Is that a bug or a feature?

Acceptance: `python3 -m unittest tests.test_ledger -v` (16 tests).
