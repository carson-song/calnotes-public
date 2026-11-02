"""Acceptance tests for the approval step (approve/SPEC.md). Each name says which requirement it checks."""
import copy
import unittest
from datetime import datetime

from approve.apply import MAX_ATTEMPTS, apply_decisions
from approve.calendar import CalendarError, TransientCalendarError
from approve.parse import Decision, parse_reply
from approve.fake import FakeCalendar

IDS = {"p1", "p2", "p3"}
NOW = datetime(2026, 10, 15, 8, 0)
T = datetime.fromisoformat


def state():
    def block(pid, item, start, minutes, title):
        return {"proposal_id": pid, "item_id": item, "title": title, "source": "", "start": start,
                "minutes": minutes, "proposed_minutes": minutes, "goals": ["G1"], "reason": f"why {pid}",
                "status": "proposed", "decision": None, "attempts": 0, "event_id": None}
    return {"digest_id": "cn-test", "blocks": [
        block("p1", "n40", "2026-10-15T09:00", 20, "Text Nico"),
        block("p2", "n30", "2026-10-15T10:00", 90, "Find the furniture designers"),
        block("p3", "n32", "2026-10-16T10:00", 120, "Catalog AI-able projects"),
    ]}


class Saver:
    def __init__(self):
        self.snapshots = []

    def __call__(self, st):
        self.snapshots.append(copy.deepcopy(st))


def run(st, decisions, cal=None, now=NOW):
    cal = cal or FakeCalendar()
    save = Saver()
    return apply_decisions(st, decisions, cal, now, save), cal, save


def blk(st, pid):
    return next(b for b in st["blocks"] if b["proposal_id"] == pid)


class TestParse(unittest.TestCase):
    def test_P1_three_commands_in_order_any_case(self):
        r = parse_reply("p1 accept\nP2 Edit 60\np3 REJECT not this week", IDS)
        self.assertEqual(r.decisions, [Decision("p1", "accept"), Decision("p2", "edit", 60),
                                       Decision("p3", "reject", note="not this week")])
        self.assertEqual(r.errors, [])

    def test_P2_quoted_digest_is_never_parsed(self):
        # Gmail quotes the original digest, which contains the example lines "p1 accept" etc.
        # Some clients quote with ">", some paste the original unmarked under an "On ... wrote:" line.
        reply = "p2 reject\n\nOn Wed, Oct 14, 2026 at 7:00 AM <me@example.com> wrote:\n\np1 accept\np3 reject"
        self.assertEqual(parse_reply(reply, IDS).decisions, [Decision("p2", "reject")])
        reply = "p2 reject\n> To approve, reply with one line per block:\np1 accept"
        self.assertEqual(parse_reply(reply, IDS).decisions, [Decision("p2", "reject")])

    def test_P3_other_lines_are_ignored(self):
        r = parse_reply("Looks good!\n\n  p1 accept  \nthanks\n-- \nCarson", IDS)
        self.assertEqual(r.decisions, [Decision("p1", "accept")])
        self.assertEqual(r.errors, [])

    def test_P4_unknown_block_is_an_error_and_the_rest_still_parse(self):
        r = parse_reply("p9 accept\np1 accept", IDS)
        self.assertEqual(r.decisions, [Decision("p1", "accept")])
        self.assertEqual(len(r.errors), 1)
        self.assertIn("p9", r.errors[0])

    def test_P5_edit_needs_valid_minutes(self):
        for bad in ("p1 edit", "p1 edit soon", "p1 edit 5", "p1 edit 600", "p1 edit -30"):
            r = parse_reply(bad, IDS)
            self.assertEqual(r.decisions, [], bad)
            self.assertEqual(len(r.errors), 1, bad)
        self.assertEqual(parse_reply("p1 edit 45 shorter is fine", IDS).decisions,
                         [Decision("p1", "edit", 45, "shorter is fine")])

    def test_P6_a_block_named_twice_is_ambiguous_so_neither_counts(self):
        r = parse_reply("p1 accept\np2 accept\np1 reject", IDS)
        self.assertEqual(r.decisions, [Decision("p2", "accept")])
        self.assertTrue(any("p1" in e for e in r.errors))

    def test_P7_unknown_command_is_an_error(self):
        r = parse_reply("p1 maybe", IDS)
        self.assertEqual(r.decisions, [])
        self.assertEqual(len(r.errors), 1)

    def test_P8_text_before_the_commands_never_stops_parsing(self):
        # Only a real quote marker ends the reply: "Ok", "only two today", "On it!" are not quotes.
        for opener in ("Ok, here you go:", "only two today", "On it!"):
            r = parse_reply(f"{opener}\np1 accept", IDS)
            self.assertEqual(r.decisions, [Decision("p1", "accept")], opener)

    def test_P9_notes_keep_their_capitalization(self):
        r = parse_reply("P3 Reject Dentist moved to Thursday", IDS)
        self.assertEqual(r.decisions, [Decision("p3", "reject", note="Dentist moved to Thursday")])


