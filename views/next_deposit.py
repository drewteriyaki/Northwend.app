# Part of dashboard.py, which runs this file with _view("next_deposit") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Where could your next deposit go? (next_deposit.py): under the Plan page's
# target mix, an amount (the plan's monthly one to start) split by asset class
# to move closest to the target without selling, with the mix before and
# after; and one line under Home's drift notice. Asset classes only - which
# funds fill each part is the person's own choice.
# ruff: noqa: F821

import next_deposit

DEPOSIT_DEFAULT = 500.0   # without a monthly amount in the plan


def _deposit_start():
    """The amount to start from: the plan's monthly amount, else 500."""
    return float((load_plan() or {}).get("monthly_contribution") or 0.0) or DEPOSIT_DEFAULT


def _render_next_deposit(alloc_rows, targets):
    """Inside the Target mix tab (a fragment): only with holdings and a target."""
    current = {r["label"]: float(r["value"] or 0.0) for r in (alloc_rows or [])}
    if not targets or not sum(current.values()):
        return
    st.markdown("**Where could your next deposit go?**")
    if _hidden():
        amount = _deposit_start()
        st.caption("Amounts are hidden, so this shows how your planned monthly amount would "
                   "split, as shares of it. Show amounts (the eye beside the page title) to "
                   "try another amount.")
    else:
        st.session_state.setdefault("deposit_amount", _deposit_start())
        amount = st.number_input("An amount you're about to add ($)", min_value=0.0,
                                 step=50.0, format="%.0f", key="deposit_amount")
    if amount <= 0:
        st.caption("Type an amount to see how it could be split.")
        return
    r = next_deposit.plan(current, targets, amount)
    rows = ""
    for row in r["rows"]:
        if _hidden():
            add = f"{row['add'] / amount * 100:.0f}% of it" if row["add"] else "-"
            mix = f"target {row['target_pct']:g}%" if row["target_pct"] else "no target"
        else:
            add = ("+" + fmt_money0(row["add"])) if row["add"] else "-"
            mix = (f"{row['now_pct']:.0f}% → {row['after_pct']:.0f}% · "
                   + (f"target {row['target_pct']:g}%" if row["target_pct"] else "no target"))
        rows += ("<div class='pt-legend-row'>"
                 f"<span class='pt-legend-label'>{html.escape(row['class'])}"
                 f"<span class='pt-goal-sub' style='display:block'>{html.escape(mix)}</span></span>"
                 f"<span class='pt-legend-pct'>{html.escape(add)}</span></div>")
    st.html(f"<div class='pt-legend'>{rows}</div>")
    lines = []
    if not r["add"]:
        lines.append("Your mix is already at its target - a deposit split the same way keeps it "
                     "there.")
    elif not _hidden():
        lines.append(f"Split this way, nothing is sold and the furthest part goes from "
                     f"{r['gap_before']:.0f} to {r['gap_after']:.0f} points off its target.")
    if r["to_reach"] is None:
        lines.append("Part of your money is in an asset class with no target, so adding money "
                     "alone won't bring the mix all the way to its target.")
    elif r["to_reach"] > amount + 0.5 and not _hidden():
        lines.append(f"Adding about {fmt_money0(r['to_reach'])} in all would bring every part to "
                     "its target without selling.")
    if lines:
        _md("  \n".join(lines))
    st.caption("By asset class only - which funds fill each part is your choice. Rebalancing "
               "with new money avoids selling, which can mean taxes in a taxable account. "
               "An illustration, not advice.")


def deposit_line(alloc_by_class, targets):
    """One line for Home's drift notice: where a deposit could go to move
    back toward the target without selling ("" when nothing is under its
    target). No amounts."""
    current = {r["label"]: float(r["value"] or 0.0) for r in (alloc_by_class or [])}
    if not targets or not sum(current.values()):
        return ""
    words = next_deposit.words(next_deposit.split(current, targets, _deposit_start()))
    if not words:
        return ""
    return (f"New money can bring it back without selling: your next deposit could go "
            f"{words}.")


def _open_deposit_tab():
    """Home's "Where it could go": the Plan page, on its Target mix tab."""
    st.session_state["plan_tab"] = "Target mix"
    _go("Plan")
