"""The advisor directory (directory.py, views/directory.py; PLAN step 5 items
3-4 and 11, master brief 3.3 and 4.2, decision B4): what an advisor can put
in a listing (https-only scheduling link, length caps, plain text), when a
listing is shown, the one order - alphabetical by name within the person's
filters, checked on shuffled profiles for every filter combination - no
ranking fields or sort keys anywhere, only the B4 filters, the flag and gate
L2 hiding everything, client mode never seeing Find a guide, and browsing
writing nothing (no view logging, brief 3.4).

    python -m unittest tests.test_directory        (from the repo root)
"""

import ast
import contextlib
import itertools
import os
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import advisor  # noqa: E402
import auth  # noqa: E402
import directory  # noqa: E402
import flags  # noqa: E402
import licence_check  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
# every profile question answered, a goal, and Learn walked (as in test_invest_path)
READY = {"goal": "Build long-term wealth", "time_horizon_years": 10,
         "risk_tolerance": "moderate", "drawdown_reaction": "Hold and wait",
         "experience": "new", "age_range": "25-34", "income_stability": "Very stable",
         "emergency_fund": "3-6 months", "high_interest_debt": "None",
         "employer_match": "No match or no plan"}
GOAL = {"goal_type": "Build long-term wealth", "target_amount": 20000.0,
        "target_date": "2036-10-01", "monthly_contribution": 100.0}
LEARN_DONE = {"first_steps": {"done": True},
              "get_started_done": ["goal", "basics", "mix", "practice"]}


def _profile(name, firm="A Firm", **over):
    """A complete profile's fields."""
    fields = {"display_name": name, "firm": firm, "reg_type": "sec_ria",
              "reg_number": "1234567", "credentials": "CFP", "fee_models": ["flat"],
              "minimum": "none", "serves": ["new"], "states": ["NY"], "meeting": "both",
              "description": "Plain words about how I work.",
              "scheduling_url": "https://cal.example.com/me"}
    fields.update(over)
    return fields


def _db(tmp, name="dir.db"):
    path = os.path.join(tmp, name)
    portfolio._SCHEMA_READY.discard(os.path.abspath(path))
    return path


def _advisor(c, login):
    uid = auth.create_user(c, login, PW)
    auth.set_advisor(c, login, True)
    return uid


_REAL_OUTSIDE_CHECKS = directory._outside_checks


@contextlib.contextmanager
def _checks(*fns):
    """directory's outside checks (the licence and agreement modules,
    directory.OUTSIDE_CHECKS) replaced by these - none: approval alone."""
    with unittest.mock.patch.object(directory, "_outside_checks", lambda: list(fns)):
        yield


