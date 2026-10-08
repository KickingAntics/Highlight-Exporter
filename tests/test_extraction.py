"""Layer 1: exact-answer tests on generated PDFs."""
import pymupdf
import pytest

from highlight_export.extract import extract
from highlight_export.write_docx import word_color

from pdfmaker import (BLUE, GREEN, PARA1, PARA2, PARA3, PINK, RED, YELLOW, frame, hl, new_doc, put, save)


def hl_runs(res):
    return [[r.text for r in p if r.hl] for e in res.excerpts for p in e.paras]


def all_hl(res):
    return [r.text for e in res.excerpts for p in e.paras for r in p if r.hl]


def para_text(ex, i=0):
    return "".join(r.text for r in ex.paras[i])


def one_page(tmp_path, build):
    d = new_doc()
    p = d.new_page()
    build(p)
    return save(d, tmp_path / "t.pdf")


def test_01_single_line_highlight(tmp_path):
    def b(p):
        put(p, 72, 100, PARA1)
        hl(p, "written limits on government power")
    res = extract(one_page(tmp_path, b))
    assert res.found == 1 and res.exported == 1 and res.no_text == 0
    assert all_hl(res) == ["written limits on government power"]
    assert res.excerpts[0].pages == (1, 1)
    assert para_text(res.excerpts[0]) == " ".join(PARA1)
    assert res.excerpts[0].flags == []


def test_02_multiline_no_neighbour_bleed(tmp_path):
    def b(p):
        put(p, 72, 100, PARA1)
        hl(p, "limits on government power were essential to",
           "preserving liberty. Courts therefore began to treat the document as"[:30] if False else
           "preserving liberty. Courts therefore began to treat the document as",
           "enforceable law,")
    res = extract(one_page(tmp_path, b))
    assert len(res.excerpts) == 1
    assert all_hl(res) == ["limits on government power were essential to preserving liberty. Courts "
                           "therefore began to treat the document as enforceable law,"]


def test_03_partial_word(tmp_path):
    def b(p):
        put(p, 72, 100, ["The Westminster Standards were adopted in 1647 by the assembly."])
        hl(p, "Stand")
    res = extract(one_page(tmp_path, b))
    assert all_hl(res) == ["Stand"]
    assert any("inside a word" in f for f in res.excerpts[0].flags)


def _two_columns():
    left = [f"left line {i:02d} alpha beta gamma delta epsilon" for i in range(1, 13)]
    right = [f"right line {i:02d} zeta eta theta iota kappa" for i in range(1, 13)]
    left[6] = "left line 07 alpha beta gamma delta epsilon"
    return left, right


def test_04_two_columns_reading_order_and_crossing(tmp_path):
    left, right = _two_columns()

    def b(p):
        # paragraph break (indent + gap) at left line 7 and right line 5
        y = 100
        for i, t in enumerate(left):
            x = 86 if i == 6 else 72
            y_i = 100 + i * 12 + (8 if i >= 6 else 0)
            p.insert_text((x, y_i), t, fontsize=10, fontname="helv")
        for i, t in enumerate(right):
            x = 336 if i == 4 else 322
            y_i = 100 + i * 12 + (8 if i >= 4 else 0)
            p.insert_text((x, y_i), t, fontsize=10, fontname="helv")
        hl(p, "right line 02 zeta eta")
        hl(p, "left line 02 alpha beta")
    res = extract(one_page(tmp_path, b))
    assert [e.number for e in res.excerpts] == [1, 2]
    assert all_hl(res) == ["left line 02 alpha beta", "right line 02 zeta eta"]
    second = para_text(res.excerpts[1])
    assert second.index("left line 07") < second.index("left line 12") < second.index("right line 01")
    assert any("across a page or column" in f for f in res.excerpts[1].flags)


def test_05_header_footer_excluded_and_printed_page(tmp_path):
    d = new_doc()
    for i in range(4):
        p = d.new_page()
        frame(p, header="Journal of Testing 2024", footer=str(101 + i))
        put(p, 72, 100, PARA1 + [""] if False else PARA1)
        if i == 2:
            hl(p, "written limits on government power")
    res = extract(save(d, tmp_path / "t.pdf"))
    ex = res.excerpts[0]
    assert ex.pages == (3, 3) and ex.printed == ("103", "103")
    text = para_text(ex)
    assert "Journal of Testing" not in text and "103" not in text


def test_06_footnote_separated(tmp_path):
    d = new_doc()
    for i in range(3):
        p = d.new_page()
        put(p, 72, 100, [f"{chr(97 + i) * 4} {l}" for l in PARA1])
        put(p, 72, 700 - 12 * i, ["1 Smith, supra note 3, at 45 (describing the early cases)."], size=8)
        if i == 1:
            hl(p, "written limits on government power")
            hl(p, "describing the early cases")
    res = extract(save(d, tmp_path / "t.pdf"))
    body = next(e for e in res.excerpts if e.kind == "body")
    foot = next(e for e in res.excerpts if e.kind == "footnote")
    assert "Smith" not in para_text(body)
    assert "describing the early cases" in para_text(foot)
    assert [r.text for r in foot.paras[0] if r.hl] == ["describing the early cases"]


