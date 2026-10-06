"""What each holding actually holds: Stocks, Bonds, Cash or Other.

The broker's asset type says what kind of security something is ("ETFs &
Closed End Funds"), not what it holds - an ETF can be all stocks (VTI), all
bonds (BND) or both (AOR). Targets, model portfolios and drift use these
classes instead, so a 60/40 mix can be set and tracked.

Each holding gets a split, {class: fraction} summing to 1, from the first
of these that applies:
1. the account's own override for that symbol (one class, 100%),
2. Yahoo, via sync_history into security_info: a fund's stock / bond / cash
   positions (a balanced fund is split between them), a money-market fund
   is cash, a single stock is stocks,
3. the broker's asset type (Equity -> Stocks, Fixed Income -> Bonds,
   Cash and Money Market -> Cash), else Other.

Pure logic plus a few small reads/writes; standard library only.
"""

from __future__ import annotations

import json

CLASSES = ("Stocks", "Bonds", "Cash", "Other")

# broker asset type (long or short label) -> class, when Yahoo has nothing
_FROM_ASSET_TYPE = {
    "Equity": "Stocks",
    "Fixed Income": "Bonds",
    "Cash and Money Market": "Cash",
    "Cash": "Cash",
}

# old target keys (broker asset types) -> class, for converting saved targets
_OLD_TARGET_KEYS = {"Equity": "Stocks", "Fixed Income": "Bonds", "Cash": "Cash"}
_UNTRANSLATABLE = ("ETF / CEF", "Mutual Funds")

SOURCE_LABELS = {"override": "your choice", "yahoo": "Yahoo", "broker": "broker type"}


def _whole(cls: str) -> dict:
    return {cls: 1.0}


def from_yahoo(info: dict | None) -> dict | None:
    """A split from a security_info row, or None if Yahoo gave nothing usable."""
    if not info:
        return None
    qt = (info.get("quote_type") or "").upper()
    if qt == "EQUITY":
        return _whole("Stocks")
    if qt == "MONEYMARKET":
        return _whole("Cash")
    if qt == "CRYPTOCURRENCY":
        return _whole("Other")
    parts = {"Stocks": info.get("stock_pct"), "Bonds": info.get("bond_pct"),
             "Cash": info.get("cash_pct"), "Other": info.get("other_pct")}
    parts = {k: float(v) for k, v in parts.items() if v is not None and float(v) > 0}
    total = sum(parts.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in parts.items()}


def from_asset_type(asset_type: str | None) -> dict:
    return _whole(_FROM_ASSET_TYPE.get(asset_type or "", "Other"))


def split_for(symbol: str, asset_type: str | None, info: dict | None,
              overrides: dict | None = None) -> tuple[dict, str]:
    """(split, source) for one holding; source is 'override', 'yahoo' or 'broker'."""
    chosen = (overrides or {}).get(symbol)
    if chosen in CLASSES:
        return _whole(chosen), "override"
    y = from_yahoo(info)
    if y:
        return y, "yahoo"
    return from_asset_type(asset_type), "broker"


def main_class(split: dict) -> str:
    """The class with the biggest share (for a one-word label)."""
    return max(split.items(), key=lambda kv: kv[1])[0] if split else "Other"


def describe(split: dict) -> str:
    """'Stocks' for a whole split, else '62% stocks / 38% bonds'."""
    parts = sorted(((k, v) for k, v in split.items() if v >= 0.005), key=lambda kv: -kv[1])
    if len(parts) <= 1:
        return parts[0][0] if parts else main_class(split)
    return " / ".join(f"{v * 100:.0f}% {k.lower()}" for k, v in parts)


def mix_return(mix: dict, returns: dict) -> float | None:
    """A mix's weighted return: `mix` is {class: share} (any total), `returns`
    {class: %} with an "Other" fallback. None for an empty mix. Used by the
    advisor proposal card (proposals.compare) and the stress test (stress.py)."""
    total = sum(mix.values())
    if not total:
        return None
    return sum(returns.get(k, returns["Other"]) * v for k, v in mix.items()) / total