@contextlib.contextmanager
def _settings(flags_value="", gates_value=""):
    with unittest.mock.patch.dict(os.environ, {flags.FLAGS_SETTING: flags_value,
                                               flags.GATES_SETTING: gates_value}), \
            unittest.mock.patch.object(flags, "_secret", lambda name: None):
        yield


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(_checks())
        self.tmp = tempfile.mkdtemp(prefix="pt_dir_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.c = portfolio.connect(_db(self.tmp))
        self.addCleanup(self.c.close)


# --------------------------------------------------------------------------- #
# what an advisor can enter
# --------------------------------------------------------------------------- #
class ProfileValidationTests(_DbCase):

    def test_scheduling_link_is_https_only(self):
        ok = ("https://calendly.com/carol-ruiz", "https://cal.example.com/me?x=1",
              "HTTPS://Example.com/book")
        for url in ok:
            self.assertIsNone(directory.scheduling_link_error(url), url)
        bad = ("http://calendly.com/carol", "javascript:alert(1)", "ftp://x.com/a",
               "calendly.com/carol", "https://localhost/book", "https://user:pw@x.com/",
               "https://x.com/a b", "https://", "data:text/html,hi", "https://.com",
               "https://x.com/" + "a" * 300, "//x.com/a")
        for url in bad:
            self.assertIsNotNone(directory.scheduling_link_error(url), url)
        # through clean(): optional, but checked when given
        self.assertEqual(directory.clean(_profile("A", scheduling_url=""))[1], [])
        self.assertTrue(directory.clean(_profile("A", scheduling_url="http://x.com"))[1])

    def test_caps_and_plain_text(self):
        L = directory.LIMITS
        cases = {
            "display_name": "N" * (L["display_name"] + 1),
            "firm": "F" * (L["firm"] + 1),
            "description": "d" * (L["description"] + 1),
            "reg_number": "1" * (L["reg_number"] + 1),
            "credentials": ", ".join(f"C{i}" for i in range(L["credentials"] + 1)),
        }
        for field, value in cases.items():
            with self.subTest(field):
                self.assertTrue(directory.clean(_profile("A", **{field: value}))[1])
        at_cap = _profile("N" * L["display_name"], firm="F" * L["firm"],
                          description="d" * L["description"])
        self.assertEqual(directory.clean(at_cap)[1], [])
        self.assertTrue(directory.clean(_profile("A", credentials="X" * 31))[1])
        # the description is plain text: no links, emails or tags (the
        # scheduling link has its own box)
        for desc in ("Book at https://x.com/me", "see www.example.org", "visit ruizwealth.com",
                     "email carol@ruizwealth.com", "<b>bold</b>"):
            with self.subTest(desc):
                self.assertTrue(directory.clean(_profile("A", description=desc))[1])
        for name in ("Carol https://x.com", "carol@x.com"):
            self.assertTrue(directory.clean(_profile(name))[1])
        self.assertEqual(directory.clean(_profile("A", description="Smith & Co. since 2010, "
                                                  "e.g. retirement income."))[1], [])

    def test_choices_come_from_the_lists_and_keep_their_order(self):
        for field, value in (("fee_models", ["commission"]), ("serves", ["vip"]),
                             ("states", ["ZZ"]), ("minimum", "5m_plus"),
                             ("meeting", "phone"), ("reg_type", "insurance")):
            with self.subTest(field):
                self.assertTrue(directory.clean(_profile("A", **{field: value}))[1])
        clean, errors = directory.clean(_profile("A", fee_models=["hourly", "aum"],
                                                 states=["WY", "AL", "NY"],
                                                 credentials="CFA, CFP®, CFA"))
        self.assertEqual(errors, [])
        self.assertEqual(clean["fee_models"], ["aum", "hourly"])
        self.assertEqual(clean["states"], ["AL", "NY", "WY"])
        self.assertEqual(clean["credentials"], ["CFA", "CFP®"])

    def test_saving(self):
        carol = _advisor(self.c, "carol")
        alice = auth.create_user(self.c, "alice", PW)
        # only an approved advisor has a listing
        with self.assertRaises(PermissionError):
            directory.save_profile(self.c, alice, _profile("Alice"))
        # a draft can be saved unlisted; listing it needs every required field
        draft = {"display_name": "Carol Ruiz", "firm": "Ruiz Wealth"}
        self.assertTrue(directory.save_profile(self.c, carol, draft)["ok"])
        refused = directory.save_profile(self.c, carol, draft, listed=True)
        self.assertFalse(refused["ok"])
        self.assertIn("To be listed, fill in", refused["errors"][0])
        self.assertFalse(directory.get_profile(self.c, carol)["listed"])
        self.assertFalse(directory.set_listed(self.c, carol, True))
        # a wrong field saves nothing
        bad = directory.save_profile(self.c, carol, _profile("Carol", scheduling_url="http://x"))
        self.assertFalse(bad["ok"])
        self.assertEqual(directory.get_profile(self.c, carol)["display_name"], "Carol Ruiz")
        # complete: listed; credentials and the scheduling link are optional
        done = directory.save_profile(self.c, carol, _profile("Carol Ruiz", credentials="",
                                                              scheduling_url=""), listed=True)
        self.assertTrue(done["ok"], done)
        saved = directory.get_profile(self.c, carol)
        self.assertTrue(saved["listed"])
        self.assertEqual(saved["states"], ["NY"])
        self.assertTrue(directory.set_listed(self.c, carol, False))
        self.assertFalse(directory.get_profile(self.c, carol)["listed"])
        self.assertTrue(directory.delete_profile(self.c, carol))
        self.assertIsNone(directory.get_profile(self.c, carol))

    def test_the_public_record_link(self):
        p = directory.clean(_profile("A", reg_type="bd_rep", reg_number="7654321"))[0]
        self.assertEqual(directory.lookup(p), (
            "FINRA BrokerCheck", "https://brokercheck.finra.org/individual/summary/7654321"))
        p = directory.clean(_profile("A", reg_type="state_ria", reg_number="801-12345"))[0]
        self.assertEqual(directory.lookup(p)[1], "https://adviserinfo.sec.gov/")
        p = directory.clean(_profile("A", reg_type="sec_ria", reg_number="12345"))[0]
        self.assertEqual(directory.lookup(p)[1],
                         "https://adviserinfo.sec.gov/individual/summary/12345")


# --------------------------------------------------------------------------- #
# who's shown
# --------------------------------------------------------------------------- #
class ListingRuleTests(_DbCase):

    def setUp(self):
        super().setUp()
        self.carol = _advisor(self.c, "carol")
        self.assertTrue(directory.save_profile(self.c, self.carol, _profile("Carol Ruiz"),
                                               listed=True)["ok"])

    def names(self, filters=None):
        return [p["display_name"] for p in directory.listings(self.c, filters)]

    def test_approved_complete_and_listed(self):
        self.assertEqual(self.names(), ["Carol Ruiz"])
        self.assertEqual(directory.why_not_shown(self.c, self.carol), [])
        # listed off by the advisor
        directory.set_listed(self.c, self.carol, False)
        self.assertEqual(self.names(), [])
        self.assertIn("You've chosen not to be listed.",
                      directory.why_not_shown(self.c, self.carol))
        directory.set_listed(self.c, self.carol, True)
        # no longer an advisor: gone, though the row stays
        auth.set_advisor(self.c, "carol", False)
        self.assertEqual(self.names(), [])
        self.assertIn("Your advisor access isn't approved.",
                      directory.why_not_shown(self.c, self.carol))
        auth.set_advisor(self.c, "carol", True)
        self.assertEqual(self.names(), ["Carol Ruiz"])
        # incomplete (a field emptied behind the form's back): not shown
        self.c.execute("UPDATE advisor_profiles SET description = '' WHERE user_id = ?",
                       (self.carol,))
        self.c.commit()
        self.assertEqual(self.names(), [])
        self.assertTrue(any("Still to fill in" in w
                            for w in directory.why_not_shown(self.c, self.carol)))

    def test_licence_and_agreement_checks_when_their_modules_exist(self):
        # neither module there: skipped, approval stands
        self.assertEqual(self.names(), ["Carol Ruiz"])
        calls = []

        def current(conn, uid):
            calls.append(uid)
            return uid != self.carol
        fake = types.SimpleNamespace(licence_current=current)
        with _checks(lambda conn, uid: fake.licence_current(conn, uid)):
            self.assertEqual(self.names(), [])          # not current: left out
            self.assertIn(self.carol, calls)
            self.assertIn("Your licence check or advisor agreement needs renewing.",
                          directory.why_not_shown(self.c, self.carol))
            fake.licence_current = lambda conn, uid: True
            self.assertEqual(self.names(), ["Carol Ruiz"])

            def broken(conn, uid):
                raise RuntimeError("no evidence table yet")
            fake.licence_current = broken                # an error fails closed
            self.assertEqual(self.names(), [])
        with _checks(lambda conn, uid: False):           # the agreement not accepted
            self.assertEqual(self.names(), [])
        self.assertEqual(self.names(), ["Carol Ruiz"])

    def test_the_real_checks(self):
        # the modules themselves: no licence check on record is not current;
        # one recorded today is. The agreement asks nothing while its flag is off.
        import advisor_agreement
        self.assertEqual(directory.OUTSIDE_CHECKS, (("licence_check", "licence_current"),
                                                    ("advisor_agreement", "tools_open")))
        self.assertEqual(_REAL_OUTSIDE_CHECKS(),
                         [licence_check.licence_current, advisor_agreement.tools_open])
        real = (licence_check.licence_current, advisor_agreement.tools_open)
        with _settings(), _checks(*real):
            self.assertEqual(self.names(), [])
            licence_check.record(self.c, self.carol, source="BrokerCheck", crd="7012345",
                                 checked_on=licence_check._today().isoformat())
            self.assertEqual(self.names(), ["Carol Ruiz"])
        with _settings(flags_value="advisor_agreement"), _checks(*real):
            self.assertEqual(self.names(), [])           # the flag on: not accepted yet
            advisor_agreement.accept(self.c, self.carol, ticked=True)
            self.assertEqual(self.names(), ["Carol Ruiz"])

    def test_state_coverage(self):
        # PLAN step 5 item 11: not shown for a state they didn't list
        self.assertEqual(self.names({"state": "NY"}), ["Carol Ruiz"])
        self.assertEqual(self.names({"state": "CA"}), [])

    def test_only_the_b4_filters(self):
        self.assertEqual(directory.FILTERS,
                         ("state", "meeting", "fee_models", "serves", "minimum"))
        for not_a_filter in ("credentials", "reg_type", "description", "scheduling_url",
                             "one_time_cost", "one_time", "rank", "sort", "order", "featured",
                             "rating"):
            with self.subTest(not_a_filter), self.assertRaises(ValueError):
                directory.listings(self.c, {not_a_filter: "x"})
        with self.assertRaises(ValueError):
            directory.listings(self.c, {"state": "ZZ"})
        with self.assertRaises(ValueError):
            directory.listings(self.c, {"fee_models": ["commission"]})


# --------------------------------------------------------------------------- #
# the one order
# --------------------------------------------------------------------------- #
NAMES = ["anna Lee", "Ánna Bell", "Ben O'Hara", "ben Adams", "Chloé Diaz", "Dmitri Volkov",
         "Eve", "Eve", "Femi Okafor", "zack Young", "Zoë Abbott", "Ōta Ken", "Mary-Kate Ruiz",
         "Mary Kate Ruiz", "Lu Wei", "Yusuf Ali"]


class OrderTests(_DbCase):
    """Profiles saved in shuffled order, with every filter value varied; the
    result is alphabetical by name for every filter combination."""

    def setUp(self):
        super().setUp()
        rnd = random.Random(20261006)
        fees = [k for k, _ in directory.FEE_MODELS]
        serves = [k for k, _ in directory.SERVES]
        mins = [k for k, _ in directory.MINIMUMS]
        meets = [k for k, _ in directory.MEETING]
        # a one-time review (ADR 0005) varied too: offered at a price, "ask", or not
        once = ["", "ask", "1", "99", "250", "10000"]
        self.specs = []
        for i, name in enumerate(NAMES):
            self.specs.append(_profile(
                name, firm=f"Firm {chr(90 - i)}",       # firms in the other order
                fee_models=rnd.sample(fees, rnd.randint(1, 3)),
                serves=rnd.sample(serves, rnd.randint(1, 3)),
                minimum=rnd.choice(mins), meeting=rnd.choice(meets),
                one_time_cost=rnd.choice(once),
                states=rnd.sample(["NY", "CA", "TX", "WA"], rnd.randint(1, 3))))
        rnd.shuffle(self.specs)
        for i, spec in enumerate(self.specs):
            uid = _advisor(self.c, f"adv{i}")
            self.assertTrue(directory.save_profile(self.c, uid, spec, listed=True)["ok"])

    def test_every_filter_combination_is_alphabetical(self):
        expected_all = sorted(self.specs, key=lambda s: directory.sort_key(s))
        everyone = directory.listings(self.c)
        self.assertEqual([(p["display_name"], p["firm"]) for p in everyone],
                         [(s["display_name"], s["firm"]) for s in expected_all])
        options = {
            "state": [None, "NY", "CA", "TX", "WA", "AK"],
            "meeting": [None, "virtual", "in_person"],
            "fee_models": [None, ["aum"], ["flat", "hourly"], ["subscription"]],
            "serves": [None, ["new"], ["retirement", "business"]],
            "minimum": [None, "none", "100k_250k", "500k_1m"],
        }
        n = 0
        for combo in itertools.product(*options.values()):
            filters = {k: v for k, v in zip(options, combo) if v is not None}
            got = directory.listings(self.c, filters)
            keys = [directory.sort_key(p) for p in got]
            self.assertEqual(keys, sorted(keys), filters)
            # filtering only removes: the rest keep the alphabetical order
            self.assertEqual([p["user_id"] for p in got],
                             [p["user_id"] for p in everyone if directory.matches(p, filters)])
            n += 1
        self.assertEqual(n, 6 * 3 * 4 * 3 * 4)
        # the one-time review is in the mix, and moves no one
        self.assertGreater(len({p["one_time_cost"] for p in everyone}), 2)

    def test_the_names_in_order(self):
        # case, accents and punctuation don't move anyone; the firm only splits
        # two identical names
        names = [p["display_name"] for p in directory.listings(self.c)]
        self.assertEqual(names, ["Ánna Bell", "anna Lee", "ben Adams", "Ben O'Hara",
                                 "Chloé Diaz", "Dmitri Volkov", "Eve", "Eve", "Femi Okafor",
                                 "Lu Wei", "Mary Kate Ruiz", "Mary-Kate Ruiz", "Ōta Ken",
                                 "Yusuf Ali", "zack Young", "Zoë Abbott"])
        eves = [p["firm"] for p in directory.listings(self.c) if p["display_name"] == "Eve"]
        self.assertEqual(eves, sorted(eves))

    def test_shuffled_input_same_output(self):
        rows = directory.visible(self.c)
        for seed in range(25):
            mixed = rows[:]
            random.Random(seed).shuffle(mixed)
            self.assertEqual(directory.in_order(mixed), rows)

    def test_the_sort_key_reads_only_the_name_and_firm(self):
        p = directory.listings(self.c)[0]
        other = {**p, "user_id": 10 ** 6, "updated_at": "1999-01-01T00:00:00Z",
                 "credentials": ["CFP", "CFA", "PhD"], "fee_models": ["aum"], "states": ["CA"],
                 "minimum": "1m_plus", "listed": False, "description": "x",
                 "scheduling_url": "", "reg_type": "bd_rep", "reg_number": "1",
                 "one_time_cost": "ask" if p["one_time_cost"] != "ask" else "10000"}
        self.assertEqual(directory.sort_key(p), directory.sort_key(other))
        # one profile, one-time review changed through every value: same key
        for value in ("", "ask", "1", "250", "10000"):
            self.assertEqual(directory.sort_key({**p, "one_time_cost": value}),
                             directory.sort_key(p))


class NoRankingTests(unittest.TestCase):
    """Nothing to rank by, and no other order, anywhere in the directory's code."""
    RANKING = re.compile(r"rank|score|featur|rating|review|priorit|boost|weight|sponsor|"
                         r"promot|paid|bid|impression|click|view_count|views|popular|"
                         r"match_score|best", re.I)

    def _tree(self, rel):
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            src = fh.read()
        return src, ast.parse(src)

    def test_no_sort_but_the_name(self):
        for rel in ("directory.py", os.path.join("views", "directory.py")):
            src, tree = self._tree(rel)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (
                    fn.attr if isinstance(fn, ast.Attribute) else "")
                if name in ("sorted", "sort", "min", "max", "nlargest", "nsmallest", "shuffle",
                            "choice", "sample"):
                    key = next((k.value for k in node.keywords if k.arg == "key"), None)
                    self.assertTrue(rel == "directory.py" and isinstance(key, ast.Name)
                                    and key.id == "sort_key",
                                    f"{rel}:{node.lineno}: {name}() other than by sort_key")
            sql = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
                   and isinstance(n.value, str) and re.search(r"\bSELECT\b", n.value)]
            self.assertFalse([s for s in sql if re.search(r"ORDER\s+BY", s, re.I)], rel)
            self.assertNotIn("import random", src, rel)
        # sorted(..., key=sort_key) is in exactly one place: in_order
        src, tree = self._tree("directory.py")
        self.assertEqual(src.count("key=sort_key"), 1)

    def test_no_ranking_fields(self):
        c = sqlite3.connect(":memory:")
        self.addCleanup(c.close)
        with open(os.path.join(REPO, "schema.sql"), encoding="utf-8") as fh:
            c.executescript(fh.read())
        cols = [r[1] for r in c.execute("PRAGMA table_info(advisor_profiles)")]
        self.assertEqual(cols, ["user_id", *directory.FIELDS, "listed", "updated_at"])
        with open(os.path.join(REPO, "schema_pg.sql"), encoding="utf-8") as fh:
            pg = fh.read()
        block = pg[pg.index("CREATE TABLE IF NOT EXISTS advisor_profiles"):]
        block = block[:block.index(");")]
        for col in cols:
            self.assertIn(f"    {col} ", block)
        for col in cols:
            self.assertIsNone(self.RANKING.search(col), col)
        # nor any name in the code: functions, variables, attributes, dict keys
        for rel in ("directory.py", os.path.join("views", "directory.py")):
            _, tree = self._tree(rel)
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
            bad = sorted(n for n in names if self.RANKING.search(n))
            self.assertEqual(bad, [], rel)

    def test_only_the_advisors_own_edits_write(self):
        """No function that a person browsing calls writes anything: SQL that
        changes rows is only in save_profile, set_listed and delete_profile."""
        _, tree = self._tree("directory.py")
        writers = set()
        for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and re.search(r"\b(INSERT|UPDATE|DELETE)\b", node.value)):
                    writers.add(fn.name)
        self.assertEqual(writers, {"save_profile", "set_listed", "delete_profile"})
        # and the intro button's hook records nothing
        result = directory.request_intro_placeholder(1, 2)
        self.assertEqual(result, {"sent": False, "message": directory.INTROS_SOON})

    def test_the_draft_copy(self):
        self.assertEqual(directory.COPY_STATUS, "DRAFT")
        words = " ".join((directory.INTRO, *directory.ABOUT_LINES, directory.ORDER_LINE,
                          directory.PRIVACY_LINE)).lower()
        for said in ("independent", "flat fee", "never paid per client",
                     "doesn't recommend, rate or vet", "alphabetical",
                     "nothing about your browsing is recorded"):
            self.assertIn(said, words)
        # never a nudge that they need one
        for nudge in ("you need an advisor", "you should", "get matched", "best advisor",
                      "recommended advisor", "top advisor"):
            self.assertNotIn(nudge, words)


