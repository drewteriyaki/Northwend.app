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
    # Reading holdings from screenshots with the AI (screenshot_read.py,
    # views/holdings_input.py): the image goes to the model, so it's off on
    # the live copy (decision D1). Paste and CSV work without it.
    "screenshot_ai": {"gates": (), "view": None},
    # The Storm Drill (ROADMAP R4, future_notes.DRILL, views/future_notes.py):
    # "What will you do when this happens?" on the Plan's Stress test, shown
    # back on Home's storm note when a drop comes; counted in totals only
    # (feature_counts.drill_answers, Admin > Feature tests).
    "storm_drill": {"gates": (), "view": None},
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
