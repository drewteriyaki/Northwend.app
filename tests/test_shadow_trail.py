"""Shadow Trail (ROADMAP R14; shadow_trail.py, views/shadow_trail.py, flag
shadow_trail + gate L3).

At most two shadows, each a mix of kinds of funds only (never a ticker),
changed at most once a quarter (removing doesn't reset the date); the paths
are percent changes on a fixed price series; every line is labelled
hypothetical and free of ranking or advice words (banned words and
ai_policy.findings); nothing to act on; only kind keys, whole percents and
two days are kept. In the app: off unless the flag and gate L3 are both on;
the login's own account (an advisor's client signed in themselves included);
never while an advisor is in a client's account.

    python -m unittest tests.test_shadow_trail        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import ai_policy  # noqa: E402
import auth  # noqa: E402
import flags  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import shadow_trail as sh  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
TAB = "Shadow Trail"
# ranking, advice and action words that must never appear in what people read
NEVER = (r"\bwinn", r"\bbeat", r"\bbetter\b", r"\bworse\b", r"\bshould\b", r"\bbest\b",
         r"\brecommend", r"\bsuggest", r"\boutperform", r"\bunderperform", r"\bleader\b",
         r"\bleading\b", r"\bswitch", r"\brebalance to\b", r"\bbuy\b", r"\bsell\b",
         r"\btrade\b", r"\bguarantee", r"\bahead of\b", r"\bbehind\b", r"\bwinner",
         r"\bloser", r"\buse this mix\b")
TICKERS = ("VTI", "VXUS", "BND")
US, INTL, BONDS = (sh.BY_KIND[k]["proxy"] for k in ("us", "intl", "bonds"))
DAY = date(2026, 1, 15)


def _code_words(path):
    """A source file's text without its comment lines (lower case)."""
    with open(path, encoding="utf-8") as fh:
        return "\n".join(line for line in fh.read().lower().splitlines()
                         if not line.lstrip().startswith("#"))


class WordingTests(unittest.TestCase):

    def test_no_banned_words_and_no_tickers(self):
        text = sh.all_text().lower()
        for pat in NEVER:
            self.assertNotRegex(text, pat)
        for t in TICKERS:
            self.assertNotIn(t.lower(), re.findall(r"[a-z]+", text))
        view = _code_words(os.path.join(REPO, "views", "shadow_trail.py"))
        for pat in NEVER:
            # strings only: a quoted literal with the word in it
            self.assertNotRegex(view, r"\"[^\"\n]*" + pat + r"[^\"\n]*\"")

    def test_every_line_passes_the_conclusion_policy(self):
        for line in sh.sample_texts():
            with self.subTest(line=line[:50]):
                self.assertEqual(ai_policy.findings(line, allowed_tickers=set()), [])

    def test_the_hypothetical_label(self):
        self.assertEqual(sh.HYPOTHETICAL, "Hypothetical - a made-up mix you don't hold, on "
                                          "past prices. Not a forecast, not advice.")
        self.assertIn("Kinds of funds, represented by", sh.PROXY_LINE)
        self.assertIn("cash is counted flat", sh.PROXY_LINE)
        self.assertIn("Only you see it", sh.KEPT_LINE)

    def test_no_action_buttons(self):
        # the only buttons are the shadow's own: set up / edit / save / remove /
        # cancel - nothing that moves money, a target or a trade
        view = _code_words(os.path.join(REPO, "views", "shadow_trail.py"))
        labels = re.findall(r"button\(\s*([\w.]+(?:\(name=name\))?)", view)
        self.assertEqual(len(labels), 4)
        allowed = {"label.format(name=name)", "sh.cancel_label",
                   "sh.save_label.format(name=name)", "sh.remove_label.format(name=name)"}
        for lab in labels:
            self.assertIn(lab.strip(), allowed, lab)
        for word in ("target", "rebalance", "link_button", "page_link", "switch_page",
                     "save_plan", "alloc_targets", "write_snapshot"):
            self.assertNotIn(word, view)

    def test_neutral_colours(self):
        view = _code_words(os.path.join(REPO, "views", "shadow_trail.py"))
        for pat in (r"pt-up", r"pt-down", r"\bgreen\b", r"\bred\b", r"st\.error",
                    r"st\.success", r"#[0-9a-f]{6}"):
            self.assertNotRegex(view, pat)
        self.assertIn("SERIES_OTHER, SERIES_OTHER", _code_words(
            os.path.join(REPO, "views", "shadow_trail.py")).upper())