# --------------------------------------------------------------------------- #
# ADR 0005: a one-time review, the calm link, "How advisors are paid"
# --------------------------------------------------------------------------- #
# words the directory's own copy never uses (education only; never a nudge,
# a ranking or a hint that Northwend refers or is paid per lead)
NEVER_SAID = re.compile(r"\bshould\b|\bbest\b|recommend|\btop\b|\branked\b|\bcheapest\b|"
                        r"\bmust\b|per lead|referr|refer you|matched|deadline|hurry|\btoday\b",
                        re.I)


class OneTimeReviewTests(_DbCase):

    def test_what_can_be_saved(self):
        ok = [(None, ""), ("", ""), ("  ", ""), ("ask", "ask"), ("ASK", "ask"), (1, "1"),
              (250, "250"), (250.0, "250"), ("250", "250"), ("$1,250", "1250"),
              ("1250.00", "1250"), (10_000, "10000")]
        for raw, saved in ok:
            with self.subTest(raw=raw):
                self.assertEqual(directory.one_time_value(raw), (saved, None))
        for raw in (0, -5, 10_001, 99.5, "free", "250/hr", "https://x.com", "1e3", True,
                    "none given", "２５０", [250]):
            with self.subTest(raw=raw):
                value, problem = directory.one_time_value(raw)
                self.assertEqual(value, "")
                self.assertIn("One-time review", problem)
        # through clean(): optional, and checked when given
        self.assertEqual(directory.clean(_profile("A"))[0]["one_time_cost"], "")
        self.assertTrue(directory.clean(_profile("A", one_time_cost="cheap"))[1])
        self.assertEqual(directory.clean(_profile("A", one_time_cost=300))[0]["one_time_cost"],
                         "300")

    def test_saved_shown_in_plain_words_and_exported(self):
        import export
        carol = _advisor(self.c, "carol")
        self.assertTrue(directory.save_profile(self.c, carol, _profile("Carol", one_time_cost=1500),
                                               listed=True)["ok"])
        p = directory.get_profile(self.c, carol)
        self.assertEqual(p["one_time_cost"], "1500")
        self.assertEqual(directory.describe(p)["one_time"],
                         "Offered - $1,500, the price as the advisor states it")
        self.assertEqual(directory.describe({**p, "one_time_cost": "ask"})["one_time"],
                         "Offered - ask the advisor for the price")
        self.assertEqual(directory.describe({**p, "one_time_cost": ""})["one_time"], "")
        # a wrong price saves nothing
        self.assertFalse(directory.save_profile(self.c, carol, _profile("Carol",
                                                                        one_time_cost=0))["ok"])
        self.assertEqual(directory.get_profile(self.c, carol)["one_time_cost"], "1500")
        # in Export everything (export.OWN: your_directory_listing)
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(export.export_zip(self.c, carol)))
        listing = z.read("your_directory_listing.csv").decode()
        self.assertIn("one_time_cost", listing.splitlines()[0])
        self.assertIn("1500", listing)

    def test_an_old_database_gets_the_column(self):
        # made before the column: the back-fill adds it (portfolio._ensure_schema)
        path = _db(self.tmp, "old.db")
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE advisor_profiles (user_id INTEGER PRIMARY KEY, "
                    "display_name TEXT NOT NULL DEFAULT '', listed INTEGER NOT NULL DEFAULT 0, "
                    "updated_at TEXT NOT NULL)")
        old.execute("INSERT INTO advisor_profiles (user_id, display_name, updated_at) "
                    "VALUES (1, 'Old', '2026-01-01T00:00:00Z')")
        old.commit()
        old.close()
        c = portfolio.connect(path)
        self.addCleanup(c.close)
        cols = [r[1] for r in c.execute("PRAGMA table_info(advisor_profiles)")]
        self.assertIn("one_time_cost", cols)
        self.assertEqual(c.execute("SELECT one_time_cost FROM advisor_profiles").fetchone()[0], "")

    def test_never_a_filter_or_an_order(self):
        self.assertNotIn("one_time_cost", directory.FILTERS)
        self.assertEqual(len(directory.FILTERS), 5)
        for key in ("one_time_cost", "one_time"):
            with self.assertRaises(ValueError):
                directory.check_filters({key: "ask"})
        self.assertIn("Paid to the advisor directly", directory.ONE_TIME_NOTE)
        self.assertIn("Northwend takes no part of it", directory.ONE_TIME_NOTE)


