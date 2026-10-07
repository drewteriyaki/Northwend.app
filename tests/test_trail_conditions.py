"""Trail Conditions (trail_conditions.py, flag `trail_conditions`): the
opt-in Monday email. Off by default, and turning it on keeps the time of
consent; the one-click link and the switch both stop it; calm almost every
week, with fixed lines only for a storm, a season begun, the walk waiting
and a readiness-map gap; never a figure, a ticker or an account name about
the person (a seeded account with holdings); once an ISO week; nothing at
all while the flag is off or the postal address is empty; the workflow job
with its own failure step; the Account switch in the app.

    python -m unittest tests.test_trail_conditions        (from the repo root)
"""

import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import auth  # noqa: E402
import checkin  # noqa: E402
import drills  # noqa: E402
import flags  # noqa: E402
import mailer  # noqa: E402
import manual_entry  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import seasons  # noqa: E402
import trail_conditions as tc  # noqa: E402
import unsubscribe  # noqa: E402

PW = "pw-123456789"
ADDRESS = "PO Box 1, Example, ST 00000"
MONDAY = date(2026, 9, 14)          # between seasons, ISO week 38
OCT_MONDAY = date(2026, 10, 5)      # the open-enrollment season, ISO week 41


@contextlib.contextmanager
def _flags(names=""):
    clean = {k: v for k, v in os.environ.items()
             if k not in (flags.FLAGS_SETTING, flags.GATES_SETTING)}
    clean[flags.FLAGS_SETTING] = names
    with unittest.mock.patch.dict(os.environ, clean, clear=True), \
            unittest.mock.patch.object(flags, "_secret", lambda name: None):
        yield


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_trail_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.sent = []

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _person(self, name, *, on=True, advisor=False, confirmed=True, extra=None):
        c = self.conn
        uid = auth.create_user(c, name, PW)
        if advisor:
            auth.set_advisor(c, name, True)
        c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                  (f"{name}@example.com", "2026-09-01T10:00:00Z" if confirmed else None, uid))
        c.commit()
        p = dict(extra or {})
        if on:
            tc.set_on(p, True, datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc))
        prefs.save(c, uid, p)
        return uid

    def _holdings(self, uid, *, drop):
        """VTI and BND in an account named "Rainy Day 4417", with daily closes
        for 60 days ending `drop` percent below their high."""
        meta, rows, totals, _ = manual_entry.build(
            [{"account": "Rainy Day 4417", "symbol": "VTI", "quantity": 37, "cost_basis": 8123.45,
              "asset_type": "Equity"},
             {"account": "Rainy Day 4417", "symbol": "BND", "quantity": 12, "cost_basis": 901.0,
              "asset_type": "Fixed Income"}],
            {"Rainy Day 4417": 55.0}, {"VTI": {"price": 300.0}, "BND": {"price": 70.0}},
            today=MONDAY - timedelta(days=70))
        portfolio.write_snapshot(self.conn, uid, meta, rows, totals, manual_entry.SOURCE)
        bars = []
        for i in range(60):
            d = (MONDAY - timedelta(days=60 - i)).isoformat()
            vti = 300.0 * (1 - drop / 100 * max(0, i - 40) / 19) if i > 40 else 300.0
            bars += [("VTI", d, vti), ("BND", d, 70.0)]
        self.conn.executemany("INSERT INTO daily_bars (ticker, date, close, volume) "
                              "VALUES (?, ?, ?, 1000)", bars)
        self.conn.commit()

    def _send(self, to, lines, link, unsub, address):
        self.sent.append({"to": to, "lines": list(lines), "link": link, "unsub": unsub,
                          "address": address})
        return True

    def _run(self, today=MONDAY, flag="trail_conditions", address=ADDRESS, **kw):
        with _flags(flag):
            return tc.run(self.conn, "https://app.example/", today, send=self._send,
                          address=address, **kw)


class SwitchTests(_DB):

    def test_off_by_default_and_on_keeps_the_consent_time(self):
        self.assertFalse(tc.is_on({}))
        self._person("quiet", on=False)
        self.assertEqual(tc.recipients(self.conn), [])
        p = {}
        tc.set_on(p, True, datetime(2026, 10, 6, 8, 30, tzinfo=timezone.utc))
        self.assertEqual((p[tc.PREF_ON], p[tc.PREF_CONSENT]), (True, "2026-10-06T08:30:00Z"))
        tc.set_on(p, True, datetime(2026, 11, 1, tzinfo=timezone.utc))   # the first time stays
        self.assertEqual(p[tc.PREF_CONSENT], "2026-10-06T08:30:00Z")
        tc.set_on(p, False)
        self.assertFalse(tc.is_on(p))
        self.assertNotIn(tc.PREF_CONSENT, p)

    def test_only_confirmed_non_advisors_who_turned_it_on(self):
        yes = self._person("yes")
        self._person("adv", advisor=True)
        self._person("unconfirmed", confirmed=False)
        self._person("off", on=False)
        self.assertEqual([r["id"] for r in tc.recipients(self.conn)], [yes])

    def test_the_flag_is_off_unless_set(self):
        self.assertEqual(flags.FEATURES["trail_conditions"], {"gates": (), "view": None})
        with _flags(""):
            self.assertFalse(flags.on("trail_conditions"))
        with _flags("trail_conditions"):
            self.assertTrue(flags.on("trail_conditions"))


