"""A fake Anthropic client for testing the agent loop without network calls or cost.

It returns scripted responses shaped like the SDK's (blocks with .type/.text/.id/.name/.input,
plus .stop_reason and .usage) and records a deep copy of every request it receives.
"""
import copy
from types import SimpleNamespace


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def response(*blocks, stop=None, usage=(10, 5)):
    if stop is None:
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop,
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
    )


class FakeClient:
    """Use like the real client: client.messages.create(model=..., messages=..., ...)."""

    def __init__(self, script):
        self._script = script  # a list of responses, or a function(call_number) -> response
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        n = len(self.calls)
        if callable(self._script):
            return self._script(n)
        if n > len(self._script):
            raise AssertionError(f"the model was called {n} times but only {len(self._script)} responses were scripted")
        return self._script[n - 1]
