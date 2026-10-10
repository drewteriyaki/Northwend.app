"""The one retention measure (R1, feature_counts.py): of the people whose
first monthly walk was more than 45 days ago, how many walked again within
45 days of it. The eligible group and the 45-day edges, who's left out
(opt-out, check-ins from before counting, admin logins, deleted accounts),
nothing under 20 (by month too, with no working one out by subtraction),
the owner's target (NORTHWEND_SECOND_WALK_TARGET) on the Admin panel, and
the RUNBOOK's SQL giving the code's own number. Made-up people only, on a
scratch database in a temp dir.

    python -m unittest tests.test_second_walk_measure      (from the repo root)
"""

import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import auth  # noqa: E402
import checkin  # noqa: E402
import feature_counts as fc  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import settings  # noqa: E402

TODAY = date(2027, 3, 31)
PW = "pw-123456789"


def walker(*days, off=False, before=None):
    """One account's settings with a walk on each of `days` (one a month,
    as checkin.finish keeps them)."""
    log, kept = list(before or []), {}
    for d in (d for d in days if d):
        m = f"{d.year:04d}-{d.month:02d}"
        log.append(m)
        kept[m] = {"kind": "within", "on": d.isoformat()}
    p = {checkin.PREF_LOG: sorted(log), checkin.PREF_VERDICTS: kept}
    if off:
        p[fc.PREF_OFF] = True
    return p


def runbook_sql(n):
    """The n-th ```sql block of docs/RUNBOOK.md's "The second-walk measure"."""
    with open(os.path.join(REPO, "docs", "RUNBOOK.md"), encoding="utf-8") as fh:
        text = fh.read()
    part = text.split("## The second-walk measure", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"```sql\n(.*?)```", part, re.S)[n]


class DefinitionTests(unittest.TestCase):

    def test_the_45_day_edges(self):
        closed_on = TODAY - timedelta(days=46)      # day 45 was yesterday: over
        still_open = TODAY - timedelta(days=45)     # day 45 is today: not over yet
        self.assertTrue(fc.window_closed(closed_on, TODAY))
        self.assertFalse(fc.window_closed(still_open, TODAY))
        self.assertTrue(fc.walked_again(closed_on, closed_on + timedelta(days=45)))
        self.assertFalse(fc.walked_again(closed_on, closed_on + timedelta(days=46)))
        self.assertFalse(fc.walked_again(closed_on, None))
        # month-end to the next month's first: a second walk a day later counts
        self.assertTrue(fc.walked_again(date(2026, 10, 31), date(2026, 11, 1)))

    def test_eligible_group_only(self):
        a = TODAY - timedelta(days=46)
        people = ([walker(a, a + timedelta(days=45)) for _ in range(12)]     # day 45: yes
                  + [walker(a, a + timedelta(days=46)) for _ in range(4)]    # day 46: no
                  + [walker(a) for _ in range(4)]                            # never: no
                  # day 45 is today: a first walk, but not in the group yet
                  + [walker(TODAY - timedelta(days=45)) for _ in range(7)])
        self.assertEqual(fc.walk_totals(people, TODAY),
                         {"first_walks": 27, "window_closed": 20, "second_walks": 12})
        # the next day they're in, and they didn't walk again
        self.assertEqual(fc.walk_totals(people, TODAY + timedelta(days=1)),
                         {"first_walks": 27, "window_closed": 27, "second_walks": 12})

    def test_only_the_first_two_walks_matter(self):
        a = TODAY - timedelta(days=100)
        late_then_often = walker(a, a + timedelta(days=50), a + timedelta(days=80))
        self.assertEqual(fc.first_two(late_then_often), (a, a + timedelta(days=50)))
        people = [late_then_often] * 20
        self.assertEqual(fc.walk_totals(people, TODAY)["second_walks"], 0)

    def test_left_out_and_from_before(self):
        a = TODAY - timedelta(days=60)
        people = [walker(a, a + timedelta(days=30)) for _ in range(20)]
        self.assertEqual(fc.walk_totals(people, TODAY)["second_walks"], 20)
        people += [walker(a, off=True)] * 5 + [walker(a, before=["2026-01"])] * 5
        self.assertEqual(fc.walk_totals(people, TODAY),
                         {"first_walks": 20, "window_closed": 20, "second_walks": 20})
        people[0] = walker(a, a + timedelta(days=30), off=True)
        self.assertIsNone(fc.walk_totals(people, TODAY))                      # 19 now

    def test_odd_dates_are_skipped(self):
        a = TODAY - timedelta(days=60)
        p = walker(a)
        p[checkin.PREF_VERDICTS]["2026-12"] = {"kind": "within", "on": "soon"}
        p[checkin.PREF_VERDICTS]["2026-11"] = "junk"
        p[checkin.PREF_VERDICTS][f"{a.year:04d}-{a.month:02d}"]["on"] += "T23:59:00Z"
        self.assertEqual(fc.first_two(p), (a, None))

    def test_nothing_under_twenty(self):
        a = TODAY - timedelta(days=60)
        self.assertIsNone(fc.walk_totals([walker(a, a + timedelta(days=9))] * 19, TODAY))
        recent = TODAY - timedelta(days=10)
        people = [walker(a)] * 19 + [walker(recent)] * 5
        self.assertEqual(fc.walk_totals(people, TODAY),
                         {"first_walks": 24, "window_closed": 19, "second_walks": None})
        self.assertIsNone(fc.walk_month_totals(people, TODAY))


