"""Put Northwend's name and icon on the page Streamlit serves before the app runs.

Streamlit ships its own index.html with <title>Streamlit</title> and its
favicon. The app's st.set_page_config only renames the tab once the script
has connected and run, so a visitor first sees "Streamlit" in the tab (and
keeps seeing it while the page loads). This rewrites that file in the
installed package: the title, a short description and the website's icon.

Run once after `pip install` on a host we run ourselves (render.yaml's
buildCommand). Standard library only; safe to run again (it changes nothing
the second time). If Streamlit's file ever changes shape, it says what it
couldn't find and leaves the build to carry on - the app still works.

    python scripts/brand_page.py
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "Northwend"
DESCRIPTION = "Northwend: see your investments in one calm place."
ICON_SOURCE = os.path.join(REPO, "website", "assets", "favicon.svg")
ICON_NAME = "northwend-icon.svg"   # copied next to Streamlit's own favicon.png

TITLE = re.compile(r"<title>.*?</title>", re.S)
ICON_LINK = re.compile(r'<link[^>]*rel="(?:shortcut )?icon"[^>]*>')


def static_dir() -> str | None:
    """Streamlit's static folder in the installed package, without importing it."""
    spec = importlib.util.find_spec("streamlit")
    if spec is None or not spec.submodule_search_locations:
        return None
    return os.path.join(list(spec.submodule_search_locations)[0], "static")


def brand_html(html: str) -> tuple[str, list[str]]:
    """The page with Northwend's title, description and icon, and what changed."""
    changes = []
    title = f"<title>{NAME}</title>"
    if TITLE.search(html) and title not in html:
        html = TITLE.sub(title, html, count=1)
        changes.append("title")
    link = f'<link rel="icon" type="image/svg+xml" href="./{ICON_NAME}" />'
    if link not in html and ICON_LINK.search(html):
        html = ICON_LINK.sub(link, html, count=1)
        changes.append("icon")
    meta = f'<meta name="description" content="{DESCRIPTION}" />'
    if meta not in html and "</head>" in html:
        html = html.replace("</head>", f"  {meta}\n  </head>", 1)
        changes.append("description")
    return html, changes


def brand(folder: str) -> list[str]:
    """Rewrite folder/index.html and copy the icon in. Returns what changed."""
    path = os.path.join(folder, "index.html")
    with open(path, encoding="utf-8") as fh:
        before = fh.read()
    after, changes = brand_html(before)
    shutil.copyfile(ICON_SOURCE, os.path.join(folder, ICON_NAME))
    if after != before:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(after)
    return changes


def main() -> int:
    folder = static_dir()
    if not folder or not os.path.exists(os.path.join(folder, "index.html")):
        print("brand_page: Streamlit's index.html wasn't found - left as it is.")
        return 0
    changes = brand(folder)
    missing = {"title", "icon"} - set(changes)
    with open(os.path.join(folder, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    missing = {m for m in missing
               if (m == "title" and f"<title>{NAME}</title>" not in html)
               or (m == "icon" and ICON_NAME not in html)}
    if missing:
        print("brand_page: couldn't find Streamlit's " + " and ".join(sorted(missing))
              + " - the tab may still say Streamlit while the page loads.")
    print("brand_page: " + (", ".join(changes) if changes else "already branded"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
