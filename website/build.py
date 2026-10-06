"""Builds the Northwend website into website/public/, which Cloudflare Pages
serves at northwend.app (no build step there: public/ is committed).

    python website/build.py

Plain HTML and CSS, no JavaScript. Pages are templates/base.html around each
page's content; the About page is made from disclosures.py, so the website
and the app's About page say the same thing (a test checks public/ is up to
date). The fonts come from the app's own static/ folder. Change APP_URL here
when the app moves (ROADMAP L4).

The "calculators" are tables worked out here at build time (the CSP allows
no scripts): what a monthly amount could grow to, and what a fund's yearly
fee costs over time - always at one stated, hypothetical rate.
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
APP_URL = "https://go.northwend.app/"  # the live app (Render, behind Cloudflare)
SIGNUP_URL = APP_URL + "?signup=1"                # opens the app's Create account form
ADVISOR_SIGNUP_URL = APP_URL + "?signup=advisor"  # ...with "I'm a financial advisor" chosen
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
    "new-to-investing.html": ("new-to-investing.html", "New to investing? Start here · Northwend",
                              "Never invested before? Learn the basics in short steps, try it "
                              "with practice money, then open an account and make a first "
                              "investment - with a guide that never sells you anything.",
                              "/new-to-investing"),
    "advisors.html": ("advisors.html", "For financial advisors · Northwend",
                      "Bring your clients along: setup links, one view of every client, "
                      "proposals, meeting prep and progress reports - clients bring holdings "
                      "from any brokerage.",
                      "/advisors"),
    "decode-401k.html": ("decode-401k.html", "Decode your 401(k) menu · Northwend",
                         "Paste your workplace plan's fund list and see what kind of fund each "
                         "one is and what it charges - free, no account, nothing saved.",
                         "/decode-401k"),
    "about.html": ("about.html", "About and disclosures · Northwend",
                   "What Northwend is, what it stores, what's sent to the AI, and who runs it.",
                   "/about"),
    "terms.html": ("legal.html", "Terms of Use · Northwend",
                   "The terms for using Northwend: education, not advice; free, with no ads "
                   "or commissions; what's yours and what we promise.",
                   "/terms"),
    "privacy.html": ("legal.html", "Privacy Policy · Northwend",
                     "What Northwend keeps, what it never keeps, who it's shared with, what's "
                     "sent to the AI, and how to see, download or delete it.",
                     "/privacy"),
    "404.html": ("404.html", "Page not found · Northwend",
                 "This page isn't on the map.", "/404"),
}

# written and tested, but not on the site yet: the no-account decoder's page
# waits for its route (flag decoder_public, switched on after the hosting
# move, PLAN step 4). Take a name out of HELD to publish it.
HELD = {"decode-401k.html"}
PUBLISHED = {k: v for k, v in PAGES.items() if k not in HELD}


# the header's links: (label, path); the current page's link is marked
NAV = (("New to investing", "/new-to-investing"), ("For advisors", "/advisors"),
       ("Privacy", "/#privacy"))

# the worked-out tables: one hypothetical yearly growth rate, stated beside them
RATE = 0.06
MONTHLY = (100, 250, 500)
YEARS = (10, 20, 30)
FEE_START, FEE_YEARS = 10_000, 30
FEES = (0.0005, 0.005, 0.01)   # 0.05% (a broad index fund), 0.5%, 1%


def grown(monthly: float, years: int, rate: float = RATE) -> float:
    """What `monthly` put in at the end of every month for `years` grows to,
    growing `rate` a year (compounded monthly)."""
    i, n = rate / 12, years * 12
    return monthly * ((1 + i) ** n - 1) / i


def after_fees(start: float, years: int, fee: float, rate: float = RATE) -> float:
    """`start` left alone for `years`, growing `rate` a year less a yearly `fee`."""
    return start * (1 + rate - fee) ** years


def money(v: float, nearest: int = 100) -> str:
    """$16,400: rounded, so the tables don't look more exact than they are."""
    return f"${round(v / nearest) * nearest:,.0f}"


def growth_table() -> str:
    head = "".join(f'<th scope="col">{y} years</th>' for y in YEARS)
    rows = []
    for m in MONTHLY:
        cells = "".join(
            f"<td><strong>{money(grown(m, y))}</strong>"
            f'<span class="cell-sub">you put in {money(m * 12 * y)}</span></td>' for y in YEARS)
        rows.append(f'<tr><th scope="row">${m} a month</th>{cells}</tr>')
    return (f'<table class="calc"><caption class="small muted">Growing {RATE:.0%} a year, '
            f'every month\'s amount invested on the same day.</caption>'
            f'<thead><tr><td></td>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>')


