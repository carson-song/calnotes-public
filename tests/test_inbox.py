"""Reading replies from the digest's Gmail thread, and applying them once each. No network."""
import unittest
from datetime import datetime
from email.message import EmailMessage

from approve.fake import FakeCalendar
from approve.inbox import Reply, digest_message_id, replies_in_thread
from approve_run import apply_replies
from tests.test_approve import Saver, blk, state

ME = "me@sandbox.test"


def raw(sender=ME, text=None, html=None, digest_header=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = sender, ME, "Re: Plan [cn-test]", "Thu, 15 Oct 2026 07:30 -0700"
    if digest_header:
        m["X-Calnotes-Digest"] = "cn-test"
    if text is not None:
        m.set_content(text)
        if html is not None:
            m.add_alternative(html, subtype="html")
    elif html is not None:
        m.set_content(html, subtype="html")
    return bytes(m)


class TestThreadScan(unittest.TestCase):
    def test_the_digest_itself_is_skipped(self):
        scan = replies_in_thread([("d1", raw(text="p1 accept", digest_header=True))], ME)
        self.assertEqual((scan.replies, scan.ignored), ([], []))

    def test_a_reply_from_you_is_returned_with_its_plain_text(self):
        thread = [("d1", raw(text="digest", digest_header=True)),
                  ("r1", raw(text="p1 accept\n\nOn Thu wrote:\n> p2 accept", html="<p>p1 accept</p>"))]
        scan = replies_in_thread(thread, ME)
        self.assertEqual([r.message_id for r in scan.replies], ["r1"])
        self.assertIn("p1 accept", scan.replies[0].text)
        self.assertNotIn("<p>", scan.replies[0].text)

    def test_anyone_else_in_the_thread_is_ignored_and_reported(self):
        scan = replies_in_thread([("x1", raw(sender="stranger@evil.test", text="p1 accept"))], ME)
        self.assertEqual(scan.replies, [])
        self.assertEqual(scan.ignored[0][0], "x1")

    def test_sender_match_ignores_case_and_display_name(self):
        scan = replies_in_thread([("r1", raw(sender='"Carson" <ME@Sandbox.test>', text="p1 accept"))], ME)
        self.assertEqual(len(scan.replies), 1)

    def test_html_only_reply_is_ignored_not_guessed_at(self):
        scan = replies_in_thread([("r1", raw(html="<p>p1 accept</p>"))], ME)
        self.assertEqual((scan.replies, scan.ignored[0][1]), ([], "no plain-text part"))

    def test_a_dry_run_digest_has_no_thread(self):
        self.assertEqual(digest_message_id({"delivered": "gmail message 18f2a"}), "18f2a")
        with self.assertRaises(SystemExit):
            digest_message_id({"delivered": "dry run"})


class TestApplyReplies(unittest.TestCase):
    NOW = datetime(2026, 10, 15, 8, 0)

    def test_each_reply_is_applied_once_across_runs(self):
        st, cal = state(), FakeCalendar()
        replies = [Reply("r1", ME, "", "p1 accept"), Reply("r2", ME, "", "p3 reject not now")]
        apply_replies(st, replies, cal, self.NOW, Saver())
        self.assertEqual((blk(st, "p1")["status"], blk(st, "p3")["status"]), ("written", "rejected"))
        self.assertEqual(st["replies_seen"], ["r1", "r2"])

        results = apply_replies(st, replies, cal, self.NOW, Saver())     # the next poll sees the same thread
        self.assertEqual(cal.insert_calls, 1)
        self.assertIsNone(results[0][0])                                  # nothing new: plain retry

    def test_a_reply_with_no_valid_commands_is_still_marked_seen(self):
        st = state()
        results = apply_replies(st, [Reply("r1", ME, "", "thanks!")], FakeCalendar(), self.NOW, Saver())
        self.assertEqual(st["replies_seen"], ["r1"])
        self.assertEqual(results[0][1].decisions, [])

    def test_seen_replies_reach_the_saved_state(self):
        st, save = state(), Saver()
        apply_replies(st, [Reply("r1", ME, "", "p1 accept")], FakeCalendar(), self.NOW, save)
        self.assertEqual(save.snapshots[-1]["replies_seen"], ["r1"])


if __name__ == "__main__":
    unittest.main()
