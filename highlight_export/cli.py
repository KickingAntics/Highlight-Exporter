"""Choose PDFs, export highlights to Word, write a report. Never overwrites existing files."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

from . import write_docx
from .extract import PdfProblem, extract, open_pdf

DEFAULTS = {"context": "paragraph", "emphasis": "highlight", "combined": False,
            "include_underline": False, "expand_partial_words": False,
            "output_folder_name": "Highlights Export"}
TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def load_settings(path=None):
    s = dict(DEFAULTS)
    path = path or os.path.join(TOOL_DIR, "settings.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
        except (OSError, ValueError) as e:
            print(f"Could not read settings.json ({e}); using defaults.")
    return s


def collect_pdfs(inputs):
    out = []
    for p in inputs:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs.sort()
                for fn in sorted(files):
                    if fn.lower().endswith(".pdf"):
                        out.append(os.path.join(root, fn))
        elif os.path.isfile(p) and p.lower().endswith(".pdf"):
            out.append(p)
    seen, uniq = set(), []
    for p in out:
        k = os.path.normcase(p)
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def _clean(name):
    return _BAD.sub("_", name).strip(" .")[:120] or "document"


def plan_names(pdfs, base_for_parents):
    """Predictable output stems; identical PDF names get their folder name added."""
    stems = [_clean(os.path.splitext(os.path.basename(p))[0]) for p in pdfs]
    count = {}
    for s in stems:
        count[s.lower()] = count.get(s.lower(), 0) + 1
    names, used = [], set()
    for p, s in zip(pdfs, stems):
        name = s
        if count[s.lower()] > 1:
            parts = os.path.relpath(os.path.dirname(p), base_for_parents).split(os.sep)
            parent = _clean(" - ".join(x for x in parts if x not in (".", "..")) or "root")
            name = f"{parent} - {s}"
        k, final = 2, name
        while final.lower() in used:
            final = f"{name} ({k})"
            k += 1
        used.add(final.lower())
        names.append(final)
    return names


MAX_PATH_BUDGET = 235  # Windows stops at 260; leave room for a timestamp/counter suffix


def fit_name(folder, filename):
    """Shorten a too-long file name so the full path stays under the Windows limit."""
    room = MAX_PATH_BUDGET - len(os.path.abspath(folder)) - 1
    if len(filename) <= room:
        return filename
    stem, ext = os.path.splitext(filename)
    tail = ""
    for marker in (" (highlights)",):
        if stem.endswith(marker):
            stem, tail = stem[:-len(marker)], marker
    keep = max(12, room - len(tail) - len(ext) - 1)
    return stem[:keep].rstrip(" .") + "~" + tail + ext


def free_path(folder, filename):
    """A path that does not exist yet: add a timestamp, then a counter, never overwrite."""
    filename = fit_name(folder, filename)
    path = os.path.join(folder, filename)
    if not os.path.exists(path):
        return path, False
    stem, ext = os.path.splitext(filename)
    cand = os.path.join(folder, f"{stem} {write_docx.stamp()}{ext}")
    k = 2
    while os.path.exists(cand):
        cand = os.path.join(folder, f"{stem} {write_docx.stamp()}-{k}{ext}")
        k += 1
    return cand, True


def _flattened_hint(path):
    """True if a PDF without annotations has colored filled rectangles that may be painted highlights."""
    try:
        doc = open_pdf(path)
    except PdfProblem:
        return False
    try:
        for pno in range(min(doc.page_count, 40)):
            for d in doc[pno].get_drawings():
                f = d.get("fill")
                if not f or len(f) != 3:
                    continue
                r = d["rect"]
                if max(f) - min(f) >= 0.4 and r.height < 40 and r.width > 20:
                    return True
    except Exception:
        return False
    finally:
        doc.close()
    return False


def run(inputs, out_dir, settings, base=None, log=print):
    pdfs = collect_pdfs(inputs)
    if not pdfs:
        log("No PDF files found in the selection.")
        return []
    os.makedirs(out_dir, exist_ok=True)
    base = base or os.path.commonpath([os.path.dirname(p) for p in pdfs])
    names = plan_names(pdfs, base)
    context = 1 if settings["context"] == "paragraphs" else 0
    rows, combined = [], []
    for pdf, name in zip(pdfs, names):
        row = {"file": pdf, "status": "", "found": 0, "exported": 0, "no_text": 0, "flagged": 0,
               "output": "", "detail": ""}
        try:
            res = extract(pdf, context=context, include_underline=settings["include_underline"],
                          expand_partial_words=settings["expand_partial_words"])
            if res.found == 0:
                row["status"] = "no highlights"
                row["detail"] = "no highlight annotations found"
                if _flattened_hint(pdf):
                    row["detail"] += "; the page has colored rectangles that may be painted-in highlights " \
                                     "(not supported in this version)"
            else:
                path, renamed = free_path(out_dir, f"{name} (highlights).docx")
                write_docx.write_single(path, res, os.path.basename(pdf), settings["emphasis"])
                row.update(found=res.found, exported=res.exported, no_text=res.no_text, flagged=res.flagged)
                row["status"] = "exported"
                row["output"] = path
                if renamed:
                    row["detail"] = "an earlier output with this name exists and was left untouched; " \
                                    "this run saved a new file"
                combined.append((os.path.basename(pdf), res))
        except PdfProblem as e:
            row["status"], row["detail"] = e.status, e.detail
        except Exception as e:  # keep processing the other files
            row["status"], row["detail"] = "failed", f"{type(e).__name__}: {str(e)[:150]}"
        rows.append(row)
        log(f"  {row['status']:<14} {os.path.basename(pdf)}")
    if settings["combined"] and combined:
        path, _ = free_path(out_dir, "_Combined highlights.docx")
        write_docx.write_combined(path, combined, settings["emphasis"])
        log(f"Combined file: {path}")
    _write_report(rows, out_dir)
    return rows


REPORTS_FOLDER = "Reports"


def _write_report(rows, out_dir):
    stamp = write_docx.stamp()
    out_dir = os.path.join(out_dir, REPORTS_FOLDER)  # keep the Word files folder clean
    os.makedirs(out_dir, exist_ok=True)
    txt, _ = free_path(out_dir, f"Export report {stamp}.txt")
    lines = [f"Highlight export report {stamp}", ""]
    ok = [r for r in rows if r["status"] == "exported"]
    lines.append(f"{len(rows)} PDFs: {len(ok)} exported, {len(rows) - len(ok)} not exported.")
    lines.append(f"Highlights found {sum(r['found'] for r in rows)}, exported with text "
                 f"{sum(r['exported'] for r in rows)}, without text {sum(r['no_text'] for r in rows)}. "
                 f"Excerpts to review: {sum(r['flagged'] for r in rows)}.")
    lines.append("")
    for r in rows:
        lines.append(f"[{r['status']}] {r['file']}")
        if r["status"] == "exported":
            lines.append(f"    highlights found {r['found']}, exported {r['exported']}, no text {r['no_text']}; "
                         f"excerpts to review {r['flagged']}")
            lines.append(f"    -> {r['output']}")
        if r["detail"]:
            lines.append(f"    {r['detail']}")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    csvp, _ = free_path(out_dir, f"Export report {stamp}.csv")
    with open(csvp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nReport: {txt}")


def _ask_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    pick = messagebox.askyesnocancel("Export highlights",
                                     "Yes = choose one or more PDF files\nNo = choose a folder of PDFs")
    if pick is None:
        return None, None
    if pick:
        inputs = filedialog.askopenfilenames(title="Choose PDF files", filetypes=[("PDF", "*.pdf")])
    else:
        d = filedialog.askdirectory(title="Choose a folder of PDFs")
        inputs = (d,) if d else ()
    if not inputs:
        return None, None
    return list(inputs), root


def main(argv=None):
    ap = argparse.ArgumentParser(prog="highlight_export",
                                 description="Export highlighted PDF passages to Word (.docx).")
    ap.add_argument("inputs", nargs="*", help="PDF files or folders (leave empty to choose in a window)")
    ap.add_argument("--out", help="output folder (default: 'Highlights Export' next to the PDFs)")
    ap.add_argument("--context", choices=["paragraph", "paragraphs"])
    ap.add_argument("--emphasis", choices=["highlight", "bold"])
    ap.add_argument("--combined", action="store_true")
    ap.add_argument("--underline", action="store_true")
    ap.add_argument("--whole-words", action="store_true", help="mark a clipped word at a highlight edge whole")
    a = ap.parse_args(argv)
    s = load_settings()
    if a.context:
        s["context"] = a.context
    if a.emphasis:
        s["emphasis"] = a.emphasis
    if a.combined:
        s["combined"] = True
    if a.underline:
        s["include_underline"] = True
    if a.whole_words:
        s["expand_partial_words"] = True
    inputs, root = a.inputs, None
    if not inputs:
        inputs, root = _ask_gui()
        if not inputs:
            print("Nothing selected.")
            return 0
    first = os.path.abspath(inputs[0])
    default_out = os.path.join(first if os.path.isdir(first) else os.path.dirname(first),
                               s["output_folder_name"])
    out = a.out or default_out
    if root is not None and not a.out:
        from tkinter import filedialog, messagebox
        if not messagebox.askyesno("Export highlights", f"Save the Word files to:\n{default_out}\n\n"
                                   "Yes = use this folder   No = choose another"):
            d = filedialog.askdirectory(title="Choose where to save the Word files")
            if not d:
                print("Nothing selected.")
                return 0
            out = d
    print(f"Saving to: {out}\n")
    rows = run(inputs, out, s)
    ok = sum(1 for r in rows if r["status"] == "exported")
    print(f"\nDone: {ok} of {len(rows)} PDFs exported. Anything marked 'Review' in the Word files "
          "needs a quick look.")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
