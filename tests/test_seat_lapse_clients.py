"""The advisor agreement's promise to a lapsed advisor's clients (section 6):
while billing is on (flag `billing` + gate L1a) and an advisor's seat is past
its grace or paused (billing.tools_paused - the same rule as billing.state's
"open", read only), each of their clients, signed in as themselves, sees one
plain line (billing.CLIENT_PAUSED_LINE) where the advisor's next step shows,
and nothing that has them wait for the advisor. No email.

- billing off: never paused, whatever the seat row says;
- a live seat, a seat in its grace, an advisor never seen (no row): not paused,
  and nothing is written;
- past grace: paused for every linked client; a manual seat past its
  paid-through day and grace too; restored: gone;
- the words: no figures, no reason, nothing about price or the seat;
- the client's Home (with and without holdings) and Your advisor in the app;
  never the advisor in the client's account.

    python -m unittest tests.test_seat_lapse_clients        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import advising  # noqa: E402
import auth  # noqa: E402
import billing  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
SETTING_NAMES = ("NORTHWEND_FLAGS", "NORTHWEND_GATES", "STRIPE_SECRET_KEY",
                 "STRIPE_PRICE_MONTHLY", "STRIPE_PRICE_YEARLY", "NORTHWEND_SEAT_GRACE_DAYS")


@contextlib.contextmanager
def _settings(**values):
    """Only these settings (none from the real environment, secrets or .env)."""
    env = {k: v for k, v in os.environ.items() if k not in SETTING_NAMES}
    env.update(values)
    with unittest.mock.patch.dict(os.environ, env, clear=True), \
            unittest.mock.patch("flags._secret", lambda name: None), \
            unittest.mock.patch("settings.load_env", lambda *a, **k: {}):
        yield


def _on():
    return _settings(NORTHWEND_FLAGS="billing", NORTHWEND_GATES="L1a",
                     NORTHWEND_SEAT_GRACE_DAYS="14")


def _stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class PausedTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_seatlapse_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.c = portfolio.connect(os.path.join(self.dir, "s.db"))
        self.addCleanup(self.c.close)
        self.carol = auth.create_user(self.c, "carol", PW)
        auth.set_advisor(self.c, "carol", True)
        self.dana = auth.create_user(self.c, "dana", PW)
        self.eli = auth.create_user(self.c, "eli", PW)
        for client in (self.dana, self.eli):
            auth.link_client(self.c, self.carol, client)
        self.nina = auth.create_user(self.c, "nina", PW)   # no advisor
        self.c.commit()

    def _row(self, status, grace, *, started=True):
        self.c.execute("DELETE FROM seats")
        self.c.execute("INSERT INTO seats (user_id, status, founding, grace_until, started_at, "
                       "created_at) VALUES (?, ?, 0, ?, ?, ?)",
                       (self.carol, status, grace and _stamp(grace),
                        _stamp(NOW - timedelta(days=200)) if started else None,
                        _stamp(NOW - timedelta(days=200))))
        self.c.commit()

    def _paused(self, client, now=NOW):
        return advising.advisor_tools_paused(self.c, client, now=now)

    def _seats(self):
        return self.c.execute("SELECT COUNT(*) AS n FROM seats").fetchone()["n"]

    def test_billing_off_nothing(self):
        self._row("canceled", NOW - timedelta(days=100))
        for flags_value, gates in (("", "L1a"), ("billing", ""), ("billing", "L1b")):
            with self.subTest(flags=flags_value, gates=gates), \
                    _settings(NORTHWEND_FLAGS=flags_value, NORTHWEND_GATES=gates):
                self.assertFalse(billing.tools_paused(self.c, self.carol, now=NOW))
                self.assertFalse(self._paused(self.dana))

    def test_never_seen_active_and_in_grace_nothing_and_nothing_written(self):
        with _on():
            self.assertFalse(self._paused(self.dana))          # no seat row yet
            self.assertEqual(self._seats(), 0)                  # and none made
            self._row("active", None)
            self.assertFalse(self._paused(self.dana, NOW + timedelta(days=400)))
            self._row("past_due", None)
            self.assertFalse(self._paused(self.dana))
            self._row("none", NOW + timedelta(days=3), started=False)   # new or beta advisor
            self.assertFalse(self._paused(self.dana))
            self._row("canceled", NOW + timedelta(days=1))      # ended, in its grace
            self.assertFalse(self._paused(self.dana))
            self.assertFalse(self._paused(self.nina))           # no advisor at all

    def test_past_grace_every_linked_client(self):
        with _on():
            self._row("canceled", NOW - timedelta(days=1))
            self.assertTrue(self._paused(self.dana))
            self.assertTrue(self._paused(self.eli))
            self.assertFalse(self._paused(self.nina))
            self._row("none", NOW - timedelta(days=1), started=False)   # never subscribed
            self.assertTrue(self._paused(self.dana))

    def test_same_rule_as_the_advisors_own_state(self):
        with _on():
            for status, grace in (("canceled", NOW - timedelta(days=1)),
                                  ("canceled", NOW + timedelta(days=1)),
                                  ("active", None), ("none", NOW - timedelta(days=2))):
                self._row(status, grace)
                st = billing.state(self.c, self.carol, now=NOW)
                self.assertEqual(billing.tools_paused(self.c, self.carol, now=NOW),
                                 not st["open"], status)

    def test_a_manual_seat_ended_past_its_date(self):
        with _on():
            billing.set_manual(self.c, self.carol, active=True, paid_through="2026-10-31",
                               now=NOW)
            self.assertFalse(self._paused(self.dana))
            day_after = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
            self.assertFalse(self._paused(self.dana, day_after))          # in its grace
            later = day_after + timedelta(days=20)
            # before the nightly job marks it ended, and after
            self.assertTrue(self._paused(self.dana, later))
            self.assertEqual(billing.end_manual(self.c, now=later), 1)
            self.assertTrue(self._paused(self.dana, later))
            self.assertTrue(self._paused(self.eli, later))
            # set by hand again: gone
            billing.set_manual(self.c, self.carol, active=True, paid_through="2027-01-31",
                               now=later)
            self.assertFalse(self._paused(self.dana, later))

    def test_restored_the_line_goes(self):
        with _on():
            self._row("canceled", NOW - timedelta(days=1))
            self.assertTrue(self._paused(self.dana))
            sub = {"id": "sub_c", "object": "subscription", "status": "active",
                   "customer": "cus_c", "start_date": int(NOW.timestamp()),
                   "metadata": {"northwend_user": str(self.carol)},
                   "items": {"data": [{"price": {"id": "p", "recurring": {"interval": "month"}},
                                       "current_period_end": int(NOW.timestamp()) + 2600000}]}}
            billing.apply(self.c, self.carol, sub, now=NOW)
            self.assertFalse(self._paused(self.dana))
            self.assertFalse(self._paused(self.eli))

    def test_the_words(self):
        line = billing.CLIENT_PAUSED_LINE
        self.assertFalse(re.search(r"\d|\$|%", line), line)
        for word in ("price", "pay", "paid", "bill", "seat", "grace", "subscri", "card",
                     "stripe", "lapse", "cancel", "fee", "cost"):
            self.assertNotIn(word, line.lower(), word)
        self.assertIn("stay yours", line)


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_seatlapse_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)     # nothing brought in yet
            cls.eli = auth.create_user(c, "eli", PW)       # with holdings
            for client in (cls.dana, cls.eli):
                auth.link_client(c, cls.carol, client)
            sample_data.load(c, cls.eli)
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _seat(self, status, grace):
        c = portfolio.connect(self.db)
        try:
            c.execute("DELETE FROM seats")
            c.execute("INSERT INTO seats (user_id, status, founding, grace_until, started_at, "
                      "created_at) VALUES (?, ?, 0, ?, ?, ?)",
                      (self.carol, status, grace, "2026-01-01T00:00:00Z",
                       "2026-01-01T00:00:00Z"))
            c.commit()
        finally:
            c.close()

    def _run(self, uid, name, page="Dashboard", flags="billing", gates="L1a", **state):
        from streamlit.testing.v1 import AppTest
        import yfinance

        def offline(*a, **k):
            raise RuntimeError("offline in tests")

        def no_net(*a, **k):
            raise urllib.error.URLError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "RESEND_API_KEY")
               + SETTING_NAMES}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flags, NORTHWEND_GATES=gates)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("urllib.request.urlopen", no_net), \
                unittest.mock.patch("settings.load_env", lambda *a, **k: {}), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown] + [h.proto.body for h in at.get("html")]
        for kind in ("success", "info", "warning", "error", "caption"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    @staticmethod
    def _keys(at):
        return [b.key for b in at.button if b.key]

    def test_the_clients_home_while_paused(self):
        self._seat("canceled", "2026-01-02T00:00:00Z")
        for uid, name in ((self.dana, "dana"), (self.eli, "eli")):
            with self.subTest(client=name):
                at = self._run(uid, name)
                text = self._text(at)
                self.assertEqual(text.count(billing.CLIENT_PAUSED_LINE), 1)
                self.assertNotIn("route_go", self._keys(at))    # no step that waits on them
                self.assertNotIn("Your next step, with your advisor", text)
                self.assertNotIn("Your advisor sets your goal with you", text)
                self.assertNotIn(billing.CLOSED_LINE, text)     # never the advisor's words
                # Your advisor: the same line under their card
                at = self._run(uid, name, "Advisor notes")
                self.assertIn(billing.CLIENT_PAUSED_LINE, self._text(at))

    def test_off_live_or_in_grace_the_home_is_as_before(self):
        cases = (("canceled", "2026-01-02T00:00:00Z", "", "L1a"),        # billing off
                 ("canceled", "2026-01-02T00:00:00Z", "billing", "L0"),  # gate off
                 ("active", None, "billing", "L1a"),
                 ("canceled", "2099-01-01T00:00:00Z", "billing", "L1a"))  # in its grace
        for status, grace, flags_value, gates in cases:
            self._seat(status, grace)
            for uid, name in ((self.dana, "dana"), (self.eli, "eli")):
                with self.subTest(status=status, grace=grace, flags=flags_value, client=name):
                    at = self._run(uid, name, flags=flags_value, gates=gates)
                    text = self._text(at)
                    self.assertNotIn(billing.CLIENT_PAUSED_LINE, text)
                    self.assertIn("route_go", self._keys(at))
                    self.assertIn("Your next step, with your advisor", text)

    def test_never_shown_to_the_advisor(self):
        self._seat("canceled", "2026-01-02T00:00:00Z")
        for page, client in (("Dashboard", self.dana), ("Dashboard", self.eli),
                             ("Advisor notes", self.eli), ("Clients", self.carol)):
            with self.subTest(page=page, client=client):
                at = self._run(self.carol, "carol", page, two_step_ok=self.carol_ok,
                               active_user_id=client)
                self.assertNotIn(billing.CLIENT_PAUSED_LINE, self._text(at))


if __name__ == "__main__":
    unittest.main()
