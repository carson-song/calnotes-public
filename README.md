# calnotes

**An AI agent that turns messy calendar notes into a daily plan I approve by email, built so my raw notes never leave my machine.**

I use Google Calendar as a scratchpad: a 60-minute "event" that says `text nico. and ben okafor` is really a to-do; one that says `a quiet kind of reckless` is a phrase I liked. calnotes reads those notes every morning, works out which are tasks and which goals they serve, asks Claude to plan time for them around my real schedule, emails me the plan, and puts the blocks I approve on my calendar.

The interesting part isn't the planning. It's doing it over data I treat as sensitive:

- **Raw notes stay local.** A deterministic rule stage and a local model (Ollama) do all reading of note text. Only a pseudonymized, allowlisted batch crosses to Claude, through an egress gate that fails closed.
- **Nothing a model writes can change my calendar.** Approval is a fixed reply grammar parsed by plain code, so text in an email can't talk the system into anything.
- **It runs unattended** on a Mac mini: scheduled jobs, idempotent writes, retries, a dead man's switch.

> **About the data in this repo.** The pipeline was built and evaluated on 211 of my real calendar notes, which aren't published. Everything here runs on an invented twin dataset (`tests/fixtures/`, copied to `data/`): same structure, same label distribution, same rule behaviour note by note, but every name, place and word is made up.

## How it works

```
notes calendar (read-only) ──▶ pull ──▶ ledger: what's still open?
        │
        ▼
 stage 1: rules (no model) ──▶ stage 2: local model (Ollama, qwen2.5:7b)      ← raw text never leaves the machine
        │
        ▼
 egress gate: allowlist by privacy level, names → [PERSON_n], items → handles  ← fails closed
        │
        ▼
 Claude planner agent (raw Anthropic SDK tool loop; sees busy TIMES only, never titles)
        │
        ▼
 vault maps handles back locally ──▶ email digest ──▶ my reply ("p1 accept", "p2 edit 60", "p3 reject later 7d")
        │
        ▼
 deterministic parser + state machine ──▶ calendar write (idempotency key, retries, conflict and expiry checks)
        │
        ▼
 every decision logged as eval data
```

| Folder | What's in it |
|---|---|
| `triage/` | Stage 1 rules (`detect.py`), local and frontier model backends, few-shot selection, output schemas |
| `boundary/` | The trust boundary: privacy levels, pseudonymizing vault, egress gate. See `boundary/CONTRACT.md` |
| `planner/` | The agent loop and its tools (free/busy, propose a block) |
| `digest/` | Builds and sends the email digest |
| `approve/` | Reply parsing, the approval state machine, Google Calendar and Gmail adapters |
| `ingest/` | Live pull from the notes calendar, and the ledger: each note's status derived by replaying past decisions |
| `ops/` | Scheduler (launchd), sign-in helper, Mac mini runbook, public export |
| `tools/` | Hand-labeling tool, label checks, eval comparison |

## Results: local vs. frontier triage

165 held-out notes, hand-labeled, never seen by any prompt. Scores are from my real notes; the eval code here is the same.

| Model | Type | Coarse | Goals | s/note | Cost per run |
|---|---|---|---|---|---|
| llama3.2:3b (local) | 66% | 79% | 52% | 1.4 s | $0 |
| **qwen2.5:7b (local)** | **68%** | **81%** | **73%** | **2.7 s** | **$0** |
| qwen2.5:14b (local) | 68% | 81% | 73% | 5.4 s | $0 |
| Claude Haiku 5.5 | 66% | 79% | 73% | 1.8 s | $0.05 |
| Claude Sonnet 5.5 | 72% | 85% | 79% | 3.2 s | $1.17 |

*Type = exact category (9 types). Coarse = the four buckets the planner acts on (event / actionable / reflection / goal). Goals = exact goal links. ±7 points at 95%.*

- **3B → 7B is the one large, certain gain** (goal linking 52% → 73%, paired McNemar p < 0.001).
- **Above 7B, local and frontier are statistically indistinguishable** (7B vs Sonnet: type p = 0.39, goals p = 0.21). Keeping raw notes on-device costs no measurable accuracy at this sample size.
- **Most "type" errors weren't the model's**: label definitions that had drifted from the guide, a genuinely blurry musing/learning-topic boundary, and one stage-1 rule. Scored on what the planner uses, the 7B is 81%.
- **Frontier answers vary run to run** (two identical Haiku runs disagreed on 16% of goal links), so single-run comparisons between frontier models need care.
- Caveats: labels were revised after error analysis on the 7B run, which may favour it by a few notes; sending raw notes to the API for this comparison was a one-time, explicit opt-in (`--send-raw-notes`) that production never uses.

## Run it (invented data, no accounts needed)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests          # the whole suite runs offline on the invented data
.venv/bin/python run_eval.py --labeler oracle           # plumbing check: must score 100%
.venv/bin/python run_eval.py --labeler baseline         # keyword baseline
# with Ollama running and a model pulled:
.venv/bin/python run_eval.py --labeler ollama --model qwen2.5:7b
```

Running it against your own calendar needs a Google Cloud OAuth client, two accounts (one read-only for notes) and an Anthropic API key; `ops/MAC_MINI.md` walks through the full setup, and `ops/signin.py` signs in each token with its own least-privilege scope.

## Design decisions worth reading

- **Least privilege, per token.** Four Google tokens, each with one scope and one account: read-only for notes, events-only for the plans calendar, send-only and read-only Gmail on a sandbox mailbox. A runtime check refuses to run if a token is signed in to the wrong account.
- **State is derived, not stored.** The ledger (what's open, scheduled, done, snoozed) is replayed from an append-only log of digests and decisions. No second copy to drift.
- **Fail closed everywhere it matters.** Unmapped placeholders block the digest; calendar errors become tool errors, never "free time"; malformed labels are refused before they become ground truth; the public export refuses to publish if it finds a private name.
- **Measure what the product uses.** The coarse score exists because the planner doesn't care whether a note is a musing or a phrase I liked, only whether it's actionable.

## How it was built

I wrote the core logic myself (the agent loop, the approval state machine, the ledger, live free/busy) and reviewed it PR-style with Claude, which scaffolded specs, fakes and tests and wrote the adapters and tooling. The notable bugs, including the ones the AI introduced and I caught, are written up in the case study (coming).
