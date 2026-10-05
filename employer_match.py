"""Free money check (ROADMAP overnight plan, item 6): an employer 401(k)
match calculator.

A match formula is a list of tiers, (rate, up_to): "50% of the first 6%" is
[(50, 6)], "100% of the first 3%, then 50% of the next 2%" is [(100, 3),
(50, 2)] - each tier matches `rate`% of what you put in on the next `up_to`
percent of your pay. From a salary and what someone puts in (% of pay):
the match they get now, the most they could get, and the gap.

Pure functions, standard library only. Plain arithmetic: no IRS limits,
true-ups or vesting - the page says to check the plan's own rules.
"""

from __future__ import annotations

# (label, tiers) - common formulas, then "Other" for a custom one
PRESETS = (
    ("50% of the first 6%", ((50.0, 6.0),)),
    ("100% of the first 3%, then 50% of the next 2%", ((100.0, 3.0), (50.0, 2.0))),
    ("100% of the first 4%", ((100.0, 4.0),)),
    ("100% of the first 6%", ((100.0, 6.0),)),
    ("50% of the first 4%", ((50.0, 4.0),)),
    ("100% of the first 3%", ((100.0, 3.0),)),
)
PRESET_TIERS = dict(PRESETS)
CUSTOM = "Something else"
PREF = "match_check"   # user_prefs key, only when someone asks to remember it


def tiers_for(preset: str | None, rate: float | None = None,
              up_to: float | None = None) -> tuple:
    """The tiers for a preset's label, or one custom tier (rate, up_to)."""
    if preset in PRESET_TIERS:
        return PRESET_TIERS[preset]
    rate, up_to = max(0.0, float(rate or 0.0)), max(0.0, float(up_to or 0.0))
    return ((rate, up_to),) if rate and up_to else ()


def match_pct(contrib_pct: float, tiers) -> float:
    """The employer's match as a % of pay, for putting in `contrib_pct`% of pay."""
    left = max(0.0, float(contrib_pct or 0.0))
    out = 0.0
    for rate, up_to in tiers:
        part = min(left, max(0.0, float(up_to)))
        out += part * max(0.0, float(rate)) / 100
        left -= part
        if left <= 0:
            break
    return out


def full_at(tiers) -> float:
    """What you need to put in (% of pay) to get the whole match."""
    return sum(max(0.0, float(u)) for r, u in tiers if r and u)


def check(salary: float | None, contrib_pct: float, tiers) -> dict:
    """{"you_pct", "match_pct", "max_pct", "full_at", "missing_pct", and with a
    salary "you_yearly", "match_yearly", "max_yearly", "missing_yearly"
    (None without one), "getting_all": bool, "has_match": bool}."""
    you = max(0.0, float(contrib_pct or 0.0))
    got = match_pct(you, tiers)
    full = full_at(tiers)
    most = match_pct(full, tiers)
    pay = max(0.0, float(salary or 0.0)) or None

    def dollars(pct):
        return pay * pct / 100 if pay else None
    missing = max(0.0, most - got)
    return {"you_pct": you, "match_pct": got, "max_pct": most, "full_at": full,
            "missing_pct": missing, "you_yearly": dollars(you), "match_yearly": dollars(got),
            "max_yearly": dollars(most), "missing_yearly": dollars(missing),
            "getting_all": missing < 1e-9, "has_match": most > 0}


def describe(tiers) -> str:
    """'50% of the first 6%' / '100% of the first 3%, then 50% of the next 2%'."""
    parts = []
    for i, (rate, up_to) in enumerate(tiers):
        parts.append(f"{rate:g}% of the {'first' if i == 0 else 'next'} {up_to:g}%")
    return ", then ".join(parts)


def clean_saved(saved) -> dict:
    """The remembered inputs, checked: {} if anything looks wrong."""
    if not isinstance(saved, dict):
        return {}
    out = {}
    for k in ("salary", "contrib_pct", "rate", "up_to"):
        v = saved.get(k)
        if isinstance(v, (int, float)) and 0 <= v <= (10_000_000 if k == "salary" else 100):
            out[k] = float(v)
    if saved.get("preset") in PRESET_TIERS or saved.get("preset") == CUSTOM:
        out["preset"] = saved["preset"]
    return out
