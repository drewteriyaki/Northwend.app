# ADR 0002: Feature flags and legal gates

- **Status:** Accepted
- **Date:** October 2026
- **Approved:** by the owner with PLAN.md ("Flags and gates (the smallest version)")

## Context

The brief wants every new feature behind a flag, and every legal gate as a
setting that is off by default. There were no flags before.

Staging is fast-forwarded to `main`. Anything on staging goes live at the
next release. So "ship it dark on staging" isn't a way to hold a feature
back. Only a setting can.

`docs/LEGAL_GATES.md` lists the gates the lawyer signs off: L0 (beta
baseline), L1 (advisor seats and billing), L2 (directory and intros) and
L3 (conclusion policy). L4, in-house advice, is never in scope.

## Decision

1. One small standard-library module, `flags.py`, reads two settings:
   `NORTHWEND_GATES` (for example `L0,L3`) and `NORTHWEND_FLAGS` (for
   example `walk,screenshot_ai`). Environment first, then Streamlit
   secrets.
2. Everything is off by default. A missing or empty setting means off.
3. Only the gates L0 to L3 exist. There is no L4: a setting that names it
   is ignored, and a test checks that.
4. One table, `FEATURES`, lists each feature: its flag, the gates it
   needs, and the view it owns. `flags.on(name)` is true only when the flag
   and all its gates are on.
5. `_view()` in `dashboard.py` skips a view whose feature is off, and its
   page leaves `PAGES` and the menu. A feature inside an existing view calls
   `flags.on(...)` where it's drawn.
6. Staging turns everything on. Production turns on only what the owner
   has approved. Admin > System lists what's on. These aren't secrets.
7. Per-account flags (beta testers) aren't built. They can be added later
   as one more setting.

## Consequences

- A new feature can't reach the live copy by accident: its flag starts off.
- A whole view can't forget its flag, because `_view()` checks it.
- Tests (`tests/test_flags.py`) check: with no settings everything is off;
  there is no L4; a feature needs its flag and every gate; a view whose
  feature is off is skipped and its page leaves `PAGES`; every flag is
  checked somewhere. A test that every gated feature in `LEGAL_GATES.md` is
  listed in `FEATURES` comes with the first gated feature.
- A gate that's off can't switch off something people already use. What
  shows with a gate off is decided per feature in `LEGAL_GATES.md`.
- Turning a feature on is a settings change and a restart, not a deploy.
