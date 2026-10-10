"""The database roles (docs/DB_ROLES.md, PLAN 4.6, audit 1.6c and 1.6f).

Three roles, and only one of them can change tables:
- the owner (Neon's own, e.g. `neondb_owner`): owns every table, runs
  `northwend-migrate` - by hand, from the owner's computer, and nowhere else;
- `northwend_app`, the app on Render: reads, adds, changes and deletes rows -
  no CREATE on the schema or the database, owns nothing, so no DDL;
- `northwend_jobs`, the scheduled jobs: the same rows as the app for now
  (the tidy deletes old accounts across many tables), with its own password.

On the append-only tables (portfolio.APPEND_ONLY_TABLES: consent records and
the advisor access log) the app may only add and read; the jobs keep DELETE
for the 7-year prunes and nothing else.

    northwend-migrate --db "<owner connection string>" --roles
    northwend-migrate --db "..." --roles --new-password northwend_app   (rotate)
    python db_roles.py --sql            # the SQL it runs, to read (no passwords)

Run it as the owner. It is safe to run again: a role that exists is left as it
is (and keeps its password); the grants are put back as they should be. A
role it makes gets a long random password, sent to Postgres once and printed
once, as a connection string, to the owner's terminal - never written to a
file or a log. After the grants it checks each role's real rights and says
what is wrong, if anything.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from urllib.parse import quote, urlsplit, urlunsplit

APP_ROLE = "northwend_app"
JOBS_ROLE = "northwend_jobs"
ROLES = (APP_ROLE, JOBS_ROLE)

# What both roles get on every table and id counter, now and later.
TABLE_RIGHTS = ("SELECT", "INSERT", "UPDATE", "DELETE")
SEQUENCE_RIGHTS = ("USAGE", "SELECT")
# Never on a table: emptying it in one go, foreign keys to it, triggers on it.
NEVER_ON_TABLES = ("TRUNCATE", "REFERENCES", "TRIGGER")
# What every role is made without (CREATE ROLE's defaults, said out loud).
ROLE_ATTRIBUTES = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"

_NAME = re.compile(r"[a-z_][a-z0-9_]*")


def _ident(name: str) -> str:
    """A quoted SQL identifier (role, schema or database name)."""
    return '"' + name.replace('"', '""') + '"'


def _role_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name) or len(name) > 63:
        raise ValueError(f"not a role name this command makes: {name!r}")
    return name


def statements(owner: str, database: str, schema: str = "public",
               roles: tuple[str, str] = ROLES) -> list[str]:
    """The SQL, one statement per item, in order. Every one is safe to run
    again: the roles are made only if missing (a DO block), GRANT and REVOKE
    of what is already so change nothing. The append-only tables' revokes
    (portfolio._append_only_grants) run after these, as with every migrate."""
    app, jobs = (_role_name(r) for r in roles)
    both = f"{_ident(app)}, {_ident(jobs)}"
    s, db, own = _ident(schema), _ident(database), _ident(owner)
    out = []
    for role in (app, jobs):
        out.append(
            "DO $roles$ BEGIN "
            f"IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN "
            f"CREATE ROLE {_ident(role)} WITH {ROLE_ATTRIBUTES}; "
            "END IF; END $roles$")
    out += [
        # nobody but the owner makes anything in the schema (Postgres 15 and
        # later already say so for public; this makes sure), or a new schema
        f"REVOKE CREATE ON SCHEMA {s} FROM PUBLIC",
        f"REVOKE CREATE ON SCHEMA {s} FROM {both}",
        f"REVOKE CREATE ON DATABASE {db} FROM {both}",
        f"GRANT CONNECT ON DATABASE {db} TO {both}",
        f"GRANT USAGE ON SCHEMA {s} TO {both}",
        # every table and id counter there now...
        f"GRANT {', '.join(TABLE_RIGHTS)} ON ALL TABLES IN SCHEMA {s} TO {both}",
        f"REVOKE {', '.join(NEVER_ON_TABLES)} ON ALL TABLES IN SCHEMA {s} FROM {both}",
        f"GRANT {', '.join(SEQUENCE_RIGHTS)} ON ALL SEQUENCES IN SCHEMA {s} TO {both}",
        # ...and every one the owner (northwend-migrate) makes later
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {own} IN SCHEMA {s} "
        f"GRANT {', '.join(TABLE_RIGHTS)} ON TABLES TO {both}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {own} IN SCHEMA {s} "
        f"REVOKE {', '.join(NEVER_ON_TABLES)} ON TABLES FROM {both}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {own} IN SCHEMA {s} "
        f"GRANT {', '.join(SEQUENCE_RIGHTS)} ON SEQUENCES TO {both}",
    ]
    return out


def append_only_revokes(roles: tuple[str, str] = ROLES) -> dict[str, str]:
    """portfolio.APPEND_ONLY_REVOKES for these role names (the tests use
    their own names; the live database uses ROLES)."""
    import portfolio
    app, jobs = roles
    return {app: portfolio.APPEND_ONLY_REVOKES[APP_ROLE],
            jobs: portfolio.APPEND_ONLY_REVOKES[JOBS_ROLE]}


def script(owner: str = "neondb_owner", database: str = "neondb", schema: str = "public",
           roles: tuple[str, str] = ROLES) -> str:
    """Every statement setup() runs, as one script to read (no passwords)."""
    import portfolio
    lines = [s + ";" for s in statements(owner, database, schema, roles)]
    for role, rights in append_only_revokes(roles).items():
        lines.append(f"REVOKE {rights} ON {', '.join(portfolio.APPEND_ONLY_TABLES)} "
                     f"FROM {_ident(role)};")
    return "\n".join(lines) + "\n"


def new_password() -> str:
    """A long random password: 192 bits, letters, digits, - and _ only (safe
    inside a SQL literal and a URL; well over Neon's 60-bit minimum)."""
    return secrets.token_urlsafe(24)


def connection_string(dsn: str, role: str, password: str) -> str:
    """The owner's connection string with the role and its password in place
    of the owner's: the same host, database and options."""
    parts = urlsplit(dsn)
    host = parts.netloc.rsplit("@", 1)[-1]
    netloc = f"{quote(role, safe='')}:{quote(password, safe='')}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def check(conn, schema: str, database: str, roles: tuple[str, str] = ROLES) -> list[str]:
    """What is wrong with the roles' real rights, in words ([] = all right):
    each logs in, is no superuser and can make no roles or databases, belongs
    to no other role, can't create in the schema or the database, owns no
    table, has every row right on every table and sequence (but TRUNCATE on
    none), and on the append-only tables only what it should."""
    import portfolio
    problems = []
    revokes = append_only_revokes(roles)
    for role in roles:
        row = conn.execute(
            "SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolreplication, "
            "rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = ?", (role,)).fetchone()
        if row is None:
            problems.append(f"{role}: doesn't exist")
            continue
        if not row["rolcanlogin"]:
            problems.append(f"{role}: can't log in")
        for attr, word in (("rolsuper", "is a superuser"), ("rolcreaterole", "can make roles"),
                           ("rolcreatedb", "can make databases"),
                           ("rolreplication", "has REPLICATION"),
                           ("rolbypassrls", "has BYPASSRLS")):
            if row[attr]:
                problems.append(f"{role}: {word}")
        for m in conn.execute(
                "SELECT g.rolname FROM pg_catalog.pg_auth_members a "
                "JOIN pg_catalog.pg_roles g ON g.oid = a.roleid "
                "JOIN pg_catalog.pg_roles u ON u.oid = a.member WHERE u.rolname = ? "
                "ORDER BY g.rolname", (role,)).fetchall():
            problems.append(f"{role}: is a member of {m['rolname']} (made on Neon's Roles "
                            "page? it should be made by this command)")
        on = conn.execute(
            "SELECT has_schema_privilege(CAST(? AS name), CAST(? AS text), 'CREATE') AS mk, "
            "has_schema_privilege(CAST(? AS name), CAST(? AS text), 'USAGE') AS use, "
            "has_database_privilege(CAST(? AS name), CAST(? AS text), 'CREATE') AS db",
            (role, schema, role, schema, role, database)).fetchone()
        if on["mk"]:
            problems.append(f"{role}: can create in schema {schema}")
        if not on["use"]:
            problems.append(f"{role}: no USAGE on schema {schema}")
        if on["db"]:
            problems.append(f"{role}: can create schemas in database {database}")
        owned = [r["tablename"] for r in conn.execute(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = ? AND tableowner = ?",
            (schema, role)).fetchall()]
        if owned:
            problems.append(f"{role}: owns {', '.join(owned)}")
        taken = {t: {r.strip() for r in revokes[role].split(",")}
                 for t in portfolio.APPEND_ONLY_TABLES}
        # every right on every table in one query (Neon: one round trip each)
        rights = TABLE_RIGHTS + NEVER_ON_TABLES
        cols = ", ".join(f"has_table_privilege(CAST(? AS name), c.oid, '{r}') AS r{i}"
                         for i, r in enumerate(rights))
        for row in conn.execute(
                f"SELECT c.relname AS t, {cols} FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = ? AND c.relkind IN ('r', 'p') ORDER BY c.relname",
                (*(role for _ in rights), schema)).fetchall():
            for i, right in enumerate(rights):
                has = row[f"r{i}"]
                should = right in TABLE_RIGHTS and right not in taken.get(row["t"], set())
                if has and not should:
                    problems.append(f"{role}: has {right} on {row['t']}")
                elif should and not has:
                    problems.append(f"{role}: no {right} on {row['t']}")
        cols = ", ".join(f"has_sequence_privilege(CAST(? AS name), c.oid, '{r}') AS r{i}"
                         for i, r in enumerate(SEQUENCE_RIGHTS))
        for row in conn.execute(
                f"SELECT c.relname AS s, {cols} FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = ? AND c.relkind = 'S' ORDER BY c.relname",
                (*(role for _ in SEQUENCE_RIGHTS), schema)).fetchall():
            for i, right in enumerate(SEQUENCE_RIGHTS):
                if not row[f"r{i}"]:
                    problems.append(f"{role}: no {right} on sequence {row['s']}")
    return problems


def setup(conn, dsn: str, *, roles: tuple[str, str] = ROLES,
          new_passwords: tuple[str, ...] = ()) -> dict:
    """Make the roles and their grants on a Postgres database, as its owner,
    in one transaction (committed). A role made now - or named in
    `new_passwords` - gets a new random password. Returns {"owner", "roles",
    "created": [roles made now], "strings": {role: connection string with its
    new password}, "problems": check()'s list}."""
    import portfolio
    roles = tuple(_role_name(r) for r in roles)
    for r in new_passwords:
        if r not in roles:
            raise ValueError(f"--new-password: {r!r} isn't one of {', '.join(roles)}")
    here = conn.execute("SELECT current_user AS owner, current_database() AS db, "
                        "current_schema() AS schema").fetchone()
    owner, database, schema = here["owner"], here["db"], here["schema"]
    if owner in roles:
        raise PermissionError(f"connected as {owner}: run this as the database's owner role "
                              "(its connection string), not the app's or the jobs'")
    if schema is None:
        raise RuntimeError("no current schema: check the connection string's search_path")
    before = {r["rolname"] for r in conn.execute(
        "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname IN (?, ?)", roles).fetchall()}
    try:
        for stmt in statements(owner, database, schema, roles):
            conn.execute(stmt)
        portfolio._append_only_grants(conn, append_only_revokes(roles))
        created = [r for r in roles if r not in before]
        strings = {}
        for role in roles:
            if role in created or role in new_passwords:
                pw = new_password()
                assert re.fullmatch(r"[A-Za-z0-9_-]+", pw)
                conn.execute(f"ALTER ROLE {_ident(role)} WITH PASSWORD '{pw}'")
                strings[role] = connection_string(dsn, role, pw)
        problems = check(conn, schema, database, roles)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"owner": owner, "roles": list(roles), "created": created, "strings": strings,
            "problems": problems}