class SendTests(_DB):

    def test_calm_by_default(self):
        self._person("ann")
        done = self._run()
        self.assertEqual((done["sent"], done["calm"]), (1, 1))
        self.assertEqual(self.sent[0]["lines"], [tc.CALM])
        self.assertEqual(self.sent[0]["link"], "https://app.example/?page=dashboard")
        self.assertTrue(self.sent[0]["unsub"].startswith("https://app.example/?unsubscribe="))

    def test_once_a_week(self):
        ann = self._person("ann")
        self.assertEqual(self._run()["sent"], 1)
        self.assertEqual(prefs.load(self.conn, ann)[tc.PREF_SENT], "2026-W38")
        again = self._run(MONDAY + timedelta(days=3))           # the same ISO week
        self.assertEqual((again["sent"], again["already"]), (0, 1))
        self.assertEqual(self._run(MONDAY + timedelta(days=7))["sent"], 1)   # the next week
        self.assertEqual(len(self.sent), 2)

    def test_flag_off_sends_nothing(self):
        self._person("ann")
        done = self._run(flag="")
        self.assertEqual((done["sent"], self.sent), (0, []))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM email_tokens")
                         .fetchone()["n"], 0)
        out = io.StringIO()
        with _flags(""), contextlib.redirect_stdout(out):
            self.assertEqual(tc.main(["--db", self.db, "--app-url", "https://x/"]), 0)
        self.assertIn("isn't turned on", out.getvalue())

    def test_an_empty_postal_address_sends_nothing(self):
        self._person("ann")
        self.assertEqual(mailer.POSTAL_ADDRESS, mailer.POSTAL_ADDRESS.strip())
        for address in ("", "   "):
            done = self._run(address=address)
            self.assertEqual((done["sent"], done["would_send"], self.sent), (0, 0, []))
        with unittest.mock.patch.object(mailer, "POSTAL_ADDRESS", ""):
            self.assertEqual(self._run(address=None)["sent"], 0)      # the constant itself
            out = io.StringIO()
            with _flags("trail_conditions"), contextlib.redirect_stdout(out), \
                    unittest.mock.patch.object(tc, "run") as run:
                self.assertEqual(tc.main(["--db", self.db, "--app-url", "https://x/"]), 0)
            run.assert_not_called()
            self.assertIn("no postal address", out.getvalue())
        self.assertEqual(self.sent, [])

    def test_dry_run_counts_and_records_nothing(self):
        ann = self._person("ann")
        done = self._run(dry_run=True)
        self.assertEqual((done["would_send"], done["sent"], self.sent), (1, 0, []))
        self.assertNotIn(tc.PREF_SENT, prefs.load(self.conn, ann))

    def test_a_failed_send_is_tried_again_next_run(self):
        ann = self._person("ann")
        with _flags("trail_conditions"):
            done = tc.run(self.conn, "https://a/", MONDAY, send=lambda *a: False, address=ADDRESS)
        self.assertEqual(done["failed"], 1)
        self.assertNotIn(tc.PREF_SENT, prefs.load(self.conn, ann))

    def test_unsubscribe_link_and_switch_stop_it(self):
        ann = self._person("ann")
        self._run()
        token = self.sent[0]["unsub"].split("?unsubscribe=", 1)[1]
        self.assertEqual(unsubscribe.use(self.conn, token), {"ok": True, "kind": "trail"})
        p = prefs.load(self.conn, ann)
        self.assertFalse(tc.is_on(p))
        self.assertNotIn(tc.PREF_CONSENT, p)
        self.assertEqual(tc.recipients(self.conn), [])
        self.assertEqual(self._run(MONDAY + timedelta(days=7))["sent"], 0)
        self.assertIn("Trail Conditions", unsubscribe.WHERE["trail"])
        # and turned off by the switch (prefs saved off), nothing goes either
        bob = self._person("bob")
        p = prefs.load(self.conn, bob)
        prefs.save(self.conn, bob, tc.set_on(p, False))
        self.assertEqual(self._run(MONDAY + timedelta(days=14))["sent"], 0)