# ---- storage ---------------------------------------------------------------- #
OVERRIDES_PREF = "class_overrides"   # user_prefs key: {symbol: class}


def load_overrides(conn, user_id: int) -> dict:
    import prefs
    return overrides_in(prefs.load(conn, user_id))


def overrides_in(saved_prefs: dict) -> dict:
    """load_overrides() from an account's settings already read (prefs.load)."""
    raw = saved_prefs.get(OVERRIDES_PREF) or {}
    return {s: c for s, c in raw.items() if c in CLASSES} if isinstance(raw, dict) else {}


INFO_COLS = ("quote_type", "stock_pct", "bond_pct", "cash_pct", "other_pct")


def load_info(conn, symbols) -> dict:
    """{symbol: security_info fields used here} for the symbols that have a row."""
    symbols = sorted({s for s in symbols if s})
    if not symbols:
        return {}
    rows = conn.execute(
        f"SELECT ticker, {', '.join(INFO_COLS)} FROM security_info WHERE ticker IN "
        f"({', '.join('?' for _ in symbols)})", tuple(symbols)).fetchall()
    return {r["ticker"]: {c: r[c] for c in INFO_COLS} for r in rows}


def splits(conn, positions, overrides: dict | None = None) -> dict:
    """{symbol: split} for every holding in `positions` (dicts with symbol and
    asset_type), ready for allocation.allocate(..., splits=...)."""
    positions = list(positions)
    return splits_from(positions, load_info(conn, [p.get("symbol") for p in positions]),
                       overrides)


def splits_from(positions, info_by_symbol: dict, overrides: dict | None = None) -> dict:
    """splits() with the security_info rows already in hand."""
    return {p["symbol"]: split_for(p["symbol"], p.get("asset_type"),
                                   info_by_symbol.get(p["symbol"]), overrides)[0]
            for p in positions if p.get("symbol")}


# ---- saved targets from before classes -------------------------------------- #
def convert_targets(mix: dict | None) -> tuple[dict, bool]:
    """A saved target mix moved to classes: (new_mix, cleared). Old keys that
    map (Equity, Fixed Income, Cash) are renamed; a mix that used ETF / CEF or
    Mutual Funds can't be translated, so it's cleared (cleared=True)."""
    mix = {k: float(v) for k, v in (mix or {}).items() if v}
    if not mix or all(k in CLASSES for k in mix):
        return mix, False
    if any(k in _UNTRANSLATABLE for k in mix):
        return {}, True
    out: dict = {}
    for k, v in mix.items():
        cls = k if k in CLASSES else _OLD_TARGET_KEYS.get(k)
        if cls is None:
            return {}, True
        out[cls] = out.get(cls, 0.0) + v
    return out, False


def migrate_targets(conn) -> dict:
    """Move every saved plan target and model portfolio to classes, once.
    A plan whose target was cleared gets plans.targets_cleared = 1 so the Plan
    page can say so. Returns counts, for the startup log."""
    done = {"plans": 0, "plans_cleared": 0, "models": 0, "models_cleared": 0}
    for table, key, flag in (("plans", "user_id", True), ("model_portfolios", "id", False)):
        for r in conn.execute(f"SELECT {key}, target_alloc FROM {table} "
                              "WHERE target_alloc IS NOT NULL AND target_alloc <> '' "
                              "AND target_alloc <> '{}'").fetchall():
            try:
                old = json.loads(r["target_alloc"])
            except ValueError:
                continue
            if not isinstance(old, dict):
                continue
            new, cleared = convert_targets(old)
            if new == {k: float(v) for k, v in old.items() if v} and not cleared:
                continue
            name = "plans" if flag else "models"
            done[name] += 1
            done[name + "_cleared"] += cleared
            sets = "target_alloc = ?" + (", targets_cleared = ?" if flag else "")
            args = (json.dumps(new),) + ((1 if cleared else 0,) if flag else ()) + (r[key],)
            conn.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", args)
    return done
