# ingest: live notes

- `pull.py` (provided): reads the notes calendar for a window, normalizes each event to the shape triage
  reads, saves a snapshot to `data/live/` (gitignored: these are your real notes).
- `ledger.py` (yours): see SPEC.md.
- `source.py` (provided): pull → ledger → select → label with the local model.

Live notes never use the oracle labeler: there are no hand labels for them. The local model labels them,
using the hand-labeled dev notes in `data/` only as worked examples. Nothing here talks to the frontier model;
the planner still only sees the sanitized batch.
