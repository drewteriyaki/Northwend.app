"""Per-account dashboard settings, stored in the database (`user_prefs`).

One JSON object per account: chosen Holdings columns, alert limits, hide
amounts, the performance series, the drift threshold. These used to live in
`.dashboard_prefs.<id>.json` files next to the app, which a hosted app loses
on every restart; `load()` still reads such a file once, the first time an
account has no saved row, so local settings carry over.
"""

from __future__ import annotations

import json


def load(conn, user_id: int, legacy_path: str | None = None) -> dict:
    row = conn.execute("SELECT data FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return _from_row(conn, user_id, row, legacy_path)


def load_many(conn, user_ids, legacy_path=None) -> dict:
    """load() for several accounts in one query: {user_id: settings}.
    `legacy_path`, if given, is a function of the account id (see load())."""
    ids = tuple(dict.fromkeys(user_ids))
    if not ids:
        return {}
    rows = {r["user_id"]: r for r in conn.execute(
        f"SELECT user_id, data FROM user_prefs WHERE user_id IN ({', '.join('?' for _ in ids)})",
        ids)}
    return {i: _from_row(conn, i, rows.get(i), legacy_path(i) if legacy_path else None)
            for i in ids}


def _from_row(conn, user_id: int, row, legacy_path: str | None) -> dict:
    if row is not None:
        try:
            data = json.loads(row["data"])
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    data = _read_legacy(legacy_path)
    if data:
        save(conn, user_id, data)
    return data


def save(conn, user_id: int, data: dict) -> None:
    conn.execute("INSERT INTO user_prefs (user_id, data) VALUES (?, ?) "
                 "ON CONFLICT (user_id) DO UPDATE SET data = excluded.data",
                 (user_id, json.dumps(data)))
    conn.commit()


def _read_legacy(path: str | None) -> dict:
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
