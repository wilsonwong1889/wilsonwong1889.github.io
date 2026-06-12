"""Generate the public "How to use the Studio Booking site" PDF guide.

Branded to match the website header / receipt (Arts Marvels × BIPOC Foundation).
Content is kept in sync with the live FAQ, Pricing, Reserve and Staff pages.

The booking walkthrough uses annotated screenshots of the live site, stored in
media/guide/ (step1-rooms.png … step9-receipt.png). They were captured with
Playwright against production and annotated with red arrows/badges; regenerate
them with scripts/guide_capture.py + scripts/guide_annotate.py if the UI changes.

Usage:
    python -m scripts.build_user_guide            # writes the default output
    python -m scripts.build_user_guide out.pdf    # custom path

The default output lands in the frontend media folder so it is served at
/assets/media/studio-user-guide.pdf and can be linked from the site.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from PIL import Image  # bundled with fpdf2; used to read screenshot dimensions

# ── paths & brand ─────────────────────────────────────────────────────────────
_FRONTEND = Path(__file__).resolve().parent.parent / "app" / "frontend"
_MEDIA = _FRONTEND / "media"
_AM_LOGO = _MEDIA / "arts-marvels-logo.png"
_AM_ASPECT = 2710 / 1447
_BIPOC_LOGO = _MEDIA / "bipoc-foundation-logo.png"
_BIPOC_ASPECT = 4500 / 1539

# Annotated screenshots of the live booking site. Regenerate with the Playwright
# capture + annotate scripts, then copy the PNGs into media/guide/.
_SHOTS = _MEDIA / "guide"
_SHOT_ROOMS = _SHOTS / "step1-rooms.png"
_SHOT_STUDIOS = _SHOTS / "step2-studios.png"
_SHOT_RESERVE = _SHOTS / "step3-reserve.png"
_SHOT_DETAILS = _SHOTS / "step4-details.png"
_SHOT_PAYMENT = _SHOTS / "step5-payment.png"
_SHOT_STAFF = _SHOTS / "step6-staff.png"
_SHOT_STAFFBOOK = _SHOTS / "step7-staff-booking.png"
_SHOT_APPLY = _SHOTS / "step8-apply.png"
_SHOT_RECEIPT = _SHOTS / "step9-receipt.png"

_DEFAULT_OUT = _MEDIA / "studio-user-guide.pdf"

_RED = (231, 54, 60)
_NAVY = (13, 37, 69)
_DARK = (26, 26, 26)
_MID = (96, 104, 112)
_LGREY = (245, 246, 248)
_LINE = (218, 222, 226)
_WHITE = (255, 255, 255)
_GREEN = (22, 150, 80)

PAGE_W = 215.9   # Letter
PAGE_H = 279.4
MX = 18          # content margin
CONTENT_W = PAGE_W - 2 * MX


class Guide(FPDF):
    """FPDF subclass that paints the running header/footer on content pages."""

    # Core PDF fonts are latin-1 only; transliterate the typographic characters
    # we use (em/en dashes, curly quotes, arrows) to safe equivalents.
    _TRANSLATE = str.maketrans({
        "—": "-", "–": "-",
        "“": '"', "”": '"', "‘": "'", "’": "'",
        "→": "->", "…": "...",
    })

    def normalize_text(self, text):  # noqa: D401 - fpdf hook
        return super().normalize_text(text.translate(self._TRANSLATE))

    def header(self) -> None:  # noqa: D401 - fpdf hook
        if self.page_no() <= 2:  # cover + table of contents
            return
        # Slim brand strip at the very top of each content page.
        if _AM_LOGO.exists():
            self.image(str(_AM_LOGO), x=MX, y=9, h=7)
        if _BIPOC_LOGO.exists():
            h = 5.2
            self.image(str(_BIPOC_LOGO), x=PAGE_W - MX - h * _BIPOC_ASPECT, y=10, h=h)
        self.set_draw_color(*_LINE)
        self.set_line_width(0.3)
        self.line(MX, 19, PAGE_W - MX, 19)
        self.set_y(26)

    def footer(self) -> None:  # noqa: D401 - fpdf hook
        if self.page_no() <= 2:  # cover + table of contents
            return
        self.set_y(-15)
        self.set_draw_color(*_LINE)
        self.set_line_width(0.3)
        self.line(MX, self.get_y(), PAGE_W - MX, self.get_y())
        self.set_y(-12)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*_MID)
        self.cell(0, 6, "BIPOC Foundation — Digital Media & Creative Innovation Hub", align="L")
        self.set_x(MX)
        self.cell(CONTENT_W, 6, f"Page {self.page_no() - 2}", align="R")


# ── low-level text helpers ────────────────────────────────────────────────────
def _set(pdf: Guide, font: str, style: str, size: float, color: tuple[int, int, int]) -> None:
    pdf.set_font(font, style, size)
    pdf.set_text_color(*color)


def _space(pdf: Guide, mm: float) -> None:
    pdf.set_y(pdf.get_y() + mm)


def _para(pdf: Guide, text: str, *, size: float = 9.5, color=_DARK, style: str = "",
          gap: float = 2.2, lh: float = 5.0, indent: float = 0.0) -> None:
    _set(pdf, "Helvetica", style, size, color)
    pdf.set_x(MX + indent)
    pdf.multi_cell(CONTENT_W - indent, lh, text, align="L")
    _space(pdf, gap)


# ── imagery & flow diagrams ───────────────────────────────────────────────────
def _shot(pdf: Guide, src: Path, caption: str | None = None,
          width: float = 158.0, max_h: float = 116.0) -> None:
    """Place a website screenshot centered, preserving aspect ratio.

    Slightly narrower than the text column so two landscape shots pair on a page.
    """
    if not src.exists():
        return
    iw, ih = Image.open(src).size
    w = width
    h = w * ih / iw
    if h > max_h:
        h = max_h
        w = h * iw / ih
    if pdf.get_y() + h + (9 if caption else 5) > PAGE_H - 18:
        pdf.add_page()
    x = MX + (CONTENT_W - w) / 2
    y = pdf.get_y()
    pdf.image(str(src), x=x, y=y, w=w, h=h)
    pdf.set_y(y + h)
    if caption:
        _space(pdf, 1.8)
        _set(pdf, "Helvetica", "I", 7.8, _MID)
        pdf.set_x(MX)
        pdf.multi_cell(CONTENT_W, 4, caption, align="C")
        _space(pdf, 5)
    else:
        _space(pdf, 5)


def _arrow(pdf: Guide, x: float, yc: float, length: float,
           color: tuple[int, int, int] = _RED) -> None:
    """Short horizontal arrow pointing right, vertically centered on `yc`."""
    pdf.set_draw_color(*color)
    pdf.set_fill_color(*color)
    pdf.set_line_width(0.8)
    pdf.line(x, yc, x + length, yc)
    head = 2.6
    pdf.polygon(
        [(x + length, yc - 1.9), (x + length + head, yc), (x + length, yc + 1.9)],
        style="F",
    )


def _flow_strip(pdf: Guide, steps: list[str]) -> None:
    """Horizontal step boxes connected by red arrows (the on-screen booking flow)."""
    n = len(steps)
    gap = 9.5
    box_h = 15.0
    box_w = (CONTENT_W - gap * (n - 1)) / n
    if pdf.get_y() > PAGE_H - box_h - 18:
        pdf.add_page()
    y = pdf.get_y()
    x = MX
    for i, label in enumerate(steps):
        pdf.set_fill_color(*_NAVY)
        pdf.rect(x, y, box_w, box_h, "F")
        pdf.set_fill_color(*_RED)
        pdf.rect(x, y, box_w, 1.4, "F")  # red cap
        _set(pdf, "Helvetica", "B", 7, (167, 183, 204))
        pdf.set_xy(x, y + 3.4)
        pdf.cell(box_w, 3, f"STEP {i + 1}", align="C")
        _set(pdf, "Helvetica", "B", 10.5, _WHITE)
        pdf.set_xy(x, y + 6.7)
        pdf.cell(box_w, 6, label, align="C")
        if i < n - 1:
            _arrow(pdf, x + box_w + 1.6, y + box_h / 2, gap - 4.6)
        x += box_w + gap
    pdf.set_y(y + box_h)
    _space(pdf, 7)


def _section_title(pdf: Guide, number: str, title: str) -> None:
    """Big numbered section heading with a red rule — also registers a TOC entry."""
    if pdf.get_y() > PAGE_H - 55:
        pdf.add_page()
    pdf.start_section(title)
    _space(pdf, 2)
    y = pdf.get_y()
    pdf.set_fill_color(*_RED)
    pdf.rect(MX, y + 0.5, 4.2, 9.5, "F")
    _set(pdf, "Helvetica", "B", 9, _RED)
    pdf.set_xy(MX + 7, y - 0.5)
    pdf.cell(0, 5, f"SECTION {number}")
    _set(pdf, "Helvetica", "B", 16, _NAVY)
    pdf.set_xy(MX + 7, y + 3.5)
    pdf.cell(0, 7, title)
    _space(pdf, 15)


def _sub(pdf: Guide, text: str) -> None:
    if pdf.get_y() > PAGE_H - 40:
        pdf.add_page()
    _space(pdf, 1.5)
    _set(pdf, "Helvetica", "B", 11, _NAVY)
    pdf.set_x(MX)
    pdf.cell(0, 6, text)
    _space(pdf, 7.5)


def _step(pdf: Guide, n: int, head: str, body: str) -> None:
    if pdf.get_y() > PAGE_H - 38:
        pdf.add_page()
    y = pdf.get_y()
    # numbered navy disc
    d = 7.0
    pdf.set_fill_color(*_NAVY)
    pdf.ellipse(MX, y, d, d, "F")
    _set(pdf, "Helvetica", "B", 10, _WHITE)
    pdf.set_xy(MX, y + 1.0)
    pdf.cell(d, 5, str(n), align="C")
    # head + body
    tx = MX + d + 5
    tw = PAGE_W - MX - tx
    _set(pdf, "Helvetica", "B", 10, _DARK)
    pdf.set_xy(tx, y - 0.3)
    pdf.multi_cell(tw, 5.2, head, align="L")
    _set(pdf, "Helvetica", "", 9, _MID)
    pdf.set_x(tx)
    pdf.multi_cell(tw, 4.6, body, align="L")
    pdf.set_y(max(pdf.get_y(), y + d) + 3.5)


def _bullet(pdf: Guide, text: str, *, bold_lead: str | None = None) -> None:
    if pdf.get_y() > PAGE_H - 28:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_fill_color(*_RED)
    pdf.rect(MX + 1, y + 1.6, 1.7, 1.7, "F")
    tx = MX + 7
    tw = PAGE_W - MX - tx
    pdf.set_xy(tx, y)
    if bold_lead:
        _set(pdf, "Helvetica", "B", 9.3, _DARK)
        lead_w = pdf.get_string_width(bold_lead + " ")
        pdf.cell(lead_w, 4.8, bold_lead + " ")
        _set(pdf, "Helvetica", "", 9.3, _MID)
        pdf.multi_cell(tw - lead_w, 4.8, text, align="L")
    else:
        _set(pdf, "Helvetica", "", 9.3, _MID)
        pdf.multi_cell(tw, 4.8, text, align="L")
    _space(pdf, 1.6)


def _callout(pdf: Guide, title: str, body: str) -> None:
    if pdf.get_y() > PAGE_H - 45:
        pdf.add_page()
    pad = 4.0
    _set(pdf, "Helvetica", "B", 9, _NAVY)
    title_h = 5.0
    _set(pdf, "Helvetica", "", 8.8, _DARK)
    lines = pdf.multi_cell(CONTENT_W - 2 * pad, 4.6, body, align="L",
                           dry_run=True, output="LINES")
    body_h = len(lines) * 4.6
    box_h = title_h + body_h + 2 * pad
    y0 = pdf.get_y()
    pdf.set_fill_color(*_LGREY)
    pdf.set_draw_color(*_LINE)
    pdf.set_line_width(0.3)
    pdf.rect(MX, y0, CONTENT_W, box_h, "DF")
    pdf.set_fill_color(*_RED)
    pdf.rect(MX, y0, 1.6, box_h, "F")
    _set(pdf, "Helvetica", "B", 9, _NAVY)
    pdf.set_xy(MX + pad, y0 + pad)
    pdf.cell(0, 4.6, title)
    _set(pdf, "Helvetica", "", 8.8, _DARK)
    pdf.set_xy(MX + pad, y0 + pad + title_h)
    pdf.multi_cell(CONTENT_W - 2 * pad, 4.6, body, align="L")
    pdf.set_y(y0 + box_h + 4)


def _fact_grid(pdf: Guide, rows: list[tuple[str, str]]) -> None:
    """Two-column label/value quick-facts block. Kept together on one page."""
    row_h = 8.5
    label_w = 42
    if pdf.get_y() > PAGE_H - 25 - len(rows) * row_h:
        pdf.add_page()
    for i, (label, value) in enumerate(rows):
        y = pdf.get_y()
        if i % 2 == 0:
            pdf.set_fill_color(*_LGREY)
            pdf.rect(MX, y, CONTENT_W, row_h, "F")
        _set(pdf, "Helvetica", "B", 9, _NAVY)
        pdf.set_xy(MX + 3, y + 2)
        pdf.cell(label_w, 4.6, label)
        _set(pdf, "Helvetica", "", 9, _DARK)
        pdf.set_xy(MX + 3 + label_w, y + 2)
        pdf.multi_cell(CONTENT_W - label_w - 6, 4.6, value, align="L")
        pdf.set_y(y + row_h)
    _space(pdf, 3)


# ── price table ───────────────────────────────────────────────────────────────
def _price_table(pdf: Guide) -> None:
    headers = ["User category", "Per room", "Full space"]
    rows = [
        ("Artist Member", "$50 / hr", "$100 / hr"),
        ("Venture Member (after free hours)", "$50 / hr", "$100 / hr"),
        ("BIPOC Community Member", "$75 / hr", "$150 / hr"),
        ("General Public", "$100 / hr", "$200 / hr"),
        ("Organizational Member", "Contact us", "Contact us"),
    ]
    col_w = [CONTENT_W * 0.52, CONTENT_W * 0.24, CONTENT_W * 0.24]
    # header
    y = pdf.get_y()
    pdf.set_fill_color(*_NAVY)
    pdf.rect(MX, y, CONTENT_W, 8, "F")
    _set(pdf, "Helvetica", "B", 8.5, _WHITE)
    x = MX
    for w, h in zip(col_w, headers):
        pdf.set_xy(x + 2.5, y + 2)
        pdf.cell(w - 5, 4, h, align="L" if h == headers[0] else "R")
        x += w
    pdf.set_y(y + 8)
    # rows
    for i, r in enumerate(rows):
        y = pdf.get_y()
        if i % 2 == 1:
            pdf.set_fill_color(*_LGREY)
            pdf.rect(MX, y, CONTENT_W, 7.5, "F")
        x = MX
        for j, (w, cell) in enumerate(zip(col_w, r)):
            _set(pdf, "Helvetica", "B" if j == 0 else "", 8.5, _DARK if j == 0 else _MID)
            pdf.set_xy(x + 2.5, y + 1.8)
            pdf.cell(w - 5, 4, cell, align="L" if j == 0 else "R")
            x += w
        pdf.set_y(y + 7.5)
    pdf.set_draw_color(*_LINE)
    pdf.set_line_width(0.3)
    pdf.line(MX, pdf.get_y(), PAGE_W - MX, pdf.get_y())
    _space(pdf, 5)


# ── cover & TOC ───────────────────────────────────────────────────────────────
def _cover(pdf: Guide) -> None:
    pdf.add_page()
    # top brand lockup
    top = 30
    if _AM_LOGO.exists():
        pdf.image(str(_AM_LOGO), x=MX, y=top, h=18)
    if _BIPOC_LOGO.exists():
        h = 11
        pdf.image(str(_BIPOC_LOGO), x=PAGE_W - MX - h * _BIPOC_ASPECT, y=top + 3.5, h=h)

    # hero band
    band_y = 95
    pdf.set_fill_color(*_NAVY)
    pdf.rect(0, band_y, PAGE_W, 78, "F")
    pdf.set_fill_color(*_RED)
    pdf.rect(0, band_y, PAGE_W, 2.4, "F")

    _set(pdf, "Helvetica", "B", 11, _RED)
    pdf.set_xy(MX, band_y + 14)
    pdf.cell(0, 6, "USER GUIDE")
    _set(pdf, "Helvetica", "B", 30, _WHITE)
    pdf.set_xy(MX, band_y + 24)
    pdf.cell(0, 13, "How to Use the Studio")
    pdf.set_xy(MX, band_y + 37)
    pdf.cell(0, 13, "Booking Website")
    _set(pdf, "Helvetica", "", 11, (210, 218, 228))
    pdf.set_xy(MX, band_y + 56)
    pdf.cell(0, 6, "Digital Media & Creative Innovation Hub")

    # intro line
    _set(pdf, "Helvetica", "", 10, _MID)
    pdf.set_xy(MX, band_y + 92)
    pdf.multi_cell(
        CONTENT_W, 5.2,
        "Everything you need to reserve a studio room, book a session with a "
        "sound or media engineer, know what to expect on the day, and — if you "
        "are an engineer — apply to work out of the Hub.",
        align="L",
    )

    # footer block on cover
    _set(pdf, "Helvetica", "B", 9, _NAVY)
    pdf.set_xy(MX, PAGE_H - 34)
    pdf.cell(0, 5, "BIPOC Foundation  ·  Powered by Arts Marvels")
    _set(pdf, "Helvetica", "", 8.5, _MID)
    pdf.set_xy(MX, PAGE_H - 28)
    pdf.cell(0, 5, "2525 36 St N, Lethbridge, AB T1H 5L1   ·   403-393-8857")
    pdf.set_xy(MX, PAGE_H - 23)
    pdf.cell(0, 5, "lethsmakeithappen@bipocfoundation.org")
    pdf.set_xy(MX, PAGE_H - 18)
    pdf.cell(0, 5, f"Updated {datetime.now():%B %Y}")


def _render_toc(pdf: Guide, outline) -> None:
    pdf.set_y(30)
    _set(pdf, "Helvetica", "B", 9, _RED)
    pdf.set_x(MX)
    pdf.cell(0, 6, "CONTENTS")
    _set(pdf, "Helvetica", "B", 22, _NAVY)
    pdf.set_xy(MX, 37)
    pdf.cell(0, 9, "Table of Contents")
    pdf.set_draw_color(*_LINE)
    pdf.set_line_width(0.4)
    pdf.line(MX, 52, PAGE_W - MX, 52)
    pdf.set_y(60)

    for i, entry in enumerate(outline, start=1):
        y = pdf.get_y()
        # number chip (red with white numeral, matching the section markers)
        pdf.set_fill_color(*_RED)
        pdf.rect(MX, y, 9, 9, "F")
        _set(pdf, "Helvetica", "B", 10, _WHITE)
        pdf.set_xy(MX, y + 2.2)
        pdf.cell(9, 4.6, str(i), align="C")
        # title
        _set(pdf, "Helvetica", "B", 11.5, _DARK)
        pdf.set_xy(MX + 13, y + 2.2)
        pdf.cell(0, 4.6, entry.name)
        # dotted leader + page number
        page_label = str(entry.page_number - 2)
        _set(pdf, "Helvetica", "", 10, _MID)
        title_w = pdf.get_string_width(entry.name)
        pn_w = pdf.get_string_width(page_label)
        dot_start = MX + 13 + title_w + 3
        dot_end = PAGE_W - MX - pn_w - 3
        pdf.set_draw_color(*_LINE)
        pdf.set_line_width(0.2)
        pdf.set_dash_pattern(dash=0.4, gap=1.4)
        if dot_end > dot_start:
            pdf.line(dot_start, y + 6, dot_end, y + 6)
        pdf.set_dash_pattern()
        pdf.set_xy(PAGE_W - MX - pn_w - 2, y + 2.2)
        _set(pdf, "Helvetica", "B", 10, _NAVY)
        pdf.cell(pn_w + 2, 4.6, page_label, align="R")
        pdf.set_y(y + 13)


# ── content sections ──────────────────────────────────────────────────────────
def _content(pdf: Guide) -> None:
    # 1 — Welcome & quick facts
    _section_title(pdf, "1", "Welcome & Quick Facts")
    _para(pdf,
          "The Studio Booking website lets you reserve creative studio rooms at the "
          "BIPOC Foundation Digital Media & Creative Innovation Hub in Lethbridge. You "
          "can browse rooms, pick a date and time, optionally add a studio engineer, "
          "and pay your deposit online. You do not need an account to get started — a "
          "name and phone number are enough on supported screens.")
    _sub(pdf, "At a glance")
    _fact_grid(pdf, [
        ("Open days", "Wednesday, Thursday, Friday & Saturday only"),
        ("Hours", "12:00 PM – 8:00 PM each operating day"),
        ("Session length", "1-hour blocks · minimum 1 hour · maximum 5 hours per day"),
        ("Deposit", "$20 due at checkout (space-only or with an engineer)"),
        ("Address", "2525 36 St N, Lethbridge, AB T1H 5L1"),
        ("Contact", "403-393-8857 · lethsmakeithappen@bipocfoundation.org"),
    ])
    _callout(pdf, "Account or guest?",
             "You can complete a booking as a guest using just your name and phone "
             "number. Creating an account lets you review past bookings, keep your "
             "details on file, and — for engineers — build a full public profile.")

    # 2 — Book a room
    _section_title(pdf, "2", "How to Book a Studio Room")
    _para(pdf, "From the home page or the Rooms page, start a booking and follow the "
               "four-step flow shown along the top of the screen:", gap=5)
    _flow_strip(pdf, ["Date", "Time", "Details", "Checkout"])
    _para(pdf, "Here is the whole process on the live site. On each screenshot, the red "
               "number and arrow show exactly what to do next.", size=9, color=_MID, gap=5)
    _shot(pdf, _SHOT_ROOMS,
          "1 · On the Rooms page, click any green (open) day. Only Wednesday–Saturday "
          "have openings — closed days are greyed out.")
    _shot(pdf, _SHOT_STUDIOS,
          "2 · Each available studio lists its open start times for that day. Pick the "
          "studio and the start time you want.")
    _shot(pdf, _SHOT_RESERVE,
          "3 · The reserve page tracks your progress along the top: "
          "Date → Time → Details → Checkout.")
    _shot(pdf, _SHOT_DETAILS,
          "4 · Confirm your start time and length (1-hour blocks, up to 5 hours per day), "
          "then enter your name and phone. Continuing as a guest is fine.")
    _shot(pdf, _SHOT_PAYMENT,
          "5 · Review the price breakdown and pay only the deposit now — by card, Apple "
          "Pay, or Google Pay. The balance is due at the studio.")
    _shot(pdf, _SHOT_RECEIPT,
          "6 · Your booking is confirmed, and you can download a PDF receipt like this "
          "one at any time.")
    _callout(pdf, "Why a phone number?",
             "It gives the team a reliable way to confirm details, reach you if a timing "
             "issue comes up, and help with your booking faster. Guest bookings still "
             "create a full booking record you can review.")

    # 3 — What to expect
    _section_title(pdf, "3", "What to Expect on the Day")
    _sub(pdf, "Before you arrive")
    _bullet(pdf, "10 to 15 minutes early so you have time to check in, unload gear, and "
                 "get settled before your session starts.", bold_lead="Arrive")
    _bullet(pdf, "your files, drives, reference tracks, and any specialty gear you need. "
                 "Match the space to your project using the room page.", bold_lead="Bring")
    _bullet(pdf, "you can bring additional people as long as you stay within the room "
                 "capacity shown on the room page.", bold_lead="Guests —")
    _sub(pdf, "Timing & payment")
    _bullet(pdf, "Late arrival still counts against your booked time, and early "
                 "departure is charged for the full booked session.")
    _bullet(pdf, "Full payment is required before the session begins; the deposit you "
                 "paid online is applied toward your total.")
    _bullet(pdf, "Projects with unusual setup, staffing, or access needs may require "
                 "approval before they are confirmed.")
    _sub(pdf, "Equipment")
    _bullet(pdf, "Check the room page for the available setup, then bring your own "
                 "files, drives, references, and specialty gear.")
    _bullet(pdf, "Equipment rentals may require a credit-card authorization and a "
                 "signed usage agreement before use.")

    # 4 — Booking with staff
    _section_title(pdf, "4", "Booking a Room With Staff Support")
    _para(pdf,
          "Add a studio engineer when you want help with setup, room guidance, or a "
          "more hands-on session — for podcasting, sound, photography, video, branding, "
          "or other production support, subject to availability. There are two ways to "
          "book with staff:")
    _sub(pdf, "Option A — Add staff while booking a room")
    _para(pdf, "If the room offers engineer support, the booking flow shows a staff "
               "option on the Details step. Add it there and the updated price "
               "(including the engineer) appears before you confirm.", indent=0)
    _sub(pdf, "Option B — Start from the Staff page")
    _para(pdf, "Open the Staff page, browse the team, and select an engineer to book "
               "them directly. This uses a four-step flow:", gap=5)
    _flow_strip(pdf, ["Staff", "Time", "Details", "Checkout"])
    _shot(pdf, _SHOT_STAFF,
          "Browse the team on the Staff page — search by name, skill, or role, or filter "
          "by discipline.")
    _shot(pdf, _SHOT_STAFFBOOK,
          "Select an engineer, then pick a date and time from their calendar. The same "
          "Staff → Time → Details → Checkout flow takes your $20 deposit to confirm.")
    _callout(pdf, "Good to know",
             "A booking with an engineer uses the same $20 deposit as a space-only "
             "booking. The engineer's support is reflected in the session price you "
             "review before checkout.")

    # 5 — Rates, deposits, cancellation
    _section_title(pdf, "5", "Rates, Deposits & Cancellation")
    _sub(pdf, "Public hourly pricing")
    _price_table(pdf)
    _para(pdf, "Your user category sets your hourly rate. Artist Members get the "
               "$50/hr room rate and can receive the approved “book 4 hours, get the "
               "5th free” incentive. Contact the team to apply for or confirm your "
               "category.", size=9, color=_MID)
    _sub(pdf, "Deposits")
    _bullet(pdf, "$20 due at checkout.", bold_lead="Space-only booking —")
    _bullet(pdf, "$20 due at checkout.", bold_lead="Booking with an engineer —")
    _bullet(pdf, "credit-card authorization for full replacement value may be required.",
            bold_lead="Equipment rental —")
    _sub(pdf, "Cancellation policy")
    _bullet(pdf, "Deposits are non-refundable after checkout.")
    _bullet(pdf, "Cancellations do not return the deposit.")
    _bullet(pdf, "No-show: the deposit is not refunded.")
    _bullet(pdf, "Late arrival or early departure: the full booked time is still charged.")

    # 6 — Apply to be a studio engineer
    _section_title(pdf, "6", "Apply to Be a Studio Engineer")
    _para(pdf,
          "Are you an audio, video, or production engineer who wants to work out of the "
          "Hub? You can apply right from the website. Open the Staff page and scroll to "
          "“Apply to be a studio engineer,” then fill out the short form.")
    _shot(pdf, _SHOT_APPLY,
          "The application form on the Staff page. Required fields are marked; the red "
          "numbers point out the two that matter most.")
    _sub(pdf, "What the form asks — and what to put")
    _form_field(pdf, "Name", True,
                "Your full name, e.g. “Jane Doe.”")
    _form_field(pdf, "Email", True,
                "An address you check — the team replies here.")
    _form_field(pdf, "Phone", True,
                "A reliable number, e.g. 403-555-0100.")
    _form_field(pdf, "Skillset", True,
                "What you do: recording, mixing, mastering, live sound, video editing, "
                "photography, podcasting, branding, and so on. Be specific.")
    _form_field(pdf, "Equipment", False,
                "Any gear you would bring or work with. Optional, but it helps the team "
                "understand what you can offer.")
    _form_field(pdf, "Why should you be considered?", True,
                "Your experience and what you would bring to the studio — past projects, "
                "credits, and the kind of sessions you want to run.")
    _callout(pdf, "What happens after you submit",
             "Your application is sent to the team and an admin reviews it. If it is a "
             "fit, they will be in touch. To work as a studio engineer you will also "
             "create an account and build your full profile — headshots, portfolio, "
             "skills, and gear — which an admin reviews before granting studio-engineer "
             "access. Start that at Account → Create your engineer profile.")

    # 7 — Need help
    _section_title(pdf, "7", "Need Help?")
    _para(pdf, "Still have questions before you book? The FAQ page answers the most "
               "common ones about rooms, equipment, booking rules, and staff support. "
               "You can also reach the team directly:")
    _fact_grid(pdf, [
        ("Phone", "403-393-8857"),
        ("Email", "lethsmakeithappen@bipocfoundation.org"),
        ("Address", "2525 36 St N, Lethbridge, AB T1H 5L1"),
        ("Hours", "Wed–Sat, 12:00 PM – 8:00 PM"),
        ("Online", "FAQ, Rooms, Pricing & Staff pages on the website"),
    ])
    _set(pdf, "Helvetica", "B", 9.5, _GREEN)
    pdf.set_x(MX)
    _space(pdf, 2)
    pdf.cell(0, 6, "Thank you for choosing the BIPOC Foundation Creative Innovation Hub.")


def _form_field(pdf: Guide, label: str, required: bool, guidance: str) -> None:
    if pdf.get_y() > PAGE_H - 32:
        pdf.add_page()
    y = pdf.get_y()
    # label line with required/optional tag
    _set(pdf, "Helvetica", "B", 10, _NAVY)
    pdf.set_xy(MX, y)
    lw = pdf.get_string_width(label + "  ")
    pdf.cell(lw, 5, label + "  ")
    if required:
        _set(pdf, "Helvetica", "B", 7.5, _RED)
        pdf.cell(0, 5, "REQUIRED")
    else:
        _set(pdf, "Helvetica", "B", 7.5, _MID)
        pdf.cell(0, 5, "OPTIONAL")
    pdf.set_y(y + 5.2)
    _set(pdf, "Helvetica", "", 9, _MID)
    pdf.set_x(MX + 4)
    pdf.multi_cell(CONTENT_W - 4, 4.6, guidance, align="L")
    _space(pdf, 3.5)


# ── build ─────────────────────────────────────────────────────────────────────
def build(out_path: Path) -> Path:
    pdf = Guide(orientation="P", unit="mm", format="Letter")
    pdf.set_title("Studio Booking — User Guide")
    pdf.set_author("BIPOC Foundation Digital Media & Creative Innovation Hub")
    # Cover and TOC are fixed layouts — no auto page breaks while drawing them.
    pdf.set_auto_page_break(False)
    _cover(pdf)
    pdf.add_page()  # TOC page; the placeholder's own page break starts content
    pdf.insert_toc_placeholder(_render_toc, pages=1)

    pdf.set_auto_page_break(True, margin=20)
    _content(pdf)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_OUT
    path = build(out)
    print(f"Wrote {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
