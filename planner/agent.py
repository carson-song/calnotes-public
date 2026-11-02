"""YOUR ASSIGNMENT: the planner's agent loop.

Read planner/SPEC.md first. Write it with the Anthropic SDK directly — no agent frameworks.
Acceptance: `python3 -m unittest tests.test_agent` passes, then a real run with plan_demo.py.
"""
import json
from pathlib import Path
import tempfile

from dataclasses import dataclass, field

from boundary.export import EgressBatch  # noqa: F401  (you'll need it for requirement 1)
from planner.tools import GOALS_SUMMARY, ToolBox, ToolError  # noqa: F401


@dataclass
class AgentResult:
    final_text: str           # the model's last text answer ("" if it never gave one)
    stop_reason: str          # "end_turn", "max_steps", "max_tokens", ...
    steps: int                # number of model calls made
    proposals: list = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})

SYSTEM_PROMPT = f"""You plan focused work blocks for one person’s week. This person has stated the following goals: 
G1: {GOALS_SUMMARY["G1"]},
G2: {GOALS_SUMMARY["G2"]}, 
G3: {GOALS_SUMMARY["G3"]}. 
Check free slots before proposing, skip pending_clarification items, never plan musings, good words, or friends’ goals, and at most 5 blocks."""




def run_agent(batch, client, model: str, task: str, max_steps: int = 8,
              log_path=None, max_tokens: int = 2000, calendar = None, now=None) -> AgentResult:
    """Run the planner on a sanitized batch until it finishes or hits a limit."""

    #r1
    if not isinstance(batch, EgressBatch):
        raise TypeError("agent did not receive a batch")

    #create messages trail as list of dicts
    messages = [{"role": "user", "content": task}]
    
    #initate toolbox and create first client call
    toolbox = ToolBox(batch, calendar=calendar, now=now)
    steps = 0
    usage = {"input_tokens": 0, "output_tokens": 0}
    finalText = ""
    stop_reason = ""
    while True:
        #make client call and increase counter
        
        steps += 1
        r = client.messages.create(model=model, max_tokens=max_tokens, system=SYSTEM_PROMPT, tools=toolbox.definitions, messages=messages)
        
        #track per call and cumulative token usage
        this_usage = {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens}
        usage["input_tokens"] += r.usage.input_tokens
        usage["output_tokens"] += r.usage.output_tokens

        #update final text, if possible
        for block in r.content:
                if block.type == "text":
                    finalText = block.text
        
        #append client's response to the messages trail
        messages.append({"role": "assistant", "content": r.content})


        #navigate client's response, assessing for task completion and calling tools where necessary
        if r.stop_reason != "tool_use":
            #return agent result, noting that "r" is just the client's most recent response
            updateLogs(log_path, steps, r.stop_reason,[] , this_usage, convert_blocks_to_dict(r.content), [])
            stop_reason = r.stop_reason
            break

        response = []
        tool_calls = []
        for block in r.content:
            if block.type == "tool_use":
                tool_calls.append(block.name)
                try:
                    tool_result = toolbox.call(block.name, block.input)
                    response.append( {"type": "tool_result", "tool_use_id": block.id, "content": tool_result})
                except ToolError as e:
                    response.append( {"type": "tool_result", "tool_use_id": block.id, "content": f"Tool Error - {e}", "is_error": True})
                
        messages.append({"role": "user", "content": response})
        
        #check if max steps -- then log with max steps
        if steps == max_steps:
            updateLogs(log_path, steps, "max_steps", [b.name for b in r.content if b.type == "tool_use"], this_usage, convert_blocks_to_dict(r.content), response)
            stop_reason = "max_steps"
            break
            # return AgentResult(finalText, "max_steps", steps, list(toolbox.proposals), usage) 
        else: # otherwise log it with tool use reason 
            updateLogs(log_path, steps, r.stop_reason,list(tool_calls), this_usage, convert_blocks_to_dict(r.content), response)


    # finalLog = vars(block)
    return AgentResult(finalText, stop_reason, steps, list(toolbox.proposals), usage) 
    # return AgentResult(r.content[0], r.stop_reason, steps, list(toolbox.proposals), usage) 
    
    
def updateLogs(log_path, steps, stop_reason, tool_calls, usage, full_log_assistant, full_log_tool_calls):
    if log_path is None:
        return
    logDict = {"step": steps, "stop_reason": stop_reason, "tool_calls": tool_calls, "usage": usage, "full_log_assistant": full_log_assistant,"full_log_tool_calls":full_log_tool_calls }
    with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(logDict) + "\n")
        
        # with open(log_path, "w", encoding="utf-8") as f:


def convert_blocks_to_dict(blocks):
    return [b.model_dump() if hasattr(b, "model_dump") else vars(b) for b in blocks]