class TriggerTests(_DB):

    def test_a_storm(self):
        ann = self._person("ann")
        self._holdings(ann, drop=25)
        self._run()
        self.assertEqual(self.sent[0]["lines"], [tc.STORM])
        # rough weather (under 10%) isn't a storm: calm
        self.conn.execute("DELETE FROM daily_bars")
        self.conn.commit()
        bob = self._person("bob")
        self._holdings(bob, drop=6)
        self._run(MONDAY + timedelta(days=7))
        self.assertEqual(self.sent[-1]["lines"], [tc.CALM])

    def test_a_season_begun_once(self):
        ann = self._person("ann")
        self._run(OCT_MONDAY, flag="trail_conditions,seasons")
        self.assertEqual(self.sent[0]["lines"], [tc.SEASON["enrollment"]])
        self.assertEqual(prefs.load(self.conn, ann)[tc.PREF_SEASON], "2026-enrollment")
        self._run(OCT_MONDAY + timedelta(days=7), flag="trail_conditions,seasons")
        self.assertEqual(self.sent[1]["lines"], [tc.CALM])
        # already opened or put away in the app: not mentioned; flag off: not mentioned
        p = seasons.with_status({}, "2026-enrollment", seasons.SEEN)
        self.assertEqual(tc.news(p, OCT_MONDAY, None), [])
        with _flags("trail_conditions"):
            self.assertEqual(tc.news({}, OCT_MONDAY, None), [])

    def test_the_walk_waiting_once_a_month(self):
        ann = self._person("ann", extra={checkin.PREF_SINCE: "2026-08"})
        self._run(flag="trail_conditions,walk")
        self.assertEqual(self.sent[0]["lines"], [tc.WALK])
        self._run(MONDAY + timedelta(days=7), flag="trail_conditions,walk")
        self.assertEqual(self.sent[1]["lines"], [tc.CALM])
        self.assertEqual(prefs.load(self.conn, ann)[tc.PREF_WALK], "2026-09")
        # finished this month: nothing waiting
        p = {checkin.PREF_SINCE: "2026-08",
             checkin.PREF_STATE: {"month": "2026-10", "done": list(checkin.REQUIRED),
                                  "finished": "2026-10-02", "skipped": False}}
        with _flags("trail_conditions,walk"):
            self.assertEqual(tc.news(p, OCT_MONDAY, None), [])

    def test_a_readiness_gap_every_few_weeks(self):
        self._person("ann")
        weeks = [MONDAY + timedelta(days=7 * i) for i in range(6)]
        for d in weeks:
            self._run(d, flag="trail_conditions,drills")
        said = [s["lines"] == [tc.GAP] for s in self.sent]
        self.assertEqual(said, [True, False, False, False, True, False])
        # everything rehearsed: never
        p = {}
        for i, k in enumerate(drills.KEYS):
            drills.record(p, k, drills.choices_of(k)[0][0], MONDAY - timedelta(days=7 * (i + 1)))
        with _flags("trail_conditions,drills"):
            self.assertEqual(tc.news(p, MONDAY, None), [])

    def test_at_most_three_lines_and_the_rest_wait(self):
        ann = self._person("ann", extra={checkin.PREF_SINCE: "2026-08"})
        self._holdings(ann, drop=25)
        storm = {"level": "storm"}
        with _flags("trail_conditions,seasons,walk,drills"):
            items = tc.news(prefs.load(self.conn, ann), OCT_MONDAY, storm)
        self.assertEqual([k for k, *_ in items], ["storm", "season", "walk"])
        p = tc.remember(prefs.load(self.conn, ann), items, OCT_MONDAY)
        self.assertNotIn(tc.PREF_GAP, p)     # not said, so it waits for next week
        with _flags("trail_conditions,seasons,walk,drills"):
            later = tc.news(p, OCT_MONDAY + timedelta(days=7), None)
        self.assertEqual([k for k, *_ in later], ["gap"])