class ByMonthTests(unittest.TestCase):

    def test_months_of_twenty_or_more(self):
        oct_, nov, dec = date(2026, 10, 5), date(2026, 11, 5), date(2026, 12, 5)
        people = ([walker(oct_, oct_ + timedelta(days=30))] * 15 + [walker(oct_)] * 10
                  + [walker(nov, nov + timedelta(days=30))] * 21
                  + [walker(dec)] * 22)
        self.assertEqual(fc.walk_month_totals(people, TODAY), [
            {"month": "2026-10", "people": 25, "second": 15},
            {"month": "2026-11", "people": 21, "second": 21},
            {"month": "2026-12", "people": 22, "second": 0}])

    def test_a_month_still_open_is_not_listed(self):
        # February's people are all in the group for the total (their 45 days
        # are over) but the month isn't: a Feb 28 first walk's window is still open
        feb = date(2027, 2, 1)
        people = [walker(feb, feb + timedelta(days=40))] * 20 + [walker(date(2026, 12, 1))] * 25
        rows = fc.walk_month_totals(people, date(2027, 3, 20))
        self.assertEqual([r["month"] for r in rows], ["2026-12"])
        # Feb's 20 aren't shown, and that's 20: December needn't be held back
        self.assertEqual(rows[0], {"month": "2026-12", "people": 25, "second": 0})

    def test_small_months_cant_be_worked_out(self):
        oct_, nov, dec = date(2026, 10, 5), date(2026, 11, 5), date(2026, 12, 5)
        people = ([walker(oct_, oct_ + timedelta(days=30))] * 30
                  + [walker(nov)] * 25
                  + [walker(dec, dec + timedelta(days=30))] * 3)      # a month of 3
        rows = fc.walk_month_totals(people, TODAY)
        # December alone would be the total minus the others: November (the
        # smaller shown month) is held back too, so 28 are hidden together
        self.assertEqual(rows, [
            {"month": "2026-10", "people": 30, "second": 30},
            {"month": "2026-11", "people": 25, "second": None},
            {"month": "2026-12", "people": None, "second": None}])
        total = fc.walk_totals(people, TODAY)
        hidden = total["window_closed"] - sum(r["people"] for r in rows if r["second"] is not None)
        self.assertGreaterEqual(hidden, fc.MIN_GROUP)


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_second_walk_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def person(self, name, p):
        uid = auth.create_user(self.conn, name, PW)
        prefs.save(self.conn, uid, p)
        return uid


