"""Write highlight excerpts to Word. Only the highlighted text is emphasized."""
from __future__ import annotations

import datetime

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt, RGBColor

# Word offers a fixed set of highlight colors. PDF colors map to the nearest of these
# light, readable ones (orange and gold highlighters become yellow).
PALETTE = {
    "YELLOW": ((1.0, 1.0, 0.0), WD_COLOR_INDEX.YELLOW),
    "BRIGHT_GREEN": ((0.0, 1.0, 0.0), WD_COLOR_INDEX.BRIGHT_GREEN),
    "TURQUOISE": ((0.0, 1.0, 1.0), WD_COLOR_INDEX.TURQUOISE),
    "PINK": ((1.0, 0.0, 1.0), WD_COLOR_INDEX.PINK),
    "RED": ((1.0, 0.0, 0.0), WD_COLOR_INDEX.RED),
    "BLUE": ((0.0, 0.0, 1.0), WD_COLOR_INDEX.BLUE),
    "GRAY_25": ((0.75, 0.75, 0.75), WD_COLOR_INDEX.GRAY_25),
}


def word_color(rgb):
    """Nearest Word highlight color name for a PDF RGB triple (yellow if none given).

    Matching is by hue, so pale and strong versions of a color share one Word color.
    Grays map to light gray; pale blues map to turquoise (Word's blue is dark).
    """
    if not rgb or len(rgb) != 3:
        return "YELLOW"
    lo, hi = min(rgb), max(rgb)
    if hi - lo < 0.12:
        return "GRAY_25"
    pure = [(c - lo) / (hi - lo) for c in rgb]
    name = min((k for k in PALETTE if k != "GRAY_25"),
               key=lambda k: sum((a - b) ** 2 for a, b in zip(PALETTE[k][0], pure)))
    if name == "BLUE" and lo > 0.3:
        return "TURQUOISE"
    return name


def page_label(ex):
    p0, p1 = ex.pages
    pdf = f"PDF page {p0}" if p0 == p1 else f"PDF pages {p0}–{p1}"
    if ex.printed:
        a, b = ex.printed
        pr = f"printed page {a}" if a == b else f"printed pages {a}–{b}"
        return f"{pdf} ({pr})"
    return pdf


def _add_runs(par, runs, emphasis):
    for r in runs:
        run = par.add_run(r.text)
        if r.hl:
            if emphasis == "bold":
                run.bold = True
            else:
                run.font.highlight_color = PALETTE[word_color(r.color)][1]


def _n(count, noun):
    return f"{count} {noun}" + ("" if count == 1 else "s")


def add_source(doc, res, emphasis="highlight", heading_page_break=False, name=None):
    """Append one source's heading and excerpts to an open Document."""
    title = res.title or name
    h = doc.add_heading(title, level=1)
    if heading_page_break:
        h.paragraph_format.page_break_before = True
    p = doc.add_paragraph()
    p.add_run("File: ").bold = True
    p.add_run(name)
    p = doc.add_paragraph()
    src = f"Title source: {res.title_source}" if res.title_source else "Title: none in the PDF, filename used"
    p.add_run(f"{src}  ·  {_n(res.found, 'highlight')} found, {res.exported} exported with text, "
              f"{res.no_text} without text  ·  {_n(len(res.excerpts), 'excerpt')}, "
              f"{res.flagged} to review").italic = True
    for note in res.notes:
        q = doc.add_paragraph()
        r = q.add_run(f"Note: {note}")
        r.italic = True
        r.font.size = Pt(9)
    for ex in res.excerpts:
        hp = doc.add_paragraph(style="Excerpt Heading")
        hp.paragraph_format.space_before = Pt(12)
        hp.paragraph_format.keep_with_next = True
        kind = " (footnote)" if ex.kind == "footnote" else ""
        r = hp.add_run(f"Excerpt {ex.number} — {page_label(ex)}{kind}")
        r.bold = True
        if ex.flags:
            fp = doc.add_paragraph(style="Review Flag")
            fp.paragraph_format.keep_with_next = True
            fr = fp.add_run("⚠ Review: " + "; ".join(ex.flags))
            fr.font.color.rgb = RGBColor(0xB0, 0x30, 0x00)
            fr.font.size = Pt(9)
        for runs in ex.paras:
            _add_runs(doc.add_paragraph(style="Excerpt Text"), runs, emphasis)
        for c in ex.comments:
            cp = doc.add_paragraph(style="Excerpt Note")
            cr = cp.add_run(f"PDF note: {c}")
            cr.italic = True
        if ex.notes and any(n not in ("footnote",) for n in ex.notes):
            np_ = doc.add_paragraph(style="Excerpt Note")
            nr = np_.add_run("Note: " + "; ".join(n for n in ex.notes if n != "footnote"))
            nr.font.size = Pt(9)
            nr.italic = True


def new_document():
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    for name in ("Excerpt Heading", "Excerpt Text", "Review Flag", "Excerpt Note"):
        st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = doc.styles["Normal"]
    return doc


def write_single(path, res, name, emphasis="highlight"):
    doc = new_document()
    add_source(doc, res, emphasis, False, name)
    doc.save(path)


def write_combined(path, results, emphasis="highlight"):
    """results: list of (name, DocResult) in the order the sources were selected."""
    doc = new_document()
    for i, (name, res) in enumerate(results):
        add_source(doc, res, emphasis, heading_page_break=i > 0, name=name)
    doc.save(path)


def stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H%M")
