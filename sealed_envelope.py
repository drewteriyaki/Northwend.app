"""The Sealed Envelope (ROADMAP "Someday" -> built, flag sealed_envelope):
a printable one-page PDF of the person's own Storm Drill answer
(future_notes.DRILL), to fold, seal and open on a hard day. Pure logic, no
Streamlit; views/future_notes.py offers it under the drill's answer on the
Plan's Stress test.

The page holds only the person's own words exactly as they wrote them, the
day they wrote them, a calm label for the envelope (TITLE - the roadmap's own
20%, the person's label, not a forecast) and a short fixed reminder
(REMINDER: education, never an instruction). Never a figure: no balances,
amounts, holdings, tickers, account names, email or login - render_pdf
takes nothing it could print them from. The person's name only if they tick
it. The PDF is made when they click and never saved; the only thing kept is
the day they made it (prefs PREF_MADE, a date), so Home's storm note can say
"Earlier, you made a sealed envelope for a drop like this one". Never offered
while an advisor is in a client's account, never sent to the AI.
"""

from __future__ import annotations

import re
from datetime import date

PREF_MADE = "sealed_envelope"   # prefs: the day (ISO) the person last made one
OFFER = "Make it a sealed envelope"
TITLE = "Open this when the market has fallen 20%"
REMINDER = ("You wrote this on a calm day. Read it slowly. Nothing has to be decided "
            "today.")
OFFER_LINE = ("A one-page PDF of your answer, in your own words, to print, seal and keep "
              "somewhere you'll find it. It holds no numbers about your money. It's made "
              "when you click and isn't saved anywhere.")
STORM_LINE = "Earlier, you made a sealed envelope for a drop like this one."
FOOTER = "Your own words, kept by you."

_ASCII = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": " - ",
    "…": "...", "•": "-", " ": " ", "−": "-",
})


def _latin(s) -> str:
    """The built-in PDF fonts are latin-1 only; anything else would raise."""
    text = str(s if s is not None else "").translate(_ASCII)
    return text.encode("latin-1", "replace").decode("latin-1")


def _day(d) -> str:
    """'Oct 6, 2026' from '2026-10-06'."""
    try:
        d = date.fromisoformat(str(d)[:10])
    except ValueError:
        return str(d or "")
    return f"{d:%b} {d.day}, {d.year}"


def words(note: dict | None) -> str:
    """The answer exactly as written (line breaks kept), or ''."""
    body = str((note or {}).get("body") or "")
    return re.sub(r"\r\n?", "\n", body).strip()


def render_pdf(body: str, written_on: str, *, name: str | None = None) -> bytes:
    """The envelope's page as PDF bytes: TITLE, the person's words
    (`body`), the day they wrote them (`written_on`, ISO) and REMINDER -
    and `name` only when given (the person ticked it)."""
    from fpdf import FPDF

    class _PDF(FPDF):
        def footer(self):
            self.set_y(-16)
            self.set_font("Helvetica", "I", 7.5)
            self.set_text_color(130)
            self.cell(0, 4, _latin(FOOTER), align="C")
            self.set_text_color(0)

    pdf = _PDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(28, 26, 28)
    pdf.add_page()

    pdf.set_font("Times", "B", 22)
    pdf.multi_cell(0, 10, _latin(TITLE), align="C", new_x="LMARGIN", new_y="NEXT")
    if name:
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(90)
        pdf.multi_cell(0, 5, _latin(f"For {name}"), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
    pdf.ln(10)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90)
    pdf.multi_cell(0, 5, _latin(f"What you wrote on {_day(written_on)}, when you asked "
                                "yourself what you'd do in a drop like this:"),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(4)
    pdf.set_font("Times", "", 14)
    pdf.multi_cell(0, 7.5, _latin(body), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(12)

    pdf.set_draw_color(180)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 11)
    pdf.multi_cell(0, 6, _latin(REMINDER), align="C", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def file_name() -> str:
    return "sealed-envelope.pdf"
