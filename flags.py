"""Feature flags and legal gates (docs/PLAN.md "Flags and gates";
docs/LEGAL_GATES.md section 1). Standard library only (Streamlit's secrets
are read if Streamlit is there).

Two settings, both off unless set:
- NORTHWEND_GATES - the legal gates the owner's lawyer has signed off, for
  example "L0,L3". Only L0-L3 exist. There is no L4 (in-house advice is
  never in scope): a setting that names it is ignored, and a test checks it.
- NORTHWEND_FLAGS - the features turned on, for example "walk,screenshot_ai".

Each is read from the environment first, then the app's Streamlit secrets
(where a TOML list, ["walk", "screenshot_ai"], works as well as a comma
string). Missing or empty means off. Staging turns everything on; the live
copy turns on only what's been approved. Neither is a secret: Admin > System
lists them (state()).

FEATURES is the one table: each feature's flag name, the gates it needs as
well as its flag, and the view it owns (views/<view>.py), if any, with the
page (PAGES) that view draws. on(name) is true only when its flag and every
one of its gates are on. dashboard._view() skips a view whose feature is off,
and a page whose feature is off leaves PAGES and the menu. A feature drawn
inside an existing view checks on("name") where it's drawn - a test checks
every name in FEATURES is checked somewhere.

A gate can also be checked on its own, with gate("L0"), for what it changes
in something people already use (LEGAL_GATES.md's "when it is off" column).
GATE_CHECKS lists each such check; a test makes sure each one is really
checked somewhere. The rest are wired in with each gate's own work (L3's
careful wording, step 2).
"""

from __future__ import annotations

import os

GATES = ("L0", "L1", "L2", "L3")   # never an L4 (LEGAL_GATES.md: no flag, nothing built toward it)
GATES_SETTING = "NORTHWEND_GATES"
FLAGS_SETTING = "NORTHWEND_FLAGS"

# gate -> what checking it on its own (gate(...)) changes, and where
GATE_CHECKS = {
    # PLAN 1a.9, decision B7: open self-serve sign-up. Off, Create account asks
    # for an invite code the admin made (auth.invite_only, invite_codes.py).
    # Signing in, setup links and admin-made accounts never change. The live
    # copy needs NORTHWEND_GATES = "L0" to keep sign-up open.
    "L0": "open self-serve sign-up - off, Create account needs an invite code",
    # PLAN step 2, master brief 3.1 and 5.3 (LEGAL_GATES.md "What off means
    # for L3"): anything worked out from a person's answers. Off, Learn, Home
    # and Plan show common starting points - one table, the same for everyone
    # (learn.common_starting_points) - instead of an example mix or investor
    # type picked for them, and nothing copies Northwend's mix into their
    # target (dashboard.TAILORED_MIX); Ask Northwend's about-my-situation
    # answers stay in general terms (ai_policy.situation_answers_open). On:
    # today's tailored example mix, pending the lawyer.
    "L3": "answers worked out from a person's own answers - off, common starting points "
          "the same for everyone, and Ask Northwend's about-my-situation answers stay general",
    # PLAN step 5 item 1, master brief 4.1 and 4.5: advisor seats. Off, every
    # seat is a free beta seat and the advisor agreement (advisor_agreement.py,
    # its own flag below) is shown marked "Beta"; which state it was in is
    # kept with each acceptance. No billing exists yet (step 6).
    "L1": "advisor seats - off, free beta seats, and the advisor agreement is shown marked Beta",
}

