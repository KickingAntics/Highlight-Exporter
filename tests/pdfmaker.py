"""Build small PDFs with known text and highlights, so tests know the exact right answer."""
import pymupdf

LINE_H = 14
FONT = "helv"

YELLOW, GREEN, BLUE, PINK, RED = (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0)


def new_doc():
    return pymupdf.open()


def put(page, x, y, lines, size=11, indent=0, pitch=LINE_H, gap=9):
    """Write lines top-to-bottom; the first is indented. Returns the y for the next paragraph."""
    for i, t in enumerate(lines):
        page.insert_text((x + (indent if i == 0 else 0), y), t, fontsize=size, fontname=FONT)
        y += pitch
    return y + gap


def frame(page, header=None, footer=None, size=9):
    """Running header (top) and footer (bottom) text."""
    if header:
        page.insert_text((72, 40), header, fontsize=size, fontname=FONT)
    if footer:
        page.insert_text((300, 765), footer, fontsize=size, fontname=FONT)


def hl(page, *phrases, color=YELLOW, occurrence=0, content=None):
    """Highlight the given phrase(s) (one per line) as ONE annotation with one quad per line."""
    quads = []
    for ph in phrases:
        hits = page.search_for(ph, quads=True)
        assert hits, f"phrase not found for highlighting: {ph!r}"
        quads.append(hits[occurrence])
    a = page.add_highlight_annot(quads=quads)
    a.set_colors(stroke=color)
    if content:
        a.set_info(content=content)
    a.update()
    return a


def save(doc, path):
    doc.save(str(path))
    doc.close()
    return str(path)


PARA1 = ["The framers of the constitution disagreed about many things, but they",
         "agreed that written limits on government power were essential to",
         "preserving liberty. Courts therefore began to treat the document as",
         "enforceable law, not mere aspiration."]
PARA2 = ["Critics answered that judges lack the democratic standing to enforce",
         "such limits against elected legislatures. They urged restraint and",
         "deference in nearly every dispute that reached the bench."]
PARA3 = ["Defenders replied that restraint is itself a choice with consequences,",
         "and that neutrality between the branches is a myth worth abandoning."]
