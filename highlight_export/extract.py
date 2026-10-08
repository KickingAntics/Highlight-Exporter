"""Read a PDF's highlight annotations and map them to the text underneath.

Nothing here rewrites text: highlighted words are the characters whose boxes lie under
the highlight, context is the surrounding paragraph rebuilt from the same characters.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from .pages import detect_printed

HIGHLIGHT, UNDERLINE = 8, 9
COVER = 0.5  # a character counts as highlighted when more than this share of it is covered
EDGE_TOUCH = 0.15  # a letter this covered at the edge of a highlight joins it if it continues a word
TERMINATORS = ".?!:\"”’)]"
HYPHENS = "-‐‑"
SOFT_HYPHEN = "­"


class PdfProblem(Exception):
    """A file that cannot be processed; `status` is the plain-words reason for the report."""

    def __init__(self, status, detail=""):
        super().__init__(f"{status}: {detail}" if detail else status)
        self.status = status
        self.detail = detail


@dataclass
class Ch:
    c: str
    bbox: tuple
    anns: list = field(default_factory=list)


@dataclass
class Line:
    page: int
    bbox: tuple
    size: float
    chars: list
    kind: str = "body"
    col: int = 0  # 0 left/only, 1 right, -1 spans both columns
    seq: int = 0

    @property
    def text(self):
        return "".join(c.c for c in self.chars)


@dataclass
class Cell:
    ch: str
    anns: tuple
    page: int
    seq: int
    note: str = ""


@dataclass
class Para:
    cells: list = field(default_factory=list)
    crosses: bool = False


@dataclass
class Run:
    text: str
    hl: bool = False
    color: tuple = None
    ann: int = None


@dataclass
class Excerpt:
    kind: str
    paras: list
    pages: tuple = None
    printed: tuple = None
    flags: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    comments: list = field(default_factory=list)
    ann_ids: list = field(default_factory=list)
    empty: bool = False
    number: int = 0
    sortkey: tuple = (0, 0)


@dataclass
class DocResult:
    path: str
    title: str
    title_source: str
    n_pages: int
    excerpts: list
    found: int = 0
    exported: int = 0
    no_text: int = 0
    flagged: int = 0
    notes: list = field(default_factory=list)


@dataclass
class Annot:
    id: int
    page: int
    kind: int
    color: tuple
    content: str
    n_quads: int
    expanded: bool = False


# ---------------------------------------------------------------- opening

def open_pdf(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise PdfProblem("cannot open file",
                         "not available offline? In File Explorer right-click it and choose "
                         f"'Always keep on this device' ({e.strerror or e})")
    if not data:
        raise PdfProblem("unreadable", "the file is empty")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        raise PdfProblem("unreadable", f"not a valid PDF ({str(e)[:80]})")
    if doc.needs_pass:
        raise PdfProblem("locked", "password-protected: open it, save a copy without the password, and try again")
    if doc.page_count == 0:
        raise PdfProblem("unreadable", "the PDF has no pages")
    return doc


_BAD_TITLES = re.compile(r"(\.(pdf|docx?|indd|tex|rtf|txt)$)|^(microsoft word|untitled|document\d*$)", re.I)


def real_title(doc):
    t = (doc.metadata or {}).get("title") or ""
    t = " ".join(t.split())
    if len(t) >= 4 and not _BAD_TITLES.search(t):
        return t
    return ""


# ---------------------------------------------------------------- page text

def _merge_fragments(frags):
    """Justified lines often arrive as several pieces on one baseline: join them into one line."""
    out = []
    for ln in frags:
        prev = out[-1] if out else None
        if prev is not None:
            h = min(prev.bbox[3] - prev.bbox[1], ln.bbox[3] - ln.bbox[1])
            overlap = min(prev.bbox[3], ln.bbox[3]) - max(prev.bbox[1], ln.bbox[1])
            gap = ln.bbox[0] - prev.bbox[2]
            if h > 0 and overlap >= 0.5 * h and -2 <= gap <= 6 * max(prev.size, ln.size):
                if gap > 0.15 * prev.size and prev.chars[-1].c.strip() and ln.chars[0].c.strip():
                    prev.chars.append(Ch(" ", (prev.bbox[2], prev.bbox[1], ln.bbox[0], prev.bbox[3])))
                prev.chars.extend(ln.chars)
                prev.bbox = (min(prev.bbox[0], ln.bbox[0]), min(prev.bbox[1], ln.bbox[1]),
                             max(prev.bbox[2], ln.bbox[2]), max(prev.bbox[3], ln.bbox[3]))
                continue
        out.append(ln)
    return out


def _parse_page(page, pno):
    lines = []
    raw = page.get_text("rawdict")
    for b in raw["blocks"]:
        if b.get("type") != 0:
            continue
        frags = []
        for l in b["lines"]:
            chars, sizes = [], Counter()
            for s in l["spans"]:
                for c in s["chars"]:
                    chars.append(Ch(c["c"], tuple(c["bbox"])))
                    if c["c"].strip():
                        sizes[round(s["size"], 1)] += 1
            if not any(c.c.strip() for c in chars):
                continue
            size = sizes.most_common(1)[0][0] if sizes else 10.0
            frags.append(Line(pno, tuple(l["bbox"]), size, chars))
        lines.extend(_merge_fragments(frags))
    return lines


def _norm_key(text):
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text.lower())).strip()


_ROMAN = re.compile(r"^[ivxlcdm]+$", re.I)


def _pagenum_like(text):
    t = text.strip()
    return (len(t) <= 12 and (re.fullmatch(r"(page\s*)?\d{1,4}", t, re.I) is not None
                              or _ROMAN.match(t) is not None))


def _edge_lines(lines, k=3):
    srt = sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0]))
    return {id(l) for l in srt[:k] + srt[-k:]}


def _classify(pages_lines, page_heights, body_size):
    n = len(pages_lines)
    edge_keys = {}
    edges = []
    for pno, lines in enumerate(pages_lines):
        h = page_heights[pno]
        e = _edge_lines(lines)
        for ln in lines:
            yc = (ln.bbox[1] + ln.bbox[3]) / 2
            if yc < 0.10 * h or yc > 0.90 * h:
                e.add(id(ln))
        edges.append(e)
        for ln in lines:
            if id(ln) in e:
                edge_keys.setdefault(_norm_key(ln.text), []).append((pno, (ln.bbox[1] + ln.bbox[3]) / 2))
    need = min(3, n)
    for pno, lines in enumerate(pages_lines):
        h = page_heights[pno]
        for ln in lines:
            yc = (ln.bbox[1] + ln.bbox[3]) / 2
            in_band = yc < 0.10 * h or yc > 0.90 * h
            # running headers/footers repeat at the same height; repeated footnotes ("Id.") do not
            same_spot = {q for q, y in edge_keys.get(_norm_key(ln.text), []) if abs(y - yc) <= 8}
            repeats = n >= 2 and id(ln) in edges[pno] and len(same_spot) >= need
            if (in_band and _pagenum_like(ln.text)) or repeats:
                ln.kind = "furniture"
            elif ln.size <= 0.88 * body_size and yc > 0.45 * h:
                ln.kind = "footnote"
            else:
                ln.kind = "body"


def _find_gutter(lines, page_w):
    """x-range of a clear vertical gutter in the middle of the page, or None."""
    if len(lines) < 6:
        return None
    lo_x, hi_x = int(page_w * 0.3), int(page_w * 0.7)
    cover = [0] * (int(page_w) + 2)
    for ln in lines:
        for x in range(max(0, int(ln.bbox[0])), min(len(cover) - 1, int(ln.bbox[2]) + 1)):
            cover[x] += 1
    limit = max(1, int(0.15 * len(lines)))
    best, cur_start = None, None
    for x in range(lo_x, hi_x + 1):
        if cover[x] <= limit:
            if cur_start is None:
                cur_start = x
        else:
            if cur_start is not None and (best is None or x - cur_start > best[1] - best[0]):
                best = (cur_start, x)
            cur_start = None
    if cur_start is not None and (best is None or hi_x - cur_start > best[1] - best[0]):
        best = (cur_start, hi_x)
    if not best or best[1] - best[0] < 8:
        return None
    mid = (best[0] + best[1]) / 2
    left = sum(1 for l in lines if (l.bbox[0] + l.bbox[2]) / 2 < mid and l.bbox[2] <= best[1] + 2)
    right = sum(1 for l in lines if (l.bbox[0] + l.bbox[2]) / 2 >= mid and l.bbox[0] >= best[0] - 2)
    if left < 0.25 * len(lines) or right < 0.25 * len(lines):
        return None
    return best


def _merge_baseline(lines):
    """Pieces of one visual line that live in different text blocks (e.g. a citation link) -> one line."""
    rows = []  # each row: list of Lines on one baseline
    for ln in sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])):
        placed = False
        for row in rows[-8:]:
            top = min(l.bbox[1] for l in row)
            bot = max(l.bbox[3] for l in row)
            h = min(bot - top, ln.bbox[3] - ln.bbox[1])
            overlap = min(bot, ln.bbox[3]) - max(top, ln.bbox[1])
            if h <= 0 or overlap < 0.5 * h:
                continue
            gaps = [max(ln.bbox[0] - l.bbox[2], l.bbox[0] - ln.bbox[2]) for l in row]
            if min(gaps) <= 6 * max(ln.size, row[0].size) and min(gaps) >= -2:
                row.append(ln)
                placed = True
                break
        if not placed:
            rows.append([ln])
    out = []
    for row in rows:
        if len(row) == 1:
            out.append(row[0])
            continue
        row.sort(key=lambda l: l.bbox[0])
        head = max(row, key=lambda l: len(l.chars))
        chars = list(row[0].chars)
        for prev, nxt in zip(row, row[1:]):
            gap = nxt.bbox[0] - prev.bbox[2]
            if gap > 0.15 * prev.size and chars[-1].c.strip() and nxt.chars[0].c.strip():
                chars.append(Ch(" ", (prev.bbox[2], prev.bbox[1], nxt.bbox[0], prev.bbox[3])))
            chars.extend(nxt.chars)
        merged = Line(row[0].page, (min(l.bbox[0] for l in row), min(l.bbox[1] for l in row),
                                    max(l.bbox[2] for l in row), max(l.bbox[3] for l in row)),
                      head.size, chars, kind=row[0].kind)
        out.append(merged)
    return out


def _order(lines, page_w):
    """Reading order for one page's lines; sets .col."""
    gutter = _find_gutter(lines, page_w)
    if gutter is None:
        out = sorted(_merge_baseline(lines), key=lambda l: (l.bbox[1], l.bbox[0]))
        for l in out:
            l.col = 0
        return out
    mid = (gutter[0] + gutter[1]) / 2
    wide, left, right = [], [], []
    for l in lines:
        if l.bbox[0] < gutter[0] - 2 and l.bbox[2] > gutter[1] + 2:
            l.col = -1
            wide.append(l)
        elif (l.bbox[0] + l.bbox[2]) / 2 < mid:
            l.col = 0
            left.append(l)
        else:
            l.col = 1
            right.append(l)
    wide, left, right = _merge_baseline(wide), _merge_baseline(left), _merge_baseline(right)
    for l in wide:
        l.col = -1
    for l in left:
        l.col = 0
    for l in right:
        l.col = 1
    out, buf = [], []

    def flush():
        out.extend(sorted([l for l in buf if l.col == 0], key=lambda l: l.bbox[1]) +
                   sorted([l for l in buf if l.col == 1], key=lambda l: l.bbox[1]))
        buf.clear()

    for l in sorted(wide + left + right, key=lambda l: (l.bbox[1], l.bbox[0])):
        if l.col == -1:
            flush()
            out.append(l)
        else:
            buf.append(l)
    flush()
    return out