def test_07_three_highlights_one_paragraph(tmp_path):
    def b(p):
        put(p, 72, 100, PARA1)
        hl(p, "framers of the constitution")
        hl(p, "written limits")
        hl(p, "not mere aspiration.")
    res = extract(one_page(tmp_path, b))
    assert len(res.excerpts) == 1
    assert hl_runs(res) == [["framers of the constitution", "written limits", "not mere aspiration."]]


def test_08_paragraph_across_pages(tmp_path):
    d = new_doc()
    p1 = d.new_page()
    put(p1, 72, 640, ["The framers of the constitution disagreed about many things, but they",
                      "agreed that written limits on government power were essential to the"])
    p2 = d.new_page()
    put(p2, 72, 72, ["preserving of liberty. Courts therefore began to treat it as law."])
    hl(d[0], "essential to the")
    hl(d[1], "preserving of liberty.")
    res = extract(save(d, tmp_path / "t.pdf"))
    assert len(res.excerpts) == 1
    ex = res.excerpts[0]
    assert ex.pages == (1, 2)
    assert hl_runs(res) == [["essential to the", "preserving of liberty."]]
    assert any("across a page" in f for f in ex.flags)


def test_09_hyphenation(tmp_path):
    def b(p):
        put(p, 72, 100, ["We study the constitution of the state, and we study the consti-",
                         "tution of the nation. These ideas are self-",
                         "evident to anyone who reads carefully."])
        hl(p, "consti-", "tution of the nation.")
        hl(p, "self-", "evident to")
    res = extract(one_page(tmp_path, b))
    assert all_hl(res) == ["constitution of the nation.", "self-evident to"]
    flags = res.excerpts[0].flags
    assert any("hyphen kept" in f for f in flags)
    assert "constitution of the nation." in para_text(res.excerpts[0])
    assert any("hyphens were joined" in n for n in res.notes)


def test_10_overlapping_context_merges(tmp_path):
    def b(p):
        y = put(p, 72, 100, PARA1)
        y = put(p, 72, y, PARA2, )
        put(p, 72, y, PARA3)
        hl(p, "written limits on government power")
        hl(p, "lack the democratic standing")
    path = one_page(tmp_path, b)
    res0 = extract(path, context=0)
    assert len(res0.excerpts) == 2
    res1 = extract(path, context=1)
    assert len(res1.excerpts) == 1
    ex = res1.excerpts[0]
    assert len(ex.paras) == 3 and hl_runs(res1)[0] == ["written limits on government power"] and \
        hl_runs(res1)[1] == ["lack the democratic standing"]


def test_11_color_mapping():
    assert word_color(YELLOW) == "YELLOW"
    assert word_color((1.0, 0.76, 0.0)) == "YELLOW"
    assert word_color(GREEN) == "BRIGHT_GREEN"
    assert word_color(BLUE) == "BLUE"
    assert word_color(PINK) == "PINK"
    assert word_color(RED) == "RED"
    assert word_color((0.6, 0.8, 1.0)) == "TURQUOISE"
    assert word_color(None) == "YELLOW"


def test_11b_color_carried_to_runs(tmp_path):
    def b(p):
        put(p, 72, 100, PARA1)
        hl(p, "framers of the constitution", color=GREEN)
        hl(p, "written limits", color=PINK)
    res = extract(one_page(tmp_path, b))
    colors = [r.color for e in res.excerpts for p in e.paras for r in p if r.hl]
    assert colors == [GREEN, PINK]


def test_12_page_labels(tmp_path):
    d = new_doc()
    for i in range(4):
        p = d.new_page()
        put(p, 72, 100, PARA1)
        if i == 2:
            hl(p, "written limits on government power")
    d.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                       {"startpage": 2, "prefix": "", "style": "D", "firstpagenum": 1}])
    res = extract(save(d, tmp_path / "a.pdf"))
    assert res.excerpts[0].pages == (3, 3) and res.excerpts[0].printed == ("1", "1")

    d = new_doc()
    for i in range(4):
        p = d.new_page()
        put(p, 72, 100, PARA1)
        if i == 2:
            hl(p, "written limits on government power")
    res = extract(save(d, tmp_path / "b.pdf"))
    assert res.excerpts[0].printed is None  # nothing reliable: never estimated


