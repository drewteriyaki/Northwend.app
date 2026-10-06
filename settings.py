"""Northwend's settings in one place (audit 1.5b). Standard library only: the
scheduled jobs and command-line tools import it outside Streamlit.

Every setting is an environment variable - an entry in the app's Secrets on
Streamlit Community Cloud, in the Environment on Render, or a plain variable
for the GitHub jobs. Running locally, the keys can also sit in a `.env` file
beside the code (`get(..., env_file=True)`, as the email and price code have
always read them).

"Hosted" (`hosted()`) means a copy people use: on Render (`RENDER`), on
Streamlit Community Cloud (`/mount/src`), or anywhere `NORTHWEND_ENV` says
"production" or "staging". A hosted copy fails closed:
- it won't start without a Postgres `PORTFOLIO_DB` (`config_problem()`) -
  never a local SQLite file beside the code;
- no "path to a CSV on this machine" box (it would read the server's disk);
- no error details on screen, and errors are emailed to the admin.
A local run (none of the above) keeps the friendly defaults: `portfolio.db`
beside the code, the path box, and details under the error message.
"""

from __future__ import annotations

import os

import pgcompat

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
HOSTED_ENVS = ("production", "staging")   # NORTHWEND_ENV values that mean "hosted"
COMMUNITY_CLOUD_ROOT = "/mount/src"       # where Community Cloud checks the app out


def load_env(path: str = ENV_PATH) -> dict:
    """The `NAME=value` lines of a .env file ({} when there's none)."""
    env = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def get(name: str, default: str = "", *, env_file: bool = False) -> str:
    """The setting `name`, stripped, or `default` when it's unset or blank.
    env_file=True looks in the local .env file first (it wins over the
    environment there, as it always has for the email and API keys)."""
    value = (load_env(ENV_PATH).get(name) or "") if env_file else ""
    value = (value or os.environ.get(name) or "").strip()
    return value or default


def environment() -> str:
    """NORTHWEND_ENV, lower-cased: "production", "staging" or "" (local)."""
    return get("NORTHWEND_ENV").lower()


def staging() -> bool:
    """The staging copy (its own app and database; every page says so)."""
    return environment() == "staging"


def _on_community_cloud() -> bool:
    return (HERE.startswith(COMMUNITY_CLOUD_ROOT)
            or os.environ.get("HOSTNAME", "").startswith("streamlit")
            or os.path.isdir(COMMUNITY_CLOUD_ROOT))


def host() -> str:
    """Where this copy runs: "Render", "Streamlit Community Cloud" or ""
    (this computer, as far as anything says)."""
    if get("RENDER"):
        return "Render"
    if _on_community_cloud():
        return "Streamlit Community Cloud"
    return ""


def hosted() -> bool:
    """A copy people use (live or staging), not someone's own computer."""
    return bool(host()) or environment() in HOSTED_ENVS


def database(local_default: str) -> str:
    """PORTFOLIO_DB; else, running locally only, `local_default` (the
    portfolio.db file beside the code). A hosted copy never falls back to a
    local file: "" (and `config_problem()` says why)."""
    db = get("PORTFOLIO_DB")
    if db:
        return db
    return "" if hosted() else local_default


def config_problem() -> str:
    """Why this copy can't start, in one sentence for the admin - or "".
    Only a hosted copy has one: it needs a Postgres PORTFOLIO_DB. The value
    itself is never repeated (it holds the database password)."""
    if not hosted():
        return ""
    db = get("PORTFOLIO_DB")
    if not db:
        return "This copy isn't set up: PORTFOLIO_DB is missing."
    if not pgcompat.is_postgres_dsn(db):
        return ("This copy isn't set up: PORTFOLIO_DB isn't a Postgres connection string "
                "(it should start with postgresql://).")
    return ""


def show_error_details() -> bool:
    """Error details (the traceback) may show on screen: local runs only."""
    return not hosted()


def send_error_alerts() -> bool:
    """Errors are emailed to the admin (error_alerts.py): hosted copies only."""
    return hosted()


def server_files_ok() -> bool:
    """The "path to a CSV on this machine" box may show: local runs only -
    hosted, the path would be on the server's own disk."""
    return not hosted()
