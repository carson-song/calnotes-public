"""The model backends: token accounting, and the frontier request shape. No network, no model."""
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import run_eval
from triage import local_llm

FIXTURES = Path(__file__).resolve().parent / "fixtures"   # invented data, never data/


def backend(cls):
    events, golds, split = run_eval.load(root=FIXTURES)
    return cls("m", run_eval.ROOT / "guide" / "rules_v0.3.md", events, golds, split["dev"]), events


class TestLocalUsage(unittest.TestCase):
    def test_tokens_from_each_ollama_reply_add_up(self):
        b, events = backend(local_llm.OllamaBackend)
        replies = iter([({"x": 1}, {"input_tokens": 100, "output_tokens": 7}),
                        ({"x": 2}, {"input_tokens": 50, "output_tokens": 3})])
        with mock.patch.object(local_llm, "_chat", lambda *a: next(replies)):
            b.event_fields(next(iter(events.values())))
            b.reflection(next(iter(events.values())))
        self.assertEqual((b.calls, b.usage["input_tokens"], b.usage["output_tokens"]), (2, 150, 10))


class FakeClient:
    def __init__(self):
        self.requests = []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text='{"goal_links": ["G1"]}')],
            usage=SimpleNamespace(input_tokens=40, output_tokens=12, cache_read_input_tokens=900,
                                  cache_creation_input_tokens=0))


class TestFrontier(unittest.TestCase):
    def setUp(self):
        sys.modules.setdefault("anthropic", types.SimpleNamespace(Anthropic=lambda **kw: None))
        from triage.frontier import FrontierBackend
        self.b, self.events = backend(FrontierBackend)
        self.b.client = self.fake = FakeClient()

    def test_same_prompt_as_local_with_structured_output_and_cached_system(self):
        item = next(iter(self.events.values()))
        out = self.b.event_fields(item)
        req = self.fake.requests[0]
        local = local_llm.OllamaBackend.messages(self.b, "event", [], item)
        self.assertEqual(out, {"goal_links": ["G1"]})
        self.assertEqual(req["system"][0]["text"], local[0]["content"])           # identical system prompt
        self.assertEqual(req["system"][0]["cache_control"], {"type": "ephemeral"})
        fmt = req["output_config"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertIs(fmt["schema"]["additionalProperties"], False)               # required by structured outputs
        self.assertNotIn("tools", req)                                             # no forced tool call
        from triage import schema as S
        self.assertNotIn("additionalProperties", S.EVENT_SCHEMA)                  # local model's schema untouched
        self.assertNotIn("temperature", req)     # current SDKs reject it; recent models sample at defaults
        self.assertNotIn("system", [m["role"] for m in req["messages"]])

    def test_schemas_meet_structured_output_rules(self):
        from triage import schema as S
        from triage.frontier import strict

        def nodes(n):
            if isinstance(n, dict):
                yield n
                for v in n.values():
                    yield from nodes(v)
            elif isinstance(n, list):
                for v in n:
                    yield from nodes(v)
        for sc in (S.EVENT_SCHEMA, S.category_schema(True), S.category_schema(False), S.REFLECTION_SCHEMA):
            for n in nodes(strict(sc)):
                self.assertFalse(isinstance(n.get("type"), list) and "enum" in n, n)   # enum beside a type list
                if n.get("type") == "object":
                    self.assertIs(n["additionalProperties"], False)
        theme = strict(S.REFLECTION_SCHEMA)["properties"]["musing_theme"]
        self.assertEqual(theme["anyOf"], [{"type": "string", "enum": S.THEMES}, {"type": "null"}])

    def test_cache_reads_are_counted_separately(self):
        self.b.event_fields(next(iter(self.events.values())))
        self.assertEqual((self.b.usage["input_tokens"], self.b.usage["cache_read_tokens"]), (40, 900))


if __name__ == "__main__":
    unittest.main()