class TestApply(unittest.TestCase):
    def test_A1_accept_writes_the_event(self):
        st = state()
        rep, cal, _ = run(st, [Decision("p1", "accept")])
        self.assertEqual(rep.written, ["p1"])
        (eid, ev), = cal.events.items()
        self.assertEqual((ev["start"], ev["end"]), (T("2026-10-15T09:00"), T("2026-10-15T09:20")))
        self.assertEqual(ev["summary"], "Text Nico")
        self.assertEqual(ev["key"], "cn-test:p1")
        self.assertEqual((blk(st, "p1")["status"], blk(st, "p1")["event_id"]), ("written", eid))

    def test_A2_edit_changes_the_length_and_keeps_the_original(self):
        st = state()
        run(st, [Decision("p2", "edit", 60)])
        b = blk(st, "p2")
        self.assertEqual((b["minutes"], b["proposed_minutes"], b["status"]), (60, 90, "written"))

    def test_A3_reject_writes_nothing(self):
        st = state()
        rep, cal, _ = run(st, [Decision("p3", "reject", note="not now")])
        self.assertEqual((rep.rejected, cal.events), (["p3"], {}))
        self.assertEqual(blk(st, "p3")["status"], "rejected")
        self.assertEqual(blk(st, "p3")["decision"], {"action": "reject", "minutes": None, "note": "not now"})

    def test_A4_unmentioned_blocks_are_untouched(self):
        st = state()
        run(st, [Decision("p1", "accept")])
        self.assertEqual(blk(st, "p2"), state()["blocks"][1])

    def test_A5_the_same_reply_twice_changes_nothing(self):
        st, cal = state(), FakeCalendar()
        ds = [Decision("p1", "accept"), Decision("p2", "edit", 60)]
        run(st, ds, cal)
        rep, _, _ = run(st, ds, cal)
        self.assertEqual(cal.insert_calls, 2)
        self.assertEqual(sorted(rep.unchanged), ["p1", "p2"])
        self.assertEqual(rep.written, [])

    def test_A6_a_different_second_decision_is_refused(self):
        st = state()
        run(st, [Decision("p1", "accept")])
        rep, _, _ = run(st, [Decision("p1", "reject")])
        self.assertEqual(len(rep.errors), 1)
        self.assertEqual(blk(st, "p1")["status"], "written")

    def test_A7_unknown_block_is_an_error(self):
        rep, _, _ = run(state(), [Decision("p9", "accept")])
        self.assertEqual(len(rep.errors), 1)

    def test_A8_lost_response_does_not_duplicate_the_event(self):
        st, cal = state(), FakeCalendar(lose_response={1})
        rep, _, _ = run(st, [Decision("p1", "accept")], cal)
        self.assertEqual(rep.retry, ["p1"])                  # we don't know it worked
        rep, _, _ = run(st, [], cal)                         # next run, no new reply
        self.assertEqual(rep.written, ["p1"])
        self.assertEqual((cal.insert_calls, len(cal.events)), (1, 1))
        self.assertEqual(blk(st, "p1")["event_id"], "ev1")

    def test_A9_transient_failures_retry_then_give_up(self):
        st = state()
        fail = {n: TransientCalendarError("429") for n in range(1, 10)}
        cal = FakeCalendar(fail=fail)
        for attempt in range(1, MAX_ATTEMPTS):
            rep, _, _ = run(st, [Decision("p1", "accept")] if attempt == 1 else [], cal)
            self.assertEqual((rep.retry, blk(st, "p1")["attempts"]), (["p1"], attempt))
        rep, _, _ = run(st, [], cal)
        self.assertEqual((rep.failed, blk(st, "p1")["status"]), (["p1"], "failed"))

    def test_A10_one_permanent_failure_does_not_stop_the_others(self):
        st, cal = state(), FakeCalendar(fail={1: CalendarError("forbidden")})
        rep, _, _ = run(st, [Decision("p1", "accept"), Decision("p3", "accept")], cal)
        self.assertEqual((rep.failed, rep.written), (["p1"], ["p3"]))

    def test_A11_conflict_with_an_existing_event_is_not_written(self):
        st = state()
        cal = FakeCalendar(busy=[(T("2026-10-15T09:10"), T("2026-10-15T09:40"))])
        rep, _, _ = run(st, [Decision("p1", "accept")], cal)
        self.assertEqual((rep.conflicts, cal.insert_calls), (["p1"], 0))
        self.assertEqual(blk(st, "p1")["status"], "conflict")

    def test_A12_an_edit_that_runs_into_the_next_block_conflicts(self):
        st = state()   # p1 09:00 + 120 min overlaps p2 at 10:00
        rep, _, _ = run(st, [Decision("p1", "edit", 120), Decision("p2", "accept")])
        self.assertEqual((rep.written, rep.conflicts), (["p1"], ["p2"]))

    def test_A13_a_block_whose_time_has_passed_expires(self):
        st = state()
        rep, cal, _ = run(st, [Decision("p1", "accept")], now=datetime(2026, 10, 15, 12, 0))
        self.assertEqual((rep.expired, cal.insert_calls), (["p1"], 0))
        self.assertEqual(blk(st, "p1")["status"], "expired")      # saved, so the next run doesn't retry it

    def test_A21_a_block_already_under_way_is_still_written(self):
        st = state()   # p1 is 09:00-09:20
        rep, cal, _ = run(st, [Decision("p1", "accept")], now=datetime(2026, 10, 15, 9, 10))
        self.assertEqual(rep.written, ["p1"])
        ev = next(iter(cal.events.values()))
        self.assertEqual(ev["start"], T("2026-10-15T09:00"))      # written as approved, not trimmed

    def test_A21_a_block_expires_when_it_ends(self):
        st = state()
        rep, cal, _ = run(st, [Decision("p1", "accept")], now=datetime(2026, 10, 15, 9, 20))
        self.assertEqual((rep.expired, cal.insert_calls), (["p1"], 0))

    def test_A14_progress_is_saved_after_each_write(self):
        st = state()
        _, _, save = run(st, [Decision("p1", "accept"), Decision("p3", "accept")])
        # some saved snapshot shows p1 written while p3 is approved but not yet written:
        # a crash at that point loses nothing
        self.assertTrue(any(blk(s, "p1")["status"] == "written" and blk(s, "p3")["status"] == "approved"
                            for s in save.snapshots))
        self.assertEqual(save.snapshots[-1], st)


