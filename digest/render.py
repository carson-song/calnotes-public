"""Turn a planner result into an email digest. Runs locally, after the trust boundary.

The planner only ever saw handles and [PERSON_n] placeholders. Here we map them back with the vault so
the digest reads like your own notes. That makes the digest the most sensitive thing the pipeline
produces after the raw calendar, so two rules:

  1. Fail closed: if anything is still a placeholder or handle after mapping back, refuse to build it.
  2. It goes only to the one recipient you configured (see digest/send.py).
"""
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from boundary.vault import HANDLE, PLACEHOLDER

GOAL_SHORT = {"G1": "job search", "G2": "build-out", "G3": "furniture"}

# Email styling: inline styles and tables only (Gmail strips <style> and most layout CSS). Mid-tone colours
# survive Gmail's dark-mode inversion. Goal colours: (text, background).
GOAL_COLOR = {"G1": ("#1d4ed8", "#e8efff"), "G2": ("#047857", "#e3f6ee"), "G3": ("#b45309", "#fdf0dc")}
INK, MUTED, LINE, CARD, BG = "#1f2328", "#5b636e", "#e3e6ea", "#ffffff", "#f4f5f7"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,Menlo,Consolas,monospace"
REPLY_HELP = (
    "To approve, reply with one line per block:\n"
    "  p1 accept          (put it on your calendar)\n"
    "  p2 edit 60          (keep the block, change its length in minutes)\n"
    "  p3 reject later 7d  (not now: propose it again in 7 days; plain 'later' = 3 days)\n"
    "  p4 reject done      (already did it: stop proposing it)\n"
    "  p5 reject drop      (not doing it: stop proposing it)\n"
    "Any other reject reason is kept as a note, and the item comes back in the next digest.\n"
    "Blocks you don't mention stay off your calendar."
)


class DigestError(Exception):
    """The digest isn't safe or complete enough to send."""


@dataclass
class Block:
    proposal_id: str
    item_id: str
    title: str                       # what to do: the next action if there is one, else the note
    source: str                      # the note it came from ("" when title is the note itself)
    start: str
    minutes: int
    goals: list
    reason: str

    @property
    def when(self) -> str:
        s = datetime.fromisoformat(self.start)
        e = s + timedelta(minutes=self.minutes)
        return f"{s:%a %b} {s.day}, {s:%H:%M}–{e:%H:%M}"

    def day_and_span(self) -> tuple:
        """("Fri Oct 30", "9:00–9:45 AM"): 12-hour clock, AM/PM once unless the block crosses noon."""
        s = datetime.fromisoformat(self.start)
        e = s + timedelta(minutes=self.minutes)
        clock = lambda d: f"{d.hour % 12 or 12}:{d:%M}"
        first = clock(s) if s.strftime("%p") == e.strftime("%p") else f"{clock(s)} {s:%p}"
        return f"{s:%a %b} {s.day}", f"{first}–{clock(e)} {e:%p}"


