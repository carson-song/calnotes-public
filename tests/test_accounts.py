"""Two Google accounts: the right token, permission and account for each role, checked without network."""
import os
import sys
import types
import unittest
from unittest import mock

try:                                            # installed on your Mac; stubbed where it isn't
    import googleapiclient.errors  # noqa: F401
except ImportError:
    errors = types.ModuleType("googleapiclient.errors")
    errors.HttpError = type("HttpError", (Exception,), {})
    sys.modules["googleapiclient"] = types.ModuleType("googleapiclient")
    sys.modules["googleapiclient.errors"] = errors

import gauth
from approve import accounts
from approve.gcal import check_account


class FakeService:
    """Answers events().list(...).execute() with a calendar whose name is the signed-in account."""
    def __init__(self, summary):
        self.summary = summary

    def events(self):
        return self

    def list(self, **kw):
        return self

    def execute(self, num_retries=0):
        return {"summary": self.summary, "items": []}


def signed_in_as(summary, calls):
    def fake(api, version, scopes, token):
        calls.append((token, tuple(scopes)))
        return FakeService(summary)
    return fake


class TestCheckAccount(unittest.TestCase):
    def test_match_ignores_case_and_spaces(self):
        check_account(" Me@Example.com", "me@example.com", "plans")

    def test_wrong_account_stops_the_run(self):
        with self.assertRaises(SystemExit):
            check_account("notes@example.com", "me@example.com", "plans")

    def test_no_expected_account_stops_the_run(self):
        with self.assertRaises(SystemExit):
            check_account("me@example.com", "", "plans")


class TestRoles(unittest.TestCase):
    ENV = {"CALNOTES_PLANS_ACCOUNT": "plans@test", "CALNOTES_NOTES_ACCOUNT": "notes@test"}

    def test_plans_uses_its_own_token_with_write_permission(self):
        calls = []
        with mock.patch.dict(os.environ, self.ENV), mock.patch.object(gauth, "service", signed_in_as("plans@test", calls)):
            cal = accounts.plans_calendar()
        self.assertEqual(calls, [(accounts.PLANS_TOKEN, tuple(accounts.EVENTS_SCOPE))])
        self.assertEqual(cal.account, "plans@test")

    def test_notes_is_read_only_with_its_own_token(self):
        calls = []
        with mock.patch.dict(os.environ, self.ENV), mock.patch.object(gauth, "service", signed_in_as("notes@test", calls)):
            accounts.notes_calendar()
        self.assertEqual(calls, [(accounts.NOTES_TOKEN, tuple(accounts.READONLY_SCOPE))])
        self.assertNotEqual(accounts.NOTES_TOKEN, accounts.PLANS_TOKEN)

    def test_signing_in_with_the_notes_account_for_plans_is_refused(self):
        with mock.patch.dict(os.environ, self.ENV), \
                mock.patch.object(gauth, "service", signed_in_as("notes@test", [])), self.assertRaises(SystemExit):
            accounts.plans_calendar()

    def test_plans_without_a_configured_account_is_refused(self):
        env = {k: v for k, v in os.environ.items() if k != "CALNOTES_PLANS_ACCOUNT"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(gauth, "service", signed_in_as("plans@test", [])), self.assertRaises(SystemExit):
            accounts.plans_calendar()


if __name__ == "__main__":
    unittest.main()
