# Invented test data

`events_v0.jsonl`, `labels_v1.csv` and `split_v0.json` are a made-up twin of the real 46 labeled notes: same
ids, times, lengths, colours, label types, goals, confidence and questions-asked pattern, so every triage rule
takes the same path on each note (checked note by note when the twin was built). Every name, company, place
and word of note text is invented. Tests load this, never `data/`, so the suite runs without private data.