# name -> {"gates": the gates it needs besides its flag, "view": the view it
# owns or None, and "page": that view's page, when it's one of PAGES}
FEATURES = {
    # The Monthly Walk (ROADMAP R1, checkin.py): the Home card, the Account
    # "Monthly walk" section, its reminder email (checkin_email.py) and the
    # kit's logbook. A calculator on the person's own target and band
    # (LEGAL_GATES.md C3: L0 is the baseline every live feature sits under,
    # not a switch; its verdict wording is L3's work in step 2).
    "walk": {"gates": (), "view": None},
    # The Expedition Log (ROADMAP R3, expedition_log.py): a line per finished
    # walk ("Your log" on the Walk card, the year's lines in Year in review).
    # Drawn inside the walk's card, so it needs `walk` on too.
    "walk_log": {"gates": (), "view": None},
    # The Do-Nothing Ledger (ROADMAP R2, ledger.py): "You stayed with your
    # plan" per walk with no sale, and during a drop the hypothetical both
    # ways. Inside the walk's card too, so it needs `walk` on.
    "ledger": {"gates": (), "view": None},
    # Reading holdings from screenshots with the AI (screenshot_read.py,
    # views/holdings_input.py): the image goes to the model, so it's off on
    # the live copy (decision D1). Paste and CSV work without it.
    "screenshot_ai": {"gates": (), "view": None},
    # The Storm Drill (ROADMAP R4, future_notes.DRILL, views/future_notes.py):
    # "What will you do when this happens?" on the Plan's Stress test, shown
    # back on Home's storm note when a drop comes; counted in totals only
    # (feature_counts.drill_answers, Admin > Feature tests).
    "storm_drill": {"gates": (), "view": None},
    # The Sealed Envelope (ROADMAP "Someday" -> built, sealed_envelope.py): under
    # the person's own Storm Drill answer, "Make it a sealed envelope" - a
    # one-page PDF of their words and the day, no figures, made on click and
    # never saved (prefs keep only the day it was made, for the storm note's
    # line). Descriptive (their own words; LEGAL_GATES.md section 6): no gate.
    # Drawn beside the drill answer, so it needs `storm_drill` on too
    # (views/future_notes.py checks both); never while an advisor is in a
    # client's account.
    "sealed_envelope": {"gates": (), "view": None},
    # The 401(k) Menu Decoder (ROADMAP R5, menu_decoder.py): paste a plan's
    # fund list, see each fund's kind and fee - descriptive, no AI, nothing
    # saved (LEGAL_GATES.md section 6: L0 + flag; L3 looks at it). Its window
    # opens from a card beside the Free money check (Plan's Contributions tab,
    # Learn's "Are you ready to invest?" step).
    "decoder_401k": {"gates": (), "view": "menu_decoder"},
    # The same decoder without an account (master brief 8a; PLAN step 3 item 6,
    # decision B12; decoder_public.py): ?decode=401k before sign-in, linked from
    # the website's /decode-401k page. No AI, cached fund data only, nothing
    # kept but a rate-limit count per hashed address (LEGAL_GATES.md section 6:
    # L0 + flag). Its first page without sign-in: switch it on in production
    # only after step 4's hosting move (Render behind Cloudflare, so the limit
    # sees each visitor's real address - CLIENT_IP_HEADER). Staging may have it on.
    "decoder_public": {"gates": ("L0",), "view": "decoder_public"},
    # Lost & Found (ROADMAP R9, lost_found.py): where to look for old 401(k)s,
    # unclaimed property, old HSAs, FSAs and IRAs and savings bonds (official
    # links only), an old 401(k)'s common choices side by side with questions
    # to ask - never which one - and the person's own "places I've looked"
    # list in their settings. Education (LEGAL_GATES.md section 6): no gate.
    # Under the account map on Account (views/account.py checks on("lost_found")),
    # the login's own only - never while an advisor is in a client's account.
    "lost_found": {"gates": (), "view": "lost_found"},
    # Trail Forks (ROADMAP R8, trail_forks.py): a route per life event (a new
    # job, a layoff, a new baby, an inheritance, a divorce, the death of a
    # parent) - what changes, what to gather, what to ask and whom, what not
    # to rush - each ending in the Walk. Education (LEGAL_GATES.md section 6):
    # no gate. Under Lost & Found on Account (views/account.py checks
    # on("trail_forks")); the person's forks and ticks in their own settings,
    # never drawn while an advisor is in a client's account.
    "trail_forks": {"gates": (), "view": "trail_forks"},
    # The Four Seasons (ROADMAP R7, seasons.py): January (this year's limits,
    # last year's IRA window, the fee bill to the goal date), April (tax forms
    # explained), October-November (open enrollment, HSAs), December (Year in
    # review, a letter to future you, an RMD reminder for the 65-or-older age
    # range). Education (LEGAL_GATES.md section 6): no gate. A card on Home in
    # season and a line on Learn (views/dashboard_page.py and
    # views/get_started.py check on("seasons")); the login's own only.
    "seasons": {"gates": (), "view": "seasons"},
    # Explain it to someone (ROADMAP R10, explain_share.py): a private,
    # expiring, revocable link (?share=...) that shows a partner or family
    # member the owner's plan in plain words - asset-class percents, the
    # goal's kind and timeline bucket, the route stage, the target mix and
    # band; never a figure, holding or account detail. Descriptive (the
    # person's own data, LEGAL_GATES.md section 6): no gate. Owns no view on
    # purpose: views/explain_share.py always loads so that, while this is
    # off, an existing link still shows the calm "no longer active" page
    # (it checks on("explain_share") itself, as views/account.py does before
    # drawing the owner's section).
    "explain_share": {"gates": (), "view": None},
    # "Price look wrong?" (PLAN G8, price_report.py): on a ticker's details a
    # person picks a fixed reason (no free text) and a row goes in
    # price_reports; admins see counts by ticker and reason, never who. Account
    # data, nothing advice-like: no gate. Drawn in views/ticker_detail.py and
    # counted in views/admin.py, which check on("price_report"). The "as of"
    # words under each price aren't flagged: they only describe the prices
    # already shown.
    "price_report": {"gates": (), "view": None},
    # Preparedness drills (ROADMAP R12, the one-week test; drills.py): ten short
    # tap-only situations, hard times and good times alike, one a week in a
    # small card on Home under Your kit, with the readiness map, a count of
    # weeks rehearsed and the whistle for the kit. Taps are considerations and
    # questions, never trades, never graded. Education with the person's own
    # mix in percentages (LEGAL_GATES.md section 6: L0 + flag; L3 reviews that
    # no drill implies a correct choice). The person's own only: never while
    # an advisor is in a client's account, never in the client record or the
    # AI. views/dashboard_page.py and views/start_home.py check on("drills").
    "drills": {"gates": (), "view": "drills"},
    # Trail Conditions (ROADMAP "The weekly rhythm", Phase C; trail_conditions.py):
    # an opt-in Monday email, off by default (Account > Trail Conditions, the
    # login's own switch; views/account.py checks on("trail_conditions")).
    # "Calm on the trail - nothing to do" almost every week; fixed lines only
    # when a storm, a season, the walk or the readiness map changed. No
    # figures, no forecasts. Education (LEGAL_GATES.md section 6): no gate.
    # CAN-SPAM: one-click unsubscribe and a postal address in every email -
    # nothing is sent while mailer.POSTAL_ADDRESS is empty.
    "trail_conditions": {"gates": (), "view": None},
    # Pay yourself (ROADMAP R11, pay_yourself.py): a Plan tab next to Money
    # going out - a monthly "paycheck" picture from the person's own payouts
    # (income.py) under a rule of thumb they pick from a fixed, named list
    # (income only, the default; 3%, 4% or 5% of today's balance a year), the
    # thinnest month, and a labelled hypothetical 20% fall. The closest thing
    # here to retirement-income advice for one person, so it needs gate L3 as
    # well as its flag: L3 review before it's on anywhere but staging
    # (LEGAL_GATES.md section 6). views/plan.py checks on("pay_yourself");
    # never for an advisor's client signed in themselves; an advisor in a
    # client's account sees it with the standing line and saves nothing.
    "pay_yourself": {"gates": ("L3",), "view": "pay_yourself"},
    # The advisor agreement and attestation (PLAN step 5 item 1, master brief
    # 4.1; advisor_agreement.py, views/advisor_agreement.py): an approved
    # advisor accepts it before Your clients and clients' accounts open. Not
    # behind L1: with L1 off the same text is shown marked "Beta" (free beta
    # seats, brief 4.5) - L1 changes only that label (GATE_CHECKS).
    "advisor_agreement": {"gates": (), "view": None},
    # The advisor directory (PLAN step 5 items 3-4 and 11, master brief 3.3 and
    # 4.2, decision B4; directory.py): "Find a guide" in an individual's name
    # menu (never in client mode, never for an advisor), and "Your directory
    # listing" on Your clients (views/clients.py checks on("directory")).
    # Alphabetical within the person's filters, nothing ranked, nothing about
    # browsing counted. Gate L2: its copy, filters and order are the lawyer's.
    "directory": {"gates": ("L2",), "view": "directory", "page": "Find a guide"},
    # Introductions and the two-step consent to full sharing (PLAN step 5 items
    # 5-6, master brief 4.3; intros.py, views/intros.py): "Request an
    # introduction" on Find a guide sends a message and a figure-free outline;
    # the advisor answers under Introductions on Your clients; the person may
    # then share their full account in two steps. Drawn inside Find a guide and
    # Your clients, so it needs `directory` on too (views/directory.py and
    # views/clients.py check on("intros")). Gate L2: its copy and the consent
    # text are the lawyer's. Off, the button says introductions open soon.
    "intros": {"gates": ("L2",), "view": "intros"},
    # The plain-words read of the mix on Home (PLAN step 7, docs/AI_PLAN.md
    # section 9 row 1; allocation.summary_words): one line under Allocation
    # from fixed templates - shares, counts, the largest holding's share. No
    # AI and no judgement words. Descriptive (LEGAL_GATES.md section 6): no
    # gate; views/dashboard_page.py checks on("plain_summary").
    "plain_summary": {"gates": (), "view": None},
    # The glossary in the app (PLAN step 7, AI_PLAN section 9 row 5;
    # glossary.py): "What does this mean?" beside the words on Home's
    # allocation, the Fee check, Income and Learn's "Open your account", and
    # the whole list in Learn's basics. Owner-written, the same text Ask
    # Northwend reads. Education: no gate. dashboard.what_this_means()
    # checks on("glossary").
    "glossary": {"gates": (), "view": None},
}


