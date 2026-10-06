"""Principle test (PLAN 1a.10, audit 1.2a): one account's helpers never read,
change or delete another account's rows - for every table in
admin.ACCOUNT_TABLES.

Two worlds are seeded the same way on a scratch database: A (alice, an
investor; carol, an advisor, with her client dana and a former client) and
B (bob; omar, an advisor, with his client zed and a former client). Every
text B writes carries B_MARK and every figure B_FIG. Then, table by table,
A's helpers run - reads, writes, deletes, and writes aimed at B's own row
ids - and:
- nothing a read returns carries B's marker or figure;
- every one of B's rows, in every account table, is exactly as it was.

MATRIX lists the helpers each table is checked with. A new account table
must be added to it (and seeded for B): a test fails until it is.

    python -m unittest tests.test_principle_matrix        (from the repo root)
"""

import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import account_map  # noqa: E402
import accounts  # noqa: E402
import admin  # noqa: E402
import advising  # noqa: E402
import advisor  # noqa: E402
import ai_usage  # noqa: E402
import auth  # noqa: E402
import export  # noqa: E402
import future_notes  # noqa: E402
import perf  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import proposals  # noqa: E402
import reports  # noqa: E402
import txn_import  # noqa: E402
import two_step  # noqa: E402
import watchlist  # noqa: E402

B_MARK = "BOBSECRET"
B_FIG = 987654.32
A_FIG = 1234.5
SNAP = "2026-09-30"        # both worlds save holdings on the same dates
EARLIER = "2026-08-31"
PW = "pw-123456789"

# table -> the helpers A runs against it (module.function). Every table in
# admin.ACCOUNT_TABLES must be here, with a check_<table> method below.
MATRIX = {
    "snapshots": ("portfolio.write_snapshot", "portfolio.current_holdings",
                  "portfolio.previous_snapshot", "portfolio.snapshot_source",
                  "portfolio.remove_account", "portfolio.clear_sample",
                  "portfolio.delete_holdings"),
    "positions": ("portfolio.current_holdings", "account_map.brought_in",
                  "portfolio.prepare_save", "portfolio.save_prepared",
                  "portfolio.remove_account", "portfolio.delete_holdings"),
    "account_totals": ("portfolio.current_holdings", "portfolio.previous_snapshot",
                       "portfolio.write_snapshot", "portfolio.delete_holdings"),
    "transactions": ("txn_import.save", "txn_import.existing_keys", "txn_import.covered",
                     "txn_import.refresh_gains", "txn_import.save_worked_out",
                     "plans.money_moves", "plans.imported_window"),
    "value_log": ("perf.log_open", "perf.last_open", "perf.history"),
    "account_labels": ("accounts.labels", "accounts.set_label"),
    "investor_profiles": ("advisor.get_profile", "advisor.get_profiles",
                          "advisor.get_profile_and_memory", "advisor.save_profile",
                          "advisor.save_memory"),
    "watchlist": ("watchlist.list_tickers", "watchlist.add", "watchlist.remove"),
    "user_prefs": ("prefs.load", "prefs.load_many", "prefs.save"),
    "plans": ("plans.get_plan", "plans.get_plans", "plans.save_plan", "plans.may_change"),
    "contributions": ("plans.list_contributions", "plans.add_contribution",
                      "plans.delete_contribution", "plans.money_in_history"),
    "login_sessions": ("auth.create_session", "auth.session_user", "auth.end_session",
                       "auth.end_other_sessions", "two_step.remember_device",
                       "two_step.device_remembered"),
    "ai_usage": ("ai_usage.used", "ai_usage.status", "ai_usage.record"),
    "email_tokens": ("auth.start_confirmation", "auth.request_password_reset",
                     "auth.setup_link", "auth.reset_info", "auth.reset_password",
                     "auth.confirm_email"),
    "advisor_requests": ("auth.advisor_request", "auth.request_advisor"),
    "invites": ("auth.create_invite", "auth.pending_invite", "auth.cancel_invite"),
    "advisor_clients": ("auth.list_clients", "auth.can_view", "auth.set_client_name",
                        "auth.unlink_client", "advising.ending_plan",
                        "advising.end_relationship"),
    "advisor_notes": ("advising.list_notes", "advising.notes_for", "advising.add_note",
                      "advising.set_done", "advising.archive_note", "advising.restore_note",
                      "advising.edit_note"),
    "model_portfolios": ("advising.list_models", "advising.save_model",
                         "advising.delete_model"),
    "proposals": ("proposals.for_client", "proposals.save", "proposals.share",
                  "proposals.delete", "proposals.archive", "proposals.restore",
                  "proposals.respond"),
    "progress_reports": ("reports.for_client", "reports.sent", "reports.last_end",
                         "reports.save", "reports.mark_read"),
    "two_step": ("two_step.status", "two_step.enable", "two_step.verify",
                 "two_step.reset"),
    "money_out": ("plans.list_money_out", "plans.add_money_out", "plans.update_money_out",
                  "plans.delete_money_out"),
    "former_clients": ("advising.former_clients", "export.client_record"),
    "future_notes": ("future_notes.get", "future_notes.all_notes", "future_notes.save",
                     "future_notes.delete"),
    "account_map": ("account_map.load", "account_map.save_account", "account_map.save_other",
                    "account_map.delete_entry", "account_map.save_family",
                    "account_map.clear"),
}

