"""The Expedition Log (ROADMAP R3): one line written by the app for each
finished Monthly Walk (checkin.py), from percentages and facts only - the
month, the largest drift from the target mix in points, whether the holdings
were updated or nothing changed, the market's move for the person's own mix
over the month before (percent), what their own plan said, and whether they
wrote a note to future you on that walk. Never an amount of money. Pure
logic plus one small query; no Streamlit (the card is views/checkin.py, the
year's lines are in Year in review, recap.py).

Kept in the account's settings (prefs.py) beside the walk's verdict, with no
figures but rounded percentages and points:
  PREF_LOG {"2026-10": {"on": "2026-10-05", "updated": bool,
            "drift": {"class": "Stocks", "pts": 4} | None,
            "market": 1.8 | None, "sold": bool, "note": bool}}
"sold" is whether any sale was recorded since the walk before (the worked-out
or imported activity) - the Do-Nothing Ledger's rule (ledger.py). The note
itself stays in future_notes; only that one was written is kept here.

The person's own, like the walk: written only while the walk_log or ledger
flag is on (flags.py), drawn only on their own account - never while an
advisor looks at it, never in an advisor's client record and never sent to
the AI.
"""

from __future__ import annotations

from datetime import date, timedelta

import checkin
from asset_classes import CLASSES

PREF_LOG = "walk_log"
MARKET_DAYS = 30        # "the month before": the walk's day and the 30 days before it
MARKET_SLACK = 7        # the first close may be up to this many days into that window
MAX_PTS = 100


def month_label(month: str) -> str:
    """'October 2026' from '2026-10'."""
    return f"{checkin.month_name(month)} {month[:4]}"


# ---- the facts, worked out when a walk is finished --------------------------- #

def largest_drift(actual: dict, targets: dict) -> dict | None:
    """{"class", "pts"}: the targeted asset class furthest from its target,
    in whole points (positive: above it), or None without a target mix.
    `actual` and `targets` are {class: %}."""
    rows = [r for r in checkin.drift_rows(actual or {}, {k: v for k, v in (targets or {}).items()
                                                         if v})
            if r["off"] is not None and r["label"] in CLASSES]
    if not rows:
        return None
    top = max(rows, key=lambda r: abs(r["off"]))
    return {"class": top["label"], "pts": int(round(top["off"]))}


def market_move(points, day: date) -> float | None:
    """The percent move of the holdings now, priced at each close (perf's
    reconstructed line, `points` = [(date, value)]), over the MARKET_DAYS
    before `day` - rounded to one decimal; None when the closes don't cover
    that month."""
    start = (day - timedelta(days=MARKET_DAYS)).isoformat()
    end = day.isoformat()
    pts = sorted((str(d)[:10], float(v)) for d, v in points or ()
                 if d and v is not None and float(v) > 0 and start <= str(d)[:10] <= end)
    if len(pts) < 2:
        return None
    if pts[0][0] > (day - timedelta(days=MARKET_DAYS - MARKET_SLACK)).isoformat():
        return None
    return round((pts[-1][1] / pts[0][1] - 1) * 100, 1)


def sold_since(conn, user_id: int, after: str | None, until: str) -> bool:
    """Whether any sale is recorded in the account's activity (worked out
    from updates or imported) after the day `after` (None: from the first
    of `until`'s month) up to and including `until`."""
    since = after or f"{until[:7]}-01"
    op = ">" if after else ">="
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM transactions WHERE user_id = ? AND UPPER(action) = 'SELL' "
        f"AND SUBSTR(trade_date, 1, 10) {op} ? AND SUBSTR(trade_date, 1, 10) <= ?",
        (user_id, since, until[:10])).fetchone()
    return bool(row["n"])


def previous_day(p: dict, month: str) -> str | None:
    """The day the walk before `month` was finished (the log, or the kept
    verdicts), or None."""
    days = []
    for key in (PREF_LOG, checkin.PREF_VERDICTS):
        kept = p.get(key)
        if isinstance(kept, dict):
            days += [str(v.get("on"))[:10] for m, v in kept.items()
                     if isinstance(m, str) and m < month and isinstance(v, dict) and v.get("on")]
    return max(days) if days else None


