"""Model steps served by a local Ollama model. Raw note text only goes to localhost.

Three narrow prompts instead of one wide one:
  event_fields  — events: goal links, people, company, next action
  category      — notes (and unsure items): 7 categories, reflection is one bucket
  reflection    — reflections only: musing vs. good words, and the musing theme
"""
import json
import urllib.request

from triage import fewshot
from triage import schema as S
from triage.items import item_view

OLLAMA_URL = "http://localhost:11434/api/chat"

PROMPT_SECTIONS = {
    "event": ["Context", "Goal links", "Other fields", "Ask, don't guess"],
    "note": ["Context", "Note categories", "Goal links", "Other fields", "Ask, don't guess"],
    "unsure": ["Context", "Note or event", "Note categories", "Goal links", "Other fields", "Ask, don't guess"],
    "reflection": ["Context", "Reflections"],
}


def load_rules(path) -> dict[str, str]:
    sections, cur = {}, None
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for line in lines:
        if line.startswith("## "):
            cur = line[3:].strip()
            sections[cur] = []
        elif cur:
            sections[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _chat(model: str, messages: list[dict], fmt: dict) -> tuple[dict, dict]:
    body = {
        "model": model, "messages": messages, "format": fmt,  # constrained decoding to the schema
        "stream": False, "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        OLLAMA_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.loads(r.read())
    usage = {"input_tokens": resp.get("prompt_eval_count", 0), "output_tokens": resp.get("eval_count", 0)}
    return json.loads(resp["message"]["content"]), usage


class OllamaBackend:
    def __init__(self, model, rules_path, events, golds, dev_ids):
        self.model, self.events, self.golds, self.dev = model, events, golds, dev_ids
        self.rules = load_rules(rules_path)
        self.calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}

    def _count(self, usage: dict):
        for k, v in usage.items():
            self.usage[k] = self.usage.get(k, 0) + (v or 0)

    def messages(self, step: str, shots, item) -> list[dict]:
        system = "\n\n".join(f"## {name}\n{self.rules[name]}" for name in PROMPT_SECTIONS[step])
        system += "\n\nReturn ONLY a JSON object matching the schema."
        msgs = [{"role": "system", "content": system}]
        for ex_item, ex_out in shots:
            msgs.append({"role": "user", "content": json.dumps(item_view(ex_item), ensure_ascii=False)})
            msgs.append({"role": "assistant", "content": json.dumps(ex_out, ensure_ascii=False)})
        msgs.append({"role": "user", "content": json.dumps(item_view(item), ensure_ascii=False)})
        return msgs

    def _run(self, step, shots, item, fmt):
        self.calls += 1
        out, usage = _chat(self.model, self.messages(step, shots, item), fmt)
        self._count(usage)
        return out

    def event_fields(self, item):
        shots = fewshot.event_shots(item["id"], self.dev, self.events, self.golds)
        return self._run("event", shots, item, S.EVENT_SCHEMA)

    def category(self, item, mode):
        unsure = mode == "unsure"
        shots = fewshot.category_shots(item["id"], self.dev, self.events, self.golds, allow_event=unsure)
        return self._run(mode, shots, item, S.category_schema(allow_event=unsure))

    def reflection(self, item):
        shots = fewshot.reflection_shots(item["id"], self.dev, self.events, self.golds)
        return self._run("reflection", shots, item, S.REFLECTION_SCHEMA)
