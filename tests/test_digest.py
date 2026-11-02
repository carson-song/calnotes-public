"""The digest: names come back locally, nothing opaque or unsafe gets sent, one recipient only."""
import email
import json
import os
import tempfile
import unittest
from email import policy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from boundary.vault import Vault
from digest.render import DigestError, build_digest
from digest.send import FileSender, build_message, recipient, save_state

EVENTS = {
    "n13": {"id": "n13", "title": "text nico. and ben okafor", "start": "2026-10-12T09:00"},
    "n40": {"id": "n40", "title": "sell the <b>orla</b> strap & co", "start": "2026-10-12T10:00"},
}
RECORDS = {"n13": {"id": "n13", "goal_links": ["G1"]},
           "n40": {"id": "n40", "goal_links": ["G3"], "next_action": "List it on the forum"}}


def setup():
    v = Vault(Path(tempfile.mkdtemp()) / "vault.json")
    h13, h40, nico = v.handle("n13"), v.handle("n40"), v.person("Nico")
    return v, h13, h40, nico


def result(proposals, final_text="ok"):
    return SimpleNamespace(proposals=proposals, final_text=final_text)


def prop(pid, handle, start, minutes, reason):
    return {"proposal_id": pid, "handle": handle, "start": start, "minutes": minutes, "reason": reason}


class TestRender(unittest.TestCase):
    def test_names_and_items_come_back(self):
        v, h13, h40, nico = setup()
        r = result([prop("p1", h13, "2026-10-15T09:00", 20, f"Text {nico} for leads."),
                    prop("p2", h40, "2026-10-16T14:00", 30, "List it.")],
                   final_text=f"I picked **{nico}** first ({h13}).")
        d = build_digest("cn-x", r, v, EVENTS, RECORDS)
        body = d.text()
        self.assertIn("text nico. and ben okafor", body)       # the real note title
        self.assertIn("Text nico for leads.", body)               # placeholder mapped back
        self.assertIn("Thu Oct 15, 09:00–09:20", body)
        self.assertIn("[G1 job search]", body)
        self.assertNotIn("[PERSON_", body)
        self.assertNotIn("h_", body)
        self.assertNotIn("**", d.notes)                           # markdown bold stripped
        self.assertEqual(d.subject, "Plan for Oct 15–Oct 16: 2 blocks [cn-x]")

    def test_unknown_placeholder_fails_closed(self):
        v, h13, _, _ = setup()
        r = result([prop("p1", h13, "2026-10-15T09:00", 20, "Text [PERSON_99] today.")])
        with self.assertRaises(DigestError):
            build_digest("cn-x", r, v, EVENTS, RECORDS)

    def test_unknown_handle_in_notes_fails_closed(self):
        v, h13, _, _ = setup()
        r = result([prop("p1", h13, "2026-10-15T09:00", 20, "ok")], final_text="see h_0123456789")
        with self.assertRaises(DigestError):
            build_digest("cn-x", r, v, EVENTS, RECORDS)

    def test_proposal_for_item_not_in_calendar_fails(self):
        v, *_ = setup()
        r = result([prop("p1", v.handle("n99"), "2026-10-15T09:00", 20, "ok")])
        with self.assertRaises(DigestError):
            build_digest("cn-x", r, v, EVENTS, RECORDS)

    def test_no_proposals_still_builds(self):
        v, *_ = setup()
        d = build_digest("cn-x", result([], final_text=""), v, EVENTS, RECORDS)
        self.assertIn("no blocks", d.text())
        self.assertIn("0 blocks", d.subject)

    def test_html_is_escaped(self):
        v, _, h40, _ = setup()
        d = build_digest("cn-x", result([prop("p1", h40, "2026-10-16T14:00", 30, "a < b")]), v, EVENTS, RECORDS)
        self.assertIn("&lt;b&gt;orla&lt;/b&gt; strap &amp; co", d.html())
        self.assertNotIn("<b>orla</b>", d.html())

    def test_next_action_leads_and_note_is_the_source(self):
        v, _, h40, _ = setup()
        d = build_digest("cn-x", result([prop("p1", h40, "2026-10-16T14:00", 30, "ok")]), v, EVENTS, RECORDS)
        self.assertEqual(d.blocks[0].title, "List it on the forum")
        self.assertIn("from: sell the <b>orla</b> strap & co", d.text())