def fee_table() -> str:
    best = after_fees(FEE_START, FEE_YEARS, FEES[0])
    rows = []
    for fee in FEES:
        end = after_fees(FEE_START, FEE_YEARS, fee)
        cost = "-" if fee == FEES[0] else f"{money(best - end)} less"
        rows.append(f'<tr><th scope="row">{fee * 100:.2f}% a year</th>'
                    f"<td><strong>{money(end)}</strong></td><td>{cost}</td></tr>")
    return (f'<table class="calc"><caption class="small muted">{money(FEE_START, 1)} left '
            f"alone for {FEE_YEARS} years, growing {RATE:.0%} a year before the fee.</caption>"
            '<thead><tr><th scope="col">Yearly fund fee</th><th scope="col">After '
            f'{FEE_YEARS} years</th><th scope="col">Compared with the lowest</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def contours() -> str:
    """The app's own contour lines (static/topo-light.svg) drawn inline in
    currentColor, so the site and the app share one map and its colour
    follows the theme (--contour in styles.css)."""
    with open(os.path.join(REPO, "static", "topo-light.svg"), encoding="utf-8") as fh:
        paths = re.findall(r'<path d="([^"]+)"/>', fh.read())
    return ('<svg class="contours" viewBox="0 0 1400 1000" preserveAspectRatio="xMidYMin slice" '
            'fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true" '
            'focusable="false">' + "".join(f'<path d="{d}"></path>' for d in paths) + "</svg>")


def nav_links(path: str) -> str:
    return "\n".join(f'<a class="nav-link" href="{href}"'
                     + (' aria-current="page"' if href == path else "") + f">{label}</a>"
                     for label, href in NAV)


def sitemap() -> str:
    urls = "".join(f"<url><loc>{SITE_URL}{path}</loc></url>"
                   for _, _, _, path in PUBLISHED.values() if path != "/404")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')


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


# The Terms of Use and the Privacy Policy: markdown in docs/legal/ (the copies
# people read; the -DRAFT files beside them are the lawyer's working copies,
# written for after the hosting move). Their {{NAMES}} are filled from
# disclosures.py, so the operator, the contact, the date (the version people
# agree to at sign-up is disclosures.LAST_UPDATED) and the app's host stay the
# same everywhere - the host rows change by themselves when HOST_MOVED does.
LEGAL = {"terms.html": "terms-of-use.md", "privacy.html": "privacy-policy.md"}


def host_rows(moved: bool | None = None) -> str:
    """The Privacy Policy's table rows for who hosts the app and the website."""
    moved = disclosures.HOST_MOVED if moved is None else moved
    if moved:
        return ("| **Render** | Hosts the app (go.northwend.app), in the United States (Ohio) "
                "| Requests to the app, your IP address, server logs |\n"
                "| **Cloudflare** | Serves the website northwend.app (Pages), and sits in front "
                "of the app: every connection to go.northwend.app passes through it, and it "
                "adds security settings | Visitors' IP address and browser details; for the "
                "app, the requests and pages passing through it on their way |")
    return ("| **Streamlit Community Cloud** | Hosts the app today. It's moving to Render (in "
            "the United States), with Cloudflare in front of it; this policy will say so "
            "when it has | Requests to the app, your IP address, server logs |\n"
            "| **Cloudflare** | Serves the website, northwend.app (Pages) | Visitors' IP "
            "address and browser details |")


def where_app_runs(moved: bool | None = None) -> str:
    moved = disclosures.HOST_MOVED if moved is None else moved
    if moved:
        return "The app runs on Render, in the United States (Ohio)."
    return ("The app is hosted by Streamlit Community Cloud today, and is moving to Render, "
            "in the United States.")


def legal_text(name: str, moved: bool | None = None) -> str:
    """A legal page's markdown with its {{NAMES}} filled in."""
    with open(os.path.join(REPO, "docs", "legal", LEGAL[name]), encoding="utf-8") as fh:
        text = fh.read()
    return _fill(text, {"EFFECTIVE": disclosures.LAST_UPDATED,
                        "OPERATOR": disclosures.OPERATOR_NAME,
                        "CONTACT": disclosures.CONTACT,
                        "HOST_ROWS": host_rows(moved), "WHERE_APP_RUNS": where_app_runs(moved),
                        # "stored encrypted" only once disclosures.TWO_STEP_ENCRYPTED is True
                        "TWO_STEP_KEY": disclosures.two_step_key_words()})


def _doc_inline(text: str) -> str:
    """_inline, plus [links](to)."""
    out = _inline(text)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)


