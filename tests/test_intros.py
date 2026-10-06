"""Introductions and the two-step consent to full sharing (intros.py,
views/intros.py; PLAN step 5 items 5-6, master brief 4.3): only a visible
directory advisor can receive one; an advisor sees only intros sent to them
and never the sender's account id or email; the outline sent is figure-free
(no amounts, share counts, tickers or account names); full sharing happens
only after both steps, with a consent grant (how 'intro', the exact words)
written in the same transaction as the link; reply / decline / withdraw
rules; the daily limit; nothing about browsing counted; the flag and gate L2
hiding everything; client mode never seeing it.

    python -m unittest tests.test_intros        (from the repo root)
"""

import ast
import contextlib
import json
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

import admin  # noqa: E402
import advising  # noqa: E402
import advisor  # noqa: E402
import auth  # noqa: E402
import consent  # noqa: E402
import directory  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import intros  # noqa: E402
import licence_check  # noqa: E402
import portfolio  # noqa: E402
import recap  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
BIG = 987654.32           # a figure that must never reach an advisor
ACCOUNT = "Brokerage IRA ...456"


def _profile(name, firm="A Firm", **over):
    fields = {"display_name": name, "firm": firm, "reg_type": "sec_ria",
              "reg_number": "1234567", "credentials": "CFP", "fee_models": ["flat"],
              "minimum": "none", "serves": ["new"], "states": ["NY"], "meeting": "both",
              "description": "Plain words about how I work.",
              "scheduling_url": "https://cal.example.com/me"}
    fields.update(over)
    return fields


def _db(tmp, name="intros.db"):
    path = os.path.join(tmp, name)
    portfolio._SCHEMA_READY.discard(os.path.abspath(path))
    return path


def _listed_advisor(c, login, name, *, listed=True, checked=True, **over):
    uid = auth.create_user(c, login, PW)
    auth.set_advisor(c, login, True)
    if checked:   # a current licence check (licence_check.py), so the listing shows
        licence_check.record(c, uid, source="IAPD", crd="7012345",
                             checked_on=licence_check._today().isoformat())
    assert directory.save_profile(c, uid, _profile(name, **over), listed=listed)["ok"]
    return uid


def _holdings(c, uid, source="mine.csv"):
    """Real-looking holdings with big figures and a ticker the outline must drop."""
    row = {col: None for col in portfolio.POSITION_COLS}
    row.update(snapshot_date="2026-09-30", account=ACCOUNT, symbol="ZZQX",
               description="Secret Growth Fund", asset_type="Equity", quantity=1234.5,
               cost_basis=BIG, market_value=BIG)
    bond = {**row, "symbol": "BNDQ", "description": "A bond fund", "asset_type": "Fixed Income",
            "market_value": BIG / 3, "cost_basis": BIG / 3, "quantity": 77.0}
    portfolio.write_snapshot(c, uid, {"snapshot_date": "2026-09-30", "as_of_text": "as of"},
                             [row, bond], {ACCOUNT: {"cash_value": 12345.67,
                                                     "reported_cost_basis": None,
                                                     "reported_market_value": None,
                                                     "reported_gain": None,
                                                     "reported_gain_pct": None}}, source)
    c.commit()


@contextlib.contextmanager
def _settings(flags_value="", gates_value=""):
    with unittest.mock.patch.dict(os.environ, {flags.FLAGS_SETTING: flags_value,
                                               flags.GATES_SETTING: gates_value}), \
            unittest.mock.patch.object(flags, "_secret", lambda name: None):
        yield


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt_intros_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.c = portfolio.connect(_db(self.tmp))
        self.addCleanup(self.c.close)
        c = self.c
        self.alice = auth.create_user(c, "alice", PW)                # an individual
        self.carol = _listed_advisor(c, "carol", "Carol Reyes", firm="Reyes Wealth")
        self.omar = _listed_advisor(c, "omar", "Omar Diaz")

    def send(self, person=None, adv=None, message="Hello - I'd like help with a plan.", **kw):
        kw.setdefault("name", "Alice")
        return intros.send(self.c, person or self.alice, adv or self.carol, message, **kw)

    def rows(self, table, where="1 = 1", params=()):
        return [dict(r) for r in self.c.execute(f"SELECT * FROM {table} WHERE {where}", params)]