class GuideLinkTests(unittest.TestCase):

    def test_who_sees_it(self):
        base = dict(directory_on=True, is_advisor=False, is_admin=False, client_mode=False,
                    has_advisor=False)
        self.assertTrue(directory.guide_link_shown(**base))
        for off in base:
            with self.subTest(off):
                flipped = {**base, off: not base[off]}
                self.assertFalse(directory.guide_link_shown(**flipped))
        self.assertEqual((directory.GUIDE_LINE, directory.GUIDE_BUTTON),
                         ("Want a second opinion?", "Find a guide"))


class FeeExplainerTests(unittest.TestCase):

    def test_every_fee_model_in_the_listings_own_order(self):
        keys = [k for k, *_ in directory.FEES_EXPLAINED]
        self.assertEqual(keys, [k for k, _ in directory.FEE_MODELS] + ["commission"])
        labels = {k: label for k, label, _ in directory.FEES_EXPLAINED}
        self.assertIn("one-time review", labels["flat"])
        for k, label, words in directory.FEES_EXPLAINED:
            with self.subTest(k):
                self.assertIn("Ask ", words)       # each says what to ask, none favoured
                self.assertLess(len(words), 400)
        self.assertGreaterEqual(len(directory.FEES_QUESTIONS), 4)
        text = " ".join(directory.FEES_QUESTIONS).lower()
        for said in ("paid", "conflicts of interest", "fiduciary", "form crs"):
            self.assertIn(said, text)

    def test_official_sites_only(self):
        from urllib.parse import urlsplit
        self.assertTrue(directory.OFFICIAL_SITES)
        for name, url in directory.OFFICIAL_SITES:
            with self.subTest(url):
                parts = urlsplit(url)
                self.assertEqual(parts.scheme, "https")
                self.assertTrue(any(parts.hostname == h or parts.hostname.endswith("." + h)
                                    for h in directory.OFFICIAL_HOSTS), url)
        hosts = {urlsplit(u).hostname for _, u in directory.OFFICIAL_SITES}
        self.assertEqual(hosts, {"www.investor.gov", "brokercheck.finra.org",
                                 "adviserinfo.sec.gov"})
        # no other links in the words
        words = " ".join([directory.FEES_INTRO, directory.FEES_CONFLICTS,
                          *directory.FEES_QUESTIONS,
                          *(w for _, _, w in directory.FEES_EXPLAINED)])
        self.assertIsNone(re.search(r"https?://|www\.", words))

    def test_the_new_words_are_education_only(self):
        self.assertEqual(directory.COPY_STATUS, "DRAFT")
        new_copy = [directory.FEES_TITLE, directory.FEES_INTRO, directory.FEES_CONFLICTS,
                    directory.FEES_QUESTIONS_TITLE, *directory.FEES_QUESTIONS,
                    *(f"{label} {w}" for _, label, w in directory.FEES_EXPLAINED),
                    directory.ONE_TIME_NOTE, directory.GUIDE_LINE, directory.GUIDE_BUTTON,
                    *(label for _, label in directory.ONE_TIME_CHOICES),
                    directory.one_time_words("ask"), directory.one_time_words("250")]
        for line in new_copy:
            with self.subTest(line[:40]):
                self.assertIsNone(NEVER_SAID.search(line), line)
                self.assertNotRegex(line, r"\d+(\.\d+)?\s*%")   # no invented figures