@dataclass
class Digest:
    digest_id: str
    subject: str
    blocks: list
    notes: str                       # the planner's explanation, mapped back
    run: dict = field(default_factory=dict)

    def text(self) -> str:
        lines = [self._headline(), ""]
        for b in self.blocks:
            goals = ", ".join(f"{g} {GOAL_SHORT.get(g, '')}".strip() for g in b.goals) or "no goal"
            lines += [f"{b.proposal_id}  {b.when}  ({b.minutes} min)  [{goals}]"]
            lines += _indent(b.title, "    ")
            lines += _indent(b.source, "    from: ", "          ") if b.source else []
            lines += [f"    Why: {b.reason}", ""]
        lines += [REPLY_HELP, "", "— Planner's notes —", self.notes or "(none)", "", "— Run —"]
        lines += [f"{k}: {v}" for k, v in self.run.items()]
        return "\n".join(lines) + "\n"

    def html(self) -> str:
        e = html.escape
        total = sum(b.minutes for b in self.blocks)
        minutes_by_goal = {}
        for b in self.blocks:
            for g in b.goals:
                minutes_by_goal[g] = minutes_by_goal.get(g, 0) + b.minutes
        summary = "".join(
            f"<span style='display:inline-block;white-space:nowrap;margin:0 8px 4px 0'>{_chip(g)}"
            f"<span style='font-size:12px;color:{MUTED}'> {m} min</span></span>" for g, m in minutes_by_goal.items())
        title = (f"{len(self.blocks)} block{'s' * (len(self.blocks) != 1)} proposed · {total // 60}h {total % 60:02d}m"
                 if self.blocks else "No blocks this time")
        sub = ("Nothing is on your calendar until you reply." if self.blocks
               else "The planner proposed no blocks. Its notes are below.")
        help_rows = "".join(
            f"<tr><td style='padding:3px 12px 3px 0;font-family:{MONO};font-size:13px;color:{INK};"
            f"white-space:nowrap'>{e(cmd)}</td><td style='padding:3px 0;font-size:13px;color:{MUTED}'>{e(meaning)}</td></tr>"
            for cmd, meaning in _help_commands())
        notes = "".join(f"<p style='margin:0 0 8px'>{_lines(p)}</p>" for p in self.notes.split("\n\n") if p.strip())
        run = " · ".join(f"{e(str(k))}: {e(str(v))}" for k, v in self.run.items())
        reply = "" if not self.blocks else (
            f"{_box_open(4)}<div style='font-size:15px;font-weight:700;margin-bottom:6px'>How to reply</div>"
            f"<div style='font-size:13px;color:{MUTED};margin-bottom:8px'>One line per block. "
            "Blocks you don't mention stay off your calendar.</div>"
            f"<table role='presentation' cellpadding='0' cellspacing='0'>{help_rows}</table>"
            f"<div style='font-size:13px;color:{MUTED};margin-top:8px'>Any other reject reason is kept as a note, "
            f"and the item comes back in the next digest.</div>{_BOX_CLOSE}")
        return (
            f"<div style='font-family:{FONT};color:{INK};background:{BG};padding:16px 12px'>"
            "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='max-width:600px;margin:0 auto'>"
            "<tr><td>"
            f"<div style='font-size:20px;font-weight:700;margin:4px 2px 2px'>{e(title)}</div>"
            f"<div style='font-size:14px;color:{MUTED};margin:0 2px 10px'>{e(sub)}</div>"
            f"<div style='margin:0 0 14px'>{summary}</div>"
            + "".join(_card(b) for b in self.blocks) + reply +
            f"<div style='font-size:15px;font-weight:700;margin:18px 2px 6px'>Planner's notes</div>"
            f"<div style='font-size:14px;line-height:1.5;color:{INK};margin:0 2px'>{notes or e('(none)')}</div>"
            f"<div style='font-size:11px;color:{MUTED};margin:18px 2px 0;border-top:1px solid {LINE};"
            f"padding-top:8px'>{run}</div>"
            "</td></tr></table></div>")

    def _headline(self) -> str:
        n = len(self.blocks)
        if n == 0:
            return "The planner proposed no blocks this time. Its notes are below."
        return f"{n} proposed block{'s' * (n != 1)}. Nothing is on your calendar until you approve it."


def build_digest(digest_id, result, vault, events, records, run_meta=None) -> Digest:
    """result: the planner's AgentResult. records: local labels by item id (for goal links)."""
    blocks = []
    for p in result.proposals:
        real = vault.reidentify(p)               # handle -> item id, [PERSON_n] -> name
        item_id = real["handle"]
        if item_id not in events:
            raise DigestError(f"{p['proposal_id']}: handle {p['handle']} doesn't map to a known item")
        rec = records.get(item_id, {})
        note = events[item_id]["title"].strip()         # in full: the digest is where you read it
        action = (rec.get("next_action") or "").strip()
        blocks.append(Block(p["proposal_id"], item_id, action or note, note if action else "", p["start"],
                            p["minutes"], list(rec.get("goal_links") or []), real["reason"]))
    notes = _plain(vault.reidentify(result.final_text or ""))

    leftovers = [f"{b.proposal_id}: {x}" for b in blocks for x in _unresolved(b.reason)]
    leftovers += [f"notes: {x}" for x in _unresolved(notes)]
    if leftovers:
        raise DigestError("unmapped placeholders or handles: " + "; ".join(leftovers))

    dates = sorted(b.start[:10] for b in blocks)
    span = f"{_day(dates[0])}–{_day(dates[-1])}" if dates else "no blocks"
    subject = f"Plan for {span}: {len(blocks)} block{'s' * (len(blocks) != 1)} [{digest_id}]"
    return Digest(digest_id, subject, blocks, notes, dict(run_meta or {}))