class FromTheDatabaseTests(_DB):

    def test_admins_and_deleted_accounts_are_not_counted(self):
        c = self.conn
        a = TODAY - timedelta(days=60)
        for i in range(20):
            self.person(f"w{i}", walker(a, a + timedelta(days=30) if i < 5 else None))
        boss = self.person("boss", walker(a, a + timedelta(days=30)))
        self.person("Owner", walker(a, a + timedelta(days=30)))
        gone = self.person("gone", walker(a, a + timedelta(days=30)))
        c.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (boss,))
        c.commit()
        # "owner" is in NORTHWEND_ADMINS (any case): the caller passes it in
        self.assertEqual(fc.walks(c, TODAY, ["owner"]),
                         {"first_walks": 21, "window_closed": 21, "second_walks": 6})
        self.assertEqual(admin.delete_account(c, gone, by=boss)["ok"], True)
        self.assertEqual(fc.walks(c, TODAY, ["OWNER"]),
                         {"first_walks": 20, "window_closed": 20, "second_walks": 5})
        self.assertEqual(fc.walks(c, TODAY)["first_walks"], 21)   # Owner, not listed
        # settings left behind with no login aren't anyone's: not counted
        c.execute("INSERT INTO user_prefs (user_id, data) VALUES (?, ?)",
                  (99999, '{"walk_verdicts": {"2027-01": {"on": "2027-01-04"}}}'))
        c.commit()
        self.assertEqual(fc.walks(c, TODAY, ["owner"])["first_walks"], 20)

    def test_the_runbook_sqlite_query_gives_the_same_number(self):
        c = self.conn
        # the SQL's own today (date('now'), UTC), for the code too
        today = date.fromisoformat(c.execute("SELECT date('now') AS d").fetchone()["d"])
        a =today - timedelta(days=60)
        later = today - timedelta(days=10)
        made = [walker(a, a + timedelta(days=45))] * 9 + [walker(a, a + timedelta(days=46))] * 4
        made += [walker(a)] * 8 + [walker(later)] * 3 + [walker(a, off=True)] * 4
        made += [walker(a, before=["2001-01"])] * 2
        made += [walker(today - timedelta(days=46), today - timedelta(days=1))] * 2   # edge: in
        made += [walker(today - timedelta(days=45))]                                   # edge: out
        for i, p in enumerate(made):
            self.person(f"s{i}", p)
        boss = self.person("boss", walker(a, a + timedelta(days=1)))
        c.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (boss,))
        c.commit()
        mine = fc.walks(c, today)
        self.assertEqual(mine, {"first_walks": 27, "window_closed": 23, "second_walks": 11})
        row = c.execute(runbook_sql(2)).fetchone()
        self.assertEqual((row["first_walks"], row["window_closed"], row["second_walks"]),
                         (27, 23, 11))
        self.assertEqual(row["percent"], round(100 * 11 / 23))
        # under 20 first walks: no row at all
        c.execute("DELETE FROM user_prefs WHERE user_id IN (SELECT id FROM users "
                  "WHERE username IN ('s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7'))")
        c.commit()
        self.assertIsNone(fc.walks(c, today))
        self.assertIsNone(c.execute(runbook_sql(2)).fetchone())

    def test_the_runbook_names_the_same_rules(self):
        pg = runbook_sql(0)
        for words in ('"walk_verdicts"', "feature_counts_off", "checkin_log", "is_admin",
                      "+ 45 < current_date", "second_on <= first_on + 45",
                      "window_closed >= 20", "first_walks >= 20"):
            self.assertIn(words, pg)
        self.assertIn("HAVING count(*) >= 20", runbook_sql(1))
        self.assertEqual((fc.SECOND_WITHIN_DAYS, fc.MIN_GROUP, fc.PREF_OFF,
                          checkin.PREF_VERDICTS, checkin.PREF_LOG),
                         (45, 20, "feature_counts_off", "walk_verdicts", "checkin_log"))


class TargetTests(unittest.TestCase):

    def test_the_setting(self):
        for raw, want in (("", None), ("40", 40.0), ("37.5%", 37.5), (" 50 ", 50.0),
                          ("lots", None), ("-1", None), ("101", None)):
            with unittest.mock.patch.dict(os.environ, {"NORTHWEND_SECOND_WALK_TARGET": raw}):
                self.assertEqual(settings.second_walk_target(), want, raw)


class AdminPanelTests(_DB):
    PANEL = """
import sys, os
sys.path.insert(0, {repo!r})
from datetime import datetime
import pandas as pd
import streamlit as st
import auth, mailer, pgcompat
from portfolio import connect
HERE = {repo!r}
DB = {db!r}
STAGING = False
HOSTED = False
LOGIN_ID = 1
IS_ADVISOR = False
path = os.path.join(HERE, "views", "admin.py")
with open(path, encoding="utf-8") as fh:
    exec(compile(fh.read(), path, "exec"), globals())
c = connect(DB)
_render_feature_tests(c)
c.close()
"""

    def _panel(self, target=""):
        from streamlit.testing.v1 import AppTest
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_SECOND_WALK_TARGET": target,
                                                   "NORTHWEND_ADMINS": "owner"}):
            at = AppTest.from_string(self.PANEL.format(repo=REPO, db=self.db),
                                     default_timeout=30).run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        return " ".join([h.value for h in at.subheader] + [m.value for m in at.markdown]
                        + [c.value for c in at.caption])

    def test_the_rate_the_target_and_the_months(self):
        today = datetime.now().date()
        first = date(today.year, today.month, 1) - timedelta(days=120)   # a whole month back
        first = first.replace(day=3)
        for i in range(22):
            self.person(f"walker{i}", walker(first, first + timedelta(days=30) if i < 11 else None))
        self.person("owner", walker(first, first + timedelta(days=30)))   # NORTHWEND_ADMINS
        text = self._panel()
        self.assertIn("Walked again within 45 days: 11 of 22 (50%)", text)
        self.assertNotIn("target", text.replace("The target is", ""))
        text = self._panel("40")
        self.assertIn("Walked again within 45 days: 11 of 22 (50%) · target 40%", text)
        self.assertIn(f"{first:%Y-%m}: 11 of 22 (50%)", text)
        self.assertIn("Admin logins aren't counted", text)
        for i in range(22):
            self.assertNotIn(f"walker{i}", text)
        self.assertNotIn("owner", text)

    def test_target_shown_while_too_few(self):
        text = self._panel("35")
        self.assertIn("Fewer than 20 people have finished a first walk so far - nothing to "
                      "show yet. · target 35%", text)


if __name__ == "__main__":
    unittest.main()
