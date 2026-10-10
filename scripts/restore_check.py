"""Row counts for the restore drill (docs/RUNBOOK.md, "Quarterly restore
drill"; PLAN step 4.3, audit 1.6e): how many rows each of Northwend's tables
holds, so a restored Neon branch can be compared with the live one.

    python scripts/restore_check.py --db "<restored branch's connection string>"
    python scripts/restore_check.py --db "<restored>" --against "<live>"
    python scripts/restore_check.py --db ask --against ask

`ask` asks for the connection string without showing it, so it never lands
in the shell's history (PowerShell keeps every command line it's given).

Counts only - it never reads a row's contents, so nobody looks at anyone's
holdings to check a restore. It only reads: the Postgres session is read-only
and a SQLite file is opened read-only, and unlike everything else that
connects it never sets the schema up (no portfolio.connect). The connection
string is never printed (it holds the database password).

The tables are every table in schema_pg.sql, so a new table is counted
without a change here. One missing from a database shows as "missing".
With --against, each table's difference is shown (the live branch usually
has a few more rows than one restored from an hour ago - the drill's "give
or take the last hour"); judging it is the person's. The difference is the
second database's count minus the first's, so "+3" means live has 3 more
rows. Tables with FEWER rows in the second are listed again at the end, to
look at: in a drill (a branch from an hour ago against live) that should
only be a few deletions from the last hour. Exit code: 1 when a table is
missing from either database, else 0.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from urllib.parse import urlsplit

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import pgcompat  # noqa: E402

SCHEMA_PG = os.path.join(REPO, "schema_pg.sql")


def tables(schema_path: str = SCHEMA_PG) -> list[str]:
    """Every table schema_pg.sql creates, in its order."""
    with open(schema_path, encoding="utf-8") as fh:
        text = fh.read()
    return re.findall(r"(?im)^\s*CREATE TABLE IF NOT EXISTS\s+([a-z_][a-z0-9_]*)", text)


def where(db: str) -> str:
    """A label for the database that never shows the password: the Postgres
    host and database name, or the SQLite file's name."""
    if pgcompat.is_postgres_dsn(db):
        parts = urlsplit(db)
        return f"{parts.hostname or 'localhost'}{parts.path or ''}"
    return os.path.basename(db)


def _sqlite_counts(path: str, names: list[str]) -> dict:
    if not os.path.isfile(path):
        raise SystemExit(f"No database file at {path}.")
    conn = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
    try:
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        # names come from schema_pg.sql (checked above), never from input
        return {t: (conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    if t in have else None) for t in names}
    finally:
        conn.close()


def _postgres_counts(dsn: str, names: list[str]) -> dict:
    import psycopg   # only needed for a Postgres database
    with psycopg.connect(dsn) as conn:
        conn.read_only = True   # this session can't write, whatever it's sent
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = current_schema()")
            have = {r[0] for r in cur.fetchall()}
            out = {}
            for t in names:
                if t in have:
                    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                    out[t] = cur.fetchone()[0]
                else:
                    out[t] = None
        conn.rollback()
    return out


def counts(db: str, names: list[str] | None = None) -> dict:
    """{table: row count, or None when the table isn't there}."""
    names = tables() if names is None else names
    if pgcompat.is_postgres_dsn(db):
        return _postgres_counts(db, names)
    return _sqlite_counts(db, names)


def report(first: dict, second: dict | None = None,
           labels: tuple[str, str] = ("restored", "live")) -> tuple[str, bool]:
    """The table of counts as text, and whether every table is there. With
    two databases, a last column says how far the second is from the first."""
    ok = True
    width = max([len(t) for t in first] + [5])

    def cell(n):
        return "missing" if n is None else f"{n:,}"

    if second is None:
        lines = [f"{'table':<{width}}  {'rows':>12}"]
        for t, n in first.items():
            ok = ok and n is not None
            lines.append(f"{t:<{width}}  {cell(n):>12}")
        return "\n".join(lines), ok
    lines = [f"{'table':<{width}}  {labels[0]:>12}  {labels[1]:>12}  difference"]
    for t, n in first.items():
        m = second.get(t)
        note = "same"
        if n is None or m is None:
            note = "missing"
            ok = False
        elif n != m:
            note = f"{m - n:+,}"
        lines.append(f"{t:<{width}}  {cell(n):>12}  {cell(m):>12}  {note}".rstrip())
    return "\n".join(lines), ok


def fewer(first: dict, second: dict) -> list[str]:
    """Tables with fewer rows in the second database than in the first."""
    return [t for t, n in first.items()
            if n is not None and second.get(t) is not None and second[t] < n]


def _ask(value: str | None, which: str) -> str | None:
    """`ask` -> the connection string, typed without being shown."""
    if value != "ask":
        return value
    import getpass
    return getpass.getpass(f"Connection string for {which} (not shown): ").strip()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Row counts of Northwend's tables, for the "
                                            "restore drill. Counts only; read-only.")
    p.add_argument("--db", required=True,
                   help="the database to count: a Postgres connection string, a SQLite "
                        "file, or `ask` to type it without it being shown")
    p.add_argument("--against",
                   help="a second database to compare with (for the drill: the live one); "
                        "`ask` works here too")
    args = p.parse_args(argv)
    args.db = _ask(args.db, "the restored branch")
    args.against = _ask(args.against, "the live branch")
    names = tables()
    first = counts(args.db, names)
    second = counts(args.against, names) if args.against else None
    print(f"Counting rows in {where(args.db)}"
          + (f" against {where(args.against)}" if args.against else "") + ".")
    text, ok = report(first, second)
    print(text)
    if second is None:
        print("All tables there." if ok else "A table is missing.")
    else:
        print("The difference is the second count minus the first: + means the second "
              "(live) has more rows.")
        lower = fewer(first, second)
        if lower:
            print("Fewer rows in the second than the first - look at these: "
                  + ", ".join(lower) + ".")
        print("Every table is in both. Differences should be only what changed since "
              "the restore point." if ok else "A table is missing from one of them.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
