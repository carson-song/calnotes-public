"""What the Mac mini runs on a schedule. Provided (ops glue).

  python3 scheduled.py replies    # every 15 min: read replies to recent digests, write approved blocks
  python3 scheduled.py digest     # 7:00 daily: replies first (so the ledger is current), then a new digest

Each step is a separate process (approve_run.py, digest_run.py), so one failing digest can't take the others down,
and each one is exactly the command you'd run by hand. Rules this follows:

- One run at a time: a lock file. A slow digest run can't overlap the next replies run.
- Never a browser: CALNOTES_HEADLESS=1, so an expired sign-in stops with a message instead of hanging.
- A ping to a dead man's switch (healthchecks.io) after every run, /fail on failure. If the mini is off, asleep or
  stuck at the FileVault login after a power cut, no ping arrives and the service emails you. Only the ping is
  sent, never the log: the log can hold note titles.
- The API key comes from the macOS Keychain, never a file.
"""
import fcntl
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from ingest.ledger import digest_date
from ingest.source import load_states

ROOT = Path(__file__).resolve().parent
DIGEST_DIR = ROOT / "runs" / "digest"
LOCK = ROOT / "runs" / ".scheduled.lock"
REPLY_WINDOW_DAYS = 3        # digests older than this have no live proposals left
DIGEST_ARGS = os.environ.get("CALNOTES_DIGEST_ARGS",
                             "--send --source live --labeler ollama --calendar live --level 2 --local-model qwen2.5:7b").split()


def log(msg: str):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def needs_attention(state: dict, today: date) -> bool:
    """A digest is worth checking for replies while it's recent, was really sent, and still has open blocks."""
    return (state.get("delivered", "").startswith("gmail message")
            and digest_date(state["digest_id"]) >= today - timedelta(days=REPLY_WINDOW_DAYS)
            and any(b["status"] in ("proposed", "approved") for b in state["blocks"]))


def api_key_from_keychain():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    r = subprocess.run(["security", "find-generic-password", "-s", "calnotes-anthropic", "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("No API key: add it with  security add-generic-password -a \"$USER\" -s calnotes-anthropic -w")
    os.environ["ANTHROPIC_API_KEY"] = r.stdout.strip()


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def step(args: list, timeout: int) -> bool:
    log("$ " + " ".join(args))
    try:
        r = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"  timed out after {timeout}s")
        return False
    for line in (r.stdout + r.stderr).strip().splitlines():
        log("  " + line)
    if r.returncode != 0:
        log(f"  exit {r.returncode}")
    return r.returncode == 0


def run_replies() -> bool:
    ok = True
    pending = [s for s in load_states(DIGEST_DIR) if needs_attention(s, date.today())]
    if not pending:
        log("no digests waiting on replies")
    for s in pending:
        ok &= step(["approve_run.py", str(DIGEST_DIR / f"{s['digest_id']}.json"), "--write", "--from-gmail"], 300)
    return ok


def run_digest() -> bool:
    ok = run_replies()
    if not ollama_up():
        log("Ollama isn't running on localhost:11434: no digest today")
        return False
    api_key_from_keychain()
    return step(["digest_run.py", *DIGEST_ARGS], 1800) and ok


def ping(ok: bool, job: str):
    url = os.environ.get(f"CALNOTES_HC_{job.upper()}")
    if not url:
        return
    try:
        urllib.request.urlopen(url + ("" if ok else "/fail"), timeout=10).close()
    except OSError as e:
        log(f"healthcheck ping failed: {e}")


def main():
    job = sys.argv[1] if len(sys.argv) > 1 else ""
    if job not in ("replies", "digest"):
        raise SystemExit(__doc__)
    os.environ["CALNOTES_HEADLESS"] = "1"
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log(f"{job}: another run is in progress; skipping")
            return
        log(f"--- {job} ---")
        try:
            ok = run_digest() if job == "digest" else run_replies()
        except SystemExit as e:                       # a clear stop (sign-in, missing key): still a failure
            log(str(e))
            ok = False
        except Exception as e:                        # anything unexpected: log it, alert, exit non-zero
            log(f"crashed: {type(e).__name__}: {e}")
            ok = False
        log(f"--- {job}: {'ok' if ok else 'FAILED'} ---")
        ping(ok, job)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