class MixTests(unittest.TestCase):

    def test_kinds_only_whole_steps_adding_to_100(self):
        self.assertEqual(sh.clean_mix({"us": 60, "bonds": 40}), {"us": 60, "bonds": 40})
        self.assertEqual(sh.clean_mix({"bonds": 40.0, "us": 60, "cash": 0}),
                         {"us": 60, "bonds": 40})
        for bad in ({"us": 60, "bonds": 35}, {"VTI": 100}, {"us": 62, "bonds": 38},
                    {"us": "x"}, {"us": -10, "bonds": 110}, {}, None, "us"):
            self.assertIsNone(sh.clean_mix(bad), bad)
        self.assertEqual(sh.mix_text({"us": 40, "intl": 20, "bonds": 30, "cash": 10}),
                         "40% US stocks / 20% international stocks / 30% bonds / 10% cash")

    def test_why_a_typed_mix_isnt_kept(self):
        self.assertEqual(sh.save_problem({"us": 60, "bonds": 35}),
                         sh.TOTAL_LINE.format(total=95))
        self.assertEqual(sh.save_problem({"us": 62, "bonds": 38}),
                         sh.STEP_LINE.format(step=sh.STEP))
        self.assertIsNone(sh.save_problem({"us": 60, "bonds": 40, "cash": 0}))

    def test_at_most_two(self):
        self.assertEqual(sh.MAX_SHADOWS, 2)
        p, ok = sh.with_shadow({}, 2, {"us": 100}, DAY)
        self.assertFalse(ok)
        p, _ = sh.with_shadow({}, 0, {"us": 100}, DAY)
        p, _ = sh.with_shadow(p, 1, {"bonds": 100}, DAY)
        self.assertEqual(len(sh.active(p)), 2)
        p[sh.PREF]["shadows"].append({"mix": {"cash": 100}, "start": "2026-01-01",
                                      "changed": "2026-01-01"})
        self.assertEqual(len(sh.slots(p)), 2)
        self.assertEqual(len(sh.active(p)), 2)

    def test_quarterly_lock(self):
        p, ok = sh.with_shadow({"other": 1}, 0, {"us": 60, "bonds": 40}, DAY)
        self.assertTrue(ok)
        self.assertEqual(p[sh.PREF]["shadows"][0],
                         {"mix": {"us": 60, "bonds": 40}, "start": "2026-01-15",
                          "changed": "2026-01-15"})
        self.assertEqual(p["other"], 1)
        slot = sh.slots(p)[0]
        self.assertEqual(sh.next_change(slot), date(2026, 4, 15))
        for d in (DAY, date(2026, 4, 14)):
            again, ok = sh.with_shadow(p, 0, {"us": 100}, d)
            self.assertFalse(ok)
            self.assertEqual(again, p)
        later, ok = sh.with_shadow(p, 0, {"us": 100}, date(2026, 4, 15))
        self.assertTrue(ok)
        s = sh.slots(later)[0]
        self.assertEqual((s["start"], s["changed"]), ("2026-01-15", "2026-04-15"))
        self.assertEqual(sh.next_change(s), date(2026, 7, 15))

    def test_removing_doesnt_reset_the_date(self):
        p, _ = sh.with_shadow({}, 0, {"us": 100}, DAY)
        gone = sh.without_shadow(p, 0)
        self.assertEqual(sh.active(gone), [])
        self.assertEqual(sh.slots(gone)[0]["mix"], {})
        _, ok = sh.with_shadow(gone, 0, {"bonds": 100}, date(2026, 2, 1))
        self.assertFalse(ok)
        back, ok = sh.with_shadow(gone, 0, {"bonds": 100}, date(2026, 4, 15))
        self.assertTrue(ok)
        self.assertEqual(sh.slots(back)[0]["start"], "2026-04-15")
        self.assertEqual(sh.cleared(back), {})

    def test_stand_ins_match_the_practice_portfolio(self):
        import learn
        for k in ("us", "intl", "bonds"):
            self.assertEqual(sh.BY_KIND[k]["proxy"], learn.PRACTICE_TICKERS[k])
            self.assertEqual(sh.BY_KIND[k]["about"], learn.KINDS[k])
        self.assertIsNone(sh.BY_KIND["cash"]["proxy"])

    def test_month_ends(self):
        self.assertEqual(sh.add_months(date(2026, 11, 30), 3), date(2027, 2, 28))
        self.assertEqual(sh.add_months(date(2026, 10, 31), 3), date(2027, 1, 31))

    def test_only_keys_numbers_and_days_are_kept(self):
        raw = {sh.PREF: {"shadows": [
            {"mix": {"us": 60, "bonds": 40}, "start": "2026-01-15", "changed": "2026-01-15",
             "note": "free text"},
            {"mix": {"VTI": 100}, "start": "x", "changed": "2026-02-01"}]}}
        s = sh.slots(raw)
        self.assertEqual(s[0], {"mix": {"us": 60, "bonds": 40}, "start": "2026-01-15",
                                "changed": "2026-01-15"})
        self.assertEqual(s[1], {"mix": {}, "start": None, "changed": "2026-02-01"})
        self.assertEqual(sh.slots({sh.PREF: "junk"}), [None, None])


