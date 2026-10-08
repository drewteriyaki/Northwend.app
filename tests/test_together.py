"""Doing it together (together.py, views/together.py, flag together).

Two people pair up and each sees three habit facts about the other. The
tests are mostly about what must never happen: anything but the three facts
crossing over, a pairing without both yeses recorded word for word, a link
kept in readable form or working past its time, sharing that survives a
stop, a nudge more than once a week or to someone who turned them off, and
any of it for an advisor, an admin or client mode.

    python -m unittest tests.test_together        (from the repo root)
"""

import contextlib
import os
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

import admin  # noqa: E402
import advisor  # noqa: E402
import auth  # noqa: E402
import consent  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import rate_limits  # noqa: E402
import recap  # noqa: E402
import sample_data  # noqa: E402
import together as tg  # noqa: E402
import two_step  # noqa: E402
import unsubscribe  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
TODAY = NOW.date()
NEVER = (r"\bshould\b", r"\bbest\b", r"\brecommend", r"\bmust\b", r"\burgent", r"\bhurry\b")
# a partner full of distinctive things: none of it may cross over
SECRETS = ("ZQXW", "Zebra Quantum", "Pinecrest", "987", "4321", "98765", "123456", "55555",
           "777777", "Maui", "Quincy", "Xylophone", "Rainy Day", "zelda.q", "@example",
           "Retirement", "Buy a home", "Stocks", "2033")


def _seed_rich(c, login="zelda.q@example.com", name="Zelda Quartermaine"):
    """An account with holdings, a plan, a goal, notes and settings."""
    uid = auth.create_user(c, login, PW)
    c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
              (login, "2026-09-01 10:00:00", uid))
    auth.set_display_name(c, uid, name)
    row = {k: None for k in portfolio.POSITION_COLS}
    row.update(snapshot_date="2026-09-30", account="Pinecrest Brokerage ...987", symbol="ZQXW",
               description="Zebra Quantum Growth Fund", asset_type="Equity", quantity=4321.0,
               cost_basis=98765.43, market_value=123456.78)
    portfolio.write_snapshot(c, uid, {"snapshot_date": "2026-09-30", "as_of_text": None}, [row],
                             {"Pinecrest Brokerage ...987": {
                                 "cash_value": 55555.55, "reported_cost_basis": None,
                                 "reported_market_value": None, "reported_gain": None,
                                 "reported_gain_pct": None}}, "Pinecrest-777777.csv")
    c.commit()
    advisor.save_profile(c, uid, {"goal": "Retirement", "notes": "Xylophone notes"})
    plans.save_plan(c, uid, {"goal_type": "Buy a home", "goal_name": "Maui House for Quincy",
                             "target_amount": 777777, "target_date": "2033-06-01",
                             "target_alloc": {"Stocks": 70, "Bonds": 30},
                             "notes": "Xylophone plan"}, uid)
    prefs.save(c, uid, {
        "drift_threshold": 7.0, "note": "Rainy Day",
        recap.LEARN_DATES: {"basics": "2026-10-02", "goal": "2026-09-20"},
        recap.LEARN_READS: {"basics:fees": "2026-10-02", "basics:time": "2026-10-05"},
        "teach_back": {"funds": {"held": True, "on": "2026-10-06"}},
        "checkin_log": ["2026-08", "2026-10"],
        "walk_verdicts": {"2026-10": {"kind": "next", "class": "Stocks", "on": "2026-10-03"}},
        "gear_seen": ["map", "tent", "not-a-gear"]})
    return uid