def clean(rec: dict) -> dict:
    """What's kept of a log record: booleans, a class from the fixed list,
    whole points and a rounded percent - nothing else, so no amount can be
    stored."""
    rec = rec or {}
    out = {"on": str(rec.get("on") or "")[:10], "updated": bool(rec.get("updated")),
           "drift": None, "market": None, "sold": bool(rec.get("sold")),
           "note": bool(rec.get("note"))}
    d = rec.get("drift")
    if isinstance(d, dict) and d.get("class") in CLASSES:
        try:
            out["drift"] = {"class": d["class"],
                            "pts": max(-MAX_PTS, min(MAX_PTS, int(round(float(d["pts"])))))}
        except (KeyError, TypeError, ValueError):
            pass
    m = rec.get("market")
    if isinstance(m, (int, float)) and abs(m) < 1000:
        out["market"] = round(float(m), 1)
    return out


def record(p: dict, month: str, rec: dict) -> dict:
    """Keep the walk's facts for `month` in PREF_LOG (changes `p`)."""
    kept = p.get(PREF_LOG)
    kept = dict(kept) if isinstance(kept, dict) else {}
    kept[month] = clean(rec)
    p[PREF_LOG] = kept
    return kept[month]


def entries(p: dict) -> dict:
    """{month: record} of every walk logged, kept tidy."""
    kept = p.get(PREF_LOG)
    if not isinstance(kept, dict):
        return {}
    return {m: clean(v) for m, v in kept.items()
            if isinstance(m, str) and len(m) == 7 and isinstance(v, dict)}


# ---- the line ------------------------------------------------------------ #

def _verdict_words(v: dict | None) -> str:
    kind = (v or {}).get("kind")
    if kind == checkin.WITHIN:
        return "Your plan said nothing to do."
    if kind == checkin.NEXT and (v or {}).get("class"):
        how = {"all": "", "most": "mostly ", "much": "partly "}.get(v.get("how"), "")
        return f"Your plan pointed new money {how}to {checkin.class_name(v['class'])}."
    if kind == checkin.NEXT:
        return "Your plan pointed new money back toward your target."
    if kind == checkin.NONE:
        return "No target mix yet, so no verdict."
    return ""


def _drift_words(d: dict | None) -> str:
    if not d:
        return ""
    name = checkin.class_name(d["class"])
    pts = d["pts"]
    if pts == 0:
        return "Your mix was on its target."
    unit = "point" if abs(pts) == 1 else "points"
    side = "above" if pts > 0 else "below"
    return f"Largest drift: {name}, {abs(pts)} {unit} {side} target."


def _market_words(m: float | None) -> str:
    if m is None:
        return ""
    if abs(m) < 0.05:
        return "Your mix was about flat over the month before."
    return (f"Your mix {'rose' if m > 0 else 'fell'} {abs(m):.1f}% over the month before "
            "(prices only).")


def line(month: str, rec: dict, verdict: dict | None = None) -> str:
    """The walk's line: 'October 2026: Holdings updated. Largest drift:
    stocks, 4 points above target. Your mix rose 1.8% over the month before
    (prices only). Your plan said nothing to do.' Percentages and facts
    only - never an amount."""
    rec = clean(rec)
    parts = ["Holdings updated." if rec["updated"] else "Nothing changed in your holdings.",
             _drift_words(rec["drift"]), _market_words(rec["market"]), _verdict_words(verdict)]
    if rec["note"]:
        parts.append("You wrote a note to future you.")
    return f"{month_label(month)}: " + " ".join(x for x in parts if x)


def lines(p: dict, year: int | None = None, newest_first: bool = True) -> list[dict]:
    """[{"month", "on", "text", "note"}] for each logged walk (only `year`'s
    when given)."""
    out = []
    for month, rec in sorted(entries(p).items(), reverse=newest_first):
        if year is not None and not month.startswith(f"{year:04d}-"):
            continue
        out.append({"month": month, "on": rec["on"], "note": rec["note"],
                    "text": line(month, rec, checkin.verdict_of(p, month))})
    return out
