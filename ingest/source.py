"""Live notes for the planner: pull -> ledger -> select -> triage. Provided (wiring).

  from ingest.source import live_records
  events, records, stats = live_records(now, labeler="ollama", model="llama3.2:3b")

Live notes have no hand labels, so the oracle labeler can't be used; the local model labels them, using the
hand-labeled dev notes from data/ only as its worked examples.
"""
import argparse
import json
from datetime import timedelta
from pathlib import Path

import run_eval
from ingest.ledger import build_ledger, select_open_items
from ingest.pull import pull
from triage import detect, pipeline

ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR = ROOT / "data" / "live"
DIGEST_DIR = ROOT / "runs" / "digest"


def load_states(digest_dir: Path = DIGEST_DIR) -> list:
    """Every digest state file, skipping anything that isn't one."""
    states = []
    for p in sorted(Path(digest_dir).glob("*.json")):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(s, dict) and "digest_id" in s and "blocks" in s:
            states.append(s)
    return states


def label_items(items: list, labeler: str, model: str, rules: str | None = None) -> list:
    if labeler == "oracle":
        raise SystemExit("Live notes have no hand labels: use --labeler ollama (or baseline) with --source live.")
    static_events, golds, split = run_eval.load()
    a = argparse.Namespace(labeler=labeler, model=model, rules=rules or str(ROOT / "guide" / "rules_v0.3.md"))
    backend, _ = run_eval.make_backend(a, static_events, golds, split)
    pool = list(static_events.values()) + list(items)          # meeting logs in either teach known names
    return [pipeline.label_item(it, backend, detect.known_names_before(pool, it["start"])) for it in items]


def live_records(now, labeler="ollama", model="llama3.2:3b", window_days=14, calendar=None):
    from approve.accounts import notes_calendar
    calendar = calendar or notes_calendar()
    pulled, snapshot = pull(calendar, now - timedelta(days=window_days), now + timedelta(minutes=1), LIVE_DIR)
    ledger = build_ledger(load_states(), now)
    open_items = select_open_items(pulled, ledger, now, window_days)
    records = label_items(open_items, labeler, model)
    stats = {"pulled": len(pulled), "open": len(open_items), "snapshot": snapshot.name,
             "notes account": calendar.account}
    return {e["id"]: e for e in open_items}, records, stats