# ---------------------------------------------------------------- paragraphs

def _is_break(prev, nxt, col_left, col_right, pitch):
    size = max(prev.size, nxt.size)
    if abs(prev.size - nxt.size) > 0.15 * size:
        return True
    ends = prev.text.rstrip()[-1:] in TERMINATORS if prev.text.strip() else False
    indented = nxt.bbox[0] - col_left.get((nxt.page, nxt.col), nxt.bbox[0]) > 0.9 * size
    short = prev.bbox[2] < col_right.get((prev.page, prev.col), prev.bbox[2]) - 5 * size
    if prev.col == -1 or nxt.col == -1:
        return True
    if prev.page == nxt.page and prev.col == nxt.col:
        if pitch.get(prev.page) and (nxt.bbox[1] - prev.bbox[1]) > 1.45 * pitch[prev.page]:
            return True
        if indented:
            return True
        return bool(short and ends)
    return bool(ends and (indented or short))


def _stream_paragraphs(lines, vocab, col_left, col_right, pitch, one_per_line=False, marker_breaks=False):
    """Build paragraphs from lines already in reading order."""
    paras, cur, prev = [], None, None
    events = []  # (kind, text) hyphen decisions, for the notes
    for ln in lines:
        new = cur is None
        crossing = False
        if not new and one_per_line:
            new = True
        elif not new:
            new = _is_break(prev, ln, col_left, col_right, pitch)
            if not new and (prev.page != ln.page or prev.col != ln.col):
                crossing = True
            if not new and marker_breaks and _starts_marker(ln):
                new = True
                crossing = False
        if new:
            cur = Para()
            paras.append(cur)
        if crossing:
            cur.crosses = True
        _append_line(cur, prev if not new else None, ln, vocab, events)
        prev = ln
    return paras, events


