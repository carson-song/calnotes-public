"""Which digests the scheduler checks for replies. No network, no subprocesses."""
import unittest
from datetime import date

from scheduled import needs_attention

TODAY = date(2026, 10, 29)


def st(digest_id="cn-20261029-0700", delivered="gmail message abc", *statuses):
    return {"digest_id": digest_id, "delivered": delivered,
            "blocks": [{"status": s} for s in (statuses or ("proposed",))]}


class TestNeedsAttention(unittest.TestCase):
    def test_a_fresh_sent_digest_with_open_blocks(self):
        self.assertTrue(needs_attention(st(), TODAY))

    def test_a_dry_run_is_never_checked(self):
        self.assertFalse(needs_attention(st(delivered="file runs/digest/x.eml"), TODAY))

    def test_old_digests_are_left_alone(self):
        self.assertTrue(needs_attention(st("cn-20261026-0700"), TODAY))      # 3 days: still in
        self.assertFalse(needs_attention(st("cn-20261025-0700"), TODAY))

    def test_a_digest_with_nothing_left_to_do_is_skipped(self):
        self.assertFalse(needs_attention(st("cn-20261029-0700", "gmail message a", "written", "rejected"), TODAY))
        self.assertTrue(needs_attention(st("cn-20261029-0700", "gmail message a", "written", "approved"), TODAY))


if __name__ == "__main__":
    unittest.main()
