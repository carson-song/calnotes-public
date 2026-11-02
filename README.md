# calnotes

**A hybrid local/frontier AI agent that turns messy, private notes into an approved daily plan.**

###  Problem statement
I use Google Calendar as my primary note-taking mechanism. People generally see this as a bit unusual with so many dedicated "notes apps" on the market, but...
* It solves for fast ‘time-to-keyboard’. Ideas are fleeting, and I need to be able to quickly add notes with only one hand free.  (I’ve found it’s often faster to create a new event in GCal than it is to load a new blank note in many of the major note apps, even when using the "new note" home screen widget...) 
* I can easily search for things by ‘fuzzy relative dates’ because the events are added 'temporally near' memorable events. "Alberto said this interesting thing at our last coffee catch-up which was roughly mid-March..."
* It's easy to distinguish between 'nostalgic notions' and 'imminent to-dos' by simply putting them in the past/future on my calendar. 

For a few years now, I’ve been using the GCal notes method. It’s worked but still requires me to closely review a weakly-structured littering of notes to surface important items. Sorting through a file directory or reading notes line-by-line is a rigid, mechanistic way of looking, and I've found that it often pollutes my creative flow. It feels like a good task to offload to an LLM-powered agent – sift through noisy data, classify them for triage, and suggest scheduled tasks to stay on track. 

I hope to make an attention aid that can do the heavy-lifting organizational work, so I can preserve an unburdened creative headspace and continue my unstructured notetaking habit.

### _Proof of concept:_ 'calnotes' is a system that reads my unstructured notes every morning, identifies actionable tasks that are linked to my goals, asks Claude to plan time for them around my real schedule, emails me the plan, and puts the blocks I approve on my calendar.

I treated this project as primarily an educational tool, especially simulating questions an FDE may face on the job:
* What does it feel like to build alongside a coding agent in Oct 2026? 
* How do various models across the cost-capability pareto perform at elements of this problem (e.g., semantic classification)? 
* Is it changing my day-to-day productivity by suggesting actually useful tasks? 
* How can you design agentic systems that handle sensitive data (e.g., strict boundary controls)?
* How can you solve for common pitfalls like prompt injection and runaway token costs through system design?

A few important design constraints:

