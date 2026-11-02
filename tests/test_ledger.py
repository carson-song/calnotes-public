"""Acceptance tests for ingest/SPEC.md: the item ledger and which notes are still open."""
import unittest
from datetime import datetime

from ingest.ledger import LATER_DEFAULT_DAYS, build_ledger, select_open_items

NOW = datetime(2026, 10, 20, 8, 0)
T = datetime.fromisoformat


def block(item, status="proposed", decision=None, start="2026-10-20T10:00", minutes=30, pid="p1"):
    return {"proposal_id": pid, "item_id": item, "start": start, "minutes": minutes, "status": status,
            "decision": decision}


def dec(action, note="", minutes=None):
    return {"action": action, "minutes": minutes, "note": note}


def digest(digest_id, *blocks):
    return {"digest_id": digest_id, "blocks": list(blocks)}


def status(states, item, now=NOW):
    return build_ledger(states, now)[item]["status"]


def ev(id_, start="2026-10-19T09:00", **kw):
    return {"id": id_, "title": id_, "start": start, "end": start, "all_day": False, "calnotes_key": None, **kw}


class TestLedgerRejections(unittest.TestCase):
    D = "cn-20261019-0700"

    def test_L1_no_reply_leaves_the_item_open(self):
        self.assertEqual(status([digest(self.D, block("n1"))], "n1"), "open")

    def test_L2_reject_done_and_drop(self):
        st = [digest(self.D, block("n1", "rejected", dec("reject", "done")),
                     block("n2", "rejected", dec("reject", "drop not doing this"), pid="p2"))]
        self.assertEqual((status(st, "n1"), status(st, "n2")), ("done", "dropped"))

    def test_L3_reject_later_snoozes_from_the_digest_date(self):
        st = [digest(self.D, block("n1", "rejected", dec("reject", "later 5d")))]
        led = build_ledger(st, NOW)
        self.assertEqual((led["n1"]["status"], led["n1"]["until"]), ("snoozed", "2026-10-24"))
        st = [digest(self.D, block("n1", "rejected", dec("reject", "later")))]
        self.assertEqual(build_ledger(st, NOW)["n1"]["until"], f"2026-10-{19 + LATER_DEFAULT_DAYS}")

    def test_L4_a_snooze_ends_on_its_date(self):
        st = [digest(self.D, block("n1", "rejected", dec("reject", "later 2d")))]   # until 10-21
        self.assertEqual(status(st, "n1", datetime(2026, 10, 20, 23, 0)), "snoozed")
        self.assertEqual(status(st, "n1", datetime(2026, 10, 21, 0, 1)), "open")

    def test_L5_any_other_reject_is_open_and_counted(self):
        st = [digest(self.D, block("n1", "rejected", dec("reject", "meh")))]
        led = build_ledger(st, NOW)
        self.assertEqual((led["n1"]["status"], led["n1"]["times_rejected"]), ("open", 1))

    def test_L6_reasons_ignore_case(self):
        st = [digest(self.D, block("n1", "rejected", dec("reject", "Done!")))]
        self.assertEqual(status(st, "n1"), "open")      # "done!" isn't the word "done": don't guess
        st = [digest(self.D, block("n1", "rejected", dec("reject", "DONE")))]
        self.assertEqual(status(st, "n1"), "done")


class TestLedgerApprovals(unittest.TestCase):
    D = "cn-20261019-0700"

    def test_L7_a_written_block_still_ahead_is_scheduled(self):
        st = [digest(self.D, block("n1", "written", dec("accept"), start="2026-10-20T10:00"))]
        self.assertEqual(status(st, "n1"), "scheduled")

    def test_L8_a_written_block_that_has_ended_is_unconfirmed(self):
        st = [digest(self.D, block("n1", "written", dec("accept"), start="2026-10-19T10:00", minutes=30))]
        self.assertEqual(status(st, "n1"), "unconfirmed")

    def test_L9_approved_but_not_yet_written_counts_as_scheduled(self):
        st = [digest(self.D, block("n1", "approved", dec("accept"), start="2026-10-19T10:00"))]
        self.assertEqual(status(st, "n1"), "scheduled")

    def test_L10_an_approval_that_never_reached_the_calendar_is_open(self):
        for s in ("conflict", "expired", "failed"):
            st = [digest(self.D, block("n1", s, dec("accept")))]
            self.assertEqual(status(st, "n1"), "open", s)


