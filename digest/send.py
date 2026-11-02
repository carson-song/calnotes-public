"""Deliver a digest. Two senders with the same interface:

  FileSender   dry run: writes .eml + .txt to runs/digest/ (default; nothing leaves your machine)
  GmailSender  sends through the Gmail API with the narrowest scope (gmail.send: can't read your mail)

The recipient comes from one place only, the CALNOTES_DIGEST_TO environment variable, and the
sender refuses to run without it. A digest holds your real notes, so a typo'd address is the one
mistake here you can't take back.
"""
import base64
import json
import os
from email.message import EmailMessage
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def recipient() -> str:
    to = os.environ.get("CALNOTES_DIGEST_TO", "").strip()
    if not to or "@" not in to or "," in to:
        raise SystemExit("Set CALNOTES_DIGEST_TO to exactly one address (use the sandbox account).")
    return to


def build_message(digest, to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = to                     # a note to yourself
    msg["Subject"] = digest.subject
    msg["X-Calnotes-Digest"] = digest.digest_id   # lets the reply reader match replies later
    msg.set_content(digest.text())
    msg.add_alternative(digest.html(), subtype="html")
    return msg


class FileSender:
    def __init__(self, out_dir: Path):
        self.out_dir = Path(out_dir)

    def send(self, msg: EmailMessage, digest_id: str) -> str:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        eml = self.out_dir / f"{digest_id}.eml"
        eml.write_bytes(bytes(msg))
        txt = msg.get_body(("plain",)).get_content()
        (self.out_dir / f"{digest_id}.txt").write_text(txt, encoding="utf-8")
        return str(eml)


class GmailSender:
    """First run opens a browser to sign in; the token is cached in secrets/ (git-ignored)."""

    def __init__(self):
        self._service = None

    def send(self, msg: EmailMessage, digest_id: str) -> str:
        if self._service is None:
            import gauth
            self._service = gauth.service("gmail", "v1", SCOPES, "token_gmail.json")
        raw = base64.urlsafe_b64encode(bytes(msg)).decode()
        sent = self._service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"gmail message {sent['id']}"


def save_state(digest, to: str, delivered: str, out_dir: Path) -> Path:
    """What was proposed, by real item id: the reply reader (next step) applies approvals from this."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{digest.digest_id}.json"
    state = {
        "digest_id": digest.digest_id, "to": to, "delivered": delivered, "run": digest.run,
        "blocks": [{**vars(b), "proposed_minutes": b.minutes, "status": "proposed", "decision": None,
                    "attempts": 0, "event_id": None} for b in digest.blocks],
    }
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
