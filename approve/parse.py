"""YOUR ASSIGNMENT, part 1: turn a reply email into decisions. Read approve/SPEC.md first.

Acceptance: the TestParse tests in tests/test_approve.py.
"""
from dataclasses import dataclass, field
import re 

MIN_MINUTES, MAX_MINUTES = 15, 240

COMMAND_START = re.compile(r"^\s*(p\d+)\b\s*(.*)", re.IGNORECASE)
COMMAND_ACTION = re.compile(r"^\s*\b(accept|edit|reject)\b\s*(.*)", re.IGNORECASE)
COMMAND_MINS = re.compile(r"^\s*(\d+)\b\s*(.*)", re.IGNORECASE)

@dataclass(frozen=True)
class Decision:
    proposal_id: str            # "p1"
    action: str                 # "accept" | "edit" | "reject"
    minutes: int | None = None  # only for "edit"
    note: str = ""              # free text after the command, e.g. why you rejected it


@dataclass
class ParseResult:
    decisions: list = field(default_factory=list)  # in the order they appear in the reply
    errors: list = field(default_factory=list)     # one readable message per problem, naming the block


def parse_reply(text: str, proposal_ids: set) -> ParseResult:
    """Parse your reply. Never raises on bad input: problems go in .errors."""
    #split by new lines
    lines = text.splitlines()
    found = {}
    decisions = {}
    errors = []
    for l in lines:
        # l = l.casefold()
        if l == "":
            continue

        QUOTE_HEADER = re.compile(r"^On .+wrote:$", re.IGNORECASE)
        line = l.strip()
        if line.startswith(">") or QUOTE_HEADER.match(line):
        # if l[0] == ">" or l[0] =="o":
            # print("exited upon seeing start of email history chain")
            break

        

        match1 = COMMAND_START.match(l)

        if match1:
                p_id, tail = match1.groups()
                p_id = p_id.lower()
                if p_id not in proposal_ids:
                    errors.append(f"No matching proposal for \"{p_id}\". Start your reply with p*, where * is a valid proposal id")
                    continue
                if p_id in found:
                    found[p_id] += 1
                    decisions.pop(p_id, None)
                    errors.append(f"Multiple instructions found for \"{p_id}\". Please specify a single instruction.")
                    continue
                else:
                    found[p_id] = 1
                
                
                match2 = COMMAND_ACTION.match(tail)
                
                if match2:
                    response, tail = match2.groups()
                    response = response.lower()
                    match response:
                        case "accept":
                            decision = Decision(p_id, response, None, tail)
                            decisions[p_id] = decision
                            # print("accepted decision")
                            continue
                        case "reject":
                            decision = Decision(p_id, response, None, tail)
                            decisions[p_id] = decision
                            # print("rejected decision")
                            continue
                        case "edit":
                            
                            match3 = COMMAND_MINS.match(tail)
                            
                            if match3:
                                mins, tail = match3.groups()
                                mins = int(mins)
                                if MIN_MINUTES<= mins <= MAX_MINUTES:
                                    decision = Decision(p_id, response, mins, tail)
                                    decisions[p_id] = decision
                                    # print("edited decision")
                                else: 
                                    errors.append(f"Suggested meeting time was \"{mins}mins\". Must be between {MIN_MINUTES} and {MAX_MINUTES} minutes.")
                                    continue
                            else:
                                errors.append("edit must include a minutes adjustment amount")
                                continue
                else:
                    errors.append("invalid response type. use 'accept', 'reject', or 'edit'")
                    continue
        else: 
            continue
        
    
    return ParseResult(list(decisions.values()),errors)