class _DB(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_together_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.c = portfolio.connect(self.db)
        self.env = unittest.mock.patch.dict(os.environ, {"MAIL_DRY_RUN": "1"})
        self.env.start()
        os.environ.pop("NORTHWEND_ADMINS", None)
        self.zelda = _seed_rich(self.c)
        self.robin = auth.create_user(self.c, "robin", PW)
        auth.set_display_name(self.c, self.robin, "Robin")
        self.c.execute("UPDATE users SET email = 'robin@example.org', email_verified_at = "
                       "'2026-09-01 10:00:00' WHERE id = ?", (self.robin,))
        self.c.commit()

    def tearDown(self):
        self.env.stop()
        self.c.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def dump(self) -> str:
        c = sqlite3.connect(self.db)
        try:
            return "\n".join(c.iterdump())
        finally:
            c.close()

    def pair(self, inviter, invitee, now=NOW):
        token = tg.invite(self.c, inviter, by=inviter, now=now)
        found = tg.find_invite(self.c, tg.token_hash(token), now=now)
        tg.accept(self.c, tg.token_hash(token), invitee, by=invitee,
                  text_shown=tg.join_text(found["name"]), now=now)
        return token

    def records(self):
        return [dict(r) for r in self.c.execute(
            "SELECT client_id, advisor_id, kind, scope, text_shown, text_sha256, how, at "
            "FROM consent_records ORDER BY id")]


class WordsTests(unittest.TestCase):

    def test_plain_calm_words(self):
        text = tg.all_text()
        for pattern in NEVER:
            self.assertNotRegex(text.lower(), pattern)
        self.assertFalse(recap.has_money(text))

    def test_the_nudge_says_only_that_the_walk_is_waiting(self):
        self.assertEqual(tg.NUDGE_SUBJECT, "Your walk is waiting")
        body = "\n".join(tg.NUDGE_LINES)
        self.assertFalse(recap.has_money(body))
        self.assertNotRegex(body, r"\{|%")   # nothing filled in: no names, no figures

    def test_the_consent_words_say_what_is_and_isnt_shared(self):
        for words in (tg.INVITE_CONSENT, tg.join_text("Sam")):
            for part in ("learned something this month", "this month's walk", "wins",
                         "Never your amounts, holdings, goals or accounts",
                         "Your walk is waiting", "stop sharing at any time"):
                self.assertIn(part, words)
        self.assertTrue(tg.join_text("Sam").startswith("Sam invited you"))


class FactsTests(_DB):

    def test_only_the_three_facts_cross_over(self):
        self.pair(self.zelda, self.robin)
        seen = tg.for_partner(self.c, self.robin, self.zelda, today=TODAY)
        self.assertEqual(set(seen), set(tg.FACTS))
        self.assertEqual(seen, {"learn_days": 3, "walk_done": True, "wins": 2})
        self.assertIsInstance(seen["learn_days"], int)
        self.assertIsInstance(seen["walk_done"], bool)
        self.assertIsInstance(seen["wins"], int)
        text = repr(seen) + repr(tg.partners(self.c, self.robin))
        for secret in SECRETS:
            self.assertNotIn(secret, text, secret)
        # no money, holding, goal or account field, whatever its name
        for key in seen:
            self.assertNotRegex(key, r"value|amount|cost|price|holding|symbol|account|goal|plan")
        # the partner list: a first name (letters only), never the login or email
        self.assertEqual([p["name"] for p in tg.partners(self.c, self.robin)], ["Zelda"])

    def test_how_each_fact_is_worked_out(self):
        p = {recap.LEARN_DATES: {"a": "2026-10-01", "b": "2026-09-30"},
             recap.LEARN_READS: {"r": "2026-10-01", "s": "2026-10-09"},   # the 9th is ahead
             "teach_back": {"funds": {"held": False, "on": "2026-10-04"}},
             tg.MINUTE_PREF: {"days": ["2026-10-05", "2026-10-04"], "streak": 2},
             "checkin_log": ["2026-09"], "gear_seen": ["map"], tg.WINS_PREF: ["a", "b", "c"]}
        self.assertEqual(tg.facts_from(p, TODAY),
                         {"learn_days": 3, "walk_done": False, "wins": 3})
        self.assertEqual(tg.facts_from({}, TODAY),
                         {"learn_days": 0, "walk_done": False, "wins": 0})
        self.assertEqual(tg.facts_from(None, TODAY)["wins"], 0)

    def test_the_page_reads_a_partner_only_through_for_partner(self):
        with open(os.path.join(REPO, "views", "together.py"), encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("prefs.load", "current_holdings", "plans.", "SELECT", "facts_from(c",
                       "facts_from(conn", "partner_id\"]))"):
            self.assertNotIn(banned, src, banned)
        self.assertIn("tg.for_partner(conn, LOGIN_ID", src)
        # the page's own facts come from its own settings only
        self.assertIn("tg.facts_from(_read_prefs(), today)", src)

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "meeting.py", "reports.py", "overview.py", "advising.py",
                     "proposals.py", "weekly_email.py", "client_plan.py",
                     os.path.join("views", "assistant.py"), os.path.join("views", "clients.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("together_pairs", text, name)
            self.assertNotIn("import together", text, name)
        for name in ("together.py", os.path.join("views", "together.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotRegex(fh.read(), r"\bprint\(|\blogging\b|\blogger\b")


class LinkTests(_DB):

    def test_only_the_hash_is_kept_and_the_link_works_once(self):
        token = tg.invite(self.c, self.zelda, by=self.zelda, now=NOW)
        self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")
        dump = self.dump()
        self.assertNotIn(token, dump)
        self.assertIn(tg.token_hash(token), dump)
        self.assertRegex(tg.link("https://go.northwend.app/?page=life", token),
                         r"^https://go\.northwend\.app/\?together=[A-Za-z0-9_-]{43}$")
        found = tg.find_invite(self.c, tg.token_hash(token), now=NOW)
        self.assertEqual((found["user_id"], found["name"]), (self.zelda, "Zelda"))
        tg.accept(self.c, tg.token_hash(token), self.robin, by=self.robin,
                  text_shown=tg.join_text("Zelda"), now=NOW)
        self.assertEqual(self.c.execute("SELECT COUNT(*) AS n FROM together_invites")
                         .fetchone()["n"], 0)
        with self.assertRaises(ValueError) as e:      # used once
            tg.accept(self.c, tg.token_hash(token), self.robin, by=self.robin,
                      text_shown="x", now=NOW)
        self.assertEqual(str(e.exception), tg.LINK_GONE)

    def test_expires_after_seven_days_and_is_tidied(self):
        token = tg.invite(self.c, self.zelda, by=self.zelda, now=NOW)
        late = NOW + timedelta(days=tg.INVITE_DAYS, minutes=1)
        self.assertIsNotNone(tg.find_invite(self.c, tg.token_hash(token),
                                            now=NOW + timedelta(days=6)))
        self.assertIsNone(tg.find_invite(self.c, tg.token_hash(token), now=late))
        with self.assertRaises(ValueError):
            tg.accept(self.c, tg.token_hash(token), self.robin, by=self.robin,
                      text_shown="x", now=late)
        self.assertEqual(tg.prune(self.c, now=late), 1)
        for odd in ("", "x" * 64, tg.token_hash(token).upper(), None, 5):
            self.assertIsNone(tg.find_invite(self.c, odd, now=NOW))

    def test_both_yeses_recorded_word_for_word(self):
        made = NOW - timedelta(days=2)
        token = tg.invite(self.c, self.zelda, by=self.zelda, now=made)
        words = tg.join_text("Zelda")
        tg.accept(self.c, tg.token_hash(token), self.robin, by=self.robin, text_shown=words,
                  now=NOW)
        rows = self.records()
        self.assertEqual(len(rows), 2)
        inviter, invitee = rows
        self.assertEqual((inviter["client_id"], inviter["advisor_id"], inviter["kind"],
                          inviter["scope"], inviter["how"], inviter["text_shown"]),
                         (self.zelda, self.robin, "grant", "together", "together_invite",
                          tg.INVITE_CONSENT))
        self.assertEqual(inviter["at"], "2026-10-05T15:00:00Z")    # when the link was made
        self.assertEqual((invitee["client_id"], invitee["advisor_id"], invitee["how"],
                          invitee["text_shown"]),
                         (self.robin, self.zelda, "together_join", words))
        for r in rows:
            self.assertEqual(r["text_sha256"], consent.text_sha256(r["text_shown"]))
        self.assertIn("together", consent.SCOPES)
        for how in (tg.HOW_INVITE, tg.HOW_JOIN, tg.HOW_STOP, tg.HOW_ENDED):
            self.assertIn(how, consent.HOWS)
        with self.assertRaises(ValueError):    # a yes needs the words
            tg.accept(self.c, "0" * 64, self.robin, by=self.robin, text_shown=" ")

    def test_only_the_signed_in_person_and_not_their_own_link(self):
        with self.assertRaises(PermissionError):
            tg.invite(self.c, self.zelda, by=self.robin)
        token = tg.invite(self.c, self.zelda, by=self.zelda, now=NOW)
        with self.assertRaises(PermissionError):
            tg.accept(self.c, tg.token_hash(token), self.robin, by=self.zelda,
                      text_shown="x", now=NOW)
        with self.assertRaises(ValueError) as e:
            tg.accept(self.c, tg.token_hash(token), self.zelda, by=self.zelda,
                      text_shown="x", now=NOW)
        self.assertEqual(str(e.exception), tg.OWN_LINK)
        self.assertEqual(self.records(), [])

    def test_at_most_three(self):
        others = [auth.create_user(self.c, f"p{i}", PW) for i in range(4)]
        for o in others[:2]:
            self.pair(self.zelda, o)
        tg.invite(self.c, self.zelda, by=self.zelda, now=NOW)      # the third place
        self.assertEqual(tg.room(self.c, self.zelda, now=NOW), 0)
        with self.assertRaises(ValueError):
            tg.invite(self.c, self.zelda, by=self.zelda, now=NOW)
        # someone full can't join another
        token = tg.invite(self.c, others[3], by=others[3], now=NOW)
        with self.assertRaises(ValueError) as e:
            tg.accept(self.c, tg.token_hash(token), self.zelda, by=self.zelda,
                      text_shown="x", now=NOW)
        self.assertEqual(str(e.exception), tg.FULL)


class EligibilityTests(_DB):

    def setUp(self):
        super().setUp()
        self.carol = auth.create_user(self.c, "carol", PW)
        auth.set_advisor(self.c, "carol", True)
        self.dana = auth.create_user(self.c, "dana", PW)
        auth.link_client(self.c, self.carol, self.dana)
        self.root = auth.create_user(self.c, "root", PW)
        admin.set_admin(self.c, "root", True)
        self.c.commit()

    def test_never_an_advisor_a_client_or_an_admin(self):
        for uid in (self.carol, self.dana, self.root):
            self.assertFalse(tg.eligible(self.c, uid))
            with self.assertRaises(PermissionError):
                tg.invite(self.c, uid, by=uid)
            token = tg.invite(self.c, self.zelda, by=self.zelda, now=NOW)
            with self.assertRaises(PermissionError):
                tg.accept(self.c, tg.token_hash(token), uid, by=uid, text_shown="x", now=NOW)
        self.assertTrue(tg.eligible(self.c, self.zelda))
        # an advisor's or admin's link never works
        self.assertIsNone(tg.find_invite(self.c, "f" * 64))

    def test_a_partner_who_becomes_a_client_shows_nothing(self):
        self.pair(self.zelda, self.robin)
        auth.link_client(self.c, self.carol, self.zelda)
        with self.assertRaises(PermissionError):
            tg.for_partner(self.c, self.robin, self.zelda, today=TODAY)
        with self.assertRaises(PermissionError):
            tg.for_partner(self.c, self.zelda, self.robin, today=TODAY)
        # and either can still stop
        self.assertTrue(tg.stop(self.c, self.zelda, self.robin, by=self.zelda))


class StopTests(_DB):

    def test_one_step_ends_it_for_both(self):
        self.pair(self.zelda, self.robin)
        self.assertEqual(tg.for_partner(self.c, self.zelda, self.robin, today=TODAY)["wins"], 0)
        with self.assertRaises(PermissionError):
            tg.stop(self.c, self.zelda, self.robin, by=self.robin)
        self.assertTrue(tg.stop(self.c, self.robin, self.zelda, by=self.robin, now=NOW))
        self.assertEqual(tg.partners(self.c, self.robin), [])
        self.assertEqual(tg.partners(self.c, self.zelda), [])
        for a, b in ((self.robin, self.zelda), (self.zelda, self.robin)):
            with self.assertRaises(PermissionError):
                tg.for_partner(self.c, a, b, today=TODAY)
            self.assertFalse(consent.current(self.c, a, b, "together"))
        ends = [(r["client_id"], r["how"]) for r in self.records() if r["kind"] == "revoke"]
        self.assertEqual(sorted(ends), sorted([(self.robin, "together_stop"),
                                               (self.zelda, "together_ended")]))
        self.assertFalse(tg.stop(self.c, self.zelda, self.robin, by=self.zelda))
        # the record on each side, by first name, never the login
        self.assertEqual({r["name"] for r in tg.history(self.c, self.robin)}, {"Zelda"})

    def test_deleting_an_account_ends_it_and_keeps_the_records(self):
        self.pair(self.zelda, self.robin)
        tg.invite(self.c, self.robin, by=self.robin, now=NOW)
        self.assertTrue(admin.delete_account(self.c, self.zelda, by=-1)["ok"])
        self.assertEqual(tg.partners(self.c, self.robin), [])
        self.assertEqual(self.c.execute("SELECT COUNT(*) AS n FROM together_pairs")
                         .fetchone()["n"], 0)
        self.assertEqual(sorted(r["how"] for r in self.records() if r["kind"] == "revoke"),
                         ["account_deleted", "account_deleted"])
        self.assertTrue(admin.delete_account(self.c, self.robin, by=-1)["ok"])
        self.assertEqual(self.c.execute("SELECT COUNT(*) AS n FROM together_invites")
                         .fetchone()["n"], 0)

    def test_in_the_tables_lists_and_the_own_export(self):
        self.assertEqual(admin.ACCOUNT_TABLES["together_pairs"], ("user_id", "partner_id"))
        self.assertEqual(admin.ACCOUNT_TABLES["together_invites"], ("user_id",))
        self.pair(self.zelda, self.robin)
        tg.invite(self.c, self.robin, by=self.robin, now=NOW)
        got = export.collect(self.c, self.robin)
        self.assertEqual(len(got["doing_it_together"]), 1)
        self.assertNotIn("partner_id", got["doing_it_together"][0])
        self.assertEqual(len(got["together_invitations"]), 1)
        self.assertNotIn("token_hash", got["together_invitations"][0])
        for secret in SECRETS:
            self.assertNotIn(secret, repr(got["doing_it_together"]))


class NudgeTests(_DB):

    def setUp(self):
        super().setUp()
        self.pair(self.zelda, self.robin)   # robin hasn't walked; zelda has
        self.sent = []

    def send(self, to, link, unsub):
        self.sent.append((to, link, unsub))
        return True

    def nudge(self, sender, partner, now=NOW):
        return tg.nudge(self.c, sender, partner, by=sender, app_url="https://go.example/",
                        send=self.send, now=now, today=now.date())

    def test_once_a_week_per_person_per_partner(self):
        self.assertEqual(self.nudge(self.zelda, self.robin), (True, tg.NUDGE_SENT))
        to, link, unsub = self.sent[0]
        self.assertEqual(to, "robin@example.org")
        self.assertEqual(link, "https://go.example/?page=dashboard")
        self.assertRegex(unsub, r"^https://go\.example/\?unsubscribe=")
        ok, words = self.nudge(self.zelda, self.robin, NOW + timedelta(days=6))
        self.assertFalse(ok)
        self.assertEqual(words, tg.NUDGE_WAIT.format(day="Oct 14"))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.nudge(self.zelda, self.robin, NOW + timedelta(days=7, minutes=1))[0])
        # someone who has walked this month gets none
        self.assertEqual(self.nudge(self.robin, self.zelda), (False, ""))

    def test_off_when_they_turned_nudges_off_and_the_unsubscribe_link(self):
        p = prefs.load(self.c, self.robin)
        prefs.save(self.c, self.robin, tg.set_nudges(p, False))
        self.assertEqual(self.nudge(self.zelda, self.robin), (False, tg.NUDGE_OFF))
        self.assertEqual(self.sent, [])
        prefs.save(self.c, self.robin, tg.set_nudges(prefs.load(self.c, self.robin), True))
        self.assertTrue(self.nudge(self.zelda, self.robin)[0])
        token = self.sent[0][2].rsplit("=", 1)[1]
        self.assertEqual(unsubscribe.use(self.c, token), {"ok": True, "kind": "together"})
        self.assertFalse(tg.nudges_on(prefs.load(self.c, self.robin)))
        self.assertEqual(unsubscribe.WHERE["together"], "Life, under Doing it together")

    def test_only_to_a_confirmed_email_and_only_when_paired(self):
        self.c.execute("UPDATE users SET email_verified_at = NULL WHERE id = ?", (self.robin,))
        self.c.commit()
        self.assertEqual(self.nudge(self.zelda, self.robin), (False, tg.NUDGE_NO_EMAIL))
        other = auth.create_user(self.c, "other", PW)
        with self.assertRaises(PermissionError):
            self.nudge(self.zelda, other)
        with self.assertRaises(PermissionError):
            tg.nudge(self.c, self.zelda, self.robin, by=self.robin, app_url="x", send=self.send)
        self.assertEqual(self.sent, [])

    def test_rate_limited(self):
        others = []
        for i in range(2):
            o = auth.create_user(self.c, f"o{i}", PW)
            self.c.execute("UPDATE users SET email = ?, email_verified_at = '2026-09-01' "
                           "WHERE id = ?", (f"o{i}@example.org", o))
            self.c.commit()
            self.pair(self.zelda, o)
            others.append(o)
        with unittest.mock.patch.dict(rate_limits.LIMITS, {rate_limits.NUDGE: (2, 10)}):
            self.assertTrue(self.nudge(self.zelda, self.robin)[0])
            self.assertTrue(self.nudge(self.zelda, others[0])[0])
            self.assertEqual(self.nudge(self.zelda, others[1]), (False, rate_limits.CALM))
        self.assertEqual(len(self.sent), 2)

    def test_the_email_goes_through_mailer_with_no_figures(self):
        with unittest.mock.patch("mailer.send", return_value=True) as sent:
            self.assertTrue(tg.nudge_email("robin@example.org", "https://go.example/?page=x",
                                           "https://go.example/?unsubscribe=abc"))
        (to, subject, text, html), kw = sent.call_args
        self.assertEqual((to, subject), ("robin@example.org", "Your walk is waiting"))
        self.assertFalse(recap.has_money(text))
        self.assertNotIn("Zelda", text + html)
        self.assertIn("List-Unsubscribe", kw["headers"])
        # dry run: logged, nothing sent
        self.assertTrue(tg.nudge_email("robin@example.org", "https://go.example/"))


class FlagTests(unittest.TestCase):

    def test_off_unless_set(self):
        self.assertEqual(flags.FEATURES["together"], {"gates": (), "view": "together"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("together"))
            self.assertFalse(flags.view_on("together"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "together"}):
            self.assertTrue(flags.on("together"))


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
def _strings(msg, out):
    for _field, value in msg.ListFields():
        repeated = (hasattr(value, "__iter__") and not isinstance(value, (str, bytes))
                    and not hasattr(value, "ListFields"))
        for v in (value if repeated else [value]):
            if isinstance(v, str):
                out.append(v)
            elif hasattr(v, "ListFields"):
                _strings(v, out)


def _tree_text(at) -> str:
    out = []

    def walk(node):
        proto = getattr(node, "proto", None)
        if proto is not None and hasattr(proto, "ListFields"):
            _strings(proto, out)
        for child in (getattr(node, "children", None) or {}).values():
            walk(child)
    walk(at._tree)
    return "\n".join(s for s in out
                     if not s.lstrip().startswith(("<style", "<script", "$$ID-")))


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_together_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.zelda = _seed_rich(c)
            cls.robin = auth.create_user(c, "robin", PW)
            auth.set_display_name(c, cls.robin, "Robin")
            c.execute("UPDATE users SET email = 'robin@example.org', email_verified_at = "
                      "'2026-09-01 10:00:00' WHERE id = ?", (cls.robin,))
            sample_data.load(c, cls.robin)
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
            for t in ("together_pairs", "together_invites", "email_sends"):
                c.execute(f"DELETE FROM {t}")
            c.commit()
        finally:
            c.close()

    @contextlib.contextmanager
    def _app(self, uid=None, name=None, *, flag="together", invite=None, page="Life", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        if uid is not None:
            for k, v in {"user_id": uid, "username": name, "page": page,
                         "auto_backfilled": True, **state}.items():
                at.session_state[k] = v
        if invite is not None:
            at.query_params[tg.QUERY] = invite
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

    def _q(self, sql, args=()):
        c = portfolio.connect(self.db)
        try:
            return [tuple(r) for r in c.execute(sql, args)]
        finally:
            c.close()

    def test_invite_join_see_nudge_and_stop(self):
        # zelda makes a link, once she's said she understands
        with self._app(self.zelda, "zelda.q@example.com") as at:
            text = _tree_text(at)
            self.assertIn(tg.TITLE, text)
            self.assertIn(tg.NONE_YET, text)
            self.assertTrue(at.button(key="tg_make").disabled)
            at.checkbox(key="tg_agree").check().run()
            at.button(key="tg_make").click().run()
            new = at.session_state["tg_new"]
            self.assertRegex(new, r"\?together=[A-Za-z0-9_-]{43}$")
        token = new.rsplit("=", 1)[1]
        self.assertEqual(self._q("SELECT user_id, token_hash FROM together_invites"),
                         [(self.zelda, tg.token_hash(token))])
        # robin opens it signed in: Life, the words, yes
        with self._app(self.robin, "robin", invite=token, page="Dashboard") as at:
            self.assertEqual(at.session_state["page"], "Life")
            self.assertEqual(at.session_state["together_hash"], tg.token_hash(token))
            text = _tree_text(at)
            self.assertIn("Zelda invited you to do it together", text)
            self.assertIn(tg.join_text("Zelda"), text)
            self.assertNotIn(tg.QUERY, at.query_params)   # the address drops the link
            at.button(key="tg_yes").click().run()
            text = _tree_text(at)
            self.assertIn(tg.JOINED, text)
            self.assertIn("Zelda", text)
            self.assertIn("Learning days this month", text)
            self.assertIn("October walk", text)
            for secret in SECRETS[:-4]:   # (Stocks etc. are Robin's own example words)
                self.assertNotIn(secret, text.replace("zelda.q", ""), secret)
            # zelda has walked this month: no nudge to her
            self.assertNotIn(f"tg_nudge_{self.zelda}", [b.key for b in at.button])
        self.assertEqual(self._q("SELECT how FROM consent_records WHERE scope = 'together' "
                                 "ORDER BY id")[-2:], [("together_invite",), ("together_join",)])
        # zelda sees robin, who hasn't walked: a nudge, once
        with self._app(self.zelda, "zelda.q@example.com") as at:
            self.assertIn("Robin hasn't done the October walk yet", _tree_text(at))
            at.button(key=f"tg_nudge_{self.robin}").click().run()
            self.assertIn(tg.NUDGE_SENT, _tree_text(at))
            at.button(key=f"tg_nudge_{self.robin}").click().run()
            self.assertIn("You've sent them a nudge in the last week", _tree_text(at))
            # either side stops in one step
            at.button(key=f"tg_stop_{self.robin}").click().run()
            self.assertIn(tg.STOPPED, _tree_text(at))
        self.assertEqual(self._q("SELECT * FROM together_pairs"), [])
        with self._app(self.robin, "robin") as at:   # the other side sees it end
            text = _tree_text(at)
            self.assertIn(tg.NONE_YET, text)
            self.assertNotIn("Zelda", text.split(tg.TITLE, 1)[1].split("Your sharing record")[0])

    def test_not_signed_in_the_sign_in_page_says_why(self):
        with self._app(invite="A" * 43) as at:
            self.assertIn(tg.SIGN_IN, _tree_text(at))

    def test_off_nothing_at_all(self):
        with self._app(self.zelda, "zelda.q@example.com", flag="") as at:
            self.assertNotIn(tg.TITLE, _tree_text(at))
            self.assertNotIn("tg_make", [b.key for b in at.button])
        with self._app(invite="A" * 43, flag="") as at:
            self.assertNotIn(tg.SIGN_IN, _tree_text(at))

    def test_never_for_an_advisor_a_client_or_an_admin(self):
        for uid, name, state in (
                (self.carol, "carol", {"two_step_ok": self.carol_ok,
                                       "active_user_id": self.dana, "page": "Account"}),
                (self.carol, "carol", {"two_step_ok": self.carol_ok, "page": "Account"}),
                (self.dana, "dana", {}),
                (self.root, "root", {"two_step_ok": self.root_ok})):
            with self.subTest(name), self._app(uid, name, **state) as at:
                self.assertNotIn(tg.TITLE, _tree_text(at))
                self.assertNotIn("tg_make", [b.key for b in at.button])
        # a client who opens a link is told it isn't for them
        c = portfolio.connect(self.db)
        try:
            token = tg.invite(c, self.zelda, by=self.zelda)
        finally:
            c.close()
        with self._app(self.dana, "dana", invite=token) as at:
            self.assertIn(tg.NOT_ALLOWED, _tree_text(at))
            self.assertNotIn("tg_yes", [b.key for b in at.button])

    def test_the_nudge_switch(self):
        c = portfolio.connect(self.db)
        try:
            token = tg.invite(c, self.zelda, by=self.zelda)
            tg.accept(c, tg.token_hash(token), self.robin, by=self.robin,
                      text_shown=tg.join_text("Zelda"))
        finally:
            c.close()
        with self._app(self.robin, "robin") as at:
            self.assertTrue(at.toggle(key="tg_nudges_on").value)
            at.toggle(key="tg_nudges_on").set_value(False).run()
        c = portfolio.connect(self.db)
        try:
            self.assertFalse(tg.nudges_on(prefs.load(c, self.robin)))
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
