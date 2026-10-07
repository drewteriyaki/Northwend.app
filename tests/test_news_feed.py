"""Your news (flag news_feed): the selection rule, the hourly job, and where it
shows - the card on Home and the News tab in Money. No network: the job's
fetch and pause are stand-ins, and the app runs with sockets blocked.

    python -m unittest tests.test_news_feed        (from the repo root)
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
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import auth  # noqa: E402
import flags  # noqa: E402
import news  # noqa: E402
import news_feed as nf  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import watchlist  # noqa: E402

NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
PW = "pw-123456789"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def art(ticker, headline, *, hours=1, source="Reuters", url=None, now=NOW):
    """An article as news_feed.load returns it."""
    slug = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")
    return {"ticker": ticker, "headline": headline, "source": source,
            "url": url or f"https://{source.lower().replace(' ', '')}.example/{slug}",
            "published_at": _iso(now - timedelta(hours=hours))}


# --------------------------------------------------------------------------- #
# The selection
# --------------------------------------------------------------------------- #
class SelectionTests(unittest.TestCase):

    def test_press_release_wires_and_junk_are_left_out(self):
        rows = [
            art("AAPL", "Apple opens a new design studio in Austin"),
            art("AAPL", "Acme Corp announces quarterly dividend payment", source="Business Wire"),
            art("AAPL", "Acme Corp names a new chief financial officer", source="Yahoo",
                url="https://www.globenewswire.com/news-release/2026/10/07/1"),
            art("AAPL", "SHAREHOLDER ALERT: law firm reminds investors of class action deadline",
                source="Accesswire Partner"),
            art("AAPL", "Investors who lost money in Apple encouraged to contact the firm",
                source="Benzinga"),
            art("AAPL", "Apple up", source="Benzinga"),                     # too short
            art("AAPL", "Apple supplier results come in above estimates", url="ftp://x/y"),
        ]
        picked = nf.pick(rows, now=NOW, per_ticker=10)
        self.assertEqual([s["headline"] for s in picked],
                         ["Apple opens a new design studio in Austin"])
        self.assertTrue(nf.is_junk({"headline": "Fund files report with regulators today",
                                    "url": "https://www.prnewswire.com/a", "source": "x"}))
        self.assertFalse(nf.is_junk(rows[0]))

    def test_the_same_story_is_shown_once_with_its_source_count(self):
        rows = [
            art("AAPL", "Apple reports record iPhone sales in September quarter", hours=2),
            art("AAPL", "Apple reports record iPhone sales for the September quarter",
                hours=1, source="CNBC"),
            art("AAPL", "A different headline about Apple's services business", hours=3,
                source="MarketWatch", url="https://reuters.example/apple-record?utm=x"),
            art("AAPL", "Totally unrelated words describing a supply chain change", hours=4,
                url="https://reuters.example/apple-record/"),
        ]
        picked = nf.pick(rows, now=NOW, per_ticker=10)
        self.assertEqual(len(picked), 2, picked)
        first = picked[0]
        self.assertEqual(first["headline"], "Apple reports record iPhone sales for the September quarter")
        self.assertEqual(first["sources"], 2)   # Reuters and CNBC
        # the same link (query, trailing slash aside) is the same story
        self.assertEqual(picked[1]["sources"], 2)
        self.assertEqual(nf.same_link("https://www.a.com/x/?q=1#f"), nf.same_link("http://a.com/x"))

    def test_only_the_last_three_days(self):
        rows = [art("MSFT", "Microsoft story from yesterday afternoon here", hours=20),
                art("MSFT", "Microsoft story from four days ago here", hours=4 * 24),
                art("MSFT", "Microsoft story dated in the future somehow", hours=-5),
                {**art("MSFT", "Microsoft story with no date at all"), "published_at": None}]
        picked = nf.pick(rows, now=NOW)
        self.assertEqual([s["headline"] for s in picked],
                         ["Microsoft story from yesterday afternoon here"])

    def test_at_most_two_per_ticker_and_ten_in_all(self):
        rows = []
        topics = ("opens a factory in Ohio", "names a new finance chief",
                  "settles a long patent dispute", "delays its product launch event")
        for t in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"):
            for i, topic in enumerate(topics):
                rows.append(art(t, f"{t} {topic}", hours=i + 1,
                                url=f"https://x.example/{t}/{i}"))
        picked = nf.pick(rows, now=NOW)
        self.assertEqual(len(picked), nf.LIMIT)
        counts = {}
        for s in picked:
            counts[s["tickers"][0]] = counts.get(s["tickers"][0], 0) + 1
        self.assertTrue(all(n <= nf.PER_TICKER for n in counts.values()), counts)
        # newest first
        whens = [s["when"] for s in picked]
        self.assertEqual(whens, sorted(whens, reverse=True))

    def test_a_story_under_two_tickers_counts_for_each(self):
        url = "https://reuters.example/apple-and-microsoft"
        rows = [art("AAPL", "Apple and Microsoft agree on a cloud partnership", url=url),
                art("MSFT", "Apple and Microsoft agree on a cloud partnership", url=url),
                art("AAPL", "Apple opens a design studio in Austin Texas", hours=2),
                art("AAPL", "Apple names a new head of retail stores", hours=3),
                art("MSFT", "Microsoft updates its gaming subscription prices", hours=2)]
        picked = nf.pick(rows, now=NOW)
        self.assertEqual(picked[0]["tickers"], ["AAPL", "MSFT"])
        self.assertEqual(sum("AAPL" in s["tickers"] for s in picked), 2)
        self.assertEqual(len(picked), 3)
        # alike headlines about different companies are different stories
        alike = [art("AAPL", "Apple shares rise after earnings beat estimates"),
                 art("MSFT", "Microsoft shares rise after earnings beat estimates")]
        self.assertEqual(len(nf.pick(alike, now=NOW)), 2)

    def test_more_sources_move_a_story_up_a_little(self):
        rows = [art("AAPL", "Apple wins an appeal in its patent case", hours=8),
                art("AAPL", "Apple wins appeal in its patent case", hours=8, source="CNBC"),
                art("AAPL", "Apple wins an appeal in the patent case", hours=8, source="AP"),
                art("AAPL", "Apple opens a design studio in Austin Texas", hours=1),
                art("AAPL", "Apple names a new head of retail stores", hours=20)]
        picked = nf.pick(rows, now=NOW, per_ticker=10)
        # 8 hours old with 3 sources (+12 h) beats 1 hour old with one ...
        self.assertEqual(picked[0]["sources"], 3)
        self.assertEqual(picked[1]["headline"], "Apple opens a design studio in Austin Texas")
        # ... but a boost is small: two days old with three sources stays behind
        rows2 = [art("AAPL", "Apple wins an appeal in its patent case", hours=48),
                 art("AAPL", "Apple wins appeal in its patent case", hours=48, source="CNBC"),
                 art("AAPL", "Apple wins an appeal in the patent case", hours=48, source="AP"),
                 art("AAPL", "Apple opens a design studio in Austin Texas", hours=30)]
        self.assertEqual(nf.pick(rows2, now=NOW)[0]["sources"], 1)

    def test_how_long_ago_in_words(self):
        for delta, words in ((timedelta(seconds=30), "just now"),
                             (timedelta(minutes=25), "25 minutes ago"),
                             (timedelta(minutes=70), "1 hour ago"),
                             (timedelta(hours=5), "5 hours ago"),
                             (timedelta(hours=30), "yesterday"),
                             (timedelta(days=2, hours=3), "2 days ago")):
            self.assertEqual(nf.ago(NOW - delta, NOW), words)

    def test_the_rule_has_no_judgement_words(self):
        # what the feed says about itself, and the module's own rule
        import ast
        with open(os.path.join(REPO, "views", "news_feed.py"), encoding="utf-8") as fh:
            src = fh.read()
        strings = " ".join(n.value for n in ast.walk(ast.parse(src))
                           if isinstance(n, ast.Constant) and isinstance(n.value, str))
        for word in ("should", "best", "recommend", "buy", "sell", "important"):
            self.assertNotRegex(strings.lower(), rf"\b{word}\b")


# --------------------------------------------------------------------------- #
# The stored rows and the job
# --------------------------------------------------------------------------- #
class _DB(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_newsfeed_")
        self.db = os.path.join(self.dir, "n.db")
        self.c = portfolio.connect(self.db)

    def tearDown(self):
        self.c.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _store(self, ticker, n=1, *, hours=1, fetched=None):
        now = datetime.now(timezone.utc)
        for i in range(n):
            aid = abs(hash((ticker, i, hours))) % 10**9
            self.c.execute(
                "INSERT INTO news (id, ticker, headline, source, url, published_at"
                + (", fetched_at" if fetched else "") + ") VALUES (?, ?, ?, ?, ?, ?"
                + (", ?" if fetched else "") + ")",
                (aid, ticker, f"{ticker} story number {i} about the company", "Reuters",
                 f"https://reuters.example/{ticker}/{i}/{hours}",
                 _iso(now - timedelta(hours=hours)), *([fetched] if fetched else [])))
        self.c.commit()


class StoredTests(_DB):

    def test_load_reads_only_these_tickers_and_recent_ones(self):
        self._store("AAPL", 2)
        self._store("MSFT", 1)
        self._store("AAPL", 1, hours=24 * 5)       # too old
        rows = nf.load(self.c, ["aapl", "VTI"])
        self.assertEqual({r["ticker"] for r in rows}, {"AAPL"})
        self.assertEqual(len(rows), 2)
        self.assertEqual(nf.load(self.c, []), [])
        self.assertNotIn("summary", rows[0])        # never the summary

    def test_prune_deletes_only_old_stories(self):
        self._store("AAPL", 1, hours=24 * 40)
        self._store("AAPL", 1, hours=2)
        self.assertEqual(nf.prune(self.c), 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM news").fetchone()[0], 1)


class JobTests(_DB):

    def setUp(self):
        super().setUp()
        c = self.c
        self.ann = auth.create_user(c, "ann", PW)
        self.ben = auth.create_user(c, "ben", PW)
        # ann: an older snapshot with OLD, today's with AAPL and a mutual fund
        for day, syms in (("2026-09-01", ["OLD"]), ("2026-10-01", ["AAPL", "VFIAX"])):
            for s in syms:
                c.execute("INSERT INTO positions (user_id, snapshot_date, account, symbol) "
                          "VALUES (?, ?, 'Brokerage', ?)", (self.ann, day, s))
        c.commit()
        watchlist.add(c, self.ben, "MSFT")
        watchlist.add(c, self.ann, "AAPL")

    def test_held_and_watched_tickers_across_accounts(self):
        self.assertEqual(nf.tickers_to_fetch(self.c), ["AAPL", "MSFT"])
        # the one fetched longest ago comes first
        self._store("AAPL", 1, fetched="2026-10-07 09:00:00")
        self._store("MSFT", 1, fetched="2026-10-07 08:00:00")
        self.assertEqual(nf.tickers_to_fetch(self.c), ["MSFT", "AAPL"])
        self.assertFalse(nf.wanted("VFIAX"))
        self.assertTrue(nf.wanted("BRK.B"))

    def test_each_ticker_once_with_a_pause_between(self):
        calls, pauses = [], []

        def fetch(sym, token):
            calls.append((sym, token))
            return [{"id": len(calls), "headline": f"{sym} news story here", "datetime": 1}], ""

        s = nf.sync_all(self.c, "k", fetch=fetch, sleep=pauses.append, log=lambda *_: None)
        self.assertEqual(calls, [("AAPL", "k"), ("MSFT", "k")])
        self.assertEqual(pauses, [nf.DELAY])           # between calls, not before the first
        self.assertGreaterEqual(nf.DELAY, 1.0)         # at most 60 a minute, with room
        self.assertEqual((s["fetched"], s["new"], s["failed"]), (2, 2, 0))
        # stored just now: the next run doesn't ask again
        calls.clear()
        s = nf.sync_all(self.c, "k", fetch=fetch, sleep=pauses.append, log=lambda *_: None)
        self.assertEqual((calls, s["skipped"]), ([], 2))

    def test_a_cap_per_run_and_stopping_when_told_too_many(self):
        for t in ("AMZN", "GOOG", "NVDA", "TSLA"):
            watchlist.add(self.c, self.ben, t)
        calls = []

        def fetch(sym, token):
            calls.append(sym)
            return [], "HTTP 429: API limit reached"

        s = nf.sync_all(self.c, "k", max_tickers=10, fetch=fetch, sleep=lambda _: None,
                        log=lambda *_: None)
        self.assertTrue(s["stopped"])
        self.assertEqual(len(calls), nf.RATE_LIMITED_STOP)
        calls.clear()
        s = nf.sync_all(self.c, "k", max_tickers=2, fetch=lambda sym, t: (calls.append(sym)
                                                                          or ([], "")),
                        sleep=lambda _: None, log=lambda *_: None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(s["skipped"], 4)

    def test_the_command_does_nothing_while_the_flag_is_off(self):
        env = {"NORTHWEND_FLAGS": "", "FINNHUB_API_KEY": "k"}
        with unittest.mock.patch.dict(os.environ, env), \
                unittest.mock.patch.object(nf, "sync_all") as sync, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(nf.main(["--db", self.db]), 0)
        sync.assert_not_called()
        self.assertIn("off", out.getvalue())
        env["NORTHWEND_FLAGS"] = "news_feed"
        fake = {"tickers": 2, "fetched": 0, "skipped": 0, "new": 0, "failed": 2,
                "stopped": False}
        with unittest.mock.patch.dict(os.environ, env), \
                unittest.mock.patch.object(nf, "sync_all", return_value=fake) as sync, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(nf.main(["--db", self.db]), 1)   # every call failed: the admin hears
        self.assertEqual(sync.call_args.kwargs["delay"], nf.DELAY)

    def test_the_scheduled_job(self):
        with open(os.path.join(REPO, ".github", "workflows", "scheduled-sync.yml"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('- cron: "7 11-23 * * *"', text)
        job = text.split("\n  news:", 1)[1]
        self.assertIn("github.event.schedule == '7 11-23 * * *'", job)
        self.assertIn('python news_feed.py --db "$DATABASE_URL"', job)
        self.assertIn("NORTHWEND_FLAGS: ${{ secrets.NORTHWEND_FLAGS }}", job)
        self.assertIn("FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}", job)
        self.assertIn('python error_alerts.py job "Your news"', job)

    def test_the_feature_owns_the_news_page(self):
        self.assertEqual(flags.FEATURES["news_feed"],
                         {"gates": (), "view": "news_feed", "page": "News"})


# --------------------------------------------------------------------------- #
# In the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_newsapp_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            sample_data.load(c, cls.alice)       # VTI, VXUS, BND, AAPL, VOO, SCHD
            watchlist.add(c, cls.alice, "NVDA")
            cls.bob = auth.create_user(c, "bob", PW)   # watches only
            watchlist.add(c, cls.bob, "MSFT")
            now = datetime.now(timezone.utc)
            arts = {"AAPL": ["Apple opens a design studio in Austin Texas",
                             "Apple names a new head of its retail stores",
                             "Apple supplier reports a quarter of higher sales"],
                    "NVDA": ["Nvidia shows a new chip at its developer event"],
                    "MSFT": ["Microsoft updates its gaming subscription plans"],
                    "TSLA": ["Tesla story nobody here holds or watches at all"]}
            n = 0
            for t, heads in arts.items():
                for i, h in enumerate(heads):
                    n += 1
                    news.upsert_news(c, t, [{
                        "id": n, "headline": h, "source": "Reuters",
                        "summary": "SUMMARY TEXT NOT SHOWN",
                        "url": f"https://reuters.example/{t.lower()}/{i}",
                        "datetime": int((now - timedelta(hours=n)).timestamp())}])
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _run(self, uid, name, page="Dashboard", flag="news_feed"):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page,
                     "auto_backfilled": True, "income_synced": True, "fs_hide": True}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY", "ANTHROPIC_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown]
        parts += [str(e.value) for e in at.caption]
        return "\n".join(parts)

    @staticmethod
    def _stories(at):
        """The markdown lines that are headlines: a ticker badge, then a link."""
        return [m.value for m in at.markdown if ":gray-badge[" in m.value]

    def test_off_nothing_shows(self):
        at = self._run(self.alice, "alice", flag="")
        self.assertNotIn("News on what you own", self._text(at))
        self.assertEqual(self._stories(at), [])
        at = self._run(self.alice, "alice", page="Income", flag="")
        self.assertEqual([b.key for b in at.button if (b.key or "").startswith("money_")],
                         ["money_Income", "money_Activity", "money_Watchlist"])
        # an old link to the News tab opens the first page instead
        at = self._run(self.alice, "alice", page="News", flag="")
        self.assertNotEqual(at.session_state["page"], "News")

    def test_home_card_shows_a_few_headlines_and_no_figures(self):
        at = self._run(self.alice, "alice")
        text = self._text(at)
        self.assertIn("News on what you own", text)
        self.assertIn("Headlines from news sources about what you hold. Northwend doesn't "
                      "write them or say what to do about them.", text)
        stories = self._stories(at)
        self.assertEqual(len(stories), 3, stories)   # AAPL's two + NVDA's one
        joined = "\n".join(stories)
        self.assertIn(":gray-badge[AAPL]", joined)
        self.assertIn(":gray-badge[NVDA]", joined)            # watched counts too
        self.assertNotIn("Tesla", joined)                     # not theirs
        self.assertNotIn("supplier reports", joined)          # AAPL's third: 2 per ticker
        self.assertNotIn("SUMMARY", text)
        for line in stories:
            # a markdown link to the source (Streamlit opens it in a new tab)
            self.assertRegex(line, r"\]\(https://reuters\.example/[a-z]+/\d\)$")
            self.assertNotRegex(line, r"[$%]|\d+\.\d")        # no figures with a headline
        captions = [str(c.value) for c in at.caption if "Reuters ·" in str(c.value)]
        self.assertEqual(len(captions), 3)
        for c in captions:
            self.assertRegex(c, r"^Reuters · (\d+ (minutes|hours?) ago|1 hour ago)$")
        self.assertIn("news_all", [b.key for b in at.button])

    def test_news_tab_in_money(self):
        at = self._run(self.alice, "alice", page="News")
        self.assertEqual([b.key for b in at.button if (b.key or "").startswith("money_")],
                         ["money_Income", "money_Activity", "money_Watchlist", "money_News"])
        self.assertEqual(at.query_params["page"], "news")
        self.assertEqual(len(self._stories(at)), 3)
        self.assertIn("Company press releases are left out.", self._text(at))

    def test_news_for_someone_who_only_watches(self):
        at = self._run(self.bob, "bob", page="News")
        stories = self._stories(at)
        self.assertEqual(len(stories), 1)
        self.assertIn("Microsoft updates", stories[0])


if __name__ == "__main__":
    unittest.main()
