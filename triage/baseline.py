"""Keyword rules for the model steps. The floor the local model has to beat.

Its keywords were written after reading all 46 sandbox notes, so its scores on v0 are
inflated. Judge it on new weeks of notes, not on v0.
"""
import re


def _goals(t: str, category: str) -> list[str]:
    if category == "other_person_goal":
        return []
    g = set()
    if re.search(r"\b(ai|agent|claude|job|evals?|jira|interview)\b", t):
        g.add("G1")
    if re.search(r"\b(apartment|bench|craft|kitchen|shelf)\b", t):
        g.add("G2")
    if re.search(r"\b(furniture|showroom|art|artisans|designers?|homegoods|sell|guild)\b", t):
        g.add("G3")
    return sorted(g)


def _fields(t, category, ask=None):
    return {
        "normalized_text": t, "goal_links": _goals(t, category), "people": [], "company": None,
        "next_action": None, "confidence": "medium", "needs_clarification": ask,
    }


class KeywordBackend:
    def __init__(self):
        self.calls = 0

    def event_fields(self, item):
        self.calls += 1
        return _fields(item["title"].lower(), "event")

    def category(self, item, mode):
        self.calls += 1
        t = item["title"].lower()
        if re.search(r"\bgoals?\b", t):
            cat = "goal" if t.startswith(("carson", "goal")) else "other_person_goal"
        elif re.match(r"^(text|sell|call|email|buy|book|measure)\b", t):
            cat = "action"
        elif re.search(r"\b(build|agent|board|app)\b", t):
            cat = "project_idea"
        elif re.search(r"\b(rent|showroom|curation|fulfillment|certified)\b", t):
            cat = "business_idea"
        elif re.search(r"\b(dangers|evals|frontier|lesson|learning)\b", t):
            cat = "learning_topic"
        else:
            cat = "reflection"
        ask = "Is this a plan to meet, or a note?" if mode == "unsure" else None
        out = _fields(t, cat, ask)
        return {"normalized_text": out.pop("normalized_text"), "category": cat, **out}

    def reflection(self, item):
        self.calls += 1
        short = len(item["title"].split()) <= 4
        return {"kind": "good_words" if short else "musing", "musing_theme": None}