def test_13_highlight_over_nothing_is_listed(tmp_path):
    def b(p):
        put(p, 72, 100, PARA1)
        hl(p, "written limits")
        p.add_highlight_annot(pymupdf.Rect(300, 600, 400, 614))
    res = extract(one_page(tmp_path, b))
    assert res.found == 2 and res.exported == 1 and res.no_text == 1
    empty = [e for e in res.excerpts if e.empty]
    assert len(empty) == 1 and "no text found" in empty[0].flags[0] and empty[0].pages == (1, 1)


def test_14_same_sentence_twice_uses_position(tmp_path):
    def b(p):
        y = put(p, 72, 100, ["Alpha opens here. The identical sentence appears in both places.",
                             "End of the alpha paragraph, which is quite short."])
        put(p, 72, y, ["Beta opens here. The identical sentence appears in both places.",
                       "End of the beta paragraph, which is quite short."])
        hl(p, "The identical sentence appears in both places.", occurrence=1)
    res = extract(one_page(tmp_path, b))
    ex = res.excerpts[0]
    assert len(ex.paras) == 1
    assert "Beta" in para_text(ex) and "Alpha" not in para_text(ex)


@pytest.mark.parametrize("mode", ["rotate", "crop"])
def test_15_rotated_and_cropped_pages(tmp_path, mode):
    d = new_doc()
    p = d.new_page()
    put(p, 72, 100, PARA1)
    if mode == "rotate":
        p.set_rotation(90)
    else:
        p.set_cropbox(pymupdf.Rect(50, 50, 500, 400))
    hl(p, "written limits on government power")
    res = extract(save(d, tmp_path / "t.pdf"))
    assert all_hl(res) == ["written limits on government power"]


def test_16_comment_text_kept(tmp_path):
    def b(p):
        put(p, 72, 100, PARA1)
        hl(p, "written limits", content="check this cite")
    res = extract(one_page(tmp_path, b))
    assert res.excerpts[0].comments == ["check this cite"]


def test_17_excerpts_in_page_order(tmp_path):
    d = new_doc()
    for i in range(3):
        p = d.new_page()
        put(p, 72, 100, PARA1)
    hl(d[2], "written limits")
    hl(d[0], "framers of the constitution")
    hl(d[1], "enforceable law")
    res = extract(save(d, tmp_path / "t.pdf"))
    assert [e.pages[0] for e in res.excerpts] == [1, 2, 3]


def test_18_repeated_footnote_text_is_not_a_running_footer(tmp_path):
    """'Id.'-style footnotes repeat but sit at different heights: they stay footnotes."""
    d = new_doc()
    for i in range(4):
        p = d.new_page()
        put(p, 72, 100, [f"{chr(97 + i) * 4} {l}" for l in PARA1])
        put(p, 72, 690 - 14 * i, ["2 Id. at 18."], size=8)
    hl(d[1], "Id. at 18.")
    res = extract(save(d, tmp_path / "t.pdf"))
    assert res.excerpts[0].kind == "footnote"


def _clipped(page, phrase, left_covered, right_covered):
    """Highlight `phrase` but cut the first/last letter so only the given share of it is covered."""
    rect = page.search_for(phrase)[0]
    first = page.get_text("rawdict", clip=rect)["blocks"][0]["lines"][0]["spans"][0]["chars"]
    w0 = first[0]["bbox"][2] - first[0]["bbox"][0]
    w1 = first[-1]["bbox"][2] - first[-1]["bbox"][0]
    a = page.add_highlight_annot(pymupdf.Rect(rect.x0 + w0 * (1 - left_covered), rect.y0,
                                              rect.x1 - w1 * (1 - right_covered), rect.y1))
    a.update()


def test_19_clipped_edge_letters_are_included(tmp_path):
    """A highlight that visibly touches the first/last letter of a word marks the whole word."""
    def b(p):
        put(p, 72, 100, ["Entry into the job market is hard for new scholars."])
        _clipped(p, "job market", 0.35, 0.35)
    res = extract(one_page(tmp_path, b))
    assert all_hl(res) == ["job market"]
    assert res.excerpts[0].flags == []


def test_20_barely_touched_letters_stay_out_and_are_flagged(tmp_path):
    def b(p):
        put(p, 72, 100, ["Entry into the job market is hard for new scholars."])
        _clipped(p, "job market", 0.05, 0.05)
    res = extract(one_page(tmp_path, b))
    assert all_hl(res) == ["ob marke"]
    assert any("inside a word" in f for f in res.excerpts[0].flags)


def test_21_printed_numbers_survive_omitted_pages(tmp_path):
    """Excerpted PDFs skip pages: printed numbers 150, 151, 153, 158, 159 still read correctly."""
    d = new_doc()
    printed = [150, 151, 153, 158, 159]
    for i, num in enumerate(printed):
        p = d.new_page()
        frame(p, header=f"Some Law Review 1992 {num}")
        put(p, 72, 100, [f"{chr(97 + i) * 4} {l}" for l in PARA1])
    hl(d[3], "written limits")
    res = extract(save(d, tmp_path / "t.pdf"))
    assert res.excerpts[0].pages == (4, 4) and res.excerpts[0].printed == ("158", "158")


