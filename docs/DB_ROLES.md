# Database roles: least privilege

PLAN step 4.6, audit 1.6c. Until this page is done, the app, the scheduled
jobs and `northwend-migrate` all connect to Neon as the database's owner
role, which can create, change and drop every table. Someone who got the
app's connection string could delete everything in one line. After it there
are three roles, and only one of them can change tables - and that one never
sits in the app, in Render or in GitHub.

| Role | Used by | Can | Can't |
|---|---|---|---|
| Owner (Neon's own, usually `neondb_owner`) | `northwend-migrate` only, run by hand by you | Everything: create, change and drop tables | - (so it lives only in your password manager) |
| `northwend_app` | The app (Render's web service `PORTFOLIO_DB`; staging's Streamlit Secrets) | Read, add, change and delete rows | Create, change or drop any table, schema or role; change or delete a consent record or an access-log row |
| `northwend_jobs` | The scheduled jobs (Render's two cron jobs' `PORTFOLIO_DB`, GitHub's `DATABASE_URL`) | The same rows as the app, and the 7-year prunes of consent records and the access log | The same as the app, except those prunes |

The jobs need nearly the app's rights today (the price jobs write prices,
the nightly tidy deletes old accounts across many tables). They get their
own role anyway: their own password, rotated on its own; Neon shows which
role is connected; and they can be narrowed later without touching the app.

The owner stays the owner: it already owns every table, so it is the one
that changes them (`northwend-migrate`). There is no separate "migrate" role
to make.

Contents:
- [What the command does](#what-the-command-does)
- [0. Before you start](#0-before-you-start)
- [1. Staging: run the migration](#1-staging-run-the-migration)
- [2. Staging: check the roles](#2-staging-check-the-roles)
- [3. Staging: switch to the roles](#3-staging-switch-to-the-roles)
- [4. Live: the same, in Render and GitHub](#4-live-the-same-in-render-and-github)
- [5. Put the owner away](#5-put-the-owner-away)
- [Where each connection string goes](#where-each-connection-string-goes)
- [Schema changes from now on](#schema-changes-from-now-on)
- [A new password for a role](#a-new-password-for-a-role)
- [Consent and access-log tables (1.6f)](#consent-and-access-log-tables-16f)
- [Undo](#undo)

---

## What the command does

```
northwend-migrate --db "<owner connection string>" --roles
```

(or `python portfolio.py migrate --db "..." --roles`). First the usual
migrate: the schema up to this code's `SCHEMA_VERSION`. Then, in one
transaction (`db_roles.py`):

- makes `northwend_app` and `northwend_jobs` if they aren't there - `LOGIN`,
  and no superuser, `CREATEDB`, `CREATEROLE`, `REPLICATION` or `BYPASSRLS`;
- `REVOKE CREATE` on the schema (from everyone but the owner) and on the
  database (no new schemas) - so neither role can make a table;
- `SELECT, INSERT, UPDATE, DELETE` on every table, `USAGE, SELECT` on every
  id counter (sequence) - never `TRUNCATE`, `REFERENCES` or `TRIGGER`;
- `ALTER DEFAULT PRIVILEGES` for the owner, so every table and counter a
  later `northwend-migrate` makes gets the same rights by itself;
- the consent and access-log revokes ([below](#consent-and-access-log-tables-16f));
- then checks each role's real rights in the database and lists anything
  that isn't right under "Not right yet" (and ends with an error code).

It is safe to run again, as often as you like: a role that exists keeps its
password, and the grants are put back as they should be. To read the SQL
without running anything: `python db_roles.py --sql` (Neon's default names;
`--owner` and `--database` for others).

**Passwords.** A role the command makes gets a long random password
(192 bits), sent to Neon once and printed once to your terminal, as the
role's full connection string (the owner's with the role and password
swapped: same host, database and options). Nothing is written to a file or
the repo, and nothing has to be typed or invented. Why not set them in Neon's
console? Roles made on Neon's Roles page join `neon_superuser`, which is far
more than these need (the check says so if one did); roles made in SQL are
plain. Copy each string straight to where it goes and into your password
manager, then close the window. Lost one? Make a new one
([A new password for a role](#a-new-password-for-a-role)).

---

## 0. Before you start

- [ ] The release with `db_roles.py` is live (`northwend-migrate --help` shows
      `--roles`). Run it from your computer, in the project folder, after
      `git checkout staging && git pull` (`pip install -e .` once gives the
      `northwend-*` commands; or use `python portfolio.py migrate ...`).
- [ ] The owner's connection strings for staging's and live's Neon projects
      (Neon > the project > **Connect**, role `neondb_owner`). Paste them
      only into the command - never into a file. In PowerShell:
      `$env:OWNER_DB = "<owner connection string>"`, then use `$env:OWNER_DB`,
      and close the window afterwards.
- [ ] Staging first, everything, then live. Each Neon project gets its own
      two roles with their own passwords.

## 1. Staging: run the migration

```
northwend-migrate --db $env:OWNER_DB --roles
```

It prints the schema's version, `northwend_app: made now`,
`northwend_jobs: made now`, the two new connection strings, and
"Checked: ...". Save both strings in your password manager now, named
"Northwend staging - app role" and "... - jobs role".

If it says "Not right yet", read the list: usually a role that already
existed with more rights (made on Neon's Roles page). Delete that role in
Neon's console, run the command again.

## 2. Staging: check the roles

With the app string, in a terminal (`psql "<app connection string>"`):

```
SELECT current_user;                -- northwend_app
SELECT COUNT(*) FROM users;         -- a number: it can read
CREATE TABLE role_check (x int);    -- ERROR: permission denied for schema public
UPDATE consent_records SET kind = kind;   -- ERROR: permission denied
```

No psql? The same check without it - the app as the app role, the tidy as
the jobs role, neither allowed to set the schema up:

```
$env:NORTHWEND_SKIP_SCHEMA_SETUP = "1"
python scripts/restore_check.py --db "<app connection string>"
northwend-tidy --db "<jobs connection string>"
```

`restore_check.py` lists every table with a count and no "missing"; the tidy
(the nightly retention clean-up, run once by hand) prints what it removed and
no error. Close the window.

## 3. Staging: switch to the roles

Staging's Streamlit app > Settings > **Secrets**, both in one save:

```
NORTHWEND_SKIP_SCHEMA_SETUP = "1"
PORTFOLIO_DB = "<staging app connection string>"
```

Wait for the reboot, sign in, open a few pages, save a small change (a
watchlist ticker), Admin > System. Nothing looks different. Staging has no
scheduled jobs: its jobs string is only for checks like step 2.

If the page says "Something went wrong" and the log shows `SchemaNotReady`,
run step 1's command again (it migrates first) and reload.

## 4. Live: the same, in Render and GitHub

1. [ ] `northwend-migrate --db $env:OWNER_DB --roles` with **live's** owner
       string. Save the two strings ("Northwend live - app role", "... -
       jobs role").
2. [ ] Step 2's check with live's strings.
3. [ ] Render > the `northwend` web service > **Environment**: set
       `NORTHWEND_SKIP_SCHEMA_SETUP` to `1` and `PORTFOLIO_DB` to the live
       **app** string, then **Save, rebuild and deploy** (one deploy). Sign
       in and look around; Render > Logs shows no errors.
4. [ ] Render > `northwend-prices` > **Environment**: the same two, with the
       live **jobs** string. Save. The same on `northwend-news`. On each,
       **Trigger Run**: it ends green.
5. [ ] GitHub > Settings > Secrets and variables > Actions > **Variables** >
       New repository variable: `NORTHWEND_SKIP_SCHEMA_SETUP` = `1` (the
       Scheduled sync workflow passes it to every job).
6. [ ] Then **Secrets** > `DATABASE_URL` > Update: the live **jobs** string.
7. [ ] Actions > Scheduled sync > **Run workflow**. Every job is green.

If the live app is still on Streamlit Community Cloud when you do this (the
move to Render not yet done), step 3 is its Secrets instead, as in step 3
for staging; Render gets the same values when it is set up.

## 5. Put the owner away

Neon > the project > **Roles** > `neondb_owner` > **Reset password**. Every
old copy of the owner's string stops working: Community Cloud's secrets, the
old GitHub secret, anything pasted earlier. Keep the new one in your password
manager only, for `northwend-migrate`. Do the same on staging's project.

The old Community Cloud app needs no database at all once `MOVED_TO` is set
(its "has moved" page comes before anything connects): delete its other
secrets (RUNBOOK, Move to Render).

## Where each connection string goes

| String | Goes in | Never in |
|---|---|---|
| Live owner (`neondb_owner`) | Your password manager; pasted into `northwend-migrate` only | Render, GitHub, Streamlit, any file |
| Live `northwend_app` | Render web service `northwend`: `PORTFOLIO_DB` | GitHub; the cron jobs |
| Live `northwend_jobs` | Render cron jobs `northwend-prices` and `northwend-news`: `PORTFOLIO_DB`; GitHub secret `DATABASE_URL` | The web service |
| Staging owner | Password manager; `northwend-migrate` against staging | Anywhere else |
| Staging `northwend_app` | Staging's Streamlit Secrets: `PORTFOLIO_DB` | Render, GitHub |
| Staging `northwend_jobs` | Password manager (checks by hand) | Anywhere live |

`NORTHWEND_SKIP_SCHEMA_SETUP` is `1` beside every app or jobs string (Render
web and crons, the GitHub variable, staging's Secrets), and unset only where
the owner's string is used.

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
northwend-migrate --db $env:OWNER_DB --roles
```

It prints the version it reached and checks the roles again (new tables get
the roles' rights by themselves - the default privileges - and the check
confirms it). Without `--roles` it only migrates, which is also fine.

If it was forgotten, nothing is damaged: the app stops with a message naming
both versions ("The database's schema is at version 12; this code needs
version 13 ... run northwend-migrate"), which shows in Render's Logs, and the
next scheduled job fails and emails you. Run the migrate; the app picks it
up on the next page load, without a restart.

## A new password for a role

If a string may have leaked, or as part of [Rotate a key](RUNBOOK.md#rotate-a-key):

```
northwend-migrate --db $env:OWNER_DB --roles --new-password northwend_app
```

(`--new-password northwend_jobs` for the jobs; both flags for both). It
prints the role's new string once. The old password stops at once, so put
the new string in every place from the table above right away, at a quiet
hour: for the app role the web service is down until it's in; for the jobs
role a run in between fails and emails you.

## Consent and access-log tables (1.6f)

Two tables must only ever grow: `consent_records` (`consent.py`) and
`advisor_access_log` (`access_log.py`), kept 7 years (B6). The table grants
above would let the app change or delete their rows, so every schema setup -
`northwend-migrate`, as the owner, with or without `--roles` - takes that
back (`portfolio._append_only_grants`, only for the roles that exist - none
on local copies or in CI):

```sql
REVOKE UPDATE, DELETE, TRUNCATE ON consent_records, advisor_access_log FROM northwend_app;
REVOKE UPDATE, TRUNCATE ON consent_records, advisor_access_log FROM northwend_jobs;
```

The app role then has `INSERT, SELECT` only on them. The jobs role keeps
`DELETE` for one thing: the nightly `northwend-tidy` runs the 7-year prunes
(`consent.prune`, `access_log.prune`) as `northwend_jobs`. `--roles` checks
both. `tests/test_postgres.py` (`ConsentAccessTests`) and
`tests/test_db_roles_split.py` check that an `UPDATE` or `DELETE` as the app
role fails and an `INSERT` works.

## Undo

Put the owner's string back in `PORTFOLIO_DB` (Render web and crons, or
staging's Secrets) and `DATABASE_URL` (GitHub), and set
`NORTHWEND_SKIP_SCHEMA_SETUP` back to `0` there (or delete the GitHub
variable). Both are by-hand settings in Render, so no release is needed. If
step 5 was done, that means the owner's new password - which then lives in
those places again until you redo the switch. The roles can stay. To remove
them later, as the owner:
`DROP OWNED BY northwend_app, northwend_jobs; DROP ROLE northwend_app, northwend_jobs;`
(they own nothing, so this only drops their grants and default privileges).
