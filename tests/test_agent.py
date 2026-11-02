"""Acceptance tests for YOUR agent loop (planner/agent.py). They fail until you write it.

Run just these:   python3 -m unittest tests.test_agent -v
Each test name says which SPEC.md requirement it checks.
"""
import json
import tempfile
import unittest
from pathlib import Path

from boundary.export import export_batch
from boundary.vault import Vault
from planner.agent import run_agent
from tests.fakes import FakeClient, response, text, tool_use
from tests.test_boundary import CANARY, canary_item_and_record


def small_batch():
    """Three sanitized items built from canary-laden raw data: an action, a musing, an event."""
    items, recs = {}, []
    for t in ("action", "musing", "event"):
        item, rec = canary_item_and_record(t)
        items[item["id"]] = item
        recs.append(rec)
    vault = Vault(Path(tempfile.mkdtemp()) / "v.json")
    batch = export_batch(recs, items, vault, level=1)
    handles = {r["type"]: r["handle"] for r in batch.records}
    return batch, handles


TASK = "Plan my week."


class TestAgentLoop(unittest.TestCase):
    def setUp(self):
        self.batch, self.h = small_batch()

    def run_with(self, script, **kw):
        client = FakeClient(script)
        result = run_agent(self.batch, client, model="test-model", task=TASK, **kw)
        return client, result

    # R1 ---------------------------------------------------------------------
    def test_r1_rejects_anything_but_an_egress_batch(self):
        with self.assertRaises(TypeError):
            run_agent([{"title": "raw note"}], FakeClient([]), model="m", task=TASK)

    def test_r1_no_raw_data_in_any_request(self):
        client, _ = self.run_with([response(tool_use("t1", "list_items", {})), response(text("done"))])
        blob = repr(client.calls).lower()
        self.assertNotIn(CANARY, blob)
        self.assertNotIn("marisol", blob)

    # R2 ---------------------------------------------------------------------
    def test_r2_first_request_has_system_tools_and_task(self):
        client, _ = self.run_with([response(text("done"))])
        first = client.calls[0]
        self.assertEqual(first["model"], "test-model")
        self.assertTrue(first.get("system") and "TODO" not in first["system"], "write a real system prompt")
        self.assertIn("G1", first["system"], "the system prompt should give the goals")
        self.assertEqual({t["name"] for t in first["tools"]}, {"list_items", "get_free_slots", "propose_block"})
        self.assertEqual(first["messages"][0]["role"], "user")
        self.assertIn(TASK, json.dumps(first["messages"][0]["content"]))

    # R3 ---------------------------------------------------------------------
    def test_r3_final_answer_without_tools(self):
        client, r = self.run_with([response(text("Nothing to plan."))])
        self.assertEqual((r.final_text, r.stop_reason, r.steps), ("Nothing to plan.", "end_turn", 1))

    def test_r3_tool_result_goes_back_with_matching_id(self):
        client, r = self.run_with([response(tool_use("t1", "list_items", {"type": "action"})),
                                   response(text("ok"))])
        msgs = client.calls[1]["messages"]
        self.assertEqual(msgs[-2]["role"], "assistant", "append the model's turn before the results")
        self.assertEqual(msgs[-1]["role"], "user")
        res = msgs[-1]["content"]
        self.assertEqual(len(res), 1)
        self.assertEqual((res[0]["type"], res[0]["tool_use_id"]), ("tool_result", "t1"))
        self.assertIsInstance(res[0]["content"], str)
        self.assertIn(self.h["action"], res[0]["content"])
        self.assertEqual(r.steps, 2)

    def test_r3_parallel_calls_answered_in_one_message_in_order(self):
        client, _ = self.run_with([
            response(text("Let me look."), tool_use("t1", "list_items", {}),
                     tool_use("t2", "get_free_slots", {"date": "2026-10-20"})),
            response(text("ok")),
        ])
        res = client.calls[1]["messages"][-1]["content"]
        self.assertEqual([x["tool_use_id"] for x in res], ["t1", "t2"])

    # R4 ---------------------------------------------------------------------
    def test_r4_tool_errors_are_reported_not_raised(self):
        client, r = self.run_with([
            response(tool_use("t1", "no_such_tool", {}),
                     tool_use("t2", "propose_block", {"handle": self.h["musing"], "start": "2026-10-21T10:00",
                                                      "minutes": 30, "reason": "x"})),
            response(text("sorry")),
        ])
        res = client.calls[1]["messages"][-1]["content"]
        self.assertTrue(all(x.get("is_error") is True for x in res), res)
        self.assertEqual(r.stop_reason, "end_turn")

    def test_r4_successful_results_are_not_marked_errors(self):
        client, _ = self.run_with([response(tool_use("t1", "list_items", {})), response(text("ok"))])
        self.assertFalse(client.calls[1]["messages"][-1]["content"][0].get("is_error", False))

    # R5 ---------------------------------------------------------------------
    def test_r5_stops_at_max_steps(self):
        forever = lambda n: response(tool_use(f"t{n}", "list_items", {}))
        client, r = self.run_with(forever, max_steps=3)
        self.assertEqual((r.stop_reason, r.steps, len(client.calls)), ("max_steps", 3, 3))

    def test_r5_stops_on_max_tokens(self):
        client, r = self.run_with([response(text("partial answer, cut o"), stop="max_tokens")])
        self.assertEqual((r.stop_reason, r.steps), ("max_tokens", 1))

    def test_r5_passes_max_tokens_to_the_api(self):
        client, _ = self.run_with([response(text("done"))], max_tokens=777)
        self.assertEqual(client.calls[0]["max_tokens"], 777)

    # R6 ---------------------------------------------------------------------
    def test_r6_returns_proposals_and_summed_usage(self):
        client, r = self.run_with([
            response(tool_use("t1", "propose_block", {"handle": self.h["action"], "start": "2026-10-21T10:00",
                                                      "minutes": 60, "reason": "Moves G1 forward."}),
                     usage=(100, 20)),
            response(text("Proposed one block."), usage=(150, 30)),
        ])
        self.assertEqual([p["handle"] for p in r.proposals], [self.h["action"]])
        self.assertEqual(r.usage, {"input_tokens": 250, "output_tokens": 50})
        self.assertEqual(r.final_text, "Proposed one block.")

    # R7 ---------------------------------------------------------------------
    def test_r7_writes_one_log_line_per_model_call(self):
        log = Path(tempfile.mkdtemp()) / "run.jsonl"
        client, r = self.run_with([response(tool_use("t1", "list_items", {})), response(text("done"))],
                                  log_path=log)
        lines = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), r.steps)
        for i, line in enumerate(lines, 1):
            self.assertEqual(line["step"], i)
            for key in ("stop_reason", "tool_calls", "usage"):
                self.assertIn(key, line)
        self.assertEqual(lines[0]["tool_calls"], ["list_items"])

    # R8 ---------------------------------------------------------------------
    def test_r8_max_steps_is_one(self):
        client, r = self.run_with([response(text("only one step needed."))], max_steps = 1)
        self.assertEqual((r.final_text, r.stop_reason, r.steps), ("only one step needed.", "end_turn", 1))

    # R9 ---------------------------------------------------------------------
    def test_r9_silent_final_block(self):
        client, r = self.run_with([
            response(text("loud at beginning"), tool_use("t1", "list_items", {}),
                     tool_use("t2", "get_free_slots", {"date": "2026-10-21"})),
            response(tool_use("t1", "list_items", {}),
                     tool_use("t2", "get_free_slots", {"date": "2026-10-20"}))
        ], max_steps = 2)
        self.assertEqual(r.final_text, "loud at beginning")

    # R10 ---------------------------------------------------------------------
    def test_r10_refusal(self):
        client, r = self.run_with([
            response(text("i cant do that"), stop="refusal"),
        ])
        # for i in range(len(client.calls)):
        #     print(client.calls[i], "\n\n") 
        # print(client.messages)
        self.assertEqual((r.final_text, r.stop_reason), ("i cant do that", "refusal"))
        self.assertEqual(len(client.calls),  1)


if __name__ == "__main__":
    unittest.main()
