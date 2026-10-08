# Highlight Exporter

Turns the highlights you made in PDFs into editable Word documents: each highlighted passage, the
paragraph around it, and its page number. Everything runs on your computer. Nothing is uploaded, and
your PDFs are never changed.

![Input: a PDF with highlights](docs/input-pdf.png)

![Output: the Word document](docs/output-word.png)

The pictures show an invented sample (`examples/`): the PDF you highlighted, and the Word file the
tool produces from it.

## Get it

Windows only. You need [Python 3.10 or newer](https://www.python.org/downloads/) installed once
(tick "Add python.exe to PATH" in the installer).

1. On this page choose **Code, then Download ZIP** (or download the zip from the Releases page).
2. Unzip it anywhere, keeping the folder together. Do not move the `.bat` out of the folder; make a
   shortcut to it instead.
3. Double-click **Export Highlights.bat**. The first run installs what it needs (a minute or two,
   internet required once).

## Using it

1. Double-click **Export Highlights.bat**. (Or drag a PDF, several PDFs, or a folder onto it.)
2. Choose one or more PDF files, or a folder of PDFs. Folders are searched including subfolders.
3. Confirm where to save. The default is a folder called `Highlights Export` next to your PDFs.
4. Read the summary in the window. When it finishes it asks "Run again?": press Y to export more
   PDFs without reopening it, or N to close.

The first time on a computer it sets itself up (a minute or two, needs internet once). Python must
be installed; if it is not, the window says so and where to get it.

## What you get

- One Word file per PDF: `<PDF name> (highlights).docx`. If two PDFs share a name, the folder name is
  added. For each highlight the file shows the source name, the page, and the paragraph, with only
  the highlighted words emphasized.
- Optional `_Combined highlights.docx`: every source in one file, each starting on a new page.
- A `Reports` subfolder with `Export report <date time>.txt` and `.csv`: for every PDF, how many
  highlights were found, exported, or need a look, and why any file was skipped. The main folder
  holds only Word documents.

Excerpt layout:

```
Source title (or file name)
File: name.pdf   ·   Title source: PDF metadata   ·   15 highlights found ...

Excerpt 1 — PDF page 3 (printed page 151)
  ...paragraph text with [the highlighted words] emphasized...
Excerpt 2 — PDF pages 7–8
  ⚠ Review: paragraph continues across a page or column break: check the join
  ...
```

- **PDF page** is always the one-based position in the PDF. **Printed page** appears only when the
  PDF's own page labels or its running header/footer numbers give a reliable answer. Nothing is
  estimated.
- A title is used only if the PDF really contains one; otherwise the file name is the heading.

## Re-running is safe

The tool never overwrites a Word file. If the name already exists (for example you edited it), the
new file gets a date and time in its name and the report says so.

## Settings

Edit `settings.json` (or ask for a different option when launching):

| Setting | Values | Meaning |
|---|---|---|
| `context` | `paragraph` (default), `paragraphs` | The paragraph that holds the highlight, or also the paragraph before and after. Overlapping contexts merge into one excerpt. |
| `emphasis` | `highlight` (default), `bold` | Word highlight in the closest of Word's colors (orange and gold become yellow), or bold. |
| `combined` | `false` / `true` | Also write one combined file. |
| `include_underline` | `false` / `true` | Also export underline annotations. |
| `expand_partial_words` | `false` / `true` | If a highlight clips the edge of a word, mark the whole word and note it. Off by default, which exports exactly what was selected and flags it. |

## What "Review" means

The tool never guesses silently. These are marked with a ⚠ in the Word file and counted in the report:

- the highlight starts or ends inside a word;
- a paragraph runs across a page or column break;
- a line-end hyphen was kept (could not confirm the word);
- the highlight is on a running header/footer or page number;
- two highlights overlap;
- no text was found under a highlight (still listed, never dropped).

Line-end hyphens are rejoined only when the unhyphenated word appears elsewhere in the same PDF, and
the report counts them.

## Limits (first version)

- Works on PDFs that contain real highlight annotations and a text layer. Scanned PDFs that already
  have an OCR text layer work, with the scan's own recognition errors. Scans with no text layer are
  reported as needing OCR.
- Highlights painted into the page as colored shapes (not annotations) are not detected. The report
  says when a PDF has colored rectangles that might be such highlights.
- Paragraph boundaries are a best guess from layout (indent, spacing, line length). Unusual layouts,
  tables, and sidebars can produce a shorter or longer context paragraph. The highlighted words
  themselves come straight from the PDF and are exact.
- Password-protected, empty, and damaged files are reported and skipped; other files keep going.
- If a file is stored online-only in OneDrive, make it available offline first (the report says so).

## For whoever maintains it

- `highlight_export/extract.py` finds highlights and maps them to the text underneath;
  `pages.py` finds printed page numbers; `write_docx.py` writes the Word files; `cli.py` handles the
  windows, file naming, and report.
- Tests: `python -m pip install -r requirements-dev.txt`, then `python -m pytest`. Most tests build
  their own small PDFs with known answers. Extra tests run only if a local, untracked
  `test-samples` folder exists.
- The repository must never contain names, paths, or text from anyone's real documents; a test
  enforces this.
- Licensed under the GNU Affero General Public License v3.0 (see `LICENSE`), which matches the
  license of PyMuPDF, the PDF library it relies on. python-docx is MIT-licensed.

## License

Highlight Exporter is free software under the [GNU AGPL-3.0](LICENSE). You may use, study, change,
and share it; if you distribute a modified version, or let others use one over a network, you must
make your source available under the same license. It comes with no warranty. Check important
quotations against the original PDF.
