"""Saving holdings (views/holdings_input.py's review and save): what changed,
the buys and sells worked out from it, account numbers kept to their last 3
digits everywhere, and holdings from several brokerages side by side - a save
updates only the accounts in it and keeps the others as they are. The save is
the same two steps the view takes: portfolio.prepare_save (the review), then
portfolio.save_prepared. The App classes drive the app itself (AppTest).

    python -m unittest tests.test_import_save        (from the repo root)
"""

import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import accounts  # noqa: E402
import auth  # noqa: E402
import changes  # noqa: E402
import csv_import  # noqa: E402
import manual_entry  # noqa: E402
import perf  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import txn_import  # noqa: E402

BROKERS = os.path.join(os.path.dirname(__file__), "fixtures", "brokers")
SCHWAB = os.path.join(os.path.dirname(__file__), "fixtures", "sample_positions.csv")
# positions exports, and the columns to read when the names don't say
POSITION_FILES = {"vanguard_download.csv": None, "fidelity_positions.csv": None,
                  "etrade_portfolio.csv": None,
                  "odd_layout.csv": {"symbol": 0, "quantity": 1, "cost": 2, "value": 3}}
# a 401(k) export with a pooled fund known only by its CUSIP
FIDELITY_401K = (
    "Account Number,Account Name,Symbol,Description,Quantity,Last Price,Current Value,"
    "Cost Basis Total\n"
    "71234,ACME CORP 401(K) PLAN,FXAIX,FIDELITY 500 INDEX FUND,120.512,$245.10,$29537.49,"
    "$22000.00\n"
    "71234,ACME CORP 401(K) PLAN,31617E471,FID CONTRAFUND POOL CL 2,180.0,$28.40,$5112.00,"
    "$4200.00\n")


def read_file(path, mapping=None, day=None, account_default="My account"):
    """A positions file as the CSV import reads it: (meta, rows, totals, parsed)."""
    with open(path, "rb") as fh:
        rows = csv_import.read_rows(fh.read())
    hi, _ = csv_import.find_header(rows)
    hi = hi if hi is not None else csv_import.guess_header(rows)
    found = csv_import.parse(rows, mapping or csv_import.auto_mapping(rows[hi]),
                             today=day or date(2026, 9, 30))
    meta, prow, totals = csv_import.to_snapshot(found, account_default=account_default)
    return meta, prow, totals, found


def dated(meta, rows, day):
    """The same holdings, saved as of `day`."""
    meta = {**meta, "snapshot_date": day.isoformat()}
    return meta, [{**r, "snapshot_date": day.isoformat()} for r in rows]


def save_p(conn, user_id, meta, rows, totals, src="upload: test.csv", **kw):
    """The view's review and save: returns what the review showed
    (portfolio.prepare_save's result)."""
    p = portfolio.prepare_save(conn, user_id, meta, rows, totals, src, **kw)
    portfolio.save_prepared(conn, user_id, p, src)
    return p


def save(conn, user_id, meta, rows, totals, src="upload: test.csv", **kw):
    """The view's review and save: returns (diff, the trades worked out)."""
    p = save_p(conn, user_id, meta, rows, totals, src, **kw)
    return p["diff"], p["txns"]


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_save_")
        self.db = os.path.join(self.dir, "test.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.user_id = auth.create_user(self.conn, "saver", "pw-123456789")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def trades(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT account, action, symbol, quantity, realized_gain FROM transactions "
            "WHERE user_id = ? ORDER BY id", (self.user_id,))]


