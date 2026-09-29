"""Display names for broker accounts.

The broker's own account name ("Individual ...111") stays the key everywhere
in the database. A user can give any account a nickname ("Roth IRA"), stored
in `account_labels`; the dashboard swaps it in for display only.
"""

from __future__ import annotations

MAX_LEN = 40


def labels(conn, user_id: int) -> dict[str, str]:
    """{broker account name: nickname} for one user."""
    return {r["account"]: r["nickname"] for r in conn.execute(
        "SELECT account, nickname FROM account_labels WHERE user_id = ?", (user_id,))}


def set_label(conn, user_id: int, account: str, nickname: str | None) -> None:
    """Save a nickname, or clear it when `nickname` is blank."""
    nickname = (nickname or "").strip()[:MAX_LEN]
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
