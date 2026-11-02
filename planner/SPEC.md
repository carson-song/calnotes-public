# Assignment: the planner's agent loop

You write one function, `run_agent()` in `planner/agent.py`, plus its system prompt. Everything else
is provided: the tools (`planner/tools.py`), a fake client for testing (`tests/fakes.py`), the acceptance
tests (`tests/test_agent.py`) and a real-API runner (`plan_demo.py`).

**Rules:** Anthropic SDK only (`client.messages.create`), no agent frameworks. Don't change the tools or
the tests. Try it without looking back at earlier code in our conversation; the hints at the bottom are
there if you get stuck.

## What the agent does

It gets a sanitized `EgressBatch` (level 1) and a task such as *"Propose up to 5 time blocks over the next
3 days for the items that best advance my goals."* It explores with `list_items` and `get_free_slots`,
proposes blocks with `propose_block`, and ends with a short text explanation. Proposals don't touch the
calendar; you approve them later.

## Interface (given)

```python
run_agent(batch, client, model, task, max_steps=8, log_path=None, max_tokens=2000) -> AgentResult
AgentResult(final_text, stop_reason, steps, proposals, usage)
ToolBox(batch).definitions   # tool schemas for the API
ToolBox(batch).call(name, input) -> str   # raises ToolError on a bad request
ToolBox(batch).proposals     # list of accepted proposals
GOALS_SUMMARY                # goal descriptions that may cross the boundary
```

## Requirements

1. **Boundary.** Accept only an `EgressBatch`; raise `TypeError` for anything else. Nothing reaches the
   model except the task, your system prompt, tool definitions and tool results.
2. **Prompt.** Send a real system prompt via `system=`: the goals (from `GOALS_SUMMARY`), what a good plan
   looks like, and what not to schedule. Send the tools via `tools=` and the task as the first user message.
3. **The loop.** Call the model; append its whole turn to the conversation as an `assistant` message; if it
   asked for tools, run every `tool_use` block and answer with ONE `user` message holding one `tool_result`
   per call, in the same order, each with the matching `tool_use_id` and string `content`. Repeat.
4. **Tool errors don't crash the run.** A `ToolError` (including an unknown tool) becomes a `tool_result`
   with `"is_error": True` and the error text, so the model can correct itself. Successful results have no
   error flag.
5. **Stopping.** Stop when the model finishes (`stop_reason` is anything other than `"tool_use"`; report it
   as-is, e.g. `"end_turn"` or `"max_tokens"`), or after `max_steps` model calls (report `"max_steps"`).
   Pass `max_tokens` to every API call.
6. **Result.** `final_text` = the model's last text block; `steps` = model calls made; `proposals` = the
   toolbox's accepted proposals; `usage` = input and output tokens summed over all calls.
7. **Trace.** If `log_path` is given, write one JSON line per model call with at least `step` (1-based),
   `stop_reason`, `tool_calls` (list of tool names called) and `usage` for that call.

## How to work

```bash
python3 -m unittest tests.test_agent -v      # 13 tests; each name says which requirement it checks
```

Get them passing one requirement at a time, in order. Then run it for real:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
python3 plan_demo.py                          # oracle labels, level 1, default model
python3 plan_demo.py --level 0                # same task with no words crossing: compare the plans
```

A run is a handful of calls with small prompts. `plan_demo.py` prints your agent's proposals mapped back to
your real notes (locally, through the vault) and writes the trace to `runs/agent/`.

## What I'll look at in review

- **Correctness beyond the tests:** what happens if the model returns no text at all, calls a tool with
  missing arguments, or proposes something the tools reject three times in a row?
- **The system prompt:** does it produce plans you'd actually accept? Read two real traces before tuning it.
- **Readability:** could someone new follow the loop in one read?
- **The trace:** could you debug a bad plan from the log alone?

## Hints (read only if stuck)

<details><summary>1. Where to start</summary>
Build a <code>ToolBox</code> from the batch, a <code>messages</code> list with the task, and a counter.
The loop is a <code>while</code> on the counter.
</details>

<details><summary>2. Appending the model's turn</summary>
Append <code>{"role": "assistant", "content": response.content}</code>. The SDK accepts its own content blocks back.
</details>

<details><summary>3. Text and tool calls in the same turn</summary>
One response can hold text blocks and several tool_use blocks. Loop over <code>response.content</code>
and check each block's <code>.type</code>.
</details>

<details><summary>4. Why the counter check matters</summary>
Without a step limit, a model that keeps calling tools never stops, and every extra call costs money.
</details>