# --------------------------------------------------------------------------- #
# who can send, and to whom
# --------------------------------------------------------------------------- #
class SendTests(_DbCase):

    def test_only_a_visible_advisor_receives(self):
        c = self.c
        hidden = _listed_advisor(c, "hal", "Hal Unlisted", listed=False)
        stale = _listed_advisor(c, "sam", "Sam No Check", checked=False)
        investor = auth.create_user(c, "ivy", PW)
        for target in (hidden, stale, investor, self.alice, 999):
            with self.subTest(target=target):
                res = self.send(adv=target)
                self.assertFalse(res["ok"])
        self.assertEqual(self.rows("intro_requests"), [])
        self.assertTrue(self.send()["ok"])
        self.assertEqual([r["advisor_id"] for r in self.rows("intro_requests")], [self.carol])

    def test_advisors_and_clients_dont_send(self):
        c = self.c
        dana = auth.create_client(c, self.omar, "dana", name="Dana")   # omar's client
        self.assertFalse(self.send(person=dana)["ok"])
        self.assertFalse(self.send(person=self.omar)["ok"])            # an advisor
        self.assertEqual(self.rows("intro_requests"), [])

    def test_message_and_name_are_plain_text(self):
        for message in ("See https://me.example.com", "mail me at a@b.com", "www.me.com",
                        "<b>hi</b>", "My account is 12345678", "Call 555-123-4567",
                        "x" * (intros.LIMITS["message"] + 1), "   "):
            with self.subTest(message=message[:30]):
                self.assertFalse(self.send(message=message)["ok"])
        for name in ("", "alice@example.com", "<i>Al</i>", "A" * (intros.LIMITS["name"] + 1)):
            with self.subTest(name=name[:20]):
                self.assertFalse(self.send(name=name)["ok"])
        self.assertEqual(self.rows("intro_requests"), [])
        # an amount in their own words is their choice; a year is fine
        self.assertTrue(self.send(message="Retiring in 2040.\nAbout $250,000 saved.")["ok"])

    def test_no_second_open_intro_to_the_same_advisor(self):
        first = self.send()
        self.assertTrue(first["ok"])
        self.assertIn("already written", self.send()["error"])
        self.assertTrue(self.send(adv=self.omar)["ok"])      # another advisor is fine
        self.assertTrue(intros.withdraw(self.c, self.alice, first["id"])["ok"])
        self.assertTrue(self.send()["ok"])                   # after withdrawing, again

    def test_not_again_soon_after_a_decline(self):
        first = self.send(now=NOW)
        self.assertTrue(intros.decline(self.c, self.carol, first["id"], now=NOW)["ok"])
        self.assertFalse(self.send(now=NOW + timedelta(days=10))["ok"])
        later = NOW + timedelta(days=intros.DECLINE_WAIT_DAYS + 1)
        self.assertTrue(self.send(now=later)["ok"])

    def test_a_few_a_day(self):
        c = self.c
        others = [_listed_advisor(c, f"adv{i}", f"Advisor {i}") for i in range(intros.PER_DAY + 1)]
        for i, adv in enumerate(others[:intros.PER_DAY]):
            self.assertTrue(self.send(adv=adv, now=NOW + timedelta(minutes=i))["ok"])
        res = self.send(adv=others[-1], now=NOW + timedelta(hours=2))
        self.assertFalse(res["ok"])
        self.assertIn("last day", res["error"])
        self.assertTrue(self.send(adv=others[-1], now=NOW + timedelta(days=1, hours=1))["ok"])


