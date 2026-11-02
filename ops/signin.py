"""Sign in every token once, by hand, on the machine that will run the schedule. Provided.

  python3 -m ops.signin            # creates any missing token; each opens a browser once
  python3 -m ops.signin --check    # no browser: says which tokens work and which need a sign-in

Run it after moving to a new machine, after publishing the Google app, or when a scheduled run says a token
expired. Each token has its own account and scope (least privilege), so each prompt says which account to pick.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    check = "--check" in sys.argv
    if check:
        os.environ["CALNOTES_HEADLESS"] = "1"
    plans = os.environ.get("CALNOTES_PLANS_ACCOUNT", "the plans account")
    notes = os.environ.get("CALNOTES_NOTES_ACCOUNT", "the notes account")
    me = os.environ.get("CALNOTES_DIGEST_TO", "")
    # The sandbox mailbox sends the digest and reads your replies; the digest goes TO your real address.
    # Reading needs a scope that sees the whole mailbox, so it must never be your real inbox.
    mail = os.environ.get("CALNOTES_MAIL_ACCOUNT") or os.environ.get("CALNOTES_NOTES_ACCOUNT", "the sandbox account")

    def notes_cal():
        from approve.accounts import notes_calendar
        return f"signed in as {notes_calendar().account}"

    def plans_cal():
        from approve.accounts import plans_calendar
        return f"signed in as {plans_calendar().account}"

    def gmail_send():
        import gauth
        from digest.send import SCOPES
        gauth.service("gmail", "v1", SCOPES, "token_gmail.json")
        return "ok (the send-only scope can't report its account: make sure you picked the right one)"

    def gmail_read():
        from approve.inbox import GmailInbox
        who = GmailInbox().api.users().getProfile(userId="me").execute()["emailAddress"]
        if who.lower() == me.lower():
            raise SystemExit(
                f"signed in as {who}, which is also CALNOTES_DIGEST_TO. The digest should go to your real inbox and be "
                f"read from the sandbox, so these must differ. Either CALNOTES_DIGEST_TO is wrong (check it first: "
                f"echo $CALNOTES_DIGEST_TO), or this token is on your real inbox: then delete "
                f"secrets/token_gmail_read.json and sign in as {mail}.")
        return f"signed in as {who}"

    steps = [("notes calendar, read-only", notes, notes_cal), ("plans calendar", plans, plans_cal),
             ("Gmail, send", mail, gmail_send), ("Gmail, read replies", mail, gmail_read)]
    failed = 0
    for what, account, fn in steps:
        if not check:
            print(f"\n{what}: if a browser opens, pick {account}")
        try:
            print(f"  {what}: {fn()}")
        except SystemExit as e:
            failed += 1
            print(f"  {what}: NEEDS ATTENTION: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
