"""Run the pipeline over a split and score it against the frozen ground truth.

  python3 run_eval.py --labeler oracle                       # plumbing check: must be 100%
  python3 run_eval.py --labeler baseline
  python3 run_eval.py --labeler ollama --model llama3.2:3b
  python3 run_eval.py --labeler ollama --model llama3.2:3b --split test --final   # milestones only
  python3 run_eval.py --labeler ollama --model qwen2.5:14b --split fresh --final         # model comparison
  python3 run_eval.py --labeler frontier --model claude-sonnet-5-5 --split fresh --final --send-raw-notes

Data:
  data/events_v0.jsonl, data/labels_v1.csv, data/split_v0.json   the original 46 notes (dev and test splits)
  data/fresh/events.jsonl, data/fresh/labels.csv                 the notes labeled later: the "fresh" split
The fresh split is loaded together with the original notes (so names and examples still come from them), and
the local model's worked examples come only from dev: no prompt has ever seen a fresh note.
"""
import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from triage import detect, pipeline
from triage.schema import REFLECTION_KINDS, TYPES, gold_from_row

ROOT = Path(__file__).parent
DATA = ROOT / "data"


LABELS = "labels_v1.csv"  # labeled under guide v0.3


FRESH = DATA / "fresh"


def load(labels=None, fresh=False, root=None):
    """The original notes; with fresh=True, also the fresh ones from data/fresh/labels.csv.

    root: where the three files live. Default data/ (your real notes). Tests pass tests/fixtures/, an invented
    dataset with the same structure, so no test ever depends on private data.
    """
    root = Path(root) if root else DATA
    lines = (root / "events_v0.jsonl").read_text(encoding="utf-8").splitlines()
    events = {e["id"]: e for e in map(json.loads, filter(None, lines))}
    with open(root / (labels or LABELS), encoding="utf-8") as f:
        golds = {r["id"]: gold_from_row(r) for r in csv.DictReader(f)}
    split = json.loads((root / "split_v0.json").read_text())
    if fresh and (FRESH / "labels.csv").exists():
        from tools.check_labels import check
        rows = check(FRESH / "labels.csv", FRESH / "events.jsonl")      # refuses malformed labels
        fresh_events = {e["id"]: e for e in map(json.loads, filter(None, (FRESH / "events.jsonl").read_text(
            encoding="utf-8").splitlines()))}
        for r in rows:
            events[r["id"]], golds[r["id"]] = fresh_events[r["id"]], gold_from_row(r)
        split["fresh"] = sorted(r["id"] for r in rows)
    return events, golds, split


def make_backend(a, events, golds, split):
    if a.labeler == "oracle":
        from triage.oracle import OracleBackend
        return OracleBackend(golds), "oracle"
    if a.labeler == "baseline":
        from triage.baseline import KeywordBackend
        return KeywordBackend(), "baseline"
    if a.labeler == "frontier":
        from triage.frontier import FrontierBackend
        return FrontierBackend(a.model, a.rules, events, golds, split["dev"]), f"frontier-{a.model}"
    from triage.local_llm import OllamaBackend
    return OllamaBackend(a.model, a.rules, events, golds, split["dev"]), f"ollama-{a.model.replace(':', '_')}"


# What the planner actually uses: it schedules actionable notes, never reflections, and treats events as busy time.
COARSE = {"event": "event", "musing": "reflection", "good_words": "reflection", "goal": "goal",
          "other_person_goal": "goal"}


def coarse(t):
    return COARSE.get(t, "actionable")