class WhatChangedTests(_DB):

    def test_the_same_file_again_changes_nothing(self):
        meta, rows, totals, _ = read_file(os.path.join(BROKERS, "vanguard_download.csv"))
        save(self.conn, self.user_id, *dated(meta, rows, date(2026, 9, 1)), totals)
        d, txns = save(self.conn, self.user_id, *dated(meta, rows, date(2026, 9, 2)), totals)
        self.assertEqual((len(d["new"]), len(d["closed"]), len(d["increased"]),
                          len(d["decreased"]), len(d["unchanged"])), (0, 0, 0, 0, 3))
        self.assertEqual(txns, [])
        self.assertEqual(self.trades(), [])
        # a real change is still worked out, in the account as saved
        more = [{**r, "quantity": r["quantity"] + 2} if r["symbol"] == "VTSAX" else r
                for r in rows]
        d, txns = save(self.conn, self.user_id, *dated(meta, more, date(2026, 9, 3)), totals)
        self.assertEqual([(t["account"], t["action"], t["symbol"], t["quantity"])
                          for t in self.trades()], [("...678", "BUY", "VTSAX", 2.0)])

    def test_a_first_save_is_where_an_account_starts_not_buys(self):
        clean, cash, _ = manual_entry.validate(
            [{"Account": "Roth", "Symbol": "VTI", "Shares": 10, "Total cost": 2000}], [])
        found = {"VTI": {"price": 300.0}, "SCHD": {"price": 28.0}}
        meta, rows, totals, _ = manual_entry.build(clean, cash, found, today=date(2026, 9, 1))
        _, txns = save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertEqual(txns, [])                      # the very first save
        # later: one more share of VTI, and a new account with 1,100 SCHD
        clean, cash, _ = manual_entry.validate(
            [{"Account": "Roth", "Symbol": "VTI", "Shares": 11, "Total cost": 2300},
             {"Account": "Brokerage", "Symbol": "SCHD", "Shares": 1100, "Total cost": 28000}], [])
        meta, rows, totals, _ = manual_entry.build(clean, cash, found, today=date(2026, 9, 2))
        d, txns = save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertEqual(len(d["new"]), 1)              # still shown as new in the review
        self.assertEqual([(t["account"], t["action"], t["symbol"]) for t in self.trades()],
                         [("Roth", "BUY", "VTI")])      # but SCHD wasn't bought that day
        # an account left out of a save wasn't sold off either
        clean, cash, _ = manual_entry.validate(
            [{"Account": "Brokerage", "Symbol": "SCHD", "Shares": 1000, "Total cost": 25000}], [])
        meta, rows, totals, _ = manual_entry.build(clean, cash, found, today=date(2026, 9, 3))
        _, txns = save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertEqual([(t["account"], t["action"], t["symbol"], t["quantity"]) for t in txns],
                         [("Brokerage", "SELL", "SCHD", 100.0)])

    def test_an_account_with_only_cash_before_records_its_buys(self):
        clean, cash, _ = manual_entry.validate([], [{"Account": "Roth", "Cash": 5000}])
        meta, rows, totals, _ = manual_entry.build(clean, cash, {}, today=date(2026, 9, 1))
        save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        clean, cash, _ = manual_entry.validate([{"Account": "Roth", "Symbol": "VTI", "Shares": 10}],
                                               [{"Account": "Roth", "Cash": 2000}])
        meta, rows, totals, _ = manual_entry.build(clean, cash, {"VTI": {"price": 300.0}},
                                                   today=date(2026, 9, 2))
        _, txns = save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertEqual([(t["action"], t["symbol"]) for t in txns], [("BUY", "VTI")])

    def test_the_example_portfolio_replaced_by_a_first_import_is_not_sold(self):
        sample_data.load(self.conn, self.user_id, today=date(2026, 9, 1))
        meta, rows, totals, _ = read_file(SCHWAB)
        d, txns = save(self.conn, self.user_id, *dated(meta, rows, date(2026, 9, 2)), totals)
        self.assertEqual((d["closed"], txns, self.trades()), ([], [], []))
        self.assertEqual(portfolio.previous_snapshot(self.conn, self.user_id, "2026-09-03")[0],
                         "2026-09-02")


class AccountNumberTests(_DB):

    def test_no_table_ever_holds_a_full_account_number(self):
        files = [(os.path.join(BROKERS, n), m) for n, m in POSITION_FILES.items()]
        files += [(SCHWAB, None)]
        plain = os.path.join(self.dir, "fid401k.csv")
        with open(plain, "w", encoding="utf-8") as fh:
            fh.write(FIDELITY_401K)
        files += [(plain, None)]
        numbers = set()
        day = date(2026, 1, 1)
        for path, mapping in files:
            meta, rows, totals, found = read_file(path, mapping)
            numbers |= {n for h in found["holdings"] for n in re.findall(r"\d{5,}", h["Account"])}
            for change in range(3):   # first save, the same again, then a change
                day += timedelta(days=1)
                if change == 2:
                    rows = [{**r, "quantity": r["quantity"] + 1} for r in rows[:-1]] or rows
                save(self.conn, self.user_id, *dated(meta, rows, day), totals,
                     f"upload: {os.path.basename(path)}")
            accounts.set_label(self.conn, self.user_id, rows[0]["account"], "Mine")
        self.assertTrue({"12345678", "87654321", "71234"} <= numbers, numbers)
        self.assertTrue(self.trades())               # some trades were worked out
        dump = "\n".join(self.conn.iterdump())
        for n in numbers:
            self.assertNotIn(n, dump)
        for table in portfolio.ACCOUNT_COLUMNS:
            for r in self.conn.execute(f"SELECT DISTINCT account FROM {table}"):
                self.assertEqual(accounts.mask_number(r["account"]), r["account"], table)

    def test_old_rows_are_masked_once_when_the_app_starts(self):
        c, uid = self.conn, self.user_id
        c.execute("INSERT INTO transactions (account, trade_date, action, symbol, user_id) "
                  "VALUES ('12345678', '2026-09-01', 'BUY', 'VTI', ?)", (uid,))
        c.execute("INSERT INTO transactions (account, trade_date, action, symbol, user_id) "
                  "VALUES ('Roth IRA', '2026-09-01', 'BUY', 'VTI', ?)", (uid,))
        for acct in ("Individual Z12345678", "Individual ...999", "Individual 55554999"):
            c.execute("INSERT INTO positions (snapshot_date, account, symbol, quantity, user_id, "
                      "imported_at) VALUES ('2026-09-01', ?, 'VTI', 1, ?, datetime('now'))",
                      (acct, uid))
        c.execute("INSERT INTO account_totals (snapshot_date, account, cash_value, user_id, "
                  "imported_at) VALUES ('2026-09-01', 'Individual Z12345678', 5, ?, "
                  "datetime('now'))", (uid,))
        c.execute("INSERT INTO account_labels (user_id, account, nickname) "
                  "VALUES (?, 'Individual Z12345678', 'Main')", (uid,))
        c.commit()
        c.close()
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))   # the next process start
        self.conn = c = portfolio.connect(self.db)
        self.assertEqual(sorted(r["account"] for r in c.execute("SELECT account FROM transactions")),
                         ["...678", "Roth IRA"])
        self.assertEqual(sorted(r["account"] for r in c.execute("SELECT account FROM positions")),
                         ["Individual ...678", "Individual ...999", "Individual ...999 (2)"])
        self.assertEqual([r["account"] for r in c.execute("SELECT account FROM account_totals")],
                         ["Individual ...678"])
        self.assertEqual([r["account"] for r in c.execute("SELECT account FROM account_labels")],
                         ["Individual ...678"])
        # ("Individual ...999" already held VTI that day: kept apart, not merged.)
        self.assertEqual(portfolio._mask_saved_accounts(c), {})   # nothing left to do


