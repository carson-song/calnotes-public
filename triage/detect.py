"""Stage 1: decide note vs. event with deterministic rules. No model, no network.

Rules run in order of reliability; the first one that fires decides. Every decision
records which rule fired and why, so a wrong call can be traced to one rule.
Verdicts: "event", "note", or "unsure" (sent to the model, which may ask Carson).
"""
import re
from dataclasses import dataclass

from triage.items import minutes

# --- tunable constants -------------------------------------------------------
DEFAULT_NOTE_MINUTES = 60  # tap-and-type notes get the calendar's default length
SENTENCE_MIN_WORDS = 9     # 9+ words reads as something written, not a named event
MEETING_WORDS = {
    "coffee", "call", "lunch", "dinner", "breakfast", "brunch", "drink", "drinks",
    "beer", "demo", "show", "interview", "meet", "meeting", "hang",
}
WITH_FIELD = re.compile(r"with:\s*([^|<]+)", re.IGNORECASE)


@dataclass(frozen=True)
class Decision:
    verdict: str  # "event" | "note" | "unsure"
    rule: str     # e.g. "R2_location"
    detail: str   # human-readable reason


def _words(title: str) -> list[str]:
    return re.findall(r"[a-z]+", title.lower())


# --- rules, most reliable first ----------------------------------------------
def r1_meeting_log(item, names):
    if "meeting-log" in (item.get("description") or ""):
        return Decision("event", "R1_meeting_log", "meeting-log tag in description")


def r2_location(item, names):
    if item.get("location"):
        return Decision("event", "R2_location", f"has location: {item['location']}")


def r3_color(item, names):
    if item.get("color_id"):
        return Decision("event", "R3_color", f"has color {item['color_id']}")


def r4_length(item, names):
    m = minutes(item)
    if m != DEFAULT_NOTE_MINUTES:
        return Decision("event", "R4_length", f"non-default length ({m} min)")


def r5_sentence(item, names):
    t = item["title"].lower()
    if re.search(r"[a-z0-9]\.\s+\w", t):
        return Decision("note", "R5_sentence", "period mid-title")
    n = len(t.split())
    if n >= SENTENCE_MIN_WORDS:
        return Decision("note", "R5_sentence", f"{n}-word title")


def r6_meeting_word(item, names):
    hits = sorted(set(_words(item["title"])) & MEETING_WORDS)
    if hits:
        return Decision("event", "R6_meeting_word", f"meeting word '{hits[0]}'")


def r7_known_name(item, names):
    for w in _words(item["title"]):
        base = w[:-1] if w.endswith("s") and w[:-1] in names else w  # "teos" -> "teo"
        if base in names:
            return Decision("unsure", "R7_known_name", f"known name '{base}' but no meeting word")


RULES = [r1_meeting_log, r2_location, r3_color, r4_length, r5_sentence, r6_meeting_word, r7_known_name]


def decide(item: dict, known_names=frozenset()) -> Decision:
    for rule in RULES:
        d = rule(item, known_names)
        if d:
            return d
    return Decision("note", "R8_default", "no event signal")


def known_names_before(items: list[dict], when: str) -> set[str]:
    """First names from meeting-log "with:" fields of items that START before `when`.

    Time-aware on purpose: in production the list only holds people already met,
    so the eval must not learn a name from a later meeting.
    First names only, so "Felix Ward" doesn't make the word "ward" look like a name.
    """
    names = set()
    for it in items:
        if it["start"] >= when:
            continue
        m = WITH_FIELD.search(it.get("description") or "")
        if not m:
            continue
        for person in m.group(1).split(","):
            parts = _words(person)
            if parts and len(parts[0]) >= 2:
                names.add(parts[0])
    return names
