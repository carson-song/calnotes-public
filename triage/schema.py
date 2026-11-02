"""Label vocabulary, the JSON schemas each model step must fill, and gold-label converters."""

TYPES = [
    "event", "action", "project_idea", "business_idea", "learning_topic",
    "goal", "other_person_goal", "musing", "good_words",
]
REFLECTION_KINDS = ["musing", "good_words"]
NOTE_CATEGORIES = [
    "action", "project_idea", "business_idea", "learning_topic",
    "goal", "other_person_goal", "reflection",  # reflection is split in a second step
]
GOALS = ["G1", "G2", "G3"]
THEMES = ["identity", "self-direction", "action and momentum", "doing over learning", "AI and humanity"]
CONFIDENCE = ["high", "medium", "low"]

_STR_OR_NULL = {"type": ["string", "null"]}


def _fields() -> dict:
    # normalized_text comes first on purpose: the model decodes the typos before it classifies.
    return {
        "normalized_text": {"type": "string"},
        "goal_links": {"type": "array", "items": {"type": "string", "enum": GOALS}},
        "people": {"type": "array", "items": {"type": "string"}},
        "company": _STR_OR_NULL,
        "next_action": _STR_OR_NULL,
        "confidence": {"type": "string", "enum": CONFIDENCE},
        "needs_clarification": _STR_OR_NULL,
    }


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props)}


def category_schema(allow_event: bool) -> dict:
    """Step for notes (and unsure items, which may still turn out to be events)."""
    f = _fields()
    cats = NOTE_CATEGORIES + (["event"] if allow_event else [])
    props = {"normalized_text": f.pop("normalized_text"), "category": {"type": "string", "enum": cats}, **f}
    return _obj(props)


REFLECTION_SCHEMA = _obj({
    "kind": {"type": "string", "enum": REFLECTION_KINDS},
    "musing_theme": {"type": ["string", "null"], "enum": THEMES + [None]},
})

EVENT_SCHEMA = _obj(_fields())


# --- gold labels ------------------------------------------------------------
def gold_from_row(row: dict) -> dict:
    """A labels CSV row in the same shape the pipeline emits."""
    split = lambda s: [x.strip() for x in s.split(";") if x.strip()]
    return {
        "is_note": row["is_note"].strip().upper() == "TRUE",
        "type": row["type"].strip(),
        "normalized_text": row["normalized_text"],
        "goal_links": sorted(split(row["goal_link"])),
        "people": split(row["people"]),
        "company": row.get("company", "").strip().lower() or None,
        "next_action": row["next_action"].strip() or None,
        "musing_theme": row["musing_theme"].strip() or None,
        "confidence": row["confidence"].strip(),
        # The CSV's needs_clarification column holds the labeler's own open questions,
        # kept for reference; it is not a target the model is scored on.
        "labeler_question": row["needs_clarification"].strip() or None,
    }


def _shared(g: dict, ask: str | None) -> dict:
    return {
        "normalized_text": g["normalized_text"], "goal_links": g["goal_links"], "people": g["people"],
        "company": g["company"], "next_action": g["next_action"], "confidence": g["confidence"],
        "needs_clarification": ask,
    }


def to_category_output(g: dict, ask: str | None = None) -> dict:
    cat = "reflection" if g["type"] in REFLECTION_KINDS else g["type"]
    out = _shared(g, ask)
    return {"normalized_text": out.pop("normalized_text"), "category": cat, **out}


def to_reflection_output(g: dict) -> dict:
    return {"kind": g["type"], "musing_theme": g["musing_theme"] if g["type"] == "musing" else None}


def to_event_output(g: dict, ask: str | None = None) -> dict:
    return _shared(g, ask)
