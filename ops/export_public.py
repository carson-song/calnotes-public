"""Build the public copy of this repo, refuse if anything private would leak. Provided.

  python3 ops/export_public.py ../calnotes-public           # builds, scans, tests; then you review and commit

The same design as the egress gate, applied to publishing:
  1. Allowlist. Only the paths in INCLUDE are copied. A new file is private until it's listed here.
  2. Swap. public/README.md and public/guide/ replace their private versions; data/ is filled from the invented
     dataset in tests/fixtures/. The real data/, runs/, vault/ and secrets/ are never read for copying.
  3. Scan, fail closed. Every exported text file is checked against terms taken from YOUR real data (people,
     companies, places, meeting-log names, account emails, 4-word runs of real note titles), plus anything in
     ops/private_terms.txt, plus secret-shaped strings. One hit and nothing is written to the target.
  4. Test. The full suite must pass in the exported tree, on the invented data alone.
Only then is the target folder updated (its .git is kept). Committing and pushing stay a human step.

False positives (a real name that's also an ordinary word in your code) go in ops/public_scan_allow.txt, one
term per line, after you've looked at the hit. Extra private terms go in ops/private_terms.txt. Neither file is
ever exported; keep private_terms.txt out of git too (it lists real names), via .gitignore.
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INCLUDE = [
    "approve", "boundary", "digest", "ingest", "planner", "triage", "tools", "tests", "ops",
    "run_eval.py", "plan_demo.py", "digest_run.py", "approve_run.py", "scheduled.py", "gauth.py",
    "requirements.txt", ".github/workflows", ".gitignore",
]
NEVER = {"__pycache__", ".DS_Store", "private_terms.txt", "public_scan_allow.txt", ".venv"}
SWAPS = {"public/README.md": "README.md", "public/guide/rules_v0.3.md": "guide/rules_v0.3.md"}
FIXTURE_DATA = ["events_v0.jsonl", "labels_v1.csv", "split_v0.json"]
TEXT_SUFFIXES = {".py", ".md", ".txt", ".csv", ".json", ".jsonl", ".html", ".yml", ".yaml", ".sh", ".plist", ".cfg",
                 ".toml", ".ini", ""}
SECRET_SHAPES = [r"sk-ant-[A-Za-z0-9_-]{10,}", r"AIza[0-9A-Za-z_-]{20,}", r'"refresh_token"\s*:', r'"client_secret"\s*:',
                 r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"ya29\.[0-9A-Za-z_-]{20,}"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
OK_EMAIL_DOMAINS = ("example.com", "example.org", "localhost", "github.com", "anthropic.com")   # + any *.test
STOP = {"the", "and", "for", "with", "from", "goals", "goal", "coffee", "lunch", "call", "drink", "show", "demo",
        "meeting", "art", "business", "social", "friends", "none", "null"}


def norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", s.lower()))


def private_terms() -> tuple[set, set]:
    """(words and phrases, 4-word title runs) taken from the real data. Missing files are skipped."""
    terms, shingles = set(), set()
    data = ROOT / "data"
    label_files = [data / "labels_v1.csv", data / "fresh" / "labels.csv"]
    event_files = [data / "events_v0.jsonl", data / "fresh" / "events.jsonl", *sorted((data / "live").glob("*.jsonl"))]
    for f in label_files:
        if not f.exists():
            continue
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            for field in ("people", "company"):
                for person in (r.get(field) or "").split(";"):
                    p = norm(person)
                    if p:
                        terms.add(p)
                        first = p.split()[0]
                        if len(first) >= 3:
                            terms.add(first)
            w = norm(r.get("title_raw") or "").split()
            shingles |= {" ".join(w[k:k + 4]) for k in range(len(w) - 3)}
    for f in event_files:
        if not f.exists():
            continue
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            e = json.loads(line)
            w = norm(e.get("title") or "").split()
            shingles |= {" ".join(w[k:k + 4]) for k in range(len(w) - 3)}
            if e.get("location"):
                terms.add(norm(e["location"]))
            m = re.search(r"with:\s*([^|<]+)", e.get("description") or "", re.I)
            for person in (m.group(1).split(",") if m else []):
                p = norm(person)
                if p:
                    terms.add(p)
                    if len(p.split()[0]) >= 3:
                        terms.add(p.split()[0])
    for k, v in os.environ.items():
        if k.startswith("CALNOTES_") and "@" in v:
            terms.add(v.strip().lower())
    extra = ROOT / "ops" / "private_terms.txt"
    if extra.exists():
        terms |= {norm(t) for t in extra.read_text().splitlines() if t.strip() and not t.startswith("#")}
    allow = ROOT / "ops" / "public_scan_allow.txt"
    allowed = {norm(t) for t in allow.read_text().splitlines()} if allow.exists() else set()
    terms = {t for t in terms if t and t not in STOP and t not in allowed and len(t) >= 3}
    return terms, shingles - allowed


def build(tmp: Path):
    for item in INCLUDE:
        src = ROOT / item
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, tmp / item, ignore=shutil.ignore_patterns(*NEVER), dirs_exist_ok=True)
        else:
            (tmp / item).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tmp / item)
    for src, dst in SWAPS.items():
        (tmp / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, tmp / dst)
    (tmp / "data").mkdir(exist_ok=True)
    for name in FIXTURE_DATA:
        shutil.copy2(ROOT / "tests" / "fixtures" / name, tmp / "data" / name)


def scan(tmp: Path, terms: set, shingles: set) -> list:
    hits = []
    word_res = [(t, re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])")) for t in sorted(terms)]
    for f in sorted(tmp.rglob("*")):
        if not f.is_file() or ".git" in f.parts:
            continue
        rel = f.relative_to(tmp)
        if f.suffix.lower() not in TEXT_SUFFIXES:
            hits.append((rel, "binary or unknown file type: add it deliberately or leave it out"))
            continue
        raw = f.read_text(encoding="utf-8", errors="replace")
        text = norm(raw)
        for t, rx in word_res:
            if rx.search(text):
                hits.append((rel, f"private term: {t!r}"))
        for s in shingles:
            if s in text:
                hits.append((rel, f"text from a real note: {s!r}"))
        for pat in SECRET_SHAPES:
            if re.search(pat, raw):
                hits.append((rel, f"secret-shaped string: /{pat}/"))
        for email in EMAIL.findall(raw):
            domain = email.lower().rsplit("@", 1)[1]
            if not (domain.endswith(OK_EMAIL_DOMAINS) or domain.endswith(".test")):
                hits.append((rel, f"email address: {email}"))
    return hits


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    target = Path(sys.argv[1]).expanduser().resolve()
    if ROOT == target or ROOT in target.parents:
        raise SystemExit("The target must be outside this repo (e.g. ../calnotes-public).")
    terms, shingles = private_terms()
    if not terms and not shingles:
        raise SystemExit("No real data found to derive private terms from: run this in the private repo.")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "export"
        tmp.mkdir()
        build(tmp)
        hits = scan(tmp, terms, shingles)
        if hits:
            print(f"NOT EXPORTED: {len(hits)} possible leak(s). Fix them in the private repo (or, for a false "
                  f"positive, add the term to ops/public_scan_allow.txt) and run again:")
            for rel, why in hits:
                print(f"  {rel}: {why}")
            sys.exit(1)
        print(f"scan clean: {sum(1 for f in tmp.rglob('*') if f.is_file())} files, {len(terms)} private terms, "
              f"{len(shingles)} note fragments checked")
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=tmp,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("NOT EXPORTED: the test suite fails on the invented data alone:\n" + r.stderr[-3000:])
            sys.exit(1)
        print("tests pass on the invented data: " + r.stderr.strip().splitlines()[-1])
        target.mkdir(parents=True, exist_ok=True)
        for old in target.iterdir():                    # replace everything except the public repo's history
            if old.name == ".git":
                continue
            shutil.rmtree(old) if old.is_dir() else old.unlink()
        for item in tmp.iterdir():
            dst = target / item.name
            shutil.copytree(item, dst) if item.is_dir() else shutil.copy2(item, dst)
    print(f"exported to {target}. Review with `git -C {target} status` and `git -C {target} diff`, then commit "
          f"and push yourself.")


if __name__ == "__main__":
    main()
