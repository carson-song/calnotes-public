"""Pick worked examples for each prompt from the DEV split.

Leave-one-out: the item being labeled is never one of its own examples, so every dev
item can still be scored. Test items are never used. Choices are deterministic.
"""
from triage import schema as S

RANK = {"high": 0, "medium": 1, "low": 2}


def _pool(dev_ids, golds, exclude, pred):
    ids = [i for i in dev_ids if i not in exclude and pred(golds[i])]
    return sorted(ids, key=lambda i: (RANK[golds[i]["confidence"]], i))


def ask_example_id(dev_ids, golds, exclude) -> str | None:
    """A low-confidence dev note that came with a real question: shows the model that asking is allowed."""
    pool = [
        i for i in sorted(dev_ids)
        if i not in exclude and golds[i]["is_note"] and golds[i]["confidence"] == "low" and golds[i]["labeler_question"]
    ]
    return pool[0] if pool else None


def category_shots(item_id, dev_ids, events, golds, allow_event=False):
    ask_id = ask_example_id(dev_ids, golds, {item_id})
    skip = {item_id, ask_id}
    picks = []
    for cat in S.NOTE_CATEGORIES:
        kinds = S.REFLECTION_KINDS if cat == "reflection" else [cat]
        for k in kinds:  # reflections get one musing and one good-words example
            p = _pool(dev_ids, golds, skip, lambda g, k=k: g["type"] == k)
            if p:
                picks.append(p[0])
    if allow_event:
        p = _pool(dev_ids, golds, skip, lambda g: g["type"] == "event")
        p.sort(key=lambda i: bool(events[i]["description"]))  # prefer bare-title events
        if p:
            picks.append(p[0])
    shots = [(events[i], S.to_category_output(golds[i])) for i in sorted(picks)]
    if ask_id:
        shots.append((events[ask_id], S.to_category_output(golds[ask_id], ask=golds[ask_id]["labeler_question"])))
    return shots


def reflection_shots(item_id, dev_ids, events, golds, per_kind=2):
    picks = []
    for k in S.REFLECTION_KINDS:
        picks += _pool(dev_ids, golds, {item_id}, lambda g, k=k: g["type"] == k)[:per_kind]
    return [(events[i], S.to_reflection_output(golds[i])) for i in sorted(picks)]


def event_shots(item_id, dev_ids, events, golds):
    """Balanced on purpose: one social hang with no goal, and linked events with different goals.
    (v0.2 used two linked events and one unlinked, and the model learned to link everything.)"""
    is_event = lambda g: g["type"] == "event"
    no_goal = _pool(dev_ids, golds, {item_id}, lambda g: is_event(g) and not g["goal_links"])[:1]
    picks, seen = list(no_goal), set()
    for i in _pool(dev_ids, golds, {item_id}, lambda g: is_event(g) and g["goal_links"]):
        key = tuple(golds[i]["goal_links"])
        if key not in seen:
            seen.add(key)
            picks.append(i)
        if len(picks) == 3:
            break
    return [(events[i], S.to_event_output(golds[i])) for i in sorted(picks)]