# --------------------------------------------------------------------------- #
# the flag and the gate
# --------------------------------------------------------------------------- #
class FlagTests(unittest.TestCase):

    def test_needs_the_flag_and_gate_l2(self):
        self.assertEqual(flags.FEATURES["directory"],
                         {"gates": ("L2",), "view": "directory", "page": "Find a guide"})
        for flag_value, gate_value, on in (("", "", False), ("directory", "", False),
                                           ("", "L2", False), ("directory", "L0,L1,L3", False),
                                           ("directory", "L2", True)):
            with self.subTest(flags=flag_value, gates=gate_value), \
                    _settings(flag_value, gate_value):
                self.assertEqual(flags.on("directory"), on)
                self.assertEqual(flags.view_on("directory"), on)
                self.assertEqual(flags.page_on("Find a guide"), on)


class DirectoryAppTests(unittest.TestCase):
    """The app itself (AppTest): Find a guide in an individual's name menu
    only with the flag and L2 on, never for an advisor's client or an
    advisor; the advisor's listing on Your clients; browsing writes nothing."""

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.tmp = tempfile.mkdtemp(prefix="pt_dir_app_")
        cls.db = _db(cls.tmp, "app.db")
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)          # an individual
            sample_data.load(c, cls.alice)
            cls.carol = _advisor(c, "carol")                      # an advisor
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dave = auth.create_user(c, "dave", PW)            # carol's client
            auth.link_client(c, cls.carol, cls.dave)
            sample_data.load(c, cls.dave)
            directory.save_profile(c, cls.carol, _profile("Zed Carol Ruiz", states=["NY", "CA"]),
                                   listed=True)
            for login, name, once in (("adv_b", "Bea Okafor", "250"),
                                      ("adv_m", "Marcus Lee", "")):
                uid = _advisor(c, login)
                directory.save_profile(c, uid, _profile(name, meeting="virtual",
                                                        one_time_cost=once), listed=True)
            # an individual who has finished Learn and set a goal (ADR 0005's link)
            cls.lena = auth.create_user(c, "lena", PW)
            advisor.save_profile(c, cls.lena, READY)
            plans.save_plan(c, cls.lena, GOAL, set_by=cls.lena)
            prefs.save(c, cls.lena, LEARN_DONE)
            # carol's client has finished Learn with a goal too (set by carol) -
            # never the link
            advisor.save_profile(c, cls.dave, READY)
            plans.save_plan(c, cls.dave, GOAL, set_by=cls.carol)
            prefs.save(c, cls.dave, LEARN_DONE)
            # an admin, the same as lena otherwise - never the link
            import admin
            cls.ada = auth.create_user(c, "ada", PW)
            admin.set_admin(c, "ada", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.ada, secret, two_step.totp(secret))
            cls.ada_ok = f"{cls.ada}:{two_step.status(c, cls.ada)['stamp']}"
            advisor.save_profile(c, cls.ada, READY)
            plans.save_plan(c, cls.ada, GOAL, set_by=cls.ada)
            prefs.save(c, cls.ada, LEARN_DONE)
            # each advisor's licence checked today (licence_check.py), so they're listed
            for uid in (cls.carol, *(r["id"] for r in c.execute(
                    "SELECT id FROM users WHERE username IN ('adv_b', 'adv_m')"))):
                licence_check.record(c, uid, source="BrokerCheck", crd="7012345",
                                     checked_on=licence_check._today().isoformat())
            cls.ids = {p["display_name"]: p["user_id"] for p in directory.visible(c)}
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, user_id, username, page=None, flags_value="directory", gates_value="L2",
             **state):
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
                        + [s.value for s in at.subheader])

    def test_off_there_is_nothing(self):
        # neither set, the gate alone, or the flag without L2
        for flag_value, gate_value in (("", ""), ("", "L2"), ("directory", "L0,L1,L3")):
            with self.subTest(flags=flag_value, gates=gate_value):
                at, _ = self._run(self.alice, "alice", "find-a-guide", flag_value, gate_value)
                self.assertNotIn("menu_Find a guide", self._menu(at))
                self.assertNotEqual(at.session_state["page"], "Find a guide")
                self.assertNotIn("Request an introduction", [b.label for b in at.button])
                at, _ = self._run(self.carol, "carol", "your-clients", flag_value, gate_value,
                                  two_step_ok=self.carol_ok)
                self.assertNotIn("Your directory listing", [s.value for s in at.subheader])
                self.assertNotIn("dir_p_loaded", at.session_state)

    def test_client_mode_and_advisors_never_see_it(self):
        # carol's client, dave: no Find a guide, and the address doesn't open it
        at, _ = self._run(self.dave, "dave", "find-a-guide")
        self.assertNotIn("menu_Find a guide", self._menu(at))
        self.assertNotEqual(at.session_state["page"], "Find a guide")
        # carol in dave's account (client mode), and carol on her own
        for active in (self.dave, self.carol):
            at, _ = self._run(self.carol, "carol", "find-a-guide", two_step_ok=self.carol_ok,
                              active_user_id=active)
            self.assertNotIn("menu_Find a guide", self._menu(at))
            self.assertNotEqual(at.session_state["page"], "Find a guide")

    def _dump(self):
        c = sqlite3.connect(self.db)
        try:
            return set(c.iterdump())
        finally:
            c.close()

    def test_browse_filter_and_request_writes_nothing(self):
        at, env = self._run(self.alice, "alice", "about")      # settle sign-in's own writes
        self.assertIn("menu_Find a guide", self._menu(at))
        before = self._dump()
        at, env = self._run(self.alice, "alice", "find-a-guide")
        self.assertEqual(at.session_state["page"], "Find a guide")
        text = self._text(at)
        for line in directory.ABOUT_LINES:
            self.assertIn(line, text)
        self.assertIn(directory.ORDER_LINE, text)
        # alphabetical, whatever order they were saved in
        cards = [b.key for b in at.button if (b.key or "").startswith("dir_intro_")]
        self.assertEqual(cards, [f"dir_intro_{self.ids[n]}"
                                 for n in ("Bea Okafor", "Marcus Lee", "Zed Carol Ruiz")])
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.selectbox(key="dir_f_state").set_value("CA").run()
            self.assertEqual([b.key for b in at.button if (b.key or "").startswith("dir_intro_")],
                             [f"dir_intro_{self.ids['Zed Carol Ruiz']}"])
            at.selectbox(key="dir_f_state").set_value(None).run()
            at.radio(key="dir_f_meeting").set_value("in_person").run()
            self.assertEqual([b.key for b in at.button if (b.key or "").startswith("dir_intro_")],
                             [f"dir_intro_{self.ids['Zed Carol Ruiz']}"])
            at.button(key=f"dir_intro_{self.ids['Zed Carol Ruiz']}").click().run()
            self.assertIn(directory.INTROS_SOON, [i.value for i in at.info])
            self.assertFalse(at.exception, [e.value for e in at.exception])
        after = self._dump()
        changed = {line.split('"')[1] for line in after ^ before
                   if line.startswith("INSERT INTO")}
        # (a page open refreshes the sign-in's own rows; nothing about browsing)
        self.assertLessEqual(changed, {"login_sessions", "users", "value_log"}, changed)
        self.assertEqual({x for x in after ^ before if "advisor_profiles" in x}, set())
        self.assertFalse([x for x in after - before if re.search(r"guide|directory|dir_", x)])

    def test_the_advisors_listing_on_your_clients(self):
        at, env = self._run(self.carol, "carol", "your-clients", two_step_ok=self.carol_ok)
        self.assertIn("Your directory listing", [s.value for s in at.subheader])
        self.assertIn("Shown in Find a guide", self._text(at))
        self.assertEqual(at.text_input(key="dir_p_display_name").value, "Zed Carol Ruiz")
        for word in ("views", "clicks", "impressions"):   # no counts, only the promise
            self.assertNotRegex(self._text(at), rf"\d+ {word}")
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.text_input(key="dir_p_scheduling_url").set_value("http://not-https.example.com")
            at.button(key="FormSubmitter:dir_listing_form-Save listing").click().run()
            self.assertIn("https://", " ".join(e.value for e in at.error))
            at.text_input(key="dir_p_scheduling_url").set_value("https://cal.example.com/zed")
            at.button(key="FormSubmitter:dir_listing_form-Save listing").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
        c = portfolio.connect(self.db)
        try:
            self.assertEqual(directory.get_profile(c, self.carol)["scheduling_url"],
                             "https://cal.example.com/zed")
        finally:
            c.close()

    def test_the_advisor_sets_a_one_time_review(self):
        at, env = self._run(self.carol, "carol", "your-clients", two_step_ok=self.carol_ok)
        self.assertEqual(at.radio(key="dir_p_one_time").value, "")
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            # a set price with no price: refused, nothing saved
            at.radio(key="dir_p_one_time").set_value("price")
            at.button(key="FormSubmitter:dir_listing_form-Save listing").click().run()
            self.assertIn("One-time review", " ".join(e.value for e in at.error))
            at.number_input(key="dir_p_one_time_price").set_value(300)
            at.button(key="FormSubmitter:dir_listing_form-Save listing").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
        c = portfolio.connect(self.db)
        try:
            self.assertEqual(directory.get_profile(c, self.carol)["one_time_cost"], "300")
            directory.save_profile(c, self.carol, {**directory.get_profile(c, self.carol),
                                                   "one_time_cost": ""}, listed=True)
        finally:
            c.close()

    def test_find_a_guide_shows_the_review_and_the_explainer(self):
        at, _ = self._run(self.alice, "alice", "find-a-guide")
        text = self._text(at)
        self.assertIn(r"**One-time review:** Offered - \$250, the price as the advisor states it",
                      text)
        self.assertEqual(text.count(directory.ONE_TIME_NOTE), 1)   # Bea's only
        self.assertIn(directory.FEES_TITLE, [e.label for e in at.expander])
        for _, label, words in directory.FEES_EXPLAINED:
            self.assertIn(words, text)
        for name, url in directory.OFFICIAL_SITES:
            self.assertIn(f"[{name}]({url})", text)

    def _guide_buttons(self, at):
        return [b.key for b in at.button if b.key in ("gs_guide", "plan_guide")]

    def test_the_calm_link_on_learn_and_plan(self):
        # Learn finished, a goal set: one quiet line on each, with the flag and L2 on
        for page, key in (("learn", "gs_guide"), ("plan", "plan_guide")):
            with self.subTest(page):
                at, _ = self._run(self.lena, "lena", page)
                self.assertEqual(self._guide_buttons(at), [key])
                self.assertIn(directory.GUIDE_LINE, [c.value for c in at.caption])
                # off, the gate alone, or the flag without L2: nothing
                for flag_value, gate_value in (("", ""), ("", "L2"), ("directory", "L0,L1,L3")):
                    at, _ = self._run(self.lena, "lena", page, flag_value, gate_value)
                    self.assertEqual(self._guide_buttons(at), [])
                    self.assertNotIn(directory.GUIDE_LINE, [c.value for c in at.caption])
                # someone with an advisor (client mode), and the advisor in their account
                at, _ = self._run(self.dave, "dave", page)
                self.assertEqual(self._guide_buttons(at), [])
                at, _ = self._run(self.carol, "carol", page, two_step_ok=self.carol_ok,
                                  active_user_id=self.dave)
                self.assertEqual(self._guide_buttons(at), [])
        # alice hasn't set a goal or finished Learn: no line yet
        for page in ("learn", "plan"):
            at, _ = self._run(self.alice, "alice", page)
            self.assertEqual(self._guide_buttons(at), [])

    def test_the_link_is_never_shown_to_an_admin(self):
        # an admin with Learn finished and a goal, past two-step sign-in
        for page in ("learn", "plan"):
            at, _ = self._run(self.ada, "ada", page, two_step_ok=self.ada_ok)
            self.assertEqual(at.session_state["page"], "Plan" if page == "plan" else "Get started")
            self.assertEqual(self._guide_buttons(at), [])

    def test_seeing_and_pressing_the_link_writes_nothing(self):
        # settle sign-in's own writes, and the pages' own first-visit ones (the
        # gear a goal earns, the plan's return assumption) - not the link's
        for page in ("about", "plan", "learn"):
            self._run(self.lena, "lena", page)
        before = self._dump()
        at, env = self._run(self.lena, "lena", "plan")
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.button(key="plan_guide").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(at.session_state["page"], "Find a guide")
        at, env = self._run(self.lena, "lena", "learn")
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.button(key="gs_guide").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(at.session_state["page"], "Find a guide")
        after = self._dump()
        changed = {line.split('"')[1] for line in after ^ before
                   if line.startswith("INSERT INTO")}
        # (a page open refreshes the sign-in's own rows; nothing about the link)
        self.assertLessEqual(changed, {"login_sessions", "users", "value_log"}, changed)
        self.assertFalse([x for x in after - before if re.search(r"guide|directory|dir_", x)])


if __name__ == "__main__":
    unittest.main()