class TestApplyEdges(unittest.TestCase):
    """Added after the first review: cases the original 21 tests didn't pin down."""

    def test_A15_a_conflict_is_reported_for_the_block_that_conflicts(self):
        st = state()
        cal = FakeCalendar(busy=[(T("2026-10-15T10:30"), T("2026-10-15T11:00"))])   # overlaps p2 only
        rep, _, _ = run(st, [Decision("p2", "accept"), Decision("p3", "accept")], cal)
        self.assertEqual((rep.conflicts, rep.written), (["p2"], ["p3"]))

    def test_A16_a_retry_run_with_no_decisions_can_hit_a_conflict(self):
        st = state()
        blk(st, "p1").update(status="approved", decision={"action": "accept", "minutes": None, "note": ""})
        cal = FakeCalendar(busy=[(T("2026-10-15T09:00"), T("2026-10-15T09:30"))])
        rep, _, _ = run(st, [], cal)
        self.assertEqual(rep.conflicts, ["p1"])

    def test_A17_a_rejected_block_cannot_be_accepted_later(self):
        st = state()
        run(st, [Decision("p3", "reject")])
        rep, cal, _ = run(st, [Decision("p3", "accept")])
        self.assertEqual((len(rep.errors), cal.insert_calls), (1, 0))
        self.assertEqual(blk(st, "p3")["status"], "rejected")

    def test_A18_a_permanent_error_from_any_calendar_call_fails_that_block_only(self):
        class BusyRefused(FakeCalendar):
            def busy(self, start, end):
                if start.hour == 9:
                    raise CalendarError("403")
                return super().busy(start, end)
        st = state()
        rep, _, _ = run(st, [Decision("p1", "accept"), Decision("p3", "accept")], BusyRefused())
        self.assertEqual((rep.failed, rep.written), (["p1"], ["p3"]))
        self.assertEqual(blk(st, "p1")["status"], "failed")

    def test_A19_a_transient_error_from_any_calendar_call_is_retried_not_raised(self):
        class FindRateLimited(FakeCalendar):
            def find_by_key(self, key):
                raise TransientCalendarError("429")
        st = state()
        rep, _, _ = run(st, [Decision("p1", "accept")], FindRateLimited())
        self.assertEqual(rep.retry, ["p1"])
        self.assertEqual((blk(st, "p1")["status"], blk(st, "p1")["attempts"]), ("approved", 1))

    def test_A20_every_change_reaches_the_saved_state(self):
        # The runner only persists what save() receives. Changes made after the last save() are lost
        # when the process exits, e.g. an attempts count that never reaches MAX_ATTEMPTS.
        cases = [("transient failure", FakeCalendar(fail={1: TransientCalendarError("429")}), NOW),
                 ("expired", FakeCalendar(), datetime(2026, 10, 15, 12, 0))]
        for name, cal, now in cases:
            st = state()
            _, _, save = run(st, [Decision("p1", "accept")], cal, now)
            self.assertEqual(save.snapshots[-1], st, name)


class TestRunner(unittest.TestCase):
    """Provided pieces of approve_run.py (not part of the assignment)."""

    def test_atomic_save_round_trips(self):
        import json, tempfile
        from pathlib import Path
        from approve_run import atomic_save
        path = Path(tempfile.mkdtemp()) / "s.json"
        atomic_save(path)(state())
        self.assertEqual(json.loads(path.read_text()), state())
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_eval_log_records_only_new_decisions(self):
        import json, tempfile
        from pathlib import Path
        from approve_run import log_decisions
        log = Path(tempfile.mkdtemp()) / "d.jsonl"
        before, after = state(), state()
        blk(after, "p2").update(decision={"action": "edit", "minutes": 60, "note": ""}, status="written", minutes=60)
        self.assertEqual(log_decisions(before, after, log), 1)
        row = json.loads(log.read_text())
        self.assertEqual((row["proposal_id"], row["action"], row["proposed_minutes"], row["minutes"]),
                         ("p2", "edit", 90, 60))
        self.assertEqual(log_decisions(after, after, log), 0)


if __name__ == "__main__":
    unittest.main()
