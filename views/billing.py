# Part of dashboard.py, which runs this file with _view("billing") at the point
# where this code sits, in dashboard.py's own namespace: the names here (st, DB,
# LOGIN_ID, IS_ADVISOR, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Paid advisor seats (billing.py; flag billing + gate L1a). Not owned by the
# flag (flags.FEATURES "billing" has no view): the names below are used by
# Your clients, proposals, reports, meeting prep and drafts, so this file
# always runs and checks flags.on("billing") itself. Off, SEAT_OPEN is True
# and nothing is read, written or shown - every seat a free beta seat.
#
# On, for an approved advisor:
# - "Your seat" on Account (_render_your_seat): status, price, founding place,
#   Subscribe (Stripe's hosted checkout) and Manage billing (Stripe's portal).
# - Back from Stripe (?billing=done, taken off the address by dashboard.py),
#   the checkout kept on the seat is checked with Stripe itself - never the
#   link - before anything changes.
# - While the seat isn't live past its grace days (SEAT_OPEN False): one plain
#   line and a way to Your seat in place of the add and send buttons
#   (_render_seat_paused), and each of those buttons' callbacks asks again
#   (_seat_ok). Reading and every export stay open; clients are never blocked.
# ruff: noqa: F821

import billing

SEAT = None          # billing.state() for the login, while billing is on
SEAT_OPEN = True     # may add clients and send (always while billing is off)
if IS_ADVISOR and flags.on("billing"):
    _bill_conn = connect(DB)
    try:
        if st.session_state.pop("billing_back", None) == "done":
            # back from Stripe's checkout: check it with Stripe, on the server
            try:
                _bill_said = billing.verify_checkout(_bill_conn, LOGIN_ID)
            except billing.BillingError:
                _bill_said = "error"
            st.session_state["seat_note"] = {
                "done": ("success", "Thank you - your seat is active."),
                "open": ("info", "Stripe hasn't confirmed the payment yet. This page checks "
                                 "again each time you open it."),
                "error": ("warning", billing.NOT_REACHED + " Your payment, if you made one, "
                                     "is safe - this page checks again when you open it."),
            }.get(_bill_said)
        SEAT = billing.state(_bill_conn, LOGIN_ID)
    finally:
        _bill_conn.close()
    SEAT_OPEN = SEAT["open"]


def _seat_ok():
    """In an add or send button's callback: may this advisor do it now? Read
    again from the database (the page may have been open a while)."""
    if not flags.on("billing"):
        return True
    c = connect(DB)
    try:
        ok = billing.can_write(c, st.session_state["user_id"])
    finally:
        c.close()
    if not ok:
        st.toast(billing.CLOSED_LINE)
    return ok


def _render_seat_paused(key):
    """One plain line, and the way to Your seat, where add and send would be."""
    with st.container(border=True):
        st.markdown(billing.CLOSED_LINE)
        st.button("Subscribe", key=f"seat_go_{key}", type="primary", icon=":material/badge:",
                  on_click=_go, args=("Account",))


def _seat_checkout():
    """Subscribe: make Stripe's checkout page for the plan picked; the next run
    shows the link to it (Streamlit can't send the browser there itself)."""
    plan = "yearly" if st.session_state.get("seat_plan") == "Yearly" else "monthly"
    c = connect(DB)
    try:
        url = billing.start_checkout(c, st.session_state["user_id"], plan, _app_address())
    except ValueError as exc:
        st.session_state["seat_note"] = ("info", str(exc))
        return
    except billing.BillingError:
        st.session_state["seat_note"] = ("warning", billing.NOT_REACHED)
        return
    finally:
        c.close()
    st.session_state["seat_link"] = ("Go to Stripe's payment page", url)


def _seat_portal():
    """Manage billing: Stripe's customer portal for this login's own seat."""
    c = connect(DB)
    try:
        url = billing.portal_url(c, st.session_state["user_id"], _app_address())
    except ValueError as exc:
        st.session_state["seat_note"] = ("info", str(exc))
        return
    except billing.BillingError:
        st.session_state["seat_note"] = ("warning", billing.NOT_REACHED)
        return
    finally:
        c.close()
    st.session_state["seat_link"] = ("Go to Stripe's billing page", url)


def _seat_check():
    """Check again: a checkout still waiting, read from Stripe."""
    c = connect(DB)
    try:
        said = billing.verify_checkout(c, st.session_state["user_id"])
    except billing.BillingError:
        said = "error"
    finally:
        c.close()
    st.session_state["seat_note"] = {
        "done": ("success", "Thank you - your seat is active."),
        "open": ("info", "Stripe hasn't confirmed the payment yet."),
        "expired": ("info", "That checkout page expired without a payment. Nothing was "
                            "charged."),
        "error": ("warning", billing.NOT_REACHED),
    }.get(said)


