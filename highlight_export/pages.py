"""Printed page numbers: use PDF page labels or running-header numbers, only when reliable."""
from __future__ import annotations

import re

_INT_AT_EDGE = re.compile(r"^\s*(\d{1,4})(?=\s|\]|$)|(?:^|\s)(\d{1,4})\s*$")


def _edge_numbers(text):
    """Integers sitting at the start or end of a header/footer line."""
    found = []
    for m in _INT_AT_EDGE.finditer(text.strip()):
        found.append(int(m.group(1) or m.group(2)))
    return found


def detect_printed(doc, furniture_text_by_page):
    """Return {page_index: (label, source)} for pages with a reliable printed page number.

    Sources: 'PDF page label' (labels that differ from plain 1,2,3...) or
    'running header/footer' (numbers that move in step with the PDF page position).
    Pages without a reliable number are simply absent: nothing is estimated.
    """
    n = doc.page_count
    out = {}

    labels = []
    for i in range(n):
        try:
            labels.append((doc[i].get_label() or "").strip())
        except Exception:
            labels.append("")
    if any(labels) and any(lab and lab != str(i + 1) for i, lab in enumerate(labels)):
        for i, lab in enumerate(labels):
            if lab:
                out[i] = (lab, "PDF page label")
        return out

    cands = {}
    for i in range(n):
        nums = set()
        for text in furniture_text_by_page.get(i, []):
            nums.update(_edge_numbers(text))
        if nums:
            cands[i] = nums
    if len(cands) < 3 or len(cands) < 0.5 * n:
        return out

    # Printed page numbers only ever increase, and by at least as much as the PDF page position
    # (pages can be omitted from an excerpt). Find the longest such chain, one number per page.
    nodes = [(i, v) for i in sorted(cands) for v in sorted(cands[i])]
    best, prev = {}, {}
    for k, (i, v) in enumerate(nodes):
        best[k], prev[k] = 1, None
        for m in range(k):
            pi, pv = nodes[m]
            if pi < i and v > pv and (v - pv) >= (i - pi) and best[m] + 1 > best[k]:
                best[k], prev[k] = best[m] + 1, m
    end = max(best, key=lambda k: (best[k], -nodes[k][1]))
    chain, k = [], end
    while k is not None:
        chain.append(nodes[k])
        k = prev[k]
    if len(chain) < 3 or len(chain) < 0.7 * len(cands):
        return out
    if all(v == i + 1 for i, v in chain):
        return out  # identical to the PDF position: nothing new to say
    for i, v in chain:
        out[i] = (str(v), "running header/footer")
    return out
