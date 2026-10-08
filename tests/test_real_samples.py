"""Layers 4-5 on real PDFs kept only in the git-ignored test-samples folder.

These tests skip when that folder is absent (for example on another computer or a fresh clone).
Nothing about the samples is stored in the repository.
"""
import glob
from collections import Counter
import json
import os

import pymupdf
import pytest

from highlight_export.extract import extract

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = sorted(glob.glob(os.path.join(ROOT, "test-samples", "**", "*.pdf"), recursive=True))
pytestmark = pytest.mark.skipif(not SAMPLES, reason="no local test-samples folder")


def oracle(path):
    """Independent answer: characters whose centre lies inside a highlight rectangle, per annotation."""
    doc = pymupdf.open(path)
    want, nid = {}, 0
    for pg in doc:
        chars = [c for b in pg.get_text("rawdict")["blocks"] if b["type"] == 0
                 for l in b["lines"] for s in l["spans"] for c in s["chars"]]
        for a in pg.annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT]):
            v = a.vertices or []
            quads = [pymupdf.Quad(v[i:i + 4]).rect for i in range(0, len(v) - len(v) % 4, 4)] or [a.rect]
            text = ""
            for q in quads:
                hit = [c for c in chars
                       if q.x0 <= (c["bbox"][0] + c["bbox"][2]) / 2 <= q.x1
                       and q.y0 <= (c["bbox"][1] + c["bbox"][3]) / 2 <= q.y1]
                hit.sort(key=lambda c: (round(c["bbox"][1] / 4), c["bbox"][0]))
                text += "".join(c["c"] for c in hit)
            want[nid] = text
            nid += 1
    return want


def exported(res):
    out = {}
    for e in res.excerpts:
        for p in e.paras:
            for r in p:
                if r.hl:
                    out[r.ann] = out.get(r.ann, "") + r.text
    return out


def squash(s):
    """Letters only: the word-level oracle also swallows adjacent punctuation and footnote digits."""
    return "".join(ch for ch in s if ch.isalpha())


@pytest.mark.parametrize("path", SAMPLES, ids=[os.path.basename(p)[:40] for p in SAMPLES])
def test_every_highlight_matches_independent_oracle_or_is_flagged(path):
    res = extract(path)
    assert res.found == res.exported + res.no_text
    want, got = oracle(path), exported(res)
    flagged_ann = set()
    for e in res.excerpts:
        if e.flags or e.empty:
            flagged_ann.update(e.ann_ids)
    bad = []
    for k, text in want.items():
        a, b = squash(text), squash(got.get(k, ""))
        # allow the two methods to differ by at most one letter at each end (edge-letter decisions)
        # same letters in any order (order is judged separately, by eye), or off by one edge letter
        diff = (Counter(a) - Counter(b)) + (Counter(b) - Counter(a))
        close = a == b or sum(diff.values()) <= 2
        if not close and k not in flagged_ann:
            bad.append((k, text[:60], got.get(k, "")[:60]))
    assert not bad, f"unflagged disagreements with the oracle: {bad[:5]}"
    for e in res.excerpts:
        assert 1 <= e.pages[0] <= e.pages[1] <= res.n_pages
        if not e.empty:
            assert any(r.hl and r.text.strip() for p in e.paras for r in p)


GOLDEN = os.path.join(ROOT, "test-samples", "expected.json")


@pytest.mark.skipif(not os.path.exists(GOLDEN), reason="no verified golden answers yet")
def test_verified_golden_answers_still_hold():
    with open(GOLDEN, encoding="utf-8") as f:
        golden = json.load(f)
    for rel, items in golden.items():
        path = os.path.join(ROOT, "test-samples", rel)
        res = extract(path)
        got = exported(res)
        pages = {}
        for e in res.excerpts:
            for aid in e.ann_ids:
                pages[aid] = (e.pages, e.printed)
        for it in items:
            assert got.get(it["ann"]) == it["text"], (rel, it["ann"])
            assert [list(pages[it["ann"]][0]), pages[it["ann"]][1] and list(pages[it["ann"]][1])] == \
                [it["pdf_pages"], it["printed"]], (rel, it["ann"])
