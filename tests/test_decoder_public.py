"""The 401(k) Menu Decoder without an account (master brief 8a; docs/PLAN.md
step 3 item 6, decision B12; decoder_public.py, views/decoder_public.py):
?decode=401k before sign-in behind flag decoder_public and gate L0; nothing
written but the rate-limit count per hashed address; the limit trips calmly;
the account offer only after a result; the pasted order; the website's
explainer page.

The fund data is fixture data for these tests, not a statement of any fund's
real fee.

    python -m unittest tests.test_decoder_public        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import auth  # noqa: E402
import decoder_public as dp  # noqa: E402
import flags  # noqa: E402
import portfolio  # noqa: E402
import sync_history  # noqa: E402
import tidy  # noqa: E402

INFO = [
    {"ticker": "FXAIX", "name": "Fidelity 500 Index Fund", "quote_type": "MUTUALFUND",
     "category": "Large Blend", "expense_ratio": 0.00015, "fetched_at": "2026-10-03 02:00:00"},
    {"ticker": "VFIFX", "name": "Vanguard Target Retirement 2050 Fund",
     "quote_type": "MUTUALFUND", "category": "Target-Date 2050", "expense_ratio": 0.0008,
     "fetched_at": "2026-10-02 02:00:00"},
]

# deliberately not in fee order: the table must keep it
MENU = ("Zephyr Quiet Harbor Stable Value Fund  Expense ratio 0.40%\n"
        "Fidelity 500 Index Fund (FXAIX)\n"
        "Acme Pricey Growth Fund  Expense ratio 1.10%\n"
        "Vanguard Target Retirement 2050 Fund (VFIFX)\n"
        "Your balance: $12,345.67\n")

NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)
IP = "203.0.113.7"


def _new_db(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    db = os.path.join(d, "app.db")
    portfolio._SCHEMA_READY.discard(os.path.abspath(db))
    return d, db


def _counts(db):
    """Rows in every table of the database."""
    c = sqlite3.connect(db)
    try:
        names = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'")]
        return {n: c.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        c.close()


# --------------------------------------------------------------------------- #
# the limit (decoder_public.take)
# --------------------------------------------------------------------------- #
class LimitTests(unittest.TestCase):
    def setUp(self):
        d, db = _new_db("pt_dp_limit_")
        self.addCleanup(shutil.rmtree, d, True)
        self.conn = portfolio.connect(db)
        self.addCleanup(self.conn.close)

    def _rows(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT address_key, created_at, ok FROM signups ORDER BY created_at")]

    def test_the_route(self):
        self.assertTrue(dp.wanted({"decode": "401k"}))
        self.assertTrue(dp.wanted({"decode": " 401K "}))
        for q in ({}, {"decode": ""}, {"decode": "403b"}, {"page": "plan"}, None):
            self.assertFalse(dp.wanted(q), q)

    def test_per_address_per_hour_then_a_calm_no(self):
        for i in range(dp.PER_ADDRESS_PER_HOUR):
            self.assertIsNone(dp.take(self.conn, IP, now=NOW + timedelta(seconds=i)))
        said = dp.take(self.conn, IP, now=NOW + timedelta(minutes=5))
        self.assertEqual(said, dp.TOO_MANY_FROM_HERE)
        self.assertIn("nothing you pasted was kept", said)
        for word in ("error", "blocked", "denied", "abuse", "!"):
            self.assertNotIn(word, said.lower())
        # a refused decode isn't counted; another address isn't affected
        self.assertEqual(len(self._rows()), dp.PER_ADDRESS_PER_HOUR)
        self.assertIsNone(dp.take(self.conn, "198.51.100.2", now=NOW + timedelta(minutes=5)))
        # an hour on, the address may decode again
        self.assertIsNone(dp.take(self.conn, IP, now=NOW + timedelta(minutes=61)))

    def test_only_a_hash_with_the_prefix_is_kept(self):
        dp.take(self.conn, IP, now=NOW)
        (row,) = self._rows()
        self.assertEqual(row["address_key"], dp.KEY_PREFIX + auth._address_key(IP))
        self.assertNotIn(IP, row["address_key"])
        self.assertEqual(row["ok"], 0)

    def test_app_wide_cap_and_unknown_addresses(self):
        with unittest.mock.patch.object(dp, "PER_HOUR", 3):
            for i in range(3):   # no address known: only the app-wide cap applies
                self.assertIsNone(dp.take(self.conn, None, now=NOW + timedelta(seconds=i)))
            self.assertEqual(dp.take(self.conn, IP, now=NOW), dp.TOO_MANY_EVERYWHERE)
        self.assertEqual({r["address_key"] for r in self._rows()}, {dp.KEY_PREFIX})

    def test_sign_up_limits_never_see_decoder_counts(self):
        for i in range(dp.PER_ADDRESS_PER_HOUR):
            dp.take(self.conn, IP, now=NOW + timedelta(seconds=i))
        res = auth.sign_up(self.conn, "after.decoding@example.com", "pw-1234567890",
                           agreed=True, adult=True, us_resident=True, terms_version="t",
                           ip=IP, seconds_open=60, needs_code=False,
                           now=NOW + timedelta(minutes=1))
        self.assertTrue(res["ok"], res["error"])

    def test_the_nightly_tidy_clears_a_day_old_count(self):
        dp.take(self.conn, IP, now=NOW - timedelta(days=2))
        dp.take(self.conn, IP, now=NOW)
        self.assertEqual(len(self._rows()), 1)    # take() itself tidies, as sign-up does
        self.conn.execute("INSERT INTO signups (address_key, created_at, ok) VALUES (?, ?, 0)",
                          (dp.address_key(IP), auth._utc(NOW - timedelta(days=2))))
        self.conn.commit()
        done = tidy.run(self.conn, now=NOW)
        self.assertEqual(done["sign-up counts"], 1)
        self.assertEqual(len(self._rows()), 1)


class FlagTests(unittest.TestCase):
    def test_off_unless_set_and_needs_l0(self):
        self.assertEqual(flags.FEATURES["decoder_public"],
                         {"gates": ("L0",), "view": "decoder_public"})
        with unittest.mock.patch.object(flags, "_secret", lambda name: None):
            with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "",
                                                       "NORTHWEND_GATES": "L0"}):
                self.assertFalse(flags.on("decoder_public"))
                self.assertFalse(flags.view_on("decoder_public"))
            with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "decoder_public",
                                                       "NORTHWEND_GATES": ""}):
                self.assertFalse(flags.on("decoder_public"))
            with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "decoder_public",
                                                       "NORTHWEND_GATES": "L0"}):
                self.assertTrue(flags.on("decoder_public"))
                self.assertTrue(flags.view_on("decoder_public"))
                self.assertFalse(flags.on("decoder_401k"))   # each its own flag


class ViewSourceTests(unittest.TestCase):
    """What the page's code may and may not do."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(REPO, "views", "decoder_public.py"), encoding="utf-8") as fh:
            cls.src = fh.read()
        cls.code = "\n".join(line for line in cls.src.splitlines()
                             if not line.lstrip().startswith("#"))

    def test_no_ai_no_fetching_no_writes_but_the_count(self):
        for name in ("advisor", "ai_gateway", "anthropic", "ai_usage", "ai_spend",
                     "fund_holdings", "yfinance", "live_prices", "sync_history", "news",
                     "feature_counts", "_write_prefs", "prefs.", "logging", "print("):
            self.assertNotIn(name, self.code, name)
        self.assertNotIn("INSERT", self.code)
        self.assertNotIn("UPDATE", self.code)
        self.assertIn("decoder_public.take(", self.code)

    def test_never_sorted_ranked_or_marked(self):
        self.assertIn("menu_decoder.table(result, monthly)", self.code)
        self.assertIn("st.table(", self.code)
        for word in ("sort", "st.dataframe(", "best", "cheapest", "recommend", "top pick",
                     "lowest"):
            self.assertNotIn(word, self.code.lower(), word)


