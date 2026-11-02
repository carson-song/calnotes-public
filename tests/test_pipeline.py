import json
import unittest
from pathlib import Path

import run_eval
from triage import detect, fewshot, local_llm, pipeline
from triage import schema as S
from triage.oracle import OracleBackend

FIXTURES = Path(__file__).resolve().parent / "fixtures"   # invented data, never data/

ROOT = Path(__file__).resolve().parent.parent


class TestPlumbing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events, cls.golds, cls.split = run_eval.load(root=FIXTURES)
        cls.items = list(cls.events.values())

    def run_all(self, backend, ids):
        return {
            i: pipeline.label_item(self.events[i], backend, detect.known_names_before(self.items, self.events[i]["start"]))
            for i in ids
        }

    def test_oracle_scores_perfectly(self):
        ids = sorted(self.events)
        recs = self.run_all(OracleBackend(self.golds), ids)
        m, *_ = run_eval.score(ids, recs, self.golds)
        for k in ["is_note_acc_final", "type_acc_strict", "goal_links_exact", "musing_theme_acc"]:
            self.assertEqual(m[k], 1.0, k)

    def test_hard_rules_enforced(self):
        rec = pipeline.enforce({"type": "good_words", "goal_links": ["G1"], "musing_theme": "identity"})
        self.assertEqual((rec["goal_links"], rec["musing_theme"], rec["is_note"]), ([], None, True))
        rec = pipeline.enforce({"type": "other_person_goal", "goal_links": ["G3"]})
        self.assertEqual(rec["goal_links"], [])

    def test_social_events_link_only_with_a_task(self):
        hang = pipeline.enforce({"type": "event", "meeting_type": "social", "goal_links": ["G1"], "next_action": None})
        task = pipeline.enforce({"type": "event", "meeting_type": "social", "goal_links": ["G2"], "next_action": "Measure kitchen"})
        biz = pipeline.enforce({"type": "event", "meeting_type": "business", "goal_links": ["G1"], "next_action": None})
        self.assertEqual((hang["goal_links"], task["goal_links"], biz["goal_links"]), ([], ["G2"], ["G1"]))

    def test_event_shots_are_balanced(self):
        shots = fewshot.event_shots("n04", self.split["dev"], self.events, self.golds)
        goals = [tuple(out["goal_links"]) for _, out in shots]
        self.assertIn((), goals)
        self.assertEqual(len(set(goals)), len(goals))

    def test_fewshot_never_leaks(self):
        dev, test = self.split["dev"], set(self.split["test"])
        for i in sorted(self.events):
            shot_ids = set()
            for allow_event in (False, True):
                for ev, _ in fewshot.category_shots(i, dev, self.events, self.golds, allow_event):
                    shot_ids.add(ev["id"])
            for ev, _ in fewshot.reflection_shots(i, dev, self.events, self.golds):
                shot_ids.add(ev["id"])
            for ev, _ in fewshot.event_shots(i, dev, self.events, self.golds):
                shot_ids.add(ev["id"])
            self.assertNotIn(i, shot_ids, "an item is its own example")
            self.assertFalse(shot_ids & test, "a test item was used as an example")

    def test_category_shots_include_an_ask(self):
        shots = fewshot.category_shots("n40", self.split["dev"], self.events, self.golds)
        self.assertTrue(any(out["needs_clarification"] for _, out in shots))


class TestOllamaPathWithoutOllama(unittest.TestCase):
    """Runs the real prompt-building code with the HTTP call replaced by a stub."""

    def test_real_prompts_route_correctly(self):
        events, golds, split = run_eval.load(root=FIXTURES)
        sent = []

        def fake_chat(model, messages, fmt):
            sent.append((messages, fmt))
            props = fmt["properties"]
            if "kind" in props:
                return {"kind": "good_words", "musing_theme": None}, {}       # (reply, token usage)
            out = S.to_event_output(golds["n03"])
            if "category" in props:
                out = {"normalized_text": "x", "category": "reflection", **{k: v for k, v in out.items() if k != "normalized_text"}}
            return out, {}

        real = local_llm._chat
        local_llm._chat = fake_chat
        try:
            backend = local_llm.OllamaBackend("stub", ROOT / "guide" / "rules_v0.3.md", events, golds, split["dev"])
            items = list(events.values())
            ev = pipeline.label_item(events["n37"], backend, detect.known_names_before(items, events["n37"]["start"]))
            note = pipeline.label_item(events["n16"], backend, detect.known_names_before(items, events["n16"]["start"]))
        finally:
            local_llm._chat = real

        self.assertEqual((ev["type"], ev["model_calls"]), ("event", 1))
        self.assertEqual((note["type"], note["model_calls"]), ("good_words", 2))
        for messages, fmt in sent:
            self.assertEqual(messages[0]["role"], "system")
            self.assertIn("## Context", messages[0]["content"])
            last = json.loads(messages[-1]["content"])
            self.assertNotIn("id", last)  # the model never sees ids or labels


if __name__ == "__main__":
    unittest.main()


class TestNoTestItemsInPrompts(unittest.TestCase):
    """The model must never see a held-out test item's wording in its rules."""

    def test_rules_do_not_quote_test_items(self):
        import re
        norm = lambda s: " ".join(re.findall(r"[a-z0-9']+", s.lower()))
        # The invented fixtures always; your real notes too when data/ is present (the private repo).
        roots = [FIXTURES] + ([run_eval.DATA] if (run_eval.DATA / "events_v0.jsonl").exists() else [])
        for root in roots:
            events, _, split = run_eval.load(root=root)
            for path in (ROOT / "guide").glob("rules_v*.md"):
                if path.name < "rules_v0.3.md":
                    continue  # older versions are kept for history only
                rules = norm(path.read_text(encoding="utf-8"))
                for i in split["test"]:
                    w = norm(events[i]["title"]).split()
                    runs = [" ".join(w[k:k + 3]) for k in range(len(w) - 2)] or [" ".join(w)]
                    leaked = [r for r in runs if r in rules]
                    self.assertFalse(leaked, f"{path.name} quotes test item {i} ({root.name}): {leaked}")
