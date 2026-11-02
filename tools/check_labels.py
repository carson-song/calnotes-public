"""Check your fresh labels before they count as ground truth. Provided.

  python3 tools/check_labels.py            # checks data/fresh/labels.csv against data/fresh/events.jsonl

run_eval runs the same check every time it loads the fresh split, and refuses to score against labels that
fail it, so a labeling slip can't quietly become ground truth. Nothing is written or merged.
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from triage.schema import THEMES, TYPES  # noqa: E402

FRESH = ROOT / "data" / "fresh"
GOALS = {"G1", "G2", "G3"}
CONF = {"high", "medium", "low"}


def problems(r: dict, known_ids: set) -> list:
    p = []
    if r["type"] not in TYPES:
        p.append(f"type {r['type']!r} isn't one of {TYPES}")
    if r["is_note"] not in ("TRUE", "FALSE") or (r["is_note"] == "FALSE") != (r["type"] == "event"):
        p.append("is_note doesn't match type (FALSE only for events)")
    if any(g.strip() not in GOALS for g in r["goal_link"].split(";") if g.strip()):
        p.append(f"goal_link {r['goal_link']!r}: use G1/G2/G3 separated by ;")
    if r["confidence"] not in CONF:
        p.append(f"confidence {r['confidence']!r}")
    if r["type"] == "musing" and r["musing_theme"] not in THEMES:
        p.append("a musing needs a theme")
    if r["type"] != "musing" and r["musing_theme"]:
        p.append("only musings have a theme")
    if r["duplicate_of"] and r["duplicate_of"] not in known_ids:
        p.append(f"duplicate_of {r['duplicate_of']} isn't a known id")
    if not r["normalized_text"].strip():
        p.append("normalized_text is empty")
    return p


def check(labels_path=FRESH / "labels.csv", events_path=FRESH / "events.jsonl") -> list:
    if not Path(events_path).exists():
        raise SystemExit(f"Missing {events_path}: it comes with the labeling kit (the notes you labeled).")
    rows = list(csv.DictReader(open(labels_path, encoding="utf-8-sig")))
    fresh_ids = {json.loads(l)["id"] for l in open(events_path, encoding="utf-8") if l.strip()}
    known = fresh_ids | {f"n{i:02d}" for i in range(1, 47)}
    bad, seen = [], set()
    for r in rows:
        if r["id"] not in fresh_ids:
            bad.append(f"{r['id']}: not one of the fresh notes")
        if r["id"] in seen:
            bad.append(f"{r['id']}: labeled twice")
        seen.add(r["id"])
        bad += [f"{r['id']} ({r['title_raw'][:40]}): {x}" for x in problems(r, known)]
    if bad:
        raise SystemExit("Labels not usable yet. Fix these in the labeler, export again, rerun:\n  " + "\n  ".join(bad))
    return rows


if __name__ == "__main__":
    rows = check()
    print(f"{len(rows)} fresh labels OK")
    print("types:", dict(Counter(r["type"] for r in rows).most_common()))
    print("goals:", dict(Counter(r["goal_link"] or "none" for r in rows).most_common()))
    print("confidence:", dict(Counter(r["confidence"] for r in rows).most_common()))