def test_22_constant_year_in_header_is_not_a_page_number(tmp_path):
    d = new_doc()
    for i in range(5):
        p = d.new_page()
        frame(p, header="Some Law Review 1992")
        put(p, 72, 100, [f"{chr(97 + i) * 4} {l}" for l in PARA1])
    hl(d[2], "written limits")
    res = extract(save(d, tmp_path / "t.pdf"))
    assert res.excerpts[0].printed is None


def test_23_expand_partial_words_is_opt_in_and_noted(tmp_path):
    def b(p):
        put(p, 72, 100, ["The Westminster Standards were adopted in 1647 by the assembly."])
        hl(p, "Stand")
    path = one_page(tmp_path, b)
    exact = extract(path)
    assert all_hl(exact) == ["Stand"]
    whole = extract(path, expand_partial_words=True)
    assert all_hl(whole) == ["Standards"]
    assert whole.excerpts[0].flags == []
    assert any("marked whole" in n for n in whole.excerpts[0].notes)


def test_24_citation_fragment_in_its_own_block_stays_in_the_paragraph(tmp_path):
    """A cite that arrives as a separate text object on the same baseline must not split the paragraph."""
    def b(p):
        y = 100
        for i in range(5):
            p.insert_text((72, y + 14 * i), f"plain filler line number {chr(97 + i) * 3} of the first paragraph",
                          fontsize=11, fontname="helv")
        y2 = 100 + 14 * 5
        p.insert_text((72, y2), "unlawful interest in racial balancing.", fontsize=11, fontname="helv")
        p.insert_text((72 + 215, y2 + 0.4), "Id., at 306-307.", fontsize=11, fontname="helv")
        p.insert_text((72 + 300, y2), "Second, the Justice rejected", fontsize=11, fontname="helv")
        p.insert_text((72, y2 + 14), "a further interest in remedying societal discrimination.", fontsize=11,
                      fontname="helv")
        hl(p, "Second, the Justice rejected", "a further interest in remedying societal discrimination.")
    res = extract(one_page(tmp_path, b))
    text = para_text(res.excerpts[0])
    assert "balancing. Id., at 306-307. Second" in text and len(res.excerpts[0].paras) == 1


def test_25_printed_numbers_restart_in_each_section(tmp_path):
    """A syllabus (1-3) followed by an opinion that restarts at 1: each section reads correctly."""
    d = new_doc()
    numbers = [1, 2, 3, 1, 2, 3, 4, 5, 6]
    for i, num in enumerate(numbers):
        p = d.new_page()
        frame(p, header=f"Cite as: 603 U. S. (2024) {num}")
        put(p, 72, 100, [f"{chr(97 + i) * 4} {l}" for l in PARA1])
    hl(d[1], "written limits")   # section one: printed number equals the PDF position
    hl(d[5], "written limits")   # section two: PDF page 6 is printed page 3
    hl(d[8], "written limits")   # PDF page 9 is printed page 6
    res = extract(save(d, tmp_path / "t.pdf"))
    assert [(e.pages[0], e.printed) for e in res.excerpts] == [(2, None), (6, ("3", "3")), (9, ("6", "6"))]


def test_26_scattered_numbers_are_not_page_numbers(tmp_path):
    d = new_doc()
    for i, num in enumerate([57, 3, 912, 40, 7, 1990]):
        p = d.new_page()
        frame(p, header=f"Some Review {num}")
        put(p, 72, 100, [f"{chr(97 + i) * 4} {l}" for l in PARA1])
    hl(d[2], "written limits")
    assert extract(save(d, tmp_path / "t.pdf")).excerpts[0].printed is None


def test_27_footnote_marker_after_the_last_sentence_still_ends_the_paragraph(tmp_path):
    """"...(1961).3" then a centered heading on the next page: the heading is not part of the paragraph."""
    d = new_doc()
    p1 = d.new_page()
    put(p1, 72, 100, ["Courts decide legal questions by applying their own independent judgment to every",
                      "dispute that reaches them, and the statute leaves no room for another approach.",
                      "See Smith v. Jones, 366 U. S. 36, 50 (1961).3"])
    p2 = d.new_page()
    p2.insert_text((300, 100), "A", fontsize=11, fontname="helv")
    put(p2, 72, 130, ["The next section begins here and discusses something else entirely, at length,",
                      "across several lines of ordinary body text on the second page."], indent=18)
    hl(d[0], "independent judgment")
    res = extract(save(d, tmp_path / "t.pdf"))
    ex = res.excerpts[0]
    assert para_text(ex).endswith("(1961).3") and ex.flags == []
