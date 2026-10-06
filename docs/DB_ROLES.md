# Database roles: least privilege

PLAN step 4.6, audit 1.6c. Today the app, the scheduled jobs and
`northwend-migrate` all connect to Neon as the database's owner role, which
can create, change and drop every table. Someone who got the app's
connection string could delete everything in one line. After this page there
are three roles, and only one of them can change tables - and that one never
sits in the app or in GitHub.

| Role | Used by | Can | Can't |
|---|---|---|---|
| Owner (Neon's own, usually `neondb_owner`) | `northwend-migrate` only, run by hand by the owner | Everything: create, change and drop tables | - (so it lives only in the owner's password manager) |
| `northwend_app` | The app on Render (`PORTFOLIO_DB`) | Read, add, change and delete rows | Create, change or drop any table |
| `northwend_jobs` | The GitHub jobs (`DATABASE_URL`) | The same rows as the app, for now | The same |

The jobs need nearly the app's rights today (the price jobs write prices,
the nightly tidy deletes old accounts across many tables). They get their
own role anyway: their own password, rotated on its own; Neon shows which
role is connected; and they can be narrowed later without touching the app.

Values in angle brackets come from you; none of them goes in this repo. The
owner's role and database names are in its connection string:
`postgresql://<owner role>@<host>/<database>`. The SQL below uses Neon's
defaults, `neondb_owner` and `neondb` - change them if yours differ.

