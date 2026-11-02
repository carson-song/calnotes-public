"""A fake backend that answers with the gold labels. It tests the plumbing, not a model:
run through the pipeline and eval, it must score 100% on everything the model controls."""
from triage import schema as S


class OracleBackend:
    def __init__(self, golds):
        self.golds = golds
        self.calls = 0

    def event_fields(self, item):
        self.calls += 1
        return S.to_event_output(self.golds[item["id"]])

    def category(self, item, mode):
        self.calls += 1
        return S.to_category_output(self.golds[item["id"]])  # an event gold yields category "event"

    def reflection(self, item):
        self.calls += 1
        return S.to_reflection_output(self.golds[item["id"]])
