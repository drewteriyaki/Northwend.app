"""Paid advisor seats (billing.py, views/billing.py; direction item 10, flag
`billing` + gate L1a), and the L1 split in flags.py:
- gates: L1a / L1b, the old "L1" meaning both, nothing like L4 getting in;
  which features need which;
- flag off: nothing read, written or shown - every seat a free beta seat;
- checkout: one seat, quantity 1, the login's id, the founding or standard
  price, the session kept to check; Stripe's form encoding and errors;
- the check on return: only a complete session naming this login changes
  the seat; reconciliation updates every known subscription;
- founding places numbered once, never reused, lost on a lapse;
- lapse: add and send closed after the grace days, reading and exports open;
- Admin counts only; a live seat stops account deletion;
- no per-client or usage billing anywhere in billing.py;
- the settings, the schema files, the export, the nightly job;
- in the app: flag off unchanged; on, Your seat on Account and one plain
  line in place of add and send while lapsed.

Stripe is never called: billing._stripe (or urllib's urlopen) is replaced.

    python -m unittest tests.test_billing        (from the repo root)
"""

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import admin  # noqa: E402
import auth  # noqa: E402
import billing  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
STRIPE_ENV = {"STRIPE_SECRET_KEY": "rk_test_unused", "STRIPE_PRICE_MONTHLY": "price_found_m",
              "STRIPE_PRICE_YEARLY": "price_found_y"}
SETTING_NAMES = ("NORTHWEND_FLAGS", "NORTHWEND_GATES", "STRIPE_SECRET_KEY",
                 "STRIPE_PRICE_MONTHLY", "STRIPE_PRICE_YEARLY", "STRIPE_PRICE_STANDARD_MONTHLY",
                 "STRIPE_PRICE_STANDARD_YEARLY", "NORTHWEND_FOUNDING_SEATS",
                 "NORTHWEND_SEAT_PRICES", "NORTHWEND_STANDARD_SEAT_PRICES",
                 "NORTHWEND_SEAT_GRACE_DAYS")


@contextlib.contextmanager
def _settings(**values):
    """Only these settings (none from the real environment, secrets or .env)."""
    env = {k: v for k, v in os.environ.items() if k not in SETTING_NAMES}
    env.update(values)
    with unittest.mock.patch.dict(os.environ, env, clear=True), \
            unittest.mock.patch("flags._secret", lambda name: None), \
            unittest.mock.patch("settings.load_env", lambda *a, **k: {}):
        yield


def _on(**more):
    """Billing on (flag + L1a), test-mode Stripe settings."""
    return _settings(NORTHWEND_FLAGS="billing", NORTHWEND_GATES="L1a", **STRIPE_ENV, **more)


def _sub(sid="sub_1", status="active", *, user=None, interval="month", start=1790000000,
         period_end=1793000000, customer="cus_1", **more):
    sub = {"id": sid, "object": "subscription", "status": status, "customer": customer,
           "start_date": start,
           "items": {"data": [{"price": {"id": "price_x", "recurring": {"interval": interval}},
                               "current_period_end": period_end}]}, **more}
    if user is not None:
        sub["metadata"] = {"northwend_user": str(user)}
    return sub


