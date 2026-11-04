"""
A scorecard for one book: how its text is laid out (font sizes, bold,
text problems) and, for a book with a profile in books/, how well ingest
reads it (recipe count, odd titles, recipes with no ingredients, lines
the ingredient parser rejected, group kinds). Meant for sizing up a new
book and for checking a parsing change from every side at once.

Reads the saved extraction (ingest_utils/extract.py), so it needs the
PDF only the first time. Run from app/ (either form works):
    python3 tools/diagnostics/book_report.py "BraveTart"
    python3 tools/diagnostics/book_report.py "BraveTart" --anchor "^YIELD:"
    python3 -m tools.diagnostics.book_report "Dessert Person"

--anchor REGEX lists every line matching it with the lines just above,
and their sizes, for finding a new book's titles from a line that always
follows them (a yield line, say).

Prints a summary; the full report, which quotes the book, goes to
testing/one_off/report_<book>.txt.
"""

import argparse
import os
import re
import sys
from collections import Counter, defaultdict

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so the shared modules can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from books import strategy_for  # noqa: E402  (imports need the path above)
from common.config import BOOK_FILES, PROJECT_ROOT, book_pdf_path  # noqa: E402
from ingest_utils.pdf_text import build_layout_stream  # noqa: E402
from ingest_utils.structure import structure_book  # noqa: E402
from match_utils.recipe_index import index_entry  # noqa: E402
from scale_utils.ingredients import extract_ingredient_groups  # noqa: E402

REPORT_DIR = os.path.join(PROJECT_ROOT, "testing", "one_off")

# Text problems worth fixing at extraction, each with how to spot it.
TEXT_PROBLEMS = {
    "private-use glyph": re.compile(r"[-]"),
    "replacement char": re.compile("�"),
    # "al l -purpose f lour": a lone lowercase letter other than "a"
    # split off a word. Not after a number, where it's a unit ("306 g").
    "spaced letters": re.compile(r"(?<![\w'’.&°-])(?<!\d )[b-z](?= -?[a-z])"
                                 r"|(?<=[a-z] )[b-z](?![\w'’.&-])"),
    # The Cookie Book's broken ligatures come out as IPA letters (ɻ, ɹ, ʃ).
    "IPA letter": re.compile(r"[\u0250-\u02af]"),
    "control char": re.compile(r"[\x00-\x08\x0b-\x1f]"),
}


