"""What's new: a short, dated list of what changed for people using
Northwend, opened from the name menu (views/whats_new.py). Pure data and
logic, no Streamlit.

Every release to main that changes something people can see adds an entry
at the top of ENTRIES, in the same plain, calm words as the rest of the app:
what they can now do or will notice, never code or test details. An item
for a feature behind a flag names it (`flag`), so it only shows on copies
where that feature is on - a hidden feature is never announced.

The website's What's new page (northwend.app/whats-new) is built from
ENTRIES too, with every flagged item left out: run `python website/build.py`
after editing (a test fails while website/public/ is stale).

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
    {"date": "2026-10-07", "title": "Northwend in your browser tab",
     "items": [
         "Your browser tab now says Northwend, with its flag icon, from the moment the "
         "page starts loading.",
     ]},
    {"date": "2026-10-06", "title": "This month's world",
     "items": [
         {"text": "Some months, the drill card on Home has a short note on what happened in "
                  "the markets and the economy last month - only what already happened, never "
                  "a forecast. It has a line about investments like yours and links to the "
                  "official sources. Each note is written by hand and checked before it "
                  "appears. Nothing about you goes into it, and it's never sent to the AI.",
          "flag": "month_world"},
     ]},
    {"date": "2026-10-06", "title": "Your walks and your advisor",
     "items": [
         {"text": "If you work with an advisor, you can now choose to let them see whether "
                  "you've done your monthly walk this month - just yes or not yet, and the "
                  "month of your last one, never what your plan said or any amount. It's off "
                  "until you turn it on, on the Your advisor page. Stop sharing there now also "
                  "spells out what you keep (everything in your account) and what your "
                  "advisor keeps (their own notes).", "flag": "client_owned_book"},
         {"text": "Advisors: Your clients has a short note on how the book works, counts of "
                  "clients who walked this month and who updated their holdings lately, and "
                  "each client's figures marked client-reported with the day they were last "
                  "updated.", "flag": "client_owned_book"},
     ]},
    {"date": "2026-10-06", "title": "Look up another word, and drafts for advisors",
     "items": [
         {"text": "Under the glossary in Learn, you can now look up a word it doesn't have. "
                  "Only the word goes to Ask Northwend - nothing about you or your money - and "
                  "the answer is a general explanation, labelled as one.", "flag": "glossary_ai"},
         {"text": "For advisors: Draft with Northwend writes a first draft of a proposal's "
                  "words, a message to clients or a progress report's message, right in the "
                  "box, for you to edit. Nothing goes to a client until you send it yourself, "
                  "under your name.", "flag": "advisor_drafts"},
     ]},
    {"date": "2026-10-06", "title": "The Inheritance Rehearsal",
     "items": [
         {"text": "The Inheritance Rehearsal, on the Account page, is a practice run with a "
                  "made-up family: it goes through looking after a parent's accounts after "
                  "they die, one small step at a time - finding out what accounts there are, "
                  "who to call, which papers people are often asked for, and taking care of "
                  "yourself. Nothing is graded, and it never tells you what to do; it's there "
                  "so you'll know what to expect if it ever happens for real.",
          "flag": "inheritance_rehearsal"},
     ]},
    {"date": "2026-10-06", "title": "Teach it back",
     "items": [
         {"text": "Under each of the basics on Learn there's now an optional box to explain "
                  "the idea back in your own words. Northwend's AI tells you whether you've "
                  "got the main idea and points to what the topic says - generously, never "
                  "with a score, and never about your own money. Try again as often as you "
                  "like; your words aren't saved. Explaining three topics earns the map case "
                  "for your kit.",
          "flag": "teach_back"},
     ]},
    {"date": "2026-10-06", "title": "Trail Conditions",
     "items": [
         {"text": "Trail Conditions is a short Monday email you can turn on from the Account "
                  "page. Most weeks it just says nothing needs your attention. It mentions "
                  "something only when there's something new: a seasonal guide, your monthly "
                  "check-in, a practice question, or a big drop in the markets. It never has "
                  "amounts or anything else about your money, and one click stops it.",
          "flag": "trail_conditions"},
     ]},
    {"date": "2026-10-06", "title": "Pay yourself",
     "items": [
         {"text": "A new Pay yourself tab on the Plan page shows your savings as a monthly "
                  "paycheck: what your investments are estimated to pay each month, and how "
                  "much a rule of thumb you pick from a short list would give. It shows which "
                  "month pays the least, and what the paycheck would be if investments fell "
                  "20% - hypothetical, not a forecast and not advice - with questions to ask a licensed professional about "
                  "retirement income.", "flag": "pay_yourself"},
     ]},
    {"date": "2026-10-06", "title": "Bring to my advisor",
     "items": [
         {"text": "If you work with an advisor, Bring to my advisor on the Account page lets "
                  "you pick private things to show them before a meeting: your plan in plain "
                  "words, the life events you've marked in Trail Forks (just their names), "
                  "which practice drills you've done, your Storm Drill answer, the places "
                  "you've looked for forgotten money, and questions you'd like to ask. Nothing "
                  "is ticked to start with, you're asked once before anything is shared, and "
                  "if you untick something they stop seeing it straight away.",
          "flag": "advisor_pack"},
         {"text": "Advisors see only what a client ticked, dated and marked as shared by the "
                  "client, and a short note on what clients are reading this season.",
          "flag": "advisor_pack"},
     ]},
    {"date": "2026-10-06", "title": "Read a fund fact sheet",
     "items": [
         {"text": "Read a fund fact sheet: paste the text of a fund's fact sheet and see, in "
                  "plain words, what the fund is, what it charges each year (in dollars too, "
                  "at what you put in each month), whether it follows an index, what it "
                  "holds and when it started - with a line on what each one means. Nothing "
                  "you paste is kept, and no AI reads it. It's beside the Free money check "
                  "on Plan. Fact sheets only for now: account statements aren't read.",
          "flag": "decoder_factsheet"},
     ]},
    {"date": "2026-10-06", "title": "Find a guide: how advisors are paid",
     "items": [
         {"text": "Find a guide now explains, in plain words, the usual ways advisors are paid "
                  "- a flat fee or one-time review, by the hour, a subscription, a share of "
                  "what they manage, or commissions - with questions you can ask any advisor "
                  "and links to the official places to look them up.", "flag": "directory"},
         {"text": "An advisor's listing can say whether they offer a one-time review, and its "
                  "price as they state it. You'd pay the advisor directly; Northwend takes no "
                  "part of it.", "flag": "directory"},
         {"text": "Once you've finished Learn or set a goal, Learn and Plan show one short "
                  "line, \"Want to talk with a financial advisor? Find a guide\". It's "
                  "entirely optional.",
          "flag": "directory"},
     ]},
    {"date": "2026-10-06", "title": "Trail Forks",
     "items": [
         {"text": "Trail Forks, on the Account page, has a checklist for big life events - "
                  "a new job, a layoff, a new baby, an inheritance, a divorce or the "
                  "death of a parent. Each one lists what changes, which papers to gather, "
                  "what to ask and who to ask, and which decisions can wait. It never tells "
                  "you what to do. You can mark the one that's happening to you and tick off "
                  "steps as you do them; only you see them.",
          "flag": "trail_forks"},
     ]},
    {"date": "2026-10-06", "title": "The four seasons",
     "items": [
         {"text": "Four times a year, Home now has a short guide to something that comes up "
                  "at that time of year: in January, this year's contribution limits and "
                  "what your funds' fees add up to; in April, your tax forms explained; in October and November, "
                  "open enrollment and health savings accounts; in December, your year in "
                  "review and a letter to future you. The card shows on Home during those "
                  "months - Not now hides it - and Learn has all four any time.",
          "flag": "seasons"},
     ]},
    {"date": "2026-10-06", "title": "What's new and Status, on northwend.app",
     "items": [
         "This list is now on the website too, at northwend.app/whats-new, for anyone "
         "curious about what's changed.",
         "A status page at northwend.app/status says whether the app is working as usual, "
         "with a dated list of past notices.",
     ]},
    {"date": "2026-10-06", "title": "Explain it to someone",
     "items": [
         {"text": "Explain it to someone, on the Account page, makes a private link that shows "
                  "a partner or family member your plan in plain words: your mix in "
                  "percentages, what you're investing for and roughly when, and whether "
                  "you're still learning or already investing - never an amount, a holding "
                  "or an account. You choose 7 or "
                  "30 days, your first name stays off unless you tick it, and you can turn a "
                  "link off at any time.", "flag": "explain_share"},
     ]},
    {"date": "2026-10-06", "title": "When each price is from",
     "items": [
         "Each price now says when it's from: a time, like 3:45 pm ET, while the market is "
         "open, or the day's closing price, like Oct 3 close, once the market has closed. "
         "You'll see it under a ticker's price, on your watchlist and in the Price as of "
         "column on Home.",
         {"text": "If a price ever looks wrong, tap Price look wrong? under it and pick what "
                  "seems wrong. It helps us check that price.", "flag": "price_report"},
     ]},
    {"date": "2026-10-06", "title": "A sealed envelope",
     "items": [
         {"text": "Once you've written what you'd do in a drop on the Plan's Stress test, you "
                  "can make it a sealed envelope: a one-page PDF of your own words and the day "
                  "you wrote them, to print, seal and open if the market ever drops a lot. "
                  "It has no numbers about your money, and it isn't saved anywhere.",
          "flag": "sealed_envelope"},
     ]},
    {"date": "2026-10-06", "title": "Preparedness drills",
     "items": [
         {"text": "A short drill on Home, once a week: a situation like a market drop, a job "
                  "loss, a raise or a windfall - set against your own mix and timeline, or "
                  "for practice if you're not investing yet. Tap what you'd think about first "
                  "and see what other people often consider. Nothing is graded, there's no right "
                  "answer on an investment choice, and a missed week costs nothing. Your "
                  "readiness map shows which situations you've rehearsed; only you see what "
                  "you tapped.", "flag": "drills"},
     ]},
    {"date": "2026-10-06", "title": "In plain words",
     "items": [
         {"text": "Home now describes your mix in one plain line above the allocation bars: "
                  "the shares in stocks, bonds and cash, how many holdings you have, and the "
                  "largest one's share. A description only, worked out the same way for "
                  "everyone.", "flag": "plain_summary"},
         {"text": "A glossary: \"What does this mean?\" sits beside the words on Home, the Fee "
                  "check, Income and Open your account, and Learn the basics lists every word "
                  "from A to Z.", "flag": "glossary"},
         "Your printable plan now ends with questions people often ask a licensed "
         "professional - the same list for everyone, for whenever you might want it.",
     ]},
    {"date": "2026-10-06", "title": "Lost & Found",
     "items": [
         {"text": "Lost & Found, under your account map on the Account page, shows the free, "
                  "official places to look for money you may have left behind: a 401(k) from "
                  "an old job, a state's unclaimed property, an old HSA or IRA, savings bonds. "
                  "If you find an old 401(k), it lays out the usual choices side by side, with "
                  "questions to ask - it never picks one for you. You can tick off the places "
                  "you've looked; only you see your list.", "flag": "lost_found"},
     ]},
    {"date": "2026-10-06", "title": "A new home: go.northwend.app",
     "items": [
         "Northwend now lives at go.northwend.app, on its own hosting with extra protection "
         "in front of it. Your account, holdings and settings are all exactly where you "
         "left them - you may just need to sign in once at the new address.",
         "The old address sends you to the new one for a while, so saved links keep working.",
     ]},
    {"date": "2026-10-06", "title": "Your say in sharing",
     "items": [
         "If you share your account with an advisor and haven't been asked about it in "
         "Northwend before, you'll see one short question the next time you sign in: keep "
         "sharing, or stop. Nothing changes if you keep sharing, and you can stop at any time "
         "from Your advisor.",
         "Advisors: Your clients now notes anyone who hasn't confirmed sharing yet.",
     ]},
    {"date": "2026-10-06", "title": "See when your advisor looks",
     "items": [
         "If you have an advisor, your Account page now shows when they looked at your "
         "account and which page they opened. Only you see this list.",
         "Agreeing to share your account with an advisor, and stopping, is now noted with "
         "the words you were shown. You'll find it under Your sharing record, and in your "
         "data download.",
         "Proposals, progress reports and messages from an advisor now say plainly whose "
         "advice it is: theirs, with their name and firm - not Northwend's.",
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
