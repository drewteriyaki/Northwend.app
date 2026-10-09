"""Explain it to someone (ROADMAP R10; explain_share.py,
views/explain_share.py, flag explain_share).

The share link is the risky part, so most of this file is about it: only
the signed-in owner makes one, for their own account (never an advisor on a
client, never in client mode, never an admin); only the token's hash is
kept; it expires, can be turned off, and at most MAX_ACTIVE work at once;
unknown, expired, turned-off and flag-off links all look the same; opening
one signs nobody in and draws no other page; each visit counts against a
per-address limit. And the page itself is figure-free: a portfolio full of
distinctive numbers, tickers and names is rendered, and none of them may
appear in any element.

    python -m unittest tests.test_explain_share        (from the repo root)
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
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import admin  # noqa: E402
import advisor  # noqa: E402
import auth  # noqa: E402
import context_card  # noqa: E402
import explain_share as xs  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
NEVER = (r"\bshould\b", r"\bbest\b", r"\brecommend", r"\bmust\b", r"\btop\b", r"\bworst\b",
         r"\burgent", r"\bact now\b", r"\bhurry\b", r"\bdeadline\b")

# the distinctive portfolio: none of this may reach the share page
SNAP = "2026-09-30"
ACCOUNT = "Pinecrest Brokerage ...987"
SECRETS_SHOWN_NEVER = (
    "ZQXW", "Zebra Quantum", "YLKB", "Yellowtail Bond", "Pinecrest", "987",
    "4321", "4,321", "98765", "98,765", "123456", "123,456", "55555", "55,555",
    "6543", "6,543", "777777", "777,777", "3333", "3,333", "2033", "Maui", "Quincy",
    "Xylophone", "Rainy Day", "Quartermaine", "zelda.q", "@example", "$",
)


def _position(symbol, desc, asset_type, qty, cost, value):
    row = {c: None for c in portfolio.POSITION_COLS}
    row.update(snapshot_date=SNAP, account=ACCOUNT, symbol=symbol, description=desc,
               asset_type=asset_type, quantity=qty, cost_basis=cost, market_value=value)
    return row


def _seed_zelda(c, name="zelda.q@example.com"):
    uid = auth.create_user(c, name, PW)
    c.execute("UPDATE users SET email = ? WHERE id = ?", (name, uid))
    auth.set_display_name(c, uid, "Zelda Quartermaine")
    portfolio.write_snapshot(
        c, uid, {"snapshot_date": SNAP, "as_of_text": "as of Pinecrest"},
        [_position("ZQXW", "Zebra Quantum Growth Fund", "Equity", 4321.0, 98765.43, 123456.78),
         _position("YLKB", "Yellowtail Bond Fund", "Fixed Income", 6543.0, 40000.0, 43210.0)],
        {ACCOUNT: {"cash_value": 55555.55, "reported_cost_basis": None,
                   "reported_market_value": None, "reported_gain": None,
                   "reported_gain_pct": None}}, "Pinecrest-777777.csv")
    c.commit()
    import accounts
    accounts.set_label(c, uid, ACCOUNT, "Rainy Day Vault")
    advisor.save_profile(c, uid, {"goal": "Retirement", "time_horizon_years": 25,
                                  "notes": "Xylophone notes"})
    plans.save_plan(c, uid, {"goal_type": "Buy a home", "goal_name": "Maui Beach House for Quincy",
                             "target_amount": 777777, "target_date": "2033-06-01",
                             "monthly_contribution": 3333,
                             "target_alloc": {"Stocks": 70, "Bonds": 20, "Cash": 10},
                             "notes": "Xylophone plan"}, uid)
    prefs.save(c, uid, {"drift_threshold": 7.0})
    c.commit()
    return uid


class _DB(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_share_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.c = portfolio.connect(self.db)
        self.env = unittest.mock.patch.dict(os.environ, {"MAIL_DRY_RUN": "1"})
        self.env.start()
        os.environ.pop("NORTHWEND_ADMINS", None)
        self.alice = auth.create_user(self.c, "alice", PW)
        self.bob = auth.create_user(self.c, "bob", PW)

    def tearDown(self):
        self.env.stop()
        self.c.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def dump(self) -> str:
        return "\n".join(sqlite3.connect(self.db).iterdump())


class WordsTests(unittest.TestCase):

    def test_no_should_best_or_recommend(self):
        with open(os.path.join(REPO, "views", "explain_share.py"), encoding="utf-8") as fh:
            view = "\n".join(line for line in fh.read().lower().splitlines()
                             if not line.lstrip().startswith("#"))
        for where, text in (("explain_share.py", xs.all_text().lower()),
                            ("views/explain_share.py", view)):
            for pat in NEVER:
                self.assertNotRegex(text, pat, (where, pat))

    def test_the_fixed_words_carry_no_money(self):
        import recap
        self.assertFalse(recap.has_money(xs.all_text()))
        self.assertNotIn("$", xs.all_text())

    def test_the_inactive_page_says_nothing_about_whose(self):
        for text in (xs.INACTIVE_TITLE, xs.INACTIVE_TEXT):
            self.assertNotRegex(text, r"\{|\bname\b|\bemail\b|expired|revoked|turned off")

    def test_first_name_only_a_name(self):
        self.assertEqual(xs.first_name("Zelda Quartermaine"), "Zelda")
        self.assertEqual(xs.first_name("  Mary-Jo O'Neil"), "Mary-Jo")
        self.assertEqual(xs.first_name("José"), "José")
        for junk in (None, "", "zelda@example.com", "Z3lda", "1234", "$500", "x" * 31,
                     "<b>Zed</b>", "-Ann"):
            self.assertIsNone(xs.first_name(junk), junk)

    def test_clean_page_keeps_only_words_and_whole_percents(self):
        raw = {"mix": [["Stocks", 60], ["Bonds", 40.5], ["ZQXW", 10], ["Cash", "12"],
                       ["Other", 0], ["Stocks", 5]],
               "goals": ["Retirement", "Maui house", "Buy a home"],
               "timeline": "6 to 10 years", "stage": "investing",
               "target": [["Stocks", 70], ["Bonds", 30]], "band": 7,
               "name": "Zelda Q", "amount": 777777, "ticker": "ZQXW"}
        self.assertEqual(xs.clean_page(raw), {
            "mix": [["Stocks", 60]], "goals": ["Retirement", "Buy a home"],
            "timeline": "6 to 10 years", "stage": "investing",
            "target": [["Stocks", 70], ["Bonds", 30]], "band": 7, "name": "Zelda"})
        self.assertEqual(xs.clean_page({"timeline": "2033", "stage": "rich", "band": 7,
                                        "name": "zelda@example.com"}), {})
        self.assertEqual(xs.clean_page("junk"), {})

    def test_lines_in_order(self):
        got = xs.lines({"stage": "investing", "goals": ["Buy a home"],
                        "timeline": "6 to 10 years", "mix": [["Stocks", 60], ["Bonds", 40]],
                        "target": [["Stocks", 70], ["Bonds", 30]], "band": 5})
        self.assertEqual([p for p, _, _ in got], ["stage", "goal", "mix", "target"])
        self.assertEqual(got[1][2], "Buying a home, in 6 to 10 years.")
        self.assertEqual(got[2][2], "Stocks 60%, Bonds 40%.")
        self.assertIn("more than 5 percentage points", got[3][2])
        self.assertEqual(xs.lines({}), [])


class LinkTests(_DB):

    def test_made_by_the_owner_only_the_hash_is_kept(self):
        token = xs.create(self.c, self.alice, by=self.alice)
        self.assertTrue(xs.well_formed(token))
        self.assertGreaterEqual(len(token), 43)          # 32 random bytes: 256 bits
        self.assertNotIn(token, self.dump())             # never the token itself
        self.assertIn(xs.token_hash(token), self.dump())
        found = xs.lookup(self.c, token)
        self.assertEqual((found["user_id"], found["show_name"]), (self.alice, False))
        self.assertEqual(xs.link("https://go.northwend.app/?page=home", token),
                         f"https://go.northwend.app/?share={token}")
        # no one else - not another login, not for someone else's account
        with self.assertRaises(PermissionError):
            xs.create(self.c, self.alice, by=self.bob)
        with self.assertRaises(PermissionError):
            xs.create(self.c, 999, by=999)               # no such account

    def test_an_advisors_client_and_an_admin_cannot_share(self):
        carol = auth.create_user(self.c, "carol", PW)
        auth.set_advisor(self.c, "carol", True)
        dana = auth.create_client(self.c, carol, "dana", name="Dana")
        for who in (dana,):   # client mode: their plan is the advisor's
            with self.assertRaises(PermissionError):
                xs.create(self.c, who, by=who)
        with self.assertRaises(PermissionError):         # an advisor on a client
            xs.create(self.c, dana, by=carol)
        admin.set_admin(self.c, "bob", True)
        with self.assertRaises(PermissionError):
            xs.create(self.c, self.bob, by=self.bob)
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_ADMINS": "alice"}):
            with self.assertRaises(PermissionError):
                xs.create(self.c, self.alice, by=self.alice)
        # an advisor in their own account is a person like any other
        self.assertTrue(xs.create(self.c, carol, by=carol))

    def test_a_link_stops_when_its_account_becomes_a_client_or_admin(self):
        token = xs.create(self.c, self.alice, by=self.alice)
        carol = auth.create_user(self.c, "carol", PW)
        auth.set_advisor(self.c, "carol", True)
        auth.link_client(self.c, carol, self.alice)
        self.assertIsNone(xs.lookup(self.c, token))
        auth.unlink_client(self.c, carol, self.alice)
        self.assertIsNotNone(xs.lookup(self.c, token))
        admin.set_admin(self.c, "alice", True)
        self.assertIsNone(xs.lookup(self.c, token))

    def test_expires_and_lengths(self):
        now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        self.assertEqual(xs.DAYS_CHOICES, (7, 30))
        self.assertEqual(xs.DEFAULT_DAYS, 7)
        week = xs.create(self.c, self.alice, by=self.alice, now=now)
        month = xs.create(self.c, self.alice, by=self.alice, days=30, now=now)
        for days in (0, 1, 31, 365, -7):
            with self.assertRaises(ValueError):
                xs.create(self.c, self.alice, by=self.alice, days=days, now=now)
        at = lambda d: now + timedelta(days=d)  # noqa: E731
        self.assertIsNotNone(xs.lookup(self.c, week, now=at(6.9)))
        self.assertIsNone(xs.lookup(self.c, week, now=at(7)))
        self.assertIsNotNone(xs.lookup(self.c, month, now=at(29)))
        self.assertIsNone(xs.lookup(self.c, month, now=at(30.1)))
        self.assertEqual(len(xs.active(self.c, self.alice, now=at(8))), 1)
        self.assertEqual(xs.prune(self.c, now=at(8)), 1)
        self.assertEqual(xs.prune(self.c, now=at(31)), 1)

    def test_at_most_three_working_links(self):
        now = datetime(2026, 10, 6, tzinfo=timezone.utc)
        for _ in range(xs.MAX_ACTIVE):
            xs.create(self.c, self.alice, by=self.alice, now=now)
        with self.assertRaises(ValueError):
            xs.create(self.c, self.alice, by=self.alice, now=now)
        xs.create(self.c, self.bob, by=self.bob, now=now)       # each account its own
        # once they've ended, new ones can be made (and the ended ones go)
        xs.create(self.c, self.alice, by=self.alice, now=now + timedelta(days=8))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM share_links WHERE user_id = ?",
                                        (self.alice,)).fetchone()[0], 1)

    def test_turned_off_unknown_and_odd_links_look_the_same(self):
        token = xs.create(self.c, self.alice, by=self.alice)
        other = xs.create(self.c, self.bob, by=self.bob)
        link_id = xs.active(self.c, self.alice)[0]["id"]
        bobs = xs.active(self.c, self.bob)[0]["id"]
        self.assertFalse(xs.revoke(self.c, self.alice, bobs))   # not hers
        self.assertIsNotNone(xs.lookup(self.c, other))
        self.assertTrue(xs.revoke(self.c, self.alice, link_id))
        self.assertFalse(xs.revoke(self.c, self.alice, link_id))
        for t in (token, token[:-1] + ("A" if token[-1] != "A" else "B"), "", None, 12345,
                  "x" * 5000, "../../etc", token + "'; DROP TABLE users;--", "a" * 43):
            self.assertIsNone(xs.lookup(self.c, t), t)
        self.assertEqual(xs.revoke_all(self.c, self.bob), 1)
        self.assertIsNone(xs.lookup(self.c, other))

    def test_visits_counted_for_the_owner_only(self):
        token = xs.create(self.c, self.alice, by=self.alice)
        bobs = xs.create(self.c, self.bob, by=self.bob)
        found = xs.lookup(self.c, token)
        xs.note_open(self.c, found["user_id"], found["id"], today=date(2026, 10, 7))
        xs.note_open(self.c, self.bob, found["id"], today=date(2026, 10, 8))   # wrong owner
        row = xs.active(self.c, self.alice)[0]
        self.assertEqual((row["opens"], row["last_opened_on"]), (1, "2026-10-07"))
        self.assertNotIn("token_hash", row)
        self.assertEqual(xs.active(self.c, self.bob)[0]["opens"], 0)
        self.assertIsNotNone(xs.lookup(self.c, bobs))

    def test_the_per_address_limit_is_the_same_for_every_link(self):
        now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        for _ in range(xs.PER_ADDRESS_PER_HOUR):
            self.assertIsNone(xs.take(self.c, "203.0.113.9", now=now))
        self.assertEqual(xs.take(self.c, "203.0.113.9", now=now), xs.TOO_MANY_FROM_HERE)
        self.assertIsNone(xs.take(self.c, "198.51.100.1", now=now))       # another address
        self.assertIsNone(xs.take(self.c, "203.0.113.9", now=now + timedelta(hours=1, seconds=1)))
        keys = [r[0] for r in self.c.execute("SELECT address_key FROM signups")]
        self.assertTrue(all(k.startswith(xs.KEY_PREFIX) for k in keys))
        self.assertNotIn("203.0.113.9", " ".join(keys))                 # hashed, never the address
        with unittest.mock.patch.object(xs, "PER_HOUR", 3):
            self.assertEqual(xs.take(self.c, None, now=now), xs.TOO_MANY_EVERYWHERE)
        # sign-up's own limits never count these
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM signups WHERE ok = 1"
                                        ).fetchone()[0], 0)

    def test_deleted_with_the_account_and_in_its_own_export(self):
        xs.create(self.c, self.alice, by=self.alice, show_name=True)
        xs.create(self.c, self.bob, by=self.bob)
        rows = export.collect(self.c, self.alice)["share_links"]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("token_hash", rows[0])
        self.assertEqual(rows[0]["show_name"], 1)
        self.assertEqual(admin.ACCOUNT_TABLES["share_links"], ("user_id",))
        self.assertTrue(admin.delete_account(self.c, self.alice, by=-1)["ok"])
        self.assertEqual(self.c.execute("SELECT user_id FROM share_links").fetchall()[0][0],
                         self.bob)


class PageTests(_DB):

    def test_the_page_from_a_distinctive_portfolio_is_figure_free(self):
        uid = _seed_zelda(self.c)
        today = date(2026, 10, 6)
        got = xs.page(self.c, uid, show_name=True, today=today)
        months = plans.months_until("2033-06-01", today)
        self.assertEqual(got["goals"], ["Buy a home"])
        self.assertEqual(got["timeline"], context_card.timeline_of(months / 12))
        self.assertEqual(got["stage"], "investing")
        self.assertEqual(got["target"], [["Stocks", 70], ["Bonds", 20], ["Cash", 10]])
        self.assertEqual(got["band"], 7)
        self.assertEqual(got["name"], "Zelda")
        self.assertEqual({k for k, _ in got["mix"]}, {"Stocks", "Bonds", "Cash"})
        self.assertEqual(sum(v for _, v in got["mix"]), 100)
        text = repr(got) + repr(xs.lines(got)) + xs.title(got)
        for secret in SECRETS_SHOWN_NEVER:
            self.assertNotIn(secret, text)
        self.assertNotIn("Zelda", repr(xs.page(self.c, uid, today=today)))   # off by default

    def test_the_example_portfolio_is_never_shown_as_theirs(self):
        sample_data.load(self.c, self.alice)
        got = xs.page(self.c, self.alice)
        self.assertNotIn("mix", got)
        self.assertNotEqual(got.get("stage"), "investing")

    def test_the_profiles_goal_when_there_is_no_plan(self):
        advisor.save_profile(self.c, self.alice, {"goal": "Retirement; Big yacht",
                                                  "time_horizon_years": 15})
        got = xs.page(self.c, self.alice)
        self.assertEqual(got["goals"], ["Retirement"])
        self.assertEqual(got["timeline"], "11 to 20 years")


class NeverSharedTests(unittest.TestCase):

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", "meeting.py", "reports.py", "overview.py",
                     "advising.py", "proposals.py", "weekly_email.py", "client_plan.py",
                     os.path.join("views", "assistant.py"), os.path.join("views", "clients.py"),
                     os.path.join("views", "meeting.py"), os.path.join("views", "reports.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("explain_share", text, name)
            self.assertNotIn("share_links", text, name)
        with open(os.path.join(REPO, "export.py"), encoding="utf-8") as fh:
            record = fh.read().split("def client_record", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("share_links", record)
        # the page and the module never print or log anything
        for name in ("explain_share.py", os.path.join("views", "explain_share.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotRegex(src, r"\bprint\(|\blogging\b|\blogger\b|st\.write\(token")

    def test_the_flag_is_off_unless_set(self):
        self.assertEqual(flags.FEATURES["explain_share"], {"gates": (), "view": None})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("explain_share"))
            self.assertTrue(flags.view_on("explain_share"))   # loads anyway: the inactive page
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "explain_share"}):
            self.assertTrue(flags.on("explain_share"))


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
def _strings(msg, out):
    """Every string in a protobuf message, nested ones too (as they are, unescaped)."""
    for _field, value in msg.ListFields():
        repeated = (hasattr(value, "__iter__") and not isinstance(value, (str, bytes))
                    and not hasattr(value, "ListFields"))
        values = value if repeated else [value]
        for v in values:
            if isinstance(v, str):
                out.append(v)
            elif hasattr(v, "ListFields"):
                _strings(v, out)


def _tree_text(at) -> str:
    """Every string in every element drawn - bodies, labels, help, options, values."""
    out = []

    def walk(node):
        proto = getattr(node, "proto", None)
        if proto is not None and hasattr(proto, "ListFields"):
            _strings(proto, out)
        for child in (getattr(node, "children", None) or {}).values():
            walk(child)
    walk(at._tree)
    # the app's own stylesheet and scripts (st.html) and Streamlit's internal
    # widget ids ("$$ID-<hash>-<key>") aren't the page's words
    return "\n".join(s for s in out
                     if not s.lstrip().startswith(("<style", "<script", "$$ID-")))


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_share_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.zelda = _seed_zelda(c)
            cls.bob = auth.create_user(c, "bob", PW)
            sample_data.load(c, cls.bob)
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            auth.link_client(c, cls.carol, cls.dana)
            cls.root = auth.create_user(c, "root", PW)
            admin.set_admin(c, "root", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.root, secret, two_step.totp(secret))
            cls.root_ok = f"{cls.root}:{two_step.status(c, cls.root)['stamp']}"
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        c = portfolio.connect(self.db)
        try:
            c.execute("DELETE FROM share_links")
            c.execute("DELETE FROM signups")
            c.commit()
        finally:
            c.close()

    @contextlib.contextmanager
    def _app(self, uid=None, name=None, *, flag="explain_share", share=None, page="Life",
             **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        if uid is not None:
            for k, v in {"user_id": uid, "username": name, "page": page,
                         "auto_backfilled": True, **state}.items():
                at.session_state[k] = v
        if share is not None:
            at.query_params[xs.QUERY] = share
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _make(self, uid, **kw):
        c = portfolio.connect(self.db)
        try:
            return xs.create(c, uid, by=uid, **kw)
        finally:
            c.close()

    def _q(self, sql, args=()):
        c = portfolio.connect(self.db)
        try:
            return [tuple(r) for r in c.execute(sql, args)]
        finally:
            c.close()

    @staticmethod
    def _keys(at):
        return [b.key for b in at.button]

    # ---- the owner ------------------------------------------------------------ #
    def test_the_owner_makes_sees_once_and_turns_off_a_link(self):
        with self._app(self.zelda, "zelda.q@example.com") as at:
            text = _tree_text(at)
            self.assertIn(xs.OWNER_TITLE, text)
            self.assertIn("Show my first name (Zelda)", text)
            self.assertFalse(at.checkbox(key="xs_name").value)        # off by default
            self.assertEqual(at.selectbox(key="xs_days").value, 7)    # the shorter
            at.button(key="xs_make").click().run()
            new = at.session_state["xs_new"]
            self.assertRegex(new, r"\?share=[A-Za-z0-9_-]{43}$")
            self.assertIn(new, _tree_text(at))                       # shown, once made
            token = new.rsplit("=", 1)[1]
            self.assertTrue(re.search(r"opened|not opened yet", _tree_text(at)))
            at.button(key="xs_done").click().run()
            self.assertNotIn(token, _tree_text(at))                  # gone after Done
        rows = self._q("SELECT id, user_id, token_hash, show_name FROM share_links")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:], (self.zelda, xs.token_hash(token), 0))
        c = sqlite3.connect(self.db)
        try:
            self.assertNotIn(token, "\n".join(c.iterdump()))
        finally:
            c.close()
        # turned off from the same place
        with self._app(self.zelda, "zelda.q@example.com") as at:
            at.button(key=f"xs_off_{rows[0][0]}").click().run()
            self.assertIn("That link is turned off", _tree_text(at))
        self.assertEqual(self._q("SELECT id FROM share_links"), [])
        with self._app(share=token) as at:
            self.assertIn(xs.INACTIVE_TITLE, _tree_text(at))

    def test_three_at_most_in_the_app(self):
        for _ in range(xs.MAX_ACTIVE):
            self._make(self.zelda)
        with self._app(self.zelda, "zelda.q@example.com") as at:
            self.assertTrue(at.button(key="xs_make").disabled)
            self.assertIn(xs.TOO_MANY, _tree_text(at))
            at.button(key="xs_off_all").click().run()
            self.assertFalse(at.button(key="xs_make").disabled)
        self.assertEqual(self._q("SELECT id FROM share_links"), [])

    def test_never_for_an_advisor_on_a_client_a_client_or_an_admin(self):
        for uid, name, state in (
                (self.carol, "carol", {"two_step_ok": self.carol_ok,
                                       "active_user_id": self.dana, "page": "Account"}),
                (self.carol, "carol", {"two_step_ok": self.carol_ok,   # (no Life here)
                                       "active_user_id": self.dana, "page": "Life"}),
                (self.dana, "dana", {}),
                (self.root, "root", {"two_step_ok": self.root_ok})):
            with self.subTest(name), self._app(uid, name, **state) as at:
                self.assertNotIn(xs.OWNER_TITLE, _tree_text(at))
                self.assertNotIn("xs_make", self._keys(at))
        # an advisor on their own portfolio has it on Life, as a person - not on Account
        with self._app(self.carol, "carol", page="Life", two_step_ok=self.carol_ok) as at:
            self.assertIn("xs_make", self._keys(at))
        with self._app(self.carol, "carol", page="Account", two_step_ok=self.carol_ok) as at:
            self.assertNotIn("xs_make", self._keys(at))

    def test_off_no_section_and_existing_links_stop(self):
        token = self._make(self.zelda)
        with self._app(self.zelda, "zelda.q@example.com", flag="") as at:
            self.assertNotIn(xs.OWNER_TITLE, _tree_text(at))
        with self._app(share=token, flag="") as at:
            text = _tree_text(at)
            self.assertIn(xs.INACTIVE_TITLE, text)
            self.assertNotIn("Buying a home", text)
        self.assertEqual(self._q("SELECT opens FROM share_links"), [(0,)])
        self.assertEqual(self._q("SELECT * FROM signups"), [])      # not even counted

    # ---- the viewer --------------------------------------------------------- #
    def test_opened_without_signing_in_figure_free_and_nothing_else(self):
        token = self._make(self.zelda, show_name=True)
        sessions = self._q("SELECT COUNT(*) FROM login_sessions")
        with self._app(share=token) as at:
            text = _tree_text(at)
            self.assertIn("Zelda's plan, in plain words", text)
            self.assertIn("Buying a home", text)
            self.assertIn("Stocks 70%, Bonds 20%, Cash 10%", text)
            self.assertIn("more than 7 percentage points", text)
            self.assertIn(xs.LEARN_BUTTON, text)
            for secret in SECRETS_SHOWN_NEVER:
                self.assertNotIn(secret, text, secret)
            self.assertNotIn("Quartermaine", repr(at.session_state.to_dict()))
            # nobody signed in, no menu, no other page
            self.assertNotIn("user_id", at.session_state)
            self.assertEqual(len(at.sidebar.children), 0)
            self.assertNotIn("login_form", text)
            self.assertNotIn(token, repr(at.session_state.to_dict()))    # only its hash
            at.run()                                                  # a rerun: one visit
            self.assertEqual(self._q("SELECT opens FROM share_links"), [(1,)])
            # the one way on: Create account, the link left behind
            at.button(key="xs_learn").click().run()
            self.assertNotIn(xs.QUERY, at.query_params)
            self.assertTrue(at.session_state["show_signup"])
            self.assertNotIn("user_id", at.session_state)
        self.assertEqual(self._q("SELECT COUNT(*) FROM login_sessions"), sessions)
        self.assertEqual(self._q("SELECT opens, last_opened_on FROM share_links"),
                         [(1, datetime.now(timezone.utc).date().isoformat())])

    def test_the_name_is_off_unless_ticked(self):
        token = self._make(self.zelda)
        with self._app(share=token) as at:
            text = _tree_text(at)
            self.assertIn(xs.PAGE_TITLE, text)
            self.assertNotIn("Zelda", text)

    def test_signed_in_someone_else_sees_only_the_page(self):
        token = self._make(self.zelda)
        with self._app(self.bob, "bob", share=token) as at:
            text = _tree_text(at)
            self.assertIn("Buying a home", text)
            self.assertNotIn(xs.OWNER_TITLE, text)
            self.assertEqual(len(at.sidebar.children), 0)
            self.assertEqual(at.session_state["user_id"], self.bob)   # unchanged
            at.button(key="xs_learn").click().run()                   # back to his own
            self.assertNotIn(xs.QUERY, at.query_params)

    def test_expired_unknown_and_odd_links_look_the_same(self):
        old = self._make(self.zelda)
        self._q("SELECT 1")
        c = portfolio.connect(self.db)
        try:
            c.execute("UPDATE share_links SET expires_at = '2026-01-01T00:00:00Z'")
            c.commit()
        finally:
            c.close()
        pages = []
        for t in (old, "A" * 43, "not-a-token", ""):
            with self._app(share=t) as at:
                body = [m.value for m in at.markdown] + [t_.value for t_ in at.title]
                pages.append(body)
                self.assertIn(xs.INACTIVE_TITLE, " ".join(body))
        self.assertTrue(all(p == pages[0] for p in pages), pages)

    def test_too_many_from_here(self):
        token = self._make(self.zelda)
        c = portfolio.connect(self.db)   # the app-wide hour is full
        try:
            stamp = auth._utc(datetime.now(timezone.utc))
            c.executemany("INSERT INTO signups (address_key, created_at, ok) VALUES (?, ?, 0)",
                          [(f"{xs.KEY_PREFIX}{i}", stamp) for i in range(xs.PER_HOUR)])
            c.commit()
        finally:
            c.close()
        with self._app(share=token) as at:
            text = _tree_text(at)
            self.assertIn(xs.TOO_MANY_EVERYWHERE, text)
            self.assertNotIn("Buying a home", text)
        self.assertEqual(self._q("SELECT opens FROM share_links"), [(0,)])


if __name__ == "__main__":
    unittest.main()
