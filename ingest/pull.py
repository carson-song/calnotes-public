"""Pull notes from the notes calendar and turn them into the same shape as data/events_v0.jsonl. Provided.

  normalize(google_event, tz) -> {"id", "title", "start", "end", "description", "location", "color_id",
                                  "all_day", "calnotes_key"}

Times become naive local "YYYY-MM-DDTHH:MM" like the rest of the project. An all-day event gets 00:00 and
all_day=True. calnotes_key is set on events this project wrote itself (approved blocks); selection skips
them so the system never ingests its own output.

Every pull is saved to data/live/<time>.jsonl (git-ignored: it's raw note text). Those files are also the
raw material for labels_v2, the honest holdout set.
"""
import json
import time
from datetime import datetime
from pathlib import Path

from approve.gcal import KEY_PROP


def _local(when: dict, tz) -> tuple[str, bool]:
    if "dateTime" in when:
        dt = datetime.fromisoformat(when["dateTime"]).astimezone(tz).replace(tzinfo=None)
        return dt.isoformat(timespec="minutes"), False
    return f"{when['date']}T00:00", True


def normalize(e: dict, tz) -> dict:
    start, all_day = _local(e["start"], tz)
    end, _ = _local(e["end"], tz)
    return {
        "id": e["id"],
        "title": (e.get("summary") or "").strip(),
        "start": start,
        "end": end,
        "description": e.get("description") or "",
        "location": e.get("location") or "",
        "color_id": e.get("colorId") or "",
        "all_day": all_day,
        "calnotes_key": (e.get("extendedProperties", {}).get("private", {}) or {}).get(KEY_PROP),
    }


def pull(calendar, start: datetime, end: datetime, out_dir: Path) -> tuple[list[dict], Path]:
    events = [normalize(e, calendar.tz) for e in calendar.list_events(start, end)]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    return events, path
