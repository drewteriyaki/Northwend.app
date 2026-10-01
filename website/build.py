"""Builds the Northwend website into website/public/, which Cloudflare Pages
serves at northwend.app (no build step there: public/ is committed).

    python website/build.py

Plain HTML and CSS, no JavaScript. Pages are templates/base.html around each
page's content; the About page is made from disclosures.py, so the website
and the app's About page say the same thing (a test checks public/ is up to
date). The fonts come from the app's own static/ folder. Change APP_URL here
when the app moves (ROADMAP L4).
"""

from __future__ import annotations

import html
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import disclosures  # noqa: E402

SITE_URL = "https://northwend.app"
APP_URL = "https://portfoliotracker-kh8dkygevdqrwwcg4fdcok.streamlit.app/"  # the live app (Streamlit Community Cloud)
SIGNUP_URL = APP_URL + "?signup=1"                # opens the app's Create account form
FONTS = ("Figtree-Variable-latin.woff2", "Newsreader-Variable-latin.woff2")
COPYRIGHT_YEAR = "2026"   # fixed, so a rebuild in a new year changes nothing by itself

CHECK = ('<svg class="check" width="20" height="20" viewBox="0 0 24 24" fill="none" '
         'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
         'aria-hidden="true"><path d="M5 12l5 5 9-10"></path></svg>')

PAGES = {
    # output file: (template, title, description, path on the site)
    "index.html": ("home.html", "Northwend · Your guide from first step to goal",
                   "Follow your investments from any brokerage, set a goal, and get there one "
                   "waypoint at a time with a guide who explains everything in plain language.",
                   "/"),
    "about.html": ("about.html", "About and disclosures · Northwend",
                   "What Northwend is, what it stores, what's sent to the AI, and who runs it.",
                   "/about"),
    "404.html": ("404.html", "Page not found · Northwend",
                 "This page isn't on the map.", "/404"),
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _inline(text: str) -> str:
    """Escape, then the two bits of markdown disclosures.py uses: **bold**
    and the contact address (made a mailto link)."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    if disclosures.CONTACT:
        out = out.replace(disclosures.CONTACT,
                          f'<a href="mailto:{disclosures.CONTACT}">{disclosures.CONTACT}</a>')
    return out


def markdown_blocks(text: str) -> str:
    """disclosures.py's markdown as HTML: paragraphs, and lists whose items
    start with "- " and continue on indented lines."""
    parts = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        if lines[0].startswith("- "):
            items: list[str] = []
            for line in lines:
                if line.startswith("- "):
                    items.append(line[2:].strip())
                else:
                    items[-1] += " " + line.strip()
            parts.append("<ul>\n" + "\n".join(f"<li>{_inline(i)}</li>" for i in items) + "\n</ul>")
        else:
            parts.append(f"<p>{_inline(' '.join(l.strip() for l in lines))}</p>")
    return "\n".join(parts)


def about_values() -> dict:
    sections, toc = [], []
    for title, body in disclosures.SECTIONS:
        sid = slug(title)
        toc.append(f'<a href="#{sid}">{html.escape(title)}</a>')
        sections.append(f'<h2 id="{sid}">{html.escape(title)}</h2>\n{markdown_blocks(body)}')
    toc.append('<a href="#contact">Contact</a>')
    return {"SUMMARY": _inline(disclosures.SUMMARY), "TOC": "\n".join(toc),
            "SECTIONS": "\n".join(sections), "CONTACT": disclosures.CONTACT,
            "OPERATOR": html.escape(disclosures.OPERATOR_NAME),
            "LAST_UPDATED": html.escape(disclosures.LAST_UPDATED)}


def _fill(template: str, values: dict) -> str:
    def sub(m):
        if m.group(1) not in values:
            raise KeyError(f"no value for {{{{{m.group(1)}}}}}")
        return values[m.group(1)]
    return re.sub(r"\{\{([A-Z_]+)\}\}", sub, template)


def render() -> dict[str, str]:
    """Every text file of the site: {path under public/: content}."""
    with open(os.path.join(HERE, "templates", "base.html"), encoding="utf-8") as fh:
        base = fh.read()
    common = {"APP_URL": APP_URL, "SIGNUP_URL": SIGNUP_URL, "CHECK": CHECK,
              "YEAR": COPYRIGHT_YEAR}
    out = {}
    for name, (template, title, description, path) in PAGES.items():
        with open(os.path.join(HERE, "templates", template), encoding="utf-8") as fh:
            content = fh.read()
        values = dict(common)
        if name == "about.html":
            values.update(about_values())
        page = _fill(base, {**common, "TITLE": html.escape(title),
                            "DESCRIPTION": html.escape(description),
                            "CANONICAL": SITE_URL + path,
                            "CONTENT": _fill(content, values)})
        out[name] = page
    for name in os.listdir(os.path.join(HERE, "assets")):
        if name.endswith((".css", ".svg", ".txt")) or name == "_headers":
            with open(os.path.join(HERE, "assets", name), encoding="utf-8") as fh:
                out[name] = fh.read()
    return out


def build(out_dir: str = os.path.join(HERE, "public")) -> list[str]:
    """Write the site to out_dir and remove any file there the build no longer
    makes. Folders are kept, not recreated: on Windows (and OneDrive) a folder
    something has open can't be deleted. Returns the paths written."""
    os.makedirs(os.path.join(out_dir, "fonts"), exist_ok=True)
    written = []
    for name, text in render().items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        written.append(name)
    for font in FONTS:
        shutil.copyfile(os.path.join(REPO, "static", font), os.path.join(out_dir, "fonts", font))
        written.append(f"fonts/{font}")
    for folder, _, files in os.walk(out_dir):
        for name in files:
            rel = os.path.relpath(os.path.join(folder, name), out_dir).replace(os.sep, "/")
            if rel not in written:
                os.remove(os.path.join(folder, name))
    return written


if __name__ == "__main__":
    for path in build():
        print("wrote", path)