class LastVisitTests(_DB):

    def test_since_your_last_visit_starts_again_after_a_save(self):
        perf.log_open(self.db, self.user_id, {"portfolio_value": 100000.0}, min_gap_sec=0)
        hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.conn.execute("UPDATE value_log SET logged_at = ?", (hour_ago,))
        self.conn.commit()
        self.assertEqual(perf.last_open(self.db, self.user_id)["portfolio_value"], 100000.0)
        clean, cash, _ = manual_entry.validate([{"Symbol": "VTI", "Shares": 10}], [])
        meta, rows, totals, _ = manual_entry.build(clean, cash, {"VTI": {"price": 300.0}})
        save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertIsNone(perf.last_open(self.db, self.user_id))   # that visit saw other holdings
        perf.log_open(self.db, self.user_id, {"portfolio_value": 3000.0}, min_gap_sec=0)
        self.assertEqual(perf.last_open(self.db, self.user_id)["portfolio_value"], 3000.0)


class SkippedRowTests(unittest.TestCase):

    def test_a_row_without_a_ticker_is_named_not_imported(self):
        rows = csv_import.read_rows(FIDELITY_401K.encode())
        hi, _ = csv_import.find_header(rows)
        found = csv_import.parse(rows, csv_import.auto_mapping(rows[hi]))
        self.assertEqual([h["Symbol"] for h in found["holdings"]], ["FXAIX"])   # as before
        self.assertEqual(found["left_out"], [{"Name": "FID CONTRAFUND POOL CL 2",
                                              "Value": 5112.0, "why": "it has no ticker"}])
        self.assertEqual(csv_import.left_out_text(found["left_out"]),
                         "1 row skipped, not imported: FID CONTRAFUND POOL CL 2 ($5,112.00)"
                         " - it has no ticker.")
        for name, mapping in POSITION_FILES.items():   # nothing made up for the others
            self.assertEqual(read_file(os.path.join(BROKERS, name), mapping)[3]["left_out"], [],
                             name)


# What a Robinhood holdings page gives when copied: name, ticker, shares, value.
ROBINHOOD_PASTE = """Apple
AAPL
12 shares
$2,761.20

NVIDIA
NVDA
20 shares
$3,640.00

Tesla
TSLA
8 shares
$2,096.00

Vanguard S&P 500 ETF
VOO
6.5 shares
$3,654.95

Invesco QQQ
QQQ
5 shares
$2,607.00
"""
ROBINHOOD_PRICES = {"AAPL": 230.10, "NVDA": 182.0, "TSLA": 262.0, "VOO": 562.30, "QQQ": 521.40}


def pasted(text, account, prices, day):
    """A paste as the hand-entry window saves it: (meta, rows, totals)."""
    import paste_parse
    found = paste_parse.parse(text)
    clean, cash, errors = manual_entry.validate(
        [{"Account": account, "Symbol": h["Symbol"], "Shares": h["Shares"],
          "Total cost": h["Total cost"], "Type": "Other"} for h in found["holdings"]],
        [{"Account": account, "Cash": found["cash"]}])
    assert not errors, errors
    meta, rows, totals, errors = manual_entry.build(
        clean, cash, {s: {"price": p} for s, p in prices.items()}, today=day)
    assert not errors, errors
    return meta, rows, totals


def file_account(path):
    """The account the import suggests for a file that doesn't name one."""
    with open(path, "rb") as fh:
        rows = csv_import.read_rows(fh.read())
    hi, _ = csv_import.find_header(rows)
    return accounts.guess_broker("\n".join(" ".join(r) for r in rows), header=rows[hi],
                                 filename=os.path.basename(path))


def worth(conn, user_id):
    """{account: value} of the latest holdings, and their total."""
    cur = portfolio.current_holdings(conn, user_id)
    out = {}
    for r in cur["rows"]:
        out[r["account"]] = round(out.get(r["account"], 0.0) + r["market_value"], 2)
    for a, t in cur["totals"].items():
        out[a] = round(out.get(a, 0.0) + (t["cash_value"] or 0.0), 2)
    return out, round(sum(out.values()), 2)


