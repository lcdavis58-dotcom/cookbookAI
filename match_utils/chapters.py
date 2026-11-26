"""
The chapter each recipe is in ("Snacks & Drinks", "Chapter 1: Salads"),
from the PDF's table of contents (its bookmarks), once, when the recipe
index is built. The dish labels (match_utils/dish_labels.py) use it: a
recipe in a "Small Bites" chapter is an appetizer.

Two ways, since books' tables of contents differ:
    by title    most books list every recipe under its chapter: the
                recipe's chapter is the one its title is listed under
    by page     some list only chapters (How to Cook Everything
                Vegetarian, The Food Lab): the saved extraction
                (ingest_utils/extract.py) shows the page its title is
                printed on, in the largest type, and the chapter is the
                last one starting on or before that page

A chapter is given as up to two headings: the two right above the
recipe's own entry ("Recipes > Salads" in Salt Fat Acid Heat), or the
top two levels for a page ("Part One: Doughs and Batters > Doughs"). Without the PDF there
are no chapters, and the labels go without.
"""

import os
import re

from query_utils.title_lookup import title_tokens

# Headings that are the book's front or back matter, never a chapter.
FRONT_MATTER_RE = re.compile(r"^(?:(?:table of )?contents|copyright|dedication|title page|cover|foreword|preface|"
                             r"introduction|acknowledg|index|about the|also by|other books|praise|epigraph|welcome|"
                             r"navigating|recipe (?:list|matrix)|recipes by|list of|master recipe listing|menus|"
                             r"photo|conversion|nutritional|resources|sources)", re.I)
# How deep a chapter goes: "Part Two" > "Vegetables", no further.
CHAPTER_LEVELS = 2


def _key(text):
    return " ".join(title_tokens(text or ""))


def load_toc(pdf_path):
    """[(level, heading, page)] from the PDF's bookmarks, pages 1-based;
    [] without the PDF or bookmarks."""
    if not os.path.isfile(pdf_path):
        return []
    import pymupdf  # only needed here
    with pymupdf.open(pdf_path) as doc:
        return [(level, " ".join(str(title).split()), page) for level, title, page in doc.get_toc()]


def _path(stack):
    kept = [heading for heading in stack[:CHAPTER_LEVELS] if heading and not FRONT_MATTER_RE.match(heading)]
    return " > ".join(kept)


def chapters_by_title(toc):
    """{title key: chapter} for every entry deeper than a chapter: the
    headings above it."""
    out, stack = {}, []
    for level, heading, _ in toc:
        stack = stack[:level - 1] + [heading]
        if level > 1:
            # The headings right above it: Salt Fat Acid Heat lists its
            # recipes under "Part Two > Recipes > Salads".
            chapter = _path([h for h in stack[:-1] if not FRONT_MATTER_RE.match(h)][-CHAPTER_LEVELS:])
            if chapter:
                out.setdefault(_key(heading), chapter)
    return out


def chapter_at_page(toc, page):
    """The chapter a 1-based page falls in: the heading (to
    CHAPTER_LEVELS deep) that starts latest on or before it. Ebook
    tables of contents aren't always in page order ("Master Recipe
    Listing" on page 1990 listed second), so every entry is looked at."""
    best, stack = None, []
    for level, heading, start in toc:
        if level > CHAPTER_LEVELS:
            continue
        stack = stack[:level - 1] + [heading]
        path = _path(stack)
        if 0 < start <= page and path and (best is None or start >= best[0]):
            best = (start, path)
    return best[1] if best else ""


def title_pages(extraction):
    """{title key: 1-based page} for each line's text, keeping the page
    where it's printed largest (the recipe's own page, not the table of
    contents or the index)."""
    best = {}
    for page in extraction.get("pages", []):
        for line in page.get("lines", []):
            key = _key(line.get("text"))
            if key and (key not in best or line.get("size", 0) > best[key][0]):
                best[key] = (line.get("size", 0), page["index"] + 1)
    return {key: page for key, (_, page) in best.items()}


def find_chapters(entries, toc, extraction=None):
    """{recipe_id: chapter} for one book's index entries."""
    by_title = chapters_by_title(toc)
    pages = title_pages(extraction) if extraction else {}
    out = {}
    for e in entries:
        keys = [k for k in (_key(e.get("title")), _key(e.get("match_title"))) if k]
        chapter = next((by_title[k] for k in keys if k in by_title), "")
        if not chapter:
            # Listed with more after it: "Brown Butter Tart Crust: From Paul ..."
            chapter = next((c for listed, c in by_title.items() for k in keys if listed.startswith(k + " ")), "")
        if not chapter:
            page = next((pages[k] for k in keys if k in pages), None)
            chapter = chapter_at_page(toc, page) if page else ""
        if chapter:
            out[e["recipe_id"]] = chapter
    return out


def add_chapters(entries, log=print):
    """Sets entry["chapter"] on every entry whose chapter can be found
    (needs the PDFs, COOKBOOKS_DIR). Returns how many have one."""
    from common.config import BOOK_FILES, book_pdf_path
    from ingest_utils.extract import extraction_path

    books = {}
    for e in entries:
        books.setdefault(e["book"], []).append(e)
    found = 0
    for book, book_entries in books.items():
        if book not in BOOK_FILES:
            continue
        pdf = book_pdf_path(book)
        toc = load_toc(pdf)
        if not toc:
            continue
        extraction = None
        path = extraction_path(pdf)
        if os.path.isfile(path):
            import json
            with open(path, encoding="utf-8") as f:
                extraction = json.load(f)
        chapters = find_chapters(book_entries, toc, extraction)
        for e in book_entries:
            if e["recipe_id"] in chapters:
                e["chapter"] = chapters[e["recipe_id"]]
        found += len(chapters)
    if found < len(entries):
        log(f"Chapters found for {found} of {len(entries)} recipes (the rest have no PDF or no table of contents).")
    return found
