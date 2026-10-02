"""Display names for broker accounts.

The broker's own account name ("Individual ...111") stays the key everywhere
in the database. A user can give any account a nickname ("Roth IRA"), stored
in `account_labels`; the dashboard swaps it in for display only.
"""

from __future__ import annotations

import re

MAX_LEN = 40

# An account number inside an account name: 5+ digits, possibly with a letter
# prefix and dashes or spaces ("Z12345678", "1234-5678"). 5, not 4, so a year
# in a name ("Brokerage 2024") is left alone.
_ACCOUNT_NUMBER_RE = re.compile(r"\b[A-Za-z]{0,3}\d[\d\- ]{3,}\d\b")


def mask_number(name: str | None) -> str | None:
    """An account name with any full account number cut to its last 3
    digits, the way Schwab already writes them: "Individual Z12345678" ->
    "Individual ...678". Names without one are unchanged. Applied to every
    snapshot when it's saved (portfolio.write_snapshot), whatever the source."""
    if not name:
        return name

    def cut(m):
        digits = re.sub(r"\D", "", m.group())
        return "..." + digits[-3:] if len(digits) >= 5 else m.group()
    return _ACCOUNT_NUMBER_RE.sub(cut, name)


# ---- a name for holdings that come without one ------------------------------ #
# A paste, a screenshot or an export with no account column doesn't say which
# account it is. The brokerage's name, when the text gives it away, makes a
# better suggestion than a made-up one. Listed alphabetically: none is treated
# differently, and an unknown brokerage just gets the neutral suggestion.
NEW_ACCOUNT = "Brokerage account"
_BROKERS = (
    ("Ally Invest", r"ally invest"), ("Betterment", r"betterment"),
    ("E*TRADE", r"e\s?\*\s?trade|etrade"), ("Empower", r"empower"),
    ("Fidelity", r"fidelity"), ("Firstrade", r"firstrade"),
    ("Interactive Brokers", r"interactive brokers|ibkr"), ("J.P. Morgan", r"j\.?\s?p\.? morgan"),
    ("Merrill", r"merrill"), ("Morgan Stanley", r"morgan stanley"), ("Public", r"public\.com"),
    ("Robinhood", r"robinhood"), ("Schwab", r"schwab"), ("SoFi", r"sofi"),
    ("tastytrade", r"tastytrade|tastyworks"), ("TIAA", r"tiaa"), ("Vanguard", r"vanguard"),
    ("Wealthfront", r"wealthfront"), ("Webull", r"webull"),
)
_BROKER_RES = [(name, re.compile(rf"(?<![a-z])(?:{pat})(?![a-z])", re.I)) for name, pat in _BROKERS]
# Column names only one brokerage's positions export uses (lower case).
_LAYOUTS = (
    ("E*TRADE", ("price paid $",)),
    ("Fidelity", ("cost basis total", "average cost basis")),
    ("Schwab", ("reinvest capital gains?",)),
    ("Schwab", ("cash & cash investments",)),
    ("Vanguard", ("investment name", "share price", "total value")),
)
# A fund or company's own name mentions brokerages all the time ("Vanguard
# S&P 500 ETF", "Fidelity 500 Index Fund", "Charles Schwab Corp"): a line with
# one of these words isn't read for the brokerage.
_SECURITY_WORDS = re.compile(
    r"\b(etf|etfs|fund|funds|fd|fds|index|idx|trust|admiral|adm|inv|investor|portfolio|corp|"
    r"corporation|inc|co|ltd|plc|holdings|group|class|cl|income|bond|bd|stock|stk|mkt|market|"
    r"money|treasury|dividend|equity|growth|value|sp|s&p|\d{3,})\b", re.I)


def guess_broker(text: str = "", *, header=(), filename: str = "") -> str | None:
    """The brokerage some pasted text or an export comes from, when it can be
    told - from a line naming it (not a fund's or a company's name), the
    file's name, or column names only one brokerage uses - else None. Only a
    suggestion for an account's name."""
    cells = " | ".join(str(c or "").strip().lower() for c in header)
    for name, cols in _LAYOUTS:
        if all(c in cells or c in (text or "").lower() for c in cols):
            return name
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln and len(ln) <= 80 and not _SECURITY_WORDS.search(ln)]
    for line in [filename or "", *lines]:
        for name, rx in _BROKER_RES:
            if rx.search(line):
                return name
    return None


def suggest_account(broker: str | None, existing, names: dict[str, str] | None = None) -> str:
    """The account a paste or a file without account names should go in: the
    one account already named after `broker` (its name or nickname - a new
    copy of the same holdings), else a new name no account has yet - the
    brokerage's, or "Brokerage account" - so two brokerages' holdings never
    land in one account unasked."""
    existing, names = [a for a in existing if a], names or {}
    if broker:
        rx = re.compile(rf"(?<![a-z]){re.escape(broker)}(?![a-z])", re.I)
        same = [a for a in existing if rx.search(a) or rx.search(names.get(a) or "")]
        if len(same) == 1:
            return same[0]
    base = broker or NEW_ACCOUNT
    taken = {a.casefold() for a in existing} | {(names.get(a) or "").casefold() for a in existing}
    if base.casefold() not in taken:
        return base
    n = 2
    while f"{base} {n}".casefold() in taken:
        n += 1
    return f"{base} {n}"


def labels(conn, user_id: int) -> dict[str, str]:
    """{broker account name: nickname} for one user."""
    return {r["account"]: r["nickname"] for r in conn.execute(
        "SELECT account, nickname FROM account_labels WHERE user_id = ?", (user_id,))}


def set_label(conn, user_id: int, account: str, nickname: str | None) -> None:
    """Save a nickname, or clear it when `nickname` is blank."""
    nickname = (nickname or "").strip()[:MAX_LEN]
    account = mask_number(account)  # the name as holdings are saved
    conn.execute("DELETE FROM account_labels WHERE user_id = ? AND account = ?",
                 (user_id, account))
    if nickname:
        conn.execute("INSERT INTO account_labels (user_id, account, nickname) VALUES (?, ?, ?)",
                     (user_id, account, nickname))
    conn.commit()


def display(account: str | None, names: dict[str, str]) -> str | None:
    """The nickname if there is one, else the broker's name unchanged."""
    if not account:
        return account
    return names.get(account) or account


def clash(account: str, nickname: str, accounts, names: dict[str, str]) -> str | None:
    """The other account already shown as `nickname`, if any. Two accounts
    with one display name would merge in every per-account breakdown."""
    want = (nickname or "").strip().casefold()
    if not want:
        return None
    for other in accounts:
        if other != account and (display(other, names) or "").casefold() == want:
            return other
    return None