class MergeTests(unittest.TestCase):
    """The pure parts: carrying accounts forward, and naming an account."""

    def test_carry_forward_replaces_only_the_accounts_in_the_save(self):
        cur = [{"account": "Individual Z12345678", "symbol": "VTI", "quantity": 10.0,
                "market_value": 3000.0, "snapshot_date": "2026-09-01"},
               {"account": "Roth", "symbol": "SCHD", "quantity": 100.0,
                "market_value": 2800.0, "snapshot_date": "2026-09-01"},
               {"account": "Old cash", "symbol": "BND", "quantity": 1.0,
                "market_value": 70.0, "snapshot_date": "2026-09-01"}]
        cur_totals = {"Individual Z12345678": {"cash_value": 50.0},
                      "Roth": {"cash_value": None}, "Old cash": {"cash_value": 5.0},
                      "Savings": {"cash_value": 900.0}}           # only cash
        new = [{"account": "Individual ...678", "symbol": "VTI", "quantity": 12.0,
                "market_value": 3600.0, "snapshot_date": "2026-09-02"}]
        new_totals = {"Individual ...678": {"cash_value": 10.0},
                      "Old cash": {"cash_value": 75.0}}           # in the save with cash only
        rows, totals, kept = changes.carry_forward(cur, cur_totals, new, new_totals,
                                                   "2026-09-02")
        self.assertEqual(kept, ["Roth", "Savings"])
        self.assertEqual(sorted((r["account"], r["symbol"], r["quantity"], r["snapshot_date"])
                                for r in rows),
                         [("Individual ...678", "VTI", 12.0, "2026-09-02"),   # the save's
                          ("Roth", "SCHD", 100.0, "2026-09-02")])            # carried, redated
        self.assertEqual({a: t["cash_value"] for a, t in totals.items()},
                         {"Individual ...678": 10.0, "Old cash": 75.0, "Roth": None,
                          "Savings": 900.0})
        self.assertEqual(cur[1]["snapshot_date"], "2026-09-01")   # the input isn't changed
        self.assertEqual(changes.accounts_in(new, new_totals), {"Individual ...678", "Old cash"})

    def test_the_brokerage_is_guessed_from_the_text_not_from_fund_names(self):
        g = accounts.guess_broker
        self.assertIsNone(g(ROBINHOOD_PASTE))               # "Vanguard S&P 500 ETF" is a fund
        self.assertIsNone(g("CHARLES SCHWAB CORP  SCHW  10"))
        self.assertIsNone(g("FIDELITY 500 INDEX FUND\nVANGUARD TOTAL STK MKT"))
        self.assertEqual(g("Robinhood\nAAPL 10"), "Robinhood")
        self.assertEqual(g("", filename="Robinhood_holdings_2026-10-01.csv"), "Robinhood")
        self.assertEqual(file_account(os.path.join(BROKERS, "etrade_portfolio.csv")), "E*TRADE")
        self.assertEqual(file_account(os.path.join(BROKERS, "vanguard_download.csv")), "Vanguard")
        self.assertEqual(file_account(os.path.join(BROKERS, "fidelity_positions.csv")), "Fidelity")
        self.assertEqual(file_account(SCHWAB), "Schwab")

    def test_a_suggested_account_never_lands_in_another_brokerage(self):
        s = accounts.suggest_account
        self.assertEqual(s(None, []), "Brokerage account")
        self.assertEqual(manual_entry.DEFAULT_ACCOUNT, accounts.NEW_ACCOUNT)
        # a second unnamed paste is a new account, not the first one again
        self.assertEqual(s(None, ["Brokerage account"]), "Brokerage account 2")
        self.assertEqual(s(None, ["Brokerage account", "brokerage account 2"]),
                         "Brokerage account 3")
        # the same brokerage again updates its account (by name or nickname)
        self.assertEqual(s("E*TRADE", ["E*TRADE", "Roth"]), "E*TRADE")
        self.assertEqual(s("Fidelity", ["Individual ...678"], {"Individual ...678": "My Fidelity"}),
                         "Individual ...678")
        self.assertEqual(s("Fidelity", ["Roth"], {"Roth": "Fidelity"}), "Roth")
        self.assertEqual(s("Fidelity", ["Fidelity 2"]), "Fidelity 2")
        # two accounts at that brokerage: which one can't be told - a new name
        self.assertEqual(s("Schwab", ["Schwab", "Schwab Roth"]), "Schwab 2")
        self.assertEqual(s("Vanguard", ["Brokerage account"]), "Vanguard")
        self.assertEqual(manual_entry.PCT_SOURCE, portfolio.PCT_SOURCE)

    def test_an_account_left_as_saved_in_the_form_is_unchanged(self):
        saved = [{"account": "Roth", "symbol": "VTI", "quantity": 10.0, "cost_basis": 2500.0,
                  "asset_type": "ETFs & Closed End Funds"},
                 {"account": "Taxable", "symbol": "SCHD", "quantity": 100.0, "cost_basis": None,
                  "asset_type": "Cash and Money Market"}]
        cash = {"Roth": 0.0, "Taxable": 200.0}
        form, _ = manual_entry.prefill(saved, cash)
        form_cash = [{"Account": "Taxable", "Cash": 200.0}]
        clean, c, errors = manual_entry.validate(form, form_cash)
        self.assertEqual(errors, [])
        self.assertEqual(manual_entry.unchanged_accounts(clean, c, saved, cash), {"Roth", "Taxable"})
        form[1]["Shares"] = 101
        clean, c, _ = manual_entry.validate(form + [{"Account": "New", "Symbol": "BND",
                                                     "Shares": 1}], form_cash)
        self.assertEqual(manual_entry.unchanged_accounts(clean, c, saved, cash), {"Roth"})
        clean, c, _ = manual_entry.validate(form[:1], [{"Account": "Taxable", "Cash": 250.0}])
        self.assertEqual(manual_entry.unchanged_accounts(clean, c, saved, cash), {"Roth"})