def _unresolved(s: str) -> list:
    return [m.group(0) for m in PLACEHOLDER.finditer(s)] + HANDLE.findall(s)


_BOX_CLOSE = "</td></tr></table>"


def _box_open(top: int = 0) -> str:
    return (f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='background:{CARD};"
            f"border:1px solid {LINE};border-radius:10px;margin:{top}px 0 12px'><tr><td style='padding:14px 16px'>")


def _lines(t: str) -> str:
    """Escape, keeping the note's own line breaks."""
    return "<br>".join(html.escape(line) for line in t.strip().splitlines())


def _indent(t: str, first: str, rest: str | None = None) -> list:
    lines = t.strip().splitlines() or [""]
    rest = first if rest is None else rest
    return [first + lines[0]] + [rest + line for line in lines[1:]]


def _chip(g: str) -> str:
    fg, bg = GOAL_COLOR.get(g, (MUTED, "#eef0f2"))
    label = f"{g} · {GOAL_SHORT[g]}" if g in GOAL_SHORT else g
    return (f"<span style='display:inline-block;padding:2px 8px;border-radius:999px;background:{bg};color:{fg};"
            f"font-size:12px;font-weight:600'>{html.escape(label)}</span>")


def _card(b: Block) -> str:
    e = html.escape
    day, span = b.day_and_span()
    goals = " ".join(_chip(g) for g in b.goals) or _chip("no goal")
    source = (f"<tr><td colspan='2' style='padding:10px 0 0'><div style='font-size:12px;color:{MUTED};"
              "text-transform:uppercase;letter-spacing:.04em'>From your note</div>"
              f"<div style='margin-top:3px;padding:8px 10px;background:{BG};border-left:3px solid {LINE};"
              f"border-radius:4px;font-size:14px;line-height:1.45;color:{INK}'>{_lines(b.source)}</div></td></tr>"
              ) if b.source else ""
    return (
        _box_open() + "<table role='presentation' width='100%' cellpadding='0' cellspacing='0'>"
        f"<tr><td style='font-size:13px;color:{MUTED}'><span style='display:inline-block;padding:2px 7px;"
        f"border-radius:6px;background:{INK};color:#ffffff;font-weight:700;font-size:12px'>{e(b.proposal_id)}</span>"
        f"&nbsp;<b style='color:{INK}'>{e(day)}</b> · {e(span)} · {b.minutes} min</td>"
        f"<td align='right' style='white-space:nowrap;vertical-align:top'>{goals}</td></tr>"
        f"<tr><td colspan='2' style='padding-top:10px;font-size:16px;line-height:1.4;font-weight:600;color:{INK}'>"
        f"{_lines(b.title)}</td></tr>{source}"
        f"<tr><td colspan='2' style='padding-top:10px;font-size:13px;line-height:1.45;color:{MUTED}'>"
        f"<b style='color:{INK};font-weight:600'>Why:</b> {e(b.reason)}</td></tr>"
        "</table>" + _BOX_CLOSE)


def _help_commands() -> list:
    """(command, meaning) pairs from REPLY_HELP, so the email's table and the plain text can't drift apart."""
    out = []
    for line in REPLY_HELP.splitlines():
        if line.startswith("  p"):
            cmd, _, meaning = line.strip().partition("(")
            out.append((cmd.strip(), meaning.rstrip(")").strip()))
    return out


def _day(d: str) -> str:
    x = datetime.fromisoformat(d)
    return f"{x:%b} {x.day}"


def _plain(md: str) -> str:
    """The planner writes markdown; email clients show it raw. Strip the noisiest bits."""
    md = re.sub(r"\*\*(.+?)\*\*", r"\1", md)
    return md.strip()
