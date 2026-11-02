import tempfile
import unittest
from pathlib import Path

import run_eval
from boundary import check
from boundary import policy as P
from boundary.export import export_batch
from boundary.vault import Vault
from triage import detect, pipeline
from triage.oracle import OracleBackend

FIXTURES = Path(__file__).resolve().parent / "fixtures"   # invented data, never data/

CANARY = "zqcanary"  # a string that exists nowhere else; if it shows up in a payload, something leaked


def tmp_vault():
    return Vault(Path(tempfile.mkdtemp()) / "vault.json")


def canary_item_and_record(type_, **rec_overrides):
    item = {
        "id": f"c-{type_}", "start": "2026-10-20T20:00", "end": "2026-10-20T21:00",
        "title": f"{CANARY}title secret plan with Marisol",
        "description": f"meeting-log | with: Marisol | {CANARY}desc",
        "location": f"{CANARY}ville Cafe, 1 Hidden St",
        "color_id": "",
    }
    rec = {
        "id": item["id"], "type": type_, "is_note": type_ != "event", "goal_links": ["G1"],
        "confidence": "high", "people": ["Marisol"], "company": f"{CANARY}corp",
        "normalized_text": f"{CANARY}text about Marisol", "next_action": "Call Marisol",
        "needs_clarification": f"{CANARY}question?", "detect_verdict": "note",
        "detect_rule": "R8_default", "detect_detail": f"{CANARY}detail", "musing_theme": "identity",
    }
    rec.update(rec_overrides)
    return item, rec


class TestCanaries(unittest.TestCase):
    """Plant a canary in every raw field. It must never cross, at any level."""

    def test_no_canary_crosses(self):
        for t in ["event", "action", "project_idea", "musing", "good_words", "other_person_goal"]:
            item, rec = canary_item_and_record(t)
            for level in P.LEVELS:
                with self.subTest(type=t, level=level):
                    b = export_batch([rec], {item["id"]: item}, tmp_vault(), level, canaries=[CANARY])
                    blob = repr(b.records).lower()
                    self.assertNotIn(CANARY, blob)
                    self.assertNotIn("marisol", blob)
                    self.assertNotIn(item["id"], blob)  # the source id never crosses either

    def test_never_text_types_send_no_words(self):
        for t in P.NEVER_TEXT:
            item, rec = canary_item_and_record(t)
            b = export_batch([rec], {item["id"]: item}, tmp_vault(), level=2)
            self.assertFalse(set(b.records[0]) & (P.LEVEL_1_KEYS | P.LEVEL_2_KEYS))

    def test_level_0_sends_no_free_text(self):
        item, rec = canary_item_and_record("action")
        b = export_batch([rec], {item["id"]: item}, tmp_vault(), level=0)
        self.assertFalse(set(b.records[0]) & P.TEXT_KEYS)


class TestFailClosed(unittest.TestCase):
    def test_location_word_in_action_is_dropped(self):
        item, rec = canary_item_and_record("action", next_action="Meet at Hidden St", people=[])
        b = export_batch([rec], {item["id"]: item}, tmp_vault(), level=1)
        self.assertEqual(len(b.records), 0)
        self.assertIn("location words", b.dropped[0][1][0])

    def test_checker_flags_names_and_unknown_keys(self):
        item, _ = canary_item_and_record("action")
        bad = {"handle": "h_0123456789", "type": "action", "date": "2026-10-20", "goal_links": [],
               "confidence": "high", "pending_clarification": False,
               "next_action": "call marisol", "title": "raw title"}
        v = check.violations(bad, item, {"marisol"})
        self.assertTrue(any("keys not allowed" in x for x in v))
        self.assertTrue(any("real name" in x for x in v))


class TestGroupWords(unittest.TestCase):
    def test_group_words_are_not_people(self):
        item, rec = canary_item_and_record("project_idea", people=["friends"], next_action="Ask friends",
                                           normalized_text="a chore chart for my roommates", company=None)
        b = export_batch([rec], {item["id"]: item}, tmp_vault(), level=2)
        self.assertEqual(b.records[0]["people"], [])
        self.assertIn("roommates", b.records[0]["text"])


class TestVault(unittest.TestCase):
    def test_round_trip_and_stability(self):
        v = tmp_vault()
        h = v.handle("n40")
        sent = v.pseudonymize("Text Nico and Ben Okafor; ask Okafor about Lumenware", ["Nico", "Ben Okafor"], ["lumenware"])
        self.assertNotIn("Nico", sent)
        self.assertNotIn("Okafor", sent)
        self.assertNotIn("Lumenware", sent)
        self.assertEqual(v.handle("n40"), h)
        v.save()
        again = Vault(v.path)
        self.assertEqual(again.handle("n40"), h)  # stable across restarts
        back = again.reidentify({"item": h, "do": sent})
        self.assertEqual(back["item"], "n40")
        self.assertIn("ben okafor", back["do"])


class TestAllRealItems(unittest.TestCase):
    """The full sandbox set through the real pipeline (oracle labels): nothing dropped, no names out."""

    def test_clean_export_all_levels(self):
        events, golds, _ = run_eval.load(root=FIXTURES)
        items = list(events.values())
        backend = OracleBackend(golds)
        recs = [pipeline.label_item(events[i], backend, detect.known_names_before(items, events[i]["start"]))
                for i in sorted(events)]
        names = detect.known_names_before(items, "9999")
        for level in P.LEVELS:
            with self.subTest(level=level):
                v = tmp_vault()
                b = export_batch(recs, events, v, level, extra_names=names)
                self.assertEqual(b.dropped, (), b.dropped)
                self.assertEqual(len(b.records), len(events))
                blob = repr(b.records).lower()
                for e in items:
                    if e["location"]:
                        self.assertNotIn(e["location"].lower(), blob)


if __name__ == "__main__":
    unittest.main()