class MultiBrokerTests(_DB):
    """A Fidelity file, a Robinhood paste and a Vanguard file, side by side."""

    FIDELITY = os.path.join(BROKERS, "fidelity_positions.csv")    # Sep 28, two accounts
    VANGUARD = os.path.join(BROKERS, "vanguard_download.csv")     # Sep 30
    ETRADE = os.path.join(BROKERS, "etrade_portfolio.csv")        # Sep 28, no account column

    def three(self):
        meta, rows, totals, _ = read_file(self.FIDELITY)
        p1 = save_p(self.conn, self.user_id, meta, rows, totals, "upload: Portfolio_Positions.csv")
        acct = accounts.suggest_account(accounts.guess_broker(ROBINHOOD_PASTE),
                                        changes.accounts_in(rows, totals))
        meta, rows, totals = pasted(ROBINHOOD_PASTE, acct, ROBINHOOD_PRICES, date(2026, 9, 29))
        p2 = save_p(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        meta, rows, totals, _ = read_file(self.VANGUARD)
        p3 = save_p(self.conn, self.user_id, meta, rows, totals, "upload: ofxdownload.csv")
        return p1, p2, p3

    def test_three_brokerages_end_up_side_by_side_with_no_made_up_trades(self):
        p1, p2, p3 = self.three()
        self.assertEqual(p2["updating"], ["Brokerage account"])
        self.assertEqual(p2["new"], ["Brokerage account"])
        self.assertEqual(p2["kept"], ["Individual ...678", "ROTH IRA ...321"])
        self.assertEqual(p3["updating"], ["...678"])
        self.assertEqual(p3["kept"], ["Brokerage account", "Individual ...678", "ROTH IRA ...321"])
        by_account, total = worth(self.conn, self.user_id)
        self.assertEqual(by_account, {"Individual ...678": 6097.26, "ROTH IRA ...321": 4932.15,
                                      "Brokerage account": 14759.15, "...678": 4340.15})
        self.assertEqual(total, 30128.71)
        self.assertEqual(p3["total"], total)                 # the review's total: everything
        self.assertEqual(portfolio.current_holdings(self.conn, self.user_id)["date"],
                         "2026-09-30")
        for p in (p1, p2, p3):                               # nothing "sold", nothing "bought"
            self.assertEqual((p["txns"], p["diff"]["closed"]), ([], []))
        self.assertEqual(self.trades(), [])

    def test_a_month_later_only_the_real_change_is_a_trade(self):
        self.three()
        before = portfolio.current_holdings(self.conn, self.user_id)
        meta, rows, totals, _ = read_file(self.VANGUARD)
        rows = [{**r, "quantity": round(r["quantity"] + 2.781, 3),
                 "market_value": round((r["quantity"] + 2.781) * 182.65, 2)}
                if r["symbol"] == "VTSAX" else r for r in rows]
        p = save_p(self.conn, self.user_id, *dated(meta, rows, date(2026, 10, 30)), totals,
                   "upload: ofxdownload (1).csv")
        self.assertEqual((len(p["diff"]["increased"]), len(p["diff"]["new"]),
                          len(p["diff"]["closed"]), len(p["diff"]["unchanged"])), (1, 0, 0, 2))
        self.assertEqual([(t["account"], t["action"], t["symbol"], t["quantity"])
                          for t in self.trades()], [("...678", "BUY", "VTSAX", 2.781)])
        after = portfolio.current_holdings(self.conn, self.user_id)
        self.assertEqual(after["date"], "2026-10-30")

        def held(cur, skip):
            return sorted((r["account"], r["symbol"], r["quantity"], r["market_value"],
                           r["cost_basis"]) for r in cur["rows"] if r["account"] != skip)
        self.assertEqual(held(after, "...678"), held(before, "...678"))   # others as they were
        self.assertEqual({a: t["cash_value"] for a, t in after["totals"].items()},
                         {a: t["cash_value"] for a, t in before["totals"].items()})

    def test_an_older_file_is_folded_into_the_current_holdings(self):
        self.three()
        acct = accounts.suggest_account(file_account(self.ETRADE), ["Individual ...678",
                                                                    "ROTH IRA ...321",
                                                                    "Brokerage account", "...678"])
        self.assertEqual(acct, "E*TRADE")
        meta, rows, totals, _ = read_file(self.ETRADE, account_default=acct)
        self.assertEqual(meta["snapshot_date"], "2026-09-28")
        p = save_p(self.conn, self.user_id, meta, rows, totals, "upload: PortfolioDownload.csv",
                   today=date(2026, 10, 2))
        self.assertEqual((p["older"], p["file_date"], p["meta"]["snapshot_date"]),
                         ("2026-09-30", "2026-09-28", "2026-10-02"))
        self.assertEqual((p["updating"], p["new"]), (["E*TRADE"], ["E*TRADE"]))
        self.assertEqual(len(p["kept"]), 4)
        self.assertEqual(p["txns"], [])
        by_account, total = worth(self.conn, self.user_id)
        self.assertEqual(by_account["E*TRADE"], 9088.41)
        self.assertEqual(total, round(30128.71 + 9088.41, 2))
        self.assertEqual(portfolio.current_holdings(self.conn, self.user_id)["date"], "2026-10-02")
        # no past snapshot was rewritten
        self.assertEqual(worth_on(self.conn, self.user_id, "2026-09-30"), 30128.71)
        self.assertEqual(self.trades(), [])

    def test_removing_an_account_keeps_the_others(self):
        self.three()
        self.assertIsNone(portfolio.remove_account(self.conn, self.user_id, "Nope"))
        snap = portfolio.remove_account(self.conn, self.user_id, "Brokerage account",
                                        today=date(2026, 10, 2))
        self.assertEqual(snap, "2026-10-02")
        by_account, total = worth(self.conn, self.user_id)
        self.assertEqual(sorted(by_account), ["...678", "Individual ...678", "ROTH IRA ...321"])
        self.assertEqual(total, round(30128.71 - 14759.15, 2))
        self.assertEqual(worth_on(self.conn, self.user_id, "2026-09-30"), 30128.71)   # history
        self.assertEqual(self.trades(), [])                  # removing isn't selling
        # and a later import without it doesn't bring it back
        meta, rows, totals, _ = read_file(self.VANGUARD)
        p = save_p(self.conn, self.user_id, *dated(meta, rows, date(2026, 10, 3)), totals)
        self.assertNotIn("Brokerage account", p["kept"])
        self.assertNotIn("Brokerage account", worth(self.conn, self.user_id)[0])

    def test_two_saves_the_same_day_keep_each_others_trades(self):
        self.three()
        meta, rows, totals, _ = read_file(self.FIDELITY)
        rows = [{**r, "quantity": r["quantity"] + 1} if r["symbol"] == "VTI" else r for r in rows]
        save(self.conn, self.user_id, *dated(meta, rows, date(2026, 10, 5)), totals)
        meta, rows, totals, _ = read_file(self.VANGUARD)
        rows = [{**r, "quantity": r["quantity"] - 1} if r["symbol"] == "VTIAX" else r for r in rows]
        save(self.conn, self.user_id, *dated(meta, rows, date(2026, 10, 5)), totals)
        self.assertEqual(sorted((t["account"], t["action"], t["symbol"]) for t in self.trades()),
                         [("...678", "SELL", "VTIAX"), ("Individual ...678", "BUY", "VTI")])
        # the same file again that day redoes only its own account's trades
        save(self.conn, self.user_id, *dated(meta, rows, date(2026, 10, 5)), totals)
        self.assertEqual(len(self.trades()), 2)
        self.assertEqual(len(worth(self.conn, self.user_id)[0]), 4)

    def test_the_example_and_percentages_portfolios_are_replaced_whole(self):
        sample_data.load(self.conn, self.user_id, today=date(2026, 9, 27))
        meta, rows, totals, _ = read_file(self.FIDELITY)
        p = save_p(self.conn, self.user_id, meta, rows, totals)
        self.assertEqual((p["replaces"], p["kept"], p["txns"]), ("example", [], []))
        self.assertEqual(sorted(worth(self.conn, self.user_id)[0]),
                         ["Individual ...678", "ROTH IRA ...321"])
        # a percentages portfolio is one pretend total: it replaces everything...
        clean, cash_pct, _ = manual_entry.validate_weights(
            [{"Account": "Pretend", "Symbol": "VTI", "Percent": 100}], 0, 10_000)
        meta, rows, totals, _ = manual_entry.build_weights(
            clean, cash_pct, 10_000, {"VTI": {"price": 300.0}}, today=date(2026, 9, 29))
        p = save_p(self.conn, self.user_id, meta, rows, totals, manual_entry.PCT_SOURCE,
                   whole=True)
        self.assertEqual((p["replaces"], p["kept"], p["txns"]), ("everything", [], []))
        self.assertEqual(list(worth(self.conn, self.user_id)[0]), ["Pretend"])
        # ...and real holdings replace it, with nothing bought or sold
        meta, rows, totals, _ = read_file(self.VANGUARD)
        p = save_p(self.conn, self.user_id, meta, rows, totals)
        self.assertEqual((p["replaces"], p["kept"], p["txns"], p["base_date"]),
                         ("percentages", [], [], None))
        self.assertEqual(list(worth(self.conn, self.user_id)[0]), ["...678"])
        self.assertEqual(self.trades(), [])

    def test_an_advisor_importing_for_a_client_merges_only_the_clients_accounts(self):
        client = auth.create_user(self.conn, "client1", "pw-123456789")
        meta, rows, totals, _ = read_file(self.FIDELITY)
        save(self.conn, self.user_id, meta, rows, totals)          # the advisor's own
        meta, rows, totals, _ = read_file(self.VANGUARD)
        save(self.conn, client, meta, rows, totals)
        meta, rows, totals = pasted(ROBINHOOD_PASTE, "Robinhood", ROBINHOOD_PRICES,
                                    date(2026, 10, 1))
        p = save_p(self.conn, client, meta, rows, totals, manual_entry.SOURCE)
        self.assertEqual(p["kept"], ["...678"])
        self.assertEqual(sorted(worth(self.conn, client)[0]), ["...678", "Robinhood"])
        self.assertEqual(sorted(worth(self.conn, self.user_id)[0]),
                         ["Individual ...678", "ROTH IRA ...321"])


def worth_on(conn, user_id, day):
    """The total value saved for one snapshot date."""
    v = conn.execute("SELECT COALESCE(SUM(market_value), 0) v FROM positions "
                     "WHERE snapshot_date = ? AND user_id = ?", (day, user_id)).fetchone()["v"]
    c = conn.execute("SELECT COALESCE(SUM(cash_value), 0) c FROM account_totals "
                     "WHERE snapshot_date = ? AND user_id = ?", (day, user_id)).fetchone()["c"]
    return round(v + c, 2)


class _AppBase(unittest.TestCase):
    """The app run with AppTest on a scratch database, as `USERNAME`
    (seeded by seed())."""
    USERNAME = "ann"

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or "")) == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_appsave_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.uid = auth.create_user(c, cls.USERNAME, "pw-123456789")
            cls.seed(c)
        finally:
            c.close()

    @classmethod
    def seed(cls, c):
        pass

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _app(self, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.uid, "username": self.USERNAME, "page": "Dashboard",
                     "auto_backfilled": True, "income_synced": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
        patches = [unittest.mock.patch.dict(os.environ, env, clear=True),
                   unittest.mock.patch.object(yfinance, "Ticker", offline),
                   unittest.mock.patch("socket.socket.connect", offline)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return at


class AppSaveTests(_AppBase):
    """The hand-entry window and Home."""

    @classmethod
    def seed(cls, c):
        clean, cash, _ = manual_entry.validate(
            [{"Symbol": "VTI", "Shares": 10, "Total cost": 2500},
             {"Symbol": "AAPL", "Shares": 5}], [])          # no cost for AAPL
        meta, rows, totals, _ = manual_entry.build(
            clean, cash, {"VTI": {"price": 300.0}, "AAPL": {"price": 230.0}})
        portfolio.write_snapshot(c, cls.uid, meta, rows, totals, manual_entry.SOURCE)

    def test_screenshots_are_read_once_and_counted_once(self):
        import streamlit
        at = self._app(open_dialog="manual")
        os.environ["NORTHWEND_FLAGS"] = "screenshot_ai"   # (flags.py; _app's patch puts it back)
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        reads = []

        def fake_read(images, key, **kw):
            reads.append(len(images))
            return {"holdings": [{"Symbol": "SCHD", "Shares": 3.0, "Total cost": None,
                                  "Percent": None, "Type": None}],
                    "cash": None, "mode": "Shares", "error": None, "answered": True}
        shot = types.SimpleNamespace(name="holdings.png", getvalue=lambda: b"\x89PNG\r\n\x1a\npng-bytes")
        real_uploader = streamlit.file_uploader

        def uploader(label, *a, key=None, **kw):
            if key and key.startswith("me_shots_"):
                return [shot]
            return real_uploader(label, *a, key=key, **kw)
        real_rerun = streamlit.rerun

        def rerun(*a, **kw):   # AppTest draws a window in the full run, not as a fragment
            return real_rerun(*a, **{**kw, "scope": "app"})
        for p in (unittest.mock.patch.object(sys.modules["screenshot_read"], "read", fake_read),
                  unittest.mock.patch.object(streamlit, "file_uploader", uploader),
                  unittest.mock.patch.object(streamlit, "rerun", rerun)):
            p.start()
            self.addCleanup(p.stop)
        at.session_state["open_dialog"] = "manual"
        at.run()
        at.checkbox(key="me_shots_ok_0").check()
        at.session_state["open_dialog"] = "manual"
        at.run()
        at.button(key="me_shots_btn").click()
        at.session_state["open_dialog"] = "manual"
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(reads, [1])
        self.assertEqual(at.session_state["me_shots_n"], 1)        # a fresh uploader and box
        self.assertNotIn("me_shots_ok_1", [c.key for c in at.checkbox if c.value])
        c = portfolio.connect(self.db)
        try:
            import ai_usage
            self.assertEqual(ai_usage.status(c, self.uid, "screenshot")["used"], 1)
        finally:
            c.close()
        # added to the form as a new account; the saved account's rows stay
        ids = at.session_state["me_ids"]
        self.assertEqual(len(ids), 3)
        self.assertEqual((at.session_state[f"me_sym_{ids[-1]}"],
                          at.session_state[f"me_acct_{ids[-1]}"]),
                         ("SCHD", "Brokerage account 2"))

    def test_a_new_hand_entry_row_is_type_other(self):
        at = self._app(open_dialog="manual")
        at.run()
        at.button(key="me_add").click()
        at.session_state["open_dialog"] = "manual"
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        last = at.session_state["me_ids"][-1]
        self.assertEqual(at.session_state[f"me_type_{last}"], "Other")

    def test_home_after_a_save_logs_a_fresh_baseline_and_shows_no_none(self):
        c = portfolio.connect(self.db)
        try:
            perf.log_open(self.db, self.uid, {"portfolio_value": 1.0}, min_gap_sec=0)
            n = c.execute("SELECT COUNT(*) n FROM value_log WHERE user_id = ?",
                          (self.uid,)).fetchone()["n"]
        finally:
            c.close()
        at = self._app(value_rebase=True)   # as _after_import leaves it
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        c = portfolio.connect(self.db)
        try:
            self.assertEqual(c.execute("SELECT COUNT(*) n FROM value_log WHERE user_id = ?",
                                       (self.uid,)).fetchone()["n"], n + 1)   # despite the gap
        finally:
            c.close()
        self.assertNotIn("value_rebase", at.session_state)
        table = at.dataframe[-1].value
        table = getattr(table, "data", table)
        self.assertIn("Cost Basis", table.columns)
        costs = list(table["Cost Basis"])
        self.assertIn("—", costs)                     # AAPL, entered without a cost
        self.assertFalse(any(v is None or (isinstance(v, float) and math.isnan(v)) for v in costs))


class MultiBrokerAppTests(_AppBase):
    """Several brokerages in the app: the review before a save, an older
    file, Remove on Home, and pasting into the hand-entry window. Each test
    starts from a Fidelity file and a Robinhood paste."""
    USERNAME = "bea"

    def setUp(self):
        c = portfolio.connect(self.db)
        try:
            portfolio.delete_holdings(c, self.uid)
            meta, rows, totals, _ = read_file(MultiBrokerTests.FIDELITY)
            save_p(c, self.uid, meta, rows, totals, "upload: Portfolio_Positions.csv")
            meta, rows, totals = pasted(ROBINHOOD_PASTE, "Brokerage account", ROBINHOOD_PRICES,
                                        date(2026, 9, 29))
            save_p(c, self.uid, meta, rows, totals, manual_entry.SOURCE)
        finally:
            c.close()

    def accounts_now(self):
        c = portfolio.connect(self.db)
        try:
            return worth(c, self.uid)
        finally:
            c.close()

    def text(self, at):
        return "\n".join([m.value for m in at.markdown] + [m.value for m in at.caption]
                         + [m.value for m in at.info])

    def run_import(self, path):
        at = self._app(open_dialog="import", csv_path=path)
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def test_the_review_says_what_is_updated_and_what_is_kept(self):
        at = self.run_import(MultiBrokerTests.VANGUARD)
        shown = self.text(at)
        self.assertIn("**Updating:** ...678 (new account)", shown)
        self.assertIn("**Kept as is:** Brokerage account ($14,759.15), Individual ...678 "
                      "($6,097.26), ROTH IRA ...321 ($4,932.15)", shown.replace("\\$", "$"))
        self.assertIn("Total **$30,128.71** across all your accounts", shown.replace("\\$", "$"))
        self.assertIn("3 new, 0 changed, 0 removed", shown)
        at.button(key="csv_save").click()
        at.session_state["open_dialog"] = "import"
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        by_account, total = self.accounts_now()
        self.assertEqual(sorted(by_account), ["...678", "Brokerage account", "Individual ...678",
                                              "ROTH IRA ...321"])
        self.assertEqual(total, 30128.71)

    def test_an_older_file_without_account_names_is_asked_about_and_folded_in(self):
        at = self.run_import(MultiBrokerTests.ETRADE)
        picks = [s for s in at.selectbox if (s.key or "").startswith("csv_acct_")]
        self.assertEqual([s.value for s in picks], ["E*TRADE"])
        shown = self.text(at)
        self.assertIn("This file is from Sep 28, 2026, older than your current holdings "
                      "(Sep 29, 2026) - its accounts are updated, the rest kept.", shown)
        self.assertIn("**Updating:** E*TRADE (new account)", shown)
        at.button(key="csv_save").click()
        at.session_state["open_dialog"] = "import"
        at.run()
        by_account, _ = self.accounts_now()
        self.assertEqual(by_account["E*TRADE"], 9088.41)
        self.assertEqual(len(by_account), 4)

    def test_remove_on_home_takes_out_one_account(self):
        at = self._app()
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(at.selectbox(key="acct_rm_pick").value, "Brokerage account")
        self.assertTrue(at.button(key="acct_rm_btn").disabled)   # asks first
        at.checkbox(key="acct_rm_ok_Brokerage account").check()
        at.run()
        at.button(key="acct_rm_btn").click()
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        by_account, total = self.accounts_now()
        self.assertEqual(sorted(by_account), ["Individual ...678", "ROTH IRA ...321"])
        self.assertEqual(total, round(6097.26 + 4932.15, 2))

    # audit X4: a failed save shows the calm message and an error code, never
    # the database's own text (it can carry SQL and the row's values)
    RAW = "UNIQUE constraint failed: positions.symbol VALUES (1861.5, 'Z12345678')"

    def assertCalm(self, at):
        shown = "\n".join(e.value for e in at.error)
        self.assertRegex(shown, r"nothing was changed\. .*error code \*\*[0-9a-f]{6}\*\*")
        everything = "\n".join(str(getattr(e, "value", "")) for e in
                               [*at.error, *at.success, *at.markdown, *at.caption, *at.toast])
        for raw in ("UNIQUE", "constraint", "1861.5", "Z12345678", "VALUES"):
            self.assertNotIn(raw, everything)

    def _failing(self, name):
        """After a first run: the app may have reloaded portfolio (codefresh)."""
        def boom(*a, **k):
            raise sqlite3.OperationalError(self.RAW)
        p = unittest.mock.patch.object(sys.modules["portfolio"], name, boom)
        p.start()
        self.addCleanup(p.stop)

    def test_a_failed_remove_shows_a_code_not_the_error(self):
        before = self.accounts_now()
        at = self._app()
        at.run()
        self._failing("remove_account")
        at.checkbox(key="acct_rm_ok_Brokerage account").check()
        at.run()
        at.button(key="acct_rm_btn").click()
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertCalm(at)
        self.assertIn("Removing it didn't work", at.error[0].value)
        self.assertEqual(self.accounts_now(), before)

    def test_a_failed_save_shows_a_code_not_the_error(self):
        before = self.accounts_now()
        at = self.run_import(MultiBrokerTests.VANGUARD)
        self._failing("save_prepared")
        at.button(key="csv_save").click()
        at.session_state["open_dialog"] = "import"
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertCalm(at)
        self.assertIn("Saving didn't work", at.error[0].value)
        self.assertEqual(self.accounts_now(), before)

    def test_pasting_adds_an_account_to_the_form(self):
        at = self._app(open_dialog="manual")
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        before = list(at.session_state["me_ids"])
        self.assertEqual(at.selectbox(key="me_paste_acct").value, "Brokerage account 2")
        for text, acct in (("VTI 10\nBND 5", "Brokerage account 2"),
                           ("SCHD 7", "Brokerage account 3")):
            at.session_state["me_paste"] = text
            at.session_state["open_dialog"] = "manual"
            at.run()
            at.button(key="me_paste_btn").click()
            at.session_state["open_dialog"] = "manual"
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            ids = at.session_state["me_ids"]
            self.assertEqual(ids[:len(before)], before)          # the saved rows stay
            added = [i for i in ids if at.session_state[f"me_acct_{i}"] == acct]
            self.assertEqual(len(added), len(text.splitlines()), acct)
        self.assertEqual(len(at.session_state["me_ids"]), len(before) + 3)


if __name__ == "__main__":
    unittest.main()