def report(done: dict, out=None) -> int:
    """setup()'s result in words, for the owner's terminal. 0 if all is well."""
    out = out or sys.stdout
    print(f"Database roles, set up as {done['owner']}:", file=out)
    for role in done["roles"]:
        state = "made now" if role in done["created"] else "already there"
        print(f"  {role}: {state}", file=out)
    if done["strings"]:
        print("\nNew connection strings - shown this once. Put each straight where it "
              "goes (docs/DB_ROLES.md, \"Where each connection string goes\") and into "
              "your password manager; don't save "
              "them in a file. Close this window afterwards.", file=out)
        for role, text in done["strings"].items():
            print(f"\n  {role}:\n  {text}", file=out)
        print(file=out)
    kept = [r for r in done["roles"] if r not in done["strings"]]
    if kept:
        print("Kept their passwords: " + ", ".join(kept) + " (add --new-password <role> "
              "to make a new one).", file=out)
    if done["problems"]:
        print("\nNot right yet:", file=out)
        for p in done["problems"]:
            print(f"  - {p}", file=out)
        return 1
    print("Checked: each can read and write rows, and neither can create, change or drop "
          "a table; consent records and the access log are add-only for the app.", file=out)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Print the SQL that `northwend-migrate --roles` "
                                            "runs (docs/DB_ROLES.md). To run it, use that.")
    p.add_argument("--sql", action="store_true", help="print the SQL (no passwords)")
    p.add_argument("--owner", default="neondb_owner", help="the owner role's name")
    p.add_argument("--database", default="neondb", help="the database's name")
    p.add_argument("--schema", default="public")
    args = p.parse_args(argv)
    if not args.sql:
        p.print_help()
        return 2
    sys.stdout.write(script(args.owner, args.database, args.schema))
    return 0


if __name__ == "__main__":
    sys.exit(main())
