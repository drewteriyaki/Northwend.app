"""Shared time-series chart for the dashboard.

A gridded Altair line with a hover rule that snaps to the nearest date, plus
helpers for the "last N days" range picker and the change-over-window figure.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

# (label, days back). None = everything on record.
RANGES = [("1D", 1), ("5D", 5), ("2W", 14), ("1M", 30), ("6M", 182), ("1Y", 365), ("All", None)]
RANGE_DAYS = dict(RANGES)
RANGE_LABELS = [label for label, _ in RANGES]

# Dollars on a chart's axis: short, with trailing zeros trimmed - "$0", "$500",
# "$1.5k", "$2M" (d3 calls a billion "G"). Under a dollar the short form would
# read "$500m" (milli), so those ticks show cents instead (MONEY_LABELS).
MONEY_AXIS = "$,.3~s"
MONEY_LABELS = ("abs(datum.value) > 0 && abs(datum.value) < 1 "
                "? format(datum.value, '$,.2f') : datum.label")


def y_axis(fmt: str, **kw) -> alt.Axis:
    """An alt.Axis with number format `fmt`; a money axis (MONEY_AXIS) also
    gets the under-a-dollar labels."""
    if fmt == MONEY_AXIS:
        kw.setdefault("labelExpr", MONEY_LABELS)
    return alt.Axis(format=fmt, **kw)


def clip_range(df: pd.DataFrame, tcol: str, days: int | None) -> pd.DataFrame:
    """Rows within `days` of the most recent point. `days=None` returns all."""
    if days is None or df.empty:
        return df
    cutoff = df[tcol].max() - pd.to_timedelta(int(days), unit="D")
    return df[df[tcol] >= cutoff]


def window(df: pd.DataFrame, tcol: str, days: int | None, *, min_points: int = 2):
    """Clip to the last `days`. If that leaves fewer than `min_points` rows
    (e.g. "1D" against once-a-day bars), fall back to the last `min_points` rows
    — never the whole history. Returns (rows, fell_back)."""
    if df.empty or days is None:
        return df, False
    clipped = clip_range(df, tcol, days)
    if len(clipped) >= min_points:
        return clipped, False
    return df.sort_values(tcol).tail(min_points), True


def window_change(df: pd.DataFrame, tcol: str, ycol: str):
    """(first, last, pct_change) across the rows given (already range-clipped)."""
    s = df.dropna(subset=[ycol]).sort_values(tcol)
    if s.empty:
        return None, None, None
    first, last = float(s[ycol].iloc[0]), float(s[ycol].iloc[-1])
    pct = ((last - first) / first * 100.0) if first else None
    return first, last, pct


# moving-average overlay styling: window -> (colour, dash pattern)
MA_STYLE = {20: ("#f59e0b", [1, 0]), 50: ("#a78bfa", [5, 3]), 200: ("#64748b", [2, 2])}


def line(df: pd.DataFrame, *, x: str, y: str, y_title: str, y_format: str,
         color: str | None = None, color_scale=None, line_color: str | None = None,
         tooltip=None, overlays=None, mask: bool = False, compress_gaps: bool = False,
         height: int = 320, daily: bool = False):
    """Layered chart: a smooth gridded line (no permanent point markers), a
    nearest-date hover rule, and an emphasised dot that only appears at the
    hovered date. `tooltip` is a list of alt.Tooltip. `overlays` is a list of
    (column, colour, dash) drawn as thin dashed lines. `mask=True` hides the
    y-axis tick labels (privacy mode). `line_color` sets a single fixed colour
    for the whole line (use this, not `color`, when there's only one series —
    `color`/`color_scale` are for colouring by a categorical column instead.

    `compress_gaps=True` spaces points evenly by *sequence* instead of by
    elapsed time, so market-closed stretches (overnight, weekends) don't
    stretch the chart out of proportion to how much trading actually
    happened — the same trick real stock-chart tools use for intraday data.
    `x` must already be sorted ascending; only meaningful for intraday
    resolutions (daily bars have no large gaps to compress).

    `compress_gaps=True` spaces points evenly by *sequence* instead of by
    elapsed time, so market-closed stretches (overnight, weekends) don't
    stretch the chart out of proportion to how much trading actually
    happened — the same trick real stock-chart tools use for intraday data.
    `x` must already be sorted ascending; only meaningful for intraday
    resolutions (daily bars have no large gaps to compress).

    `daily=True` (one point a day): the time axis shows days only - never
    hours between two daily closes - with a tick on each day when there are
    only a few.
    """
    df = df.sort_values(x).reset_index(drop=True)
    grid = dict(grid=True, gridOpacity=0.25, gridDash=[2, 2])

    if compress_gaps:
        df = df.copy()
        # Include the year only if the window actually spans more than one -
        # otherwise it's dead weight on every label (1D/5D/1M never cross a
        # year boundary; 1Y/All sometimes do, and "Apr 01" / "Feb 17" with no
        # year looks like the axis is out of order when it's really just Apr
        # of one year followed by Feb of the next).
        fmt = ("%b %d %H:%M" if df[x].dt.year.nunique() <= 1 else "%b %d '%y %H:%M")
        df["_x"] = df[x].dt.strftime(fmt)  # unique per bar at our finest (1-min) resolution
        x_field, x_type = "_x", "O"
        x_axis = alt.Axis(labelAngle=-40, **grid)
        x_sort = df["_x"].tolist()  # explicit chronological order (row order), not alphabetical
    elif daily:
        x_field, x_type = x, "T"
        few = len(df) <= 8
        x_axis = alt.Axis(format="%b %d", formatType="utc", **grid,
                          **({"values": [int(pd.Timestamp(t).timestamp() * 1000)
                                         for t in df[x]]} if few else {}))
        x_sort = "ascending"
    else:
        x_field, x_type = x, "T"
        x_axis = alt.Axis(**grid)
        x_sort = "ascending"

    x_key = f"{x_field}:{x_type}"
    enc = {
        "x": alt.X(x_key, title=None, sort=x_sort, axis=x_axis),
        "y": alt.Y(f"{y}:Q", title=y_title, scale=alt.Scale(zero=False),
                   axis=y_axis(y_format, labels=not mask, **grid)),
    }
    if color is not None:
        enc["color"] = (alt.Color(f"{color}:N", title="Point source", scale=color_scale)
                        if color_scale is not None else alt.Color(f"{color}:N", title=None))
    elif line_color is not None:
        enc["color"] = alt.value(line_color)

    base = alt.Chart(df).encode(**enc)
    layers = [base.mark_line(point=False, interpolate="monotone")]

    for col, colour, dash in (overlays or []):
        layers.append(alt.Chart(df).mark_line(strokeDash=dash, strokeWidth=1.5, opacity=0.8)
                      .encode(x=alt.X(x_key, sort=x_sort), y=alt.Y(f"{col}:Q"), color=alt.value(colour)))

    nearest = alt.selection_point(nearest=True, on="pointerover", fields=[x_field],
                                  empty=False, clear="pointerout")
    layers.append(alt.Chart(df).mark_rule(color="#94a3b8", strokeWidth=1)
                  .encode(x=alt.X(x_key, sort=x_sort), opacity=alt.condition(nearest, alt.value(0.7), alt.value(0))))
    layers.append(base.mark_point(size=90, filled=True)
                  .encode(opacity=alt.condition(nearest, alt.value(1), alt.value(0))))
    layers.append(alt.Chart(df).mark_rule(strokeWidth=24)
                  .encode(x=alt.X(x_key, sort=x_sort), opacity=alt.value(0),
                          tooltip=tooltip if tooltip is not None else [])
                  .add_params(nearest))

    return alt.layer(*layers).properties(height=height)


def projection(df: pd.DataFrame, *, target: float | None, color: str, mask: bool = False,
               tooltip=None, height: int = 300, marks: pd.DataFrame | None = None,
               dawn: str = "#f0b23c", dip: str = "#74838f") -> alt.LayerChart:
    """Goal projection: the low-high range as a band, the assumed return as a
    line, and the goal (if any) as a dashed rule. `df` has date / low / mid /
    high. Same hover as line(): a rule and dot at the nearest month, with
    `tooltip` on a wide invisible hit target. `marks` (plans.out_markers:
    date / kind / label) draws money going out: a dotted rule at each
    planned expense, and a dawn-coloured one where income starts (dawn is
    for arriving)."""
    grid = dict(grid=True, gridOpacity=0.25, gridDash=[2, 2])
    x = alt.X("date:T", title=None, axis=alt.Axis(**grid))
    money_axis = y_axis(MONEY_AXIS, labels=not mask, **grid)
    base = alt.Chart(df)
    layers = [
        base.mark_area(opacity=0.18, color=color).encode(
            x=x, y=alt.Y("low:Q", title=None, axis=money_axis), y2="high:Q"),
        base.mark_line(strokeWidth=2, color=color).encode(x=x, y="mid:Q"),
    ]
    if target is not None:
        layers.append(alt.Chart(pd.DataFrame({"target": [target]})).mark_rule(
            strokeDash=[6, 4], strokeWidth=1.5, color="#8a8a86").encode(y="target:Q"))
    if marks is not None and len(marks):
        m = alt.Chart(marks)
        mx = alt.X("date:T")
        tips = [alt.Tooltip("label:N", title="Planned"),
                alt.Tooltip("date:T", title="When", format="%b %Y")]
        layers.append(m.transform_filter("datum.kind == 'expense'").mark_rule(
            strokeDash=[2, 3], strokeWidth=1.5, color=dip).encode(x=mx, tooltip=tips))
        income = m.transform_filter("datum.kind == 'income'")
        layers.append(income.mark_rule(strokeWidth=2.5, color=dawn).encode(x=mx, tooltip=tips))
        layers.append(income.mark_text(align="left", baseline="top", dx=5, dy=4, color=dawn,
                                       fontWeight="bold").encode(x=mx, y=alt.value(0),
                                                                 text="label:N"))
    nearest = alt.selection_point(nearest=True, on="pointerover", fields=["date"],
                                  empty=False, clear="pointerout")
    layers.append(base.mark_rule(color="#94a3b8", strokeWidth=1).encode(
        x=x, opacity=alt.condition(nearest, alt.value(0.7), alt.value(0))))
    layers.append(base.mark_point(size=90, filled=True, color=color).encode(
        x=x, y="mid:Q", opacity=alt.condition(nearest, alt.value(1), alt.value(0))))
    layers.append(base.mark_rule(strokeWidth=24).encode(
        x=x, opacity=alt.value(0), tooltip=tooltip if tooltip is not None else []
    ).add_params(nearest))
    return alt.layer(*layers).properties(height=height)


def money_in_chart(df: pd.DataFrame, *, money_color: str, value_color: str,
                   mask: bool = False, height: int = 240) -> alt.LayerChart:
    """Money in (filled) with total value (line) over it, one point per
    statement; the gap between them is growth, or a loss when the line dips
    below. `df` has date / money_in / value. Not stacked: growth can be
    negative, and a stack would draw a loss below zero."""
    long = df.melt(id_vars=["date"], value_vars=["money_in", "value"], var_name="k", value_name="v")
    long["series"] = long["k"].map({"money_in": "Money in", "value": "Value"})
    grid = dict(grid=True, gridOpacity=0.25, gridDash=[2, 2])
    # label by year over long spans (Vega's default names only the month)
    span = (df["date"].max() - df["date"].min()).days if len(df) else 0
    x_fmt = {"format": "%Y"} if span > 730 else {"format": "%b %Y"} if span > 60 else {}
    color = alt.Color("series:N", title=None, legend=alt.Legend(orient="top"),
                      scale=alt.Scale(domain=["Money in", "Value"], range=[money_color, value_color]))
    enc = dict(x=alt.X("date:T", title=None, axis=alt.Axis(**grid, **x_fmt)),
               y=alt.Y("v:Q", title=None, axis=y_axis(MONEY_AXIS, labels=not mask, **grid)),
               color=color,
               tooltip=[alt.Tooltip("date:T", title="Statement", format="%b %d, %Y"), "series:N"]
               + ([] if mask else [alt.Tooltip("v:Q", title="Amount", format="$,.2f")]))
    base = alt.Chart(long).encode(**enc)
    return alt.layer(
        base.transform_filter("datum.series == 'Money in'").mark_area(opacity=0.3, line=True),
        base.transform_filter("datum.series == 'Value'").mark_line(strokeWidth=2, point=True),
    ).properties(height=height)
