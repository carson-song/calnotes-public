"""Stage 1 (rules) decides note vs. event; stage 2 (a backend) fills in the rest.

Backends implement three steps: event_fields(item), category(item, mode), reflection(item).
Hard rules from the labeling guide are enforced here in code, not hoped for in a prompt.
"""
from triage import detect
from triage import schema as S
from triage.items import meeting_type


def enforce(rec: dict) -> dict:
    t = rec["type"]
    rec["is_note"] = t != "event"
    rec["goal_links"] = sorted({g for g in rec.get("goal_links") or [] if g in S.GOALS})
    if t in ("other_person_goal", "good_words"):  # never link to Carson's goals
        rec["goal_links"] = []
    if t == "event" and rec.get("meeting_type") == "social" and not rec.get("next_action"):
        rec["goal_links"] = []  # a social hang links only when it names work toward a goal
    if t != "musing":
        rec["musing_theme"] = None
    elif rec.get("musing_theme") not in S.THEMES:
        rec["musing_theme"] = None
    rec.setdefault("needs_clarification", None)
    return rec


def label_item(item: dict, backend, known_names) -> dict:
    d = detect.decide(item, known_names)
    calls_before = backend.calls
    rec = {
        "id": item["id"], "detect_verdict": d.verdict, "detect_rule": d.rule, "detect_detail": d.detail,
        "meeting_type": meeting_type(item),
    }

    if d.verdict == "event":
        rec.update(backend.event_fields(item))
        rec["type"] = "event"
    else:
        out = backend.category(item, mode=d.verdict)  # "note" or "unsure"
        category = out.pop("category")
        rec.update(out)
        if category == "reflection":
            r = backend.reflection(item)
            rec["type"], rec["musing_theme"] = r["kind"], r.get("musing_theme")
        else:
            rec["type"] = category  # may be "event" for an unsure item

    rec["model_calls"] = backend.calls - calls_before
    return enforce(rec)
