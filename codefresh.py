"""Keep the running app's own modules in step with the files on disk.

After a push, Streamlit Community Cloud pulls the new files and re-runs
dashboard.py, but modules it already imported (auth, portfolio, ...) can
stay in memory at their old version - the app then mixes new and old code
(a new dashboard calling a function the old auth doesn't have) until it is
rebooted, and new schema changes don't run.

dashboard.py calls drop_stale() before importing its own modules and
mark_loaded() after. If any of the app's files changed since it was loaded,
ALL of them are dropped together, so the imports that follow load one
consistent, current version. Process-wide state that must survive a reload
(the Postgres connection pools) is carried over by carry_over().
"""

from __future__ import annotations

import os
import sys
import threading

_LOCK = threading.Lock()
_MARK = "_codefresh_stamp"


def _stamp(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _ours(here: str) -> dict:
    """The loaded modules whose file sits directly in `here` (not this one)."""
    out = {}
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if (not f or name in ("__main__", __name__)
                or os.path.dirname(os.path.abspath(f)) != here):
            continue
        out[name] = mod
    return out


def drop_stale(here: str) -> dict:
    """If any of our loaded modules changed on disk, remove all of them from
    sys.modules and return the old modules by name; otherwise return {}."""
    here = os.path.abspath(here)
    with _LOCK:
        mods = _ours(here)
        stale = any(
            getattr(m, _MARK, None) is not None and getattr(m, _MARK) != _stamp(m.__file__)
            for m in mods.values())
        if not stale:
            return {}
        for name in mods:
            sys.modules.pop(name, None)
        print(f"codefresh: app files changed on disk; reloading {len(mods)} module(s)",
              file=sys.stderr)
        return mods


def mark_loaded(here: str) -> None:
    """Record the file version of each of our modules not yet recorded."""
    here = os.path.abspath(here)
    with _LOCK:
        for m in _ours(here).values():
            if getattr(m, _MARK, None) is None:
                setattr(m, _MARK, _stamp(m.__file__))


def carry_over(old: dict) -> None:
    """Hand process-wide state from dropped modules to their fresh copies."""
    old_pg, new_pg = old.get("pgcompat"), sys.modules.get("pgcompat")
    if old_pg is not None and new_pg is not None and old_pg is not new_pg:
        # Keep the open connection pools rather than leaking them.
        for dsn, pool in getattr(old_pg, "_POOLS", {}).items():
            new_pg._POOLS.setdefault(dsn, pool)
