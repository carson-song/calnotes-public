# Assignment: the approval step

You write two functions: `parse_reply()` in `approve/parse.py` and `apply_decisions()` in `approve/apply.py`.
Everything else is provided: the calendar interface (`approve/calendar.py`), a fake calendar with failure
injection (`approve/fake.py`), the real Google adapter (`approve/gcal.py`), the runner (`approve_run.py`) and
the acceptance tests (`tests/test_approve.py`).

**Rules:** standard library only. Don't change the provided files or the tests. Try it without looking back
at earlier code in our conversation; the hints at the bottom are there if you get stuck.

## Where it sits

```
digest email ─► you reply "p1 accept / p2 edit 60 / p3 reject" ─► parse_reply ─► apply_decisions ─► calendar
                                                                                      │
                                     runs/digest/<id>.json (state) ◄── save() ────────┘
                                     runs/eval/decisions.jsonl     ◄── approve_run.py (eval data)
```

No model on this path, on purpose. Your reply is parsed by fixed rules, so nothing written in an email can
talk the system into writing to your calendar.

## The state you're updating

`runs/digest/<id>.json` has `digest_id` and a list of `blocks`. Each block:

```
proposal_id "p1" · item_id · title · start "2026-10-15T09:00" · minutes · proposed_minutes · reason
status "proposed" · decision null · attempts 0 · event_id null
```

## Part 1: `parse_reply(text, proposal_ids) -> ParseResult`

- **P1.** One command per line: `p<n> accept`, `p<n> edit <minutes> [note]`, `p<n> reject [note]`.
  Case-insensitive, extra spaces OK. Decisions come out in reply order.
- **P2.** Stop at the quoted original: a line starting with `>` or an `On ... wrote:` line ends the reply.
  The digest itself contains example lines like "p1 accept", so this one matters.
- **P3.** Lines that aren't commands (greetings, signatures) are ignored silently.
- **P4.** A block that isn't in `proposal_ids` is an error; the other lines still count.
- **P5.** `edit` needs a whole number from 15 to 240, or it's an error.
- **P6.** A block named on two lines is ambiguous: an error, and *neither* line counts. Don't guess.
- **P7.** An unknown command (`p1 maybe`) is an error.

Errors never raise. Each one is a readable message naming the block, so the runner can show it to you.

## Part 2: `apply_decisions(state, decisions, calendar, now, save) -> ApplyReport`

A small state machine per block:

```
proposed ──accept/edit──► approved ──write ok──► written
    │                        │ ├──slot taken──► conflict
    └──reject──► rejected    │ ├──end passed────► expired
                             │ └──permanent error, or MAX_ATTEMPTS transient errors──► failed
                             └──transient error──► approved (attempts + 1; a later run retries)
```

- **A1.** Accepting writes an event: `title` as the summary, `start` to `start + minutes`, `reason` as the
  description, key `"<digest_id>:<proposal_id>"`. Store the returned `event_id`; status becomes `written`.
- **A2.** `edit` sets `minutes` (keep `proposed_minutes` as it was), then writes like an accept.
- **A3.** `reject` writes nothing. Store the decision as `{"action", "minutes", "note"}` for every action.
- **A4.** Blocks without a decision stay exactly as they were.
- **A5.** **Idempotent replies.** Applying the same decision again is a no-op (`unchanged`), with no new event.
- **A6.** A *different* decision on an already-decided block is refused (`errors`); the block doesn't change.
- **A7.** A decision for a block that doesn't exist is an error.
- **A8.** **Lost responses.** The calendar may create the event and then time out. You can't tell the
  difference from a failure, so treat it as transient. The next run must find the event by its key
  (`calendar.find_by_key`) instead of creating a second one.
- **A9.** Transient errors: the block stays `approved` with `attempts + 1` and goes in `retry`. After
  `MAX_ATTEMPTS` it's `failed`.
- **A10.** One block failing doesn't stop the others.
- **A11.** Check `calendar.busy()` before writing; if anything overlaps, the block is a `conflict`.
- **A12.** That includes blocks you just wrote in the same run (an edit can make p1 run into p2).
- **A13.** A block whose end (start + minutes) is at or before `now` is `expired`, not written.
- **A21.** A block that has started but not ended is still written, at its original time: approving it
  10 minutes in leaves you the rest of the block. (Changed 2026-10-29: expiry used to be on the start.)
- **A14.** Call `save(state)` after each block changes, so a crash halfway loses nothing.

Write the blocks in start-time order. Every approved block is attempted on every run, including ones
approved in an earlier run, which is how `--retry` works.

## How to work

```bash
python3 -m unittest tests.test_approve -v     # 31 tests; TestRunner passes already
```

Do Part 1 first, P1 to P7, then Part 2 in order. Then try it:

```bash
python3 digest_run.py                                    # makes runs/digest/<id>.json
python3 approve_run.py runs/digest/<id>.json             # paste a reply, Ctrl-D: dry run
python3 approve_run.py runs/digest/<id>.json --write     # real calendar (sandbox account)
```

For `--write`, enable the **Google Calendar API** in the same Cloud project as Gmail. The first run asks you
to sign in again: it's a separate token, scope `calendar.events`, so the mail code can't touch your
calendar and vice versa.

## What I'll look at in review

- **Ordering inside a block:** which check comes first, finding the key, expiry or conflict, and why? Get
  it wrong and a retry after a lost response reports a conflict with your own event.
- **When you save:** before or after the calendar call, and what a crash at each point leaves behind.
- **Readability:** a state machine should read like one. Could someone see the transitions in one pass?

## Hints (read only if stuck)

<details><summary>1. Parsing a line</summary>
A regex like <code>^\s*(p\d+)\s*(.*)$</code> (case-insensitive) splits the block from the rest. Then
<code>rest.split(maxsplit=1)</code> gives the command and everything after it.
</details>

<details><summary>2. Duplicates (P6)</summary>
Count how many times each block appears while you parse; drop the ones counted twice at the end.
</details>

<details><summary>3. Two passes</summary>
Pass 1: apply decisions to the state (no calendar calls). Pass 2: for every <code>approved</code> block,
try to write it. Splitting them makes A5, A6 and the retry behavior fall out naturally.
</details>

<details><summary>4. Comparing decisions (A5 vs. A6)</summary>
Turn the incoming Decision into the same dict you store, then compare it with <code>==</code>.
</details>
