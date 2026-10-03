"""Choosing a brokerage: the "Choose a brokerage" waypoint of Start investing
(views/get_started.py). Pure content, no Streamlit.

Education, not a recommendation: what to compare, then some well-known US
brokerages listed alphabetically as equals - each just its name and a link
to its own site. No fees, minimums or features are stated for any one of
them (they change, and can't be checked from here); people are sent to each
one's own site for what's current. Northwend isn't paid by any of them and
doesn't rank them - no broker is "primary".
"""

from __future__ import annotations

INTRO = ("A brokerage is the company that holds your account - where you buy funds and see "
         "what you own. Most people pick one and stay a long time, so it's worth comparing a "
         "few. Here's what to look at:")

# what to compare: (the thing, a line about it)
COMPARE = (
    ("Yearly and trading fees", "any yearly account fee, and what buying or selling costs. "
                                "Fund fees (expense ratios) are separate - they depend on the "
                                "funds you pick, not the brokerage."),
    ("Account minimums", "how much you need to open the account, if anything."),
    ("Fractional shares", "buying in dollar amounts, like $50 of a fund, instead of whole "
                          "shares."),
    ("The account types you need", "for example a Roth IRA for retirement, or a regular "
                                   "brokerage account for anything else - or both."),
    ("An easy app or website", "one you'll be comfortable opening every month."),
    ("Customer help", "phone, chat, or an office nearby if you'd like to talk to someone."),
)

# Some well-known US brokerages, alphabetically (a test keeps them in order):
# (name, its own site). Only the name and the link - never a fee, a minimum or
# a feature, which change and can't be checked from here.
BROKERAGES = (
    ("Charles Schwab", "https://www.schwab.com/"),
    ("E*TRADE", "https://us.etrade.com/"),
    ("Fidelity", "https://www.fidelity.com/"),
    ("Interactive Brokers", "https://www.interactivebrokers.com/"),
    ("Merrill Edge", "https://www.merrilledge.com/"),
    ("Robinhood", "https://robinhood.com/"),
    ("Vanguard", "https://investor.vanguard.com/"),
)

LIST_INTRO = "Some well-known US brokerages, in alphabetical order:"
OTHERS = ("Many others exist too - your bank, or your employer's 401(k) provider, may offer "
          "one as well.")
NOT_RANKED = "Northwend isn't paid by any of them and doesn't rank them."
CHECK_SITES = "Fees and features change - check each one's site for current fees."


def sort_key(name: str) -> str:
    """Alphabetical order, ignoring case and punctuation ("E*TRADE" as ETRADE)."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def site_name(url: str) -> str:
    """'https://www.schwab.com/' -> 'schwab.com' (what the link shows)."""
    host = url.split("//", 1)[-1].split("/", 1)[0]
    for prefix in ("www.", "us.", "investor."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def list_markdown() -> str:
    """The brokerages as a markdown list: each a link to its own site, in
    the order kept above (alphabetical)."""
    return "\n".join(f"- [{name.replace('*', chr(92) + '*')}]({url}) - {site_name(url)}"
                     for name, url in BROKERAGES)


def compare_markdown() -> str:
    """What to compare, as a markdown list ("$" escaped for Streamlit)."""
    return "\n".join(f"- **{thing}** - {line}" for thing, line in COMPARE).replace("$", r"\$")