def _starts_marker(ln):
    chars = [c for c in ln.chars if c.c.strip()]
    if not chars:
        return False
    first = chars[0]
    h = first.bbox[3] - first.bbox[1]
    lh = ln.bbox[3] - ln.bbox[1]
    return first.c.isdigit() and h < 0.8 * lh


def _letters_at_end(cells):
    s = ""
    for c in reversed(cells):
        if c.ch.isalpha():
            s = c.ch + s
        else:
            break
    return s


def _append_line(para, prev_line, ln, vocab, events):
    chars = ln.chars
    # trim edge spaces
    start, end = 0, len(chars)
    while start < end and not chars[start].c.strip():
        start += 1
    while end > start and not chars[end - 1].c.strip():
        end -= 1
    chars = chars[start:end]
    seq = ln.seq
    if prev_line is not None and para.cells:
        last = para.cells[-1]
        joined = False
        if last.ch == SOFT_HYPHEN:
            para.cells.pop()
            joined = True
        elif last.ch in HYPHENS and len(para.cells) >= 2 and para.cells[-2].ch.isalpha() \
                and chars and chars[0].c.isalpha():
            before = _letters_at_end(para.cells[:-1])
            after = ""
            for c in chars:
                if c.c.isalpha():
                    after += c.c
                else:
                    break
            if (before + after).lower() in vocab:
                para.cells.pop()
                events.append(("joined", f"{before}-{after} -> {before}{after}"))
            else:
                last.note = "hyphen kept"
                events.append(("kept", f"{before}-{after}"))
            joined = True
        if not joined:
            a = para.cells[-1].anns
            b = tuple(chars[0].anns) if chars else ()
            para.cells.append(Cell(" ", tuple(x for x in a if x in b), ln.page, seq))
    for c in chars:
        ch = c.c
        if ch == " " or ch in "\t":
            ch = " "
        if ord(ch) < 32 and ch != " ":
            continue
        if ch == " " and para.cells and para.cells[-1].ch == " ":
            continue
        para.cells.append(Cell(ch, tuple(c.anns), ln.page, seq))