class TestSend(unittest.TestCase):
    def test_recipient_must_be_exactly_one_address(self):
        for bad in ("", "nobody", "a@example.com,b@example.org"):
            with mock.patch.dict(os.environ, {"CALNOTES_DIGEST_TO": bad}), self.assertRaises(SystemExit):
                recipient()
        with mock.patch.dict(os.environ, {"CALNOTES_DIGEST_TO": " me@sandbox.test "}):
            self.assertEqual(recipient(), "me@sandbox.test")

    def test_dry_run_writes_a_real_email_and_state(self):
        v, h13, _, nico = setup()
        d = build_digest("cn-x", result([prop("p1", h13, "2026-10-15T09:00", 20, f"Text {nico}.")]),
                         v, EVENTS, RECORDS, {"model": "m"})
        out = Path(tempfile.mkdtemp())
        msg = build_message(d, "me@sandbox.test")
        FileSender(out).send(msg, "cn-x")
        parsed = email.message_from_bytes((out / "cn-x.eml").read_bytes(), policy=policy.default)
        self.assertEqual(parsed["To"], "me@sandbox.test")
        self.assertEqual(parsed["X-Calnotes-Digest"], "cn-x")
        self.assertIn("Text nico.", parsed.get_body(("plain",)).get_content())
        self.assertIsNotNone(parsed.get_body(("html",)))

        state = json.loads(save_state(d, "me@sandbox.test", "dry run", out).read_text())
        self.assertEqual(state["blocks"][0]["item_id"], "n13")    # real id, for applying approvals later
        self.assertIsNone(state["blocks"][0]["decision"])


if __name__ == "__main__":
    unittest.main()


class TestDigestV2(unittest.TestCase):
    """The v2 email: full notes, line breaks kept, everything escaped, help built from REPLY_HELP."""

    def digest(self, title, start="2026-10-30T09:00", minutes=45):
        from digest.render import Block, Digest
        b = Block("p1", "n1", "Do the thing", title, start, minutes, ["G1"], "Because <reasons> & more")
        return Digest("cn-20261030-0700", "s", [b], "Para one.\n\nPara <two>.", {"model": "m<x>"})

    def test_long_notes_are_not_trimmed(self):
        long = "word " * 40 + "THE END"
        d = self.digest(long)
        self.assertIn("THE END", d.text())
        self.assertIn("THE END", d.html())
        self.assertNotIn("…", d.html())

    def test_a_note_keeps_its_line_breaks(self):
        d = self.digest("garage shelves\nneed: wall width\nthinking 3 shelves")
        self.assertIn("garage shelves<br>need: wall width<br>thinking 3 shelves", d.html())
        self.assertIn("          need: wall width", d.text())          # continuation lines indented under "from:"

    def test_everything_from_notes_and_the_planner_is_escaped(self):
        page = self.digest("<script>x</script>").html()
        for raw in ("<script>", "<reasons>", "<two>", "m<x>"):
            self.assertNotIn(raw, page)
        self.assertIn("&lt;script&gt;", page)

    def test_the_reply_table_comes_from_reply_help(self):
        from digest.render import _help_commands
        cmds = [c for c, _ in _help_commands()]
        self.assertEqual(cmds[:2], ["p1 accept", "p2 edit 60"])
        page = self.digest("x").html()
        for c in cmds:
            self.assertIn(c, page)

    def test_times_read_naturally(self):
        from digest.render import Block
        b = lambda start, m: Block("p1", "n", "t", "", start, m, [], "r").day_and_span()
        self.assertEqual(b("2026-10-30T09:00", 45), ("Fri Oct 30", "9:00–9:45 AM"))
        self.assertEqual(b("2026-10-30T11:30", 60), ("Fri Oct 30", "11:30 AM–12:30 PM"))
        self.assertEqual(b("2026-10-30T12:15", 30), ("Fri Oct 30", "12:15–12:45 PM"))
