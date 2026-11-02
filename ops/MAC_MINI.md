# Running calnotes 24/7 on a Mac mini

Goal: a digest every morning at 7:00 and approved blocks on the calendar within 15 minutes of a reply,
without your laptop. If anything stops, you hear about it.

```
launchd ──every 15 min──▶ scheduled.py replies ──▶ approve_run.py <digest> --write --from-gmail   (each recent digest)
        ──daily 07:00───▶ scheduled.py digest  ──▶ replies first, then digest_run.py --send --source live ...
                                    │
                                    └──▶ ping healthchecks.io (or /fail) ──▶ no ping in time? it emails you
```

## 0. One machine only
Only one machine runs the schedule. Two would each send a digest every morning and race on the same state.
Idempotency keys stop duplicate calendar events, but not duplicate digests or a split ledger. Don't install the
jobs on the laptop; if you already did: `launchctl bootout gui/$(id -u)/com.calnotes.digest` (and `.replies`).

## 1. Publish the Google app (stops the 7-day token expiry)
In Testing mode Google expires every sign-in after 7 days, which kills any schedule. In Google Cloud console →
Google Auth Platform (formerly "OAuth consent screen") → Audience → **Publish app**.

- You won't submit it for verification. An unverified app in production shows a "Google hasn't verified this
  app" screen at sign-in (Advanced → continue), and is capped at 100 users, which is fine for one.
- gmail.readonly is a restricted scope. Google's rules for unverified apps are aimed at apps with other users;
  check the console's messages when you publish. If it refuses, stay in Testing and re-sign in weekly
  (`python3 -m ops.signin`) until it's sorted: the healthcheck will tell you when a token lapses.
- After publishing, delete the old tokens (`rm secrets/token_*.json`) and sign in again (step 6): tokens issued
  in Testing keep their 7-day expiry.

## 2. Prepare the mini
- **Never sleep:** System Settings → Energy: prevent automatic sleeping, wake for network access,
  **start up automatically after a power failure**.
- **FileVault ON.** The mini holds your Google tokens and note history. The cost: after a power cut it waits at
  the login screen and nothing runs until you log in. That's the right trade: the healthcheck emails you.
- **Stay logged in.** The jobs are LaunchAgents: they run in your user session, where the Keychain is unlocked.
  Lock the screen instead of logging out.
- **Remote access** for maintenance: Screen Sharing (and Remote Login for ssh) under General → Sharing,
  your user only.

## 3. Install the tools
```bash
xcode-select --install                       # git
# Python 3.12, to match CI (your laptop runs 3.11): python.org installer or `brew install python@3.12`
# Ollama: install the app, set it to open at login, then:
ollama pull llama3.2:3b
```

## 4. Code
```bash
git clone git@github.com:<you>/calnotes.git ~/calnotes && cd ~/calnotes
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests       # same result as CI before going further
```

## 5. Private files (never through git)
Copy from the laptop by AirDrop or a USB stick: `secrets/google_client.json`, the whole `runs/` folder (your
digest states ARE the ledger: without them every note looks open again), and `vault/`. Then:
```bash
chmod 700 secrets && chmod 600 secrets/*
```

## 6. Keychain and sign-in
```bash
security add-generic-password -a "$USER" -s calnotes-anthropic -w      # prompts for the key; never in a file
export CALNOTES_DIGEST_TO=... CALNOTES_PLANS_ACCOUNT=... CALNOTES_NOTES_ACCOUNT=...
.venv/bin/python -m ops.signin                                          # 4 sign-ins, each names its account
.venv/bin/python -m ops.signin --check                                  # all four should say ok
```
The first scheduled run may trigger a macOS prompt to let python use the Keychain item: click **Always Allow**
(do this while you're at the mini, by running `.venv/bin/python scheduled.py digest` once by hand).

## 7. Healthchecks
Free account at healthchecks.io. Two checks:

| Check | Period | Grace |
|---|---|---|
| calnotes digest | 1 day | 1 hour |
| calnotes replies | 15 minutes | 30 minutes |

Copy each check's ping URL into `CALNOTES_HC_DIGEST` and `CALNOTES_HC_REPLIES`. Only the ping is sent, never
log text.

## 8. Install the schedule
```bash
export CALNOTES_HC_DIGEST=https://hc-ping.com/... CALNOTES_HC_REPLIES=https://hc-ping.com/...
ops/install_launchd.sh
launchctl kickstart -k gui/$(id -u)/com.calnotes.replies    # run it now instead of waiting 15 min
tail -f runs/logs/replies.log
```
Re-run `ops/install_launchd.sh` after changing any setting. It reinstalls both jobs.

## What can go wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| Healthcheck: digest down, mini looks fine | Ollama not running, or a token expired | `tail runs/logs/digest.log`; `python -m ops.signin --check` |
| Healthcheck: both down | Mini off, asleep, or at the FileVault login after a power cut | Log in; check Energy settings |
| Log says "needs a sign-in" | Token missing or revoked | `python -m ops.signin` at the mini |
| Digest arrives twice | Jobs installed on two machines | Step 0 |
| Replies not applied | Reply sent from a different account than CALNOTES_DIGEST_TO, or not sent from this account | The log lists ignored messages and why |