class WordingTests(_DB):
    BANNED = (r"\bshould\b", r"\bbest\b", r"\brecommend", r"\bact now\b", r"\burgent",
              r"\bhurry\b", r"\bdeadline\b", r"\bwill\b", r"\bsoon\b", r"\bforecast",
              r"\bexpect", r"\bbuy now\b", r"\brecover", r"!")

    def test_every_template_has_no_figures_or_advice_words(self):
        for line in tc.all_lines():
            with self.subTest(line):
                self.assertNotRegex(line, r"\d", "no figures")
                self.assertNotIn("%", line)
                self.assertNotIn("$", line)
                for pat in self.BANNED:
                    self.assertNotRegex(line.lower(), pat)
        self.assertEqual(tc.CALM, "Nothing needs your attention this week.")
        self.assertEqual(set(tc.SEASON), set(seasons.KEYS))   # a line for every season

    def test_the_email_has_nothing_about_the_persons_money(self):
        """A seeded account with holdings, a storm, the walk, a season and a
        gap: the whole email, as mailer.send gets it."""
        ann = self._person("ann", extra={checkin.PREF_SINCE: "2026-08"})
        self._holdings(ann, drop=25)
        got = []
        with unittest.mock.patch.object(mailer, "send",
                                        lambda *a, **k: got.append((a, k)) or True), \
                _flags("trail_conditions,seasons,walk,drills"):
            for d in (OCT_MONDAY, OCT_MONDAY + timedelta(days=7)):
                tc.run(self.conn, "https://app.example/", d, address=ADDRESS)
        self.assertEqual(len(got), 2)
        self.assertIn(tc.STORM, got[0][0][2])
        for (to, subject, text, html), kw in got:
            self.assertEqual(to, "ann@example.com")
            self.assertTrue(kw["headers"]["List-Unsubscribe"].startswith(
                "<https://app.example/?unsubscribe="))
            for body in (text, html):
                self.assertIn(mailer.UNSUBSCRIBE_LINE, body)
                self.assertIn(ADDRESS, body)
                # what's left once the links and the postal address are taken out
                rest = re.sub(r"https://\S+", "", body.replace(ADDRESS, ""))
                rest = re.sub(r"<[^>]+>|style=\"[^\"]*\"", " ", rest)
                for secret in ("VTI", "BND", "Rainy Day", "4417", "8123", "8,123", "300",
                               "37", "%", "$"):
                    self.assertNotIn(secret, rest, secret)
                self.assertNotRegex(re.sub(r"#[0-9a-fA-F]{6}|\d+px|\d\.\d", "", rest), r"\d")
            self.assertNotRegex(subject, r"\d")

    def test_no_drill_words_in_the_shared_email_files(self):
        """drills.py's own promise: the shared email files never mention it
        (tests/test_drills.py); Trail Conditions has its own module."""
        for name in ("mailer.py", os.path.join(".github", "workflows", "scheduled-sync.yml")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotIn("drill", fh.read().replace("storm_drill", ""), name)


class WorkflowTests(unittest.TestCase):

    def test_its_monday_job_has_its_own_failure_step(self):
        with open(os.path.join(REPO, ".github", "workflows", "scheduled-sync.yml"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('- cron: "0 13 * * 1"', text)
        job = text.split("\n  trail-conditions:", 1)[1]
        self.assertIn("github.event.schedule == '0 13 * * 1'", job)
        self.assertIn('python trail_conditions.py --db "$DATABASE_URL"', job)
        self.assertIn("NORTHWEND_FLAGS: ${{ secrets.NORTHWEND_FLAGS }}", job)
        self.assertIn("if: failure()", job)
        self.assertIn('python error_alerts.py job "Trail Conditions"', job)

    def test_privacy_words_and_the_gate_row(self):
        import disclosures
        text = " ".join(body for _t, body in disclosures.SECTIONS)
        self.assertIn("Trail Conditions", text)
        for name in ("privacy-policy.md", "privacy-policy-DRAFT.md"):
            with open(os.path.join(REPO, "docs", "legal", name), encoding="utf-8") as fh:
                policy = fh.read()
            self.assertIn("Where Trail Conditions is offered and you turn it on", policy, name)
            self.assertIn("stops it\n  in one click", policy, name)
        with open(os.path.join(REPO, "docs", "LEGAL_GATES.md"), encoding="utf-8") as fh:
            gates = fh.read()
        self.assertIn("flag `trail_conditions`", gates)
        self.assertIn("CAN-SPAM", gates)


# --------------------------------------------------------------------------- #
# the switch on Account, in the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_trail_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.ivy = auth.create_user(c, "ivy", PW)
            c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                      ("ivy@example.com", "2026-09-01T10:00:00Z", cls.ivy))
            prefs.save(c, cls.ivy, {"first_steps": {"done": True}})
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, flag):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.ivy, "username": "ivy", "page": "Account",
                     "auto_backfilled": True}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _prefs(self):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, self.ivy)
        finally:
            c.close()

    def test_the_switch_is_off_by_default_and_keeps_consent(self):
        with self._app("") as at:
            self.assertNotIn("acct_trail", [t.key for t in at.toggle])
        with self._app("trail_conditions") as at:
            toggle = at.toggle(key="acct_trail")
            self.assertFalse(toggle.value)
            self.assertIn(tc.SWITCH_HELP, " ".join(str(c.value) for c in at.caption))
            toggle.set_value(True).run()
            p = self._prefs()
            self.assertTrue(tc.is_on(p))
            self.assertRegex(p[tc.PREF_CONSENT], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            at.toggle(key="acct_trail").set_value(False).run()
            p = self._prefs()
            self.assertFalse(tc.is_on(p))
            self.assertNotIn(tc.PREF_CONSENT, p)


if __name__ == "__main__":
    unittest.main()
