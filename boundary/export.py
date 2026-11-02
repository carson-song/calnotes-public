"""The egress gate: the ONLY way data leaves for the frontier model.

  batch = export_batch(records, items, vault, level=1)
  frontier_client.send(batch)     # the client accepts EgressBatch objects only

Steps per record: sanitize by the allowlist -> check -> drop on any violation (fail closed).
Every batch, and every drop, is written to a local audit log.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from boundary import check
from boundary import policy as P


@dataclass(frozen=True)
class EgressBatch:
    level: int
    records: tuple
    dropped: tuple = field(default=())  # (handle, reasons) — stays local, never sent
    overlap: int = 0                     # records whose text shares a 3-word run with the raw title


def sanitize(rec: dict, item: dict, vault, level: int, extra_names=()) -> dict:
    t = rec["type"]
    out = {
        "handle": vault.handle(rec["id"]),
        "type": t,
        "date": item["start"][:10],
        "goal_links": list(rec.get("goal_links") or []),
        "confidence": rec.get("confidence", "medium"),
        "pending_clarification": bool(rec.get("needs_clarification")) or rec.get("detect_verdict") == "unsure",
    }
    if t == "event":
        out["start"], out["end"] = item["start"], item["end"]
    if t == "musing":
        out["musing_theme"] = rec.get("musing_theme")
    if t in P.NEVER_TEXT or t not in P.ACTIONABLE:
        return out

    people = [p for p in (rec.get("people") or []) if p.strip().lower() not in P.GROUP_WORDS]
    orgs = [rec["company"]] if rec.get("company") else []
    out["has_next_action"] = bool(rec.get("next_action"))
    out["people_count"] = len(people)
    names = people + list(extra_names)

    if level >= 1:
        out["people"] = [vault.person(p) for p in people]
        out["org"] = vault.org(orgs[0]) if orgs else None
        if rec.get("next_action"):
            out["next_action"] = vault.pseudonymize(rec["next_action"], names, orgs)
    if level >= 2 and t in P.TEXT_AT_LEVEL_2:
        out["text"] = vault.pseudonymize(rec.get("normalized_text") or "", names, orgs)
    return out


def export_batch(records, items, vault, level=P.DEFAULT_LEVEL, extra_names=(), canaries=(), audit_dir=None):
    if level not in P.LEVELS:
        raise ValueError(f"unknown level {level}")
    sent, dropped, overlap = [], [], 0
    for rec in records:
        item = items[rec["id"]]
        s = sanitize(rec, item, vault, level, extra_names)
        problems = check.violations(s, item, vault.real_names(), canaries)
        if problems:
            dropped.append((s["handle"], tuple(problems)))
            continue
        overlap += check.verbatim_overlap(s, item)
        sent.append(s)
    vault.save()
    batch = EgressBatch(level, tuple(sent), tuple(dropped), overlap)
    if audit_dir:
        _audit(batch, Path(audit_dir))
    return batch


def _audit(batch: EgressBatch, audit_dir: Path):
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_L{batch.level}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in batch.records:
            f.write(json.dumps({"sent": r}, ensure_ascii=False) + "\n")
        for h, reasons in batch.dropped:
            f.write(json.dumps({"dropped": h, "reasons": list(reasons)}) + "\n")
