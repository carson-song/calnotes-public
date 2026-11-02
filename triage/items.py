"""Helpers for raw calendar items (one dict per event, as in data/events_*.jsonl)."""
import re
from datetime import datetime

MEETING_TYPE = re.compile(r"type:\s*([A-Za-z]+)", re.IGNORECASE)


def minutes(item: dict) -> int:
    s = datetime.fromisoformat(item["start"])
    e = datetime.fromisoformat(item["end"])
    return int((e - s).total_seconds() // 60)


def meeting_type(item: dict) -> str | None:
    """The `type:` Carson's calendar skill writes into the meeting-log tag (social, business, art)."""
    desc = item.get("description") or ""
    if "meeting-log" not in desc:
        return None
    m = MEETING_TYPE.search(desc)
    return m.group(1).lower() if m else None


def item_view(item: dict) -> dict:
    """The fields a labeler is allowed to see for one item (no id, no labels)."""
    return {
        "title": item["title"],
        "start": item["start"],
        "duration_min": minutes(item),
        "description": item.get("description", ""),
        "location": item.get("location", ""),
        "has_color": bool(item.get("color_id")),
        "meeting_type": meeting_type(item),
    }