def _render_manual_seat(seat):
    """Your seat, for a seat the admin set by hand (billing.set_manual)."""
    from datetime import date as _date, timedelta as _td
    paid = None
    if seat["period_end"]:
        # current_period_end is the moment after the last day paid for
        paid = (_date.fromisoformat(seat["period_end"][:10]) - _td(days=1)).isoformat()
    lines = [f"**{'Active' if seat['live'] else 'Ended'}** - paid outside the app "
             f"({seat['manual']})."]
    if seat["live"] and seat["founding"]:
        lines.append(f"Founding seat (place {seat['founding_no']} of "
                     f"{billing.founding_seats()}). " + billing.FOUNDING_KEPT)
    if paid:
        lines.append(f"Paid through {_fmt_date(paid)}.")
    st.markdown("  \n".join(lines))
    if not seat["live"]:
        if seat["open"] and seat["grace_until"]:
            st.markdown(f"Adding clients and sending stay open until "
                        f"{_fmt_date(seat['grace_until'][:10])}.")
        else:
            st.markdown(billing.CLOSED_LINE)
    st.caption(billing.MANUAL_RENEW)


def _render_your_seat():
    """Account > Your seat (advisors, billing on). The login's own seat only."""
    st.subheader(billing.TITLE, anchor=False)
    c = connect(DB)
    try:
        seat = billing.state(c, LOGIN_ID)
        founding_offer = billing.offers_founding(c, LOGIN_ID)
        left = billing.founding_seats() - billing.founding_used(c)
        row = billing.seat(c, LOGIN_ID) or {}
    finally:
        c.close()
    note = st.session_state.pop("seat_note", None)
    if note:
        getattr(st, note[0])(note[1])
    st.caption(billing.WHAT_IT_IS + " " + billing.NOT_INCLUDED)
    link = st.session_state.pop("seat_link", None)
    if link:
        st.link_button(link[0], link[1], type="primary", icon=":material/open_in_new:")
    if seat["manual"]:
        # set by the admin: paid outside the app - no checkout, no portal here
        _render_manual_seat(seat)
        return
    if seat["live"]:
        plan = {"monthly": "billed monthly", "yearly": "billed yearly"}.get(seat["plan"], "")
        lines = [f"**Active**{' - ' + plan if plan else ''}."]
        if seat["founding"]:
            lines.append(f"Founding seat (place {seat['founding_no']} of "
                         f"{billing.founding_seats()}): {billing.price_words(True)}. "
                         + billing.FOUNDING_KEPT)
        if seat["period_end"]:
            lines.append(f"Paid through {_fmt_date(seat['period_end'][:10])}.")
        st.markdown("  \n".join(lines))
        if seat["status"] == "past_due":
            st.warning("The last payment didn't go through. Stripe will try again - you can "
                       "update your card under Manage billing. Your tools stay open meanwhile.")
        st.button("Manage billing", key="seat_portal", on_click=_seat_portal,
                  help="Stripe's page: change your card, switch monthly or yearly, see "
                       "invoices, or end the seat.")
        st.caption(billing.CARD_NOTE)
        return
    if not billing.configured():
        st.markdown(billing.BETA_LINE + " " + billing.NOT_SET_UP)
        return
    if seat["waiting"]:
        st.info("We're checking a payment with Stripe.")
        st.button("Check again", key="seat_check", on_click=_seat_check)
    if seat["open"] and seat["grace_until"]:
        st.markdown(f"No active seat yet. Adding clients and sending stay open until "
                    f"{_fmt_date(seat['grace_until'][:10])}.")
    elif not seat["open"]:
        st.markdown(billing.CLOSED_LINE)
    if founding_offer:
        st.markdown(f"**Founding seat:** {billing.price_words(True)}. {max(left, 0)} of "
                    f"{billing.founding_seats()} founding places left. "
                    + billing.FOUNDING_KEPT)
    else:
        st.markdown(f"**Seat:** {billing.price_words(False)}.")
    st.segmented_control("Billed", ["Monthly", "Yearly"], default="Monthly", key="seat_plan")
    with st.container(horizontal=True):
        st.button("Subscribe", key="seat_subscribe", type="primary", on_click=_seat_checkout)
        if row.get("stripe_customer"):
            st.button("Manage billing", key="seat_portal", on_click=_seat_portal,
                      help="Stripe's page: your past invoices and card.")
    st.caption(billing.CARD_NOTE + " You can end the seat at any time under Manage billing; "
               "it runs to the end of the period you paid for.")
