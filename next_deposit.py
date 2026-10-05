"""Where could your next deposit go? (ROADMAP overnight plan, item 4)

Splits an amount someone is about to add across asset classes (Stocks /
Bonds / Cash / Other) so the mix ends up as close to their own target mix as
it can - without selling anything. Asset classes only, never a fund or a
ticker: which funds fill each part is the person's choice.

"Closest" is the smallest sum of squared gaps between the new mix and the
target. That's water-filling: the deposit goes to the classes furthest below
their target first, evening them out, and never to a class already above it
(unless every class is at its target, when it's shared in the target's
proportions).

Pure functions, standard library only.
"""

from __future__ import annotations


def _shares(target: dict) -> dict:
    """{class: fraction} from a target mix in %, only the parts above 0."""
    t = {k: float(v) for k, v in (target or {}).items() if v and float(v) > 0}
    total = sum(t.values())
    return {k: v / total for k, v in t.items()} if total else {}


def split(current: dict, target: dict, amount: float) -> dict:
    """{class: dollars to add} for `amount`, each >= 0 and adding up to it.
    `current` is {class: dollars held now}; `target` {class: target %}.
    Empty when there's no target or nothing to add."""
    t = _shares(target)
    amount = float(amount or 0.0)
    if not t or amount <= 0:
        return {}
    cur = {k: max(0.0, float(v or 0.0)) for k, v in (current or {}).items()}
    after_total = sum(cur.values()) + amount
    # how far each targeted class is below its share of the new total
    gap = {k: t[k] * after_total - cur.get(k, 0.0) for k in t}
    # water-filling: x_k = max(0, gap_k - level), with the level that spends
    # exactly `amount` (the gaps always add up to at least the amount)
    ordered = sorted(gap.values(), reverse=True)
    level, running = 0.0, 0.0
    for i, g in enumerate(ordered):
        running += g
        level = (running - amount) / (i + 1)
        if i + 1 == len(ordered) or ordered[i + 1] <= level:
            break
    out = {k: max(0.0, g - level) for k, g in gap.items()}
    spent = sum(out.values())
    if spent > 0 and abs(spent - amount) > 1e-6:   # rounding in the level
        out = {k: v * amount / spent for k, v in out.items()}
    return {k: v for k, v in out.items() if v > 1e-9}


def round_split(parts: dict, amount: float) -> dict:
    """`parts` in whole dollars that still add up to `amount` (rounded): the
    leftover dollar or two goes to the biggest part."""
    whole = {k: float(round(v)) for k, v in parts.items()}
    whole = {k: v for k, v in whole.items() if v > 0}
    if whole:
        top = max(whole, key=whole.get)
        whole[top] += round(amount) - sum(whole.values())
    return whole


def mix_pct(values: dict) -> dict:
    """{class: % of the total} from {class: dollars}."""
    total = sum(v for v in values.values() if v)
    return {k: v / total * 100 for k, v in values.items() if v} if total else {}


def to_reach(current: dict, target: dict) -> float | None:
    """The smallest total deposit that brings every class to its target
    without selling - 0 when it's already there, None when it can't be done
    by adding alone (something is held in a class with no target)."""
    t = _shares(target)
    if not t:
        return None
    cur = {k: max(0.0, float(v or 0.0)) for k, v in (current or {}).items()}
    if any(v > 0.005 and k not in t for k, v in cur.items()):
        return None
    total = sum(cur.values())
    need = max([cur.get(k, 0.0) / share for k, share in t.items()] + [total])
    return max(0.0, need - total)


def plan(current: dict, target: dict, amount: float) -> dict:
    """Everything the page shows: {"rows": [{class, now_pct, add, after_pct,
    target_pct}], "add": {class: whole dollars}, "to_reach": dollars or None,
    "gap_before", "gap_after": the biggest distance from target in points}.
    Rows cover every class held or targeted, biggest target first."""
    add = round_split(split(current, target, amount), amount)
    t = {k: v * 100 for k, v in _shares(target).items()}
    after = {k: float(current.get(k, 0.0) or 0.0) + add.get(k, 0.0)
             for k in set(current) | set(add)}
    now_pct, after_pct = mix_pct(current), mix_pct(after)
    classes = sorted({k for k, v in current.items() if v} | set(t),
                     key=lambda k: (-t.get(k, 0.0), -now_pct.get(k, 0.0)))
    rows = [{"class": k, "now_pct": now_pct.get(k, 0.0), "add": add.get(k, 0.0),
             "after_pct": after_pct.get(k, 0.0), "target_pct": t.get(k, 0.0)}
            for k in classes]

    def gap(pct):
        return max((abs(pct.get(k, 0.0) - t.get(k, 0.0)) for k in classes), default=0.0)
    return {"rows": rows, "add": add, "to_reach": to_reach(current, target),
            "gap_before": gap(now_pct), "gap_after": gap(after_pct)}


def words(add: dict) -> str:
    """'entirely to bonds', 'mostly to bonds', 'to stocks and bonds' - for
    one line on Home ("your next deposit could go ...")."""
    parts = sorted(((k, v) for k, v in add.items() if v > 0), key=lambda kv: -kv[1])
    if not parts:
        return ""
    total = sum(v for _, v in parts)
    first = _name(parts[0][0])
    if len(parts) == 1:
        return f"entirely to {first}"
    if parts[0][1] / total >= 0.6:
        return f"mostly to {first}"
    names = [_name(k) for k, _ in parts]
    return "to " + (", ".join(names[:-1]) + " and " + names[-1])


def _name(cls: str) -> str:
    return "other holdings" if cls == "Other" else cls.lower()