# --------------------------------------------------------------------------- #
# the figure-free outline
# --------------------------------------------------------------------------- #
class OutlineTests(_DbCase):

    def _figures(self, text):
        bad = [f"{BIG:.2f}", "987654", "987,654", "12345", "1234.5", "1,234", "ZZQX", "BNDQ",
               "Secret Growth", ACCOUNT, "IRA", "...456", "$"]
        return [b for b in bad if b in text]

    def test_no_amounts_share_counts_tickers_or_account_names(self):
        c = self.c
        _holdings(c, self.alice)
        advisor.save_profile(c, self.alice, {"goal": "Retirement; Buy a home",
                                             "time_horizon_years": 15, "experience": "New",
                                             "notes": "My secret notes 98765"})
        found = intros.outline(c, self.alice)
        self.assertEqual(set(found), {"mix", "goals", "timeline", "stage"})
        self.assertEqual(found["goals"], ["Retirement", "Buy a home"])
        self.assertEqual(found["timeline"], "11 to 20 years")
        self.assertEqual(found["stage"], "investing")
        self.assertTrue(all(isinstance(v, int) and 0 < v <= 100 for _, v in found["mix"]))
        self.assertEqual([k for k, _ in found["mix"]], ["Stocks", "Bonds", "Cash"])
        self.assertTrue(self.send(outline=found)["ok"])
        stored = self.rows("intro_requests")[0]["outline"]
        for text in (stored, json.dumps(intros.for_advisor(c, self.carol))):
            self.assertEqual(self._figures(text), [])
            self.assertNotIn("secret", text.lower())
        for _, _, line in intros.outline_lines(found):
            self.assertFalse(recap.has_money(line), line)

    def test_only_what_an_outline_may_hold(self):
        sneaky = {"mix": [["Stocks", 60], ["ZZQX", 40], ["Bonds", 12.5], ["Cash", BIG],
                          ["Stocks", 5]],
                  "goals": ["Retirement", f"Buy a ${BIG} home"], "timeline": "15 years",
                  "stage": "rich", "amount": BIG, "account": ACCOUNT, "shares": 1234.5}
        self.assertEqual(intros.clean_outline(sneaky),
                         {"mix": [["Stocks", 60]], "goals": ["Retirement"]})
        self.assertTrue(self.send(outline=sneaky)["ok"])
        self.assertEqual(json.loads(self.rows("intro_requests")[0]["outline"]),
                         {"mix": [["Stocks", 60]], "goals": ["Retirement"]})
        self.assertEqual(intros.clean_outline("not json"), {})

    def test_the_example_portfolio_isnt_their_mix(self):
        sample_data.load(self.c, self.alice)
        found = intros.outline(self.c, self.alice)
        self.assertNotIn("mix", found)
        self.assertEqual(found["stage"], "learn")     # new, nothing of their own yet

    def test_they_choose_what_goes(self):
        _holdings(self.c, self.alice)
        found = intros.outline(self.c, self.alice)
        self.assertTrue(self.send(outline=intros.pick(found, ["stage"]))["ok"])
        self.assertEqual(json.loads(self.rows("intro_requests")[0]["outline"]),
                         {"stage": "investing"})
        self.assertEqual(intros.pick(found, []), {})


