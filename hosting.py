"""Running the app on its own host (L4: app.northwend.app on Render) as well
as on Streamlit Community Cloud. Pure logic, no Streamlit.

Two settings, both environment variables:

- CLIENT_IP_HEADER - which request header holds the visitor's real address
  when the app sits behind a proxy. Unset (Community Cloud, local runs), the
  address Streamlit sees is used. On Render: "x-forwarded-for" (Render adds
  the address it saw at the right-hand end; anything to its left came from
  the visitor and can't be trusted). Behind Cloudflare's proxy as well:
  "cf-connecting-ip". Sign-up, confirm and reset limits count per address,
  so behind a proxy without this every visitor looks the same.
- MOVED_TO - set on the old address once the app has moved: every page then
  only says where Northwend is now, with a link that keeps the ?query (so an
  old confirm or reset link in someone's inbox still works there).
"""

from __future__ import annotations

import os
from urllib.parse import urlencode


def _setting(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def client_ip(headers, fallback: str | None, header: str | None = None) -> str | None:
    """The visitor's address: from `header` (default CLIENT_IP_HEADER) when
    it's set and present, otherwise `fallback` (st.context.ip_address)."""
    name = (header if header is not None else _setting("CLIENT_IP_HEADER")).lower()
    if not name:
        return fallback
    value = ""
    try:
        value = (headers.get(name) or "").strip()
    except AttributeError:
        pass
    if not value:
        return fallback
    if name == "x-forwarded-for":
        value = value.split(",")[-1].strip()   # the one the proxy added
    return value or fallback


def moved_to() -> str:
    """The app's new address when this copy is the old one, else ""."""
    return _setting("MOVED_TO").rstrip("/")


def moved_link(new_base: str, query: dict) -> str:
    """`new_base` with this visit's ?query carried over."""
    pairs = [(k, v) for k, v in (query or {}).items() if isinstance(v, str)]
    return new_base.rstrip("/") + "/" + (("?" + urlencode(pairs)) if pairs else "")


def host_name() -> str:
    """Where this copy runs, for the Admin page's System panel."""
    if os.environ.get("RENDER"):
        return "Render"
    if os.environ.get("HOSTNAME", "").startswith("streamlit") or os.path.isdir("/mount/src"):
        return "Streamlit Community Cloud"
    return "this computer"


def version(repo: str) -> str:
    """The commit this copy runs (short), from Render's setting or the
    checkout's .git folder; "" when neither says."""
    sha = _setting("RENDER_GIT_COMMIT")
    if not sha:
        git = os.path.join(repo, ".git")
        try:
            with open(os.path.join(git, "HEAD"), encoding="utf-8") as fh:
                head = fh.read().strip()
            if head.startswith("ref: "):
                ref = head[5:]
                path = os.path.join(git, *ref.split("/"))
                if os.path.isfile(path):
                    with open(path, encoding="utf-8") as fh:
                        sha = fh.read().strip()
                else:
                    with open(os.path.join(git, "packed-refs"), encoding="utf-8") as fh:
                        sha = next((ln.split()[0] for ln in fh
                                    if ln.strip().endswith(" " + ref)), "")
            else:
                sha = head
        except OSError:
            sha = ""
    return sha[:7]
