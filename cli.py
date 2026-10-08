"""The console commands an installed copy gets (pyproject.toml, [project.scripts]).

    pip install -e .        # from the project folder, once

    northwend                       # the app (streamlit run dashboard.py)
    northwend-portfolio import ...  # portfolio.py: import / verify / report
    northwend-prices                # update_prices.py: Finnhub quotes
    northwend-history               # sync_history.py: Yahoo bars, dividends, fundamentals
    northwend-users list            # manage_users.py: logins, admins, AI limits
    northwend-weekly-email          # weekly_email.py: advisors' Monday email
    northwend-migrate --db <dsn>    # portfolio.py migrate: the schema, on purpose, and its version
    northwend-tidy --db <dsn>       # tidy.py: the retention schedule (nightly job)
    northwend-licence-check --db <dsn>  # licence_check.py: advisors due a license re-check

Each takes the same options as `python <script>.py` and runs that script's
main(). Like the scripts' own `__main__` blocks, a command closes any pooled
Postgres connections when it ends, so a one-shot run exits at once.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _run(main, argv):
    try:
        return main(argv)
    finally:
        import pgcompat
        pgcompat.close_all_pools()   # no-op unless a Postgres DSN was connected


def dashboard(argv=None):
    """`streamlit run dashboard.py`, with any further options passed along.
    Streamlit finds .streamlit/config.toml (the theme) next to the script, so
    it can be started from any folder."""
    from streamlit.web import cli as stcli
    args = sys.argv[1:] if argv is None else list(argv)
    sys.argv = ["streamlit", "run", os.path.join(HERE, "dashboard.py"), *args]
    return stcli.main()


def portfolio(argv=None):
    import portfolio as mod
    return _run(mod.main, argv)


def prices(argv=None):
    import update_prices
    return _run(update_prices.main, argv)


def history(argv=None):
    import sync_history
    return _run(sync_history.main, argv)


def users(argv=None):
    import manage_users
    return _run(manage_users.main, argv)


def weekly_email(argv=None):
    import weekly_email as mod
    return _run(mod.main, argv)


def migrate(argv=None):
    import portfolio as mod
    args = sys.argv[1:] if argv is None else list(argv)
    return _run(mod.main, ["migrate", *args])


def tidy(argv=None):
    import tidy as mod
    return _run(mod.main, argv)


def licence_check(argv=None):
    import licence_check as mod
    return _run(mod.main, argv)
