"""Fill in colour, location and description for the new notes from a live pull. Run on the Mac mini. Provided.

  python3 tools/attach_colors.py              # uses every snapshot in data/live/

The calendar export the new notes came from has no event colours, but stage 1 of triage uses colour to tell
events from notes. The live pull records it. Notes are matched on (title, start time); anything that doesn't
match keeps an empty colour and is listed, so you know how much of the set it covers.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def main():
    live = {}
    for snap in sorted((DATA / "live").glob("*.jsonl")):
        for line in open(snap, encoding="utf-8"):
            if line.strip():
                e = json.loads(line)
                live[(e["title"].strip(), e["start"])] = e          # later snapshots win
    path = DATA / "fresh" / "events.jsonl"
    events = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    matched, missing = 0, []
    for e in events:
        m = live.get((e["title"].strip(), e["start"]))
        if m:
            e["color_id"], e["location"] = m.get("color_id") or "", m.get("location") or e["location"]
            e["description"] = m.get("description") or e["description"]
            matched += 1
        else:
            missing.append(f"{e['id']} {e['start']} {e['title'][:50]}")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    print(f"matched {matched}, unmatched {len(missing)} (live pulls cover the last 14 days of each run)")
    for m in missing[:20]:
        print("  ", m)
    if not live:
        sys.exit("No snapshots in data/live/: run a digest (or ingest.pull) on this machine first.")


if __name__ == "__main__":
    main()