class FakeStripe:
    """Stands in for billing._stripe: records each call, answers from `replies`
    ({(method, path): reply or exception}) or a default."""

    def __init__(self, replies=None):
        self.calls = []
        self.replies = dict(replies or {})

    def __call__(self, method, path, params=None, *, idempotency_key=None):
        self.calls.append({"method": method, "path": path, "params": params or {},
                           "key": idempotency_key})
        reply = self.replies.get((method, path))
        if isinstance(reply, Exception):
            raise reply
        if reply is not None:
            return reply
        if (method, path) == ("POST", "checkout/sessions"):
            return {"id": f"cs_test_{len(self.calls)}", "url": "https://checkout.stripe.com/c/x"}
        if (method, path) == ("POST", "billing_portal/sessions"):
            return {"id": "bps_1", "url": "https://billing.stripe.com/p/x"}
        raise AssertionError(f"unexpected Stripe call {method} {path}")


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_billing_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, "b.db")
        self.c = portfolio.connect(self.db)
        self.addCleanup(self.c.close)
        self.ids = []
        for name in ("carol", "omar", "pat", "quinn"):
            uid = auth.create_user(self.c, name, PW)
            auth.set_advisor(self.c, name, True)
            self.ids.append(uid)
        self.carol, self.omar, self.pat, self.quinn = self.ids

    def stripe(self, replies=None):
        fake = FakeStripe(replies)
        patcher = unittest.mock.patch.object(billing, "_stripe", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def seat(self, uid):
        return billing.seat(self.c, uid)


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #
class GateTests(unittest.TestCase):

    def test_l1_is_split_and_the_old_name_means_both(self):
        self.assertEqual(flags.GATES, ("L0", "L1a", "L1b", "L2", "L3"))
        with _settings(NORTHWEND_GATES="L0,L1"):     # the live copy's old spelling
            self.assertEqual(flags.gates_on(), {"L0", "L1a", "L1b"})
            self.assertTrue(flags.gate("L1a") and flags.gate("L1b") and flags.gate("L1"))
        with _settings(NORTHWEND_GATES="l1a"):        # any case
            self.assertEqual(flags.gates_on(), {"L1a"})
            self.assertTrue(flags.gate("L1A"))
            self.assertFalse(flags.gate("L1b"))
            self.assertFalse(flags.gate("L1"))       # the old name needs both halves
        with _settings(NORTHWEND_GATES="L1b L2"):
            self.assertEqual(flags.gates_on(), {"L1b", "L2"})
        with _settings(NORTHWEND_GATES="L4,L4a,L1c,L1ab"):
            self.assertEqual(flags.gates_on(), set())
            self.assertFalse(flags.gate("L4"))
            self.assertFalse(flags.gate("L4a"))
        with _settings(NORTHWEND_GATES="L1"):
            self.assertEqual(set(flags.state()["gates"]), set(flags.GATES))
            self.assertTrue(flags.state()["gates"]["L1a"])

    def test_which_feature_needs_which_gate(self):
        self.assertEqual(flags.FEATURES["billing"]["gates"], ("L1a",))
        self.assertEqual(flags.FEATURES["advisor_drafts"]["gates"], ("L1a",))
        self.assertEqual(flags.FEATURES["directory"]["gates"], ("L1b", "L2"))
        self.assertEqual(flags.FEATURES["intros"]["gates"], ("L1b", "L2"))
        self.assertEqual(flags.FEATURES["client_owned_book"]["gates"], ("L2",))
        self.assertEqual(flags.GATE_CHECKS.keys() & {"L1", "L1b"}, set())
        self.assertIn("L1a", flags.GATE_CHECKS)
        # nothing in FEATURES or GATE_CHECKS names the old L1 or anything like L4
        for name, f in flags.FEATURES.items():
            self.assertTrue(set(f["gates"]) <= set(flags.GATES), name)

    def test_billing_needs_its_flag_and_l1a(self):
        for flag_value, gates, on in (("", "", False), ("billing", "", False),
                                      ("", "L1a", False), ("billing", "L1b,L2", False),
                                      ("billing", "L1a", True), ("billing", "L1", True)):
            with self.subTest(flags=flag_value, gates=gates), \
                    _settings(NORTHWEND_FLAGS=flag_value, NORTHWEND_GATES=gates):
                self.assertEqual(billing.on(), on)

    def test_the_live_copys_settings_dont_change(self):
        # live today: NORTHWEND_GATES = "L0" - nothing new turns on or off
        with _settings(NORTHWEND_GATES="L0",
                       NORTHWEND_FLAGS="walk,advisor_drafts,directory,billing"):
            self.assertTrue(flags.on("walk"))
            for name in ("advisor_drafts", "directory", "billing"):
                self.assertFalse(flags.on(name), name)
        # staging's "everything on" with the old spelling: as before, plus billing
        with _settings(NORTHWEND_GATES="L0,L1,L2,L3",
                       NORTHWEND_FLAGS="advisor_drafts,directory,intros,billing"):
            for name in ("advisor_drafts", "directory", "intros", "billing"):
                self.assertTrue(flags.on(name), name)

    def test_the_agreement_label_follows_l1a(self):
        import advisor_agreement
        with _settings(NORTHWEND_GATES="L1a"):
            self.assertEqual(advisor_agreement.label(), "")
        with _settings(NORTHWEND_GATES="L1b,L2"):
            self.assertEqual(advisor_agreement.label(), advisor_agreement.BETA_LABEL)


# --------------------------------------------------------------------------- #
# flag off: as today
# --------------------------------------------------------------------------- #
class FlagOffTests(_DB):

    def test_nothing_is_read_or_written(self):
        fake = self.stripe()
        with _settings(NORTHWEND_GATES="L1a", **STRIPE_ENV):   # gate on, flag off
            st = billing.state(self.c, self.carol, now=NOW)
            self.assertTrue(st["open"])
            self.assertFalse(st["billing"])
            self.assertTrue(billing.can_write(self.c, self.carol, now=NOW + timedelta(days=999)))
        self.assertIsNone(self.seat(self.carol))
        self.assertEqual(fake.calls, [])


# --------------------------------------------------------------------------- #
# checkout and Stripe's form
# --------------------------------------------------------------------------- #
class CheckoutTests(_DB):

    def test_a_checkout_is_one_flat_seat_for_this_login(self):
        fake = self.stripe()
        with _on():
            url = billing.start_checkout(self.c, self.carol, "monthly",
                                         "https://go.northwend.app/?page=clients", now=NOW)
        self.assertEqual(url, "https://checkout.stripe.com/c/x")
        (call,) = fake.calls
        p = call["params"]
        self.assertEqual((call["method"], call["path"]), ("POST", "checkout/sessions"))
        self.assertEqual(p["mode"], "subscription")
        self.assertEqual(p["line_items"], [{"price": "price_found_m", "quantity": 1}])
        self.assertEqual(p["client_reference_id"], str(self.carol))
        self.assertEqual(p["subscription_data"]["metadata"]["northwend_user"], str(self.carol))
        self.assertEqual(p["success_url"], "https://go.northwend.app/?page=account&billing=done")
        self.assertEqual(p["cancel_url"], "https://go.northwend.app/?page=account&billing=cancel")
        self.assertNotIn("customer_email", p)            # Stripe's page asks; we send none
        self.assertTrue(call["key"].startswith(f"nw-seat-{self.carol}-"))
        self.assertEqual(self.seat(self.carol)["checkout_session"], "cs_test_1")
        self.assertEqual(self.seat(self.carol)["status"], "none")   # nothing until checked

    def test_yearly_and_the_standard_price_once_places_are_gone(self):
        fake = self.stripe()
        with _on(STRIPE_PRICE_STANDARD_MONTHLY="price_std_m", STRIPE_PRICE_STANDARD_YEARLY="price_std_y",
                 NORTHWEND_FOUNDING_SEATS="1"):
            billing.start_checkout(self.c, self.carol, "yearly", "https://x/", now=NOW)
            billing.apply(self.c, self.omar, _sub(user=self.omar), now=NOW)   # takes place 1
            billing.start_checkout(self.c, self.pat, "yearly", "https://x/", now=NOW)
            billing.start_checkout(self.c, self.quinn, "monthly", "https://x/", now=NOW)
            with self.assertRaises(ValueError):
                billing.start_checkout(self.c, self.pat, "weekly", "https://x/", now=NOW)
        prices = [c["params"]["line_items"][0]["price"] for c in fake.calls]
        self.assertEqual(prices, ["price_found_y", "price_std_y", "price_std_m"])

    def test_a_live_seat_isnt_sold_twice_and_unset_stripe_is_said(self):
        self.stripe()
        with _on():
            billing.apply(self.c, self.carol, _sub(user=self.carol), now=NOW)
            with self.assertRaises(ValueError):
                billing.start_checkout(self.c, self.carol, "monthly", "https://x/", now=NOW)
        with _settings(NORTHWEND_FLAGS="billing", NORTHWEND_GATES="L1a"):   # no key, no prices
            self.assertFalse(billing.configured())
            with self.assertRaises(billing.BillingError):
                billing.start_checkout(self.c, self.omar, "monthly", "https://x/", now=NOW)

    def test_the_portal_is_the_logins_own_customer(self):
        fake = self.stripe()
        with _on():
            with self.assertRaises(ValueError):
                billing.portal_url(self.c, self.carol, "https://go.northwend.app/")
            billing.apply(self.c, self.carol, _sub(customer="cus_carol", user=self.carol), now=NOW)
            url = billing.portal_url(self.c, self.carol, "https://go.northwend.app/?x=1")
        self.assertEqual(url, "https://billing.stripe.com/p/x")
        self.assertEqual(fake.calls[-1]["params"],
                         {"customer": "cus_carol",
                          "return_url": "https://go.northwend.app/?page=account"})

    def test_stripes_form_encoding(self):
        pairs = billing._encode({"mode": "subscription", "line_items": [{"price": "p", "quantity": 1}],
                                 "metadata": {"a": "1"}, "expand": ["subscription"],
                                 "skip": None, "flag": True})
        self.assertEqual(pairs, [("mode", "subscription"), ("line_items[0][price]", "p"),
                                 ("line_items[0][quantity]", "1"), ("metadata[a]", "1"),
                                 ("expand[0]", "subscription"), ("flag", "true")])

    def test_one_https_call_and_calm_errors(self):
        seen = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(req, timeout=None):
            seen.update(url=req.full_url, method=req.get_method(), data=req.data,
                        auth=req.get_header("Authorization"),
                        idem=req.get_header("Idempotency-key"), timeout=timeout)
            return Resp(json.dumps({"id": "cs_1"}).encode())
        with _settings(STRIPE_SECRET_KEY="rk_test_secretvalue"), \
                unittest.mock.patch("urllib.request.urlopen", fake_open):
            out = billing._stripe("POST", "checkout/sessions", {"mode": "subscription"},
                                  idempotency_key="k1")
            self.assertEqual(out, {"id": "cs_1"})
            self.assertEqual(seen["url"], "https://api.stripe.com/v1/checkout/sessions")
            self.assertEqual((seen["method"], seen["data"]), ("POST", b"mode=subscription"))
            self.assertEqual(seen["auth"], "Bearer rk_test_secretvalue")
            self.assertEqual(seen["idem"], "k1")
            billing._stripe("GET", "subscriptions/sub_1", {"expand": ["customer"]})
            self.assertEqual(seen["url"], "https://api.stripe.com/v1/subscriptions/sub_1?"
                                          + urllib.parse.urlencode({"expand[0]": "customer"}))
            self.assertIsNone(seen["data"])

            def refused(req, timeout=None):
                raise urllib.error.HTTPError(req.full_url, 401, "no", {},
                                             io.BytesIO(b'{"error": {"message": "Invalid key"}}'))
            with unittest.mock.patch("urllib.request.urlopen", refused):
                with self.assertRaises(billing.BillingError) as caught:
                    billing._stripe("GET", "subscriptions/sub_1")
            self.assertIn("401", str(caught.exception))
            self.assertNotIn("secretvalue", str(caught.exception))

            def down(req, timeout=None):
                raise urllib.error.URLError("offline")
            with unittest.mock.patch("urllib.request.urlopen", down):
                with self.assertRaises(billing.BillingError):
                    billing._stripe("GET", "subscriptions/sub_1")
        with _settings():
            with self.assertRaises(billing.BillingError):
                billing._stripe("GET", "subscriptions/sub_1")


# --------------------------------------------------------------------------- #
# the check on return, and the nightly reconciliation
# --------------------------------------------------------------------------- #
class VerifyTests(_DB):

    def _checkout(self, uid, fake):
        with _on():
            billing.start_checkout(self.c, uid, "monthly", "https://x/", now=NOW)
        return self.seat(uid)["checkout_session"]

    def test_a_complete_session_for_this_login_starts_the_seat(self):
        fake = self.stripe()
        cs = self._checkout(self.carol, fake)
        fake.replies[("GET", f"checkout/sessions/{cs}")] = {
            "id": cs, "mode": "subscription", "status": "complete",
            "client_reference_id": str(self.carol), "customer": "cus_c",
            "subscription": _sub("sub_c", user=self.carol, customer=None)}
        with _on():
            self.assertEqual(billing.verify_checkout(self.c, self.carol, now=NOW), "done")
            row = self.seat(self.carol)
            self.assertEqual((row["status"], row["plan"], row["stripe_subscription"],
                              row["stripe_customer"], row["founding"], row["founding_no"]),
                             ("active", "monthly", "sub_c", "cus_c", 1, 1))
            self.assertIsNone(row["checkout_session"])
            self.assertTrue(row["current_period_end"].startswith("2026-10-26"))
            self.assertEqual(billing.verify_checkout(self.c, self.carol, now=NOW), "none")
            self.assertTrue(billing.state(self.c, self.carol, now=NOW)["live"])

    def test_a_session_for_someone_else_changes_nothing(self):
        fake = self.stripe()
        cs = self._checkout(self.carol, fake)
        fake.replies[("GET", f"checkout/sessions/{cs}")] = {
            "id": cs, "mode": "subscription", "status": "complete",
            "client_reference_id": str(self.omar), "subscription": _sub(user=self.omar)}
        with _on():
            self.assertEqual(billing.verify_checkout(self.c, self.carol, now=NOW), "mismatch")
        row = self.seat(self.carol)
        self.assertEqual((row["status"], row["stripe_subscription"]), ("none", None))
        self.assertIsNone(self.seat(self.omar))
        # a subscription whose metadata names another login: refused too
        cs = self._checkout(self.carol, fake)
        fake.replies[("GET", f"checkout/sessions/{cs}")] = {
            "id": cs, "mode": "subscription", "status": "complete",
            "client_reference_id": str(self.carol), "subscription": _sub(user=self.omar)}
        with _on():
            self.assertEqual(billing.verify_checkout(self.c, self.carol, now=NOW), "mismatch")
        self.assertEqual(self.seat(self.carol)["status"], "none")

    def test_not_paid_yet_and_expired(self):
        fake = self.stripe()
        cs = self._checkout(self.carol, fake)
        fake.replies[("GET", f"checkout/sessions/{cs}")] = {
            "id": cs, "mode": "subscription", "status": "open",
            "client_reference_id": str(self.carol), "subscription": None}
        with _on():
            self.assertEqual(billing.verify_checkout(self.c, self.carol, now=NOW), "open")
            self.assertEqual(self.seat(self.carol)["checkout_session"], cs)   # still waiting
            fake.replies[("GET", f"checkout/sessions/{cs}")]["status"] = "expired"
            self.assertEqual(billing.verify_checkout(self.c, self.carol, now=NOW), "expired")
        self.assertIsNone(self.seat(self.carol)["checkout_session"])
        self.assertEqual(self.seat(self.carol)["status"], "none")

    def test_the_session_id_is_fetched_with_the_subscription(self):
        fake = self.stripe()
        cs = self._checkout(self.carol, fake)
        fake.replies[("GET", f"checkout/sessions/{cs}")] = {
            "id": cs, "mode": "subscription", "status": "complete",
            "client_reference_id": str(self.carol), "customer": "cus_c",
            "subscription": "sub_c"}
        fake.replies[("GET", "subscriptions/sub_c")] = _sub("sub_c", user=self.carol,
                                                            interval="year")
        with _on():
            self.assertEqual(billing.verify_checkout(self.c, self.carol, now=NOW), "done")
        self.assertEqual(fake.calls[1]["params"], {"expand": ["subscription"]})
        self.assertEqual(self.seat(self.carol)["plan"], "yearly")


class SyncTests(_DB):

    def test_reconciliation_updates_every_known_subscription(self):
        fake = self.stripe()
        with _on():
            billing.apply(self.c, self.carol, _sub("sub_c", user=self.carol), now=NOW)
            billing.apply(self.c, self.omar, _sub("sub_o", user=self.omar), now=NOW)
            billing.ensure(self.c, self.pat, now=NOW)           # never subscribed: not asked
            fake.replies[("GET", "subscriptions/sub_c")] = _sub(
                "sub_c", "canceled", user=self.carol, ended_at=int(NOW.timestamp()))
            fake.replies[("GET", "subscriptions/sub_o")] = _sub("sub_o", "past_due",
                                                                user=self.omar)
            later = NOW + timedelta(days=1)
            res = billing.sync_all(self.c, now=later, pause=0)
        self.assertEqual(res, {"checked": 2, "changed": 2, "failed": 0, "mismatched": 0,
                               "manual_ended": 0})
        self.assertEqual([c["path"] for c in fake.calls],
                         ["subscriptions/sub_c", "subscriptions/sub_o"])
        carol, omar = self.seat(self.carol), self.seat(self.omar)
        self.assertEqual((carol["status"], carol["founding"]), ("canceled", 0))
        self.assertEqual(carol["founding_no"], 1)             # the place it had, kept as history
        self.assertEqual((omar["status"], omar["founding"]), ("past_due", 1))
        self.assertTrue(carol["last_checked"].startswith("2026-10-11"))

    def test_a_failure_or_a_stranger_fails_the_run(self):
        fake = self.stripe()
        with _on():
            billing.apply(self.c, self.carol, _sub("sub_c", user=self.carol), now=NOW)
            billing.apply(self.c, self.omar, _sub("sub_o", user=self.omar), now=NOW)
            fake.replies[("GET", "subscriptions/sub_c")] = billing.BillingError("down")
            fake.replies[("GET", "subscriptions/sub_o")] = _sub("sub_o", "canceled",
                                                                user=self.carol)
            res = billing.sync_all(self.c, now=NOW, pause=0)
        self.assertEqual((res["failed"], res["mismatched"]), (1, 1))
        self.assertEqual(self.seat(self.omar)["status"], "active")   # not taken from a stranger
        with _on(), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(billing.main(["--sync", "--db", self.db]), 1)
        self.assertIn("couldn't be read", out.getvalue())
        self.assertNotIn("sub_", out.getvalue())                       # counts only

    def test_the_command_line(self):
        fake = self.stripe()
        with _settings(), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(billing.main(["--sync", "--db", self.db]), 0)   # no key: skipped
        self.assertIn("Skipped", out.getvalue())
        with _on(), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(billing.main(["--sync", "--db", self.db]), 0)
        self.assertIn("Seats: 0 checked", out.getvalue())
        self.assertEqual(fake.calls, [])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            billing.main(["--db", self.db])                                 # --sync is asked for

    def test_a_waiting_checkout_is_checked_at_night_too(self):
        fake = self.stripe()
        with _on():
            billing.start_checkout(self.c, self.carol, "monthly", "https://x/", now=NOW)
            cs = self.seat(self.carol)["checkout_session"]
            fake.replies[("GET", f"checkout/sessions/{cs}")] = {
                "id": cs, "mode": "subscription", "status": "complete",
                "client_reference_id": str(self.carol), "subscription": _sub(user=self.carol)}
            res = billing.sync_all(self.c, now=NOW, pause=0)
        self.assertEqual(res["checked"], 1)
        self.assertEqual(self.seat(self.carol)["status"], "active")


# --------------------------------------------------------------------------- #
# founding places
# --------------------------------------------------------------------------- #
class FoundingTests(_DB):

    def test_numbered_once_up_to_the_limit(self):
        with _on(NORTHWEND_FOUNDING_SEATS="2"):
            for uid in (self.carol, self.omar, self.pat):
                billing.apply(self.c, uid, _sub(f"sub_{uid}", user=uid), now=NOW)
            got = [(self.seat(u)["founding"], self.seat(u)["founding_no"])
                   for u in (self.carol, self.omar, self.pat)]
            self.assertEqual(got, [(1, 1), (1, 2), (0, None)])
            self.assertEqual(billing.founding_used(self.c), 2)
            # the same subscription read again: no new place
            billing.apply(self.c, self.carol, _sub(f"sub_{self.carol}", user=self.carol), now=NOW)
            self.assertEqual(billing.founding_used(self.c), 2)
            self.assertFalse(billing.offers_founding(self.c, self.quinn))

    def test_a_lapse_loses_it_and_the_place_isnt_reused(self):
        self.stripe()
        with _on(NORTHWEND_FOUNDING_SEATS="2", STRIPE_PRICE_STANDARD_MONTHLY="price_std_m"):
            billing.apply(self.c, self.carol, _sub("sub_c", user=self.carol), now=NOW)
            # past_due keeps it: no break yet
            billing.apply(self.c, self.carol, _sub("sub_c", "past_due", user=self.carol), now=NOW)
            self.assertEqual(self.seat(self.carol)["founding"], 1)
            # ended: gone
            billing.apply(self.c, self.carol, _sub("sub_c", "canceled", user=self.carol,
                                                   ended_at=int(NOW.timestamp())), now=NOW)
            self.assertEqual(self.seat(self.carol)["founding"], 0)
            # starting again: the standard price, and no founding place
            self.assertFalse(billing.offers_founding(self.c, self.carol))
            billing.start_checkout(self.c, self.carol, "monthly", "https://x/", now=NOW)
            self.assertEqual(billing._stripe.calls[-1]["params"]["line_items"][0]["price"],
                             "price_std_m")
            billing.apply(self.c, self.carol, _sub("sub_c2", user=self.carol), now=NOW)
            self.assertEqual((self.seat(self.carol)["founding"],
                              billing.founding_used(self.c)), (0, 1))
            # the place carol lost isn't handed out again: omar gets place 2
            billing.apply(self.c, self.omar, _sub("sub_o", user=self.omar), now=NOW)
            self.assertEqual(self.seat(self.omar)["founding_no"], 2)
            # and a deleted account doesn't give its place back
            billing.apply(self.c, self.omar, _sub("sub_o", "canceled", user=self.omar), now=NOW)
            self.assertTrue(admin.delete_account(self.c, self.omar, by=-1)["ok"])
            self.assertEqual(billing.founding_used(self.c), 2)
            self.assertFalse(billing.offers_founding(self.c, self.pat))

    def test_a_first_payment_still_being_made_starts_nothing(self):
        with _on():
            billing.apply(self.c, self.carol, _sub("sub_c", "incomplete", user=self.carol),
                          now=NOW)
            row = self.seat(self.carol)
            self.assertEqual((row["status"], row["started_at"], row["founding"]),
                             ("incomplete", None, 0))
            self.assertEqual(billing.founding_used(self.c), 0)


# --------------------------------------------------------------------------- #
# lapse: add and send close; reading and exports never do
# --------------------------------------------------------------------------- #
class LapseTests(_DB):

    def test_new_and_beta_advisors_get_the_grace_days(self):
        with _on(NORTHWEND_SEAT_GRACE_DAYS="14"):
            self.assertTrue(billing.can_write(self.c, self.carol, now=NOW))   # first seen now
            self.assertTrue(billing.can_write(self.c, self.carol, now=NOW + timedelta(days=13)))
            self.assertFalse(billing.can_write(self.c, self.carol,
                                               now=NOW + timedelta(days=15)))
            st = billing.state(self.c, self.carol, now=NOW + timedelta(days=15))
            self.assertEqual((st["live"], st["status"], st["open"]), (False, "none", False))

    def test_live_past_due_and_an_ended_seat(self):
        with _on(NORTHWEND_SEAT_GRACE_DAYS="14"):
            billing.apply(self.c, self.carol, _sub("sub_c", user=self.carol), now=NOW)
            far = NOW + timedelta(days=400)
            self.assertTrue(billing.can_write(self.c, self.carol, now=far))   # live: no grace needed
            billing.apply(self.c, self.carol, _sub("sub_c", "past_due", user=self.carol), now=NOW)
            self.assertTrue(billing.can_write(self.c, self.carol, now=far))
            ended = NOW + timedelta(days=30)
            billing.apply(self.c, self.carol, _sub("sub_c", "unpaid", user=self.carol,
                                                   ended_at=int(ended.timestamp())),
                          now=ended + timedelta(days=1))
            self.assertTrue(billing.can_write(self.c, self.carol, now=ended + timedelta(days=13)))
            self.assertFalse(billing.can_write(self.c, self.carol,
                                               now=ended + timedelta(days=15)))

    def test_reading_and_exports_never_ask(self):
        # the read and export paths don't call billing at all
        for path in ("export.py", os.path.join("views", "clients.py")):
            with open(os.path.join(REPO, path), encoding="utf-8") as fh:
                src = fh.read()
            for fn in ("_prepare_client_record", "_prepare_all_records", "_prepare_former_record"):
                body = re.search(rf"def {fn}\(.*?(?=\ndef )", src, re.S)
                if body:
                    self.assertNotIn("_seat_ok", body.group(0), fn)
                    self.assertNotIn("SEAT_OPEN", body.group(0), fn)
        with open(os.path.join(REPO, "export.py"), encoding="utf-8") as fh:
            self.assertNotIn("import billing", fh.read())

    def test_every_add_and_send_asks(self):
        """Each add or send callback checks the seat again (_seat_ok), so a
        page left open can't send after a seat ends."""
        want = {"dashboard.py": ["_add_client"],
                os.path.join("views", "clients.py"): ["_add_clients_from_file", "_send_message"],
                os.path.join("views", "proposals.py"): ["_prop_save", "_prop_act"],
                os.path.join("views", "reports.py"): ["_rep_send", "_rep_send_all"],
                os.path.join("views", "meeting.py"): ["_prep_draft"],
                os.path.join("views", "drafts.py"): ["_draft_write"]}
        for path, fns in want.items():
            with open(os.path.join(REPO, path), encoding="utf-8") as fh:
                src = fh.read()
            for fn in fns:
                body = re.search(rf"\ndef {fn}\(.*?(?=\n(?:def |# ----|@))", src, re.S)
                self.assertIsNotNone(body, fn)
                self.assertIn("_seat_ok()", body.group(0), f"{path}: {fn}")


# --------------------------------------------------------------------------- #
# Admin, deletion, the export, the schema
# --------------------------------------------------------------------------- #
class RecordsTests(_DB):

    def test_admin_counts_only(self):
        with _on(NORTHWEND_FOUNDING_SEATS="3", NORTHWEND_SEAT_GRACE_DAYS="14"):
            billing.apply(self.c, self.carol, _sub("sub_c", user=self.carol), now=NOW)
            billing.apply(self.c, self.omar, _sub("sub_o", user=self.omar), now=NOW)
            billing.apply(self.c, self.omar, _sub("sub_o", "canceled", user=self.omar,
                                                  ended_at=int(NOW.timestamp())), now=NOW)
            billing.ensure(self.c, self.pat, now=NOW)
            n = billing.counts(self.c, now=NOW + timedelta(days=20))
        self.assertEqual(n, {"live": 1, "founding_kept": 1, "lapsed": 1, "not_started": 1,
                             "founding_used": 2, "founding_total": 3})

    def test_a_live_seat_stops_deletion(self):
        with _on():
            billing.apply(self.c, self.carol, _sub("sub_c", user=self.carol), now=NOW)
        res = admin.delete_account(self.c, self.carol, by=-1)
        self.assertFalse(res["ok"])
        self.assertIn("paid seat", res["error"])
        self.assertIsNotNone(auth.get_username(self.c, self.carol))
        with _on():
            billing.apply(self.c, self.carol, _sub("sub_c", "canceled", user=self.carol), now=NOW)
        self.assertTrue(admin.delete_account(self.c, self.carol, by=-1)["ok"])
        self.assertIsNone(self.seat(self.carol))

    def test_in_the_advisors_own_export_without_the_working_id(self):
        self.stripe()
        with _on():
            billing.apply(self.c, self.carol, _sub("sub_c", customer="cus_c", user=self.carol),
                          now=NOW)
            billing.ensure(self.c, self.omar, now=NOW)
            billing.start_checkout(self.c, self.omar, "monthly", "https://x/", now=NOW)
        mine = export.collect(self.c, self.carol)["your_seat"]
        self.assertEqual(len(mine), 1)
        self.assertEqual((mine[0]["stripe_customer"], mine[0]["status"]), ("cus_c", "active"))
        theirs = export.collect(self.c, self.omar)["your_seat"]
        self.assertNotIn("checkout_session", theirs[0])
        self.assertIn("seats", admin.ACCOUNT_TABLES)
        self.assertIn(("your_seat", "seats", "user_id", ""), export.OWN)

    def test_both_schema_files_have_the_same_seats_table(self):
        def cols(name):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            body = re.search(r"CREATE TABLE IF NOT EXISTS seats \((.*?)\n\);", text, re.S).group(1)
            return [re.sub(r"--.*", "", ln).split()[0] for ln in body.splitlines()
                    if re.sub(r"--.*", "", ln).strip()]
        self.assertEqual(cols("schema.sql"), cols("schema_pg.sql"))
        self.assertEqual(tuple(cols("schema.sql")), billing.COLUMNS)
        self.assertGreaterEqual(portfolio.SCHEMA_VERSION, 14)


# --------------------------------------------------------------------------- #
# manual seats: paid outside the app (a Payment Link, an invoice)
# --------------------------------------------------------------------------- #
class ManualTests(_DB):

    def test_set_by_hand_live_until_its_day_then_the_grace(self):
        fake = self.stripe()
        with _on(NORTHWEND_SEAT_GRACE_DAYS="14", NORTHWEND_FOUNDING_SEATS="2"):
            row = billing.set_manual(self.c, self.carol, active=True, paid_through="2026-11-30",
                                     note="Payment Link", founding=True, now=NOW)
            self.assertEqual((row["status"], row["manual_note"], row["founding"],
                              row["founding_no"], row["current_period_end"]),
                             ("active", "Payment Link", 1, 1, "2026-12-01T00:00:00Z"))
            st = billing.state(self.c, self.carol, now=NOW)
            self.assertEqual((st["live"], st["open"], st["manual"]), (True, True, "Payment Link"))
            # setting it again (renewed) doesn't take a second place
            billing.set_manual(self.c, self.carol, active=True, paid_through="2026-12-31",
                               note="Invoice", founding=True, now=NOW)
            self.assertEqual(billing.founding_used(self.c), 1)
            # past the day: not live, open through the grace days counted from it
            dec = datetime(2027, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
            self.assertFalse(billing.state(self.c, self.carol, now=dec)["live"])
            self.assertTrue(billing.can_write(self.c, self.carol, now=dec + timedelta(days=13)))
            self.assertFalse(billing.can_write(self.c, self.carol, now=dec + timedelta(days=15)))
            # nothing renews a manual seat, so it never blocks deleting the account
            self.assertFalse(billing.has_live_seat(self.c, self.carol))
        self.assertEqual(fake.calls, [])

    def test_the_nightly_sync_ends_it_and_never_asks_stripe(self):
        fake = self.stripe()
        with _on(NORTHWEND_SEAT_GRACE_DAYS="14"):
            billing.set_manual(self.c, self.carol, active=True, paid_through="2026-10-31",
                               founding=True, now=NOW)
            billing.set_manual(self.c, self.omar, active=True, paid_through="2027-10-31", now=NOW)
            res = billing.sync_all(self.c, now=NOW + timedelta(days=5), pause=0)
            self.assertEqual(res["manual_ended"], 0)
            later = datetime(2026, 11, 2, tzinfo=timezone.utc)
            res = billing.sync_all(self.c, now=later, pause=0)
        self.assertEqual((res["manual_ended"], res["checked"]), (1, 0))
        self.assertEqual(fake.calls, [])
        row = self.seat(self.carol)
        self.assertEqual((row["status"], row["founding"]), ("ended", 0))
        self.assertEqual(row["grace_until"], "2026-11-15T00:00:00Z")   # Nov 1 + 14 days
        self.assertEqual(self.seat(self.omar)["status"], "active")

    def test_ended_by_hand_and_the_refusals(self):
        self.stripe()
        with _on(NORTHWEND_SEAT_GRACE_DAYS="14", NORTHWEND_FOUNDING_SEATS="1"):
            billing.set_manual(self.c, self.carol, active=True, paid_through="2026-11-30",
                               founding=True, now=NOW)
            row = billing.set_manual(self.c, self.carol, active=False, note="Invoice", now=NOW)
            self.assertEqual((row["status"], row["founding"]), ("ended", 0))
            self.assertTrue(billing.can_write(self.c, self.carol, now=NOW + timedelta(days=13)))
            self.assertFalse(billing.can_write(self.c, self.carol, now=NOW + timedelta(days=15)))
            with self.assertRaises(ValueError):    # no founding places left
                billing.set_manual(self.c, self.omar, active=True, paid_through="2026-11-30",
                                   founding=True, now=NOW)
            self.assertNotEqual(self.seat(self.omar)["status"], "active")
            with self.assertRaises(ValueError):    # a day already gone
                billing.set_manual(self.c, self.omar, active=True, paid_through="2026-10-01",
                                   now=NOW)
            with self.assertRaises(ValueError):    # no day
                billing.set_manual(self.c, self.omar, active=True, now=NOW)
            investor = auth.create_user(self.c, "ivy", PW)
            with self.assertRaises(ValueError):    # not an advisor
                billing.set_manual(self.c, investor, active=True, paid_through="2026-11-30",
                                   now=NOW)
            # a seat paid through Stripe stays Stripe's
            billing.apply(self.c, self.pat, _sub("sub_p", user=self.pat), now=NOW)
            with self.assertRaises(ValueError):
                billing.set_manual(self.c, self.pat, active=False, now=NOW)
            self.assertEqual(self.seat(self.pat)["status"], "active")

    def test_admin_counts_include_manual_seats(self):
        with _on(NORTHWEND_SEAT_GRACE_DAYS="14"):
            billing.set_manual(self.c, self.carol, active=True, paid_through="2026-11-30",
                               founding=True, now=NOW)
            n = billing.counts(self.c, now=NOW)
            self.assertEqual((n["live"], n["founding_kept"]), (1, 1))
            n = billing.counts(self.c, now=datetime(2027, 1, 1, tzinfo=timezone.utc))
            self.assertEqual((n["live"], n["lapsed"]), (0, 1))


# --------------------------------------------------------------------------- #
# one flat fee: never per client, never by usage
# --------------------------------------------------------------------------- #
class FlatFeeTests(unittest.TestCase):

    def test_billing_never_reads_clients_or_intros(self):
        with open(os.path.join(REPO, "billing.py"), encoding="utf-8") as fh:
            src = fh.read()
        code = re.sub(r'(?s)""".*?"""', "", src)                   # docstrings aside
        code = "\n".join(re.sub(r"#.*", "", ln) for ln in code.splitlines())
        for word in ("advisor_clients", "intro_requests", "import intros", "import advising",
                     "list_clients", "former_clients", "usage", "metered", "per_client",
                     "quantity\": len", "COUNT(*)"):
            self.assertNotIn(word, code, word)
        # the only quantity is one seat
        self.assertEqual(re.findall(r'"quantity":\s*([^}\s,]+)', code), ["1"])
        # and the only tables it touches are its own (and app_state's counter)
        tables = set(re.findall(r"(?:FROM|INTO|UPDATE)\s+(\w+)", code))
        # (users: set_manual checks the login is an advisor - its own row only)
        self.assertEqual(tables, {"seats", "app_state", "users"})

    def test_the_words_promise_no_directory(self):
        words = " ".join(str(getattr(billing, n)) for n in (
            "WHAT_IT_IS", "NOT_INCLUDED", "FOUNDING_KEPT", "CARD_NOTE", "CLOSED_LINE"))
        self.assertIn("never per client", words)
        self.assertIn("doesn't include a directory listing", words)
        for bad in ("listed in", "get clients", "leads for you", "matched", "ranked"):
            self.assertNotIn(bad, words.lower())


# --------------------------------------------------------------------------- #
# settings, the nightly job
# --------------------------------------------------------------------------- #
class OpsTests(unittest.TestCase):
    NAMES = ("STRIPE_SECRET_KEY", "STRIPE_PRICE_MONTHLY", "STRIPE_PRICE_YEARLY",
             "STRIPE_PRICE_STANDARD_MONTHLY", "STRIPE_PRICE_STANDARD_YEARLY",
             "NORTHWEND_FOUNDING_SEATS", "NORTHWEND_SEAT_PRICES",
             "NORTHWEND_STANDARD_SEAT_PRICES", "NORTHWEND_SEAT_GRACE_DAYS")

    def _read(self, *parts):
        with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_every_setting_documented_and_on_render_as_a_secret(self):
        env, render = self._read(".env.example"), self._read("render.yaml")
        for name in self.NAMES:
            self.assertRegex(env, rf"(?m)^{name}=$", name)
            self.assertRegex(render, rf"- key: {name}\s.*\n\s+sync: false", name)

    def test_defaults(self):
        with _settings():
            self.assertEqual(billing.founding_seats(), 20)
            self.assertEqual(billing.grace_days(), 14)
            self.assertEqual(billing.prices(True), {"monthly": "$79", "yearly": "$790"})
            self.assertEqual(billing.prices(False), {"monthly": "$79", "yearly": "$790"})
            self.assertEqual(billing.price_words(True), "$79 a month, or $790 a year")
        with _settings(NORTHWEND_FOUNDING_SEATS="x", NORTHWEND_STANDARD_SEAT_PRICES="99/990",
                       NORTHWEND_SEAT_PRICES="nonsense"):
            self.assertEqual(billing.founding_seats(), 20)
            self.assertEqual(billing.prices(True), {"monthly": "$79", "yearly": "$790"})
            self.assertEqual(billing.prices(False), {"monthly": "$99", "yearly": "$990"})

    def test_the_nightly_job_runs_the_sync_and_tells_the_admin(self):
        text = self._read(".github", "workflows", "scheduled-sync.yml")
        job = text.split("\n  billing-sync:", 1)[1]
        self.assertIn('python billing.py --sync --db "$DATABASE_URL"', job)
        self.assertIn("STRIPE_SECRET_KEY: ${{ secrets.STRIPE_SECRET_KEY }}", job)
        self.assertIn("if: failure()", job)
        self.assertIn('python error_alerts.py job "Seat check with Stripe"', job)
        self.assertIn("'20 6 * * *'", job)
        self.assertIn('- cron: "20 6 * * *"', text)

    def test_the_runbook_has_the_stripe_steps(self):
        text = self._read("docs", "RUNBOOK.md")
        section = text.split("## Billing: Stripe setup", 1)[1].split("\n## ", 1)[0]
        for words in ("test mode", "restricted key", "Customer portal", "STRIPE_PRICE_MONTHLY",
                      "STRIPE_SECRET_KEY", "billing.py --sync", "L1a"):
            self.assertIn(words, section)


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_billing_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            prefs.save(c, cls.carol, {"advisor_card": {"name": "Carol Reyes",
                                                       "firm": "Reyes Wealth"}})
            cls.dana = auth.create_user(c, "dana", PW)
            auth.link_client(c, cls.carol, cls.dana)
            # an admin (made by an admin, listed in NORTHWEND_ADMINS in the runs)
            cls.ann = auth.create_user(c, "ann", PW)
            secret = two_step.new_secret()
            two_step.enable(c, cls.ann, secret, two_step.totp(secret))
            cls.ann_ok = f"{cls.ann}:{two_step.status(c, cls.ann)['stamp']}"
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _seat(self, status=None, grace=None):
        """carol's seat: none (no row), or a row with this status and grace end."""
        c = portfolio.connect(self.db)
        try:
            c.execute("DELETE FROM seats")
            if status:
                c.execute("INSERT INTO seats (user_id, status, founding, grace_until, started_at, "
                          "stripe_customer, created_at) VALUES (?, ?, 0, ?, ?, ?, ?)",
                          (self.carol, status, grace,
                           None if status == "none" else "2026-01-01T00:00:00Z", "cus_c",
                           "2026-01-01T00:00:00Z"))
            c.commit()
        finally:
            c.close()

    def _run(self, page, flags="", gates="", stripe=True, at=None, admins="", **state):
        from streamlit.testing.v1 import AppTest
        import yfinance

        def offline(*a, **k):
            raise RuntimeError("offline in tests")

        def no_stripe(*a, **k):
            raise urllib.error.URLError("offline in tests")
        if at is None:
            at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
            for k, v in {"user_id": self.carol, "username": "carol", "page": page,
                         "two_step_ok": self.carol_ok, **state}.items():
                at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "RESEND_API_KEY")
               + SETTING_NAMES}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flags, NORTHWEND_GATES=gates, NORTHWEND_ADMINS=admins,
                   **(STRIPE_ENV if stripe else {}))
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("urllib.request.urlopen", no_stripe), \
                unittest.mock.patch("settings.load_env", lambda *a, **k: {}), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown]
        for kind in ("success", "info", "warning", "error", "caption", "subheader"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    def _keys(self, at):
        return [b.key for b in at.button]

    def test_off_everything_is_as_today(self):
        self._seat("canceled", "2026-01-02T00:00:00Z")      # even a long-ended seat row
        for flags_value, gates in (("", "L1a"), ("billing", "L0"), ("billing", "L1b,L2")):
            with self.subTest(flags=flags_value, gates=gates):
                at = self._run("Clients", flags_value, gates)
                self.assertIn("add_client", self._keys(at))
                self.assertNotIn(billing.CLOSED_LINE, self._text(at))
                acct = self._run("Account", flags_value, gates)
                self.assertNotIn(billing.TITLE, [s.value for s in acct.subheader])

    def test_lapsed_add_and_send_close_reading_and_export_stay(self):
        self._seat("canceled", "2026-01-02T00:00:00Z")
        at = self._run("Clients", "billing", "L1a")
        keys, text = self._keys(at), self._text(at)
        self.assertIn(billing.CLOSED_LINE, text)
        self.assertNotIn("add_client", keys)
        self.assertNotIn("bulk_add", keys)
        self.assertIn("seat_go_add", keys)
        self.assertIn("all_records_prepare", keys)         # the export of every record
        self.assertIn("dana", text)                         # the book is still there to read
        # Subscribe goes to Account > Your seat
        at.button(key="seat_go_add").click()
        at = self._run("Clients", "billing", "L1a", at=at)
        self.assertEqual(at.session_state["page"], "Account")
        self.assertIn(billing.TITLE, [s.value for s in at.subheader])
        self.assertIn("seat_subscribe", self._keys(at))
        self.assertIn(billing.CLOSED_LINE, self._text(at))
        # Subscribe with Stripe unreachable: the calm line, nothing charged, no error
        at.button(key="seat_subscribe").click()
        at = self._run("Account", "billing", "L1a", at=at)
        self.assertIn(billing.NOT_REACHED, self._text(at))

    def test_in_grace_or_live_it_all_works(self):
        self._seat("none", "2099-01-01T00:00:00Z")
        at = self._run("Clients", "billing", "L1a")
        self.assertIn("add_client", self._keys(at))
        self.assertNotIn(billing.CLOSED_LINE, self._text(at))
        acct = self._run("Account", "billing", "L1a")
        self.assertIn("No active seat yet", self._text(acct))
        self.assertIn("20 of 20 founding places left", self._text(acct))
        self._seat("active", None)
        at = self._run("Clients", "billing", "L1a")
        self.assertIn("add_client", self._keys(at))
        acct = self._run("Account", "billing", "L1a")
        self.assertIn("seat_portal", self._keys(acct))
        self.assertNotIn("seat_subscribe", self._keys(acct))

    def test_the_admin_sets_a_seat_by_hand_and_it_is_logged(self):
        import admin_log
        from datetime import date
        self._seat()
        at = self._run("Admin", "billing", "L1a", admins="ann", user_id=self.ann,
                       username="ann", two_step_ok=self.ann_ok)
        self.assertIn("Advisor seats", [s.value for s in at.subheader])
        at.selectbox(key="admin_seat_who").set_value(self.carol)
        at.date_input(key="admin_seat_until").set_value(date(2030, 11, 30))
        at.selectbox(key="admin_seat_note").set_value("Invoice")
        at.checkbox(key="admin_seat_founding").check()
        at.button(key="admin_seat_save").click()
        at = self._run("Admin", "billing", "L1a", admins="ann", at=at)
        self.assertIn("Seat saved.", self._text(at))
        c = portfolio.connect(self.db)
        try:
            row = billing.seat(c, self.carol)
            self.assertEqual((row["status"], row["manual_note"], row["founding"]),
                             ("active", "Invoice", 1))
            (log,) = [r for r in admin_log.recent(c) if r["action"] == "seat_manual"]
            self.assertEqual((log["target"], log["admin"]), ("carol", "ann"))
            self.assertIn("active through 2030-11-30, Invoice, founding place", log["detail"])
        finally:
            c.close()
        # carol's Your seat: the status, no Subscribe and no Manage billing
        acct = self._run("Account", "billing", "L1a")
        text = self._text(acct)
        self.assertIn("paid outside the app (Invoice)", text)
        self.assertIn("Paid through Nov 30, 2030", text)
        self.assertIn(billing.MANUAL_RENEW, text)
        self.assertNotIn("seat_subscribe", self._keys(acct))
        self.assertNotIn("seat_portal", self._keys(acct))
        self.assertIn("add_client", self._keys(self._run("Clients", "billing", "L1a")))
        # with the flag off, no seat panel in Admin
        at = self._run("Admin", "", "L1a", admins="ann", user_id=self.ann, username="ann",
                       two_step_ok=self.ann_ok)
        self.assertNotIn("admin_seat_save", self._keys(at))

    def test_without_stripe_set_up_no_checkout_is_offered(self):
        self._seat("none", "2099-01-01T00:00:00Z")
        acct = self._run("Account", "billing", "L1a", stripe=False)
        self.assertIn(billing.NOT_SET_UP, self._text(acct))
        self.assertNotIn("seat_subscribe", self._keys(acct))

    def test_back_from_stripe_the_link_alone_changes_nothing(self):
        from streamlit.testing.v1 import AppTest
        self._seat("none", "2026-01-02T00:00:00Z")        # past its grace, no checkout kept
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.carol, "username": "carol",
                     "two_step_ok": self.carol_ok}.items():
            at.session_state[k] = v
        at.query_params["page"] = "account"
        at.query_params["billing"] = "done"
        at = self._run("Account", "billing", "L1a", at=at)
        self.assertEqual(at.session_state["page"], "Account")
        self.assertNotIn("billing", at.query_params)       # taken off the address
        # a crafted ?billing=done with nothing kept to check: still not active
        self.assertIn(billing.CLOSED_LINE, self._text(at))
        c = portfolio.connect(self.db)
        try:
            self.assertEqual(billing.seat(c, self.carol)["status"], "none")
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