# --------------------------------------------------------------------------- #
# the advisor's side
# --------------------------------------------------------------------------- #
class AdvisorSideTests(_DbCase):

    def test_an_advisor_sees_only_their_own(self):
        c = self.c
        bob = auth.create_user(c, "bob", PW)
        c.execute("UPDATE users SET email = 'alice@example.com' WHERE id = ?", (self.alice,))
        c.commit()
        to_carol = self.send(message="For Carol")["id"]
        to_omar = self.send(person=bob, adv=self.omar, message="For Omar", name="Bob")["id"]
        mine = intros.for_advisor(c, self.carol)
        self.assertEqual([r["id"] for r in mine], [to_carol])
        self.assertNotIn("For Omar", json.dumps(mine))
        for r in mine:   # never the person's account id or email
            self.assertNotIn("person_id", r)
            self.assertNotIn("alice@example.com", json.dumps(r))
        self.assertEqual(intros.for_advisor(c, self.alice), [])
        # carol can't touch omar's
        self.assertFalse(intros.reply(c, self.carol, to_omar, "Hi")["ok"])
        self.assertFalse(intros.decline(c, self.carol, to_omar)["ok"])
        self.assertFalse(intros.share_link(c, self.carol, to_omar)["ok"])
        self.assertIsNone(intros.answer_email(c, self.carol, to_omar))
        self.assertEqual(self.rows("intro_requests", "id = ?", (to_omar,))[0]["status"], "sent")

    def test_reply_once_plain_text_and_the_scheduling_link(self):
        c = self.c
        rid = self.send()["id"]
        self.assertFalse(intros.reply(c, self.carol, rid, "Book at https://x.example.com")["ok"])
        self.assertFalse(intros.reply(c, self.carol, rid, "")["ok"])     # nothing to send
        self.assertTrue(intros.reply(c, self.carol, rid, "Happy to talk.")["ok"])
        self.assertFalse(intros.reply(c, self.carol, rid, "Again")["ok"])
        r = intros.for_person(c, self.alice)[0]
        self.assertEqual((r["status"], r["reply"], r["scheduling_url"]),
                         ("replied", "Happy to talk.", None))
        self.assertTrue(intros.share_link(c, self.carol, rid)["ok"])
        self.assertEqual(intros.for_person(c, self.alice)[0]["scheduling_url"],
                         "https://cal.example.com/me")
        # only the link, as the answer
        other = self.send(adv=self.omar)["id"]
        self.assertTrue(intros.reply(c, self.omar, other, "", share_link=True)["ok"])
        # no link on the listing: nothing to share
        directory.save_profile(c, self.omar, _profile("Omar Diaz", scheduling_url=""),
                               listed=True)
        bob = auth.create_user(c, "bob", PW)
        third = self.send(person=bob, adv=self.omar, name="Bob")["id"]
        self.assertFalse(intros.reply(c, self.omar, third, "", share_link=True)["ok"])

    def test_decline_and_withdraw(self):
        c = self.c
        rid = self.send()["id"]
        self.assertFalse(intros.withdraw(c, self.carol, rid)["ok"])   # not the sender
        self.assertTrue(intros.decline(c, self.carol, rid, "Not taking new clients.")["ok"])
        r = intros.for_person(c, self.alice)[0]
        self.assertEqual((r["status"], r["reply"]), ("declined", "Not taking new clients."))
        self.assertFalse(intros.decline(c, self.carol, rid)["ok"])     # already closed
        self.assertFalse(intros.withdraw(c, self.alice, rid)["ok"])
        self.assertIsNotNone(intros.can_share(c, self.alice, rid))
        other = self.send(adv=self.omar)["id"]
        self.assertTrue(intros.withdraw(c, self.alice, other)["ok"])
        self.assertFalse(intros.reply(c, self.omar, other, "Hi")["ok"])
        self.assertEqual(intros.for_advisor(c, self.omar)[0]["status"], "withdrawn")


