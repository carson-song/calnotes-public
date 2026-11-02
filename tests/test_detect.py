import json
import unittest
from pathlib import Path

from triage import detect

FIXTURES = Path(__file__).resolve().parent / "fixtures"   # invented data, never data/


def item(title, minutes=60, description="", location="", color_id="", start="2026-10-20T20:00"):
    from datetime import datetime, timedelta
    s = datetime.fromisoformat(start)
    return {
        "id": "x", "title": title, "start": start,
        "end": (s + timedelta(minutes=minutes)).isoformat(timespec="minutes"),
        "description": description, "location": location, "color_id": color_id,
    }


class TestEachRule(unittest.TestCase):
    def check(self, it, verdict, rule, names=frozenset()):
        d = detect.decide(it, names)
        self.assertEqual((d.verdict, d.rule), (verdict, rule), d.detail)

    def test_r1_meeting_log(self):
        self.check(item("anything", description="meeting-log | with: Sam"), "event", "R1_meeting_log")

    def test_r2_location(self):
        self.check(item("sam", location="Ritual Coffee"), "event", "R2_location")

    def test_r3_color(self):
        self.check(item("sam", color_id="3"), "event", "R3_color")

    def test_r4_length(self):
        self.check(item("sam", minutes=90), "event", "R4_length")

    def test_r5_period_mid_title(self):
        self.check(item("ship it. now"), "note", "R5_sentence")

    def test_r5_long_title(self):
        self.check(item("one two three four five six seven eight nine"), "note", "R5_sentence")

    def test_r5_decimal_time_is_not_a_sentence(self):
        self.check(item("sam coffee 11.45"), "event", "R6_meeting_word")

    def test_r6_meeting_word(self):
        self.check(item("kai park interview"), "event", "R6_meeting_word")

    def test_r7_known_name(self):
        self.check(item("craft day sam"), "unsure", "R7_known_name", {"sam"})

    def test_r7_possessive(self):
        self.check(item("sams stuff"), "unsure", "R7_known_name", {"sam"})

    def test_r8_default(self):
        self.check(item("evals and traceability"), "note", "R8_default")

    def test_sentence_beats_known_name(self):
        self.check(item("sams goals oct. ship it"), "note", "R5_sentence", {"sam"})


class TestKnownNames(unittest.TestCase):
    def test_time_aware_and_first_names_only(self):
        past = item("x", description="meeting-log | with: Felix Ward, Teo", start="2026-10-01T10:00")
        future = item("x", description="meeting-log | with: Zed", start="2026-12-01T10:00")
        names = detect.known_names_before([past, future], "2026-10-15T00:00")
        self.assertEqual(names, {"felix", "teo"})  # no "ward", no future "zed"


class TestRegressionsFromData(unittest.TestCase):
    """Real sandbox items whose outcome was decided on purpose. Keep these passing."""

    @classmethod
    def setUpClass(cls):
        cls.events = [json.loads(l) for l in open(FIXTURES / "events_v0.jsonl")]
        cls.by_id = {e["id"]: e for e in cls.events}

    def run_one(self, i):
        e = self.by_id[i]
        return detect.decide(e, detect.known_names_before(self.events, e["start"]))

    def test_cases(self):
        expected = {
            "n13": ("unsure", "R7_known_name"),   # craft day teo ines rui: ask, don't guess
            "n42": ("note", "R5_sentence"),       # teos goals nov. ... : a note despite the name
            "n37": ("event", "R2_location"),      # missed by the 3B model
            "n44": ("event", "R6_meeting_word"),  # kai park interview
            "n45": ("event", "R4_length"),        # 2-hour block
            "n40": ("note", "R5_sentence"),       # text nico. and ben okafor
        }
        for i, want in expected.items():
            with self.subTest(i=i):
                d = self.run_one(i)
                self.assertEqual((d.verdict, d.rule), want, d.detail)


if __name__ == "__main__":
    unittest.main()
