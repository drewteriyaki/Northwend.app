"""Ask Northwend's calculator tools (docs/AI_PLAN.md 5.3, step 14): read-only
arithmetic the model can ask for, each wrapping an existing, tested pure
function.

    stress_test          stress.run / time_text     - a mix of asset classes in 2008, 2020, 2022
    next_deposit_split   next_deposit.split / to_reach - a deposit's split toward their own target
    employer_match       employer_match.match_pct / full_at - a match formula, as % of pay
    fee_drag             fees.cost_over             - what a yearly fee takes over the years
    goal_projection      plans.future_value / months_to_reach - progress toward a goal, in % of it

Figures go to the screen, not the model (AI_PLAN 5.3): every input and
every result here is a percentage, a number of months or years, or a ratio -
never a dollar amount, a balance or a share count, and there is no input
that could take one (the per-conversation opt-in for plan figures, AI_PLAN
3.3, doesn't exist yet). run() returns ToolResult.for_model: plain text with
no "$" and no amount, labelled hypothetical where it's about the future. A
result is a fact plus its label; it never says what to do.

Read-only by construction: this module imports no database code, takes no
connection and writes nothing (a test runs every tool with the database
refusing to open). The tool list is fixed (TOOLS, in this order) and the
same for everyone, so the cached prompt prefix holds (ai_gateway.
build_request). Pure: standard library and the wrapped modules only.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import employer_match
import fees
import next_deposit
import plans
import stress
from asset_classes import CLASSES

MAX_TIERS = 5
MAX_YEARS = 60
DEFAULT_DEPOSIT_PCT = 5.0        # a deposit of 5% of the portfolio, when none is given
HYPOTHETICAL = "Hypothetical illustration, not a prediction"


class ToolResult(NamedTuple):
    for_model: str          # percentages, months and ratios only - never "$" or an amount
    is_error: bool = False  # the input didn't check out; for_model says why


class _Bad(ValueError):
    """An input the model is asked to fix."""


# --------------------------------------------------------------------------- #
# the tools as the API sees them
# --------------------------------------------------------------------------- #
def _num(desc: str, *, nullable: bool = False, low=None, high=None) -> dict:
    out = {"type": ["number", "null"] if nullable else "number", "description": desc}
    if low is not None:
        out["minimum"] = low
    if high is not None:
        out["maximum"] = high
    return out


def _mix_schema(desc: str) -> dict:
    return {"type": "object", "description": desc + " Percent by asset class; leave out a "
            "class that isn't there.",
            "properties": {c: _num(f"{c}, % of the mix.", low=0, high=100) for c in CLASSES},
            "additionalProperties": False}


def _tool(name: str, description: str, properties: dict, required: list) -> dict:
    return {"name": name, "description": description, "eager_input_streaming": True,
            "input_schema": {"type": "object", "properties": properties,
                             "required": required, "additionalProperties": False}}


_COMMON = (" Percentages only - never pass a dollar amount; if the person gave amounts, use "
           "the shares they make instead. The result is arithmetic and history, never what to "
           "do: describe it, and say it's hypothetical.")

TOOLS = (
    _tool("stress_test",
          "How a mix of asset classes would have done in three hard stretches (2008, 2020, "
          "2022): the drop from the stock market's high to its low, and roughly how long the "
          "mix took to get back - from rounded index figures. Use the person's mix from the "
          "card, their own target, or a mix they ask about." + _COMMON,
          {"mix": _mix_schema("The mix to test.")}, ["mix"]),
    _tool("next_deposit_split",
          "Splits a deposit across asset classes so the mix ends up as close as it can to the "
          "person's own target without selling anything (the app's \"Where could your next "
          "deposit go?\"). Returns each class's share of the deposit, the mix after, and the "
          "deposit size that would reach the target - all as percentages. Only with a target "
          "the person set themselves (the card's target mix)." + _COMMON,
          {"current": _mix_schema("Their mix now."),
           "target": _mix_schema("Their own target mix."),
           "deposit_pct": _num("The deposit as a % of the portfolio's current value; null for "
                               f"a typical {DEFAULT_DEPOSIT_PCT:g}%.", nullable=True, low=0,
                               high=1000)},
          ["current", "target", "deposit_pct"]),
    _tool("employer_match",
          "An employer retirement-plan match, worked out as a % of pay: the match at what the "
          "person puts in, where the full match starts, and the difference. Plain arithmetic - "
          "no tax limits, true-ups or vesting; their plan's own rules decide. Uses the "
          "percentages the person gives, never their pay." + _COMMON,
          {"contribution_pct": _num("What they put in, % of pay.", low=0, high=100),
           "tiers": {"type": "array", "minItems": 1, "maxItems": MAX_TIERS,
                     "description": "The match formula in tiers: \"50% of the first 6%\" is "
                                    "[{rate_pct: 50, up_to_pct: 6}]; \"100% of the first 3%, "
                                    "then 50% of the next 2%\" is two tiers.",
                     "items": {"type": "object",
                               "properties": {"rate_pct": _num("The match rate, %.", low=0,
                                                               high=200),
                                              "up_to_pct": _num("On the next this-many % of "
                                                                "pay.", low=0, high=100)},
                               "required": ["rate_pct", "up_to_pct"],
                               "additionalProperties": False}}},
          ["contribution_pct", "tiers"]),
    _tool("fee_drag",
          "What a fund's yearly fee (expense ratio) takes over the years: how much lower the "
          "balance ends than with no fee, and the share of the growth the fee takes - as "
          "percentages, at an assumed steady growth rate with nothing added. Optionally side "
          "by side with a second fee for comparison - a fact about fees, never a reason to "
          "switch." + _COMMON,
          {"expense_ratio_pct": _num("The yearly fee, % (0.9 for 0.90%).", low=0, high=5),
           "years": _num("Years; null for 10 and 30.", nullable=True, low=1, high=MAX_YEARS),
           "growth_pct": _num(f"Assumed yearly growth, %; null for {fees.GROWTH * 100:g}%.",
                              nullable=True, low=-10, high=15),
           "compare_ratio_pct": _num("A second yearly fee to compare, %; null for none.",
                                     nullable=True, low=0, high=5)},
          ["expense_ratio_pct", "years", "growth_pct", "compare_ratio_pct"]),
    _tool("goal_projection",
          "A hypothetical projection toward a goal, in % of the goal: where steady growth and "
          "a monthly amount would get in some years, and roughly how long until the goal is "
          "reached, at the stated rate and a couple of points either side. Use the person's "
          "own figures as shares of their goal (\"I'm 40% of the way, adding about 0.5% of "
          "it a month\")." + _COMMON,
          {"now_pct_of_goal": _num("Where they are now, % of the goal.", low=0, high=1000),
           "monthly_pct_of_goal": _num("Added each month, % of the goal; null for nothing.",
                                       nullable=True, low=0, high=100),
           "annual_return_pct": _num("Assumed yearly return, %; null for "
                                     f"{plans.DEFAULT_RETURN_PCT:g}%.", nullable=True,
                                     low=-10, high=15),
           "years": _num("Years ahead to show; null for 10.", nullable=True, low=1,
                         high=MAX_YEARS)},
          ["now_pct_of_goal", "monthly_pct_of_goal", "annual_return_pct", "years"]),
)
NAMES = tuple(t["name"] for t in TOOLS)


# --------------------------------------------------------------------------- #
# checking what the model sent
# --------------------------------------------------------------------------- #
def _number(args: dict, key: str, low: float, high: float, *, default=None,
            nullable: bool = False) -> float | None:
    v = args.get(key)
    if v is None:
        if nullable:
            return default
        raise _Bad(f"{key} is required")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v) \
            or not low <= v <= high:
        unit = "%" if key.endswith("_pct") or key.endswith("_of_goal") else ""
        raise _Bad(f"{key} must be a number from {low:g}{unit} to {high:g}{unit}")
    return float(v)


def _mix(args: dict, key: str) -> dict:
    raw = args.get(key)
    if not isinstance(raw, dict) or not raw:
        raise _Bad(f"{key} must be an object of percentages by asset class: "
                   + ", ".join(CLASSES))
    unknown = set(raw) - set(CLASSES)
    if unknown:
        raise _Bad(f"{key}: unknown asset class {sorted(unknown)[0]!r} - use "
                   + ", ".join(CLASSES))
    mix = {k: _number(raw, k, 0, 100) for k in raw}
    if sum(mix.values()) <= 0:
        raise _Bad(f"{key} must have a share above 0")
    return stress.clean(mix)


def _only(args, keys) -> dict:
    if not isinstance(args, dict):
        raise _Bad("input must be an object")
    extra = set(args) - set(keys)
    if extra:
        raise _Bad(f"unknown input: {sorted(extra)[0]}")
    return args


# --------------------------------------------------------------------------- #
# words
# --------------------------------------------------------------------------- #
def _p(v: float) -> str:
    """A percent: whole above 10, one decimal below (0.4%, 8.4%, 23%)."""
    v = 0.0 if abs(v) < 0.05 else v
    if abs(v) >= 1000:
        return "more than 1000%" if v > 0 else "less than -1000%"
    return f"{v:.0f}%" if abs(v) >= 10 else f"{v:.1f}%".replace(".0%", "%")


def _mix_text(mix: dict) -> str:
    parts = sorted(((k, v) for k, v in mix.items() if v > 0.05), key=lambda kv: -kv[1])
    return ", ".join(f"{k} {v:.0f}%" for k, v in parts)


def _months_text(m: int | None, cap_years: int) -> str:
    if m is None:
        return f"not within {cap_years} years"
    if m <= 0:
        return "already there"
    if m < 24:
        return f"about {m} month{'s' if m != 1 else ''}"
    years = round(m / 12 * 2) / 2
    return f"about {years:g} years"


# --------------------------------------------------------------------------- #
# the tools
# --------------------------------------------------------------------------- #
def _stress_test(args) -> str:
    args = _only(args, ("mix",))
    mix = _mix(args, "mix")
    lines = [f"{HYPOTHETICAL}: how a mix of {_mix_text(mix)} (asset classes only) would have "
             "done, from rounded figures for broad market indexes - history, not what will "
             "happen next."]
    for r in stress.run(mix):
        move = (f"down about {_p(-r['drop_pct'])}" if r["drop_pct"] < 0
                else f"up about {_p(r['drop_pct'])}")
        back = ("it didn't fall" if r["drop_pct"] >= 0
                else f"back to where it started in {stress.time_text(r['months_back'])}")
        lines.append(f"- {r['name']} ({r['when']}): {move} from the high to the low; {back}.")
    lines.append(stress.ASSUMPTIONS)
    return "\n".join(lines)


def _next_deposit_split(args) -> str:
    args = _only(args, ("current", "target", "deposit_pct"))
    current, target = _mix(args, "current"), _mix(args, "target")
    deposit = _number(args, "deposit_pct", 0, 1000, default=DEFAULT_DEPOSIT_PCT, nullable=True)
    if deposit <= 0:
        raise _Bad("deposit_pct must be above 0")
    parts = next_deposit.split(current, target, deposit)          # in % of the portfolio
    shares = next_deposit.round_split({k: v / deposit * 100 for k, v in parts.items()}, 100)
    after = {k: current.get(k, 0.0) + parts.get(k, 0.0) for k in set(current) | set(parts)}
    reach = next_deposit.to_reach(current, target)
    lines = [f"Arithmetic on their own target mix ({_mix_text(target)}), not a "
             f"recommendation: a deposit of {_p(deposit)} of the portfolio's current value, "
             "split by asset class so the mix ends up as close as it can to that target "
             "without selling anything. Which funds fill each part is their choice."]
    lines += [f"- {k}: {v:.0f}% of the deposit" for k, v in
              sorted(shares.items(), key=lambda kv: -kv[1])]
    lines.append(f"Mix now: {_mix_text(current)}. Mix after: "
                 f"{_mix_text(next_deposit.mix_pct(after))}.")
    if reach is None:
        lines.append("Adding alone can't reach the target exactly: something is held in an "
                     "asset class the target leaves out.")
    elif reach <= 0.05:
        lines.append("The mix is already at the target.")
    else:
        lines.append(f"A deposit of about {_p(reach)} of the portfolio's current value would "
                     "bring every class to its target without selling.")
    return "\n".join(lines)


def _employer_match(args) -> str:
    args = _only(args, ("contribution_pct", "tiers"))
    you = _number(args, "contribution_pct", 0, 100)
    raw = args.get("tiers")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TIERS:
        raise _Bad(f"tiers must be a list of 1 to {MAX_TIERS} "
                   "{rate_pct, up_to_pct} objects")
    tiers = []
    for t in raw:
        t = _only(t, ("rate_pct", "up_to_pct"))
        tiers.append((_number(t, "rate_pct", 0, 200), _number(t, "up_to_pct", 0, 100)))
    tiers = tuple(tiers)
    got = employer_match.match_pct(you, tiers)
    full = employer_match.full_at(tiers)
    most = employer_match.match_pct(full, tiers)
    formula = employer_match.describe(tuple((round(r, 2), round(u, 2)) for r, u in tiers))
    lines = [f"Arithmetic on the match formula they gave ({formula}) - "
             "plain arithmetic, no tax limits, true-ups or vesting; their plan's own rules "
             "decide."]
    if most <= 0:
        lines.append("- This formula adds no match.")
        return "\n".join(lines)
    lines += [f"- Putting in {_p(you)} of pay, the match comes to {_p(got)} of pay.",
              f"- The full match starts at {_p(full)} of pay, where it comes to {_p(most)} of "
              "pay."]
    gap = max(0.0, most - got)
    lines.append(f"- The difference: {_p(gap)} of pay." if gap > 1e-9
                 else "- At what they put in, they get the whole match.")
    return "\n".join(lines)


def _drag(ratio_pct: float, years: int, growth_pct: float) -> tuple[float, float]:
    """(how much lower the end balance is than with no fee, % ; the share of
    the no-fee growth the fee takes, %) - on 100, so nothing is a dollar."""
    cost = fees.cost_over(100.0, ratio_pct / 100, years, growth_pct / 100)["total"]
    no_fee = 100.0 * (1 + growth_pct / 100) ** years
    growth = no_fee - 100.0
    return cost / no_fee * 100, (cost / growth * 100 if growth > 0 else float("nan"))


def _fee_drag(args) -> str:
    args = _only(args, ("expense_ratio_pct", "years", "growth_pct", "compare_ratio_pct"))
    ratio = _number(args, "expense_ratio_pct", 0, 5)
    years = _number(args, "years", 1, MAX_YEARS, nullable=True)
    growth = _number(args, "growth_pct", -10, 15, default=fees.GROWTH * 100, nullable=True)
    compare = _number(args, "compare_ratio_pct", 0, 5, nullable=True)
    horizons = (int(round(years)),) if years else tuple(fees.HORIZONS)
    lines = [f"{HYPOTHETICAL}: at a steady {_p(growth)} a year with nothing added, the fee "
             "coming out of the fund's value each year. A fact about the fee, not a view on "
             "the fund."]
    for r in (ratio,) + ((compare,) if compare is not None else ()):
        parts = []
        for y in horizons:
            lower, share = _drag(r, y, growth)
            parts.append(f"over {y} years the balance ends about {_p(lower)} lower than with "
                         "no fee" + ("" if math.isnan(share) else
                                     f" - about {_p(share)} of the growth"))
        lines.append(f"- A yearly fee of {fees.fmt_ratio(r / 100)}: " + "; ".join(parts) + ".")
    return "\n".join(lines)


def _goal_projection(args) -> str:
    args = _only(args, ("now_pct_of_goal", "monthly_pct_of_goal", "annual_return_pct",
                        "years"))
    now = _number(args, "now_pct_of_goal", 0, 1000)
    monthly = _number(args, "monthly_pct_of_goal", 0, 100, default=0.0, nullable=True)
    rate = _number(args, "annual_return_pct", -10, 15, default=plans.DEFAULT_RETURN_PCT,
                   nullable=True)
    years = int(round(_number(args, "years", 1, MAX_YEARS, default=10, nullable=True)))
    lines = [f"{HYPOTHETICAL}: starting at {_p(now)} of the goal"
             + (f", adding {_p(monthly)} of the goal a month" if monthly else
                ", adding nothing")
             + f", at a steady {_p(rate)} a year. Real returns vary year to year, and past "
             "results don't predict future ones."]
    for r in (rate - plans.SPREAD_PCT, rate, rate + plans.SPREAD_PCT):
        at = plans.future_value(now, monthly, r, years * 12)
        reach = plans.months_to_reach(now, monthly, r, 100.0, cap=MAX_YEARS * 12)
        lines.append(f"- At {_p(r)} a year: after {years} year{'s' if years != 1 else ''} about "
                     f"{_p(at)} of the goal; the goal reached in "
                     f"{_months_text(reach, MAX_YEARS)}.")
    return "\n".join(lines)


_RUN = {"stress_test": _stress_test, "next_deposit_split": _next_deposit_split,
        "employer_match": _employer_match, "fee_drag": _fee_drag,
        "goal_projection": _goal_projection}


def run(name: str, args) -> ToolResult:
    """Run calculator `name` on the model's `args` (already parsed JSON).
    Never raises for bad input - the model gets an error to fix instead -
    and never touches a database."""
    fn = _RUN.get(name)
    if fn is None:
        return ToolResult(f"unknown tool: {name}", True)
    try:
        return ToolResult(fn(args))
    except _Bad as exc:
        return ToolResult(str(exc), True)
