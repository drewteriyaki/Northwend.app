"""Friendly errors: an unexpected error shows a short "something went wrong"
message with a Try again button instead of a raw traceback.

Streamlit logs the full traceback itself (the Streamlit Cloud logs, or the
terminal locally) and then calls the run's on_script_error handler, which
this installs. A short error code is shown and logged next to the traceback,
so a user's report can be matched to the log. Running locally, the details
are also shown under an expander. The error's type and where it happened
(never its message or anyone's data) are also noted for the admin, who is
emailed at most once an hour per kind (error_alerts.py).

A save the page catches itself (a database error, rolled back) shows the
same kind of calm message with a code: save_failed().

on_script_error is set on the run's context (Streamlit 1.62+). If a future
Streamlit drops it, install() returns False and the default error box shows.
"""

from __future__ import annotations

import secrets
import sys
import traceback

import streamlit as st

MESSAGE = ("Something went wrong on this page. Try again, or open another page from "
           "the menu. If it keeps happening, mention error code **{ref}**.")
# a save that failed and was rolled back (save_failed): the same calm words,
# never the database's own error text (it can carry SQL and the row's values)
SAVE_MESSAGE = ("{what} didn't work, so nothing was changed. Try again in a moment. If it "
                "keeps happening, mention error code **{ref}**.")

# install()'s alert settings, for save_failed (the same for every run of this copy)
_alert: dict = {}


def install(*, show_details: bool = False, alert_db: str | None = None,
            copy: str = "", send_alerts: bool = True) -> bool:
    """Use the friendly message for any error in this run. show_details adds
    the traceback under an expander (for local use only). With alert_db, the
    error is also noted there and the admin emailed (error_alerts.py, at most
    once an hour per kind; send_alerts=False only notes it). copy names this
    copy of the app in the email (Live, Staging)."""
    alert = {"db": alert_db, "copy": copy, "send": send_alerts}
    _alert.clear()
    _alert.update(alert)   # save_failed() reports with these whatever happens below
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx
        ctx = get_script_run_ctx()
    except Exception:
        return False
    if ctx is None or not hasattr(ctx, "on_script_error"):
        return False
    handler = lambda ex: _show(ex, show_details, alert)  # noqa: E731
    ctx.on_script_error = handler
    # A click starts a new run whose button callbacks run before any page
    # code, so this run's setting would come too late for them. The browser
    # session hands its handler to each new run - set it there as well (best
    # effort: private to Streamlit, so skipped quietly if it ever changes).
    try:
        from streamlit.runtime import Runtime
        if Runtime.exists():
            info = Runtime.instance()._session_mgr.get_session_info(ctx.session_id)
            if info is not None and hasattr(info.session, "_on_script_error"):
                info.session._on_script_error = handler
    except Exception:
        pass
    return True


def _report(ex: BaseException, ref: str, alert: dict | None) -> None:
    if alert and alert.get("db"):
        try:  # in the background, and never a second error
            import error_alerts
            error_alerts.report(alert["db"], ex, ref=ref, copy=alert.get("copy") or "",
                                send=alert.get("send", True))
        except Exception:
            pass


def save_failed(ex: BaseException, what: str = "Saving") -> str:
    """For a save that was caught and rolled back (a DBError on Save): logs
    it with a short error code, notes it for the admin like any error (type
    and place only), and returns the calm message to show - never the
    exception's own text. `what` starts the sentence ("Saving", "Removing it")."""
    ref = secrets.token_hex(3)
    try:
        traceback.print_exception(ex, file=sys.stderr)   # the details stay in the log
    except Exception:
        pass
    print(f"error code {ref}: {type(ex).__name__} (save failed, traceback just above)",
          file=sys.stderr)
    _report(ex, ref, _alert)
    return SAVE_MESSAGE.format(what=what, ref=ref)


def _show(ex: Exception, show_details: bool, alert: dict | None = None) -> bool:
    ref = secrets.token_hex(3)
    # Streamlit has just logged the full traceback; this ties the code to it.
    print(f"error code {ref}: {type(ex).__name__} (traceback just above)", file=sys.stderr)
    _report(ex, ref, alert)
    st.error(MESSAGE.format(ref=ref), icon=":material/error:")
    st.button("Try again", key="pt_error_retry", type="primary")
    if show_details:
        with st.expander("Details (shown only when running locally)"):
            st.exception(ex)
    return True  # handled: don't show Streamlit's own error box