class PathTests(unittest.TestCase):
    PRICES = {US: [("2026-01-14", 90.0), ("2026-01-15", 100.0), ("2026-01-16", 110.0),
                   ("2026-01-20", 120.0)],
              INTL: [("2026-01-15", 50.0), ("2026-01-16", 45.0), ("2026-01-20", 55.0)],
              BONDS: [("2026-01-15", 80.0), ("2026-01-16", 80.0), ("2026-01-20", 84.0)]}

    def test_percent_maths_on_a_fixed_series(self):
        pts = sh.path(self.PRICES, {"us": 60, "bonds": 40}, "2026-01-15")
        self.assertEqual([d for d, _ in pts], ["2026-01-15", "2026-01-16", "2026-01-20"])
        self.assertAlmostEqual(pts[0][1], 0.0)
        self.assertAlmostEqual(pts[1][1], 6.0)        # 0.6 * 10%
        self.assertAlmostEqual(pts[2][1], 14.0)       # 0.6 * 20% + 0.4 * 5%
        # cash is flat; bought and left alone (no rebalancing)
        pts = sh.path(self.PRICES, {"intl": 50, "cash": 50}, "2026-01-15")
        self.assertAlmostEqual(pts[1][1], -5.0)
        self.assertAlmostEqual(pts[2][1], 5.0)
        # the first day on or after the day it was set
        pts = sh.path(self.PRICES, {"us": 100}, "2026-01-17")
        self.assertEqual(pts, [("2026-01-20", 0.0)])
        self.assertEqual(sh.path(self.PRICES, {"us": 100}, "2026-02-01"), [])
        self.assertEqual(sh.path({US: []}, {"us": 100}, "2026-01-15"), [])
        self.assertEqual(sh.path(self.PRICES, {"cash": 100}, "2026-01-15"),
                         [("2026-01-15", 0.0)])

    def test_real_line_and_the_table(self):
        values = [("2026-01-14", 900.0), ("2026-01-15", 1000.0), ("2026-01-16", 1020.0),
                  ("2026-01-20", 1050.0)]
        real = sh.real_path(values, "2026-01-15")
        self.assertAlmostEqual(real[-1][1], 5.0)
        a = sh.path(self.PRICES, {"us": 60, "bonds": 40}, "2026-01-15")
        b = sh.path(self.PRICES, {"bonds": 100}, "2026-01-16")
        through = sh.last_day(real, a, b)
        self.assertEqual(through, "2026-01-20")
        shadows = [{"name": "Shadow A", "mix": {"us": 60, "bonds": 40}, "changed": "2026-01-15",
                    "first": a[0][0], "points": a},
                   {"name": "Shadow B", "mix": {"bonds": 100}, "changed": "2026-01-16",
                    "first": b[0][0], "points": b}]
        rows = sh.table_rows(values, shadows, through)
        # the order they were made, never sorted by change
        self.assertEqual([r["name"] for r in rows], ["Shadow A", "Shadow B"])
        self.assertAlmostEqual(rows[0]["shadow"], 14.0)
        self.assertAlmostEqual(rows[0]["real"], 5.0)
        self.assertAlmostEqual(rows[1]["shadow"], 5.0)
        self.assertAlmostEqual(rows[1]["real"], (1050 / 1020 - 1) * 100)
        # the chart: B branches off your line on its first day
        chart = sh.chart_rows(real, [("Shadow A", a), ("Shadow B", b)], through)
        b_rows = [r for r in chart if r["line"] == "Shadow B"]
        self.assertAlmostEqual(b_rows[0]["pct"], 2.0)
        self.assertAlmostEqual(b_rows[-1]["pct"], (1.02 * 1.05 - 1) * 100)
        self.assertEqual(sh.pct_text(14.0), "+14.0%")
        self.assertEqual(sh.pct_text(-0.04), "0.0%")
        self.assertEqual(sh.pct_text(None), "–")


