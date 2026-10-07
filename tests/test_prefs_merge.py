"""Saving settings from a session that read them a while ago (prefs.merge,
dashboard._write_prefs): only what that session changed is written, so a
client's other tab, their phone or their advisor never undoes the rest - a
client's Trail Forks, drills or walk log, or the advisor's drift band."""

import contextlib
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from tests import offline as offline_net  # noqa: E402

import prefs  # noqa: E402


class MergeTests(unittest.TestCase):
    def test_keeps_what_was_saved_elsewhere(self):
        base = {"columns": ["a"], "drift_threshold": 5}
        mine = {"columns": ["a", "b"], "drift_threshold": 5}
        saved = {"columns": ["a"], "drift_threshold": 7, "trail_forks": {"move": []}}
        self.assertEqual(prefs.merge(base, mine, saved),
                         {"columns": ["a", "b"], "drift_threshold": 7,
                          "trail_forks": {"move": []}})

    def test_a_removal_and_a_new_key(self):
        base = {"lost_found": {"x": 1}, "keep": 1}
        mine = {"keep": 1, "new": True}
        saved = {"lost_found": {"x": 1}, "keep": 2, "other": 3}
        self.assertEqual(prefs.merge(base, mine, saved), {"keep": 2, "new": True, "other": 3})

    def test_nothing_changed_writes_nothing_over(self):
        saved = {"a": 9}
        self.assertEqual(prefs.merge({"a": 1}, {"a": 1}, saved), saved)


class StaleSessionTests(unittest.TestCase):
    """A session that read the settings earlier saves one thing: what another
    session saved since stays."""

    @classmethod
    def setUpClass(cls):
        import auth
        import portfolio
        import sample_data

        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == HERE}
        cls.dir = tempfile.mkdtemp(prefix="pt_prefs_merge_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.dana = auth.create_user(c, "dana", "pw-123456789")
            sample_data.load(c, cls.dana)
            prefs.save(c, cls.dana, {"first_steps": {"done": True}})
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _run(self, uid, name, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Get started",
                     "gs_at": "basics", "fs_hide": True, "auto_backfilled": True,
                     **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY", "ANTHROPIC_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("settings.load_env", lambda *a, **k: {}), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _db(self):
        import portfolio
        return portfolio.connect(self.db)

    def test_a_save_from_an_older_session_keeps_what_was_saved_since(self):
        import recap
        with self._run(self.dana, "dana") as at:
            # meanwhile, on her phone (or her advisor, in her account)
            c = self._db()
            try:
                p = prefs.load(c, self.dana)
                p["trail_forks"] = {"move": ["gather"]}
                p["drift_threshold"] = 9.0
                prefs.save(c, self.dana, p)
            finally:
                c.close()
            # this tab, which read her settings before that, notes a Learn read
            at.button(key="basics_funds").click().run()
        c = self._db()
        try:
            saved = prefs.load(c, self.dana)
        finally:
            c.close()
        self.assertIn("basics:funds", saved[recap.LEARN_READS])
        self.assertEqual(saved["trail_forks"], {"move": ["gather"]})
        self.assertEqual(saved["drift_threshold"], 9.0)
        self.assertEqual(saved["first_steps"], {"done": True})


if __name__ == "__main__":
    unittest.main()