def size_histogram(records):
    """Report lines for the font sizes in use, largest first. Body text
    is the size with the most characters; titles are usually above it."""
    by_size = defaultdict(list)
    for r in records:
        if r["text"].strip():
            by_size[r["size"]].append(r)
    chars = {size: sum(len(r["text"]) for r in rs) for size, rs in by_size.items()}
    body = max(chars, key=chars.get)
    out = [f"body size {body} ({chars[body] * 100 // sum(chars.values())}% of characters)",
           " size   lines  bold%  ital%  caps%  fonts / samples"]
    for size in sorted(by_size, reverse=True):
        rs = by_size[size]
        n = len(rs)
        caps = sum(1 for r in rs if r["text"].isupper())
        fonts = Counter(r["font"] for r in rs).most_common(2)
        out.append(f"{size:5.1f} {n:7d} {sum(r['bold'] for r in rs) * 100 // n:5d}  "
                   f"{sum(r['italic'] for r in rs) * 100 // n:5d}  {caps * 100 // n:5d}  "
                   + ", ".join(f"{f} x{c}" for f, c in fonts))
        step = max(1, n // 4)
        for r in rs[::step][:4]:
            out.append(f"{'':38}p{r['page']}: {r['text'][:60]}")
    return body, out


def text_problems(records):
    counts, samples = Counter(), defaultdict(list)
    for r in records:
        for name, pattern in TEXT_PROBLEMS.items():
            if pattern.search(r["text"]):
                counts[name] += 1
                if len(samples[name]) < 6:
                    samples[name].append(f"p{r['page']}: {r['text'][:70]!r}")
    out = []
    for name, n in counts.most_common():
        out.append(f"{name}: {n} lines")
        out.extend(f"    {s}" for s in samples[name])
    return counts, out or ["none found"]


def anchor_report(records, pattern):
    """Every line matching pattern, with the three lines above it."""
    regex = re.compile(pattern)
    out, n = [], 0
    for i, r in enumerate(records):
        if regex.search(r["text"]):
            n += 1
            out.append(f"--- p{r['page']}")
            for prev in records[max(0, i - 3):i]:
                out.append(f"    {prev['size']:4.1f}{'B' if prev['bold'] else ' '}  {prev['text'][:70]}")
            out.append(f"  > {r['size']:4.1f}{'B' if r['bold'] else ' '}  {r['text'][:70]}")
    return n, out


def structure_report(pdf_path, book_title):
    """(summary, detail) for a book with a profile: what ingest makes
    of its recipes."""
    records, _, _ = structure_book(pdf_path, book_title)
    recipes = defaultdict(list)
    pages = {}
    for text, content_type, page_num, confirmed, extra in records:
        if content_type == "recipe":
            recipes[extra["recipe_id"]].append((extra["part"], text))
            if extra["part"] == 0:
                pages[extra["recipe_id"]] = page_num if confirmed else 0

    kinds, group_kinds, empty, odd_titles = Counter(), Counter(), [], []
    rejected = defaultdict(list)
    titles = []
    for recipe_id, parts in recipes.items():
        text = "\n".join(t for _, t in sorted(parts))
        entry = index_entry(recipe_id, {"book": book_title, "text": text,
                                        "page": pages[recipe_id], "page_confirmed": True})
        title = f"p{entry['page']} {entry['title']}"
        titles.append(title)
        if not entry["ingredients"]:
            empty.append(title)
        # One-word titles ("Cake") and table cells ("SHEET PAN") are the
        # usual signs a title was taken from the wrong line.
        if len(entry["title"].split()) == 1:
            odd_titles.append(title)
        group_kinds.update(entry["groups"].values())

        def trace(kind, line, title=title):
            kinds[kind] += 1
            if kind == "rejected":
                rejected[title].append(line)
        extract_ingredient_groups(text, strategy_for(book_title), trace=trace)

    summary = [f"recipes: {len(recipes)}  (chunks: {dict(Counter(r[1] for r in records))})",
               f"no ingredients: {len(empty)}   one-word titles: {len(odd_titles)}   "
               f"recipes with rejected lines: {len(rejected)} ({kinds['rejected']} lines)",
               "group kinds: " + (", ".join(f"{k} {v}" for k, v in group_kinds.most_common()) or "none"),
               "line decisions: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common())]
    detail = ["SAMPLE TITLES"] + [f"    {t}" for t in titles[::max(1, len(titles) // 15)]]
    detail += ["", "NO INGREDIENTS"] + [f"    {t}" for t in empty]
    detail += ["", "ONE-WORD TITLES"] + [f"    {t}" for t in odd_titles]
    detail += ["", "REJECTED LINES"]
    for title, lines in rejected.items():
        detail.append(f"    {title}")
        detail.extend(f"        {line[:80]}" for line in lines[:5])
    return summary, detail


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("book", choices=list(BOOK_FILES), metavar="BOOK_TITLE")
    parser.add_argument("--anchor", help="regex for a line that always follows a title")
    args = parser.parse_args()

    pdf_path = book_pdf_path(args.book)
    records, page_starts = build_layout_stream(pdf_path)
    numbered = sum(1 for _, _, confirmed in page_starts if confirmed)
    summary = [f"=== {args.book} ===",
               f"{len(page_starts)} pages with text ({numbered} with a printed number), {len(records)} lines"]
    detail = []

    body, sizes = size_histogram(records)
    larger = sorted({r["size"] for r in records if r["size"] > body + 0.5}, reverse=True)
    summary.append(f"body text {body}pt; larger sizes: {', '.join(map(str, larger[:10])) or 'none'}")
    detail += ["FONT SIZES"] + sizes

    counts, problems = text_problems(records)
    summary.append("text problems: " + (", ".join(f"{k} {v}" for k, v in counts.most_common()) or "none"))
    detail += ["", "TEXT PROBLEMS"] + problems

    if args.anchor:
        n, lines = anchor_report(records, args.anchor)
        summary.append(f"anchor {args.anchor!r}: {n} lines")
        detail += ["", f"ANCHOR {args.anchor!r}"] + lines

    if strategy_for(args.book):
        s, d = structure_report(pdf_path, args.book)
        summary += s
        detail += [""] + d
    else:
        summary.append("no profile in books/ yet, so no recipe structure")

    slug = "".join(c if c.isalnum() else "_" for c in args.book.lower()).strip("_")
    path = os.path.join(REPORT_DIR, f"report_{slug}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary + [""] + detail) + "\n")
    print("\n".join(summary))
    print(f"full report: {path}")


if __name__ == "__main__":
    main()