- **Raw notes stay local.** A deterministic rule stage and a local model (Ollama) do all reading of note text. Only a pseudonymized, allowlisted batch crosses to an external, frontier model (Claude), through an egress gate that fails closed. (The notes live in GCal -- of course, they are exposed there -- but I'm simulating 'local boundary' for the agentic workflows as a proof of concept)
- **Nothing a model writes can change my calendar.** Approval is a fixed reply grammar parsed by plain code, so text in an email can't talk the system into anything.
- **It runs unattended** on a Mac mini: scheduled jobs, idempotent writes, retries, a dead man's switch.
- **Least privilege, per token.** Four Google tokens, each with one scope and one account: read-only for notes, events-only for the plans calendar, send-only and read-only Gmail on a sandbox mailbox. A runtime check refuses to run if a token is signed in to the wrong account.
- **State is derived, not stored.** The ledger (what's open, scheduled, done, snoozed) is replayed from an append-only log of digests and decisions. No second copy to drift.
- **Fail closed everywhere it matters.** Unmapped placeholders block the digest; calendar errors become tool errors, never "free time"; malformed labels are refused before they become ground truth; the public export refuses to publish if it finds a private name.
- **Measure what the product uses.** The coarse score exists because the planner doesn't care whether a note is a musing or a phrase I liked, only whether it's actionable.

## How it works

There are two calendars - my "raw notes" calendar that I add to throughout the day, and my "primary" calendar that holds my actual scheduled meetings and tasks.

1. All entries pulled from "raw notes" calendar (read-only) and are processed in the ledger -- a history of past decisions related to old notes. Open items (those that were previously marked as 'to-do's' and were not previously scheduled) are passed downstream.
2. A set of deterministic rules (no model) is used to filter raw entries for real notes (to eliminate things like meetings that were accidentally scheduled onto the "raw notes" calendar). 
3. A locally hosted model (Ollama, qwen2.5:7b) reviews the raw notes and organizes them across the semantic spectrum of 'to-do's' vs 'musings/notions'. Raw text never leaves the local machine. [Note: this feels like a good place to use a System One model like Jev instead of the rigid rules for robust classification performance while maintaining low cost].
4. A strict boundary is enforced before passing the tagged notes upstream to a frontier model for strategic planning (vault dictionary from raw to blinded names, fail-closed egress gate, etc.)
5. Claude planner agent (raw Anthropic SDK tool loop) checks "primary calendar" for free slots (sees busy TIMES only, never event titles) and handles the 'high strategy task' of picking the most relevant tasks for the day. Generates email digest with top 5 suggestions and rationale, considering how each task connects to my pre-defined goals.
6. Locally, the email digest is repopoulated with raw names before being sent to my personal email. I have this digest loops configured to run daily at 7am. 
7. Nothing is added to the calendar until I reply to the email in a structured acceptance format ("p1 accept", "p2 edit 60", "p3 reject later 7d"). 
8. An 'approving' agent is configured to review my inbox every 15mins for such replies and uses a deterministic parser + state machine to write accepted tasks to calendar.
9. Every decision logged as eval data to track engagement with the tool and performance of the suggestion engine.

## Results: local vs. frontier triage

I hand-labeled 165 actual calendar notes (removed from this public repo) to evaluate the model's performance in a classification task. The models were shown a raw note like "risks of reward hacking in rl training" and attempted to correctly classify it as "learning-topic" in service of goal 1 "get an applied ai job". 

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

## What's next?
Having used the system for a few weeks, I've realized that my underlying note labeling scheme is flawed. It's not MECE (mutually exclusive and collectively exhaustive) nor does it scale well to other use cases (allowing the heavy classification work to be reused).

A more useful framing is to plot every note along this 2-dimensional spectrum of temporal relevance and action-orientedness

### The 2×2
|                       | **Immediately relevant** | **Lifelong aspiration** |
|-----------------------|--------------------------|-------------------------|
| **Tactical action**   | **Do now**<br>"text nico", "call esther", "measure the hallway"<br> | **Someday projects**<br>"portfolio site for local makers", "invoice-chasing agent"<br>|
| **Nostalgic notion**  | **Current state of mind**<br>"less planning, more doing", a mood, this week's worry<br> | **Keepsakes**<br>"a quiet kind of reckless", identity statements, phrases you liked<br> |


### This structure scales very cleanly to other applications

|                       | **Immediately relevant** | **Lifelong aspiration** |
|-----------------------|--------------------------|-------------------------|
| **Tactical action**   | **_calnotes daily scheduler (this app)_**  | Monthly/quarterly planning and goal-setting |
| **Nostalgic notion**  | Digest of the week's best moments | Long-form review with selections from all historical entries |

### System One as local classification model and scaling digest window

As mentioned above, this classification tasks feels like a ripe opportunity for use of a System One model like Jev as it can allow for robust handling of messy input while achieving better marks on cost and speed. Especially if I'd like to scale the 'digest' protocol to review a wider band of notes data (currently limited to trailing 2 weeks), the speed efficiencies gained from using Jev could ensure the morning digest runs in a reasonable amount of time (~5-10 minutes).


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


> **About the data in this repo.** The pipeline was built and evaluated on 211 of my real calendar notes that I manually tagged as a baseline, which aren't published. Everything here runs on an invented twin dataset (`tests/fixtures/`, copied to `data/`): same structure, same label distribution, same rule behaviour note by note, but every name, place and word is made up.

## How it was built

I wrote the core logic myself (the agent loop, the approval state machine, the ledger, live free/busy) and reviewed it PR-style with Claude, which scaffolded specs, fakes and tests and wrote the adapters and tooling. The notable bugs, including the ones the AI introduced and I caught, are written up in the case study (coming).