class FlagTests(unittest.TestCase):

    def test_needs_the_flag_and_gate_l3(self):
        self.assertEqual(flags.FEATURES["shadow_trail"],
                         {"gates": ("L3",), "view": "shadow_trail"})
        with unittest.mock.patch.object(flags, "_secret", lambda name: None):
            for f, g, want in (("", "", False), ("shadow_trail", "", False),
                               ("", "L3", False), ("shadow_trail", "L0", False),
                               ("shadow_trail", "L3", True)):
                with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": f,
                                                           "NORTHWEND_GATES": g}):
                    self.assertEqual(flags.on("shadow_trail"), want, (f, g))
                    self.assertEqual(flags.view_on("shadow_trail"), want, (f, g))

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "meeting.py", "reports.py", "overview.py", "weekly_email.py",
                     "client_plan.py", os.path.join("views", "assistant.py"),
                     os.path.join("views", "clients.py")):
            path = os.path.join(REPO, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn("shadow_trail", fh.read(), name)


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
def _weekdays(n, end):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class CallbackGuardTests(unittest.TestCase):
    """The form's callbacks change only the login's own settings, like the
    tab itself: never while an advisor is in a client's account."""

    def _ns(self, user_id, login_id, on_client):
        writes = []
        state = {"shadow_edit": 0}
        ns = {"st": types.SimpleNamespace(session_state=state, fragment=lambda f: f),
              "USER_ID": user_id,
              "LOGIN_ID": login_id, "ON_CLIENT": on_client,
              "_read_prefs": lambda: {}, "_write_prefs": writes.append}
        path = os.path.join(REPO, "views", "shadow_trail.py")
        with open(path, encoding="utf-8") as fh:
            exec(compile(fh.read(), path, "exec"), ns)  # noqa: S102 - as dashboard._view does
        return ns, writes, state

    def test_not_in_a_clients_account(self):
        for args in ((7, 3, True), (7, 3, False)):
            ns, writes, state = self._ns(*args)
            ns["_shadow_remove"](0)
            ns["_shadow_save"](0, DAY)
            self.assertEqual(writes, [], args)
            self.assertEqual(state, {"shadow_edit": 0}, args)

    def test_the_login_s_own(self):
        ns, writes, _state = self._ns(3, 3, False)
        ns["_shadow_remove"](0)
        self.assertEqual(len(writes), 1)


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_shadow_trail_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            sample_data.load(c, cls.alice)
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana)
            auth.link_client(c, cls.carol, cls.dana)
            # 60 weekdays of made-up prices for every sample holding
            days = _weekdays(60, date.today() - timedelta(days=1))
            cls.days = days
            for t, base, step in (("VTI", 300.0, 0.5), ("VXUS", 60.0, -0.05), ("BND", 72.0, 0.01),
                                  ("AAPL", 230.0, 0.3), ("VOO", 550.0, 0.6),
                                  ("SCHD", 28.0, 0.02)):
                for i, d in enumerate(days):
                    p = base + step * i
                    c.execute("INSERT INTO daily_bars (ticker, date, close, adj_close) "
                              "VALUES (?, ?, ?, ?)", (t, d.isoformat(), p, p))
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self._set(self.alice, {})
        self._set(self.dana, {})

    def _set(self, uid, value):
        c = portfolio.connect(self.db)
        try:
            p = prefs.load(c, uid)
            p.pop(sh.PREF, None)
            if value:
                p[sh.PREF] = value
            prefs.save(c, uid, p)
        finally:
            c.close()

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    @contextlib.contextmanager
    def _app(self, uid, name, flag="shadow_trail", gates="L3", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Plan",
                     "auto_backfilled": True, "income_synced": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag, NORTHWEND_GATES=gates)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _labels(at):
        return [t.label for t in at.tabs]

    @staticmethod
    def _tab(at):
        return next(t for t in at.tabs if t.label == TAB)

    def _tab_text(self, at):
        tab = self._tab(at)
        return " ".join([m.value for m in tab.markdown] + [c.value for c in tab.caption]
                        + [i.value for i in tab.info] + [w.value for w in tab.warning])

    def test_off_without_the_flag_or_the_gate(self):
        for flag, gates in (("", ""), ("shadow_trail", ""), ("", "L3")):
            with self.subTest(flag=flag, gates=gates), \
                    self._app(self.alice, "alice", flag=flag, gates=gates) as at:
                self.assertIn("Stress test", self._labels(at))
                self.assertNotIn(TAB, self._labels(at))

    def test_setting_a_shadow_and_the_lock(self):
        with self._app(self.alice, "alice") as at:
            labels = self._labels(at)
            self.assertEqual(labels.index(TAB), labels.index("Stress test") + 1)
            text = self._tab_text(at)
            self.assertIn(sh.HYPOTHETICAL, text)
            self.assertIn(sh.NONE_YET, text)
            tab = self._tab(at)
            self.assertEqual([b.label for b in tab.button],
                             ["Set up Shadow A", "Set up Shadow B"])
            at.button(key="shadow_open_0").click().run()
            # not adding to 100: nothing saved
            at.number_input(key="shadow_0_us").set_value(60)
            at.number_input(key="shadow_0_bonds").set_value(35)
            next(b for b in self._tab(at).button if b.label == "Save Shadow A").click().run()
            self.assertIn("Adds up to 95%", self._tab_text(at))
            self.assertNotIn(sh.PREF, self._prefs(self.alice))
            # 100 but not in 5% steps: said, not silently dropped (fresh-eyes Oct 8)
            at.number_input(key="shadow_0_us").set_value(62)
            at.number_input(key="shadow_0_bonds").set_value(38)
            next(b for b in self._tab(at).button if b.label == "Save Shadow A").click().run()
            self.assertIn(sh.STEP_LINE.format(step=sh.STEP), self._tab_text(at))
            self.assertNotIn(sh.PREF, self._prefs(self.alice))
            at.number_input(key="shadow_0_us").set_value(60)
            at.number_input(key="shadow_0_bonds").set_value(35)
            at.number_input(key="shadow_0_bonds").set_value(40)
            next(b for b in self._tab(at).button if b.label == "Save Shadow A").click().run()
            self.assertEqual([e.message for e in at.exception], [])
            text = self._tab_text(at)
            self.assertIn("60% US stocks / 40% bonds", text)
            nxt = sh.date_text(sh.add_months(date.today(), 3))
            self.assertIn(f"It can change on {nxt}.", text)
            labels = [b.label for b in self._tab(at).button]
            self.assertNotIn("Edit Shadow A", labels)       # locked
            self.assertIn("Remove Shadow A", labels)
            self.assertIn("Set up Shadow B", labels)
        kept = self._prefs(self.alice)[sh.PREF]
        self.assertEqual(kept, {"shadows": [{"mix": {"us": 60, "bonds": 40},
                                             "start": date.today().isoformat(),
                                             "changed": date.today().isoformat()}]})

    def test_paths_table_and_chart(self):
        start = self.days[20].isoformat()
        self._set(self.alice, {"shadows": [
            {"mix": {"us": 60, "bonds": 40}, "start": start, "changed": start},
            {"mix": {"intl": 50, "cash": 50}, "start": self.days[40].isoformat(),
             "changed": self.days[40].isoformat()}]})
        with self._app(self.alice, "alice") as at:
            tab = self._tab(at)
            text = self._tab_text(at)
            self.assertEqual(text.count(sh.HYPOTHETICAL), 2)   # top and under the chart
            self.assertIn("represented by the past prices of a broad US stock index fund",
                          text)
            for pat in NEVER:
                self.assertNotRegex(text.lower(), pat)
            for t in TICKERS:
                self.assertNotIn(t, text)
            df = tab.dataframe[0].value
            self.assertEqual(list(df.columns), list(sh.TABLE_COLUMNS))
            self.assertEqual(list(df["Path"]), ["Shadow A", "Shadow B"])
            self.assertEqual(df["Mix"][1], "50% international stocks / 50% cash")
            self.assertTrue(all(re.fullmatch(r"[+-]?\d+\.\d%", v)
                                for v in list(df["Change, shadow"]) + list(df["Change, your mix"])))
            self.assertNotRegex(" ".join(df.astype(str).values.ravel()), r"\$")
            # the fixed series: VTI +0.5 a day, BND +0.01 a day, from day 20
            last = len(self.days) - 1
            want = (0.6 * ((300 + 0.5 * last) / (300 + 0.5 * 20) - 1)
                    + 0.4 * ((72 + 0.01 * last) / (72 + 0.01 * 20) - 1)) * 100
            self.assertEqual(df["Change, shadow"][0], sh.pct_text(want))
            self.assertEqual(len(tab.get("vega_lite_chart")), 1)

    def test_no_prices_is_a_calm_note(self):
        self._set(self.alice, {"shadows": [
            {"mix": {"us": 100}, "start": "2000-01-03", "changed": "2000-01-03"}]})
        c = portfolio.connect(self.db)
        try:
            saved = c.execute("SELECT ticker, date, close, adj_close FROM daily_bars "
                              "WHERE ticker = 'VTI'").fetchall()
            c.execute("DELETE FROM daily_bars WHERE ticker = 'VTI'")
            c.commit()
        finally:
            c.close()
        try:
            with self._app(self.alice, "alice") as at:
                self.assertIn(sh.NO_PRICES, self._tab_text(at))
                self.assertEqual(self._tab(at).dataframe, [])
        finally:
            c = portfolio.connect(self.db)
            try:
                c.executemany("INSERT INTO daily_bars (ticker, date, close, adj_close) "
                              "VALUES (?, ?, ?, ?)", [tuple(r) for r in saved])
                c.commit()
            finally:
                c.close()

    def test_removing(self):
        start = self.days[30].isoformat()
        self._set(self.alice, {"shadows": [
            {"mix": {"us": 100}, "start": start, "changed": start}]})
        with self._app(self.alice, "alice") as at:
            at.button(key="shadow_remove_0").click().run()
            self.assertEqual([e.message for e in at.exception], [])
            self.assertIn(sh.NONE_YET, self._tab_text(at))
        slot = sh.slots(self._prefs(self.alice))[0]
        self.assertEqual(slot["mix"], {})
        self.assertEqual(slot["changed"], start)

    def test_an_advisor_in_a_clients_account_never_sees_it(self):
        start = self.days[20].isoformat()
        self._set(self.dana, {"shadows": [
            {"mix": {"us": 100}, "start": start, "changed": start}]})
        with self._app(self.carol, "carol", active_user_id=self.dana,
                       two_step_ok=self.carol_ok) as at:
            self.assertIn("Stress test", self._labels(at))
            self.assertNotIn(TAB, self._labels(at))
            self.assertNotIn("Shadow A", " ".join(m.value for m in at.markdown))

    def test_an_advisors_client_signed_in_sees_their_own(self):
        start = self.days[20].isoformat()
        self._set(self.dana, {"shadows": [
            {"mix": {"us": 100}, "start": start, "changed": start}]})
        with self._app(self.dana, "dana") as at:
            self.assertIn(TAB, self._labels(at))
            self.assertIn("100% US stocks", self._tab_text(at))


if __name__ == "__main__":
    unittest.main()
