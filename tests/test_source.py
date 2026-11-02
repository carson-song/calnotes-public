"""Wiring for live notes: reading digest states, refusing the oracle. No network, no model."""
import json
import tempfile
import unittest
from pathlib import Path

from ingest.source import label_items, load_states


class TestSource(unittest.TestCase):
    def test_load_states_skips_files_that_are_not_digest_states(self):
        d = Path(tempfile.mkdtemp())
        (d / "cn-1.json").write_text(json.dumps({"digest_id": "cn-20261019-0700", "blocks": []}))
        (d / "broken.json").write_text("{not json")
        (d / "other.json").write_text(json.dumps({"something": "else"}))
        self.assertEqual([s["digest_id"] for s in load_states(d)], ["cn-20261019-0700"])

    def test_live_notes_cannot_use_the_oracle(self):
        with self.assertRaises(SystemExit):
            label_items([{"id": "g1", "title": "x", "start": "2026-10-19T09:00"}], "oracle", "m")

    def test_baseline_labels_live_notes(self):
        items = [{"id": "g1", "title": "text nico about the job lead", "start": "2026-10-19T09:00",
                  "end": "2026-10-19T10:00", "description": "", "location": "", "color_id": ""}]
        recs = label_items(items, "baseline", "unused")
        self.assertEqual(recs[0]["id"], "g1")


if __name__ == "__main__":
    unittest.main()