# --------------------------------------------------------------------------- #
# the two-step consent to full sharing
# --------------------------------------------------------------------------- #
class FullSharingTests(_DbCase):

    def _answered(self):
        rid = self.send()["id"]
        self.assertTrue(intros.reply(self.c, self.carol, rid, "Glad to help.")["ok"])
        return rid

    def test_only_after_an_answer_and_both_steps(self):
        c = self.c
        rid = self.send()["id"]
        text = intros.sharing_text_for(c, self.carol)
        # before the advisor answers
        self.assertFalse(intros.share_account(c, self.alice, rid, text, confirmed=True)["ok"])
        intros.reply(c, self.carol, rid, "Glad to help.")
        # step 2 not ticked; the words not the ones shown; someone else's intro
        self.assertFalse(intros.share_account(c, self.alice, rid, text, confirmed=False)["ok"])
        self.assertFalse(intros.share_account(c, self.alice, rid, "Something else",
                                              confirmed=True)["ok"])
        bob = auth.create_user(c, "bob", PW)
        self.assertFalse(intros.share_account(c, bob, rid, text, confirmed=True)["ok"])
        self.assertFalse(auth.can_view(c, self.carol, self.alice))
        self.assertEqual(self.rows("consent_records"), [])
        self.assertEqual(self.rows("advisor_clients"), [])

        res = intros.share_account(c, self.alice, rid, text, confirmed=True, now=NOW)
        self.assertTrue(res["ok"], res)
        self.assertTrue(auth.can_view(c, self.carol, self.alice))
        grant = self.rows("consent_records")
        self.assertEqual(len(grant), 1)
        g = grant[0]
        self.assertEqual((g["client_id"], g["advisor_id"], g["kind"], g["how"], g["scope"]),
                         (self.alice, self.carol, "grant", "intro", "full_sharing"))
        self.assertEqual(g["text_shown"], text)
        self.assertEqual(g["text_sha256"], consent.text_sha256(text))
        self.assertEqual(g["at"], "2026-10-06T12:00:00Z")
        # the advisor's name for them is the one they gave
        self.assertEqual(auth.list_clients(c, self.carol), [(self.alice, "Alice")])
        self.assertEqual(intros.for_person(c, self.alice)[0]["status"], "shared")
        # once is enough; and with an advisor they can't send more intros
        self.assertFalse(intros.share_account(c, self.alice, rid, text, confirmed=True)["ok"])
        self.assertFalse(self.send(adv=self.omar)["ok"])

    def test_the_words_shown(self):
        text = intros.sharing_text("Carol Reyes", "Reyes Wealth")
        for said in ("Carol Reyes will see everything in your Northwend account",
                     "the name and email on your account",
                     "notes to future you, your monthly walks and your account map",
                     "set your plan, goal, target mix and alert limits",
                     "Who has looked at your account",
                     "Their advice is Carol Reyes's, from Reyes Wealth - not Northwend's",
                     "stop sharing at any time from the Your advisor page",
                     "you keep everything",
                     "I understand - share my full account with Carol Reyes"):
            self.assertIn(said, text)
        self.assertTrue(text.startswith(intros.SHARE_TITLE))
        # the same words, worked out for an advisor from their listing
        self.assertEqual(intros.sharing_text_for(self.c, self.carol), text)

    def test_the_grant_is_written_before_the_link_in_one_transaction(self):
        c = self.c
        rid = self._answered()
        text = intros.sharing_text_for(c, self.carol)
        real = auth.link_client
        seen = []

        def link_checking(conn, adv, client, **kw):
            # the grant is already there, on the same connection, uncommitted
            seen.append(conn.execute("SELECT kind, how FROM consent_records WHERE "
                                     "client_id = ? AND advisor_id = ?",
                                     (client, adv)).fetchall())
            self.assertFalse(kw.get("commit", True))
            return real(conn, adv, client, **kw)
        with unittest.mock.patch.object(auth, "link_client", link_checking):
            self.assertTrue(intros.share_account(c, self.alice, rid, text, confirmed=True)["ok"])
        self.assertEqual([tuple(r) for r in seen[0]], [("grant", "intro")])

    def test_a_failure_leaves_nothing_half_done(self):
        c = self.c
        rid = self._answered()
        text = intros.sharing_text_for(c, self.carol)
        with unittest.mock.patch.object(auth, "link_client", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                intros.share_account(c, self.alice, rid, text, confirmed=True)
        self.assertEqual(self.rows("consent_records"), [])
        self.assertEqual(self.rows("advisor_clients"), [])
        self.assertEqual(self.rows("intro_requests")[0]["status"], "replied")

    def test_an_advisor_who_isnt_current_cant_be_shared_with(self):
        c = self.c
        rid = self._answered()
        text = intros.sharing_text_for(c, self.carol)
        c.execute("DELETE FROM licence_checks WHERE advisor_id = ?", (self.carol,))
        c.commit()
        self.assertFalse(intros.share_account(c, self.alice, rid, text, confirmed=True)["ok"])
        self.assertEqual(self.rows("consent_records"), [])

    def test_stop_sharing_later_writes_the_revoke(self):
        c = self.c
        rid = self._answered()
        intros.share_account(c, self.alice, rid, intros.sharing_text_for(c, self.carol),
                             confirmed=True)
        self.assertTrue(consent.current(c, self.alice, self.carol))
        res = advising.end_relationship(c, self.carol, self.alice, by="client",
                                        text_shown="Stop sharing words")
        self.assertTrue(res["ok"])
        self.assertFalse(consent.current(c, self.alice, self.carol))
        self.assertFalse(auth.can_view(c, self.carol, self.alice))
        self.assertEqual([r["how"] for r in consent.history(c, self.alice)],
                         ["client_stop", "intro"])


# --------------------------------------------------------------------------- #
# kept, exported, deleted - and nothing counted
# --------------------------------------------------------------------------- #
class RecordTests(_DbCase):

    def test_export_and_delete_with_either_account(self):
        c = self.c
        rid = self.send()["id"]
        intros.reply(c, self.carol, rid, "Hi Alice")
        mine = export.collect(c, self.alice)["your_introductions"]
        self.assertEqual(mine[0]["message"], "Hello - I'd like help with a plan.")
        theirs = export.collect(c, self.carol)["introductions_to_you"]
        self.assertNotIn("person_id", theirs[0])
        self.assertEqual(theirs[0]["reply"], "Hi Alice")
        self.assertIn("intro_requests", admin.ACCOUNT_TABLES)
        self.assertTrue(admin.delete_account(c, self.carol, by=-1)["ok"])
        self.assertEqual(self.rows("intro_requests"), [])
        self.send(adv=self.omar)
        self.assertTrue(admin.delete_account(c, self.alice, by=-1)["ok"])
        self.assertEqual(self.rows("intro_requests"), [])

    def test_the_draft_copy_and_no_nudges(self):
        self.assertEqual(intros.COPY_STATUS, "DRAFT")
        words = " ".join((intros.FORM_INTRO, intros.FORM_PRIVACY, intros.SENT_NOTE,
                          intros.PERSON_LIST_NOTE, intros.ADVISOR_INTRO, intros.SHARE_TITLE,
                          *intros.SHARE_LINES, intros.CONFIRM_LINE)).lower()
        for said in ("won't see any amounts", "only ever yours",
                     "doesn't count views or clicks"):
            self.assertIn(said, words)
        for nudge in ("you need an advisor", "you should", "best advisor", "recommended",
                      "hurry", "don't miss", "limited time"):
            self.assertNotIn(nudge, words)


class NothingCountedTests(unittest.TestCase):
    """No column or name anywhere in the intro code counts views, clicks or
    impressions, or ranks anyone."""
    COUNTING = re.compile(r"rank|score|impression|click|view_count|views_|_views|popular|"
                          r"featur|sponsor|boost|priorit|rating|match_score", re.I)

    def test_no_counting_columns(self):
        c = sqlite3.connect(":memory:")
        self.addCleanup(c.close)
        with open(os.path.join(REPO, "schema.sql"), encoding="utf-8") as fh:
            c.executescript(fh.read())
        cols = [r[1] for r in c.execute("PRAGMA table_info(intro_requests)")]
        self.assertEqual(cols, ["id", "person_id", "advisor_id", "created_at", "person_name",
                                "message", "outline", "status", "reply", "replied_at",
                                "link_shared", "closed_at"])
        self.assertFalse([col for col in cols if self.COUNTING.search(col)])
        with open(os.path.join(REPO, "schema_pg.sql"), encoding="utf-8") as fh:
            pg = fh.read()
        block = pg[pg.index("CREATE TABLE IF NOT EXISTS intro_requests"):]
        block = block[:block.index(");")]
        for col in cols:
            self.assertIn(f"    {col} ", block)

    def test_no_counting_names_in_the_code(self):
        for rel in ("intros.py", os.path.join("views", "intros.py")):
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, ast.arg):
                    names.add(node.arg)
            self.assertEqual(sorted(n for n in names if self.COUNTING.search(n)), [], rel)

    def test_only_sending_and_answering_write(self):
        """The reads a person browsing or an advisor looking makes (outline,
        for_person, for_advisor, can_send...) write nothing."""
        with open(os.path.join(REPO, "intros.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        writers = set()
        for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and re.search(r"\b(INSERT|UPDATE|DELETE)\b", node.value)):
                    writers.add(fn.name)
        self.assertEqual(writers, {"send", "reply", "share_link", "decline", "withdraw",
                                   "share_account"})


class FlagTests(unittest.TestCase):

    def test_needs_the_flag_and_gate_l2(self):
        self.assertEqual(flags.FEATURES["intros"], {"gates": ("L2",), "view": "intros"})
        for flag_value, gate_value, on in (("", "", False), ("intros", "", False),
                                           ("", "L2", False), ("intros", "L0,L1,L3", False),
                                           ("intros", "L2", True)):
            with self.subTest(flags=flag_value, gates=gate_value), \
                    _settings(flag_value, gate_value):
                self.assertEqual(flags.on("intros"), on)
                self.assertEqual(flags.view_on("intros"), on)


# --------------------------------------------------------------------------- #
# the app itself
# --------------------------------------------------------------------------- #
class IntroAppTests(unittest.TestCase):
    """AppTest: the whole flow - send from Find a guide, the advisor answers
    on Your clients, the person shares in two steps - and nothing at all with
    the flag or L2 off, or in client mode."""
    ON = "directory,intros"

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.tmp = tempfile.mkdtemp(prefix="pt_intros_app_")
        cls.db = _db(cls.tmp, "app.db")
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)          # an individual
            _holdings(c, cls.alice)
            advisor.save_profile(c, cls.alice, {"goal": "Retirement", "time_horizon_years": 25})
            cls.carol = _listed_advisor(c, "carol", "Carol Reyes", firm="Reyes Wealth")
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dave = auth.create_user(c, "dave", PW)            # carol's client
            auth.link_client(c, cls.carol, cls.dave)
            sample_data.load(c, cls.dave)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, user_id, username, page=None, flags_value=ON, gates_value="L2", **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        at.session_state["user_id"] = user_id
        at.session_state["username"] = username
        at.session_state["auto_backfilled"] = True
        for k, v in state.items():
            at.session_state[k] = v
        if page:
            at.query_params["page"] = page
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "ANTHROPIC_API_KEY", "RESEND_API_KEY",
                            "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1",
                   NORTHWEND_FLAGS=flags_value, NORTHWEND_GATES=gates_value)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at, env

    @staticmethod
    def _menu(at):
        pops = {p.proto.id.rsplit("-", 1)[-1]: p for p in at.get("popover")}
        return [b.key for b in pops["pt_me"].button]

    @staticmethod
    def _text(at):
        return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption]
                        + [s.value for s in at.subheader] + [i.value for i in at.info]
                        + [e.value for e in at.error] + [s.value for s in at.success])

    @staticmethod
    def _keys(at):
        return [k for k in ("intro_to", "intro_name", "intro_flash", "intro_share")
                if k in at.session_state]

    def _db_rows(self, table):
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute(f"SELECT * FROM {table}")]
        finally:
            c.close()

    def _dump(self):
        c = sqlite3.connect(self.db)
        try:
            return set(c.iterdump())
        finally:
            c.close()

    def _links(self):
        return {(r["advisor_id"], r["client_id"]) for r in self._db_rows("advisor_clients")}

    def test_1_off_there_is_nothing(self):
        # the directory alone (introductions open soon), the flag without L2, neither
        for flag_value, gate_value in (("directory", "L2"), (self.ON, "L0,L1,L3"), ("", "")):
            with self.subTest(flags=flag_value, gates=gate_value):
                at, env = self._run(self.alice, "alice", "find-a-guide", flag_value, gate_value)
                self.assertNotIn("Your introductions", [s.value for s in at.subheader])
                buttons = [b.key for b in at.button if (b.key or "").startswith("dir_intro_")]
                if buttons:
                    with unittest.mock.patch.dict(os.environ, env, clear=True):
                        at.button(key=buttons[0]).click().run()
                    self.assertIn(directory.INTROS_SOON, [i.value for i in at.info])
                    self.assertFalse([b for b in at.button
                                      if (b.key or "").startswith("FormSubmitter:intro_")])
                at, _ = self._run(self.carol, "carol", "your-clients", flag_value, gate_value,
                                  two_step_ok=self.carol_ok)
                self.assertNotIn("Introductions", [s.value for s in at.subheader])
                self.assertEqual(self._keys(at), [])
        self.assertEqual(self._db_rows("intro_requests"), [])

    def test_2_client_mode_never_sees_it(self):
        at, _ = self._run(self.dave, "dave", "find-a-guide")
        self.assertNotIn("menu_Find a guide", self._menu(at))
        self.assertNotIn("Your introductions", [s.value for s in at.subheader])
        self.assertNotIn("Request an introduction", [b.label for b in at.button])
        # carol in dave's account: her Introductions are on Your clients only
        at, _ = self._run(self.carol, "carol", "find-a-guide", two_step_ok=self.carol_ok,
                          active_user_id=self.dave)
        self.assertNotIn("menu_Find a guide", self._menu(at))
        self.assertNotIn("Request an introduction", [b.label for b in at.button])

    def test_3_send_answer_and_share_in_two_steps(self):
        at, env = self._run(self.alice, "alice", "about")      # settle sign-in's own writes
        before = self._dump()
        at, env = self._run(self.alice, "alice", "find-a-guide")
        card = f"dir_intro_{self.carol}"
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.button(key=card).click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            # the form shows what would be sent - percentages, never amounts
            labels = [cb.label for cb in at.checkbox if (cb.key or "").startswith("intro_part_")]
            self.assertTrue(any(lb.startswith("Your mix by asset class: Stocks") for lb in labels),
                            labels)
            self.assertFalse([lb for lb in labels if recap.has_money(lb) or "ZZQX" in lb])
            # opening the form wrote nothing
            changed = {line.split('"')[1] for line in self._dump() ^ before
                       if line.startswith("INSERT INTO")}
            self.assertLessEqual(changed, {"login_sessions", "users", "value_log"}, changed)
            at.text_area(key=f"intro_msg_{self.carol}").set_value("Hello, I'd like a plan.")
            at.checkbox(key="intro_part_goals").uncheck()
            at.button(key=f"FormSubmitter:intro_form_{self.carol}-Send introduction").click()
            at.run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            self.assertIn(intros.SENT_NOTE, [s.value for s in at.success])
            self.assertIn("Your introductions", [s.value for s in at.subheader])
        rows = self._db_rows("intro_requests")
        self.assertEqual(len(rows), 1)
        sent = rows[0]
        self.assertEqual((sent["person_id"], sent["advisor_id"], sent["message"],
                          sent["status"]), (self.alice, self.carol, "Hello, I'd like a plan.",
                                            "sent"))
        self.assertEqual(set(json.loads(sent["outline"])), {"mix", "timeline", "stage"})
        changed = {line.split('"')[1] for line in self._dump() ^ before
                   if line.startswith("INSERT INTO")}
        self.assertLessEqual(changed, {"login_sessions", "users", "value_log", "intro_requests",
                                       "sqlite_sequence"})

        # carol answers on Your clients
        at, env = self._run(self.carol, "carol", "your-clients", two_step_ok=self.carol_ok)
        self.assertIn("Introductions", [s.value for s in at.subheader])
        text = self._text(at)
        self.assertIn("Hello, I'd like a plan.", text)
        self.assertIn("Mix by asset class", text)
        self.assertNotIn("Retirement", text)       # alice unticked her goals
        for figure in ("987", "12,345", "ZZQX", "...456", "$"):
            self.assertNotIn(figure, text)
        for word in ("views", "clicks", "impressions"):
            self.assertNotRegex(text, rf"\d+ {word}")
        rid = sent["id"]
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.text_area(key=f"intro_reply_{rid}").set_value("Happy to talk - book a time.")
            at.checkbox(key=f"intro_link_{rid}").check()
            at.button(key=f"intro_send_reply_{rid}").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
        row = self._db_rows("intro_requests")[0]
        self.assertEqual((row["status"], row["reply"], row["link_shared"]),
                         ("replied", "Happy to talk - book a time.", 1))

        # alice reads it and shares, in two steps
        at, env = self._run(self.alice, "alice", "find-a-guide")
        self.assertIn("Happy to talk - book a time.", self._text(at))
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.button(key=f"intro_share_{rid}").click().run()
            step1 = self._text(at)
            self.assertIn("Step 1 of 2", step1)
            self.assertIn("Carol Reyes will see everything in your Northwend account", step1)
            self.assertNotIn("intro_share_go", [b.key for b in at.button])
            self.assertEqual(self._db_rows("consent_records"), [])
            at.button(key="intro_share_next").click().run()
            self.assertIn("Step 2 of 2", self._text(at))
            # not ticked: nothing happens
            at.button(key="intro_share_go").click().run()
            self.assertEqual(self._db_rows("consent_records"), [])
            self.assertEqual(self._links(), {(self.carol, self.dave)})
            at.checkbox(key="intro_share_ok").check()
            at.button(key="intro_share_go").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
        grants = [g for g in self._db_rows("consent_records") if g["client_id"] == self.alice]
        self.assertEqual(len(grants), 1)
        self.assertEqual((grants[0]["how"], grants[0]["kind"]), ("intro", "grant"))
        self.assertEqual(grants[0]["text_shown"], intros.sharing_text("Carol Reyes",
                                                                      "Reyes Wealth"))
        self.assertEqual(self._links(), {(self.carol, self.dave), (self.carol, self.alice)})
        # alice is now carol's client: client mode, no Find a guide
        at, _ = self._run(self.alice, "alice", "find-a-guide")
        self.assertNotIn("menu_Find a guide", self._menu(at))


if __name__ == "__main__":
    unittest.main()
