# ADR 0003: Tools and layout - no re-layout, no Alembic, no pydantic

- **Status:** Accepted
- **Date:** October 2026
- **Approved:** by the owner with PLAN.md (decision B9)

## Context

The brief's Phase 1 asks for three tools:

- a package re-layout into `core/`, `data/`, `services/` and `ui/`;
- Alembic for database migrations;
- pydantic-settings for configuration.

Their goals are good: no business logic or SQL in pages, versioned
migrations tested on Postgres, and configuration that fails closed.

The app is one Streamlit script, `dashboard.py`, with each page in
`views/` run through `_view("name")`. About 780 tests import modules by
their flat names. The schema is kept in two files, `schema.sql` and
`schema_pg.sql`, and `portfolio._ensure_schema` back-fills new columns.

## Decision

None of the three, for now. Lighter pieces meet the same goals:

1. **A layer-rule test instead of the re-layout.** Calculation modules
   (`perf`, `plans`, `income`, `fees`, `stress` and the like) import neither
   Streamlit nor the database. SQL in `views/` is listed in an allowlist
   that may only shrink.
2. **A schema version instead of Alembic.** A `schema_version` table and a
   `northwend-migrate` command that runs `portfolio._ensure_schema` on
   purpose. Migrations are tested on SQLite and on Postgres in CI.
3. **A standard-library `settings.py` instead of pydantic-settings.** It
   knows when it's hosted, refuses to start a hosted copy without a
   Postgres database, and becomes the one place settings are read.

## Consequences

- Cost saved: about 3-4 weeks with no change people would see. The
  re-layout alone is 2-3 weeks (nearly every file moves, the `_view`
  design breaks, every test import changes). Alembic is about 1 week (a
  baseline for two SQL dialects, plus learning it). pydantic-settings is
  1-2 sessions and a new dependency.
- Cost taken on: the layer rule is a test, not a folder boundary, so it's
  only as strong as the test. The allowlist must be kept honest.
- Migrations stay hand-written in `_ensure_schema`. Both schema files must
  still be kept in step (a test checks).
- This can be revisited. If the codebase or the team grows, the re-layout
  and Alembic are still possible. The layer test makes a later move
  smaller.
