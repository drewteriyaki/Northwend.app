"""What's new: a short, dated list of what changed for people using
Northwend, opened from the name menu (views/whats_new.py). Pure data and
logic, no Streamlit.

Every release to main that changes something people can see adds an entry
at the top of ENTRIES, in the same plain, calm words as the rest of the app:
what they can now do or will notice, never code or test details. An item
for a feature behind a flag names it (`flag`), so it only shows on copies
where that feature is on - a hidden feature is never announced.

Nothing nags: the name menu shows a small dot until the newest entry has
been opened once (PREF_SEEN, in the person's own settings), and that's all.
"""

from __future__ import annotations

from datetime import date

PREF_SEEN = "whats_new_seen"   # the date (ISO) of the newest entry they've opened

# newest first. Each entry: date (ISO), title, and items - a string, or a
# dict {"text": ..., "flag": feature name in flags.FEATURES} for a feature
# that's off on some copies.
ENTRIES = [
    {"date": "2026-10-06", "title": "See when your advisor looks",
     "items": [
         "If you have an advisor, your Account page now shows when they looked at your "
         "account and which page they opened. Only you see this list.",
         "Agreeing to share your account with an advisor, and stopping, is now noted with "
         "the words you were shown. You'll find it under Your sharing record, and in your "
         "data download.",
     ]},
    {"date": "2026-10-06", "title": "Our Terms of Use and Privacy Policy",
     "items": [
         "Northwend's Terms of Use and Privacy Policy are now published on northwend.app, "
         "linked from the About page and wherever you agree to them. They say the same "
         "things as the About page, in more detail: education, not advice; free, with no ads "
         "or commissions; and what's kept, what never is, and how to download or delete it.",
     ]},
    {"date": "2026-10-06", "title": "Ask Northwend, a little wiser",
     "items": [
         "Ask Northwend now has Northwend's own glossary and short reads built in, so its "
         "explanations match what you see in the app.",
         "It can work things out for you as you chat - how a mix held up in past drops, how "
         "fees add up over the years, how a goal projection changes - all as percentages.",
         "If you have an advisor, questions about your plan are pointed to them by name.",
         {"text": "Decode a 401(k) menu: paste your workplace plan's fund list and see what "
                  "kind of fund each one is and what it charges. It's beside the Free money "
                  "check on Plan.", "flag": "decoder_401k"},
     ]},
    {"date": "2026-10-06", "title": "Clearer, calmer, and the same for everyone",
     "items": [
         "Learn and Plan now show common starting points for different timelines - the same "
         "for everyone - and your target mix is always yours to choose.",
         "The plan PDF lists questions to look into, worked out from your own plan, instead "
         "of AI-written next steps.",
         "Ask Northwend explains and does arithmetic but never tells you what to buy or sell. "
         "Profile answers it picks up are saved only when you tap Save, and you can see and "
         "delete what it remembers on the Account page.",
         {"text": "The Storm Drill: on the Stress test, write down what you'll do when a big "
                  "drop comes. When one does, Home shows you your own words.",
          "flag": "storm_drill"},
         {"text": "Your walk log: one line for each monthly walk, so you can look back on "
                  "how your plan went.", "flag": "walk_log"},
     ]},
    {"date": "2026-10-06", "title": "Safer sign-in, and your data",
     "items": [
         "\"Sign out other devices\" on the Account page now closes your other open tabs too.",
         "Passwords are now stored with stronger protection. Nothing changes for you.",
         "New accounts confirm they live in the United States, beside the 18-or-older box.",
         "Reminder emails have a one-click link to stop them.",
         "The About page says plainly what's kept (your holdings, so the app can show them) "
         "and what never is (your brokerage login, uploaded files, full account numbers).",
     ]},
    {"date": "2026-10-05", "title": "New tools for your money",
     "items": [
         "Stress test: see how your mix held up through 2008, 2020 and 2022.",
         "Where your next deposit could go, to move toward your own target without selling.",
         "Cash check and Free money check (your employer's 401(k) match).",
         "Money going out: plan for big expenses and monthly withdrawals.",
         "Notes to future you, Year in review, and an account map for the people you trust.",
         {"text": "The Monthly Walk: a few minutes once a month to check in on your plan.",
          "flag": "walk"},
     ]},
]


def _item(it) -> dict:
    return it if isinstance(it, dict) else {"text": it, "flag": None}


def visible(on=None, entries=None) -> list[dict]:
    """The entries with only the items this copy shows (`on(flag) -> bool`;
    default flags.on); an entry with nothing left is dropped."""
    if on is None:
        import flags
        on = flags.on
    out = []
    for e in ENTRIES if entries is None else entries:
        items = [_item(i)["text"] for i in e["items"]
                 if not _item(i).get("flag") or on(_item(i)["flag"])]
        if items:
            out.append({"date": e["date"], "title": e["title"], "items": items})
    return out


def latest(on=None, entries=None) -> str | None:
    """The newest visible entry's date, or None."""
    shown = visible(on, entries)
    return max(e["date"] for e in shown) if shown else None


def unseen(prefs: dict, on=None, entries=None) -> bool:
    """True while there's an entry newer than the one they last opened."""
    newest = latest(on, entries)
    return bool(newest) and (prefs or {}).get(PREF_SEEN, "") < newest


def mark_seen(prefs: dict, on=None, entries=None) -> dict:
    """The settings with the newest visible entry marked as seen."""
    newest = latest(on, entries)
    return {**(prefs or {}), PREF_SEEN: newest} if newest else dict(prefs or {})


def when(iso: str) -> str:
    """'October 6, 2026'."""
    d = date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"