# ---------------------------------------------------------------- annotations

def _read_annots(page, pno, kinds, next_id):
    out = []
    for a in page.annots(types=list(kinds)) or []:
        v = a.vertices or []
        quads = [pymupdf.Quad(v[i:i + 4]).rect for i in range(0, len(v) - len(v) % 4, 4)] if v else []
        if not quads:
            quads = [a.rect]
        color = a.colors.get("stroke") or None
        info = a.info or {}
        ann = Annot(next_id, pno, a.type[0], tuple(color) if color else None,
                    (info.get("content") or "").strip(), len(quads))
        next_id += 1
        out.append((ann, quads))
    return out, next_id


def _cover_fraction(bbox, rect):
    x0, y0 = max(bbox[0], rect.x0), max(bbox[1], rect.y0)
    x1, y1 = min(bbox[2], rect.x1), min(bbox[3], rect.y1)
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if x1 <= x0 or y1 <= y0 or area <= 0:
        return 0.0
    return ((x1 - x0) * (y1 - y0)) / area


def _best_cover(ch, quads):
    return max((_cover_fraction(ch.bbox, q) for q in quads), default=0.0)


def _assign(lines, quads, ann_id, expand=False):
    """Mark the characters under a highlight. Returns True if whole-word expansion added any."""
    expanded = False
    for ln in lines:
        for q in quads:
            if ln.bbox[2] < q.x0 or ln.bbox[0] > q.x1 or ln.bbox[3] < q.y0 or ln.bbox[1] > q.y1:
                continue
            for c in ln.chars:
                if _cover_fraction(c.bbox, q) > COVER and ann_id not in c.anns:
                    c.anns.append(ann_id)
    for ln in lines:
        chars = ln.chars
        inside = [i for i, c in enumerate(chars) if ann_id in c.anns and c.c.strip()]
        if not inside:
            for c in chars:
                if ann_id in c.anns:
                    c.anns.remove(ann_id)
            continue
        # a highlighter that clips the first/last letter still visibly marks the word
        i = inside[0]
        while i > 0 and chars[i - 1].c.isalnum() and chars[i].c.isalnum() \
                and ann_id not in chars[i - 1].anns and _best_cover(chars[i - 1], quads) >= EDGE_TOUCH:
            chars[i - 1].anns.append(ann_id)
            i -= 1
        j = inside[-1]
        while j + 1 < len(chars) and chars[j + 1].c.isalnum() and chars[j].c.isalnum() \
                and ann_id not in chars[j + 1].anns and _best_cover(chars[j + 1], quads) >= EDGE_TOUCH:
            chars[j + 1].anns.append(ann_id)
            j += 1
        if expand:  # opt-in: a clipped word is marked whole, and the excerpt says so
            while i > 0 and chars[i - 1].c.isalnum() and chars[i].c.isalnum() and ann_id not in chars[i - 1].anns:
                chars[i - 1].anns.append(ann_id)
                i -= 1
                expanded = True
            while j + 1 < len(chars) and chars[j + 1].c.isalnum() and chars[j].c.isalnum() \
                    and ann_id not in chars[j + 1].anns:
                chars[j + 1].anns.append(ann_id)
                j += 1
                expanded = True
        # drop spaces at the ends of the run so the emphasis starts/ends on real text
        idx = [k for k, c in enumerate(chars) if ann_id in c.anns and c.c.strip()]
        for k, c in enumerate(chars):
            if ann_id in c.anns and (k < idx[0] or k > idx[-1]):
                c.anns.remove(ann_id)
    return expanded


