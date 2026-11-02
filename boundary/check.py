"""Checks a sanitized record before it may leave. Any violation means the record is not sent."""
import re

from boundary import policy as P
from triage import schema as S

_WORD = re.compile(r"[a-z0-9']+")
_PH = re.compile(r"\[(?:PERSON|ORG)_\d+\]|\bh_[0-9a-f]{10}\b")


def words(s: str) -> list[str]:
    return _WORD.findall(_PH.sub(" ", s.lower()))


def ngrams(ws, n=3):
    return {" ".join(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def strings_in(rec: dict):
    for k, v in rec.items():
        if isinstance(v, str):
            yield k, v
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    yield k, x


def violations(rec: dict, item: dict, real_names, canaries=()) -> list[str]:
    out = []
    extra = set(rec) - P.ALLOWED_KEYS
    if extra:
        out.append(f"keys not allowed: {sorted(extra)}")
    if rec.get("type") not in S.TYPES:
        out.append(f"bad type {rec.get('type')!r}")
    if not set(rec.get("goal_links", [])) <= set(S.GOALS):
        out.append("bad goal_links")
    if rec.get("confidence") not in S.CONFIDENCE:
        out.append("bad confidence")
    if rec.get("musing_theme") not in S.THEMES + [None]:
        out.append("bad musing_theme")
    if rec.get("type") in P.NEVER_TEXT and set(rec) & (P.LEVEL_1_KEYS | P.LEVEL_2_KEYS):
        out.append(f"text fields on never-text type {rec['type']}")
    if not re.fullmatch(r"h_[0-9a-f]{10}", rec.get("handle", "")):
        out.append("missing or malformed handle")

    place_words = {w for w in words(item.get("location") or "") if len(w) >= 4 and not w.isdigit()}
    for key, s in strings_in(rec):
        if key in ("handle", "date", "start", "end", "type", "confidence", "musing_theme", "goal_links"):
            continue
        low = s.lower()
        for c in canaries:
            if c.lower() in low:
                out.append(f"canary {c!r} in {key}")
        for name in real_names:
            if re.search(rf"\b{re.escape(name)}\b", low):
                out.append(f"real name {name!r} in {key}")
        hit = place_words & set(words(s))
        if hit:
            out.append(f"location words {sorted(hit)} in {key}")
    return out


def verbatim_overlap(rec: dict, item: dict) -> bool:
    """Reported, not blocked: does any exported text share a 3-word run with the raw title?"""
    raw = ngrams(words(item["title"]))
    return any(raw & ngrams(words(s)) for k, s in strings_in(rec) if k in P.TEXT_KEYS)