def _secret(name: str):
    """A value from Streamlit's secrets (.streamlit/secrets.toml, or the hosted
    app's Secrets box), or None - also when there's no Streamlit or no file."""
    try:
        import streamlit as st
        if not st.secrets.load_if_toml_exists():
            return None
        return st.secrets.get(name)
    except Exception:  # noqa: BLE001 - a missing or broken secrets file means "not set"
        return None


def _names(setting: str) -> set[str]:
    """The names a setting lists: the environment first (Streamlit Cloud copies
    a string secret there too), then Streamlit's secrets. Commas or spaces
    between names, or a TOML list."""
    raw = os.environ.get(setting)
    if raw is None:
        raw = _secret(setting)
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set)):
        raw = ",".join(str(x) for x in raw)
    return {x.strip() for x in str(raw).replace(",", " ").split() if x.strip()}


def gates_on() -> set[str]:
    """The gates set on - only real ones (GATES); anything else is ignored."""
    return {g.upper() for g in _names(GATES_SETTING)} & set(GATES)


def flags_set() -> set[str]:
    """Every flag name the setting lists (lower case), known or not."""
    return {f.lower() for f in _names(FLAGS_SETTING)}


def gate(name: str) -> bool:
    """Whether a legal gate is on. Never true for anything outside GATES."""
    return name.upper() in gates_on()


def on(name: str) -> bool:
    """Whether a feature is on: its flag is set and every gate it needs is on.
    An unknown name is off."""
    feat = FEATURES.get(name)
    if feat is None or name not in flags_set():
        return False
    have = gates_on()
    return all(g in have for g in feat["gates"])


def view_on(view: str) -> bool:
    """Whether dashboard._view() runs views/<view>.py: every feature that owns
    it is on (a view no feature owns always runs)."""
    return all(on(n) for n, f in FEATURES.items() if f.get("view") == view)


def page_on(page: str) -> bool:
    """Whether a page stays in PAGES and the menu: every feature whose view
    draws it is on."""
    return all(on(n) for n, f in FEATURES.items() if f.get("page") == page)


def state() -> dict:
    """For Admin > System: {"gates": {gate: on}, "flags": {name: {"on", "set",
    "needs"}}, "unknown": flag names set that no feature has}."""
    have, listed = gates_on(), flags_set()
    return {"gates": {g: g in have for g in GATES},
            "flags": {n: {"on": on(n), "set": n in listed, "needs": tuple(f["gates"])}
                      for n, f in FEATURES.items()},
            "unknown": sorted(listed - set(FEATURES))}