class TestLedgerHistory(unittest.TestCase):
    def test_L11_the_latest_digest_wins(self):
        older = digest("cn-20261018-0700", block("n1", "rejected", dec("reject", "later 1d")))
        newer = digest("cn-20261019-0700", block("n1", "written", dec("accept"), start="2026-10-20T10:00"))
        self.assertEqual(status([older, newer], "n1"), "scheduled")
        self.assertEqual(status([newer, older], "n1"), "scheduled")     # order of the list doesn't matter

    def test_L12_rejections_add_up_across_digests(self):
        st = [digest("cn-20261017-0700", block("n1", "rejected", dec("reject", "meh"))),
              digest("cn-20261018-0700", block("n1", "rejected", dec("reject", "nah")))]
        self.assertEqual(build_ledger(st, NOW)["n1"]["times_rejected"], 2)


class TestLedgerEdges(unittest.TestCase):
    D = "cn-20261019-0700"

    def test_L13_edit_counts_like_accept(self):
        st = [digest(self.D, block("n1", "written", dec("edit", minutes=45), start="2026-10-20T10:00"))]
        self.assertEqual(status(st, "n1"), "scheduled")

    def test_L14_a_reject_with_no_reason_is_open_and_counted(self):
        led = build_ledger([digest(self.D, block("n1", "rejected", dec("reject", "")))], NOW)
        self.assertEqual((led["n1"]["status"], led["n1"]["times_rejected"]), ("open", 1))

    def test_L15_an_unreadable_later_does_not_crash(self):
        for note in ("later soon", "later 5", "later tomorrow"):
            self.assertIn(status([digest(self.D, block("n1", "rejected", dec("reject", note)))], "n1"),
                          {"snoozed", "open"}, note)

    def test_L16_order_and_counts_hold_whatever_the_list_order(self):
        a = digest("cn-20261017-0700", block("n1", "rejected", dec("reject", "meh")))
        b = digest("cn-20261018-0700", block("n1", "rejected", dec("reject", "nah")))
        self.assertEqual(build_ledger([b, a], NOW)["n1"]["times_rejected"], 2)
        am = digest("cn-20261019-0700", block("n1", "rejected", dec("reject", "drop")))
        pm = digest("cn-20261019-1900", block("n1", "written", dec("accept"), start="2026-10-20T10:00"))
        self.assertEqual(status([pm, am], "n1"), "scheduled")       # same day: the time in the id decides

    def test_L17_a_later_digest_with_no_reply_keeps_the_count(self):
        st = [digest("cn-20261018-0700", block("n1", "rejected", dec("reject", "meh"))),
              digest("cn-20261019-0700", block("n1"))]
        led = build_ledger(st, NOW)
        self.assertEqual((led["n1"]["status"], led["n1"]["times_rejected"]), ("open", 1))

    def test_L18_a_block_in_progress_is_still_scheduled(self):
        st = [digest(self.D, block("n1", "written", dec("accept"), start="2026-10-20T07:45", minutes=30))]
        self.assertEqual(status(st, "n1"), "scheduled")             # ends 08:15, now is 08:00


class TestSelect(unittest.TestCase):
    def test_S1_our_own_blocks_and_all_day_events_are_skipped(self):
        events = [ev("ours", calnotes_key="cn-x:p1"), ev("allday", all_day=True), ev("note")]
        self.assertEqual([e["id"] for e in select_open_items(events, {}, NOW)], ["note"])

    def test_S2_only_the_window_up_to_now(self):
        events = [ev("old", "2026-10-05T09:00"), ev("edge", "2026-10-06T08:00"), ev("recent", "2026-10-19T09:00"),
                  ev("future", "2026-10-20T09:00")]
        self.assertEqual([e["id"] for e in select_open_items(events, {}, NOW, window_days=14)], ["edge", "recent"])

    def test_S3_items_that_are_not_open_are_skipped(self):
        led = {s: {"status": s} for s in ("scheduled", "unconfirmed", "done", "dropped", "snoozed", "open")}
        events = [ev(s) for s in led] + [ev("never_proposed")]
        self.assertEqual({e["id"] for e in select_open_items(events, led, NOW)}, {"open", "never_proposed"})

    def test_S4_results_are_in_time_order(self):
        events = [ev("b", "2026-10-19T12:00"), ev("a", "2026-10-18T09:00")]
        self.assertEqual([e["id"] for e in select_open_items(events, {}, NOW)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