_MODULES = {m.__name__: m for m in (account_map, accounts, advising, advisor, ai_usage, auth,
                                    export, future_notes, perf, plans, portfolio, prefs,
                                    proposals, reports, txn_import, two_step, watchlist)}


def _position(account, symbol, tag, fig, snap=SNAP):
    row = {c: None for c in portfolio.POSITION_COLS}
    row.update(snapshot_date=snap, account=account, symbol=symbol, description=f"{tag} fund",
               asset_type="ETF", quantity=10.0, cost_basis=fig, market_value=fig)
    return row


def _totals(account, fig):
    return {account: {"cash_value": fig, "reported_cost_basis": None,
                      "reported_market_value": None, "reported_gain": None,
                      "reported_gain_pct": None}}


def _txn(account, symbol, tag, fig, day="2026-09-15"):
    return {"account": account, "trade_date": day, "action": "DIVIDEND", "symbol": symbol,
            "description": f"{tag} dividend", "raw_action": "Dividend", "quantity": None,
            "price": None, "amount": fig, "fees": None}


class IsolationMatrix(unittest.TestCase):
    """A fresh copy of the seeded database for every test."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pt_matrix_")
        cls.template = os.path.join(cls.tmp, "template.db")
        cls.env = unittest.mock.patch.dict(os.environ, {"MAIL_DRY_RUN": "1"})
        cls.env.start()
        os.environ.pop("NORTHWEND_ADMINS", None)
        c = portfolio.connect(cls.template)
        try:
            cls.ids, cls.tokens, cls.secrets = {}, {}, {}
            for side, investor, adv, client, ex, tag, fig, ticker in (
                    ("A", "alice", "carol", "dana", "dana.ex", "ALICE", A_FIG, "VTI"),
                    ("B", "bob", "omar", "zed", "zed.ex", B_MARK, B_FIG, "BOBQ")):
                cls._seed(c, side, investor, adv, client, ex, tag, fig, ticker)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _seed(cls, c, side, investor, adv, client, ex, tag, fig, ticker):
        ids = cls.ids
        now = datetime.now(timezone.utc)
        uid = auth.create_user(c, investor, PW)
        ids[f"{side}.investor"] = uid
        c.execute("UPDATE users SET email = ? WHERE id = ?", (f"{investor}@example.com", uid))
        c.commit()
        account = f"{tag} Brokerage ...{'123' if side == 'A' else '456'}"
        ids[f"{side}.account"], ids[f"{side}.ticker"] = account, ticker
        # holdings: two snapshots, on the same dates in both worlds
        for snap in (EARLIER, SNAP):
            portfolio.write_snapshot(c, uid, {"snapshot_date": snap, "as_of_text": f"{tag} as of"},
                                     [_position(account, ticker, tag, fig, snap)],
                                     _totals(account, fig), f"{tag}.csv")
        c.commit()
        txn_import.save(c, uid, [_txn(account, ticker, tag, fig)], f"{tag}-activity.csv")
        txn_import.save_worked_out(c, uid, "2026-09-20",
                                   [{**_txn(account, ticker, tag, fig, "2026-09-20"),
                                     "action": "BUY", "quantity": 1.0, "price": fig,
                                     "amount": -fig, "realized_gain": None,
                                     "source_file": f"{tag}.csv"}])
        c.commit()
        perf.log_open(cls.template, uid, {"portfolio_value": fig, "n_positions": 1},
                      min_gap_sec=0)
        accounts.set_label(c, uid, account, f"{tag} nickname")
        advisor.save_profile(c, uid, {"goal": f"{tag} goal", "notes": f"{tag} notes"})
        advisor.save_memory(c, uid, f"{tag} memory")
        watchlist.add(c, uid, ticker)
        prefs.save(c, uid, {"note": f"{tag} prefs", "amount": fig})
        plans.save_plan(c, uid, {"goal_name": f"{tag} goal", "target_amount": fig,
                                 "target_date": "2040-01-01", "notes": f"{tag} plan"}, uid)
        plans.add_contribution(c, uid, "2026-09-01", fig, f"{tag} contribution")
        ids[f"{side}.contribution"] = plans.list_contributions(c, uid)[0]["id"]
        cls.tokens[f"{side}.session"] = auth.create_session(c, uid)
        ai_usage.record(c, uid, "chat")
        cls.tokens[f"{side}.confirm"] = auth.start_confirmation(c, uid)["token"]
        cls.tokens[f"{side}.reset"] = auth.request_password_reset(
            c, f"{investor}@example.com")["token"]
        auth.request_advisor(c, uid, f"{tag} Advisors LLC", "1234567")
        secret = two_step.new_secret()
        two_step.enable(c, uid, secret, two_step.totp(secret))
        cls.secrets[side] = secret
        ids[f"{side}.money_out"] = plans.add_money_out(
            c, uid, "expense", {"label": f"{tag} car", "amount": fig,
                                "start_date": "2030-01-01", "times": 1, "every_months": 12},
            by=uid)
        future_notes.save(c, uid, None, f"{tag} note to future me")
        future_notes.save(c, uid, ticker, f"{tag} note on a fund")
        account_map.save_account(c, uid, account, {"contact": f"{tag} contact"})
        ids[f"{side}.map_other"] = account_map.save_other(
            c, uid, {"label": f"{tag} pension", "digits": "789", "notes": f"{tag} notes"})
        account_map.save_family(c, uid, f"{tag} family notes")

        # the advisor side
        a = auth.create_user(c, adv, PW)
        auth.set_advisor(c, adv, True)
        ids[f"{side}.advisor"] = a
        asecret = two_step.new_secret()
        two_step.enable(c, a, asecret, two_step.totp(asecret))
        cid = auth.create_client(c, a, client, name=f"{tag} client")
        ids[f"{side}.client"] = cid
        auth.create_invite(c, a, cid)
        advising.add_note(c, cid, a, "Next step", f"{tag} step", "2026-09-01")
        advising.add_note(c, cid, a, "Note", f"{tag} private", "2026-09-02", private=True)
        notes = advising.list_notes(c, cid, include_private=True, advisor_id=a)
        ids[f"{side}.note"] = min(n["id"] for n in notes)
        ids[f"{side}.private_note"] = max(n["id"] for n in notes)
        advising.message_clients(c, a, [cid], f"{tag} message", now=now)
        advising.save_model(c, a, f"{tag} model", {"Stocks": 60, "Bonds": 40})
        ids[f"{side}.model"] = advising.list_models(c, a)[0]["id"]
        shared = proposals.save(c, a, cid, title=f"{tag} proposal", mix={"Stocks": 100},
                                note=f"{tag} why")
        proposals.share(c, a, shared)
        ids[f"{side}.proposal"] = shared
        ids[f"{side}.draft"] = proposals.save(c, a, cid, title=f"{tag} draft",
                                              mix={"Bonds": 100})
        ids[f"{side}.report"] = reports.save(
            c, a, cid, label="Q3 2026", start=date(2026, 7, 1), end=date(2026, 9, 30),
            facts={"value_end": fig, "who": tag}, message=f"{tag} report")
        # a former client: someone who signed in, so their account stays
        gone = auth.create_client(c, a, ex, name=f"{tag} former")
        ids[f"{side}.former"] = gone
        c.execute("UPDATE users SET last_login_at = ? WHERE id = ?",
                  ("2026-09-01 10:00:00", gone))
        c.commit()
        advising.end_relationship(c, a, gone, by="advisor", now=now)

    # ---- the harness -------------------------------------------------------- #
    def setUp(self):
        self.db = os.path.join(self.tmp, f"{self._testMethodName}.db")
        shutil.copy(self.template, self.db)
        self.c = portfolio.connect(self.db)
        self.alice, self.bob = self.ids["A.investor"], self.ids["B.investor"]
        self.carol, self.omar = self.ids["A.advisor"], self.ids["B.advisor"]
        self.dana, self.zed = self.ids["A.client"], self.ids["B.client"]
        self.b_ids = {self.bob, self.omar, self.zed, self.ids["B.former"]}
        self.a_ids = {self.alice, self.carol, self.dana, self.ids["A.former"]}

    def tearDown(self):
        self.c.close()

    def b_rows(self) -> dict:
        """Every row of B's, in every account table."""
        out = {}
        for table, cols in admin.ACCOUNT_TABLES.items():
            where = " OR ".join(f"{col} IN ({', '.join('?' * len(self.b_ids))})"
                                for col in cols)
            rows = self.c.execute(f"SELECT * FROM {table} WHERE {where}",
                                  tuple(self.b_ids) * len(cols)).fetchall()
            out[table] = sorted(tuple(str(v) for v in tuple(r)) for r in rows)
        return out

    def clean(self, value):
        """A read of A's: nothing of B's in it."""
        text = repr(value)
        self.assertNotIn(B_MARK, text)
        self.assertNotIn(f"{B_FIG:.2f}"[:6], text)
        return value

    # ---- the matrix itself -------------------------------------------------- #
    def test_the_matrix_lists_every_account_table(self):
        self.assertEqual(set(MATRIX), set(admin.ACCOUNT_TABLES),
                         "a new account table needs its row in MATRIX, a check_<table> "
                         "method and B's rows in _seed")
        for table, helpers in MATRIX.items():
            self.assertTrue(callable(getattr(self, f"check_{table}", None)), table)
            for name in helpers:
                mod, fn = name.split(".")
                self.assertTrue(callable(getattr(_MODULES[mod], fn, None)), name)

    def test_b_has_rows_in_every_account_table(self):
        # otherwise "B's rows are unchanged" would hold for nothing
        empty = [t for t, rows in self.b_rows().items() if not rows]
        self.assertEqual(empty, [])

    def test_a_never_reads_changes_or_deletes_b(self):
        for table in MATRIX:
            with self.subTest(table=table):
                before = self.b_rows()
                getattr(self, f"check_{table}")()
                after = self.b_rows()
                for t in before:
                    self.assertEqual(after[t], before[t], f"{table}: B's {t} rows changed")

    def test_deleting_a_whole_account_leaves_the_other(self):
        before = self.b_rows()
        for uid in (self.alice, self.dana, self.carol, self.ids["A.former"]):
            self.assertTrue(admin.delete_account(self.c, uid, by=-1)["ok"])
        self.assertEqual(self.b_rows(), before)
        self.assertEqual(len(export.collect(self.c, self.bob)["holdings"]), 2)

    def test_the_note_helpers_need_the_advisor(self):
        # no "any advisor" (audit 1.2a): left out, or None, is refused
        c, dana, note = self.c, self.dana, self.ids["A.note"]
        calls = (lambda **k: advising.set_done(c, dana, note, True, **k),
                 lambda **k: advising.archive_note(c, dana, note, **k),
                 lambda **k: advising.restore_note(c, dana, note, **k),
                 lambda **k: advising.edit_note(c, dana, note, "x", **k))
        for call in calls:
            with self.assertRaises(TypeError):
                call()
            with self.assertRaises(ValueError):
                call(advisor_id=None)
        # an advisor's view (private notes too) says whose private notes
        with self.assertRaises(ValueError):
            advising.list_notes(c, dana, include_private=True)
        with self.assertRaises(ValueError):
            advising.notes_for(c, [dana], include_private=True)
        self.assertTrue(advising.list_notes(c, dana, include_private=False))   # a client's view

    def test_own_export_has_nothing_of_the_other(self):
        for uid in self.a_ids:
            self.clean(export.collect(self.c, uid))
        self.clean(export.client_record(self.c, self.carol, self.dana))
        self.clean(export.client_record(self.c, self.carol, self.ids["A.former"]))
        self.clean(export.all_client_records_zip(self.c, self.carol).decode("latin-1"))

    # ---- one check per table: A's helpers, B's rows ------------------------- #
    def check_snapshots(self):
        c, a = self.c, self.alice
        self.clean(portfolio.current_holdings(c, a))
        self.clean(portfolio.previous_snapshot(c, a, "2100-01-01"))
        self.assertEqual(portfolio.snapshot_source(c, a, SNAP), "ALICE.csv")
        # A saves again on the very date B has a snapshot from another file
        portfolio.write_snapshot(c, a, {"snapshot_date": SNAP, "as_of_text": "again"},
                                 [_position("ALICE Brokerage ...123", "VTI", "ALICE", 2.0)],
                                 {}, "other.csv")
        self.assertIsNone(portfolio.remove_account(c, a, self.ids["B.account"]))
        portfolio.clear_sample(c, a)
        c.commit()
        portfolio.delete_holdings(c, a)

    def check_positions(self):
        c, a = self.c, self.alice
        self.clean(portfolio.current_holdings(c, a))
        self.clean(account_map.brought_in(c, a))
        prepared = portfolio.prepare_save(
            c, a, {"snapshot_date": "2026-10-01", "as_of_text": None},
            [_position("ALICE Brokerage ...123", "VTI", "ALICE", 3.0, "2026-10-01")], {},
            "new.csv", today=date(2026, 10, 1))
        self.clean(prepared)
        portfolio.save_prepared(c, a, prepared, "new.csv")
        portfolio.remove_account(c, a, "ALICE Brokerage ...123", today=date(2026, 10, 2))
        c.commit()
        portfolio.delete_holdings(c, a)

    def check_account_totals(self):
        c, a = self.c, self.alice
        self.clean(portfolio.current_holdings(c, a)["totals"])
        self.clean(portfolio.previous_snapshot(c, a, "2100-01-01"))
        portfolio.write_snapshot(c, a, {"snapshot_date": SNAP, "as_of_text": None}, [],
                                 _totals(self.ids["B.account"], 1.0), "ALICE.csv")
        portfolio.delete_holdings(c, a)

    def check_transactions(self):
        c, a = self.c, self.alice
        self.clean(txn_import.existing_keys(c, a))
        self.clean(txn_import.covered(c, a))
        self.clean(plans.money_moves(c, a))
        self.clean(plans.imported_window(c, a))
        # the same account name and dates as B's: still only A's rows
        txn_import.save(c, a, [_txn(self.ids["B.account"], "BOBQ", "ALICE", 5.0)], "x.csv")
        txn_import.save_worked_out(c, a, "2026-09-20", [])
        c.commit()
        txn_import.refresh_gains(c, a)
        c.commit()

    def check_value_log(self):
        a = self.alice
        self.assertTrue(perf.log_open(self.db, a, {"portfolio_value": A_FIG, "n_positions": 1},
                                      min_gap_sec=0))
        self.clean(perf.last_open(self.db, a))
        self.clean(perf.history(self.db, a))

    def check_account_labels(self):
        c, a = self.c, self.alice
        self.clean(accounts.labels(c, a))
        accounts.set_label(c, a, self.ids["B.account"], "")       # B's account name: A's row only
        accounts.set_label(c, a, self.ids["B.account"], "mine now")
        accounts.set_label(c, a, "ALICE Brokerage ...123", "")

    def check_investor_profiles(self):
        c, a = self.c, self.alice
        self.clean(advisor.get_profile(c, a))
        self.clean(advisor.get_profiles(c, [a]))
        self.clean(advisor.get_profile_and_memory(c, a))
        advisor.save_profile(c, a, {"goal": "changed"}, replace=True)
        advisor.save_memory(c, a, "")

    def check_watchlist(self):
        c, a = self.c, self.alice
        self.assertNotIn(self.ids["B.ticker"], self.clean(watchlist.list_tickers(c, a)))
        watchlist.add(c, a, self.ids["B.ticker"])
        watchlist.remove(c, a, self.ids["B.ticker"])
        watchlist.remove(c, a, "VTI")

    def check_user_prefs(self):
        c, a = self.c, self.alice
        self.clean(prefs.load(c, a))
        self.clean(prefs.load_many(c, [a]))
        prefs.save(c, a, {})

    def check_plans(self):
        c, a = self.c, self.alice
        self.clean(plans.get_plan(c, a))
        self.clean(plans.get_plans(c, [a]))
        plans.save_plan(c, a, {"goal_name": None, "target_amount": None}, a)
        self.assertFalse(plans.may_change(c, a, self.bob))
        self.assertFalse(plans.may_change(c, self.carol, self.zed))

    def check_contributions(self):
        c, a = self.c, self.alice
        self.clean(plans.list_contributions(c, a))
        self.clean(plans.money_in_history(c, a))
        plans.add_contribution(c, a, "2026-09-01", 10.0)
        plans.delete_contribution(c, a, self.ids["B.contribution"])
        plans.delete_contribution(c, a, self.ids["A.contribution"])

    def check_login_sessions(self):
        c, a = self.c, self.alice
        mine = auth.create_session(c, a)
        self.assertEqual(auth.session_user(c, mine)[0], a)
        self.assertFalse(two_step.remember_device(c, self.tokens["B.session"], a))
        self.assertFalse(two_step.device_remembered(c, self.tokens["B.session"], a))
        auth.end_other_sessions(c, a, mine)
        auth.end_other_sessions(c, a, None)
        auth.end_session(c, self.tokens["A.session"])

    def check_ai_usage(self):
        c, a = self.c, self.alice
        self.assertEqual(ai_usage.used(c, a, "chat"), 1)
        self.assertEqual(ai_usage.status(c, a, "chat")["used"], 1)
        ai_usage.record(c, a, "chat")
        self.assertEqual(ai_usage.used(c, a, "chat"), 2)

    def check_email_tokens(self):
        c, a = self.c, self.alice
        self.assertEqual(auth.reset_info(c, self.tokens["A.reset"])["user_id"], a)
        self.assertIsNone(auth.reset_info(c, "not-a-token"))
        auth.setup_link(c, a)
        token = auth.request_password_reset(c, "alice@example.com")["token"]
        self.assertTrue(auth.reset_password(c, token, "new-password-123")["ok"])
        self.assertTrue(auth.confirm_email(c, self.tokens["A.confirm"])["ok"])
        # (confirmed now: no new confirm link to make)
        self.assertFalse(auth.start_confirmation(c, a)["ok"])

    def check_advisor_requests(self):
        c, a = self.c, self.alice
        self.clean(auth.advisor_request(c, a))
        auth.request_advisor(c, a, "Another Firm", "7654321")

    def check_invites(self):
        c = self.c
        with self.assertRaises(ValueError):
            auth.create_invite(c, self.carol, self.zed)
        self.assertIsNone(auth.invite_info(c, "not-a-token"))
        auth.create_invite(c, self.carol, self.dana)
        self.assertIsNotNone(auth.pending_invite(c, self.dana))
        auth.cancel_invite(c, self.dana)

    def check_advisor_clients(self):
        c, carol = self.c, self.carol
        self.assertNotIn(self.zed, [i for i, _ in self.clean(auth.list_clients(c, carol))])
        self.assertFalse(auth.can_view(c, carol, self.zed))
        self.assertFalse(auth.can_view(c, self.alice, self.bob))
        self.assertFalse(auth.set_client_name(c, carol, self.zed, "Mine now"))
        auth.unlink_client(c, carol, self.zed)
        self.assertIsNone(advising.ending_plan(c, carol, self.zed))
        self.assertFalse(advising.end_relationship(c, carol, self.zed, by="advisor")["ok"])
        self.assertTrue(auth.set_client_name(c, carol, self.dana, "Dana L."))

    def check_advisor_notes(self):
        c, carol, dana = self.c, self.carol, self.dana
        theirs, private = self.ids["B.note"], self.ids["B.private_note"]
        self.clean(advising.list_notes(c, dana, include_private=True, advisor_id=carol))
        self.clean(advising.notes_for(c, [dana], include_private=True, advisor_id=carol))
        # their private note never reaches another advisor, even on their client
        self.assertNotIn(private, [n["id"] for n in advising.list_notes(
            c, self.zed, include_private=True, advisor_id=carol)])
        for client in (dana, self.zed):
            self.assertFalse(advising.set_done(c, client, theirs, True, advisor_id=carol))
            self.assertFalse(advising.archive_note(c, client, theirs, advisor_id=carol))
            self.assertFalse(advising.restore_note(c, client, theirs, advisor_id=carol))
            self.assertFalse(advising.edit_note(c, client, theirs, "Carol was here",
                                                advisor_id=carol))
        mine = self.ids["A.note"]
        self.assertTrue(advising.set_done(c, dana, mine, True, advisor_id=carol))
        self.assertTrue(advising.edit_note(c, dana, mine, "Edited", advisor_id=carol))
        self.assertTrue(advising.archive_note(c, dana, mine, advisor_id=carol))
        self.assertTrue(advising.restore_note(c, dana, mine, advisor_id=carol))
        advising.add_note(c, dana, carol, "Note", "Another", "2026-09-05")

    def check_model_portfolios(self):
        c, carol = self.c, self.carol
        self.clean(advising.list_models(c, carol))
        advising.save_model(c, carol, f"{B_MARK} model", {"Stocks": 100})   # B's name: A's row
        advising.delete_model(c, carol, self.ids["B.model"])
        advising.delete_model(c, carol, self.ids["A.model"])

    def check_proposals(self):
        c, carol, dana = self.c, self.carol, self.dana
        self.clean(proposals.for_client(c, dana, include_drafts=True))
        for pid in (self.ids["B.proposal"], self.ids["B.draft"]):
            self.assertFalse(proposals.share(c, carol, pid))
            self.assertFalse(proposals.delete(c, carol, pid))
            self.assertFalse(proposals.archive(c, carol, pid))
            self.assertFalse(proposals.restore(c, carol, pid))
            self.assertFalse(proposals.respond(c, dana, pid, True))
            with self.assertRaises(ValueError):
                proposals.save(c, carol, dana, title="x", mix={"Stocks": 100}, proposal_id=pid)
        self.assertTrue(proposals.respond(c, dana, self.ids["A.proposal"], True))
        self.assertTrue(proposals.delete(c, carol, self.ids["A.draft"]))

    def check_progress_reports(self):
        c, dana = self.c, self.dana
        self.clean(reports.for_client(c, dana))
        self.clean(reports.sent(c, [dana]))
        self.assertEqual(reports.last_end(c, dana), "2026-09-30")
        reports.mark_read(c, dana, self.ids["B.report"])
        reports.mark_read(c, dana, self.ids["A.report"])
        reports.save(c, self.carol, dana, label="Q4 2026", start=date(2026, 10, 1),
                     end=date(2026, 12, 31), facts={}, message="")

    def check_two_step(self):
        c, a = self.c, self.alice
        self.assertTrue(two_step.status(c, a)["on"])
        # B's code doesn't let A in (and doesn't spend B's step)
        self.assertFalse(two_step.verify(c, a, two_step.totp(self.secrets["B"]))["ok"])
        secret = two_step.new_secret()
        self.assertTrue(two_step.enable(c, a, secret, two_step.totp(secret))["ok"])
        self.assertTrue(two_step.reset(c, a))
        self.assertTrue(two_step.reset(c, self.carol))

    def check_money_out(self):
        c, a, bob = self.c, self.alice, self.bob
        item = self.ids["B.money_out"]
        self.clean(plans.list_money_out(c, a, viewer=a))
        with self.assertRaises(PermissionError):
            plans.list_money_out(c, bob, viewer=a)
        with self.assertRaises(PermissionError):
            plans.add_money_out(c, bob, "expense", {"label": "x", "amount": 1,
                                                    "start_date": "2030-01-01"}, by=a)
        with self.assertRaises(PermissionError):
            plans.delete_money_out(c, bob, item, by=a)
        with self.assertRaises(LookupError):
            plans.update_money_out(c, a, item, {"amount": 1}, by=a)
        self.assertFalse(plans.delete_money_out(c, a, item, by=a))
        plans.add_money_out(c, a, "withdrawal", {"amount": 100, "start_date": "2040-01-01"},
                            by=a)
        self.assertTrue(plans.delete_money_out(c, a, self.ids["A.money_out"], by=a))

    def check_former_clients(self):
        c, carol = self.c, self.carol
        self.assertEqual([f["client_id"] for f in self.clean(advising.former_clients(c, carol))],
                         [self.ids["A.former"]])
        with self.assertRaises(PermissionError):
            export.client_record(c, carol, self.ids["B.former"])
        with self.assertRaises(PermissionError):
            export.client_record(c, carol, self.zed)
        # carol ends with dana: a former_clients row of hers, none of omar's touched
        self.assertTrue(advising.end_relationship(c, carol, self.dana, by="client")["ok"])

    def check_future_notes(self):
        c, a = self.c, self.alice
        self.clean(future_notes.get(c, a))
        self.clean(future_notes.get(c, a, self.ids["B.ticker"]))
        self.clean(future_notes.all_notes(c, a))
        future_notes.save(c, a, self.ids["B.ticker"], "Mine on their fund")
        future_notes.delete(c, a, self.ids["B.ticker"])
        future_notes.save(c, a, None, "")       # empty: deletes A's plan note only
        future_notes.delete(c, a)

    def check_account_map(self):
        c, a = self.c, self.alice
        self.clean(account_map.load(c, a))
        account_map.save_account(c, a, self.ids["B.account"], {"contact": "mine"})
        account_map.save_other(c, a, {"label": "Mine", "digits": "1"},
                               other_id=self.ids["B.map_other"])
        account_map.delete_entry(c, a, self.ids["B.map_other"])
        account_map.save_family(c, a, "")
        account_map.clear(c, a)


if __name__ == "__main__":
    unittest.main()