def score(ids, recs, golds):
    n = len(ids)
    asked = lambda i: bool(recs[i].get("needs_clarification"))
    type_ok = lambda i: recs[i]["type"] == golds[i]["type"]
    goal_ok = lambda i: recs[i]["goal_links"] == golds[i]["goal_links"]
    frac = lambda xs, f: (sum(f(i) for i in xs) / len(xs)) if xs else None

    # stage 1: the rules
    decided = [i for i in ids if recs[i]["detect_verdict"] != "unsure"]
    unsure = [i for i in ids if recs[i]["detect_verdict"] == "unsure"]
    s1_ok = lambda i: (recs[i]["detect_verdict"] == "note") == golds[i]["is_note"]
    per_rule = defaultdict(lambda: [0, 0])
    for i in decided:
        per_rule[recs[i]["detect_rule"]][0] += 1
        per_rule[recs[i]["detect_rule"]][1] += s1_ok(i)

    # stage 2: the model
    events = [i for i in ids if golds[i]["type"] == "event"]
    notes = [i for i in ids if golds[i]["type"] != "event"]
    reflections = [i for i in ids if golds[i]["type"] in REFLECTION_KINDS]
    musings = [i for i in ids if golds[i]["type"] == "musing"]
    high = [i for i in ids if golds[i]["confidence"] == "high"]
    credited = lambda i: type_ok(i) or (asked(i) and (golds[i]["confidence"] == "low" or i in unsure))

    m = {
        "n": n,
        "stage1_coverage": len(decided) / n,
        "stage1_acc_on_decided": frac(decided, s1_ok),
        "stage1_unsure": len(unsure),
        "unsure_asked": sum(asked(i) for i in unsure),
        "is_note_acc_final": frac(ids, lambda i: recs[i]["is_note"] == golds[i]["is_note"]),
        "type_acc_strict": frac(ids, type_ok),
        "type_acc_coarse": frac(ids, lambda i: coarse(recs[i]["type"]) == coarse(golds[i]["type"])),
        "type_acc_with_clarify_credit": frac(ids, credited),
        "type_acc_notes_only": frac(notes, type_ok),
        "reflection_split_acc": frac(reflections, type_ok),
        "musing_theme_acc": frac(musings, lambda i: recs[i]["musing_theme"] == golds[i]["musing_theme"]),
        "goal_links_exact": frac(ids, goal_ok),
        "goal_links_events": frac(events, goal_ok),
        "goal_links_notes": frac(notes, goal_ok),
        "questions_asked": sum(asked(i) for i in ids),
        "over_asking_rate": frac(high, asked),
        "model_calls": sum(recs[i]["model_calls"] for i in ids),
    }
    confusion = Counter((golds[i]["type"], recs[i]["type"]) for i in ids)
    errors = [
        {"id": i, "rule": recs[i]["detect_rule"], "gold": golds[i]["type"], "pred": recs[i]["type"],
         "gold_goals": golds[i]["goal_links"], "pred_goals": recs[i]["goal_links"],
         "asked": recs[i].get("needs_clarification")}
        for i in ids if not type_ok(i) or not goal_ok(i)
    ]
    return m, dict(per_rule), confusion, errors


