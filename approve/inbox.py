"""Read your replies to a digest from Gmail. Provided (transport, not part of the assignment).

How a reply is found, without guessing from subject lines:
  state["delivered"] holds the digest's Gmail message id  ->  its thread  ->  every message in that thread
  that is not the digest itself (no X-Calnotes-Digest header) and comes from CALNOTES_DIGEST_TO.

Scope: gmail.readonly, in its own token (secrets/token_gmail_read.json). It's the narrowest Gmail scope that
can read a message body, and it can read the whole mailbox, which is why this runs on the sandbox account.
Google treats it as a "restricted" scope: fine for your own app in testing mode, but publishing an app that
uses it needs Google's review.

Everything that touches the network is in GmailInbox; replies_in_thread() is pure and tested offline.
"""
import base64
import email
import re
from dataclasses import dataclass, field
from email import policy
from email.utils import parseaddr

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DELIVERED = re.compile(r"^gmail message (\S+)$")


@dataclass
class Reply:
    message_id: str      # Gmail's id, used to remember which replies were already applied
    sender: str
    date: str
    text: str            # the plain-text body, quoted history included (parse_reply stops at the quote)


@dataclass
class ThreadScan:
    replies: list = field(default_factory=list)
    ignored: list = field(default_factory=list)   # (message_id, why): shown to you, never applied


def digest_message_id(state: dict) -> str:
    m = DELIVERED.match(state.get("delivered", ""))
    if not m:
        raise SystemExit("This digest was never sent through Gmail (dry run?), so there's no thread to read.")
    return m.group(1)


def replies_in_thread(raw_messages, allowed_from: str) -> ThreadScan:
    """raw_messages: [(gmail_id, raw RFC 822 bytes)] in thread order."""
    scan = ThreadScan()
    for gid, raw in raw_messages:
        msg = email.message_from_bytes(raw, policy=policy.default)
        if msg["X-Calnotes-Digest"]:
            continue                                   # the digest itself
        sender = parseaddr(msg["From"] or "")[1].lower()
        if sender != allowed_from.strip().lower():
            scan.ignored.append((gid, f"from {sender or 'unknown'}, not {allowed_from}"))
            continue
        part = msg.get_body(preferencelist=("plain",))
        if part is None:
            scan.ignored.append((gid, "no plain-text part"))
            continue
        scan.replies.append(Reply(gid, sender, msg["Date"] or "", part.get_content()))
    return scan


class GmailInbox:
    """First use opens a browser to sign in (sandbox account); read-only token cached in secrets/."""

    def __init__(self):
        import gauth
        self.api = gauth.service("gmail", "v1", SCOPES, "token_gmail_read.json")

    def thread_messages(self, message_id: str):
        users = self.api.users()
        thread_id = users.messages().get(userId="me", id=message_id, format="minimal").execute()["threadId"]
        thread = users.threads().get(userId="me", id=thread_id, format="minimal").execute()
        out = []
        for m in thread.get("messages", []):                 # Gmail returns them oldest first
            raw = users.messages().get(userId="me", id=m["id"], format="raw").execute()["raw"]
            out.append((m["id"], base64.urlsafe_b64decode(raw.encode())))
        return out