# --------------------------------------------------------------------------- #
# the page in the app
# --------------------------------------------------------------------------- #
class PageTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run may load fresh copies of the app's modules
        # (codefresh.py): kept here and put back after, and patched where the
        # app looks them up (sys.modules) once a first run has happened
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir, cls.db = _new_db("pt_dp_app_")
        conn = portfolio.connect(cls.db)
        cls.uid = auth.create_user(conn, "alice", "pw-123456789")
        for r in INFO:
            sync_history.upsert_info(conn, r["ticker"], r)
        conn.commit()
        conn.close()
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        env = {k: v for k, v in os.environ.items() if k != "FINNHUB_API_KEY"}
        env.update(PORTFOLIO_DB=cls.db, MAIL_DRY_RUN="1", NORTHWEND_FLAGS="decoder_public",
                   NORTHWEND_GATES="L0")
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.run()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        c = sqlite3.connect(self.db)
        c.execute("DELETE FROM signups")
        c.commit()
        c.close()

    @contextlib.contextmanager
    def _app(self, flag="decoder_public", gates="L0", state=None, query=True):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        if query:
            at.query_params["decode"] = "401k"
        for k, v in (state or {}).items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "ANTHROPIC_API_KEY", "RESEND_API_KEY",
                            "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", NORTHWEND_FLAGS=flag,
                   NORTHWEND_GATES=gates)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect), \
                unittest.mock.patch.object(sys.modules["hosting"], "client_ip",
                                           lambda *a, **k: IP):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown] + [m.value for m in at.title]
        for kind in ("caption", "info", "error", "success"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    def _describe(self, at, text=MENU, monthly=None):
        at.text_area(key="dp_text").input(text)
        if monthly is not None:
            at.number_input(key="dp_monthly").set_value(monthly)
        at.button(key="dp_go").click().run()
        self.assertEqual([e.message for e in at.exception], [])

    def test_on_it_opens_without_signing_in(self):
        with self._app() as at:
            self.assertIn("dp_text", [t.key for t in at.text_area])
            self.assertNotIn("login_user", [t.key for t in at.text_input])
            text = self._text(at)
            self.assertIn("Decode a 401(k) menu", text)
            self.assertIn("No account needed", text)
            self.assertIn("it isn't financial advice, and nothing you paste is saved", text)
            self.assertNotIn("user_id", at.session_state)
            # no offer before a result
            self.assertNotIn("dp_signup", [b.key for b in at.button])
            self.assertNotIn("keep track of your plan", text)
            self.assertNotIn("dp_overlap", [b.key for b in at.button])

    def test_off_it_is_the_sign_in_page(self):
        for flag, gates in (("", "L0"), ("decoder_public", ""), ("decoder_401k", "L0")):
            with self._app(flag=flag, gates=gates) as at:
                self.assertNotIn("dp_text", [t.key for t in at.text_area], (flag, gates))
                self.assertIn("login_user", [t.key for t in at.text_input], (flag, gates))
                self.assertNotIn("Decode a 401(k) menu", self._text(at))

    def test_signed_in_tab_goes_to_the_app(self):
        with self._app(state={"user_id": self.uid, "username": "alice",
                              "auto_backfilled": True}) as at:
            self.assertNotIn("dp_text", [t.key for t in at.text_area])

    def test_table_in_the_pasted_order_then_the_one_offer_and_nothing_kept(self):
        before = _counts(self.db)
        with self._app() as at:
            self._describe(at, monthly=300.0)
            table = at.table[0].value
            self.assertEqual(list(table.index), [1, 2, 3, 4])
            self.assertEqual(list(table["As you pasted it"]),
                             ["Zephyr Quiet Harbor Stable Value Fund",
                              "Fidelity 500 Index Fund (FXAIX)",
                              "Acme Pricey Growth Fund",
                              "Vanguard Target Retirement 2050 Fund (VFIFX)"])
            self.assertEqual(list(table["Yearly fee"]), ["0.40%", "0.015%", "1.10%", "0.08%"])
            self.assertIn("Fee on a year of $300 a month", list(table.columns))
            for word in ("best", "cheapest", "recommend"):
                self.assertNotIn(word, table.to_string().lower())
            text = self._text(at)
            self.assertIn("We identified 2 of the 4 funds you pasted", text)
            self.assertIn("It doesn't rank them or say which to choose", text)
            self.assertNotIn("12,345", table.to_string())     # a pasted balance: left out
            # the one offer, after the result
            self.assertIn("Want to keep track of your plan?", text)
            self.assertEqual([b.label for b in at.button if b.key == "dp_signup"],
                             ["Create a free account"])
            self.assertNotIn("dp_overlap", [b.key for b in at.button])
        after = _counts(self.db)
        changed = {t: (before[t], after[t]) for t in after if before.get(t) != after[t]}
        self.assertEqual(changed, {"signups": (0, 1)}, changed)
        c = sqlite3.connect(self.db)
        try:
            (key,) = c.execute("SELECT address_key FROM signups").fetchone()
            dump = "\n".join(c.iterdump())
        finally:
            c.close()
        self.assertEqual(key, dp.address_key(IP))
        for pasted in ("Zephyr Quiet Harbor", "Acme Pricey", IP):
            self.assertNotIn(pasted, dump)

    def test_no_offer_when_nothing_was_found(self):
        with self._app() as at:
            self._describe(at, text="Large Cap\nFixed Income\n")
            self.assertIn("didn't find any fund names", self._text(at))
            self.assertNotIn("dp_signup", [b.key for b in at.button])

    def test_the_offer_opens_create_account(self):
        with self._app() as at:
            self._describe(at)
            at.button(key="dp_signup").click().run()
            self.assertIn("signup_email", [t.key for t in at.text_input])
            self.assertNotIn("dp_text", [t.key for t in at.text_area])
            self.assertEqual(at.session_state["md_paste"], MENU)   # in memory, for later

    def test_the_limit_trips_calmly(self):
        with unittest.mock.patch.object(sys.modules["decoder_public"],
                                        "PER_ADDRESS_PER_HOUR", 2), self._app() as at:
            self._describe(at)
            self._describe(at, text=MENU + "Acme Bond Index\n")
            self.assertEqual(len(at.table), 1)
            self._describe(at, text="Acme Bond Index\n")
            self.assertEqual([i.value for i in at.info], [dp.TOO_MANY_FROM_HERE])
            self.assertEqual(len(at.table), 0)
            self.assertNotIn("dp_signup", [b.key for b in at.button])
            self.assertEqual(at.error, [])
        self.assertEqual(_counts(self.db)["signups"], 2)


# --------------------------------------------------------------------------- #
# the website's explainer page
# --------------------------------------------------------------------------- #
class WebsitePageTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(REPO, "website"))
        import build as site_build
        cls.site = site_build
        # published since the hosting move (flag decoder_public on)
        cls.page = site_build.render(include_held=True)["decode-401k.html"]

    def test_built_listed_and_linking_to_the_route(self):
        self.assertIn("decode-401k.html", self.site.PAGES)
        self.assertEqual(self.site.PAGES["decode-401k.html"][3], "/decode-401k")
        self.assertIn(f'href="{self.site.APP_URL}?decode=401k"', self.page)
        # published: on the site, in the sitemap, linked from every footer
        self.assertNotIn("decode-401k.html", self.site.HELD)
        built = self.site.render()
        self.assertIn("decode-401k.html", built)
        self.assertIn(f"{self.site.SITE_URL}/decode-401k", built["sitemap.xml"])
        self.assertTrue(os.path.exists(os.path.join(REPO, "website", "public",
                                                    "decode-401k.html")))
        for name, page in built.items():
            if name.endswith(".html"):
                self.assertIn('<a href="/decode-401k">Decode your 401(k) menu</a>', page, name)

    def test_calm_and_no_scripts(self):
        self.assertNotIn("<script", self.page.lower())
        self.assertNotIn("style=", self.page)
        main = self.page[self.page.index('<main id="main">'):self.page.index("</main>")]
        text = re.sub(r"<[^>]+>", " ", main).lower()
        for word in ("best", "cheapest", "recommend", "should", "top pick", "winner"):
            self.assertNotIn(word, text, word)
        self.assertIn("doesn't rank the funds or say which to choose", text)
        self.assertIn("nothing you paste is saved", text)
        self.assertIn("not financial advice", text)


if __name__ == "__main__":
    unittest.main()
