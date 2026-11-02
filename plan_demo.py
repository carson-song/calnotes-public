"""Run YOUR agent (planner/agent.py) against the real Claude API on the sandbox batch.

  pip install anthropic && export ANTHROPIC_API_KEY=...
  python3 plan_demo.py
  python3 plan_demo.py --level 0          # compare: no words cross the boundary
  python3 plan_demo.py --model claude-haiku-5-5

Only the sanitized batch goes to the API. Proposals are mapped back to your real notes here, locally.
For the emailed version, see digest_run.py.
"""
import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import run_eval
from boundary.export import EgressBatch, export_batch
from boundary.vault import Vault
from export_demo import label_all
from planner.agent import AgentResult, run_agent
from triage import detect
from datetime import date, datetime, timedelta


ROOT = Path(__file__).parent
NOW = datetime.now()
# # ONE_WEEK_FROM_NOW = NOW + timedelta(days=7)
# NEXT_TWO_DAYS = NOW + timedelta(days=2)

# TASK = (
#     f"Today is {NOW}. Propose up to 5 time blocks between {NOW} and {NEXT_TWO_DAYS} for the items that "
#     "best move my goals forward. Check free time before proposing. Finish with a short explanation of "
#     "what you picked and what you left out."
# )

def make_task(today: date) -> str:
    end = today + timedelta(days=2)
    return (f"Today is {today.isoformat()}. Propose up to 5 time blocks between {today.isoformat()} and "
            f"{end.isoformat()} for the items that best move my goals forward. Check free time before "
            "proposing. Finish with a short explanation of what you picked and what you left out.")


@dataclass
class PlanRun:
    result: AgentResult
    batch: EgressBatch
    vault: Vault
    events: dict      # raw items by id (local)
    records: dict     # local labels by id
    trace: Path
    model: str


def add_args(ap: argparse.ArgumentParser):
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--level", type=int, default=1, choices=[0, 1, 2])
    ap.add_argument("--labeler", choices=["oracle", "baseline", "ollama"], default="oracle")
    ap.add_argument("--source", choices=["snapshot", "live"], default="snapshot",
                help="snapshot: the static notes in data/; live: pull open notes from the notes calendar")
    ap.add_argument("--local-model", default="llama3.2:3b")
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--calendar", choices=["live", "snapshot"], default="live",
                help="live: read busy times from Google Calendar; snapshot: the old offline behavior")

TASK = make_task(date.today())

def run_planner(a, task: str = TASK) -> PlanRun:
    import anthropic  # imported here so the rest of the project runs without it

    # events, golds, split = run_eval.load()
    # records = label_all(a.labeler, a.local_model, events, golds, split)

    if a.source == "live":
        from ingest.source import live_records
        events, records, stats = live_records(datetime.now(), a.labeler, a.local_model)
        print("live:", stats)
        if not records:
            raise SystemExit("No open notes in the window: nothing to plan.")
    else:
        events, golds, split = run_eval.load()
        records = label_all(a.labeler, a.local_model, events, golds, split)

    vault = Vault(ROOT / "vault" / "vault.json")
    names = detect.known_names_before(list(events.values()), "9999")
    batch = export_batch(records, events, vault, level=a.level, extra_names=names,
                         audit_dir=ROOT / "runs" / "egress")
    log = ROOT / "runs" / "agent" / f"{time.strftime('%Y%m%d-%H%M%S')}_L{a.level}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)

    calendar = None
    if a.calendar == "live":
        # from approve.gcal import GoogleCalendar      # import here: snapshot runs never need Google
        # calendar = GoogleCalendar()
        from approve.accounts import plans_calendar
        calendar = plans_calendar()
    result = run_agent(batch, anthropic.Anthropic(), a.model, make_task(date.today()), max_steps=a.max_steps, log_path=log, calendar=calendar, now=NOW)    
    
    return PlanRun(result, batch, vault, events, {r["id"]: r for r in records}, log, a.model)


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    run = run_planner(ap.parse_args())
    r = run.result
    print(f"stop: {r.stop_reason} after {r.steps} calls; tokens {r.usage}\n")
    print(run.vault.reidentify(r.final_text), "\n")   # names back, locally
    print("Proposals, mapped back locally:")
    for p in r.proposals:
        real = run.vault.reidentify(p)
        print(f"  {p['start']}  {p['minutes']:>3} min  {run.events[real['handle']]['title'][:60]!r}")
        print(f"      why: {real['reason']}")
    print(f"\ntrace: {run.trace}")


if __name__ == "__main__":
    main()
