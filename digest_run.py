"""Plan, then email yourself the proposed blocks.

  python3 digest_run.py                     # dry run: writes runs/digest/<id>.eml/.txt/.json, sends nothing
  export CALNOTES_DIGEST_TO=you@sandbox     # the ONE address digests may go to
  python3 digest_run.py --send              # same, then sends it through the Gmail API

Pipeline: raw calendar -> triage -> egress gate -> planner (frontier) -> vault.reidentify (local)
          -> digest -> Gmail. The frontier model never sees the digest; Google does (it already
          holds the calendar). See boundary/CONTRACT.md, "Outbound: the digest".
"""
import argparse
import os
import time

from digest.render import DigestError, build_digest
from digest.send import FileSender, GmailSender, build_message, recipient, save_state
from plan_demo import ROOT, add_args, run_planner

OUT = ROOT / "runs" / "digest"


def run_meta(run, a=None) -> dict:
    """Shown at the bottom of the digest and saved with its state. "model" is the PLANNER (frontier) model; the
    key name stays "model" because the eval log reads it. "triage" is the local model that labeled the notes."""
    words = sum(len(str(r.get(k, "")).split()) for r in run.batch.records for k in ("next_action", "text"))
    r = run.result
    return {
        "model": run.model,
        **({"triage": a.local_model if a.labeler == "ollama" else a.labeler,
            "source": getattr(a, "source", "snapshot")} if a else {}),
        "privacy level": run.batch.level,
        "words sent to the model": words, "records dropped at the boundary": len(run.batch.dropped),
        "model calls": f"{r.steps} ({r.stop_reason})",
        "tokens": f"{r.usage['input_tokens']:,} in / {r.usage['output_tokens']:,} out",
        "trace": run.trace.name,
    }


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    ap.add_argument("--send", action="store_true", help="send through Gmail (default: dry run)")
    a = ap.parse_args()
    to = recipient() if a.send else os.environ.get("CALNOTES_DIGEST_TO", "dry-run@localhost")

    run = run_planner(a)
    digest_id = f"cn-{time.strftime('%Y%m%d-%H%M')}"
    try:
        digest = build_digest(digest_id, run.result, run.vault, run.events, run.records, run_meta(run, a))
    except DigestError as e:
        raise SystemExit(f"Not sending: {e}")

    msg = build_message(digest, to)
    FileSender(OUT).send(msg, digest_id)          # always keep a local copy
    delivered = GmailSender().send(msg, digest_id) if a.send else "dry run"
    state = save_state(digest, to, delivered, OUT)

    print(digest.text())
    print(f"{'sent to ' + to if a.send else 'dry run, not sent'} · {delivered}")
    print(f"local copy: {OUT / (digest_id + '.eml')} · state: {state}")


if __name__ == "__main__":
    main()