def report(tag, split_name, m, per_rule, confusion, errors, out):
    def fmt(k, v):
        if v is None:
            return "-"
        if k.startswith("seconds"):
            return f"{v:.2f} s"
        if k.endswith("tokens") or k == "tokens_per_item":
            return f"{v:,.0f}"
        return f"{v:.0%}" if isinstance(v, float) else str(v)
    print(f"{tag} on {split_name} ({m['n']} items, labels {m.get('labels', '?')})\n")
    print("stage 1 — rules (no model)")
    for k in ["stage1_coverage", "stage1_acc_on_decided", "stage1_unsure", "unsure_asked"]:
        print(f"  {k:32} {fmt(k, m[k])}")
    print("  rule                fired  correct")
    for rule in sorted(per_rule):
        fired, ok = per_rule[rule]
        print(f"  {rule:20} {fired:5}  {ok:7}")
    print("\nstage 2 — model")
    for k, v in m.items():
        if k not in ("n", "labels") and not k.startswith(("stage1", "unsure")):
            print(f"  {k:32} {fmt(k, v)}")
    used = [t for t in TYPES if any(t in key for key in confusion)]
    print("\nconfusion (rows = gold, cols = predicted)")
    print(" " * 18 + " ".join(f"{t[:8]:>8}" for t in used))
    for g in used:
        print(f"{g:>17} " + " ".join(f"{confusion.get((g, p), 0) or '.':>8}" for p in used))
    print(f"\n{len(errors)} items with a type or goal error -> {out / 'errors.json'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labeler", choices=["oracle", "baseline", "ollama", "frontier"], required=True)
    ap.add_argument("--model", default="llama3.2:3b")
    ap.add_argument("--rules", default=str(ROOT / "guide" / "rules_v0.3.md"))
    ap.add_argument("--labels", default=None, help="override the original notes' labels file")
    ap.add_argument("--split", choices=["dev", "test", "fresh", "all"], default="dev")
    ap.add_argument("--final", action="store_true", help="required to score the held-out test split")
    ap.add_argument("--send-raw-notes", action="store_true",
                    help="required for --labeler frontier: raw note text leaves this machine")
    a = ap.parse_args()
    if a.split in ("test", "fresh", "all") and not a.final and a.labeler != "oracle":
        raise SystemExit(f"The {a.split} split is held out. Re-run with --final for a milestone check.")

    if a.labeler == "frontier" and not a.send_raw_notes:
        raise SystemExit("--labeler frontier sends your raw notes to the Anthropic API. Add --send-raw-notes to confirm.")

    events, golds, split = load(a.labels, fresh=a.split in ("fresh", "all"))
    if a.split not in split and a.split != "all":
        raise SystemExit(f"No {a.split} split: for fresh, put your exported labels at data/fresh/labels.csv.")
    ids = sorted(events) if a.split == "all" else split[a.split]
    backend, tag = make_backend(a, events, golds, split)
    all_items = list(events.values())

    if a.labeler == "frontier":
        print(f"Sending {len(ids)} raw notes to {a.model} (deliberate exception: --send-raw-notes).")
    recs, per_item, t0 = {}, {}, time.time()
    for i in ids:
        names = detect.known_names_before(all_items, events[i]["start"])
        before, s0 = dict(getattr(backend, "usage", {})), time.time()
        recs[i] = pipeline.label_item(events[i], backend, names)
        after = getattr(backend, "usage", {})
        per_item[i] = {"seconds": round(time.time() - s0, 3),
                       **{k: after.get(k, 0) - before.get(k, 0) for k in after}}
    elapsed = time.time() - t0

    m, per_rule, confusion, errors = score(ids, recs, golds)
    m["seconds_per_item"] = round(elapsed / len(ids), 3)
    m["seconds_total"] = round(elapsed, 1)
    secs = sorted(v["seconds"] for v in per_item.values())
    m["seconds_p95"] = secs[min(len(secs) - 1, int(0.95 * len(secs)))] if secs else 0
    usage = getattr(backend, "usage", {})
    m.update({k: usage.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")})
    m["tokens_per_item"] = round((m["input_tokens"] + m["output_tokens"] + m["cache_read_tokens"]
                                  + m["cache_write_tokens"]) / len(ids), 1)
    m["labels"] = "data/fresh/labels.csv" if a.split == "fresh" else (a.labels or LABELS)
    m["model"] = a.model if a.labeler in ("ollama", "frontier") else a.labeler
    m["split"] = a.split

    out = ROOT / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}_{tag}_{a.split}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "correct.json").write_text(json.dumps(   # per item, for paired comparisons between runs
        {i: {"type": recs[i]["type"] == golds[i]["type"], "goals": recs[i]["goal_links"] == golds[i]["goal_links"],
             **per_item[i]} for i in ids}, indent=1))
    (out / "predictions.json").write_text(json.dumps(recs, indent=1, ensure_ascii=False))
    (out / "metrics.json").write_text(json.dumps({**m, "per_rule": per_rule}, indent=1))
    (out / "errors.json").write_text(json.dumps(errors, indent=1, ensure_ascii=False))
    report(tag, a.split, m, per_rule, confusion, errors, out)


if __name__ == "__main__":
    main()