# ---------------------------------------------------------------- main entry

def extract(path, context=0, include_underline=False, expand_partial_words=False):
    """Process one PDF into a DocResult. Raises PdfProblem for files that cannot be used."""
    doc = open_pdf(path)
    try:
        return _extract_doc(doc, path, context, include_underline, expand_partial_words)
    finally:
        doc.close()


def _extract_doc(doc, path, context, include_underline, expand_partial_words=False):
    kinds = (HIGHLIGHT, UNDERLINE) if include_underline else (HIGHLIGHT,)
    n = doc.page_count
    pages_lines, heights, widths = [], [], []
    total_chars = 0
    ocr_pages = 0
    for pno in range(n):
        page = doc[pno]
        lines = _parse_page(page, pno)
        pages_lines.append(lines)
        heights.append(page.rect.height)
        widths.append(page.rect.width)
        txt = sum(len(l.chars) for l in lines)
        total_chars += txt
        try:
            parea = page.rect.width * page.rect.height
            for im in page.get_image_info():
                b = im["bbox"]
                if txt > 100 and (b[2] - b[0]) * (b[3] - b[1]) >= 0.8 * parea:
                    ocr_pages += 1
                    break
        except Exception:
            pass

    annots, quads_by_ann, nid = [], {}, 0
    for pno in range(n):
        got, nid = _read_annots(doc[pno], pno, kinds, nid)
        for ann, quads in got:
            annots.append(ann)
            quads_by_ann[ann.id] = quads

    title = real_title(doc)
    result = DocResult(path, title or "", "PDF metadata" if title else "", n, [], found=len(annots))

    if total_chars <= 20:
        if annots or any(doc[i].get_images() for i in range(n)):
            raise PdfProblem("no text layer", "scanned pages without text: needs OCR first")
        return result
    if not annots:
        return result

    sizes = Counter()
    for lines in pages_lines:
        for l in lines:
            sizes[l.size] += sum(1 for c in l.chars if c.c.strip())
    body_size = sizes.most_common(1)[0][0]
    _classify(pages_lines, heights, body_size)

    # annotations -> characters (all lines, whatever their kind)
    for ann in annots:
        ann.expanded = _assign(pages_lines[ann.page], quads_by_ann[ann.id], ann.id, expand_partial_words)

    # reading order and sequence numbers
    ordered = {"body": [], "footnote": [], "furniture": []}
    seq = 0
    col_left, col_right, pitch = {}, {}, {}
    for pno, lines in enumerate(pages_lines):
        body = _order([l for l in lines if l.kind == "body"], widths[pno])
        foot = sorted(_merge_baseline([l for l in lines if l.kind == "footnote"]),
                      key=lambda l: (l.bbox[1], l.bbox[0]))
        furn = sorted([l for l in lines if l.kind == "furniture"], key=lambda l: (l.bbox[1], l.bbox[0]))
        for group, name in ((body, "body"), (foot, "footnote"), (furn, "furniture")):
            for l in group:
                l.seq = seq
                seq += 1
            ordered[name].extend(group)
        for key in {(l.page, l.col) for l in body}:
            xs = sorted(l.bbox[0] for l in body if (l.page, l.col) == key)
            ye = sorted(l.bbox[2] for l in body if (l.page, l.col) == key)
            col_left[key] = xs[len(xs) // 10]
            col_right[key] = ye[-1 - len(ye) // 10]
        gaps = [b.bbox[1] - a.bbox[1] for a, b in zip(body, body[1:]) if a.col == b.col and a.col != -1
                and 0 < b.bbox[1] - a.bbox[1] < 3 * a.size]
        if gaps:
            gaps.sort()
            pitch[pno] = gaps[len(gaps) // 2]
        for key in {(l.page, l.col) for l in foot}:
            xs = sorted(l.bbox[0] for l in foot if (l.page, l.col) == key)
            ye = sorted(l.bbox[2] for l in foot if (l.page, l.col) == key)
            col_left[key] = xs[len(xs) // 10]
            col_right[key] = ye[-1 - len(ye) // 10]
    vocab = set()
    for lines in pages_lines:
        for l in lines:
            vocab.update(w.lower() for w in re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", l.text))

    streams, events = {}, []
    streams["body"], ev = _stream_paragraphs(ordered["body"], vocab, col_left, col_right, pitch)
    events += ev
    streams["footnote"], ev = _stream_paragraphs(ordered["footnote"], vocab, col_left, col_right, pitch,
                                                 marker_breaks=True)
    events += ev
    streams["furniture"], _ = _stream_paragraphs(ordered["furniture"], vocab, col_left, col_right, pitch,
                                                 one_per_line=True)

    furn_text = {}
    for l in ordered["furniture"]:
        furn_text.setdefault(l.page, []).append(l.text)
    printed = detect_printed(doc, furn_text)

    result.excerpts = _build_excerpts(annots, streams, printed, context)
    result.found = len(annots)
    result.no_text = sum(1 for a in annots if not any(
        a.id in c.anns and c.ch.strip() for ps in streams.values() for p in ps for c in p.cells))
    result.exported = result.found - result.no_text
    result.flagged = sum(1 for e in result.excerpts if e.flags)
    if ocr_pages >= max(1, n // 2):
        result.notes.append("Scanned pages with an OCR text layer: the wording is the scan's own text, "
                            "so recognition typos are possible. Check against the page image.")
    joined = [t for k, t in events if k == "joined"]
    if joined:
        result.notes.append(f"{len(joined)} line-end hyphens were joined because the word appears unhyphenated "
                            "elsewhere in the document.")
    return result


def _printed_range(pages, printed):
    p0, p1 = pages
    labs = [printed.get(p) for p in range(p0, p1 + 1)]
    have = [l[0] for l in labs if l]
    if not have:
        return None, False
    return (have[0], have[-1]), len(have) != len(labs)


def _build_excerpts(annots, streams, printed, context):
    by_id = {a.id: a for a in annots}
    locs = {a.id: {} for a in annots}  # ann id -> {stream: set(para idx)}
    for sname, paras in streams.items():
        for pi, p in enumerate(paras):
            for c in p.cells:
                for aid in c.anns:
                    locs[aid].setdefault(sname, set()).add(pi)

    items = []  # (stream, lo, hi, ann_id)
    empties = []
    for a in annots:
        has_text = any(c.ch.strip() and a.id in c.anns for ps in streams.values() for p in ps for c in p.cells)
        if not has_text or not locs[a.id]:
            empties.append(a)
            continue
        sname = "body" if "body" in locs[a.id] else sorted(locs[a.id])[0]
        pis = locs[a.id][sname]
        n_par = len(streams[sname])
        items.append([sname, max(0, min(pis) - context), min(n_par - 1, max(pis) + context), a.id])

    groups = []
    for sname in ("body", "footnote", "furniture"):
        cur = None
        for it in sorted((i for i in items if i[0] == sname), key=lambda i: (i[1], i[2])):
            if cur and it[1] <= cur[2]:
                cur[2] = max(cur[2], it[2])
                cur[3].append(it[3])
            else:
                cur = [sname, it[1], it[2], [it[3]]]
                groups.append(cur)

    excerpts = []
    for sname, lo, hi, ids in groups:
        paras = streams[sname][lo:hi + 1]
        hl_cells = [c for p in paras for c in p.cells if any(i in ids for i in c.anns) and c.ch.strip()]
        pgs = (min(c.page for c in hl_cells), max(c.page for c in hl_cells))
        ex = Excerpt(kind=sname, paras=[], pages=(pgs[0] + 1, pgs[1] + 1), ann_ids=sorted(ids))
        ex.sortkey = (min(c.seq for c in hl_cells), 0)
        pr, partial = _printed_range(pgs, printed)
        ex.printed = pr
        if partial:
            ex.notes.append("printed page number not found for every page of this excerpt")
        for p in paras:
            runs, buf, cur_key, cur_col = [], "", None, None
            for c in p.cells:
                key = next((i for i in c.anns if i in ids), None)
                if key != cur_key and buf:
                    runs.append(Run(buf, cur_key is not None, cur_col, cur_key))
                    buf = ""
                if key != cur_key:
                    cur_key = key
                    cur_col = by_id[key].color if key is not None else None
                buf += c.ch
            if buf:
                runs.append(Run(buf, cur_key is not None, cur_col, cur_key))
            ex.paras.append(runs)
            if p.crosses and any(i in ids for c in p.cells for i in c.anns):
                if "paragraph continues across a page or column break" not in ex.flags:
                    ex.flags.append("paragraph continues across a page or column break: check the join")
            first = next((i for i, c in enumerate(p.cells) if any(a in ids for a in c.anns)), None)
            if first is not None:
                last = max(i for i, c in enumerate(p.cells) if any(a in ids for a in c.anns))
                if any(c.note == "hyphen kept" for c in p.cells[first:last + 1]):
                    ex.flags.append("line-end hyphen kept: confirm the word")
                # partial word at either end of a highlighted run
                if _partial_word(p.cells, ids):
                    ex.flags.append("highlight starts or ends inside a word")
        if any(by_id[i].expanded for i in ids):
            ex.notes.append("a clipped word at the edge of a highlight was marked whole")
        if sname == "footnote":
            ex.notes.append("footnote")
        if sname == "furniture":
            ex.flags.append("highlight is on a running header/footer or page number")
        shared = [i for i in ids if sum(1 for c in hl_cells if i in c.anns and len(c.anns) > 1) > 0]
        if shared:
            ex.flags.append("overlapping highlights: a later highlight shares text with an earlier one")
        ex.comments = [by_id[i].content for i in ids if by_id[i].content]
        ex.flags = list(dict.fromkeys(ex.flags))
        excerpts.append(ex)

    for a in empties:
        ex = Excerpt(kind="body", paras=[], pages=(a.page + 1, a.page + 1), ann_ids=[a.id], empty=True)
        ex.flags.append("no text found under this highlight: check the PDF")
        pr, _ = _printed_range((a.page, a.page), printed)
        ex.printed = pr
        ex.sortkey = (10 ** 9 + a.page, a.id)
        ex.comments = [a.content] if a.content else []
        excerpts.append(ex)

    real = sorted((e for e in excerpts if not e.empty), key=lambda e: e.sortkey)
    for e in excerpts:
        if e.empty:
            pos = next((i for i, r in enumerate(real) if r.pages[0] > e.pages[0]), len(real))
            real.insert(pos, e)
    for i, e in enumerate(real, 1):
        e.number = i
    return real


def _partial_word(cells, ids):
    for i, c in enumerate(cells):
        inside = any(a in ids for a in c.anns)
        if not inside or not c.ch.strip():
            continue
        prev_in = i > 0 and any(a in ids for a in cells[i - 1].anns)
        next_in = i + 1 < len(cells) and any(a in ids for a in cells[i + 1].anns)
        if not prev_in and i > 0 and cells[i - 1].ch.isalnum() and c.ch.isalnum():
            return True
        if not next_in and i + 1 < len(cells) and cells[i + 1].ch.isalnum() and c.ch.isalnum():
            return True
    return False