def _doc_table(lines: list[str]) -> str:
    def cells(line):
        return [c.strip() for c in line.strip().strip("|").split("|")]
    head = "".join(f'<th scope="col">{_doc_inline(c)}</th>' for c in cells(lines[0]))
    body = "".join("<tr>" + "".join(
        (f'<th scope="row">{_doc_inline(c)}</th>' if i == 0 else f"<td>{_doc_inline(c)}</td>")
        for i, c in enumerate(cells(line))) + "</tr>" for line in lines[2:])
    return (f'<div class="calc-wrap"><table class="calc doc-table"><thead><tr>{head}</tr>'
            f"</thead><tbody>{body}</tbody></table></div>")


def legal_html(markdown: str) -> str:
    """The legal pages' markdown as HTML: a # title, ## sections (with a list
    of them after the lines under the title), paragraphs, "- " lists, tables,
    **bold** and [links](to). Lines that each start with **Label:** stay on
    lines of their own."""
    parts, toc = [], []
    for block in re.split(r"\n\s*\n", markdown.strip()):
        lines = block.split("\n")
        first = lines[0]
        if first.startswith("# "):
            parts.append(f'<h1 id="legal-title" class="display">{_doc_inline(first[2:])}</h1>')
        elif first.startswith("## "):
            title = first[3:].strip()
            sid = slug(re.sub(r"^\d+\.\s*", "", title))
            toc.append(f'<a href="#{sid}">{html.escape(title)}</a>')
            parts.append(f'<h2 id="{sid}">{_doc_inline(title)}</h2>')
        elif first.startswith("|"):
            parts.append(_doc_table(lines))
        elif first.startswith("- "):
            items: list[str] = []
            for line in lines:
                if line.startswith("- "):
                    items.append(line[2:].strip())
                else:
                    items[-1] += " " + line.strip()
            parts.append("<ul>\n" + "\n".join(f"<li>{_doc_inline(i)}</li>" for i in items)
                         + "\n</ul>")
        elif all(re.match(r"\*\*[^*]+:\*\*", line) for line in lines):
            parts.append('<p class="summary">' + "<br>\n".join(_doc_inline(line.strip())
                                                               for line in lines) + "</p>")
        else:
            parts.append(f"<p>{_doc_inline(' '.join(line.strip() for line in lines))}</p>")
    nav = '<nav class="toc" aria-label="On this page">\n' + "\n".join(toc) + "\n</nav>"
    # the list of sections goes after the title and the lines under it
    parts.insert(2, nav)
    return "\n".join(parts)


def _fill(template: str, values: dict) -> str:
    def sub(m):
        if m.group(1) not in values:
            raise KeyError(f"no value for {{{{{m.group(1)}}}}}")
        return values[m.group(1)]
    return re.sub(r"\{\{([A-Z_]+)\}\}", sub, template)


def render(include_held: bool = False) -> dict[str, str]:
    """Every text file of the site: {path under public/: content}. With
    include_held, the HELD pages too (for their tests; never written)."""
    with open(os.path.join(HERE, "templates", "base.html"), encoding="utf-8") as fh:
        base = fh.read()
    common = {"APP_URL": APP_URL, "SIGNUP_URL": SIGNUP_URL,
              "ADVISOR_SIGNUP_URL": ADVISOR_SIGNUP_URL, "CHECK": CHECK,
              "YEAR": COPYRIGHT_YEAR, "GROWTH_TABLE": growth_table(),
              "FEE_TABLE": fee_table(), "RATE": f"{RATE:.0%}", "CONTOURS": contours()}
    out = {}
    for name, (template, title, description, path) in (
            PAGES if include_held else PUBLISHED).items():
        with open(os.path.join(HERE, "templates", template), encoding="utf-8") as fh:
            content = fh.read()
        values = dict(common)
        if name == "about.html":
            values.update(about_values())
        if name in LEGAL:
            values["LEGAL"] = legal_html(legal_text(name))
        page = _fill(base, {**common, "TITLE": html.escape(title), "NAV": nav_links(path),
                            "DESCRIPTION": html.escape(description),
                            "CANONICAL": SITE_URL + path,
                            "CONTENT": _fill(content, values)})
        out[name] = email_off(page)
    out["sitemap.xml"] = sitemap()
    for name in os.listdir(os.path.join(HERE, "assets")):
        if name.endswith((".css", ".svg", ".txt")) or name == "_headers":
            with open(os.path.join(HERE, "assets", name), encoding="utf-8") as fh:
                out[name] = fh.read()
    return out


_MAILTO = re.compile(r'<a\b[^>]*href="mailto:[^"]*"[^>]*>.*?</a>', re.S)


def email_off(page: str) -> str:
    """Wrap every email link in Cloudflare's email_off markers. Cloudflare's
    "Email Address Obfuscation" otherwise swaps addresses for "[email
    protected]" and a decoding script - which the site's CSP blocks, so the
    address never shows."""
    return _MAILTO.sub(lambda m: f"<!--email_off-->{m.group(0)}<!--/email_off-->", page)


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
