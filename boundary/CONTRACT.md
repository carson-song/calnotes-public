# Trust boundary contract (v1)

Raw calendar data never leaves the machine. The only path to the frontier model is
`boundary.export.export_batch()`, which applies this contract, checks the result, drops anything that
fails (fail closed), and writes what it sent to a local audit log.

## What crosses, by item type and privacy level

| Field | Event | Action / idea / learning / goal | Musing | Good words | Friend's goal | Level |
| --- | --- | --- | --- | --- | --- | --- |
| `handle` (opaque id, not the Google id) | yes | yes | yes | yes | yes | 0 |
| `type`, `date`, `goal_links`, `confidence` | yes | yes | yes | yes | yes | 0 |
| `pending_clarification` (flag only, never the question) | yes | yes | yes | yes | yes | 0 |
| `start`, `end` | yes | – | – | – | – | 0 |
| `musing_theme` | – | – | yes | – | – | 0 |
| `has_next_action`, `people_count` | yes | yes | – | – | – | 0 |
| `people` as `[PERSON_n]`, `org` as `[ORG_n]` | yes | yes | – | – | – | 1 |
| `next_action`, pseudonymized | yes | yes | – | – | – | 1 |
| `text` (normalized note), pseudonymized | – | yes | – | – | – | 2 |

**Also crosses:** the goal definitions in `planner/tools.GOALS_SUMMARY`, written in general terms with no
names, places or companies. A planner can't prioritize without them.

**Never crosses at any level:** raw titles, descriptions, locations, the clarifying question itself,
Google event ids, detection details, and any text from musings, good words or friends' goals.

Default level: **1**.

## Checks on every record (violations are dropped, not sent)

1. Only allowlisted keys; enum fields hold valid values.
2. No text fields on never-text types.
3. No real name from the vault, word for word, in any string.
4. No place words from the item's location.
5. No planted canary strings (tests).

Verbatim overlap between an exported string and the raw title is *reported*, not blocked, at
levels 1–2: an action like "measure the hallway for a shelf" is the content by design. That is the
privacy-vs-utility trade the levels exist to measure.

## Coming back the other way

The frontier model refers to items by `handle` and to people by `[PERSON_n]`. `Vault.reidentify()`
maps them back locally, just before an action runs. The frontier side never holds the mapping.

## Outbound: the digest (second boundary)

After the planner finishes, `digest/` maps its proposals back to real notes and names (locally) and
emails them. This is a different boundary with a different counterparty:

| | Frontier model (egress gate) | Email digest |
| --- | --- | --- |
| Who receives it | the model vendor | Google (Gmail), to one address you set |
| What crosses | sanitized fields by level, no real names | real note titles, next actions, names, the planner's notes |
| Why that's acceptable | it's the minimum the planner needs | Google already holds the raw calendar; nothing new reaches a new party |
| Checks | allowlist, name/place/canary checks, drop on violation | no leftover `[PERSON_n]`/handles (refuse to send), exactly one recipient from `CALNOTES_DIGEST_TO` |
| Scope | – | OAuth `gmail.send` only: the pipeline can send mail but can't read it |

**Coming back: your reply.** `approve/inbox.py` reads the digest's Gmail thread with its own read-only
token (`gmail.readonly`). Only messages from `CALNOTES_DIGEST_TO` are applied; anything else in the thread
is listed and ignored. Replies are parsed by fixed rules, never by a model, so text in an email can't
instruct the system. Each applied reply's id is kept in the state, so a reply is applied once.

Never in a digest: musings, good words, friends' goals (they can't be planned, so they never become
blocks), locations, or clarifying questions. A local copy of every digest is kept in `runs/digest/`.

## Two Google accounts

| Account | Role | Permission | Token |
| --- | --- | --- | --- |
| notes (`CALNOTES_NOTES_ACCOUNT`) | source of notes (live ingest) | `calendar.readonly` | `secrets/token_cal_notes.json` |
| plans (`CALNOTES_PLANS_ACCOUNT`) | busy time for the planner and approvals; approved blocks are written here | `calendar.events` | `secrets/token_cal_plans.json` |

Read from a source of record, write to a separate output: the planner's blocks never land in the calendar
notes are read from, and the notes token can't write at all. Each calendar checks which account signed in
and stops the run on a mismatch. Only busy *times* from the plans account reach the model, never titles.

## Known limits

- Pseudonymization only catches names it knows: the item's `people`, `company`, and first names from
  past meeting logs. An unknown name inside free text can slip through at levels 1–2. Level 0 can't leak
  names because it sends no words.
- Next actions and note text carry meaning even with names removed. That is semantic leakage, by design.
- Google already holds the raw calendar. The egress gate is about the model vendor.
- Names the vault doesn't know cross in clear text at level 2. Seen in the L2 sandbox run: a product
  name and a business name (the business labeled with no org). Fix: label the org; later, have the
  local model flag proper nouns and block items with unknown ones.
