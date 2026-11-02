"""The same three model steps, served by Claude through the Anthropic API. For the eval comparison only.

Identical prompts, worked examples and schemas to the local model (it subclasses OllamaBackend and only swaps
the transport), so a difference in scores is the model, not the prompt.

UNLIKE the local model, this sends raw note text off your machine. run_eval refuses to use it unless you pass
--send-raw-notes, so that's always a deliberate choice, never a default. The production pipeline never uses it.

Structured output: the same JSON schema goes in output_config.format (Claude's structured outputs), so the
reply is constrained to that shape, the same guarantee Ollama's constrained decoding gives the local model.
(An earlier version forced a tool call instead; some models reject forced tool use, so don't go back to that.)
No temperature: current SDKs no longer accept it, and recent Claude models only sample at their defaults. So
unlike the local model (temperature 0), frontier answers can vary run to run. Run a frontier model twice to see
how much; the comparison script's paired test shows the disagreement directly.
The system prompt is marked for prompt caching: it repeats on every call, so after the first call per step it's
read from cache. The token counts show how much that saves.
"""
import copy
import json

from triage.local_llm import OllamaBackend


def strict(schema: dict) -> dict:
    """Adapt a schema to Claude's structured-outputs rules, without touching the one the local model uses:
    - every object needs additionalProperties: false;
    - an enum can't sit beside a list of types ({"type": ["string", "null"], "enum": [..., null]} is rejected:
      "enum value does not match declared type"), so it becomes anyOf: [{"type": "string", "enum": [...]},
      {"type": "null"}], which means the same thing."""
    s = copy.deepcopy(schema)
    kinds = {"string": str, "boolean": bool, "null": type(None)}

    def split_enum(node):
        types, values = node.pop("type"), node.pop("enum")
        options = []
        for t in types:
            if t == "null":
                options.append({"type": "null"})
            else:
                vals = [v for v in values if isinstance(v, kinds.get(t, object)) and v is not None]
                options.append({"type": t, "enum": vals} if vals else {"type": t})
        node["anyOf"] = options

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
            if isinstance(node.get("type"), list) and "enum" in node:
                split_enum(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(s)
    return s


class FrontierBackend(OllamaBackend):
    def __init__(self, model, rules_path, events, golds, dev_ids):
        super().__init__(model, rules_path, events, golds, dev_ids)
        import anthropic
        self.client = anthropic.Anthropic(max_retries=6)    # backs off on 429 / overloaded by itself

    def _run(self, step, shots, item, fmt):
        self.calls += 1
        msgs = self.messages(step, shots, item)
        system, convo = msgs[0]["content"], msgs[1:]
        resp = self.client.messages.create(
            model=self.model, max_tokens=1024,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=convo,
            output_config={"format": {"type": "json_schema", "schema": strict(fmt)}},
        )
        u = resp.usage
        self._count({"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                     "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
                     "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0})
        if resp.stop_reason in ("refusal", "max_tokens"):
            raise RuntimeError(f"{self.model} stopped with {resp.stop_reason} on {item['id']}: output may not "
                               f"match the schema")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)
