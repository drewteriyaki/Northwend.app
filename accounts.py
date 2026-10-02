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
