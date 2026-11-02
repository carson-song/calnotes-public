"""Apply your reply to a digest: parse it, update the digest's state, write approved blocks to the calendar.

  python3 approve_run.py runs/digest/cn-20261015-0700.json           # paste your reply, then Ctrl-D
  python3 approve_run.py runs/digest/cn-....json --reply-file r.txt
  python3 approve_run.py runs/digest/cn-....json --write             # for real (default: dry run)
  python3 approve_run.py runs/digest/cn-....json --write --retry     # no reply: retry blocks that failed transiently
  python3 approve_run.py runs/digest/cn-....json --write --from-gmail  # read your replies from the digest's thread

Dry run: a FakeCalendar, nothing saved, so you can preview. With --write: the real calendar, the state
file is updated after every block, and each decision is appended to runs/eval/decisions.jsonl, the
planner's eval data.

No model is involved anywhere here. The approval path is deterministic on purpose: text you write is
parsed by fixed rules, so nothing in an email can talk the system into writing to your calendar.
"""
import argparse
import copy
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from approve.apply import apply_decisions
from approve.fake import FakeCalendar
from approve.parse import parse_reply

ROOT = Path(__file__).parent
EVAL_LOG = ROOT / "runs" / "eval" / "decisions.jsonl"


def atomic_save(path: Path):
    """Write to a temp file, then rename over the original: a crash mid-write can't leave half a file."""
    def save(state):
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    return save


def log_decisions(before, after, path=EVAL_LOG):
    """One line per block whose decision was set by this run."""
    old = {b["proposal_id"]: b["decision"] for b in before["blocks"]}
    rows = [{
        "decided_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "digest_id": after["digest_id"],
        "proposal_id": b["proposal_id"], "item_id": b["item_id"],
        "level": after.get("run", {}).get("privacy level"), "model": after.get("run", {}).get("model"),
        "proposed_minutes": b["proposed_minutes"], **b["decision"], "status": b["status"],
    } for b in after["blocks"] if b["decision"] and old.get(b["proposal_id"]) is None]
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    return len(rows)


def apply_replies(state, replies, calendar, now, save):
    """Apply each reply not seen before, oldest first; remember it in state["replies_seen"].

    A reply is marked seen even if it held no valid commands, so its errors are shown once, not every run.
    With no new replies this is a plain retry: pass 2 still reconciles any approved blocks.
    """
    seen = state.setdefault("replies_seen", [])
    ids = {b["proposal_id"] for b in state["blocks"]}
    results = []
    for r in replies:
        if r.message_id in seen:
            continue
        parsed = parse_reply(r.text, ids)
        report = apply_decisions(state, parsed.decisions, calendar, now, save)
        seen.append(r.message_id)
        save(state)
        results.append((r, parsed, report))
    if not results:
        results.append((None, None, apply_decisions(state, [], calendar, now, save)))
    return results


def print_report(report):
    for name, pids in vars(report).items():
        if pids:
            print(f"{name:>10}: {', '.join(map(str, pids))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state", type=Path)
    ap.add_argument("--reply-file", type=Path)
    ap.add_argument("--write", action="store_true", help="use the real calendar and save state")
    ap.add_argument("--retry", action="store_true", help="no reply; just retry approved blocks")
    ap.add_argument("--from-gmail", action="store_true", help="read replies from the digest's Gmail thread")
    a = ap.parse_args()

    state = json.loads(a.state.read_text(encoding="utf-8"))
    before = copy.deepcopy(state)
    ids = {b["proposal_id"] for b in state["blocks"]}

    if a.write:
        from approve.accounts import plans_calendar
        cal, save = plans_calendar(), atomic_save(a.state)
        print(f"writing to the plans calendar: {cal.account}")
    else:
        cal, save = FakeCalendar(), (lambda s: None)

    if a.from_gmail:
        from approve.inbox import GmailInbox, digest_message_id, replies_in_thread
        from digest.send import recipient
        scan = replies_in_thread(GmailInbox().thread_messages(digest_message_id(state)), recipient())
        for gid, why in scan.ignored:
            print(f"  ignored message {gid}: {why}")
        for r, parsed, report in apply_replies(state, scan.replies, cal, datetime.now(), save):
            print(f"reply of {r.date}:" if r else "no new replies; retrying approved blocks:")
            for e in (parsed.errors if parsed else []):
                print(f"  ! {e}")
            print_report(report)
        finish(a, before, state)
        return

    decisions = []
    if not a.retry:
        text = a.reply_file.read_text(encoding="utf-8") if a.reply_file else sys.stdin.read()
        parsed = parse_reply(text, ids)
        for e in parsed.errors:
            print(f"  ! {e}")
        decisions = parsed.decisions
        if not decisions:
            raise SystemExit("No decisions found in the reply. Nothing changed.")

    print_report(apply_decisions(state, decisions, cal, datetime.now(), save))
    finish(a, before, state)


def finish(a, before, state):
    if a.write:
        print(f"logged {log_decisions(before, state)} decision(s) to {EVAL_LOG}")
    else:
        print("dry run: nothing written, state not saved. Add --write to apply.")


if __name__ == "__main__":
    main()