Contents:
- [0. Before you start](#0-before-you-start)
- [1. Create the roles](#1-create-the-roles)
- [2. Check the roles](#2-check-the-roles)
- [3. Switch staging](#3-switch-staging)
- [4. Switch live](#4-switch-live)
- [5. Put the owner away](#5-put-the-owner-away)
- [Schema changes from now on](#schema-changes-from-now-on)
- [Consent and access-log tables (1.6f)](#consent-and-access-log-tables-16f)
- [Undo](#undo)

---

## 0. Before you start

- The code with `NORTHWEND_SKIP_SCHEMA_SETUP` is live (it is from the release
  that added this page). It's off unless set, so nothing changes until step 3.
- Do everything on staging's Neon project first, then on live's.
- Make two passwords, one per role, and keep them in your password manager:
  `python -c "import secrets; print(secrets.token_urlsafe(24))"`

## 1. Create the roles

Neon console > the project > **SQL Editor**, on the main branch, connected as
the owner role (the editor's default). Paste, put in the two passwords, run:

```sql
-- The app: rows only. The scheduled jobs: rows only (the same, for now).
CREATE ROLE northwend_app WITH LOGIN PASSWORD '<app password>';
CREATE ROLE northwend_jobs WITH LOGIN PASSWORD '<jobs password>';

-- Nobody but the owner makes anything in the schema (already the default
-- on Postgres 15 and later; this makes sure).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT CONNECT ON DATABASE neondb TO northwend_app, northwend_jobs;
GRANT USAGE ON SCHEMA public TO northwend_app, northwend_jobs;

-- Every table and id counter there now...
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
  TO northwend_app, northwend_jobs;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO northwend_app, northwend_jobs;

-- ...and every one northwend-migrate adds later (it runs as the owner).
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO northwend_app, northwend_jobs;
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO northwend_app, northwend_jobs;
```

Create them in SQL, not on Neon's Roles page: roles made there join
`neon_superuser`, which is more than these need.

## 2. Check the roles

Each role's connection string is the owner's with the role name and password
swapped: Neon > **Connect** > copy the pooled connection string, then replace
`neondb_owner:<owner password>` with `northwend_app:<app password>` (and the
same for jobs). Keep the host, database and `?sslmode=require` as they are.

For each of the two strings, in a terminal:

```
psql "<app connection string>"
SELECT current_user;                -- northwend_app
SELECT COUNT(*) FROM users;         -- a number: it can read
CREATE TABLE role_check (x int);    -- ERROR: permission denied for schema public
SELECT tablename FROM pg_tables
 WHERE schemaname = 'public' AND tableowner = current_user;   -- (0 rows)
```

If `CREATE TABLE role_check` works, stop: run `DROP TABLE role_check;`, and
check step 1's `REVOKE` ran. Then also:
`python scripts/restore_check.py --db "<app connection string>"` lists every
table with a count and no "missing" (it can read each one).

## 3. Switch staging

The order matters: first tell the app not to set the schema up, then take its
right to.

1. Staging's Streamlit Secrets: `NORTHWEND_SKIP_SCHEMA_SETUP = "1"`. Save,
   wait for the reboot, sign in. Nothing looks different.
2. Then `PORTFOLIO_DB` = staging's `northwend_app` string. Save, sign in, open
   a few pages, save a small change (a watchlist ticker), Admin > System.
3. If the page says "Something went wrong" and the log shows
   `SchemaNotReady`, run `northwend-migrate` against staging (see below) and
   reload.

## 4. Switch live

The same order, in Render and GitHub:

1. `render.yaml`: `NORTHWEND_SKIP_SCHEMA_SETUP` value `"1"`. A one-line
   change, through staging and released like any other (setting it only in
   Render's Environment would be undone by the next Blueprint sync).
   Render redeploys; the app still uses the owner's string and only checks
   the schema's version.
2. Render > the service > **Environment**: `PORTFOLIO_DB` = live's
   `northwend_app` string. Save (Render redeploys). Sign in and look around.
3. GitHub > Settings > Secrets and variables > Actions > **Variables** >
   New repository variable: `NORTHWEND_SKIP_SCHEMA_SETUP` = `1`. (The
   Scheduled sync workflow passes it to every job.)
4. Then **Secrets**: `DATABASE_URL` = live's `northwend_jobs` string.
5. Actions > Scheduled sync > **Run workflow**. Every job is green.

## 5. Put the owner away

Neon > the project > **Roles** > `neondb_owner` > **Reset password**. Every
old copy of the owner's string stops working: Community Cloud's secrets, the
old GitHub secret, anything pasted earlier. Keep the new one in your password
manager only, for `northwend-migrate`. Do the same on staging's project.

The old Community Cloud app needs no database at all once `MOVED_TO` is set
(its "has moved" page comes before anything connects): delete its other
secrets (RUNBOOK, Move to Render).

## Schema changes from now on

The app and the jobs no longer create tables or columns. `northwend-migrate`
does, as the owner, before the code that needs them arrives. Old code runs
fine on a newer schema, so: **migrate first, release second.**

A release changes the schema when `SCHEMA_VERSION` in `portfolio.py` goes up:

```
git diff origin/main staging -- portfolio.py | grep SCHEMA_VERSION
```

When it does:

1. Before pushing to `staging`: run it on staging's database.
2. Before `git push origin staging:main`: run it on live's.

```
northwend-migrate --db "<owner connection string>"
```

(or `python portfolio.py migrate --db "..."`). It prints the version it
reached. Paste the string only into that command - never into a file. In
PowerShell: `$env:OWNER_DB = "<owner connection string>"`, then
`northwend-migrate --db $env:OWNER_DB`, and close the window afterwards.

If it was forgotten, nothing is damaged: the app stops with a message naming
both versions ("The database's schema is at version 2; this code needs
version 3 ... run northwend-migrate"), which shows in Render's Logs, and the
next scheduled job fails and emails you. Run the migrate; the app picks it
up on the next page load, without a restart.

## Consent and access-log tables (1.6f)

Step 5 adds two tables that must only ever grow: `consent_records`
(`consent.py`) and `advisor_access_log` (`access_log.py`), kept 7 years (B6).
The default privileges above would let the app change or delete their rows,
so every schema setup - `northwend-migrate`, as the owner - takes that back
(`portfolio._append_only_grants`, only for the roles that exist - none on
local copies or in CI). In SQL it is:

```sql
REVOKE UPDATE, DELETE, TRUNCATE ON consent_records, advisor_access_log FROM northwend_app;
REVOKE UPDATE, TRUNCATE ON consent_records, advisor_access_log FROM northwend_jobs;
```

The app role then has `INSERT, SELECT` only on them. The jobs role keeps
`DELETE` for one thing: the nightly `northwend-tidy` runs the 7-year prunes
(`consent.prune`, `access_log.prune`) as `northwend_jobs`. If the roles are
made after the migrate that added the tables (SCHEMA_VERSION 3), run
`northwend-migrate` once more - or the two lines above, as the owner.
`tests/test_postgres.py` (`ConsentAccessTests`) checks that an `UPDATE` or
`DELETE` as an app-like role fails and an `INSERT` works.

## Undo

Set `PORTFOLIO_DB` (Render) and `DATABASE_URL` (GitHub) back to the owner's
string, and `NORTHWEND_SKIP_SCHEMA_SETUP` back to `0` / unset. The roles can
stay. To remove them later, as the owner:
`DROP OWNED BY northwend_app, northwend_jobs; DROP ROLE northwend_app, northwend_jobs;`
(they own nothing, so this only drops their grants).
